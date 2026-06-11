#!/usr/bin/env python3
"""
keyboard_control.py — fly the Tello live from the keyboard (curses, stdlib only).

Real-time RC control: each key sets a velocity on one axis and a ~20 Hz loop
streams `rc` to the drone, so motion is smooth and the continuous traffic also
keeps the drone from idle-timing-out. Release a key and that axis coasts back to
a hover within HOLD_S.

Connect your machine to the Tello Wi-Fi, then:
    python keyboard_control.py

Controls:
    movement     W / S  forward / back     A / D  left / right
    altitude     ↑ / ↓  up / down
    yaw          ← / →  turn left / right
    t takeoff    l land    f flip (forward)    x hover (zero velocities)
    SPACE        EMERGENCY stop — cuts motors, the drone DROPS
    - / =        slower / faster             q  quit (lands first)

Built on tello.py and stdlib only, so it's yours to modify. The flight logic
lives in FlightController (pure, unit-tested); curses is just the I/O shell.
"""
import curses
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tello import Tello, TelloError

RATE_S = 0.05      # rc send period (~20 Hz)
HOLD_S = 0.5       # how long an axis stays active after its last keypress.
                   # Must exceed your terminal's key-autorepeat gap or motion
                   # stutters; larger = more coast after release. Tune to taste.
SPEED_MIN, SPEED_MAX, SPEED_STEP = 10, 100, 10

# Default curses scheme (WASD + arrows). Other shells (e.g. fpv.py) pass their
# own maps into FlightController.
# movement key -> (velocity axis, sign). curses.KEY_* are import-time constants.
MOVES = {
    ord("w"): ("fb", +1), ord("s"): ("fb", -1),
    ord("d"): ("lr", +1), ord("a"): ("lr", -1),
    curses.KEY_UP: ("ud", +1), curses.KEY_DOWN: ("ud", -1),
    curses.KEY_RIGHT: ("yaw", +1), curses.KEY_LEFT: ("yaw", -1),
}
# discrete key -> action name handled by handle_key / _do_action.
DISCRETES = {
    ord("t"): "takeoff", ord("T"): "takeoff",
    ord("l"): "land", ord("L"): "land",
    ord("f"): "flip", ord("F"): "flip",
    ord(" "): "emergency",
    ord("q"): "quit", ord("Q"): "quit",
    ord("x"): "hover", ord("X"): "hover",
    ord("-"): "speed_down", ord("_"): "speed_down",
    ord("="): "speed_up", ord("+"): "speed_up",
}


class FlightController:
    """Pure control state: maps keypresses to per-axis velocities. Knows nothing
    about curses or the drone, so it can be unit-tested. The curses loop feeds it
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
            return "takeoff unconfirmed — assuming airborne; land with l/g"
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
        except TelloError:
            return "flip rejected (needs > 50% battery)"
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


def warn_if_awdl_active() -> None:
    """macOS AWDL (AirDrop/AirPlay) hops the Wi-Fi radio to 5 GHz every ~1 s,
    stalling UDP for 50-100 ms bursts — enough to drop rc/command packets to the
    Tello. Take it down automatically if the passwordless sudoers rule is
    installed; otherwise tell the pilot exactly what to run."""
    try:
        out = subprocess.run(["ifconfig", "awdl0"],
                             capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return
    if "status: active" not in out:
        return
    # Non-interactive sudo: succeeds silently if /etc/sudoers.d/awdl exists,
    # fails fast (no password prompt) if it doesn't.
    try:
        r = subprocess.run(["sudo", "-n", "/sbin/ifconfig", "awdl0", "down"],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            print("✓ AWDL (AirDrop) taken down for a cleaner drone link.")
            return
    except Exception:
        pass
    print("⚠ macOS AWDL (AirDrop/AirPlay) is ACTIVE — it stalls Wi-Fi every ~1 s.")
    print("  Take it down for this session:")
    print("    sudo ifconfig awdl0 down")
    print("  One-time setup so these scripts can do it automatically, no password:")
    print("    echo \"$USER ALL=(ALL) NOPASSWD: /sbin/ifconfig awdl0 down\" | sudo tee /etc/sudoers.d/awdl")


def _say(stdscr, y: int, x: int, text: str) -> None:
    """addstr that won't crash on a too-small terminal."""
    try:
        stdscr.addstr(y, x, text)
    except curses.error:
        pass


def _draw_hud(stdscr, drone: Tello, fc: FlightController, status: str,
              rc: tuple[int, int, int, int]) -> None:
    st = drone.state
    stdscr.erase()
    _say(stdscr, 0, 0, "TELLO KEYBOARD CONTROL")
    _say(stdscr, 2, 0, f"  battery {st.get('bat', '?')}%   "
                       f"height {st.get('h', '?')}cm   temp {st.get('temph', '?')}C")
    _say(stdscr, 3, 0, f"  flying: {fc.flying}    speed: {fc.speed}")
    _say(stdscr, 4, 0, f"  rc -> lr={rc[0]:+d} fb={rc[1]:+d} ud={rc[2]:+d} yaw={rc[3]:+d}")
    _say(stdscr, 6, 0, f"  status: {status}")
    _say(stdscr, 8, 0, "  W/S fwd/back   A/D left/right   arrows up/down + yaw")
    _say(stdscr, 9, 0, "  t takeoff   l land   f flip   x hover   -/= speed")
    _say(stdscr, 10, 0, "  SPACE = EMERGENCY (drops!)        q = quit")
    stdscr.refresh()


def fly(stdscr, drone: Tello) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    fc = FlightController()
    runner = ActionRunner(drone, fc)
    runner.last_result = "connected — press 't' to take off"
    last_heartbeat = 0.0

    try:
        while True:
            now = time.time()
            # Drain every key buffered this frame; last discrete action wins.
            action = None
            while True:
                key = stdscr.getch()
                if key == -1:
                    break
                a = fc.handle_key(key, now)
                if a:
                    action = a
            if action == "quit":
                break
            if action:
                runner.submit(action)  # never blocks; worker thread executes
            status = runner.display()

            lr, fb, ud, yaw = fc.tick(now)
            if fc.flying:
                drone.send_rc(lr, fb, ud, yaw)  # stream joystick only while airborne
            elif now - last_heartbeat > 2.0:
                # Slow heartbeat keeps the link awake on the ground without
                # flooding the command channel around takeoff/land/flip.
                drone.send_rc(0, 0, 0, 0)
                last_heartbeat = now
            _draw_hud(stdscr, drone, fc, status, (lr, fb, ud, yaw))
            time.sleep(RATE_S)
    finally:
        # Guarantee a safe landing if we were airborne.
        if fc.flying:
            try:
                drone.send_rc(0, 0, 0, 0)
                drone.land()
            except TelloError:
                pass


def main() -> None:
    warn_if_awdl_active()
    print("Connecting to Tello (be on its Wi-Fi)...")
    drone = Tello()
    try:
        drone.connect(retries=3)
        print("Connected — launching keyboard control...")
        time.sleep(0.5)
        curses.wrapper(fly, drone)
    except TelloError as e:
        print(f"Connection failed: {e}")
        print("On the Tello Wi-Fi? Drone powered on?")
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        drone.close()
    print("Landed and disconnected.")


if __name__ == "__main__":
    main()
