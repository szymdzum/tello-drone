#!/usr/bin/env python3
"""
Motor debug — identify which motor is faulty.

Strategy: send takeoff, immediately sample IMU data (pitch/roll),
and analyze which direction the drone tilts. The tilt direction
reveals which motor lost thrust.

Motor layout (top view, camera = front):

    [M1 CW]  ──  FRONT  ──  [M2 CCW]
         \                 /
          \     CAMERA    /
           \      ↑      /
            [MAINBOARD]
           /             \
          /               \
    [M3 CCW] ── REAR ──  [M4 CW]

Tilt diagnosis:
  - Tilts FORWARD-LEFT  → M1 (front-left) weak/dead
  - Tilts FORWARD-RIGHT → M2 (front-right) weak/dead
  - Tilts REAR-LEFT     → M3 (rear-left) weak/dead
  - Tilts REAR-RIGHT    → M4 (rear-right) weak/dead

The drone tips TOWARD the dead motor (no thrust on that corner).
"""

import time
import threading
from tello import Tello, TelloError


def collect_state_samples(drone: Tello, duration: float, interval: float = 0.1):
    """Collect state snapshots for a given duration."""
    samples = []
    start = time.time()
    while time.time() - start < duration:
        state = drone.state
        if state:
            samples.append({
                "t": round(time.time() - start, 2),
                "pitch": state.get("pitch", 0),
                "roll": state.get("roll", 0),
                "yaw": state.get("yaw", 0),
                "h": state.get("h", 0),
                "agx": state.get("agx", 0),
                "agy": state.get("agy", 0),
                "agz": state.get("agz", 0),
                "vgx": state.get("vgx", 0),
                "vgy": state.get("vgy", 0),
                "vgz": state.get("vgz", 0),
            })
        time.sleep(interval)
    return samples


def diagnose_motor(samples):
    """Analyze pitch/roll data to identify the faulty motor."""
    if not samples:
        print("  No telemetry samples collected!")
        return

    # Average pitch and roll during the flight attempt
    avg_pitch = sum(s["pitch"] for s in samples) / len(samples)
    avg_roll = sum(s["roll"] for s in samples) / len(samples)
    max_pitch = max(s["pitch"] for s in samples)
    min_pitch = min(s["pitch"] for s in samples)
    max_roll = max(s["roll"] for s in samples)
    min_roll = min(s["roll"] for s in samples)

    print(f"\n{'─' * 50}")
    print(f"  IMU ANALYSIS ({len(samples)} samples)")
    print(f"{'─' * 50}")
    print(f"  Pitch — avg: {avg_pitch:+.1f}°  range: [{min_pitch}, {max_pitch}]")
    print(f"  Roll  — avg: {avg_roll:+.1f}°  range: [{min_roll}, {max_roll}]")
    print()

    # Determine tilt direction
    # Pitch: positive = nose up (tilting backward), negative = nose down (tilting forward)
    # Roll:  positive = tilting right, negative = tilting left
    THRESHOLD = 5  # degrees — anything above this indicates a motor issue

    pitch_dir = ""
    roll_dir = ""

    if avg_pitch < -THRESHOLD:
        pitch_dir = "FORWARD"
    elif avg_pitch > THRESHOLD:
        pitch_dir = "REAR"

    if avg_roll < -THRESHOLD:
        roll_dir = "LEFT"
    elif avg_roll > THRESHOLD:
        roll_dir = "RIGHT"

    tilt = f"{pitch_dir}-{roll_dir}".strip("-")

    motor_map = {
        "FORWARD-LEFT":  ("M1", "Front-Left",  "CW"),
        "FORWARD-RIGHT": ("M2", "Front-Right", "CCW"),
        "REAR-LEFT":     ("M3", "Rear-Left",   "CCW"),
        "REAR-RIGHT":    ("M4", "Rear-Right",  "CW"),
        "FORWARD":       ("M1 or M2", "Front side", "—"),
        "REAR":          ("M3 or M4", "Rear side",  "—"),
        "LEFT":          ("M1 or M3", "Left side",  "—"),
        "RIGHT":         ("M2 or M4", "Right side",  "—"),
    }

    print(f"  ┌────────────────────────────────────────────┐")
    print(f"  │  MOTOR LAYOUT (top view, camera = front)   │")
    print(f"  │                                            │")
    print(f"  │   [M1 CW]    FRONT ↑    [M2 CCW]          │")
    print(f"  │       \\       CAMERA      /                │")
    print(f"  │        \\                 /                 │")
    print(f"  │         [  MAINBOARD  ]                    │")
    print(f"  │        /                 \\                 │")
    print(f"  │       /                   \\                │")
    print(f"  │   [M3 CCW]    REAR      [M4 CW]           │")
    print(f"  └────────────────────────────────────────────┘")
    print()

    if not tilt:
        if abs(avg_pitch) < 2 and abs(avg_roll) < 2:
            print("  ✓ No significant tilt detected!")
            print("  All motors appear to be working. The 'Motor stop' error")
            print("  may be intermittent — vibration loosening the connector.")
        else:
            print(f"  ⚠ Mild tilt detected (pitch={avg_pitch:+.1f}°, roll={avg_roll:+.1f}°)")
            print("  Could be normal turbulence or a partially weak motor.")
    elif tilt in motor_map:
        motor_id, position, direction = motor_map[tilt]
        print(f"  🔴 TILT DETECTED: {tilt}")
        print(f"  ─────────────────────────────")
        print(f"  Faulty motor:  {motor_id} ({position}, spins {direction})")
        print(f"  Drone tilted toward this corner = no thrust there")
        print()
        print(f"  FIX: Power off → open shell → reseat the {position} motor cable")
    else:
        print(f"  ⚠ Unusual tilt pattern: pitch={avg_pitch:+.1f}°, roll={avg_roll:+.1f}°")

    # Print raw samples for reference
    print(f"\n{'─' * 50}")
    print(f"  RAW TELEMETRY LOG")
    print(f"{'─' * 50}")
    print(f"  {'time':>5}  {'pitch':>6}  {'roll':>6}  {'yaw':>5}  {'h':>4}  {'vgx':>5}  {'vgy':>5}  {'vgz':>5}")
    for s in samples:
        print(f"  {s['t']:5.1f}  {s['pitch']:+6d}  {s['roll']:+6d}  {s['yaw']:+5d}  {s['h']:4d}  {s['vgx']:+5d}  {s['vgy']:+5d}  {s['vgz']:+5d}")


