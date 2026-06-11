# Tello Drone Controller

Control a Ryze Tello drone via Python using raw UDP sockets. The protocol core
is stdlib-only; FPV flight needs `opencv-python` + `numpy` (+ optionally `av`
for lower-latency video decode).

## Quick Start

1. **Power on** the Tello (press side button)
2. **Fly** — `drone.py` auto-joins the Tello Wi-Fi if it's broadcasting
   (`--ssid` to override the network name, empty to disable):

```bash
python drone.py          # FPV: live video window + keyboard flight (default)
python drone.py repl     # raw SDK REPL for protocol debugging (stdlib only)
python drone.py demo     # scripted square flight (stdlib only)
```

## FPV controls

OpenCV both shows the video and reads the keys, so **click the video window to
give it focus** before flying. One hand per cluster:

| Left hand (WASD) | Right hand (IJKL) |
|---|---|
| `W` / `S` forward / back | `I` / `K` up / down (throttle) |
| `A` / `D` strafe left / right | `J` / `L` yaw left / right |

`t` takeoff · `g` land · `f` flip · `h` hover · `y`/`u` speed · **SPACE** = **EMERGENCY stop (drone drops!)** · **Esc**/`q` quit (lands first).

Hold a key to move; release and that axis coasts to a hover within ~0.5 s
(tune `HOLD_S` / `RATE_S` in `tello_app/flight/controller.py`).

Design notes: video decodes on a background thread (PyAV if installed, else
OpenCV/FFMPEG), latest-frame-wins; takeoff/land/flip run on a worker thread —
so nothing can ever stall the rc stream or the HUD.

## Troubleshooting

- **macOS AWDL (AirDrop/AirPlay) stalls the Wi-Fi radio ~every second** — the
  top cause of lost replies/laggy rc. `drone.py` warns at startup; fix for the
  session: `sudo ifconfig awdl0 down`. One-time setup so it's done automatically
  (no password):
  ```bash
  echo "$USER ALL=(ALL) NOPASSWD: /sbin/ifconfig awdl0 down" | sudo tee /etc/sudoers.d/awdl
  ```
- **Timeout on commands** → check you're on the Tello Wi-Fi (`ping -c 3 192.168.10.1`)
- **No Wi-Fi network visible** → long-press power 5 s to reset Wi-Fi
- **"unactive" response to `command`** → update firmware via the Tello mobile app
- **`objc: Class AVFFrameReceiver is implemented in both ...`** at startup is
  benign — cv2 and PyAV each bundle their own FFmpeg. Ignore it.
- **`non-existing PPS 0 referenced` / `no frame!` at video startup is normal** —
  the decoder is waiting for the first keyframe.
- **`error while decoding MB x y` during flight = real packet loss** — get
  closer, kill AWDL, avoid crowded 2.4 GHz.
- **Hovering drone drifts at `rc 0 0 0 0`** → the vision positioning system is
  losing the floor, not a control bug. Fly over a textured floor in good light.
- **The official app is smoother than the SDK and that's expected** — it speaks
  a different binary protocol (50 Hz un-acked stick packets). The text SDK still
  flies + streams reliably as long as the control loop never blocks (see
  `tello_app/shells/fpv.py`).

## Project Structure

```
tello-drone/
├── drone.py             # THE entry point: fpv (default) / repl / demo
├── keepalive.py         # Hold a session open so the drone doesn't idle-power-off
├── tello_app/
│   ├── tello.py         # Tello class – UDP channels, commands, state receiver
│   ├── util.py          # Host-side helpers (macOS AWDL warning)
│   ├── flight/          # Flight brain: keymap, FlightController, ActionRunner, HUD content
│   ├── video/           # Background H.264 decode (PyAV / OpenCV), latest-frame-wins
│   └── shells/          # Front-ends: fpv (video + keys), repl (raw SDK + demo)
├── docs/                # Research notes (IDEAS, LIBRARIES, ALTERNATIVES, FLIX-BUILD)
│   └── REPAIR.md        # Historical repair log for the original (grounded) unit
├── tests/               # Hardware-free unit tests (mock the Tello class)
├── pyproject.toml       # ruff + basedpyright config
└── CLAUDE.md            # Guidance for Claude Code
```

Tests: `python -m unittest discover -s tests` (no drone needed).
Lint/type-check: `uvx ruff check .` and `uvx basedpyright`.

## SDK Command Reference (REPL)

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

## Hardware note

The original drone (dead motor + power-rail fault) is permanently grounded; a
working replacement is the flight unit. The full teardown/repair log lives in
[docs/REPAIR.md](docs/REPAIR.md).
