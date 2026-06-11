#!/usr/bin/env python3
"""
Regression tests for the REPL shell's command routing and demo safety.

Pure stdlib (unittest + unittest.mock) — no drone, no pip deps. Run with:
    python -m unittest discover tests
    python tests/test_repl.py
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

# Make the project root importable when run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tello_app.shells import repl  # noqa: E402
from tello_app.tello import TelloError  # noqa: E402


def feed_repl(drone, commands):
    """Drive run_interactive() with a scripted list of typed commands."""
    inputs = iter(commands)
    with redirect_stdout(io.StringIO()), patch("builtins.input", lambda _="": next(inputs)):
        repl.run_interactive(drone)


class TestReplRouting(unittest.TestCase):
    def test_emergency_is_fire_and_forget(self):
        """'emergency' must call drone.emergency(), not block on send_command."""
        drone = MagicMock()
        feed_repl(drone, ["emergency", "quit"])
        self.assertTrue(drone.emergency.called)
        sent = [c.args[0] for c in drone.send_command.call_args_list]
        self.assertNotIn("emergency", sent)

    def test_rc_is_parsed_and_routed(self):
        """'rc a b c d' must call send_rc with ints, not send_command."""
        drone = MagicMock()
        feed_repl(drone, ["rc 0 0 50 0", "quit"])
        self.assertEqual(drone.send_rc.call_args_list, [((0, 0, 50, 0),)])
        self.assertFalse(drone.send_command.called)

    def test_rc_bad_input_does_not_crash_or_send(self):
        """Malformed rc prints usage and sends nothing."""
        drone = MagicMock()
        feed_repl(drone, ["rc 1 2 3", "rc a b c d", "quit"])
        self.assertFalse(drone.send_rc.called)
        self.assertFalse(drone.send_command.called)

    def test_reply_bearing_command_uses_send_command(self):
        """A normal move still goes through the request/response path."""
        drone = MagicMock()
        feed_repl(drone, ["forward 50", "quit"])
        sent = [c.args[0] for c in drone.send_command.call_args_list]
        self.assertEqual(sent, ["forward 50"])


class TestDemoSafety(unittest.TestCase):
    def test_demo_lands_after_takeoff_even_on_failure(self):
        """A mid-square failure must still land the drone (try/finally)."""
        drone = MagicMock()
        drone.get_battery.return_value = 80
        drone.forward.side_effect = TelloError("Motor stop")
        with redirect_stdout(io.StringIO()), self.assertRaises(TelloError):
            repl.run_demo(drone)
        self.assertTrue(drone.takeoff.called)
        self.assertTrue(drone.land.called)

    def test_demo_aborts_on_low_battery_without_takeoff(self):
        """Low battery aborts before takeoff."""
        drone = MagicMock()
        drone.get_battery.return_value = 10
        with redirect_stdout(io.StringIO()):
            repl.run_demo(drone)
        self.assertFalse(drone.takeoff.called)


if __name__ == "__main__":
    unittest.main()
