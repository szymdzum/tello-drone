#!/usr/bin/env python3
"""
Tests for keyboard_control.FlightController — pure logic, no curses, no drone.

    python -m unittest discover -s tests
"""

import curses
import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import keyboard_control as kc  # noqa: E402
from keyboard_control import HOLD_S, SPEED_MAX, SPEED_MIN, FlightController  # noqa: E402


class TestMovementMapping(unittest.TestCase):
    def test_keys_set_expected_axes_and_signs(self):
        fc = FlightController(speed=40)
        self.assertIsNone(fc.handle_key(ord("w"), 0.0))  # forward
        self.assertIsNone(fc.handle_key(ord("a"), 0.0))  # left
        self.assertIsNone(fc.handle_key(curses.KEY_UP, 0.0))    # up
        self.assertIsNone(fc.handle_key(curses.KEY_RIGHT, 0.0)) # yaw right
        self.assertEqual(fc.tick(0.0), (-40, 40, 40, 40))  # (lr, fb, ud, yaw)

    def test_opposite_key_overrides_axis(self):
        fc = FlightController(speed=30)
        fc.handle_key(ord("w"), 0.0)
        fc.handle_key(ord("s"), 0.0)  # back overrides forward on the fb axis
        self.assertEqual(fc.tick(0.0)[1], -30)


class TestDecayAndHover(unittest.TestCase):
    def test_axis_decays_to_zero_after_hold(self):
        fc = FlightController(speed=50)
        fc.handle_key(ord("d"), 0.0)
        self.assertEqual(fc.tick(0.0), (50, 0, 0, 0))
        # still held within the window
        self.assertEqual(fc.tick(HOLD_S / 2), (50, 0, 0, 0))
        # past the window -> hover
        self.assertEqual(fc.tick(HOLD_S + 0.01), (0, 0, 0, 0))

    def test_hover_key_zeros_everything_immediately(self):
        fc = FlightController(speed=60)
        fc.handle_key(ord("w"), 0.0)
        fc.handle_key(curses.KEY_LEFT, 0.0)
        fc.handle_key(ord("x"), 0.0)  # hover
        self.assertEqual(fc.tick(0.0), (0, 0, 0, 0))


class TestDiscreteActions(unittest.TestCase):
    def test_action_keys_return_tokens(self):
        fc = FlightController()
        self.assertEqual(fc.handle_key(ord("t"), 0.0), "takeoff")
        self.assertEqual(fc.handle_key(ord("l"), 0.0), "land")
        self.assertEqual(fc.handle_key(ord("f"), 0.0), "flip")
        self.assertEqual(fc.handle_key(ord(" "), 0.0), "emergency")
        self.assertEqual(fc.handle_key(ord("q"), 0.0), "quit")

    def test_speed_clamps(self):
        fc = FlightController(speed=20)
        for _ in range(10):
            fc.handle_key(ord("-"), 0.0)
        self.assertEqual(fc.speed, SPEED_MIN)
        for _ in range(20):
            fc.handle_key(ord("="), 0.0)
        self.assertEqual(fc.speed, SPEED_MAX)


