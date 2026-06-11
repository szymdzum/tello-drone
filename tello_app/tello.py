"""
Tello drone controller via UDP sockets.

Communicates with the Tello SDK over Wi-Fi using three UDP channels:
  - Command:  192.168.10.1:8889  (send commands, receive responses)
  - State:    0.0.0.0:8890       (receive telemetry at ~10Hz)
  - Video:    0.0.0.0:11111      (receive H.264 video stream)

Usage:
    drone = Tello()
    drone.connect()
    print(drone.get_battery())
    drone.takeoff()
    drone.land()
    drone.close()
"""

import queue
import socket
import threading
import time


class TelloError(Exception):
    """Raised when a Tello command fails."""


class Tello:
    """Low-level Tello drone controller over UDP."""

    TELLO_IP = "192.168.10.1"
    COMMAND_PORT = 8889
    STATE_PORT = 8890
    VIDEO_PORT = 11111

    RESPONSE_TIMEOUT: int = 10  # seconds (overridable per instance, e.g. keepalive)
    SAFETY_TIMEOUT: int = 15  # seconds – Tello auto-lands if no command received

    def __init__(self, ip: str | None = None, *,
                 remote_port: int | None = None,
                 local_port: int | None = None,
                 state_port: int | None = None) -> None:
        """Defaults talk to a real Tello. All addressing is overridable so tests
        can run the full protocol against a fake drone on localhost."""
        self._tello_addr = (ip if ip is not None else self.TELLO_IP,
                            remote_port if remote_port is not None else self.COMMAND_PORT)

        # Command socket (send + receive responses)
        self._cmd_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._cmd_socket.bind(("", local_port if local_port is not None else self.COMMAND_PORT))
        # Short poll so the receiver thread notices shutdown quickly; the actual
        # per-command timeout is enforced in send_command via the queue.
        self._cmd_socket.settimeout(0.5)

        # State socket (receive telemetry)
        self._state_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._state_socket.bind(("", state_port if state_port is not None else self.STATE_PORT))
        self._state_socket.settimeout(3)

        self._state: dict[str, str | int | float] = {}
        self._state_lock = threading.Lock()
        self._cmd_lock = threading.Lock()  # serializes in-flight commands across threads
        # Every datagram from the drone's command port, tagged with arrival time.
        self._responses: queue.Queue[tuple[float, str]] = queue.Queue()
        self._running = True
        self._connected = False
        self._state_thread: threading.Thread | None = None
        # Receiver runs from construction: send_command never touches recvfrom.
        self._response_thread = threading.Thread(target=self._response_receiver, daemon=True)
        self._response_thread.start()

    # ── Connection ──────────────────────────────────────────────

    def connect(self, retries: int = 3) -> str:
        """Enter SDK mode and start the state receiver thread.

        Stale replies the drone buffered from an earlier session are harmless:
        send_command discards anything received before its own send time."""
        if self._state_thread is None:
            self._state_thread = threading.Thread(target=self._state_receiver, daemon=True)
            self._state_thread.start()

        for attempt in range(1, retries + 1):
            try:
                response = self.send_command("command")
                if "ok" in response.lower():
                    self._connected = True
                    print("✓ Connected to Tello (SDK mode)")
                    return response
                else:
                    print(f"  Attempt {attempt}/{retries}: unexpected response '{response}'")
            except TelloError as e:
                print(f"  Attempt {attempt}/{retries}: {e}")

            if attempt < retries:
                time.sleep(1)

        raise TelloError("Failed to enter SDK mode after all retries")

    def close(self) -> None:
        """Shut down sockets and background threads."""
        self._running = False
        self._connected = False
        self._cmd_socket.close()
        self._state_socket.close()
        print("✓ Disconnected")

    # ── Raw command interface ───────────────────────────────────

    def _response_receiver(self) -> None:
        """Background thread: drain command-channel replies into a timestamped
        queue. send_command pops from it and discards anything that arrived
        before its own send — so a late reply to a timed-out command can never
        be mistaken for the answer to the next one (response desync)."""
        while self._running:
            try:
                data, _ = self._cmd_socket.recvfrom(1518)
            except TimeoutError:
                continue
            except OSError:
                break
            text = data.decode("utf-8", errors="replace").strip()
            if not text or "�" in text or not text.isprintable():
                # Binary packet from the drone's other (non-SDK) protocol —
                # boot banner / DJI_LOG spam. Never a reply to an SDK command,
                # so it must not be matched as one.
                continue
            self._responses.put((time.monotonic(), text))

    def send_command(self, command: str, timeout: float | None = None) -> str:
        """Send a text command and wait for the response string.

        Thread-safe: _cmd_lock serializes in-flight commands (e.g. a controller's
        worker thread vs. the main thread), and replies are matched by arrival
        time — anything received before this send is a stale leftover."""
        timeout = timeout or self.RESPONSE_TIMEOUT
        with self._cmd_lock:
            sent_at = time.monotonic()
            self._cmd_socket.sendto(command.encode("utf-8"), self._tello_addr)
            deadline = sent_at + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TelloError(f"Timed out waiting for response to '{command}'")
                try:
                    received_at, response = self._responses.get(timeout=remaining)
                except queue.Empty:
                    raise TelloError(
                        f"Timed out waiting for response to '{command}'") from None
                if received_at >= sent_at:
                    break
                # else: stale reply to an earlier (timed-out) command — drop it

        if response.lower().startswith("error"):
            raise TelloError(f"Command '{command}' failed: {response}")

        return response

    def send_rc(self, lr: int, fb: int, ud: int, yaw: int) -> None:
        """Send RC joystick-style control (no response expected).

        Args:
            lr:  left/right     (-100 to 100)
            fb:  forward/back   (-100 to 100)
            ud:  up/down        (-100 to 100)
            yaw: rotation       (-100 to 100)
        """
        cmd = f"rc {lr} {fb} {ud} {yaw}"
        self._cmd_socket.sendto(cmd.encode("utf-8"), self._tello_addr)

    # ── Control commands ────────────────────────────────────────

    def takeoff(self) -> str:
        print("⏫ Taking off...")
        return self.send_command("takeoff", timeout=20)

    def land(self) -> str:
        print("⏬ Landing...")
        return self.send_command("land", timeout=20)

    def emergency(self) -> None:
        """Kill motors immediately – drone will drop!"""
        self._cmd_socket.sendto(b"emergency", self._tello_addr)
        print("🛑 EMERGENCY STOP")

    def stop(self) -> str:
        """Stop movement and hover in place."""
        return self.send_command("stop")

    # ── Movement (20–500 cm) ────────────────────────────────────

    def up(self, cm: int) -> str:
        return self.send_command(f"up {cm}")

    def down(self, cm: int) -> str:
        return self.send_command(f"down {cm}")

    def left(self, cm: int) -> str:
        return self.send_command(f"left {cm}")

    def right(self, cm: int) -> str:
        return self.send_command(f"right {cm}")

    def forward(self, cm: int) -> str:
        return self.send_command(f"forward {cm}")

    def back(self, cm: int) -> str:
        return self.send_command(f"back {cm}")

    # ── Rotation (1–360 degrees) ────────────────────────────────

    def cw(self, degrees: int) -> str:
        return self.send_command(f"cw {degrees}")

    def ccw(self, degrees: int) -> str:
        return self.send_command(f"ccw {degrees}")

    # ── Flip (l/r/f/b) ─────────────────────────────────────────

    def flip(self, direction: str) -> str:
        """Flip: 'l' (left), 'r' (right), 'f' (forward), 'b' (back)."""
        return self.send_command(f"flip {direction}")

    # ── Go to coordinates ───────────────────────────────────────

    def go(self, x: int, y: int, z: int, speed: int) -> str:
        """Fly to (x, y, z) at speed cm/s. Coords: -500..500, speed: 10..100."""
        return self.send_command(f"go {x} {y} {z} {speed}")

    # ── Set commands ────────────────────────────────────────────

    def set_speed(self, cms: int) -> str:
        """Set speed in cm/s (10–100)."""
        return self.send_command(f"speed {cms}")

    # ── Read commands (query the drone) ─────────────────────────

    def get_battery(self) -> int:
        return int(self.send_command("battery?"))

    def get_speed(self) -> int:
        return int(self.send_command("speed?"))

    def get_height(self) -> str:
        return self.send_command("height?")

    def get_temp(self) -> str:
        return self.send_command("temp?")

    def get_flight_time(self) -> str:
        return self.send_command("time?")

    def get_wifi_snr(self) -> str:
        return self.send_command("wifi?")

    def get_sdk_version(self) -> str:
        return self.send_command("sdk?")

    def get_serial(self) -> str:
        return self.send_command("sn?")

    # ── Video stream ────────────────────────────────────────────

    def stream_on(self) -> str:
        return self.send_command("streamon")

    def stream_off(self) -> str:
        return self.send_command("streamoff")

    @property
    def connected(self) -> bool:
        """True once SDK mode has been entered (used to skip cleanup commands
        when a run is aborted before the drone ever answered)."""
        return self._connected

    # ── State (telemetry) ───────────────────────────────────────

    @property
    def state(self) -> dict:
        """Latest parsed state dict from the drone."""
        with self._state_lock:
            return dict(self._state)

    def _state_receiver(self) -> None:
        """Background thread: receive and parse state packets."""
        while self._running:
            try:
                data, _ = self._state_socket.recvfrom(1518)
                raw = data.decode("utf-8").strip()
                parsed = self._parse_state(raw)
                with self._state_lock:
                    self._state = parsed
            except TimeoutError:
                continue
            except OSError:
                break

    @staticmethod
    def _parse_state(raw: str) -> dict[str, str | int | float]:
        """Parse 'key:value;key:value;...' state string."""
        state = {}
        for field in raw.split(";"):
            parts = field.split(":")
            if len(parts) != 2:
                continue
            key, val = parts[0].strip(), parts[1].strip()
            # Try to convert to number
            try:
                state[key] = int(val)
            except ValueError:
                try:
                    state[key] = float(val)
                except ValueError:
                    state[key] = val
        return state
