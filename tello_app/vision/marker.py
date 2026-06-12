"""
vision/marker.py — background ArUco marker detector, latest-detection-wins.

Same threading pattern as vision/face.py: a worker thread pulls the newest
video frame, detects 4x4_50 ArUco markers (one OpenCV call, no ML), and keeps
the largest (= nearest) one. Markers beat faces for navigation: they don't
turn sideways, and detection is near-perfect at trivial CPU cost.

Print docs/marker0.png at ~10 cm — the hold-distance constants in
flight/tracking.py assume that size.
"""
import threading
import time

import cv2
import numpy as np

DICT = cv2.aruco.DICT_4X4_50
DETECT_PERIOD_S = 0.07  # ~14 Hz, same cadence as the face detector
MAX_AGE_S = 0.5


class MarkerDetector:
    """Largest ArUco marker in the newest frame, on a worker thread."""

    def __init__(self, video, log=None) -> None:
        self._video = video
        self._log = log
        self._detector = cv2.aruco.ArucoDetector(
            cv2.aruco.getPredefinedDictionary(DICT),
            cv2.aruco.DetectorParameters())
        self._lock = threading.Lock()
        self._det: tuple[float, float, float] | None = None  # cx, cy, w (fractions)
        self._corners = None         # 4x2 int px, for HUD drawing
        self._id: int | None = None
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

    def corners(self, max_age: float = MAX_AGE_S):
        """Newest detection's (corners, id) in full-res px, for HUD drawing."""
        with self._lock:
            if self._corners is None or self._id is None \
                    or time.monotonic() - self._at > max_age:
                return None
            return self._corners, self._id

    def _detect(self, frame):
        """Pure detection step: (det, corners, id) or None. Unit-testable —
        full-res on purpose, a 10 cm marker at 1 m is only ~60 px wide."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self._detector.detectMarkers(gray)
        if ids is None or not len(corners):
            return None
        quads = [c.reshape(4, 2) for c in corners]
        i = max(range(len(quads)), key=lambda k: cv2.contourArea(quads[k]))
        quad = quads[i]
        fh, fw = gray.shape[:2]
        cx, cy = quad.mean(axis=0)
        side = float(np.mean([np.linalg.norm(quad[k] - quad[(k + 1) % 4])
                              for k in range(4)]))
        det = (float(cx) / fw, float(cy) / fh, side / fw)
        return det, quad.astype(int), int(ids.ravel()[i])

    def _loop(self) -> None:
        while self._running:
            frame = self._video.read()
            if frame is None:
                time.sleep(DETECT_PERIOD_S)
                continue
            found = self._detect(frame)
            if found is not None:
                det, quad, marker_id = found
                with self._lock:
                    self._det = det
                    self._corners = quad
                    self._id = marker_id
                    self._at = time.monotonic()
                if self._log is not None:
                    self._log.event("marker", id=marker_id, cx=round(det[0], 3),
                                    cy=round(det[1], 3), w=round(det[2], 3))
            time.sleep(DETECT_PERIOD_S)
