#!/usr/bin/env python3
"""
Tello system diagnostic.

Queries all available telemetry, runs a low-speed motor spin test,
and reports findings. Useful for detecting disconnected motors or
hardware issues.
"""

import time
from tello import Tello, TelloError


def section(title: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


def query_safe(drone: Tello, label: str, command: str) -> str:
    """Send a read command, return result or "" on failure."""
    try:
        result = drone.send_command(command)
        # send_command only raises on responses prefixed "error"; the Tello
        # also rejects unsupported reads with "unknown command: ...", which
        # would otherwise be printed as if it were a real value.
        low = result.lower()
        if "unknown command" in low or "error" in low:
            print(f"  {label:.<30} N/A ({result})")
            return ""
        print(f"  {label:.<30} {result}")
        return result
    except TelloError as e:
        print(f"  {label:.<30} FAILED ({e})")
        return ""


def run_diagnostic(drone: Tello) -> None:
    # ── 1. Basic info ───────────────────────────────────────
    section("1. DEVICE INFO")
    query_safe(drone, "Serial number", "sn?")
    query_safe(drone, "SDK version", "sdk?")
    query_safe(drone, "Hardware", "hardware?")

    # ── 2. Power ────────────────────────────────────────────
    section("2. POWER")
    battery = query_safe(drone, "Battery %", "battery?")
    if battery.isdigit():
        level = int(battery)
        if level < 10:
            print("  ⚠️  CRITICAL: Battery critically low!")
        elif level < 20:
            print("  ⚠️  WARNING: Battery too low for flight")
        else:
            print(f"  ✓ Battery OK")

    # ── 3. Sensors / Environment ────────────────────────────
    section("3. SENSORS")
    query_safe(drone, "Temperature", "temp?")
    query_safe(drone, "Barometer height", "baro?")  # SDK 1.3 via state
    query_safe(drone, "Height", "height?")
    query_safe(drone, "TOF distance", "tof?")
    query_safe(drone, "Wi-Fi SNR", "wifi?")
    query_safe(drone, "Speed setting", "speed?")

    # ── 4. Telemetry state ──────────────────────────────────
    section("4. TELEMETRY STATE (live)")
    # Give the state receiver a moment to collect data
    time.sleep(1.5)
    state = drone.state
    if state:
        imu_keys = ["pitch", "roll", "yaw"]
        accel_keys = ["agx", "agy", "agz"]
        vel_keys = ["vgx", "vgy", "vgz"]
        temp_keys = ["templ", "temph"]
        other_keys = ["tof", "h", "bat", "baro", "time"]

        for group_name, keys in [
            ("IMU orientation", imu_keys),
            ("Acceleration", accel_keys),
            ("Velocity", vel_keys),
            ("Temperature", temp_keys),
            ("Other", other_keys),
        ]:
            vals = {k: state.get(k, "N/A") for k in keys}
            print(f"  {group_name}: {vals}")

        # Flag anomalies
        agz = state.get("agz", 0)
        if isinstance(agz, (int, float)):
            # At rest, agz should be ~-1000 (1g in 0.001g units) or ~-9.8 m/s²
            # Different firmware report different units
            if abs(agz) < 1:
                print("  ⚠️  Accelerometer Z near zero – drone may not be level")
    else:
        print("  ⚠️  No state data received from drone!")

    # ── 5. Motor test ───────────────────────────────────────
    section("5. MOTOR TEST")
    print("  Attempting low-speed motor spin (SDK 3.0 'motoron')...")
    print("  Watch/listen for all 4 motors spinning evenly.")
    print()

    try:
        response = drone.send_command("motoron", timeout=10)
        print(f"  motoron → {response}")
        # The Tello replies "unknown command: motoron" (not prefixed "error"),
        # so send_command won't raise — validate the response explicitly.
        if "ok" not in response.lower():
            raise TelloError(response)
        print("  ✓ Motors running at low RPM")
        print()
        print("  ┌────────────────────────────────────────────┐")
        print("  │  CHECK NOW: Are all 4 propellers spinning? │")
        print("  │                                            │")
        print("  │   [1]  [2]     1=Front-Left  2=Front-Right │")
        print("  │     \\  /       3=Rear-Left   4=Rear-Right  │")
        print("  │      \\/                                     │")
        print("  │      /\\       If one is NOT spinning,      │")
        print("  │     /  \\      that motor cable is loose.   │")
        print("  │   [3]  [4]                                  │")
        print("  └────────────────────────────────────────────┘")
        print()

        # Keep motors on for 5 seconds for inspection
        for i in range(5, 0, -1):
            print(f"  Motors off in {i}s...", end="\r")
            time.sleep(1)
        print()

        response = drone.send_command("motoroff", timeout=10)
        print(f"  motoroff → {response}")
        print("  ✓ Motors stopped")

    except TelloError as e:
        err = str(e).lower()
        if "unknown command" in err or "error" in err:
            print(f"  ✗ 'motoron' not supported ({e})")
            print("  This drone may be a standard Tello (not EDU/RMTT).")
            print("  Motor-level testing requires SDK 3.0 (Tello EDU or RoboMaster TT).")
            print()
            print("  Alternative: visual inspection required.")
            print("  Try 'takeoff' when battery is charged – if the drone tips")
            print("  or fails to lift, the non-spinning motor is the faulty one.")
        else:
            print(f"  ✗ Motor test failed: {e}")

    # ── 6. Summary ──────────────────────────────────────────
    section("6. DIAGNOSIS SUMMARY")
    print("  If one motor did NOT spin during the test:")
    print("    → Power off the drone")
    print("    → Open the battery compartment and check motor ribbon cables")
    print("    → The Tello has 4 tiny connectors on the mainboard")
    print("    → Reseat the loose cable firmly into its socket")
    print("    → Reassemble and re-run this diagnostic")
    print()
    print("  If 'motoron' is not supported:")
    print("    → Charge battery above 50%")
    print("    → Attempt takeoff in a safe, open area")
    print("    → If the drone tilts/flips on takeoff, the silent motor is faulty")
    print()


def main() -> None:
    drone = Tello()
    try:
        drone.connect()
        run_diagnostic(drone)
    except TelloError as e:
        print(f"\nTello error: {e}")
        print("Make sure you're connected to the Tello Wi-Fi network.")
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        drone.close()


if __name__ == "__main__":
    main()
