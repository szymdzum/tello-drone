#!/usr/bin/env python3
"""
Tests for fpv.py's twin-stick keymap, driven through the shared FlightController.
No cv2 window, no drone. (Importing fpv does import cv2, which the venv has.)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fpv  # noqa: E402
from keyboard_control import FlightController  # noqa: E402


def controller(speed=40):
    return FlightController(speed=speed, moves=fpv.FPV_MOVES, discretes=fpv.FPV_DISCRETES)


class TestFpvMovementMap(unittest.TestCase):
    def test_wasd_is_throttle_and_yaw(self):
        fc = controller(50)
        fc.handle_key(ord("w"), 0.0)  # up
        fc.handle_key(ord("d"), 0.0)  # yaw right
        lr, fb, ud, yaw = fc.tick(0.0)
        self.assertEqual((ud, yaw), (50, 50))
        self.assertEqual((lr, fb), (0, 0))

    def test_ijkl_is_pitch_and_roll(self):
        fc = controller(50)
        fc.handle_key(ord("i"), 0.0)  # forward
        fc.handle_key(ord("j"), 0.0)  # left
        lr, fb, ud, yaw = fc.tick(0.0)
        self.assertEqual((fb, lr), (50, -50))
        self.assertEqual((ud, yaw), (0, 0))

    def test_down_and_back_are_negative(self):
        fc = controller(30)
        fc.handle_key(ord("s"), 0.0)  # down
        fc.handle_key(ord("k"), 0.0)  # back
        lr, fb, ud, yaw = fc.tick(0.0)
        self.assertEqual((ud, fb), (-30, -30))


class TestFpvDiscretes(unittest.TestCase):
    def test_discrete_actions(self):
        fc = controller()
        self.assertEqual(fc.handle_key(ord("t"), 0.0), "takeoff")
        self.assertEqual(fc.handle_key(ord("g"), 0.0), "land")
        self.assertEqual(fc.handle_key(ord("f"), 0.0), "flip")
        self.assertEqual(fc.handle_key(ord(" "), 0.0), "emergency")
        self.assertEqual(fc.handle_key(27, 0.0), "quit")  # Esc

    def test_movement_keys_are_not_also_discretes(self):
        # the two clusters must not collide with command keys
        self.assertFalse(set(fpv.FPV_MOVES) & set(fpv.FPV_DISCRETES))

    def test_hover_key_zeros_velocity(self):
        fc = controller(60)
        fc.handle_key(ord("i"), 0.0)
        self.assertIsNone(fc.handle_key(ord("h"), 0.0))  # hover is local-only
        self.assertEqual(fc.tick(0.0), (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
