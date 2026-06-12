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
    p = follow face   m = marker hold (any stick key = manual override)
    SPACE = EMERGENCY (drops!)               Esc / q = quit (lands first)

Requires opencv-python (cv2) + numpy. Video decode runs on a background thread
so a decode hiccup can't stall the control loop; the GUI stays on the main
thread (required on macOS).
"""
import os
import time

import cv2
import numpy as np

from tello_app.flight import hud
from tello_app.flight.controller import (
    RATE_S,
    ActionRunner,
    CrashMonitor,
    FlightController,
)
from tello_app.flight.tracking import FaceFollower, drift_correction, marker_holder
from tello_app.shells import hud_render
from tello_app.tello import Tello
from tello_app.video.stream import VideoStream
from tello_app.vision.face import FaceDetector
from tello_app.vision.marker import MarkerDetector


def _save_snapshot(video: VideoStream, drone: Tello) -> str | None:
    """Save the newest RAW camera frame (no HUD) to captures/ — dataset
    collection for detector development. Returns the path, or None if the
    video link hasn't produced a frame yet."""
    frame = video.read()  # fresh copy from the decoder, never the HUD-drawn one
    if frame is None:
        return None
    os.makedirs("captures", exist_ok=True)
    path = time.strftime("captures/cap_%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}.jpg"
    cv2.imwrite(path, frame)
    drone.log.event("capture", path=path)
    return path


def _draw_overlay(frame, drone: Tello, fc: FlightController,
                  status: str, rc: tuple[int, int, int, int],
                  face_locked: bool = False, down_hint: bool = False) -> None:
    """Thin glue: collect a telemetry snapshot, hand it to the HUD renderer."""
    hud_render.draw(frame, hud.snapshot(drone, fc), rc, status,
                    face_locked, down_hint)


def fly(drone: Tello, video: VideoStream, fc: FlightController) -> None:
    runner = ActionRunner(drone, fc)
    detector = FaceDetector(video, log=drone.log)
    detector.start()
    markers = MarkerDetector(video, log=drone.log)
    markers.start()
    follower = FaceFollower()
    holder = marker_holder()
    monitor = CrashMonitor()
    was_autopilot = None
    was_down = False
    runner.last_result = "press 't' to take off"
    win = "Tello FPV"
    cv2.namedWindow(win)
    last_rc = 0.0
    # Boot screen rendered once; reused (copied) until the first frame decodes.
    boot = np.zeros((720, 960, 3), dtype=np.uint8)
    hud_render.draw_connecting(boot)
    try:
        while True:
            # monotonic: an NTP wall-clock jump must not freeze axis decay
            # or zero the sticks mid-flight.
            now = time.monotonic()
            frame = video.read()
            if frame is None:
                frame = boot.copy()
            lr, fb, ud, yaw = fc.tick(now)
            det = detector.latest()
            mdet = markers.latest()
            if fc.autopilot != was_autopilot:
                # Fresh engagement BEFORE steering: marker hold captures its
                # distance setpoint from the first detection it sees.
                if fc.autopilot == "marker":
                    holder.reset()
                elif fc.autopilot == "follow":
                    follower.reset()
                drone.log.event("mode", autopilot=fc.autopilot)
                was_autopilot = fc.autopilot
            # Autopilot only steers airborne and never during a commanded
            # landing (fc.landing is set the instant 'g' is submitted, before
            # the worker runs — the same freeze manual steering gets).
            ap = fc.autopilot if fc.flying and not fc.landing else None
            if ap == "follow":
                lr, fb, ud, yaw = follower.update(det, now)
            elif ap == "marker":
                lr, fb, ud, yaw = holder.update(mdet, now)
            damping = False
            if (ap is None and fc.flying and not fc.landing
                    and (lr, fb, ud, yaw) == (0, 0, 0, 0)
                    and drone.state_age() <= 0.5):
                # Sticks quiet: counter reported drift instead of streaming
                # pure zeros. Any keypress takes over instantly via tick().
                st = drone.state
                lr, fb, ud, yaw = drift_correction(st.get("vgx"), st.get("vgy"))
                damping = lr != 0 or fb != 0
            # Crash reconciliation: a flip clears fc.flying (stops the rc
            # stream this tick); grounded-looking telemetry only flags the HUD.
            crash_msg = monitor.update(drone, fc, now)
            if crash_msg:
                runner.last_result = crash_msg
                drone.log.event("crash", detail="flipped")
                # Belt and braces: if the detector is wrong and the drone is
                # actually flying, this lands it instead of abandoning it; to
                # a truly motors-cut drone it's a harmless error reply.
                runner.submit("land")
            down = monitor.down_hint(now)
            if down != was_down:
                drone.log.event("down_hint", active=down)
                was_down = down
            box = detector.box()
            if box is not None:
                hud_render.draw_face(frame, box, fc.autopilot == "follow")
            mc = markers.corners()
            if mc is not None:
                quad, mid = mc
                hud_render.draw_marker(frame, quad, fc.autopilot == "marker", mid)
            # Badge lock = the ACTIVE mode's target is in sight.
            locked = (mdet if fc.autopilot == "marker" else det) is not None
            # HUD draws on the boot screen too — keys are live, never fly blind.
            _draw_overlay(frame, drone, fc, runner.display(), (lr, fb, ud, yaw),
                          face_locked=locked, down_hint=down)
            cv2.imshow(win, frame)

            key = cv2.waitKey(1) & 0xFF  # also pumps the GUI; 255 == no key
            if key != 255:
                action = fc.handle_key(key, now)
                if action == "quit":
                    break
                if action == "snapshot":  # shell-side: needs the video stream
                    path = _save_snapshot(video, drone)
                    runner.last_result = f"saved {path}" if path else "no frame yet"
                elif action:
                    runner.submit(action)  # worker thread; rc stream never stalls

            # Sticks stream while airborne; grounded, Tello.start_keepalive owns the link.
            if fc.flying and now - last_rc >= RATE_S:
                src = ap if ap else "damp" if damping else "keys"
                drone.send_rc(lr, fb, ud, yaw, src=src)
                last_rc = now
    finally:
        detector.stop()
        markers.stop()
        # Drain the worker first: a takeoff submitted just before quit must
        # finish (setting fc.flying) before we decide whether to land.
        runner.wait_idle(10)
        if fc.flying:
            runner.submit("land")  # same worker path as pressing 'g'
            runner.wait_idle(20)   # covers both land tries (7 s each) + slack
        cv2.destroyAllWindows()


def run(drone: Tello) -> None:
    """FPV session on an already-connected drone: stream on, fly, stream off."""
    video = None
    try:
        print("Starting video stream...")
        drone.stream_on()
        video = VideoStream(log=drone.log)  # both backends retry until the stream is up
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
