# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A from-scratch controller for a Ryze/DJI Tello drone, talking to the Tello SDK
directly over raw UDP sockets. **Single entry point: `drone.py`** (modes: `fpv`
default, `repl`, `demo`); the library lives in the `tello_app/` package. The
protocol core and the repl/demo modes are **stdlib-only — no pip install
needed**; only FPV pulls in external deps (OpenCV, numpy, optionally PyAV).

`docs/REPAIR.md` keeps a *historical* repair log: the original drone had a
disconnected motor and is now permanently grounded (power-rail fault); a working
replacement is the flight unit. The repair/diagnostic scripts have been removed
(see git history). See "Hardware context" below.

## Running

All scripts require the host machine to be connected to the Tello's Wi-Fi
(`TELLO-XXXXXX`, no password). The drone is always at `192.168.10.1`. There is no
build step.

Linting/typing are configured in `pyproject.toml` (ruff + basedpyright); run via
`uvx ruff check .` and `uvx basedpyright` (prefix `UV_SYSTEM_CERTS=1` if behind a
TLS-intercepting proxy). Hardware-free tests live in `tests/` (stdlib `unittest`,
they mock the `Tello` class — no drone needed): `python -m unittest discover -s tests`.

```bash
python drone.py           # FPV (default): live video + keyboard flight (cv2; WASD+IJKL)
python drone.py repl      # interactive REPL — type raw SDK commands (stdlib only)
python drone.py demo      # scripted square flight (takeoff → 50cm square → land)
python keepalive.py       # hold the drone awake between sessions (stdlib only)
```

FPV deps: `pip install opencv-python numpy` (+ `pip install av` for lower-latency
decode). Everything else runs on Python stdlib only.

Verifying connectivity before a run: `ping -c 3 192.168.10.1`.

## Architecture

Everything is built on the `Tello` class in `tello_app/tello.py` — the single
source of truth for the protocol. Layout: `tello_app/flight/` (controller + HUD
content), `tello_app/video/stream.py` (H.264 decode), `tello_app/shells/`
(fpv + repl front-ends), `drone.py` (entry point: connect once, dispatch to a
shell, always `close()`).

**Three UDP channels** (all opened in `Tello.__init__`):
- Command — send to `192.168.10.1:8889`, block for a text response. This is
  request/response: `send_command()` sends, then `recvfrom` waits for the reply.
- State — bind `0.0.0.0:8890`, telemetry pushed at ~10 Hz. A daemon thread
  (`_state_receiver`) parses `key:value;...` packets into `self._state`, guarded
  by `_state_lock`. Read it via the thread-safe `.state` property (returns a copy).
- Video — `0.0.0.0:11111`, H.264. The `Tello` class only toggles it
  (`stream_on`/`stream_off`); decoding happens in `tello_app/video/stream.py`
  (PyAV or OpenCV's FFMPEG backend), not through the `Tello` class.

**Key protocol details to preserve when editing `tello.py`:**
- Command replies are drained by a dedicated **response-receiver thread** into a
  timestamped queue; `send_command()` (serialized by `_cmd_lock`, thread-safe)
  discards any reply that arrived *before* its own send. This is what prevents a
  late reply to a timed-out command from desyncing the next request — never
  revert to inline `recvfrom`.
- `send_command()` raises `TelloError` on any response starting with `error`.
  Read commands (`battery?`, etc.) return the raw string; helpers like
  `get_battery()` cast it.
- Fire-and-forget commands (`send_rc`, `emergency`) bypass the
  request/response path — they `sendto` directly with **no** wait, because the
  drone does not reply to them.
- The Tello **auto-lands after 15 s** of silence (`SAFETY_TIMEOUT`). Any
  long-running control loop must keep sending commands.
- `Tello(ip, remote_port=…, local_port=…, state_port=…)` exists so
  `tests/test_tello.py` can run the real protocol against a fake UDP drone on
  localhost — keep addressing injectable.

**`tello_app/flight/controller.py` is the flight brain** — the keymap
(`MOVES`/`DISCRETES`: WASD horizontal, IJKL throttle+yaw), `FlightController`
(pure key→velocity logic), `_do_action`, and `ActionRunner` (worker thread for
takeoff/land/flip so the rc stream and UI never block; pending-slot with sticky
`land`; `emergency` runs inline). It depends only on `tello.py`. The FPV shell
(`tello_app/shells/fpv.py`) is a thin I/O layer over it — **put control logic in
the controller, never in a shell.** Likewise `tello_app/flight/hud.py` owns the
HUD *content* (telemetry/rc/help strings); the shell only decides how to render
it. The on-screen help in `hud.HELP_LINES` is checked against the keymap by
`tests/test_hud.py`. Lessons from a real crash: takeoff must set `flying=True`
even if the `ok` reply is lost, and nothing in the control loop may block.
`tello_app/video/stream.py` decodes with PyAV when `av` is installed (lower
latency), else falls back to cv2's FFMPEG capture; either way decode runs on its
own thread, latest-frame-wins. On macOS, **AWDL (AirDrop) stalls the Wi-Fi radio
~every second** — `drone.py` warns at startup (`tello_app/util.py`); fix is
`sudo ifconfig awdl0 down`.

The repl shell (`tello_app/shells/repl.py`) tracks `flying` state locally to
decide whether to auto-land on quit — the drone itself isn't queried for this.

## Hardware context (historical repair log)

The repair phase is **concluded**. The original unit has a disconnected motor
(rear-left, CCW) plus a power-rail fault and is permanently grounded; a working
replacement Tello is now the flight unit. The teardown, motor layout (`M0–M3`,
M0 = rear-left), wire-color polarity, and soldering steps live in
`docs/REPAIR.md` — kept as a record, not active work. The former
`diagnostic.py` / `motor_debug.py` scripts have been removed; recover them from
git history if the original is ever revived.

## Reference docs (not code)

`docs/LIBRARIES.md`, `docs/IDEAS.md`, `docs/ALTERNATIVES.md`, `docs/FLIX-BUILD.md`
are research notes. Notably, `docs/LIBRARIES.md` points to **DJITelloPy** as the production-grade
library that would replace this raw-socket code if reliability over learning
becomes the priority.
