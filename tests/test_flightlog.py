#!/usr/bin/env python3
"""
Tests for the JSONL flight recorder: the writer itself, the Tello hook points
(cmd/rc/timeout events against a fake drone), and the contract that logging
failures never touch the flight path.
"""

import json
import os
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tello_app.flightlog import FlightLog, NullLog, open_session_log  # noqa: E402
from tello_app.tello import Tello, TelloError  # noqa: E402


def read_events(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class TestFlightLog(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "test.jsonl")

    def tearDown(self):
        self.dir.cleanup()

    def test_events_are_valid_jsonl_with_timestamps(self):
        log = FlightLog(self.path)
        log.event("rc", lr=0, fb=20, ud=0, yaw=-14, src="keys")
        log.close()
        events = read_events(self.path)
        self.assertEqual([e["type"] for e in events], ["session", "rc", "close"])
        rc = events[1]
        self.assertEqual((rc["fb"], rc["src"]), (20, "keys"))
        self.assertIn("t", rc)
        self.assertIn("mono", rc)

    def test_event_fields_survives_hostile_keys(self):
        # State packet keys are drone-controlled: a malformed packet could
        # parse to keys like 'type' — they must not crash the receiver thread.
        log = FlightLog(self.path)
        log.event_fields("state", {"type": "evil", "mono": "evil", "h": 0})
        log.close()
        self.assertEqual(len(read_events(self.path)), 3)  # written, not raised

    def test_unserializable_field_is_swallowed(self):
        log = FlightLog(self.path)
        log.event("cmd", weird=object())  # default=str handles it
        log.event("rc", lr=1)
        log.close()
        self.assertEqual(len(read_events(self.path)), 4)

    def test_null_log_is_silent_and_closeable(self):
        log = NullLog()
        log.event("rc", lr=0)
        log.event_fields("state", {})
        log.close()
        self.assertIsNone(log.path)

    def test_open_session_log_creates_directory(self):
        target = os.path.join(self.dir.name, "logs")
        log = open_session_log(target)
        log.close()
        self.assertTrue(log.path and os.path.exists(log.path))


class TestTelloLogging(unittest.TestCase):
    """The hook points, against a real UDP socket pair on localhost."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "flight.jsonl")
        # A bare echo peer: replies 'ok' to anything that expects an answer.
        self.peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.peer.bind(("127.0.0.1", 0))
        self.peer.settimeout(2)
        self.drone = Tello("127.0.0.1", remote_port=self.peer.getsockname()[1],
                           local_port=0, state_port=0, log=FlightLog(self.path))

    def tearDown(self):
        self.drone.close()
        self.peer.close()
        self.dir.cleanup()

    def _events(self, type_=None):
        events = read_events(self.path)
        return [e for e in events if type_ is None or e["type"] == type_]

    def test_rc_send_is_logged_with_clamped_values_and_src(self):
        self.drone.send_rc(0, 250, 0, 0, src="follow")
        rc = self._events("rc")[0]
        self.assertEqual((rc["fb"], rc["src"]), (100, "follow"))

    def test_command_reply_logged_with_rtt(self):
        def answer():
            _, addr = self.peer.recvfrom(1518)
            self.peer.sendto(b"ok", addr)

        threading.Thread(target=answer, daemon=True).start()
        self.drone.send_command("command", timeout=2)
        cmd = self._events("cmd")[0]
        self.assertEqual(cmd["reply"], "ok")
        self.assertGreaterEqual(cmd["rtt"], 0)

    def test_timeout_is_logged(self):
        with self.assertRaises(TelloError):
            self.drone.send_command("takeoff", timeout=0.2)
        cmd = self._events("cmd")[0]
        self.assertEqual(cmd.get("error"), "timeout")

    def test_close_writes_close_event(self):
        self.drone.close()
        self.assertTrue(self._events("close"))


if __name__ == "__main__":
    unittest.main()
