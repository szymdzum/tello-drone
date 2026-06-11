# Tello Drone Controller

Control a Ryze Tello drone via Python using raw UDP sockets (no external dependencies).

## Quick Start

1. **Power on** the Tello drone (press side button)
2. **Connect your Mac** to the Tello Wi-Fi network (`TELLO-XXXXXX`, no password)
3. **Run the interactive controller:**

```bash
python main.py
```

## Modes

### Interactive (default)
Type SDK commands directly in the REPL:
```
tello> battery?
  → 87
tello> takeoff
  → ok
tello> forward 50
  → ok
tello> cw 90
  → ok
tello> land
  → ok
```

### Demo (scripted square flight)
```bash
python main.py --demo
```
Takes off, flies a 50cm square, and lands.

## Repair & Testing Checklist

### Phase 1 — Charge
- [ ] Power off the drone (hold power button until LED goes dark)
- [ ] Connect micro-USB cable to drone and a 5V/2A wall adapter
- [ ] LED blinks blue = charging; solid blue = fully charged (~90 min)
- [ ] Do NOT attempt flight below 20% battery

### Phase 2 — Physical Repair (disconnected motor)

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

### Phase 3 — Software Verification
- [ ] Power on drone (LED blinks → solid green = Vision Positioning active)
- [ ] Connect Mac to Tello Wi-Fi (`TELLO-XXXXXX`)
- [ ] Verify connectivity:
  ```bash
  ping -c 3 192.168.10.1
  ```
- [ ] Run diagnostic:
  ```bash
  python diagnostic.py
  ```
- [ ] Confirm: battery > 50%
- [ ] Confirm: IMU readings normal (pitch/roll/yaw near 0 at rest)
- [ ] Confirm: telemetry state data is streaming

### Phase 4 — Motor Test
- [ ] Place drone on a flat surface, clear area around it
- [ ] Run interactive mode:
  ```bash
  python main.py
  ```
- [ ] Send `takeoff` — watch that ALL 4 propellers spin and drone lifts evenly
- [ ] If drone tilts/flips → the tilting side's motor is still disconnected
- [ ] Send `land` immediately after confirming stable hover
- [ ] Check battery level: `battery?`

### Phase 5 — Flight Test
- [ ] Send `takeoff`
- [ ] Test basic movement: `forward 30`, `back 30`
- [ ] Test rotation: `cw 90`, `ccw 90`
- [ ] Check `state` — verify height, velocity, IMU data look sane
- [ ] Send `land`
- [ ] Run the demo flight:
  ```bash
  python main.py --demo
  ```

### Troubleshooting
- **Drone tips on takeoff** → the silent motor's cable is still loose
- **"error" response to takeoff** → battery too low or propeller obstruction
- **No Wi-Fi network visible** → long-press power 5s to reset Wi-Fi
- **Timeout on commands** → check Wi-Fi connection, re-run `ping`
- **"unactive" response to `command`** → update firmware via Tello mobile app

## Project Structure

```
tello-drone/
│  # ── Core library ──
├── tello.py          # Tello class – UDP channels, commands, state receiver
│
│  # ── Control / entry points ──
├── main.py           # Interactive REPL + scripted demo flight
├── keepalive.py      # Hold a session open so the drone doesn't idle-power-off
│
│  # ── Diagnostics / repair ──
├── diagnostic.py     # Query all sensors + attempt SDK 3.0 motor test
├── motor_debug.py    # Take off + sample IMU tilt to locate a dead motor
│
│  # ── Vision ──
├── video_stream.py   # Live H.264 video + OpenCV face detection (needs cv2)
│
├── docs/             # Research & reference notes
│   ├── IDEAS.md         # Project ideas (CV, automation, robotics, fun)
│   ├── LIBRARIES.md     # Curated libraries + pip building blocks
│   ├── ALTERNATIVES.md  # Alternative approaches / platforms
│   └── FLIX-BUILD.md    # Flix flight-controller build notes
│
├── captures/         # Stills saved by video_stream.py (gitignored)
├── README.md
└── CLAUDE.md         # Guidance for Claude Code
```

## SDK Command Reference

| Command | Description |
|---|---|
| `takeoff` / `land` | Auto take off / land |
| `up/down/left/right/forward/back <cm>` | Move 20–500 cm |
| `cw/ccw <degrees>` | Rotate 1–360° |
| `flip <l\|r\|f\|b>` | Do a flip |
| `speed <cm/s>` | Set speed (10–100) |
| `battery?` | Get battery % |
| `state` | Show live telemetry |
| `emergency` | Kill motors immediately |

## Safety Notes

- The drone **auto-lands after 15 seconds** of no commands
- `emergency` kills motors instantly – the drone will **drop**
- Always fly in an open area with sufficient ceiling height
- Keep battery above 20% for stable flight
- Wi-Fi reset: long-press power button for 5 seconds while powered on
