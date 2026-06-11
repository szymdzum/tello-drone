#!/usr/bin/env python3
"""
Tests for hud.py — the HUD data layer. The important one is anti-drift: every
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

    def test_help_is_ascii_only(self):
        """OpenCV's Hershey fonts render non-ASCII as '?'."""
        self.assertTrue(all(line.isascii() for line in hud.HELP_LINES))


class TestSnapshot(unittest.TestCase):
    def test_full_state(self):
        drone = MagicMock()
        drone.state = {"bat": 68, "h": 132, "tof": 72, "temph": 37, "time": 84,
                       "pitch": 5, "roll": -3, "yaw": 124,
                       "vgx": 4, "vgy": 3, "vgz": 0}
        snap = hud.snapshot(drone, FlightController(speed=60))
        self.assertEqual(snap["bat"], 68)
        self.assertEqual(snap["alt"], 132)
        self.assertEqual(snap["yaw"], 124)
        self.assertEqual(snap["speed"], 60)
        self.assertAlmostEqual(snap["vel"], 0.5)  # sqrt(4^2+3^2) dm/s -> m/s
        self.assertFalse(snap["flying"])
        self.assertFalse(snap["emergency"])

    def test_empty_state_defaults(self):
        drone = MagicMock()
        drone.state = {}
        snap = hud.snapshot(drone, FlightController())
        self.assertIsNone(snap["bat"])
        self.assertIsNone(snap["vel"])
        self.assertEqual((snap["pitch"], snap["roll"], snap["yaw"]), (0, 0, 0))

    def test_emergency_flag_flows_through(self):
        drone = MagicMock()
        drone.state = {}
        fc = FlightController()
        fc.emergency = True
        self.assertTrue(hud.snapshot(drone, fc)["emergency"])


if __name__ == "__main__":
    unittest.main()
