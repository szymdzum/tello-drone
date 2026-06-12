#!/usr/bin/env python3
"""
drone.py — the single entry point for flying the Tello.

    python drone.py         # FPV (default): live video window + keyboard flight
    python drone.py repl    # raw SDK REPL for protocol debugging (stdlib only)
    python drone.py demo    # scripted square flight (stdlib only)

If the machine isn't already on the Tello's Wi-Fi, drone.py joins the AP
automatically when it's broadcasting (--ssid to override, empty to disable).
FPV needs opencv-python (+ optionally `av` for lower-latency decode); repl/demo
run on the stdlib alone.
"""
import argparse

from tello_app.flightlog import NullLog, open_session_log
from tello_app.tello import Tello, TelloError
from tello_app.util import DEFAULT_SSID, ensure_on_tello, warn_if_awdl_active


def main() -> None:
    ap = argparse.ArgumentParser(description="Fly the Tello.")
    ap.add_argument("mode", nargs="?", choices=("fpv", "repl", "demo"), default="fpv",
                    help="fpv = video + keyboard flight (default); "
                         "repl = raw SDK commands; demo = scripted square")
    ap.add_argument("--ssid", default=DEFAULT_SSID,
                    help=f"Tello Wi-Fi to auto-join when not already on it "
                         f"(default {DEFAULT_SSID}; empty to disable)")
    ap.add_argument("--no-log", action="store_true",
                    help="disable the JSONL flight recorder (logs/)")
    args = ap.parse_args()
    mode = args.mode

    # Import the shell before touching the network so a missing cv2 fails fast,
    # and lazily so repl/demo stay stdlib-only.
    if mode == "fpv":
        from tello_app.shells import fpv as shell
        run = shell.run
    else:
        from tello_app.shells import repl
        run = repl.run_demo if mode == "demo" else repl.run_interactive

    warn_if_awdl_active()
    if not ensure_on_tello(args.ssid):
        print(f"Couldn't join {args.ssid or 'the Tello Wi-Fi'} — drone powered on? "
              "Trying to connect anyway...")
    log = NullLog() if args.no_log else open_session_log()
    if log.path:
        print(f"Flight log: {log.path}")
    print("Connecting to Tello...")
    drone = Tello(log=log)  # drone.close() also closes the log
    try:
        drone.connect(retries=3)
        drone.start_keepalive()  # ground-only — keeps a parked drone awake
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