def main():
    drone = Tello()
    try:
        drone.connect()
        battery = drone.get_battery()
        print(f"Battery: {battery}%")
        if battery < 15:
            print("Battery too low. Charge first.")
            return

        print()
        print("=" * 50)
        print("  MOTOR DEBUG TEST")
        print("  The drone will attempt takeoff.")
        print("  IMU data will be recorded to detect tilt.")
        print("  If a motor fails, it will land/drop safely.")
        print("=" * 50)
        print()

        # Brief pause to let state receiver warm up
        time.sleep(2)

        # Collect baseline (on ground)
        print("  Collecting baseline (on ground)...")
        baseline = collect_state_samples(drone, duration=1.5)
        if baseline:
            bp = sum(s["pitch"] for s in baseline) / len(baseline)
            br = sum(s["roll"] for s in baseline) / len(baseline)
            print(f"  Baseline — pitch: {bp:+.1f}°, roll: {br:+.1f}°")

        # Attempt takeoff and collect data
        print("\n  Attempting takeoff — monitoring IMU...")
        samples = []

        # Start collecting in background
        collecting = True

        def collector():
            while collecting:
                state = drone.state
                if state:
                    samples.append({
                        "t": round(time.time(), 2),
                        "pitch": state.get("pitch", 0),
                        "roll": state.get("roll", 0),
                        "yaw": state.get("yaw", 0),
                        "h": state.get("h", 0),
                        "agx": state.get("agx", 0),
                        "agy": state.get("agy", 0),
                        "agz": state.get("agz", 0),
                        "vgx": state.get("vgx", 0),
                        "vgy": state.get("vgy", 0),
                        "vgz": state.get("vgz", 0),
                    })
                time.sleep(0.05)

        collector_thread = threading.Thread(target=collector, daemon=True)
        collector_thread.start()

        try:
            drone.takeoff()
            # If takeoff succeeds, collect a few more seconds in the air
            time.sleep(3)
            print("  Landing...")
            drone.land()
        except TelloError as e:
            print(f"  ⚠ Takeoff error: {e}")
            # Still analyze whatever data we got

        collecting = False
        time.sleep(0.5)

        # Normalize timestamps
        if samples:
            t0 = samples[0]["t"]
            for s in samples:
                s["t"] = round(s["t"] - t0, 2)

        # Diagnose
        diagnose_motor(samples)

    except TelloError as e:
        print(f"\nTello error: {e}")
    except KeyboardInterrupt:
        print("\nInterrupted — sending emergency stop")
        drone.emergency()
    finally:
        drone.close()


if __name__ == "__main__":
    main()
