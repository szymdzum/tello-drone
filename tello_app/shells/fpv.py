"""
shells/fpv.py — fly the Tello from the keyboard with a live video window (OpenCV).

OpenCV both shows the video and reads the keys (cv2.waitKey), with a HUD drawn
over the frame. The flight brain (keymap, FlightController, ActionRunner) lives
in tello_app.flight; video decode in tello_app.video. Launch via:
    python drone.py
Click the video window so it has keyboard focus, then fly.

Controls:
    W / S  forward / back          A / D  strafe left / right
    I / K  up / down (throttle)    J / L  yaw left / right
    t takeoff   g land   f flip   h hover   y / u  slower / faster
    SPACE = EMERGENCY (drops!)               Esc / q = quit (lands first)

Requires opencv-python (cv2) + numpy. Video decode runs on a background thread
so a decode hiccup can't stall the control loop; the GUI stays on the main
thread (required on macOS).
"""
import time

import cv2
import numpy as np

from tello_app.flight import hud
from tello_app.flight.controller import RATE_S, ActionRunner, FlightController
from tello_app.tello import Tello, TelloError
from tello_app.video.stream import VideoStream

GREEN, AMBER, RED = (0, 255, 0), (0, 200, 255), (0, 80, 255)
WHITE, GREY = (255, 255, 255), (190, 190, 190)
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _text(frame, text: str, org: tuple[int, int], scale: float, color,
          thick: int = 1) -> int:
    """Text with a subtle 1-px drop shadow (readable over video, no 'glow').
    Returns the rendered width so callers can lay out runs side by side."""
    x, y = org
    cv2.putText(frame, text, (x + 1, y + 1), FONT, scale, (0, 0, 0), thick, cv2.LINE_AA)
    cv2.putText(frame, text, org, FONT, scale, color, thick, cv2.LINE_AA)
    return cv2.getTextSize(text, FONT, scale, thick)[0][0]


def _width(text: str, scale: float, thick: int = 1) -> int:
    return cv2.getTextSize(text, FONT, scale, thick)[0][0]


def _gauge(frame, label: str, value: str, x: int, y: int, color,
           align_right_to: int | None = None) -> None:
    """A small grey label with a bigger value next to it; optionally right-aligned."""
    if align_right_to is not None:
        x = align_right_to - (_width(label, 0.45) + 6 + _width(value, 0.6, 2))
    x += _text(frame, label, (x, y), 0.45, GREY) + 6
    _text(frame, value, (x, y), 0.6, color, 2)


def _battery_color(level: int | None):
    if level is None:
        return GREY
    return RED if level <= 20 else AMBER if level <= 50 else GREEN


def _draw_overlay(frame, drone: Tello, fc: FlightController,
                  status: str, rc: tuple[int, int, int, int]) -> None:
    h, w = frame.shape[:2]
    parts = dict(hud.telemetry_parts(drone, fc))
    mid_y = h // 2

    # Corners and edges, aviation-style: battery top-left, flight state
    # top-center, speed tape left edge, altitude tape right edge.
    _gauge(frame, "BAT", parts["battery"], 12, 28, _battery_color(hud.battery_level(drone)))
    state = "AIRBORNE" if fc.flying else "GROUNDED"
    _text(frame, state, ((w - _width(state, 0.55, 2)) // 2, 28), 0.55,
          GREEN if fc.flying else GREY, 2)
    _gauge(frame, "SPD", parts["speed"], 12, mid_y, WHITE)
    _gauge(frame, "ALT", parts["alt"], 0, mid_y, WHITE, align_right_to=w - 12)

    # Center crosshair — a fixed aim reference while translating/yawing.
    cv2.drawMarker(frame, (w // 2, mid_y), GREY, cv2.MARKER_CROSS, 18, 1, cv2.LINE_AA)

    # Bottom: help bottom-left, rc vector bottom-right, status centered above.
    base = h - 14
    for i, line in enumerate(reversed(hud.HELP_LINES)):
        _text(frame, line, (12, base - i * 16), 0.42, GREY)
    rc_text = hud.rc_line(rc)
    _text(frame, rc_text, (w - 12 - _width(rc_text, 0.5), base), 0.5, WHITE)
    if status:
        _text(frame, status, ((w - _width(status, 0.55, 2)) // 2,
                              base - len(hud.HELP_LINES) * 16 - 10), 0.55, AMBER, 2)


def fly(drone: Tello, video: VideoStream, fc: FlightController) -> None:
    runner = ActionRunner(drone, fc)
    runner.last_result = "press 't' to take off"
    win = "Tello FPV"
    cv2.namedWindow(win)
    last_rc = last_hb = 0.0
    try:
        while True:
            now = time.time()
            frame = video.read()
            if frame is None:
                frame = np.zeros((360, 640, 3), dtype=np.uint8)
                cv2.putText(frame, "waiting for video...", (20, 180),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)

            lr, fb, ud, yaw = fc.tick(now)
            _draw_overlay(frame, drone, fc, runner.display(), (lr, fb, ud, yaw))
            cv2.imshow(win, frame)

            key = cv2.waitKey(1) & 0xFF  # also pumps the GUI; 255 == no key
            if key != 255:
                action = fc.handle_key(key, now)
                if action == "quit":
                    break
                if action:
                    runner.submit(action)  # worker thread; rc stream never stalls

            if fc.flying and now - last_rc >= RATE_S:
                drone.send_rc(lr, fb, ud, yaw)
                last_rc = now
            elif not fc.flying and now - last_hb > 2.0:
                drone.send_rc(0, 0, 0, 0)  # slow heartbeat keeps the link awake
                last_hb = now
    finally:
        if fc.flying:
            try:
                drone.send_rc(0, 0, 0, 0)
                drone.land()
            except TelloError:
                pass
        cv2.destroyAllWindows()


def run(drone: Tello) -> None:
    """FPV session on an already-connected drone: stream on, fly, stream off."""
    video = None
    try:
        print("Starting video stream...")
        drone.stream_on()
        time.sleep(2)  # let the H.264 stream come up
        video = VideoStream()
        print(f"Video decoder: {video.backend}"
              + ("" if video.backend == "pyav" else "  (pip install av for lower latency)"))
        video.start()
        fc = FlightController()
        print("Click the video window to give it focus, then fly. ESC to quit.")
        fly(drone, video, fc)
    finally:
        if video is not None:
            video.stop()
        if drone.connected:  # skip when aborted mid-connect — would block 10s
            try:
                drone.send_command("streamoff", timeout=2)
            except Exception:
                pass
