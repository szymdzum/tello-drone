#!/usr/bin/env python3
"""
Integration tests for tello.py's UDP protocol against a fake drone on localhost.

Exercises the real sockets and threads (receiver thread, timestamp-matched
replies) — no hardware. The key regression here is the stale-reply test: a late
response to a timed-out command must never be consumed as the answer to the
next command (the desync that contributed to the FPV crash).
"""

import os
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tello import Tello, TelloError  # noqa: E402


class FakeDrone:
    """Minimal Tello stand-in: answers known commands, optionally after a delay.

    replies maps command -> reply string, or (reply, delay_s). Commands with no
    entry get no reply at all (simulates a lost packet / rc silence).
    """

    def __init__(self, replies: dict | None = None) -> None:
        self.replies = replies if replies is not None else {
            "command": "ok", "battery?": "87", "land": "ok",
        }
        self.received: list[str] = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.settimeout(0.1)
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while self._running:
            try:
                data, addr = self.sock.recvfrom(1518)
            except TimeoutError:
                continue
            except OSError:
                break
            cmd = data.decode("utf-8").strip()
            self.received.append(cmd)
            entry = self.replies.get(cmd)
            if entry is None:
                continue  # no reply (lost packet / fire-and-forget command)
            reply, delay = entry if isinstance(entry, tuple) else (entry, 0.0)
            if delay:
                time.sleep(delay)
            self.sock.sendto(reply.encode("utf-8"), addr)

    def close(self) -> None:
        self._running = False
        self.sock.close()


def make_tello(fake: FakeDrone) -> Tello:
    """A Tello wired to the fake drone, on ephemeral local ports."""
    return Tello("127.0.0.1", remote_port=fake.port, local_port=0, state_port=0)


class TestProtocol(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDrone()
        self.drone = make_tello(self.fake)

    def tearDown(self):
        self.drone.close()
        self.fake.close()

    def test_connect_and_read_command(self):
        self.assertFalse(self.drone.connected)
        self.drone.connect(retries=1)
        self.assertTrue(self.drone.connected)
        self.assertEqual(self.drone.get_battery(), 87)
        self.assertIn("command", self.fake.received)

    def test_error_response_raises(self):
        self.fake.replies["flip f"] = "error"
        with self.assertRaises(TelloError):
            self.drone.send_command("flip f", timeout=1)

    def test_timeout_when_no_reply(self):
        t0 = time.monotonic()
        with self.assertRaises(TelloError):
            self.drone.send_command("takeoff", timeout=0.3)
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_send_rc_is_fire_and_forget(self):
        t0 = time.monotonic()
        self.drone.send_rc(0, 0, 50, 0)
        self.assertLess(time.monotonic() - t0, 0.05)  # never waits
        time.sleep(0.3)
        self.assertIn("rc 0 0 50 0", self.fake.received)


class TestStaleReplyDiscard(unittest.TestCase):
    """The crash class: a reply that arrives after its command timed out must be
    discarded, not handed to the next command."""

    def test_late_reply_not_consumed_by_next_command(self):
        fake = FakeDrone(replies={
            "takeoff": ("ok", 0.6),  # reply arrives AFTER the 0.2s timeout below
            "battery?": "87",
        })
        drone = make_tello(fake)
        try:
            with self.assertRaises(TelloError):
                drone.send_command("takeoff", timeout=0.2)
            time.sleep(0.7)  # let the late 'ok' arrive and sit in the queue
            # Must get the real battery value, not the stale takeoff 'ok'.
            self.assertEqual(drone.send_command("battery?", timeout=1), "87")
        finally:
            drone.close()
            fake.close()


if __name__ == "__main__":
    unittest.main()
