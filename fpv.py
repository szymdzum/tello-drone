#!/usr/bin/env python3
"""
fpv.py — fly the Tello from the keyboard with a live video window (OpenCV).

Like keyboard_control.py but with the camera feed: OpenCV both shows the video
and reads the keys (cv2.waitKey), with a HUD drawn over the frame. The flight
logic (FlightController) and command execution (_do_action) are reused from
keyboard_control.py — only the I/O shell changes.

Connect to the Tello Wi-Fi, then:
    python fpv.py
Click the video window so it has keyboard focus, then fly.

Twin-stick (Mode-2) layout — one hand on each cluster:
    LEFT  (WASD)   W/S up/down (throttle)    A/D yaw left/right
    RIGHT (IJKL)   I/K forward/back          J/L strafe left/right
    t takeoff   g land   f flip   h hover   - / = slower/faster
    SPACE = EMERGENCY (drops!)               ESC = quit (lands first)

Requires opencv-python (cv2) + numpy. Video decode runs on a background thread
so a decode hiccup can't stall the control loop; the GUI stays on the main
thread (required on macOS).
"""
import os
import sys
import threading
import time

import cv2
import numpy as np

try:
    import av  # PyAV — lower-latency H.264 decode than cv2's FFMPEG capture
    _HAVE_AV = True
except ImportError:
    _HAVE_AV = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from keyboard_control import ActionRunner, FlightController, warn_if_awdl_active  # noqa: E402
from tello import Tello, TelloError  # noqa: E402

RATE_S = 0.05  # rc stream period (~20 Hz)

# Twin-stick map: WASD = throttle + yaw, IJKL = pitch + roll.
FPV_MOVES = {
    ord("w"): ("ud", +1), ord("s"): ("ud", -1),   # throttle up / down
    ord("a"): ("yaw", -1), ord("d"): ("yaw", +1),  # yaw left / right
    ord("i"): ("fb", +1), ord("k"): ("fb", -1),    # forward / back
    ord("j"): ("lr", -1), ord("l"): ("lr", +1),    # strafe left / right
}
FPV_DISCRETES = {
    ord("t"): "takeoff",
    ord("g"): "land",
    ord("f"): "flip",
    ord("h"): "hover",
    ord(" "): "emergency",
    27: "quit",  # Esc
    ord("-"): "speed_down", ord("_"): "speed_down",
    ord("="): "speed_up", ord("+"): "speed_up",
}

# Same FFmpeg tuning as video_stream.py — large probesize/analyzeduration so the
# decoder waits for a keyframe with SPS/PPS before decoding (avoids PPS spam).
CAP_OPTIONS = "timeout;10000000|analyzeduration;6000000|probesize;6000000"
CAP_URL = "udp://0.0.0.0:11111?overrun_nonfatal=1&fifo_size=50000000"


AV_URL = "udp://@0.0.0.0:11111"


class VideoStream:
    """Background H.264 reader with latest-frame-wins delivery.

    Prefers PyAV (what DJITelloPy switched to in 2.5.0 to cut the ~1 s latency of
    cv2's FFMPEG capture); falls back to cv2.VideoCapture when `av` isn't
    installed. Either way decoding runs on its own daemon thread and only the
    newest frame is kept, so decode hiccups can never stall the control loop."""

    def __init__(self) -> None:
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self.backend = "pyav" if _HAVE_AV else "opencv"

    def start(self) -> None:
        self._running = True
        target = self._loop_av if _HAVE_AV else self._loop_cv2
        threading.Thread(target=target, daemon=True).start()

    def _loop_av(self) -> None:
        while self._running:
            try:
                container = av.open(AV_URL, timeout=(5, None))
                for frame in container.decode(video=0):
                    if not self._running:
                        break
                    arr = frame.to_ndarray(format="bgr24")
                    with self._lock:
                        self._frame = arr
                container.close()
            except Exception:
                time.sleep(1)  # stream hiccup / not up yet — reopen

    def _loop_cv2(self) -> None:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = CAP_OPTIONS
        cap = cv2.VideoCapture(CAP_URL, cv2.CAP_FFMPEG)
        fails = 0
        while self._running:
            ok, frame = cap.read()
            if not ok:
                fails += 1
                if fails > 30:  # stream stalled — rebuild the capture
                    cap.release()
                    time.sleep(1)
                    cap = cv2.VideoCapture(CAP_URL, cv2.CAP_FFMPEG)
                    fails = 0
                continue
            fails = 0
            with self._lock:
                self._frame = frame
        cap.release()

    def read(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self) -> None:
        self._running = False


def _draw_overlay(frame, drone: Tello, fc: FlightController,
                  status: str, rc: tuple[int, int, int, int]) -> None:
    st = drone.state
    h = frame.shape[0]
    green, amber, grey = (0, 255, 0), (0, 200, 255), (200, 200, 200)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame, f"battery {st.get('bat', '?')}%   alt {st.get('h', '?')}cm   "
                f"speed {fc.speed}   flying {fc.flying}",
                (10, 24), font, 0.55, green, 1, cv2.LINE_AA)
    cv2.putText(frame, f"rc  lr={rc[0]:+d} fb={rc[1]:+d} ud={rc[2]:+d} yaw={rc[3]:+d}",
                (10, 46), font, 0.55, green, 1, cv2.LINE_AA)
    cv2.putText(frame, f"status: {status}", (10, h - 38), font, 0.55, amber, 1, cv2.LINE_AA)
    cv2.putText(frame, "WASD throttle/yaw  IJKL move  t/g takeoff/land  f flip  "
                "SPACE=STOP  ESC quit",
                (10, h - 14), font, 0.42, grey, 1, cv2.LINE_AA)


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


def main() -> None:
    warn_if_awdl_active()
    print("Connecting to Tello (be on its Wi-Fi)...")
    drone = Tello()
    video = None
    try:
        drone.connect(retries=3)
        print("Connected — starting video stream...")
        drone.stream_on()
        time.sleep(2)  # let the H.264 stream come up
        video = VideoStream()
        print(f"Video decoder: {video.backend}"
              + ("" if video.backend == "pyav" else "  (pip install av for lower latency)"))
        video.start()
        fc = FlightController(moves=FPV_MOVES, discretes=FPV_DISCRETES)
        print("Click the video window to give it focus, then fly. ESC to quit.")
        fly(drone, video, fc)
    except TelloError as e:
        print(f"Connection/stream failed: {e}")
        print("On the Tello Wi-Fi? Drone powered on?")
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        if video is not None:
            video.stop()
        if drone.connected:  # skip when aborted mid-connect — would block 10s
            try:
                drone.send_command("streamoff", timeout=2)
            except Exception:
                pass
        drone.close()
    print("Landed, stream off, disconnected.")


if __name__ == "__main__":
    main()
