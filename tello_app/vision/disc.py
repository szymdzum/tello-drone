"""
vision/disc.py — background detector for dark-blue floor discs (the Warhammer
objective markers), latest-detection-wins.

Classic CV, no ML — calibrated against real Tello captures of the discs on
the actual floor (2026-06-12 survey flight, 17/22 frames):
  1. HSV mask: blue-ish hue, some saturation, darker than the wood floor.
  2. Contour filters: minimum area, not touching the frame edge, and
     fill >= FILL_MIN — discs are SOLID ellipses; shadows, glare patches,
     the Roomba, and wall blobs all came out hollow or edge-clipped.
  3. Perspective gate: a circle lying on the floor appears flatter the
     closer it is to the horizon. Roundness above the line's allowance
     means the blob is NOT on the floor (rejected a disc-colored flower
     on a curtain). Assumes mission altitude ~1.2-1.5 m, like the survey.

Same threading pattern as face/marker detectors. No IDs — all discs look
alike; nearest (largest) wins, the full list is available for the HUD.
"""
import threading
import time

import cv2
import numpy as np

DETECT_PERIOD_S = 0.07
MAX_AGE_S = 0.5

HSV_LO = np.array((85, 25, 15), np.uint8)     # blue-ish, minimally saturated, dark
HSV_HI = np.array((145, 255, 150), np.uint8)
MIN_AREA = 250            # px^2 — below this a disc is too far to steer at
FILL_MIN = 0.78           # contour area / fitted-ellipse area: discs are solid
AR_MIN = 0.12             # flatter than this is a baseboard shadow / sliver
# Perspective gate: max allowed roundness grows linearly from the horizon
# (y ~= HORIZON_FRAC of frame height) to the bottom edge.
HORIZON_FRAC = 0.52
AR_SLACK = 0.18           # allowance above the ideal perspective line


class DiscDetector:
    """Largest floor disc in the newest frame, on a worker thread."""

    def __init__(self, video, log=None) -> None:
        self._video = video
        self._log = log
        self._lock = threading.Lock()
        self._det: tuple[float, float, float] | None = None  # cx, cy, w (fractions)
        self._boxes: list[tuple[int, int, int, int]] = []    # all discs, full-res px
        self._at = 0.0
        self._running = False

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._running = False

    def latest(self, max_age: float = MAX_AGE_S) -> tuple[float, float, float] | None:
        """Nearest disc as frame fractions, or None if stale/absent."""
        with self._lock:
            if self._det is None or time.monotonic() - self._at > max_age:
                return None
            return self._det

    def boxes(self, max_age: float = MAX_AGE_S) -> list[tuple[int, int, int, int]]:
        """All current disc boxes (px), nearest first, for HUD drawing."""
        with self._lock:
            if time.monotonic() - self._at > max_age:
                return []
            return list(self._boxes)

    @staticmethod
    def _max_roundness(cy_px: int, frame_h: int) -> float:
        """Perspective allowance: how round may a FLOOR disc be at this image
        row. 0 at the horizon, growing toward the bottom edge, plus slack."""
        span = frame_h * (1 - HORIZON_FRAC)
        below = max(0.0, cy_px - frame_h * HORIZON_FRAC)
        return (below / span) + AR_SLACK

    def _detect(self, frame) -> list[tuple[tuple[float, float, float],
                                           tuple[int, int, int, int]]]:
        """Pure detection: [(det, bbox)] sorted nearest-first. Unit-testable."""
        H, W = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, HSV_LO, HSV_HI)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        found = []
        for c in cnts:
            area = cv2.contourArea(c)
            if area < MIN_AREA or len(c) < 5:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1:
                continue  # clipped blob: shape statistics are meaningless
            (_, _), (ma_a, ma_b), _ = cv2.fitEllipse(c)
            fill = area / (np.pi * ma_a * ma_b / 4 + 1e-6)
            ar = min(ma_a, ma_b) / max(ma_a, ma_b)
            if fill < FILL_MIN or ar < AR_MIN:
                continue
            if ar > self._max_roundness(y + h // 2, H):
                continue  # too round for its distance: not lying on the floor
            det = ((x + w / 2) / W, (y + h / 2) / H, w / W)
            found.append((area, det, (x, y, w, h)))
        found.sort(key=lambda f: f[0], reverse=True)
        return [(det, box) for _, det, box in found]

    def _loop(self) -> None:
        while self._running:
            frame = self._video.read()
            if frame is None:
                time.sleep(DETECT_PERIOD_S)
                continue
            discs = self._detect(frame)
            if discs:
                det, _ = discs[0]
                with self._lock:
                    self._det = det
                    self._boxes = [box for _, box in discs]
                    self._at = time.monotonic()
                if self._log is not None:
                    self._log.event("disc", n=len(discs), cx=round(det[0], 3),
                                    cy=round(det[1], 3), w=round(det[2], 3))
            time.sleep(DETECT_PERIOD_S)
