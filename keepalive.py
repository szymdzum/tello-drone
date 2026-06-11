#!/usr/bin/env python3
"""
keepalive.py — connect to the Tello fast and keep it awake.

The Tello powers itself off after a few minutes of inactivity (and, while
flying, auto-lands after 15 s of silence). This script brings up an SDK
session quickly and then sends a lightweight `battery?` every few seconds so
the drone stays awake and ready. It waits for the drone if it isn't up yet,
and auto-recovers from transient packet drops / brief link losses.

Usage:
    python keepalive.py                 # hold awake, ~8 s heartbeat
    python keepalive.py --interval 5    # faster heartbeat
    python keepalive.py --quiet         # only print battery changes + problems

Requirements:
    - Host must be on the Tello Wi-Fi (en0 = 192.168.10.x). Internet can ride a
      separate wired adapter so you don't lose it (see CLAUDE.md / memory).
    - Stdlib only. Ctrl-C to stop.

Note: this owns the command port (8889) while running. Stop it before running
drone.py — it sends its own commands and keeps the drone awake on its own.
"""
import argparse
import sys
import time

from tello_app.tello import Tello, TelloError
from tello_app.util import DEFAULT_SSID, ensure_on_tello


def connect_fast(ssid: str, quiet: bool) -> Tello:
    """Bring up an SDK session, waiting (and retrying) until the drone answers."""
    while True:
        ensure_on_tello(ssid, quiet)
        drone = Tello()
        drone.RESPONSE_TIMEOUT = 3  # short per-try timeout = fast feedback
        try:
            drone.connect(retries=2)
            return drone
        except TelloError as e:
            drone.close()
            if not quiet:
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] drone not ready yet ({e}); retrying...", flush=True)
            time.sleep(2)


def keepalive(drone: Tello, interval: float, quiet: bool, ssid: str) -> None:
    """Ping every `interval` s to keep the drone awake.

    Returns when the link is unrecoverable on the current socket (so the caller
    can do a full reconnect). On a few misses it re-joins the Tello AP if the
    Mac roamed, then re-enters SDK mode.
    """
    last_batt = None
    misses = 0
    while True:
        ts = time.strftime("%H:%M:%S")
        try:
            batt = int(drone.send_command("battery?", timeout=3))
            misses = 0
            if not quiet or batt != last_batt:
                warn = "  ⚠ LOW — land/charge soon" if batt <= 15 else ""
                print(f"[{ts}] awake — battery {batt}%{warn}", flush=True)
                last_batt = batt
        except (TelloError, ValueError):
            misses += 1
            print(f"[{ts}] no response ({misses})", flush=True)
            if misses >= 6:
                # Give up on this socket; caller will rebuild the connection
                # (and re-join the AP) from scratch.
                print(f"[{ts}] link lost — full reconnect...", flush=True)
                return
            if misses >= 3:
                # Most common cause: en0 roamed off the Tello. Rejoin, then
                # re-enter SDK mode on the same socket.
                ensure_on_tello(ssid, quiet)
                try:
                    drone.send_command("command", timeout=3)
                    misses = 0
                    print(f"[{ts}] session restored", flush=True)
                except TelloError:
                    print(f"[{ts}] still down — will keep trying", flush=True)
        time.sleep(interval)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Connect to the Tello and keep it awake (prevent idle power-off)."
    )
    ap.add_argument(
        "--interval", type=float, default=8.0,
        help="seconds between keepalive pings (default 8; must be < 15)",
    )
    ap.add_argument(
        "--quiet", action="store_true",
        help="only print battery changes and problems",
    )
    ap.add_argument(
        "--ssid", default=DEFAULT_SSID,
        help=f"Tello Wi-Fi SSID to auto-rejoin on roam (default {DEFAULT_SSID}; "
             f"empty to disable auto-rejoin)",
    )
    args = ap.parse_args()

    if args.interval >= Tello.SAFETY_TIMEOUT:
        print(f"interval must be < {Tello.SAFETY_TIMEOUT} s "
              "(the Tello auto-lands after that long without a command).")
        sys.exit(1)

    print(
        f"Connecting to Tello (auto-rejoin {args.ssid or 'OFF'}) — internet should "
        f"be on a separate wired adapter...",
        flush=True,
    )
    try:
        while True:  # reconnect loop — survives roams and link drops
            drone = connect_fast(args.ssid, args.quiet)
            try:
                batt = drone.get_battery()
                print(
                    f"✓ Connected. Battery {batt}%. "
                    f"Holding awake every {args.interval:.0f}s — Ctrl-C to stop.",
                    flush=True,
                )
                keepalive(drone, args.interval, args.quiet, args.ssid)
            finally:
                drone.close()
    except KeyboardInterrupt:
        print("\nStopping keepalive.")


if __name__ == "__main__":
    main()
