#!/usr/bin/env python3
"""
Tests for hud.py — the shared HUD content. The important one is anti-drift: every
key in the controller keymap must be documented in the on-screen help, so
a remapped/added key can't silently vanish from the HUD.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tello_app.flight import hud  # noqa: E402
from tello_app.flight.controller import MOVES, FlightController  # noqa: E402


class TestHelpMirrorsKeymap(unittest.TestCase):
    def test_every_movement_key_is_documented(self):
        help_text = " ".join(hud.HELP_LINES).lower()
        for code in MOVES:
            ch = chr(code).lower()
            self.assertIn(ch, help_text, f"movement key {ch!r} missing from HUD help")

    def test_core_action_keys_documented(self):
        help_text = " ".join(hud.HELP_LINES).lower()
        for ch in ("t", "g", "f", "h", "y", "u", "q"):
            self.assertIn(ch, help_text, f"action key {ch!r} missing from HUD help")


class TestContentLines(unittest.TestCase):
    def test_telemetry_line_pulls_state_and_speed(self):
        drone = MagicMock()
        drone.state = {"bat": 64, "h": 80}
        fc = FlightController(speed=40)
        line = hud.telemetry_line(drone, fc)
        self.assertIn("64", line)
        self.assertIn("80", line)
        self.assertIn("40", line)
        self.assertIn("False", line)  # not flying

    def test_rc_line_format(self):
        self.assertEqual(hud.rc_line((1, -2, 3, -4)), "rc  lr=+1 fb=-2 ud=+3 yaw=-4")

    def test_telemetry_line_is_built_from_parts(self):
        """The string and structured views can't drift apart."""
        drone = MagicMock()
        drone.state = {"bat": 64, "h": 80}
        fc = FlightController(speed=40)
        parts = hud.telemetry_parts(drone, fc)
        self.assertEqual(hud.telemetry_line(drone, fc),
                         "   ".join(f"{k} {v}" for k, v in parts))

    def test_battery_level(self):
        drone = MagicMock()
        drone.state = {"bat": 47}
        self.assertEqual(hud.battery_level(drone), 47)
        drone.state = {}
        self.assertIsNone(hud.battery_level(drone))


if __name__ == "__main__":
    unittest.main()