class TestActionExecution(unittest.TestCase):
    """_do_action against a fake drone — verifies flying state + safety zeroing."""

    def _fake_drone(self):
        from unittest.mock import MagicMock
        return MagicMock()

    def test_takeoff_sets_flying_and_zeros_velocity(self):
        fc = FlightController(speed=50)
        fc.handle_key(ord("w"), 0.0)  # a held key before takeoff
        drone = self._fake_drone()
        self.assertEqual(kc._do_action(drone, fc, "takeoff"), "airborne")
        self.assertTrue(fc.flying)
        self.assertEqual(fc.tick(0.0), (0, 0, 0, 0))  # not flung forward

    def test_takeoff_stays_airborne_when_reply_is_lost(self):
        """The crash bug: a takeoff whose 'ok' is lost MUST stay flying, so the
        loop keeps streaming rc instead of abandoning an airborne drone."""
        from tello import TelloError
        fc = FlightController()
        drone = self._fake_drone()
        drone.send_command.side_effect = TelloError("Timed out")
        msg = kc._do_action(drone, fc, "takeoff")
        self.assertTrue(fc.flying)
        self.assertIn("airborne", msg.lower())

    def test_takeoff_ignored_when_already_flying(self):
        fc = FlightController()
        fc.flying = True
        drone = self._fake_drone()
        self.assertEqual(kc._do_action(drone, fc, "takeoff"), "already airborne")
        drone.send_command.assert_not_called()

    def test_flip_blocked_when_not_flying(self):
        fc = FlightController()
        drone = self._fake_drone()
        msg = kc._do_action(drone, fc, "flip")
        self.assertIn("not flying", msg)
        drone.flip.assert_not_called()

    def test_flip_rejection_shows_battery_hint(self):
        from tello import TelloError
        fc = FlightController()
        fc.flying = True
        drone = self._fake_drone()
        drone.flip.side_effect = TelloError("error")
        msg = kc._do_action(drone, fc, "flip")
        self.assertIn("> 50%", msg)
        self.assertTrue(fc.flying)  # a failed flip doesn't change flight state

    def test_land_clears_flying_even_when_drone_errors(self):
        from tello import TelloError
        fc = FlightController()
        fc.flying = True
        drone = self._fake_drone()
        drone.send_command.side_effect = TelloError("error")  # land cmd errors...
        msg = kc._do_action(drone, fc, "land")
        self.assertFalse(fc.flying)                         # ...still clear flying
        self.assertEqual(drone.send_command.call_count, 2)  # retried once
        self.assertIn("verify", msg)

    def test_land_success(self):
        fc = FlightController()
        fc.flying = True
        drone = self._fake_drone()
        self.assertEqual(kc._do_action(drone, fc, "land"), "landed")
        self.assertFalse(fc.flying)

    def test_emergency_bursts_and_clears_state(self):
        fc = FlightController(speed=50)
        fc.flying = True
        fc.handle_key(ord("d"), 0.0)
        drone = self._fake_drone()
        msg = kc._do_action(drone, fc, "emergency")
        self.assertIn("EMERGENCY", msg)
        self.assertFalse(fc.flying)
        self.assertEqual(fc.tick(0.0), (0, 0, 0, 0))
        self.assertEqual(drone.emergency.call_count, 3)  # burst through packet loss


class TestActionRunner(unittest.TestCase):
    """The worker thread that keeps the control loop non-blocking."""

    def _slow_drone(self, release: threading.Event) -> MagicMock:
        """A drone whose send_command blocks until `release` is set."""
        drone = MagicMock()

        def slow(cmd, timeout=None):
            release.wait(2)
            return "ok"

        drone.send_command.side_effect = slow
        return drone

    def _wait_idle(self, runner, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if runner.busy_with is None and runner._pending is None:
                return
            time.sleep(0.01)
        self.fail("ActionRunner did not go idle")

    def test_submit_never_blocks_while_command_is_in_flight(self):
        release = threading.Event()
        drone = self._slow_drone(release)
        fc = FlightController()
        runner = kc.ActionRunner(drone, fc)
        t0 = time.time()
        runner.submit("takeoff")
        self.assertLess(time.time() - t0, 0.1)  # the crash bug: this used to block
        time.sleep(0.1)
        self.assertEqual(runner.busy_with, "takeoff")
        self.assertTrue(fc.flying)  # set before the (blocked) reply
        release.set()
        self._wait_idle(runner)
        self.assertIn("airborne", runner.display())

    def test_pending_land_is_sticky(self):
        release = threading.Event()
        drone = self._slow_drone(release)
        fc = FlightController()
        fc.flying = True
        runner = kc.ActionRunner(drone, fc)
        runner.submit("takeoff")          # worker grabs this and blocks
        time.sleep(0.1)
        runner.submit("land")             # queued
        runner.submit("flip")             # must NOT replace the queued land
        release.set()
        self._wait_idle(runner)
        sent = [c.args[0] for c in drone.send_command.call_args_list]
        self.assertIn("land", sent)
        drone.flip.assert_not_called()

    def test_emergency_runs_inline_even_while_worker_blocked(self):
        release = threading.Event()
        drone = self._slow_drone(release)
        fc = FlightController()
        runner = kc.ActionRunner(drone, fc)
        runner.submit("takeoff")
        time.sleep(0.1)
        t0 = time.time()
        runner.submit("emergency")        # inline, never queued behind takeoff
        self.assertLess(time.time() - t0, 0.1)
        self.assertEqual(drone.emergency.call_count, 3)
        self.assertFalse(fc.flying)
        release.set()
        self._wait_idle(runner)


if __name__ == "__main__":
    unittest.main()
