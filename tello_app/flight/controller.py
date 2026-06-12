"""
flight/controller.py — the flight "brain" for the live controller.

The control scheme (keymap), the velocity model, drone-command execution, and the
non-blocking command runner all live here; the FPV shell is a thin I/O layer over
this module. Depends only on tello.py: no cv2, fully unit-testable.

Key scheme:
    W/S forward/back   A/D strafe l/r   I/K up/down (throttle)   J/L yaw l/r
    t takeoff · g land · f flip · h hover · y/u slower/faster
    p follow face · m marker hold · SPACE emergency · Esc/q quit
"""
import threading
import time

from tello_app.tello import Tello, TelloError, TelloTimeout

RATE_S = 0.05      # rc send period (~20 Hz)
HOLD_S = 0.5       # how long an axis stays active after its last keypress.
                   # Must exceed the terminal/OS key-autorepeat gap or motion
                   # stutters; larger = more coast after release. Tune to taste.
SPEED_MIN, SPEED_MAX, SPEED_STEP = 10, 100, 10

# movement key -> (velocity axis, sign):
#   WASD = horizontal (forward/back, strafe), IJKL = up/down + yaw.
MOVES = {
    ord("w"): ("fb", +1), ord("s"): ("fb", -1),     # forward / back
    ord("a"): ("lr", -1), ord("d"): ("lr", +1),     # strafe left / right
    ord("i"): ("ud", +1), ord("k"): ("ud", -1),     # up / down (throttle)
    ord("j"): ("yaw", -1), ord("l"): ("yaw", +1),   # yaw left / right
}
# discrete key -> action name handled by handle_key / _do_action.
DISCRETES = {
    ord("t"): "takeoff", ord("T"): "takeoff",
    ord("g"): "land", ord("G"): "land",
    ord("f"): "flip", ord("F"): "flip",
    ord("h"): "hover", ord("H"): "hover",
    ord("y"): "speed_down", ord("Y"): "speed_down",
    ord("u"): "speed_up", ord("U"): "speed_up",
    ord("p"): "follow", ord("P"): "follow",
    ord("m"): "marker", ord("M"): "marker",
    ord("c"): "snapshot", ord("C"): "snapshot",  # save a raw camera frame (shell-side)
    ord(" "): "emergency",
    27: "quit",                          # Esc
    ord("q"): "quit", ord("Q"): "quit",  # q alias (easy reach; Esc can be fiddly)
}


class FlightController:
    """Pure control state: maps keypresses to per-axis velocities. Knows nothing
    about curses, cv2, or the drone, so it can be unit-tested. A shell feeds it
    keys and executes the discrete 'actions' it returns against a Tello."""

    def __init__(self, speed: int = 40,
                 moves: dict[int, tuple[str, int]] | None = None,
                 discretes: dict[int, str] | None = None) -> None:
        self.speed = speed
        self.moves = moves if moves is not None else MOVES
        self.discretes = discretes if discretes is not None else DISCRETES
        self.vel = {"lr": 0, "fb": 0, "ud": 0, "yaw": 0}
        self._last = {"lr": 0.0, "fb": 0.0, "ud": 0.0, "yaw": 0.0}
        self.flying = False
        self.landing = False    # a commanded landing is in progress: steering frozen
        self.emergency = False  # motors were cut; cleared by the next takeoff
        # Autopilot mode: None (manual), "follow" (face), "marker" (ArUco hold).
        # A tracker steers instead of keys; modes are mutually exclusive.
        self.autopilot: str | None = None

    @property
    def follow(self) -> bool:
        """Back-compat view of autopilot. Setting False clears ANY autopilot —
        which is what every safety clearing site (land/emergency/crash) wants."""
        return self.autopilot == "follow"

    @follow.setter
    def follow(self, value: bool) -> None:
        self.autopilot = "follow" if value else None

    def handle_key(self, key: int, now: float) -> str | None:
        """Process one key. Returns a discrete action string (takeoff/land/flip/
        emergency/quit) for the shell to execute, or None for movement and
        local-only keys (hover, speed)."""
        if key in self.moves:
            if self.landing:
                return None  # no steering during a commanded landing
            self.autopilot = None  # any stick input = instant manual override
            axis, sign = self.moves[key]
            self.vel[axis] = sign * self.speed
            self._last[axis] = now
            return None
        action = self.discretes.get(key)
        if action in ("follow", "marker"):
            # Toggle; engaging one replaces the other (mutually exclusive).
            self.autopilot = None if self.autopilot == action else action
            if self.autopilot:
                self.hover()  # hand over from zero, not from a held key's velocity
            return None
        if action == "hover":
            self.autopilot = None
            self.hover()
            return None
        if action == "speed_down":
            self.speed = max(SPEED_MIN, self.speed - SPEED_STEP)
            return None
        if action == "speed_up":
            self.speed = min(SPEED_MAX, self.speed + SPEED_STEP)
            return None
        return action

    def hover(self) -> None:
        """Zero every axis immediately (hover in place)."""
        for axis in self.vel:
            self.vel[axis] = 0

    def tick(self, now: float) -> tuple[int, int, int, int]:
        """Decay any axis whose key hasn't been refreshed within HOLD_S, then
        return the (lr, fb, ud, yaw) velocities to stream. Forced to zero
        while landing — non-zero rc mid-descent can abort the landing."""
        if self.landing:
            self.hover()
            return (0, 0, 0, 0)
        for axis, v in self.vel.items():
            if v and now - self._last[axis] > HOLD_S:
                self.vel[axis] = 0
        return self.vel["lr"], self.vel["fb"], self.vel["ud"], self.vel["yaw"]


