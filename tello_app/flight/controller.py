"""
flight/controller.py — the flight "brain" for the live controller.

The control scheme (keymap), the velocity model, drone-command execution, and the
non-blocking command runner all live here; the FPV shell is a thin I/O layer over
this module. Depends only on tello.py: no cv2, fully unit-testable.

Key scheme:
    W/S forward/back   A/D strafe l/r   I/K up/down (throttle)   J/L yaw l/r
    t takeoff · g land · f flip · h hover · y/u slower/faster
    SPACE emergency · Esc/q quit
"""
import threading

from tello_app.tello import Tello, TelloError

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

    def handle_key(self, key: int, now: float) -> str | None:
        """Process one key. Returns a discrete action string (takeoff/land/flip/
        emergency/quit) for the shell to execute, or None for movement and
        local-only keys (hover, speed)."""
        if key in self.moves:
            axis, sign = self.moves[key]
            self.vel[axis] = sign * self.speed
            self._last[axis] = now
            return None
        action = self.discretes.get(key)
        if action == "hover":
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
        return the (lr, fb, ud, yaw) velocities to stream."""
        for axis, v in self.vel.items():
            if v and now - self._last[axis] > HOLD_S:
                self.vel[axis] = 0
        return self.vel["lr"], self.vel["fb"], self.vel["ud"], self.vel["yaw"]


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
        try:
            drone.send_command("takeoff", timeout=7)
            return "airborne"
        except TelloError:
            return "takeoff unconfirmed — assuming airborne; land with g"
    if action == "land":
        drone.send_rc(0, 0, 0, 0)
        landed = _try_land(drone)
        fc.flying = False
        fc.hover()
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
            except TelloError:
                pass
        fc.flying = False
        fc.hover()
        return "EMERGENCY STOP"
    return ""


class ActionRunner:
    """Executes discrete drone commands (takeoff/land/flip) on a worker thread so
    the control loop NEVER blocks — rc keeps streaming and the UI stays live even
    while a command waits up to 7 s for its (possibly lost) reply. This is the
    fix for the FPV crash: a blocked loop meant no rc, no HUD, no emergency.

    One pending slot, latest-wins — except a pending 'land' is sticky (only
    another land may replace it; a stray key must not cancel a landing).
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
            return
        with self._lock:
            if self._pending == "land" and action != "land":
                return  # don't let a stray key cancel a requested landing
            self._pending = action
            self._wake.set()

    def display(self) -> str:
        """One status line for the HUD: what's running / queued / last result."""
        busy, pending = self.busy_with, self._pending
        if busy:
            return f"{busy}..." + (f" (then: {pending})" if pending else "")
        return self.last_result

    def _worker(self) -> None:
        while True:
            self._wake.wait()
            with self._lock:
                action = self._pending
                self._pending = None
                self._wake.clear()
                self.busy_with = action
            result = _do_action(self._drone, self._fc, action) if action else ""
            with self._lock:
                self.busy_with = None
                if action:
                    self.last_result = result
