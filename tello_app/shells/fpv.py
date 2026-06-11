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
from tello_app.flight.controller import (
    RATE_S,
    ActionRunner,
    FlightController,
    _do_action,
)
from tello_app.shells import hud_render
from tello_app.tello import Tello
from tello_app.video.stream import VideoStream


def _draw_overlay(frame, drone: Tello, fc: FlightController,
                  status: str, rc: tuple[int, int, int, int]) -> None:
    """Thin glue: collect a telemetry snapshot, hand it to the HUD renderer."""
    hud_render.draw(frame, hud.snapshot(drone, fc), rc, status)


def fly(drone: Tello, video: VideoStream, fc: FlightController) -> None:
    runner = ActionRunner(drone, fc)
    runner.last_result = "press 't' to take off"
    win = "Tello FPV"
    cv2.namedWindow(win)
    last_rc = 0.0
    # Boot screen rendered once; reused (copied) until the first frame decodes.
    boot = np.zeros((720, 960, 3), dtype=np.uint8)
    hud_render.draw_connecting(boot)
    try:
        while True:
            now = time.time()
            frame = video.read()
            if frame is None:
                frame = boot.copy()
            lr, fb, ud, yaw = fc.tick(now)
            # HUD draws on the boot screen too — keys are live, never fly blind.
            _draw_overlay(frame, drone, fc, runner.display(), (lr, fb, ud, yaw))
            cv2.imshow(win, frame)

            key = cv2.waitKey(1) & 0xFF  # also pumps the GUI; 255 == no key
            if key != 255:
                action = fc.handle_key(key, now)
                if action == "quit":
                    break
                if action:
                    runner.submit(action)  # worker thread; rc stream never stalls

            # Sticks stream while airborne; grounded, Tello.start_keepalive owns the link.
            if fc.flying and now - last_rc >= RATE_S:
                drone.send_rc(lr, fb, ud, yaw)
                last_rc = now
    finally:
        if fc.flying:
            try:
                _do_action(drone, fc, "land")  # same land path as pressing 'g'
            except OSError:
                pass
        cv2.destroyAllWindows()


def run(drone: Tello) -> None:
    """FPV session on an already-connected drone: stream on, fly, stream off."""
    video = None
    try:
        print("Starting video stream...")
        drone.stream_on()
        video = VideoStream()  # no settle sleep: both backends retry until the stream is up
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
