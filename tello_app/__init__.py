"""
tello_app — a from-scratch Tello controller over raw UDP sockets.

Layout:
    tello.py    — the protocol driver (the only module that talks to the drone)
    flight/     — flight brain: keymap, velocity model, action execution, HUD content
    video/      — H.264 stream decoding (PyAV / OpenCV)
    shells/     — front-ends: fpv (video window + keys), repl (raw SDK / demo)
    util.py     — host-side helpers (macOS AWDL warning)

Entry point: `python drone.py` at the repo root.
"""
from tello_app.tello import Tello, TelloError

__all__ = ["Tello", "TelloError"]
