# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A from-scratch controller for a Ryze/DJI Tello drone, talking to the Tello SDK
directly over raw UDP sockets. The core (`tello.py`, `main.py`, `diagnostic.py`,
`motor_debug.py`) is **stdlib-only — no pip install needed**. Only
`video_stream.py` pulls in an external dependency (OpenCV).

This project doubles as a repair log: the physical drone has a faulty motor, and
several scripts plus `README.md` exist to diagnose and verify it. See "Hardware
context" below.

## Running

All scripts require the host machine to be connected to the Tello's Wi-Fi
(`TELLO-XXXXXX`, no password). The drone is always at `192.168.10.1`. There is no
build step.

Linting/typing are configured in `pyproject.toml` (ruff + basedpyright); run via
`uvx ruff check .` and `uvx basedpyright` (prefix `UV_SYSTEM_CERTS=1` if behind a
TLS-intercepting proxy). Hardware-free tests live in `tests/` (stdlib `unittest`,
they mock the `Tello` class — no drone needed): `python -m unittest discover -s tests`.

```bash
python main.py            # interactive REPL — type raw SDK commands
python main.py --demo     # scripted square flight (takeoff → 50cm square → land)
python diagnostic.py      # query all sensors + attempt SDK 3.0 motor spin test
python motor_debug.py     # takeoff + sample IMU tilt to locate a dead motor
python video_stream.py    # live H.264 video + OpenCV face detection (needs cv2)
```

Video deps: `pip install opencv-python` (`cv2`). Captures land in `captures/`
(created on demand). Everything else runs on Python stdlib only.

Verifying connectivity before a run: `ping -c 3 192.168.10.1`.

## Architecture

Everything is built on the `Tello` class in `tello.py` — the single source of
truth for the protocol. The three other scripts are thin front-ends over it.

**Three UDP channels** (all opened in `Tello.__init__`):
- Command — send to `192.168.10.1:8889`, block for a text response. This is
  request/response: `send_command()` sends, then `recvfrom` waits for the reply.
- State — bind `0.0.0.0:8890`, telemetry pushed at ~10 Hz. A daemon thread
  (`_state_receiver`) parses `key:value;...` packets into `self._state`, guarded
  by `_state_lock`. Read it via the thread-safe `.state` property (returns a copy).
- Video — `0.0.0.0:11111`, H.264. The `Tello` class only toggles it
  (`stream_on`/`stream_off`); decoding happens in `video_stream.py` via OpenCV's
  FFMPEG backend, not through the `Tello` class.

**Key protocol details to preserve when editing `tello.py`:**
- `connect()` enters SDK mode by sending `command` (with retries), and *flushes
  stale packets* from the command socket first — the Tello buffers old replies,
  so skipping the flush causes responses to desync from requests.
- `send_command()` raises `TelloError` on any response starting with `error`.
  Read commands (`battery?`, etc.) return the raw string; helpers like
  `get_battery()` cast it.
- Fire-and-forget commands (`send_rc`, `emergency`) bypass the
  request/response path — they `sendto` directly with **no** wait, because the
  drone does not reply to them.
- The Tello **auto-lands after 15 s** of silence (`SAFETY_TIMEOUT`). Any
  long-running control loop must keep sending commands.

`main.py` tracks `flying` state locally to decide whether to auto-land on quit —
the drone itself isn't queried for this.

## Hardware context (repair project)

The README's repair checklist and `motor_debug.py` exist because this specific
drone has a disconnected motor. Two scripts diagnose it:
- `diagnostic.py` tries `motoron`/`motoroff` (SDK 3.0, **Tello EDU/RMTT only** —
  a standard Tello returns `error`/`unknown command`, which the script handles).
- `motor_debug.py` takes off, samples `pitch`/`roll` from telemetry, and infers
  the dead motor from tilt direction (the drone tips *toward* the dead corner).

**Watch out — motor numbering is inconsistent across files.** `README.md` uses
**M0–M3** (M0 = rear-left CCW = the diagnosed faulty motor). `motor_debug.py`
uses **M1–M4** (M1 = front-left). They describe the same physical layout with
different labels; reconcile against the README diagram, which is the canonical
one, when touching motor code.

## Reference docs (not code)

`docs/LIBRARIES.md`, `docs/IDEAS.md`, `docs/ALTERNATIVES.md`, `docs/FLIX-BUILD.md`
are research notes. Notably, `docs/LIBRARIES.md` points to **DJITelloPy** as the production-grade
library that would replace this raw-socket code if reliability over learning
becomes the priority.
