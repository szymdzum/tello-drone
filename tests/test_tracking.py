#!/usr/bin/env python3
"""
Tests for face-follow: the FaceFollower P-controller (pure math, no cv2) and
the FlightController follow-mode semantics. The safety contracts: any stick
key is an instant manual override, follow never steers a landing drone, and a
lost face means hover — never search.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tello_app.flight import controller as fcmod  # noqa: E402
from tello_app.flight import tracking  # noqa: E402
from tello_app.flight.controller import FlightController  # noqa: E402
from tello_app.flight.tracking import TARGET_W, FaceFollower  # noqa: E402

CENTERED = (0.5, 0.5, TARGET_W)  # on target: nothing to correct


class TestFollowerMath(unittest.TestCase):
    def test_centered_face_at_target_distance_hovers(self):
        self.assertEqual(FaceFollower().update(CENTERED, 0.0), (0, 0, 0, 0))

    def test_face_right_of_center_yaws_right(self):
        _, _, _, yaw = FaceFollower().update((0.8, 0.5, TARGET_W), 0.0)
        self.assertGreater(yaw, 0)

    def test_face_left_of_center_yaws_left(self):
        _, _, _, yaw = FaceFollower().update((0.2, 0.5, TARGET_W), 0.0)
        self.assertLess(yaw, 0)

    def test_face_above_center_climbs(self):
        _, _, ud, _ = FaceFollower().update((0.5, 0.2, TARGET_W), 0.0)
        self.assertGreater(ud, 0)

    def test_small_face_approaches_and_large_backs_off(self):
        _, fb_far, _, _ = FaceFollower().update((0.5, 0.5, TARGET_W / 2), 0.0)
        _, fb_near, _, _ = FaceFollower().update((0.5, 0.5, TARGET_W * 2), 0.0)
        self.assertGreater(fb_far, 0)
        self.assertLess(fb_near, 0)

    def test_never_strafes(self):
        lr, _, _, _ = FaceFollower().update((0.9, 0.1, 0.4), 0.0)
        self.assertEqual(lr, 0)

    def test_outputs_clamped_at_extremes(self):
        lr, fb, ud, yaw = FaceFollower().update((1.0, 0.0, 0.01), 0.0)
        self.assertLessEqual(abs(yaw), tracking.MAX_YAW)
        self.assertLessEqual(abs(ud), tracking.MAX_UD)
        self.assertLessEqual(abs(fb), tracking.MAX_FB)

    def test_jitter_inside_deadband_is_ignored(self):
        det = (0.5 + tracking.DEADBAND / 2, 0.5, TARGET_W)
        self.assertEqual(FaceFollower().update(det, 0.0), (0, 0, 0, 0))

    def test_lost_face_coasts_briefly_then_hovers(self):
        f = FaceFollower()
        moving = f.update((0.8, 0.5, TARGET_W), 0.0)
        self.assertNotEqual(moving, (0, 0, 0, 0))
        # within the hold window: coast on the last command (detector flicker)
        self.assertEqual(f.update(None, tracking.LOST_HOLD_S / 2), moving)
        # past it: hover — never wander while blind
        self.assertEqual(f.update(None, tracking.LOST_HOLD_S + 0.1), (0, 0, 0, 0))

    def test_no_face_ever_seen_means_hover(self):
        self.assertEqual(FaceFollower().update(None, 100.0), (0, 0, 0, 0))


class TestDriftDamper(unittest.TestCase):
    """drift_correction: oppose reported velocity, never amplify it.
    Sign convention is locked by flight data — see the function docstring."""

    def test_opposes_reported_velocity(self):
        # drifting forward (vgx +10) and left (vgy -5): push back and right
        lr, fb, ud, yaw = tracking.drift_correction(10, -5)
        self.assertLess(fb, 0)
        self.assertGreater(lr, 0)
        self.assertEqual((ud, yaw), (0, 0))  # baro holds height; yaw doesn't drift

    def test_noise_inside_deadband_is_ignored(self):
        self.assertEqual(tracking.drift_correction(1, -1), (0, 0, 0, 0))

    def test_correction_is_capped(self):
        lr, fb, _, _ = tracking.drift_correction(100, -100)
        self.assertEqual(fb, -tracking.DAMP_MAX)
        self.assertEqual(lr, tracking.DAMP_MAX)

    def test_missing_telemetry_is_zero(self):
        self.assertEqual(tracking.drift_correction(None, None), (0, 0, 0, 0))

    def test_real_drift_incident_would_be_countered(self):
        # vgx: -14 from the runaway log — drifting backward at 1.4 m/s
        lr, fb, _, _ = tracking.drift_correction(-14, 0)
        self.assertEqual(fb, tracking.DAMP_MAX)  # push forward, hard-capped
        self.assertEqual(lr, 0)


class TestFollowMode(unittest.TestCase):
    def test_p_toggles_follow_and_zeros_sticks(self):
        fc = FlightController(speed=50)
        fc.handle_key(ord("w"), 0.0)  # a held key before engaging follow
        self.assertIsNone(fc.handle_key(ord("p"), 0.0))  # local-only, no action
        self.assertTrue(fc.follow)
        self.assertEqual(fc.tick(0.0), (0, 0, 0, 0))  # handover starts from zero
        fc.handle_key(ord("p"), 0.0)
        self.assertFalse(fc.follow)

    def test_any_stick_key_is_manual_override(self):
        fc = FlightController(speed=50)
        fc.handle_key(ord("p"), 0.0)
        self.assertTrue(fc.follow)
        fc.handle_key(ord("w"), 0.0)
        self.assertFalse(fc.follow)
        self.assertEqual(fc.tick(0.0)[1], 50)  # and the key steers immediately

    def test_hover_key_disengages_follow(self):
        fc = FlightController()
        fc.handle_key(ord("p"), 0.0)
        fc.handle_key(ord("h"), 0.0)
        self.assertFalse(fc.follow)

    def test_takeoff_land_emergency_all_clear_follow(self):
        for action in ("takeoff", "land", "emergency"):
            fc = FlightController()
            fc.flying = action != "takeoff"
            fc.follow = True
            fcmod._do_action(MagicMock(), fc, action)
            self.assertFalse(fc.follow, f"{action} left follow engaged")


class TestAutopilotModes(unittest.TestCase):
    """'p' (follow) and 'm' (marker hold) are mutually exclusive autopilot
    modes; any stick key or safety action clears whichever is engaged."""

    def test_m_toggles_marker_hold(self):
        fc = FlightController()
        self.assertIsNone(fc.handle_key(ord("m"), 0.0))
        self.assertEqual(fc.autopilot, "marker")
        fc.handle_key(ord("m"), 0.0)
        self.assertIsNone(fc.autopilot)

    def test_modes_are_mutually_exclusive(self):
        fc = FlightController()
        fc.handle_key(ord("p"), 0.0)
        fc.handle_key(ord("m"), 0.0)   # replaces follow, not stacks
        self.assertEqual(fc.autopilot, "marker")
        fc.handle_key(ord("p"), 0.0)
        self.assertEqual(fc.autopilot, "follow")

    def test_stick_key_clears_marker_hold(self):
        fc = FlightController(speed=50)
        fc.handle_key(ord("m"), 0.0)
        fc.handle_key(ord("w"), 0.0)
        self.assertIsNone(fc.autopilot)
        self.assertEqual(fc.tick(0.0)[1], 50)

    def test_safety_actions_clear_marker_hold(self):
        for action in ("takeoff", "land", "emergency"):
            fc = FlightController()
            fc.flying = action != "takeoff"
            fc.autopilot = "marker"
            fcmod._do_action(MagicMock(), fc, action)
            self.assertIsNone(fc.autopilot, f"{action} left marker hold engaged")

    def test_follow_property_back_compat(self):
        fc = FlightController()
        fc.follow = True
        self.assertEqual(fc.autopilot, "follow")
        fc.autopilot = "marker"
        self.assertFalse(fc.follow)
        fc.follow = False              # safety sites: clears ANY autopilot
        self.assertIsNone(fc.autopilot)

    def test_marker_holder_uses_tighter_size_band(self):
        # a marker at 4% width (slightly far) must produce approach, even
        # though the face deadband would swallow an error this small
        holder = tracking.marker_holder()
        _, fb, _, _ = holder.update((0.5, 0.5, 0.04), 0.0)
        self.assertGreater(fb, 0)
        # and at the target width it hovers
        self.assertEqual(holder.update((0.5, 0.5, tracking.MARKER_TARGET_W), 1.0),
                         (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
