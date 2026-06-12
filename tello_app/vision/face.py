"""
vision/face.py — background face detector, latest-detection-wins.

Same threading pattern as video/stream.py: detection runs on its own daemon
thread pulling frames from a VideoStream, so a slow detect can never stall
the control loop. Haar cascade — ships inside opencv-python, no model
download. Consumers read via latest()/box(), which return None once the
newest detection is older than max_age (a stale fix must not steer).
"""
import threading
import time

import cv2

DETECT_PERIOD_S = 0.07  # ~14 Hz — plenty for following, cheap on CPU
SCALE = 0.5             # detect on a half-res copy
MAX_AGE_S = 0.5


class FaceDetector:
    """Detects the largest face in the newest video frame on a worker thread."""

    def __init__(self, video, log=None) -> None:
        self._video = video
        self._log = log
        # cv2's stubs don't declare the data submodule
        haar_dir = cv2.data.haarcascades  # pyright: ignore[reportAttributeAccessIssue]
        self._cascade = cv2.CascadeClassifier(
            haar_dir + "haarcascade_frontalface_default.xml")
        self._lock = threading.Lock()
        self._det: tuple[float, float, float] | None = None  # cx, cy, w (fractions)
        self._box: tuple[int, int, int, int] | None = None   # x, y, w, h (full-res px)
        self._at = 0.0
        self._running = False

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._running = False

    def latest(self, max_age: float = MAX_AGE_S) -> tuple[float, float, float] | None:
        """Newest detection as frame fractions, or None if stale/absent."""
        with self._lock:
            if self._det is None or time.monotonic() - self._at > max_age:
                return None
            return self._det

    def box(self, max_age: float = MAX_AGE_S) -> tuple[int, int, int, int] | None:
        """Newest detection as a full-res pixel box, for HUD drawing."""
        with self._lock:
            if self._box is None or time.monotonic() - self._at > max_age:
                return None
            return self._box

    def _loop(self) -> None:
        while self._running:
            frame = self._video.read()
            if frame is None:
                time.sleep(DETECT_PERIOD_S)
                continue
            small = cv2.resize(frame, None, fx=SCALE, fy=SCALE)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = self._cascade.detectMultiScale(gray, scaleFactor=1.2,
                                                   minNeighbors=5, minSize=(24, 24))
            if len(faces):
                # Largest face wins: the nearest person is the one to follow.
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                fh, fw = small.shape[:2]
                det = ((x + w / 2) / fw, (y + h / 2) / fh, w / fw)
                with self._lock:
                    self._det = det
                    self._box = (int(x / SCALE), int(y / SCALE),
                                 int(w / SCALE), int(h / SCALE))
                    self._at = time.monotonic()
                if self._log is not None:
                    self._log.event("det", cx=round(det[0], 3),
                                    cy=round(det[1], 3), w=round(det[2], 3))
            time.sleep(DETECT_PERIOD_S)