FLIP_ROLL_DEG = 120  # inverted-on-the-ground territory (real crash read 179)
FLIP_HOLD_S = 1.0    # inversion must be SUSTAINED: a mid-air tumble the
                     # firmware recovers from transits >120 deg for <1 s, and
                     # firing on it cut the rc stream mid-flight (the runaway
                     # drift incident) — a drone lying on its back stays there
DOWN_HOLD_S = 3.0    # grounded-looking telemetry this long -> show the DOWN? hint


class CrashMonitor:
    """Reconciles the controller's airborne belief with telemetry after a crash
    (the 'HUD said AIRBORNE while it sat on the floor' incident).

    Two signals, deliberately different strengths:
      - flip: |roll| >= FLIP_ROLL_DEG sustained FLIP_HOLD_S in FRESH telemetry —
        a drone lying on its back, not a transient tumble. update() clears
        fc.flying (re-arming 't'); the CALLER must also submit a land: if the
        detector is ever wrong again, the failure mode must be 'drone lands',
        never 'rc stream silently stops' (the runaway drift incident).
      - down_hint(): h == 0 and zero velocity sustained DOWN_HOLD_S while we
        still believe airborne. DISPLAY-ONLY: baro/VPS can misread, and a false
        'landed' abandons a flying drone (see _do_action). The pilot resyncs
        with 'g'.
    """

    def __init__(self) -> None:
        self._down_since: float | None = None
        self._flip_since: float | None = None

    def update(self, drone: Tello, fc: FlightController, now: float) -> str | None:
        """Call once per control tick. Returns a status string when the flip
        rule fires (after clearing fc.flying); otherwise None."""
        if not fc.flying:
            self._down_since = None
            self._flip_since = None
            return None
        if drone.state_age() > 1.0:
            self._down_since = None  # blind: assume nothing
            self._flip_since = None
            return None
        st = drone.state
        roll = st.get("roll", 0)
        inverted = isinstance(roll, (int, float)) and abs(roll) >= FLIP_ROLL_DEG
        if inverted:
            if self._flip_since is None:
                self._flip_since = now
            if now - self._flip_since >= FLIP_HOLD_S:
                fc.flying = False
                fc.follow = False
                fc.hover()
                self._down_since = None
                self._flip_since = None
                return "CRASHED - flipped (t to relaunch)"
        else:
            self._flip_since = None
        still = (st.get("h") == 0 and st.get("vgx") == 0
                 and st.get("vgy") == 0 and st.get("vgz") == 0)
        if still:
            if self._down_since is None:
                self._down_since = now
        else:
            self._down_since = None
        return None

    def down_hint(self, now: float) -> bool:
        """True when telemetry has looked grounded for DOWN_HOLD_S while the
        controller still believes airborne."""
        return self._down_since is not None and now - self._down_since >= DOWN_HOLD_S


def _try_land(drone: Tello) -> bool:
    """Land, retrying once with a short timeout. A long block while descending is
    bad, and the Tello sometimes replies 'error' yet still settles."""
    for _ in range(2):
        try:
            drone.send_command("land", timeout=7)
            return True
        except TelloError:
            continue
    return False


