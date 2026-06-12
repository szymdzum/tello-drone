# Tello Drone Controller

[![CI](https://github.com/szymdzum/tello-drone/actions/workflows/ci.yml/badge.svg)](https://github.com/szymdzum/tello-drone/actions/workflows/ci.yml)

Fly a Ryze/DJI Tello from scratch — raw UDP sockets, no drone framework. The
protocol core is stdlib-only; FPV flight needs `opencv-python` + `numpy`
(+ optionally `av` for lower-latency video decode).

What's in the box:

- **Keyboard FPV** with live video and an arcade-style HUD (attitude ladder,
  yaw tape, virtual sticks, battery/telemetry panels)
- **Face follow** — press `p` and the drone tracks you: Haar-cascade detection
  on a background thread feeding a P-controller; any stick key overrides
- **Crash detection** — telemetry-based flip detection resyncs the controller
  when the drone ends up on its back (tuned against real crash logs)
- **Drift damper** — when the sticks are quiet, the loop counters the drone's
  own reported drift instead of streaming zeros (the firmware's optical
  position-hold goes blind on featureless floors)
- **Flight recorder** — every session logged as JSONL (telemetry, commands,
  rc stream, detections); `analyze.py` turns a log into a flight report and
  matplotlib charts. Every safety feature above was built from these logs.
- A hardened protocol layer: response-desync quarantine, ground-gated
  keepalive, non-blocking action runner — lessons from a real crash, each
  pinned by hardware-free tests

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

`t` takeoff · `g` land · `f` flip · `h` hover · `p` **follow face** · `y`/`u` speed · **SPACE** = **EMERGENCY stop (drone drops!)** · **Esc**/`q` quit (lands first).

Hold a key to move; release and that axis coasts to a hover within ~0.5 s
(tune `HOLD_S` / `RATE_S` in `tello_app/flight/controller.py`).

Design notes: video decodes on a background thread (PyAV if installed, else
OpenCV/FFMPEG), latest-frame-wins; takeoff/land/flip run on a worker thread —
so nothing can ever stall the rc stream or the HUD. Face detection follows the
same pattern: its own thread, latest-detection-wins, and the follow controller
is pure math (`tello_app/flight/tracking.py`) tuned via flight logs.

## Flight recorder

Every `drone.py` session writes a JSONL log to `logs/` (`--no-log` to disable):
telemetry at 10 Hz, every command with round-trip time, the full rc stream
tagged by who was steering (`keys` / `follow` / `damp` / `keepalive`), face
detections, and flight events.

```bash
python analyze.py            # report on the newest flight: battery drain,
                             # cmd latency, airborne rc gaps, follow share
python analyze.py --plot     # + time-aligned charts (pip install matplotlib)
```

The crash detector and drift damper in this repo were both designed — and
sign-verified — from these logs. If something weird happens in the air, the
answer is usually one `jq` query away.

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
├── analyze.py           # Flight-log report + charts
├── tello_app/
│   ├── tello.py         # Tello class – UDP channels, commands, state receiver
│   ├── flightlog.py     # JSONL flight recorder (fail-silent, thread-safe)
│   ├── util.py          # Host-side helpers (Wi-Fi auto-join, macOS AWDL)
│   ├── flight/          # Flight brain: keymap, controller, action runner,
│   │                    #   crash monitor, follow/damper math, HUD content
│   ├── vision/          # Face detector (background thread, latest-wins)
│   ├── video/           # Background H.264 decode (PyAV / OpenCV), latest-frame-wins
│   └── shells/          # Front-ends: fpv (video + keys), repl (raw SDK + demo)
├── docs/                # Research notes (IDEAS, LIBRARIES, ALTERNATIVES, FLIX-BUILD)
│   └── REPAIR.md        # Historical repair log for the original (grounded) unit
├── tests/               # Hardware-free tests (fake UDP drone, mocked Tello)
├── pyproject.toml       # ruff + basedpyright config
└── CLAUDE.md            # Guidance for Claude Code
```

Tests: `python -m unittest discover -s tests` — 93 of them, no drone needed
(the protocol tests run against a fake UDP drone on localhost). CI runs tests,
ruff, and basedpyright on every push.

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
