#!/usr/bin/env python3
"""
Tests for the FPV shell. It reuses the shared keymap (FlightController's
defaults) and picks a video decode backend. No cv2 window, no drone. Importing
the shell pulls in cv2/av/numpy, which the venv has.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tello_app.flight.controller import FlightController  # noqa: E402
from tello_app.shells import fpv  # noqa: E402


class TestVideoBackend(unittest.TestCase):
    def test_a_backend_is_selected(self):
        # Construction is cheap (no stream opened until start()).
        self.assertIn(fpv.VideoStream().backend, ("pyav", "opencv"))


class TestUnifiedScheme(unittest.TestCase):
    """fpv flies with the shared default map:
    WASD = horizontal, IJKL = throttle + yaw."""

    def test_wasd_horizontal_ijkl_throttle_and_yaw(self):
        fc = FlightController(speed=50)  # default = unified MOVES
        fc.handle_key(ord("w"), 0.0)  # forward
        fc.handle_key(ord("d"), 0.0)  # strafe right
        fc.handle_key(ord("i"), 0.0)  # up (throttle)
        fc.handle_key(ord("l"), 0.0)  # yaw right
        self.assertEqual(fc.tick(0.0), (50, 50, 50, 50))  # (lr, fb, ud, yaw)

    def test_left_and_negative_axes(self):
        fc = FlightController(speed=40)
        fc.handle_key(ord("a"), 0.0)  # strafe left
        fc.handle_key(ord("k"), 0.0)  # down
        fc.handle_key(ord("j"), 0.0)  # yaw left
        self.assertEqual(fc.tick(0.0), (-40, 0, -40, -40))

    def test_discrete_keys(self):
        fc = FlightController()
        self.assertEqual(fc.handle_key(ord("t"), 0.0), "takeoff")
        self.assertEqual(fc.handle_key(ord("g"), 0.0), "land")
        self.assertEqual(fc.handle_key(ord("f"), 0.0), "flip")
        self.assertEqual(fc.handle_key(ord(" "), 0.0), "emergency")
        self.assertEqual(fc.handle_key(27, 0.0), "quit")  # Esc

    def test_fpv_defines_no_private_keymap(self):
        # The whole point of unification: fpv must not re-declare keys.
        self.assertFalse(hasattr(fpv, "FPV_MOVES"))
        self.assertFalse(hasattr(fpv, "FPV_DISCRETES"))


class TestOverlayRender(unittest.TestCase):
    def test_draw_overlay_renders_without_error(self):
        import numpy as np
        drone = MagicMock()
        drone.state = {"bat": 92, "h": 0}
        frame = np.zeros((360, 480, 3), dtype=np.uint8)
        fpv._draw_overlay(frame, drone, FlightController(), "press 't' to take off",
                          (0, 0, 0, 0))
        self.assertTrue(frame.any())  # something was drawn onto the black frame

    def test_battery_color_thresholds(self):
        self.assertEqual(fpv._battery_color(92), fpv.GREEN)
        self.assertEqual(fpv._battery_color(50), fpv.AMBER)
        self.assertEqual(fpv._battery_color(15), fpv.RED)
        self.assertEqual(fpv._battery_color(None), fpv.GREY)  # no telemetry yet


if __name__ == "__main__":
    unittest.main()
