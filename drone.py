#!/usr/bin/env python3
"""
drone.py — the single entry point for flying the Tello.

    python drone.py         # FPV (default): live video window + keyboard flight
    python drone.py repl    # raw SDK REPL for protocol debugging (stdlib only)
    python drone.py demo    # scripted square flight (stdlib only)

Connect your machine to the Tello Wi-Fi (TELLO-XXXXXX) first. FPV needs
opencv-python (+ optionally `av` for lower-latency decode); repl/demo run on
the stdlib alone.
"""
import argparse

from tello_app.tello import Tello, TelloError
from tello_app.util import warn_if_awdl_active


def main() -> None:
    ap = argparse.ArgumentParser(description="Fly the Tello.")
    ap.add_argument("mode", nargs="?", choices=("fpv", "repl", "demo"), default="fpv",
                    help="fpv = video + keyboard flight (default); "
                         "repl = raw SDK commands; demo = scripted square")
    mode = ap.parse_args().mode

    # Import the shell before touching the network so a missing cv2 fails fast,
    # and lazily so repl/demo stay stdlib-only.
    if mode == "fpv":
        from tello_app.shells import fpv as shell
        run = shell.run
    else:
        from tello_app.shells import repl
        run = repl.run_demo if mode == "demo" else repl.run_interactive

    warn_if_awdl_active()
    print("Connecting to Tello (be on its Wi-Fi)...")
    drone = Tello()
    try:
        drone.connect(retries=3)
        print(f"Battery: {drone.get_battery()}%")
        run(drone)
    except TelloError as e:
        print(f"Tello error: {e}")
        print("On the Tello Wi-Fi? Drone powered on?")
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        drone.close()
    print("Disconnected.")


if __name__ == "__main__":
    main()
