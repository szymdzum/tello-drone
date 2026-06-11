"""
shells/repl.py — raw SDK access for protocol debugging, plus a scripted demo.

Modes (launch via drone.py):
  python drone.py repl  – type SDK commands directly (e.g. "takeoff", "forward 50")
  python drone.py demo  – take off, fly a small square, land

Stdlib only — no cv2 needed.
"""

import time

from tello_app.tello import Tello, TelloError

HELP_TEXT = """
Available commands (type directly):
  command      – enter SDK mode (done automatically on connect)
  takeoff      – auto take off
  land         – auto land
  emergency    – kill all motors immediately

  up/down/left/right/forward/back <cm>   – move (20–500 cm)
  cw/ccw <degrees>                        – rotate (1–360°)
  flip <l|r|f|b>                          – flip in direction
  go <x> <y> <z> <speed>                 – fly to coordinates
  rc <lr> <fb> <ud> <yaw>                – joystick control

  speed <cm/s>     – set speed (10–100)
  battery?         – get battery level
  speed?           – get current speed
  height?          – get height
  temp?            – get temperature
  time?            – get flight time
  wifi?            – get Wi-Fi SNR
  sn?              – get serial number

  state            – show latest telemetry
  help             – show this help
  quit / exit      – land (if flying) and disconnect

Note: while AIRBORNE the drone auto-lands after ~15s without a command —
that failsafe is deliberately left armed. While parked, drone.py keeps the
link alive automatically, so take your time between commands on the ground.
"""


def run_interactive(drone: Tello) -> None:
    """Interactive REPL: type any Tello SDK command."""
    print(HELP_TEXT)
    flying = False

    while True:
        try:
            cmd = input("tello> ").strip()
        except (EOFError, KeyboardInterrupt):
            cmd = "quit"

        if not cmd:
            continue

        if cmd in ("quit", "exit"):
            if flying:
                print("Landing before exit...")
                try:
                    drone.land()
                except TelloError as e:
                    print(f"  Land error: {e}")
            break

        if cmd == "help":
            print(HELP_TEXT)
            continue

        if cmd == "state":
            state = drone.state
            if state:
                for k, v in state.items():
                    print(f"  {k}: {v}")
            else:
                print("  No state data received yet.")
            continue

        # Fire-and-forget commands: the drone sends no reply, so routing these
        # through send_command would block until timeout. Call the dedicated
        # methods that sendto() without waiting.
        if cmd == "emergency":
            drone.emergency()
            flying = False
            continue

        if cmd.split()[0] == "rc":
            parts = cmd.split()
            if len(parts) != 5:
                print("  Usage: rc <lr> <fb> <ud> <yaw>  (each -100..100)")
                continue
            try:
                lr, fb, ud, yaw = (int(p) for p in parts[1:])
            except ValueError:
                print("  rc values must be integers (-100..100)")
                continue
            drone.send_rc(lr, fb, ud, yaw)
            continue

        # Send raw command to drone
        try:
            response = drone.send_command(cmd, timeout=20 if cmd in ("takeoff", "land") else 10)
            print(f"  → {response}")

            if cmd == "takeoff":
                flying = True
            elif cmd == "land":
                flying = False
        except TelloError as e:
            print(f"  ✗ {e}")


def run_demo(drone: Tello) -> None:
    """Scripted demo: take off, fly a small square, land."""
    print("\n── Demo flight: small square pattern ──\n")

    battery = drone.get_battery()
    print(f"Battery: {battery}%")
    if battery < 20:
        print("Battery too low for demo. Aborting.")
        return

    drone.takeoff()
    # Once airborne, always attempt to land — even if a move command fails
    # mid-square (close() only shuts sockets, it does NOT land the drone).
    try:
        time.sleep(2)

        side = 50  # cm
        for i in range(4):
            print(f"  Side {i + 1}/4: forward {side}cm, rotate 90° CW")
            drone.forward(side)
            time.sleep(1)
            drone.cw(90)
            time.sleep(1)
    finally:
        drone.land()
    print("\n── Demo complete ──")
