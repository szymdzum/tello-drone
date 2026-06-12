#!/usr/bin/env python3
"""
Tests for the ArUco marker detector — a real cv2.aruco roundtrip against
synthetic frames (no drone, no camera), plus the geometry it reports.
"""

import os
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tello_app.vision.marker import DICT, MarkerDetector  # noqa: E402


def frame_with_marker(marker_id=0, size=120, x=420, y=300, w=960, h=720):
    """A BGR frame with one marker pasted at (x, y)."""
    d = cv2.aruco.getPredefinedDictionary(DICT)
    img = cv2.aruco.generateImageMarker(d, marker_id, size)
    frame = np.full((h, w), 255, np.uint8)
    frame[y:y + size, x:x + size] = img
    return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)


class TestMarkerDetection(unittest.TestCase):
    def setUp(self):
        self.det = MarkerDetector(video=None)  # _detect is pure; no thread started

    def test_detects_marker_with_correct_geometry(self):
        # 120 px marker centered at (480, 360) in a 960x720 frame
        found = self.det._detect(frame_with_marker(size=120, x=420, y=300))
        assert found is not None
        (cx, cy, w), corners, marker_id = found
        self.assertEqual(marker_id, 0)
        self.assertAlmostEqual(cx, 0.5, places=2)
        self.assertAlmostEqual(cy, 0.5, places=2)
        self.assertAlmostEqual(w, 120 / 960, places=2)
        self.assertEqual(corners.shape, (4, 2))

    def test_empty_frame_returns_none(self):
        blank = np.full((720, 960, 3), 255, np.uint8)
        self.assertIsNone(self.det._detect(blank))

    def test_largest_allowed_marker_wins(self):
        # two allowed markers: id 1 small (far), id 2 large (near) — near wins
        det = MarkerDetector(video=None, ids=(1, 2))
        frame = frame_with_marker(marker_id=1, size=60, x=100, y=100)
        d = cv2.aruco.getPredefinedDictionary(DICT)
        big = cv2.aruco.generateImageMarker(d, 2, 200)
        frame[400:600, 600:800] = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
        found = det._detect(frame)
        assert found is not None
        self.assertEqual(found[2], 2)

    def test_unknown_id_is_rejected(self):
        """The phantom-marker incident: scene texture decoded as id 17 and the
        controller chased it. Only allowlisted ids may steer."""
        frame = frame_with_marker(marker_id=17, size=120)
        self.assertIsNone(self.det._detect(frame))  # default allowlist = {0}

    def test_phantom_never_outranks_the_real_marker(self):
        # big id-17 phantom + small real id-0: the real one must win
        frame = frame_with_marker(marker_id=0, size=80, x=120, y=120)
        d = cv2.aruco.getPredefinedDictionary(DICT)
        phantom = cv2.aruco.generateImageMarker(d, 17, 240)
        frame[380:620, 560:800] = cv2.cvtColor(phantom, cv2.COLOR_GRAY2BGR)
        found = self.det._detect(frame)
        assert found is not None
        self.assertEqual(found[2], 0)

    def test_no_detection_served_when_stale(self):
        self.assertIsNone(self.det.latest())
        self.assertIsNone(self.det.corners())


if __name__ == "__main__":
    unittest.main()
