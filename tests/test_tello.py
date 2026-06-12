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

from tello_app.tello import Tello, TelloError  # noqa: E402


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
            payload = reply if isinstance(reply, bytes) else reply.encode("utf-8")
            self.sock.sendto(payload, addr)

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

    def test_send_rc_clamps_out_of_range_values(self):
        # FlightController can't exceed ±100, but the REPL passes any int through.
        self.drone.send_rc(0, 250, -250, 100)
        time.sleep(0.3)
        self.assertIn("rc 0 100 -100 100", self.fake.received)


class TestKeepalive(unittest.TestCase):
    """start_keepalive must wake a quiet GROUNDED drone with zero rc, stay
    silent while real traffic is flowing, and — safety-critical — stay silent
    while AIRBORNE so the Tello's 15 s auto-land failsafe remains armed and a
    pilot's rc setpoint is never overridden with zeros."""

    def setUp(self):
        self.fake = FakeDrone()
        self.drone = make_tello(self.fake)
        self.drone.connect(retries=1)

    def tearDown(self):
        self.drone.close()
        self.fake.close()

    def _set_state(self, state, age=0.0):
        with self.drone._state_lock:
            self.drone._state = state
            self.drone._state_at = time.monotonic() - age

    def test_quiet_grounded_link_gets_rc_heartbeat(self):
        self._set_state({"h": 0})
        self.drone.start_keepalive(interval=0.3)
        time.sleep(1.2)
        self.assertIn("rc 0 0 0 0", self.fake.received)

    def test_airborne_drone_is_never_touched(self):
        self._set_state({"h": 50})  # flying — the failsafe must stay armed
        self.drone.start_keepalive(interval=0.2)
        time.sleep(1.0)
        self.assertNotIn("rc 0 0 0 0", self.fake.received)

    def test_no_telemetry_means_no_heartbeat(self):
        # Without state packets we can't prove the drone is grounded — stay silent.
        self.drone.start_keepalive(interval=0.2)
        time.sleep(1.0)
        self.assertNotIn("rc 0 0 0 0", self.fake.received)

    def test_stale_grounded_telemetry_means_no_heartbeat(self):
        # An old 'h: 0' from a stalled state stream proves nothing about the
        # drone NOW — the gate must fail closed, not trust the last packet.
        self._set_state({"h": 0}, age=5.0)
        self.drone.start_keepalive(interval=0.2)
        time.sleep(1.0)
        self.assertNotIn("rc 0 0 0 0", self.fake.received)

    def test_busy_link_is_left_alone(self):
        self._set_state({"h": 0})
        self.drone.start_keepalive(interval=0.4)
        for _ in range(8):
            self.drone.send_rc(0, 0, 50, 0)  # active stick stream
            time.sleep(0.1)
        self.assertNotIn("rc 0 0 0 0", self.fake.received)


class TestBinaryPacketDiscard(unittest.TestCase):
    """The Tello also speaks its old binary protocol on the command port (boot
    banners, DJI_LOG spam). Those datagrams must never be matched as the reply
    to an SDK command."""

    def test_binary_junk_is_not_a_reply(self):
        junk = b"\xcc\x88\x00BUILD May  7 2019\x00DJI_LOG_V3\xaa"
        fake = FakeDrone(replies={"command": junk, "battery?": "87"})
        drone = make_tello(fake)
        try:
            # The only "reply" to 'command' is binary junk -> dropped -> timeout,
            # NOT returned as a garbled response string.
            with self.assertRaises(TelloError):
                drone.send_command("command", timeout=0.5)
            self.assertEqual(drone.send_command("battery?", timeout=1), "87")
        finally:
            drone.close()
            fake.close()


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

    def test_cross_send_late_reply_is_not_misattributed(self):
        """The harder case: without the post-timeout quarantine, takeoff's late
        'ok' would land AFTER the next command's send time and be matched as
        its reply. The quarantine delays the next send past the late arrival,
        so the timestamp check discards it as stale."""
        fake = FakeDrone(replies={
            "takeoff": ("ok", 0.6),
            "battery?": "87",
        })
        drone = make_tello(fake)
        try:
            with self.assertRaises(TelloError):
                drone.send_command("takeoff", timeout=0.2)
            # Called immediately — takeoff's 'ok' is still in flight.
            self.assertEqual(drone.send_command("battery?", timeout=2), "87")
        finally:
            drone.close()
            fake.close()


class TestStateReceiverResilience(unittest.TestCase):
    def test_binary_state_packet_does_not_kill_the_thread(self):
        """One corrupt datagram on the state port must not raise
        UnicodeDecodeError and silently end telemetry for the session."""
        fake = FakeDrone()
        drone = make_tello(fake)
        try:
            drone.connect(retries=1)  # starts the state receiver thread
            port = drone._state_socket.getsockname()[1]
            tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            tx.sendto(b"\xff\xfe\x00garbage\xaa", ("127.0.0.1", port))
            time.sleep(0.2)
            tx.sendto(b"bat:87;h:0;", ("127.0.0.1", port))  # thread must still parse
            tx.close()
            deadline = time.time() + 2
            while time.time() < deadline and drone.state.get("bat") != 87:
                time.sleep(0.05)
            self.assertEqual(drone.state.get("bat"), 87)
        finally:
            drone.close()
            fake.close()


if __name__ == "__main__":
    unittest.main()