def _do_action(drone: Tello, fc: FlightController, action: str) -> str:
    """Execute a discrete command. Returns a short status string for the HUD.

    SAFETY-CRITICAL: takeoff sets `flying` *before* sending the command and keeps
    it set even if the reply never arrives. The drone climbs the instant it gets
    `takeoff`, so if the `ok` is lost (common once the video stream congests the
    Wi-Fi) we must still treat it as airborne — otherwise the loop stops streaming
    rc and the drone drifts with no control. A false 'airborne' is harmless (rc to
    a grounded drone does nothing); a false 'landed' abandons a flying drone."""
    if action == "takeoff":
        if fc.flying:
            return "already airborne"
        fc.hover()  # so a held key can't fling it the instant it lifts
        fc.flying = True  # assume airborne even if the ok reply is lost
        fc.emergency = False  # a new takeoff re-arms after a motor cut
        fc.follow = False  # every flight starts under manual control
        try:
            drone.send_command("takeoff", timeout=7)
            return "airborne"
        except TelloTimeout:
            # Reply lost — the drone may well be climbing. Keep flying=True:
            # a false 'landed' abandons an airborne drone.
            return "takeoff unconfirmed — assuming airborne; land with g"
        except TelloError:
            # Explicit 'error' reply: the drone REFUSED (IMU upset after a
            # crash, tilted surface, overheat). It is definitively grounded —
            # leaving flying=True here ate the pilot's retries as 'already
            # airborne' (2026-06-12 refused-takeoff incident).
            fc.flying = False
            return "takeoff refused — power-cycle on a flat surface"
    if action == "land":
        fc.landing = True  # also set here for direct callers
        fc.follow = False  # the tracker must not steer a descending drone
        fc.hover()
        try:
            drone.send_rc(0, 0, 0, 0)
            landed = _try_land(drone)
        finally:
            # Even if the socket dies mid-land, steering must not stay frozen.
            fc.flying = False
            fc.landing = False
        return "landed" if landed else "land sent — verify the drone is down"
    if action == "flip":
        if not fc.flying:
            return "can't flip — not flying"
        try:
            drone.flip("f")
            return "flip!"
        except TelloError as e:
            return f"flip rejected: {e}"
    if action == "emergency":
        for _ in range(3):  # burst — emergency packets get dropped on a busy link
            try:
                drone.emergency()
            except OSError:  # raw sendto: only the socket can fail (e.g. closing)
                break
        fc.flying = False
        fc.landing = False
        fc.emergency = True
        fc.follow = False
        fc.hover()
        return "EMERGENCY STOP"
    return ""


class ActionRunner:
    """Executes discrete drone commands (takeoff/land/flip) on a worker thread so
    the control loop NEVER blocks — rc keeps streaming and the UI stays live even
    while a command waits up to 7 s for its (possibly lost) reply. This is the
    fix for the FPV crash: a blocked loop meant no rc, no HUD, no emergency.

    One pending slot, latest-wins — except 'land' is sticky while pending OR
    executing (only another land gets through; a stray key must not cancel a
    landing, nor queue a takeoff that would relaunch the drone on touchdown).
    'emergency' never queues: it is fire-and-forget, so it runs inline."""

    def __init__(self, drone: Tello, fc: FlightController) -> None:
        self._drone = drone
        self._fc = fc
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._pending: str | None = None
        self.busy_with: str | None = None
        self.last_result = ""
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, action: str) -> None:
        if action == "emergency":
            with self._lock:
                self._pending = None  # an emergency overrides anything queued
            self.last_result = _do_action(self._drone, self._fc, action)
            self._drone.log.event("action", action=action, result=self.last_result)
            return
        with self._lock:
            landing = self._pending == "land" or self.busy_with == "land"
            if landing and action != "land":
                return  # a stray key must not cancel (or queue behind) a landing
            if action == "land":
                self._fc.landing = True  # freeze steering now, not when the worker gets to it
            self._pending = action
            self._wake.set()

    def display(self) -> str:
        """One status line for the HUD: what's running / queued / last result."""
        busy, pending = self.busy_with, self._pending
        if busy:
            return f"{busy}..." + (f" (then: {pending})" if pending else "")
        return self.last_result

    def wait_idle(self, timeout: float) -> bool:
        """Block until nothing is pending or executing (or timeout). Lets the
        FPV quit path drain the worker and land through the same code path as
        pressing 'g', instead of racing it with a direct _do_action call."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._pending is None and self.busy_with is None:
                    return True
            time.sleep(0.05)
        return False

    def _worker(self) -> None:
        while True:
            self._wake.wait()
            with self._lock:
                action = self._pending
                self._pending = None
                self._wake.clear()
                self.busy_with = action
            try:
                result = _do_action(self._drone, self._fc, action) if action else ""
            except Exception as e:
                # A dead worker would silently hang every later action.
                result = f"{action} failed: {e}"
            with self._lock:
                self.busy_with = None
                if action:
                    self.last_result = result
            if action:
                self._drone.log.event("action", action=action, result=result)
