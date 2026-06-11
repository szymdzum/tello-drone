# Repair & Testing Checklist (historical)

> **Historical record.** This documents the repair of the *original* drone, now
> permanently grounded (power-rail fault). The flight unit is a working
> replacement. Kept for reference; the `diagnostic.py` / `motor_debug.py` scripts
> it once referenced have been removed (recover from git history if needed).

## Phase 1 — Charge
- [ ] Power off the drone (hold power button until LED goes dark)
- [ ] Connect micro-USB cable to drone and a 5V/2A wall adapter
- [ ] LED blinks blue = charging; solid blue = fully charged (~90 min)
- [ ] Do NOT attempt flight below 20% battery

## Phase 2 — Physical Repair (disconnected motor)

**Diagnosed fault:** Motor M0 — **Rear-Left** (from drone's perspective) / **Back-Right** (looking at the drone from behind). CCW motor, black & white wires. Confirmed by visual inspection: motor does not spin, causes `Motor stop` error during forward thrust.

**Motor layout** (drone's perspective, camera = front):
```
  [M3 front-left CW]      [M2 front-right CCW]
  blue/red wires            black/white wires
        \                        /
         \      CAMERA ↑        /
          \                    /
           [   MAINBOARD    ]
          /                    \
         /      BATTERY ↓       \
        /                        \
  [M0 rear-left CCW] ★    [M1 rear-right CW]
  black/white wires         blue/red wires

  ★ = FAULTY MOTOR
```

**Wire color → polarity:**
- CCW motors (M0, M2): **white = (+)**, **black = (−)**
- CW motors (M1, M3): **red = (+)**, **blue = (−)**

**Option A — Wire splice (easier, no shell opening needed):**
The motor wires run through the arm from the motor to the mainboard.
You can splice wire-to-wire without touching the board.
- [ ] Remove the battery and propeller from the faulty motor
- [ ] Pull the motor out from the arm mount (pull from the outside, not the body)
- [ ] The old wires trail behind through the arm, still connected to the board
- [ ] Cut the old wires near the motor (~2cm from the motor body)
- [ ] Cut the new motor's wires to match length
- [ ] **Cut at different lengths** (stagger the joins to prevent short circuits)
- [ ] Splice new wires to old: twist together, solder, insulate each joint
- [ ] Match colors: **black→black, white→white**
- [ ] Wrap each joint in **heat shrink tubing** or electrical tape
- [ ] Tuck the wires back into the arm grooves
- [ ] Push the new motor into the mount until it seats firmly
- [ ] Reattach propeller (CCW/type B for rear-left)
- [ ] Reinsert battery and test

**Option B — Mainboard resolder (if wires detached from the board):**
- [ ] Remove battery, pop off top shell (4 clips, no screws)
- [ ] Follow M0 wires through the arm to the mainboard solder pads
- [ ] Resolder both wires: black = (−), white = (+)
- [ ] Reinforce with hot glue over the joint
- [ ] Reassemble shell
- NOTE: There are **no published schematics** for the Tello mainboard.
  The solder pads are tiny and close together. Use magnification.

**Repair references:**
- iFixit motor replacement: https://www.ifixit.com/Guide/DJI+Ryze+Tello+Motor+Replacement/104994
- iFixit propeller replacement: https://www.ifixit.com/Guide/Tello+Quadcopter+Propeller+Replacement/138620
- TelloPilots forum (photos + video): https://tellopilots.com/threads/hit-a-wall-killed-a-motor-how-to-replace.3496/
- FCC internal teardown photos (board layout): https://fccid.io/2AOOE-WM0041801/Internal-Photos/Internal-Photos-3731020
- DJI firmware wiki (board components): https://github.com/o-gs/dji-firmware-tools/wiki/WM004-Main-Processing-Core-Board

**Tools needed:** soldering iron, solder with flux, heat shrink tubing or tape, wire strippers, needle-nose pliers

## Phase 3 — Software Verification
- [ ] Power on drone (LED blinks → solid green = Vision Positioning active)
- [ ] Connect Mac to Tello Wi-Fi (`TELLO-XXXXXX`)
- [ ] Verify connectivity: `ping -c 3 192.168.10.1`
- [ ] Start the REPL (`python drone.py repl`) and query sensors:
  - `battery?` → confirm > 50%
  - `state` → IMU (pitch/roll/yaw) near 0 at rest, telemetry streaming

## Phase 4 — Motor Test
- [ ] Place drone on a flat surface, clear area around it
- [ ] Run `python drone.py repl`
- [ ] Send `takeoff` — watch that ALL 4 propellers spin and drone lifts evenly
- [ ] If drone tilts/flips → the tilting side's motor is still disconnected
- [ ] Send `land` immediately after confirming stable hover
- [ ] Check battery level: `battery?`

## Phase 5 — Flight Test
- [ ] Send `takeoff`
- [ ] Test basic movement: `forward 30`, `back 30`
- [ ] Test rotation: `cw 90`, `ccw 90`
- [ ] Check `state` — verify height, velocity, IMU data look sane
- [ ] Send `land`
- [ ] Run the demo flight: `python drone.py demo`

## Repair troubleshooting
- **Drone tips on takeoff** → the silent motor's cable is still loose
- **"error" response to takeoff** → battery too low or propeller obstruction
