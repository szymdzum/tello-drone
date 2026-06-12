#!/usr/bin/env python3
"""
Tests for the floor-disc detector, against REAL Tello camera frames from the
2026-06-12 survey flight (tests/fixtures/). The regression fixtures encode the
calibration findings: solid-fill separates discs from shadows/glare/Roomba,
and the perspective gate rejects disc-colored blobs that aren't on the floor.
"""

import os
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tello_app.vision.disc import DiscDetector  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    img = cv2.imread(os.path.join(FIXTURES, name))
    assert img is not None, f"missing fixture {name}"
    return img


class TestDiscDetection(unittest.TestCase):
    def setUp(self):
        self.det = DiscDetector(video=None)  # _detect is pure; no thread

    def test_near_disc_found_and_roomba_ignored(self):
        # bedroom frame: disc right-of-center, Roomba (dark circle) at left
        discs = self.det._detect(load("disc_near_dim.jpg"))
        self.assertEqual(len(discs), 1)
        (cx, cy, w), _ = discs[0]
        self.assertGreater(cx, 0.55)   # the disc — not the Roomba on the left
        self.assertGreater(cy, 0.6)    # lower half of frame (on the floor)

    def test_far_disc_in_bright_room(self):
        # low-saturation lighting: fill criterion carries the detection
        discs = self.det._detect(load("disc_far_bright.jpg"))
        self.assertEqual(len(discs), 1)

    def test_two_discs_nearest_first_curtain_rejected(self):
        """The curtain false positive: a disc-colored flower on fabric is too
        ROUND for its frame height — the perspective gate must reject it."""
        discs = self.det._detect(load("two_discs_curtain.jpg"))
        self.assertEqual(len(discs), 2)
        boxes = [b for _, b in discs]
        self.assertGreater(boxes[0][2], boxes[1][2])  # nearest (widest) first
        for x, y, _w, _h in boxes:
            self.assertFalse(100 <= x <= 200 and 380 <= y <= 470,
                             "curtain region must stay clean")

    def test_no_disc_frame_is_empty(self):
        self.assertEqual(self.det._detect(load("no_disc.jpg")), [])

    def test_perspective_gate_rejects_round_blob_near_horizon(self):
        """Synthetic: the same disc-colored ellipse is valid low in the frame
        but impossible (too round) just below the horizon."""
        def frame_with_ellipse(cy):
            img = np.full((720, 960, 3), (140, 180, 200), np.uint8)  # warm floor
            cv2.ellipse(img, (480, cy), (45, 22), 0, 0, 360, (90, 40, 30), -1)
            return img
        self.assertEqual(len(self.det._detect(frame_with_ellipse(620))), 1)
        self.assertEqual(self.det._detect(frame_with_ellipse(390)), [])

    def test_stale_state_serves_nothing(self):
        self.assertIsNone(self.det.latest())
        self.assertEqual(self.det.boxes(), [])


if __name__ == "__main__":
    unittest.main()
