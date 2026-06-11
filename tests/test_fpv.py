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
from tello_app.shells import fpv, hud_render  # noqa: E402


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
    """The arcade HUD must render every state variant without crashing,
    including before any telemetry has arrived (all-None snapshot values)."""

    def _frame(self):
        import numpy as np
        return np.zeros((720, 960, 3), dtype=np.uint8)

    def _render(self, state, flying=False, status="", rc=(0, 0, 0, 0), emergency=False):
        drone = MagicMock()
        drone.state = state
        fc = FlightController()
        fc.flying = flying
        fc.emergency = emergency
        frame = self._frame()
        fpv._draw_overlay(frame, drone, fc, status, rc)
        self.assertTrue(frame.any())  # something was drawn onto the black frame
        return frame

    def test_normal_flight(self):
        self._render({"bat": 68, "h": 132, "tof": 72, "temph": 37, "time": 84,
                      "pitch": 5, "roll": -3, "yaw": 124, "vgx": 4, "vgy": 3, "vgz": 0},
                     flying=True, status="airborne", rc=(20, -40, 60, -80))

    def test_no_telemetry_yet(self):
        self._render({})  # every snapshot value None / level attitude

    def test_low_battery_and_emergency_variants(self):
        self._render({"bat": 14}, flying=True, status="battery low")
        # Emergency is a controller flag, not a status-string parse.
        self._render({"bat": 14}, status="EMERGENCY STOP", emergency=True)

    def test_connecting_screen(self):
        frame = self._frame()
        hud_render.draw_connecting(frame)
        self.assertTrue(frame.any())

    def test_battery_color_thresholds(self):
        self.assertEqual(hud_render._battery_color(92), hud_render.OK)
        self.assertEqual(hud_render._battery_color(50), hud_render.WARN)
        self.assertEqual(hud_render._battery_color(15), hud_render.DANGER)
        self.assertEqual(hud_render._battery_color(None), hud_render.TEXT2)  # no data yet


if __name__ == "__main__":
    unittest.main()
