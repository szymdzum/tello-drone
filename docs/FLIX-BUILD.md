# Flix Build Guide

Source: https://github.com/okalachev/flix

## Parts List

### Electronics

| Part | Spec | Qty | Search term (AliExpress/Amazon) |
|---|---|---|---|
| Microcontroller | ESP32 Mini (D1 Mini ESP32) | 1 | "ESP32 D1 Mini" or "WEMOS D1 Mini ESP32" |
| IMU board | GY-91 (MPU-9250 + BMP280) | 1 | "GY-91 MPU9250" |
| _Alt IMU_ | _ICM20948V2 or GY-521 (MPU-6050)_ | | _Change IMU type in `imu.ino` if using alt_ |
| MOSFET | 100N03A (N-channel) | 4 | "100N03A MOSFET" |
| Pull-down resistor | 10 kΩ | 4 | "10k ohm resistor" (any standard pack) |
| Motor | 8520 3.7V brushed (shaft 0.8mm) | 4 | "8520 motor 3.7V drone" ⚠️ must be exact 3.7V, not 3.7-6V |
| Propeller | 55mm (or 65mm) | 4+ | "55mm propeller 0.8mm shaft" or "Hubsan 55mm propeller" |
| Battery | 3.7V LiPo, LW 952540 or similar | 1 | "952540 lipo 3.7v" (~500-600mAh) |
| Battery connector | MX2.0 2P female cable | 1 | "MX2.0 2P connector female" |
| LiPo charger | Any 1S LiPo USB charger | 1 | "1S lipo USB charger" |
| Boost converter | 5V output (optional, for stable power) | 1 | "3.7v to 5v boost converter mini" |
| Wires | 28 AWG silicone | — | "28 AWG silicone wire" |

### 3D Printed Parts (print yourself or order from a service)

| Part | File | Print settings |
|---|---|---|
| Frame (main) | `docs/assets/flix-frame-1.1.stl` | Layer 0.2mm, line 0.4mm, **infill 100%** |
| ESP32 holder (top) | `docs/assets/esp32-holder.stl` | Standard settings |
| IMU washers (x2) | `docs/assets/washer-m3.stl` | Standard settings |

### Hardware

| Part | Qty |
|---|---|
| M3x5 screws (IMU mounting) | 2 |
| M1.4x5 screws (frame assembly) | 4 |
| Double-sided tape | — |

### Controller (pick one)

| Option | Notes |
|---|---|
| USB gamepad (Wi-Fi) | Any two-stick gamepad, connect via QGroundControl |
| BetaFPV LiteRadio CC2500 | Dedicated RC transmitter, needs DF500 receiver on drone |
| Smartphone | Control via QGroundControl app over Wi-Fi |

### Tools Required

- 3D printer (or order prints from a service)
- Soldering iron + solder with flux
- Screwdrivers
- Multimeter
- Computer with USB cable

---

## Wiring

### IMU → ESP32 (SPI)

| IMU pin | ESP32 pin |
|---|---|
| GND | GND |
| 3.3V | 3.3V |
| SCL (SCK) | GPIO18 |
| SDA (MOSI) | GPIO23 |
| SAO (MISO) | GPIO19 |
| NCS | GPIO5 |

### Motors → ESP32 (via MOSFETs + 10kΩ pull-down each)

| Motor | Position | Direction | Prop | Wires | GPIO |
|---|---|---|---|---|---|
| M0 | Rear-Left | CCW | B | Black/White | GPIO12 |
| M1 | Rear-Right | CW | A | Blue/Red | GPIO13 |
| M2 | Front-Right | CCW | B | Black/White | GPIO14 |
| M3 | Front-Left | CW | A | Blue/Red | GPIO15 |

### Power

- Battery → ESP32 VCC (+) and GND (-)
- Optional: battery → boost converter → 5V → ESP32 VIN

---

## Dev Environment Setup (macOS)

### 1. Install Arduino CLI

```bash
brew install arduino-cli
```

### 2. Clone the Flix repo

```bash
git clone https://github.com/okalachev/flix.git ~/Developer/flix
```

### 3. Install ESP32 board support + libraries

```bash
cd ~/Developer/flix
arduino-cli core update-index --config-file arduino-cli.yaml
arduino-cli core install esp32:esp32@3.3.6 --config-file arduino-cli.yaml
arduino-cli lib update-index
arduino-cli lib install "FlixPeriph"
arduino-cli lib install "MAVLink"@2.0.25
```

### 4. Build the firmware

```bash
arduino-cli compile --fqbn esp32:esp32:d1_mini32 flix
```

### 5. Flash to ESP32 (plug in via USB)

```bash
# Find the port
ls /dev/cu.usbserial-*

# Upload
arduino-cli upload --fqbn esp32:esp32:d1_mini32 -p /dev/cu.usbserial-XXXX flix
```

### 6. Open serial monitor (115200 baud)

```bash
arduino-cli monitor -p /dev/cu.usbserial-XXXX -c baudrate=115200
```

### 7. Calibrate

In the serial monitor:
- `ca` — calibrate accelerometer (follow prompts)
- `cr` — calibrate RC (if using SBUS receiver)
- `imu` — verify IMU is working (status=OK, rate≈1000Hz)
- `mfr` / `mfl` / `mrl` / `mrr` — test individual motors

---

## Simulation (test before flying)

### Install Gazebo

```bash
brew install gazebo
```

### Build and run simulator

```bash
cd ~/Developer/flix
mkdir -p gazebo/build && cd gazebo/build && cmake ..
make
cd ~/Developer/flix
GAZEBO_MODEL_PATH=$GAZEBO_MODEL_PATH:$(pwd)/gazebo/models \
GAZEBO_PLUGIN_PATH=$GAZEBO_PLUGIN_PATH:$(pwd)/gazebo/build \
gazebo --verbose gazebo/flix.world
```

The simulator runs the **actual Arduino firmware** in Gazebo — same code, simulated physics.

---

## Python Control

```bash
pip install pyflix
```

```python
from pyflix import Flix

drone = Flix()          # connects via Wi-Fi
drone.arm()
drone.takeoff()
drone.land()
drone.disarm()
```

---

## Firmware Architecture (for hacking)

The firmware is ~1700 lines across 17 files. Main loop at 1000Hz:

| File | Purpose |
|---|---|
| `flix.ino` | Main loop, global variables |
| `imu.ino` | IMU read + calibration |
| `estimate.ino` | Attitude estimation (complementary filter) |
| `control.ino` | PID controller (attitude + rate cascaded) |
| `motors.ino` | PWM output to 4 motors |
| `rc.ino` | RC receiver input |
| `mavlink.ino` | QGroundControl / pyflix communication |
| `cli.ino` | Serial + wireless console |

Key global variables you can inspect/modify:
- `gyro`, `acc` — raw sensor data
- `rates` — filtered angular rates
- `attitude` — estimated orientation (quaternion)
- `motors[4]` — motor outputs (0.0–1.0)
- `armed`, `mode` — flight state

---

## Estimated Cost

| Category | Cost |
|---|---|
| ESP32 Mini | ~$4 |
| GY-91 IMU | ~$8 |
| 4x motors + props | ~$8 |
| 4x MOSFETs + resistors | ~$3 |
| Battery + charger + connector | ~$6 |
| 3D print (frame) | ~$5 (filament) |
| Wires, screws, tape | ~$3 |
| **Total (without controller)** | **~$37** |
| Gamepad (if needed) | ~$15-25 |
