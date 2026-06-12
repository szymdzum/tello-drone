#!/usr/bin/env python3
"""
Tests for the flight controller — the flight brain (keymap, FlightController,
_do_action, ActionRunner). Pure logic / threads, no curses, no cv2, no drone.

    python -m unittest discover -s tests
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tello_app.flight import controller as fcmod  # noqa: E402
from tello_app.flight.controller import (  # noqa: E402
    HOLD_S,
    SPEED_MAX,
    SPEED_MIN,
    FlightController,
)


class TestMovementMapping(unittest.TestCase):
    def test_keys_set_expected_axes_and_signs(self):
        fc = FlightController(speed=40)
        self.assertIsNone(fc.handle_key(ord("w"), 0.0))  # forward
        self.assertIsNone(fc.handle_key(ord("a"), 0.0))  # strafe left
        self.assertIsNone(fc.handle_key(ord("i"), 0.0))  # up
        self.assertIsNone(fc.handle_key(ord("l"), 0.0))  # yaw right
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
        fc.handle_key(ord("j"), 0.0)  # yaw left
        fc.handle_key(ord("h"), 0.0)  # hover
        self.assertEqual(fc.tick(0.0), (0, 0, 0, 0))


class TestDiscreteActions(unittest.TestCase):
    def test_action_keys_return_tokens(self):
        fc = FlightController()
        self.assertEqual(fc.handle_key(ord("t"), 0.0), "takeoff")
        self.assertEqual(fc.handle_key(ord("g"), 0.0), "land")
        self.assertEqual(fc.handle_key(ord("f"), 0.0), "flip")
        self.assertEqual(fc.handle_key(ord(" "), 0.0), "emergency")
        self.assertEqual(fc.handle_key(27, 0.0), "quit")        # Esc
        self.assertEqual(fc.handle_key(ord("q"), 0.0), "quit")  # q alias
        self.assertIsNone(fc.handle_key(ord("h"), 0.0))         # hover is local-only

    def test_speed_clamps(self):
        fc = FlightController(speed=20)
        for _ in range(10):
            fc.handle_key(ord("y"), 0.0)  # slower
        self.assertEqual(fc.speed, SPEED_MIN)
        for _ in range(20):
            fc.handle_key(ord("u"), 0.0)  # faster
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
        self.assertEqual(fcmod._do_action(drone, fc, "takeoff"), "airborne")
        self.assertTrue(fc.flying)
        self.assertEqual(fc.tick(0.0), (0, 0, 0, 0))  # not flung forward

    def test_takeoff_stays_airborne_when_reply_is_lost(self):
        """The crash bug: a takeoff whose 'ok' is lost MUST stay flying, so the
        loop keeps streaming rc instead of abandoning an airborne drone."""
        from tello_app.tello import TelloError
        fc = FlightController()
        drone = self._fake_drone()
        drone.send_command.side_effect = TelloError("Timed out")
        msg = fcmod._do_action(drone, fc, "takeoff")
        self.assertTrue(fc.flying)
        self.assertIn("airborne", msg.lower())

    def test_takeoff_ignored_when_already_flying(self):
        fc = FlightController()
        fc.flying = True
        drone = self._fake_drone()
        self.assertEqual(fcmod._do_action(drone, fc, "takeoff"), "already airborne")
        drone.send_command.assert_not_called()

    def test_flip_blocked_when_not_flying(self):
        fc = FlightController()
        drone = self._fake_drone()
        msg = fcmod._do_action(drone, fc, "flip")
        self.assertIn("not flying", msg)
        drone.flip.assert_not_called()

    def test_flip_rejection_surfaces_drone_error(self):
        from tello_app.tello import TelloError
        fc = FlightController()
        fc.flying = True
        drone = self._fake_drone()
        drone.flip.side_effect = TelloError("Command 'flip f' failed: error Not joystick")
        msg = fcmod._do_action(drone, fc, "flip")
        self.assertIn("flip rejected", msg)
        self.assertIn("Not joystick", msg)  # the drone's real reason, not a guess
        self.assertTrue(fc.flying)  # a failed flip doesn't change flight state

    def test_land_clears_flying_even_when_drone_errors(self):
        from tello_app.tello import TelloError
        fc = FlightController()
        fc.flying = True
        drone = self._fake_drone()
        drone.send_command.side_effect = TelloError("error")  # land cmd errors...
        msg = fcmod._do_action(drone, fc, "land")
        self.assertFalse(fc.flying)                         # ...still clear flying
        self.assertEqual(drone.send_command.call_count, 2)  # retried once
        self.assertIn("verify", msg)

    def test_land_success(self):
        fc = FlightController()
        fc.flying = True
        drone = self._fake_drone()
        self.assertEqual(fcmod._do_action(drone, fc, "land"), "landed")
        self.assertFalse(fc.flying)

    def test_emergency_bursts_and_clears_state(self):
        fc = FlightController(speed=50)
        fc.flying = True
        fc.handle_key(ord("d"), 0.0)
        drone = self._fake_drone()
        msg = fcmod._do_action(drone, fc, "emergency")
        self.assertIn("EMERGENCY", msg)
        self.assertFalse(fc.flying)
        self.assertEqual(fc.tick(0.0), (0, 0, 0, 0))
        self.assertEqual(drone.emergency.call_count, 3)  # burst through packet loss

    def test_emergency_sets_flag_and_takeoff_rearms(self):
        """The HUD's DISARMED overlay reads fc.emergency, not the status text —
        the flag must survive later status updates and clear on re-takeoff."""
        fc = FlightController()
        fc.flying = True
        drone = self._fake_drone()
        fcmod._do_action(drone, fc, "emergency")
        self.assertTrue(fc.emergency)
        fcmod._do_action(drone, fc, "takeoff")
        self.assertFalse(fc.emergency)

    def test_landing_freezes_steering(self):
        """While a landing is in progress, held/new movement keys must not feed
        the rc stream — non-zero rc mid-descent can abort the landing."""
        fc = FlightController(speed=50)
        fc.flying = True
        fc.handle_key(ord("w"), 0.0)  # held forward before 'g'
        fc.landing = True             # what ActionRunner.submit('land') sets
        self.assertEqual(fc.tick(0.0), (0, 0, 0, 0))   # zeroed immediately
        fc.handle_key(ord("w"), 0.0)                   # key still held mid-descent
        self.assertEqual(fc.tick(0.0), (0, 0, 0, 0))   # still frozen
        drone = self._fake_drone()
        fcmod._do_action(drone, fc, "land")
        self.assertFalse(fc.landing)                   # released on touchdown


class TestCrashMonitor(unittest.TestCase):
    """Reconciling a stale 'airborne' belief with telemetry after a crash.
    The flip rule may clear flying (unambiguous: firmware cuts motors);
    the grounded-looking rule is display-only."""

    def _drone(self, state, age=0.1):
        drone = MagicMock()
        drone.state = state
        drone.state_age.return_value = age
        return drone

    def _flying_fc(self):
        fc = FlightController()
        fc.flying = True
        return fc

    def test_sustained_flip_clears_flying_and_explains(self):
        # roll: 179 held — the real crash log: upside down on the floor for 8 s
        fc = self._flying_fc()
        fc.follow = True
        m = fcmod.CrashMonitor()
        drone = self._drone({"roll": 179, "h": 0})
        self.assertIsNone(m.update(drone, fc, 0.0))   # first sighting: not yet
        self.assertTrue(fc.flying)
        msg = m.update(drone, fc, fcmod.FLIP_HOLD_S + 0.1)
        self.assertIn("flipped", msg or "")
        self.assertFalse(fc.flying)   # 't' is re-armed for relaunch
        self.assertFalse(fc.follow)

    def test_transient_tumble_does_not_fire(self):
        """The runaway-drift regression: a mid-air tumble transits |roll|>120
        for under a second and the firmware recovers — cutting the rc stream
        on that single sample is what set the drone adrift."""
        fc = self._flying_fc()
        m = fcmod.CrashMonitor()
        m.update(self._drone({"roll": 108, "h": -150}), fc, 0.0)   # tumbling
        m.update(self._drone({"roll": 130, "h": -150}), fc, 0.2)   # peak
        m.update(self._drone({"roll": -16, "h": -350}), fc, 0.6)   # recovered
        msg = m.update(self._drone({"roll": 130, "h": 0}), fc, 5.0)  # new transient
        self.assertIsNone(msg)
        self.assertTrue(fc.flying)  # rc stream keeps flowing throughout

    def test_stale_flip_telemetry_is_ignored(self):
        fc = self._flying_fc()
        drone = self._drone({"roll": 179}, age=5.0)
        m = fcmod.CrashMonitor()
        self.assertIsNone(m.update(drone, fc, 0.0))
        self.assertIsNone(m.update(drone, fc, fcmod.FLIP_HOLD_S + 1))
        self.assertTrue(fc.flying)  # blind: keep the safe belief

    def test_normal_attitude_never_fires(self):
        fc = self._flying_fc()
        drone = self._drone({"roll": -30, "h": 50, "vgx": 5, "vgy": 0, "vgz": 1})
        m = fcmod.CrashMonitor()
        self.assertIsNone(m.update(drone, fc, 0.0))
        self.assertTrue(fc.flying)
        self.assertFalse(m.down_hint(10.0))

    def test_garbage_roll_value_is_harmless(self):
        fc = self._flying_fc()
        drone = self._drone({"roll": "junk", "h": 50})
        self.assertIsNone(fcmod.CrashMonitor().update(drone, fc, 0.0))

    def test_down_hint_needs_sustained_grounded_telemetry(self):
        fc = self._flying_fc()
        still = {"roll": 0, "h": 0, "vgx": 0, "vgy": 0, "vgz": 0}
        m = fcmod.CrashMonitor()
        m.update(self._drone(still), fc, 0.0)
        self.assertFalse(m.down_hint(1.0))            # too soon
        m.update(self._drone(still), fc, 4.0)
        self.assertTrue(m.down_hint(4.0))             # sustained
        self.assertTrue(fc.flying)                    # display-only — no control change
        # movement in telemetry resets the clock
        m.update(self._drone({"roll": 0, "h": 20, "vgx": 0, "vgy": 0, "vgz": 0}), fc, 5.0)
        self.assertFalse(m.down_hint(8.0))

    def test_not_flying_resets_and_stays_quiet(self):
        fc = FlightController()  # on the ground, belief correct
        still = {"roll": 0, "h": 0, "vgx": 0, "vgy": 0, "vgz": 0}
        m = fcmod.CrashMonitor()
        self.assertIsNone(m.update(self._drone(still), fc, 0.0))
        self.assertFalse(m.down_hint(10.0))


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
        runner = fcmod.ActionRunner(drone, fc)
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
        runner = fcmod.ActionRunner(drone, fc)
        runner.submit("takeoff")          # worker grabs this and blocks
        time.sleep(0.1)
        runner.submit("land")             # queued
        runner.submit("flip")             # must NOT replace the queued land
        release.set()
        self._wait_idle(runner)
        sent = [c.args[0] for c in drone.send_command.call_args_list]
        self.assertIn("land", sent)
        drone.flip.assert_not_called()

    def test_executing_land_blocks_queued_takeoff(self):
        """The relaunch bug: once the worker has POPPED land (pending is empty
        again), a stray 't' must not queue a takeoff that fires on touchdown."""
        release = threading.Event()
        drone = self._slow_drone(release)
        fc = FlightController()
        fc.flying = True
        runner = fcmod.ActionRunner(drone, fc)
        runner.submit("land")             # worker pops it and blocks in 'land'
        time.sleep(0.1)
        self.assertEqual(runner.busy_with, "land")
        runner.submit("takeoff")          # stray key mid-descent — must be dropped
        release.set()
        self._wait_idle(runner)
        sent = [c.args[0] for c in drone.send_command.call_args_list]
        self.assertNotIn("takeoff", sent)
        self.assertFalse(fc.flying)       # landed, and it STAYED landed

    def test_wait_idle_reflects_worker_state(self):
        release = threading.Event()
        drone = self._slow_drone(release)
        runner = fcmod.ActionRunner(drone, FlightController())
        self.assertTrue(runner.wait_idle(0.5))   # nothing submitted yet
        runner.submit("takeoff")
        self.assertFalse(runner.wait_idle(0.2))  # blocked on the slow drone
        release.set()
        self.assertTrue(runner.wait_idle(2.0))

    def test_worker_survives_action_exception(self):
        """An unexpected error (e.g. OSError from a closing socket) must not
        kill the worker thread — that would hang every later action."""
        drone = MagicMock()
        drone.send_command.side_effect = OSError("socket closed")
        fc = FlightController()
        runner = fcmod.ActionRunner(drone, fc)
        runner.submit("takeoff")
        self.assertTrue(runner.wait_idle(2.0))
        self.assertIn("failed", runner.last_result)
        self.assertFalse(fc.landing)  # land flags can't stay frozen either
        drone.send_command.side_effect = None
        drone.send_command.return_value = "ok"
        runner.submit("land")  # worker still alive and executing
        self.assertTrue(runner.wait_idle(2.0))
        self.assertEqual(runner.last_result, "landed")

    def test_emergency_runs_inline_even_while_worker_blocked(self):
        release = threading.Event()
        drone = self._slow_drone(release)
        fc = FlightController()
        runner = fcmod.ActionRunner(drone, fc)
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
