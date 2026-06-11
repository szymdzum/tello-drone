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

    RESPONSE_TIMEOUT = 10  # seconds
    SAFETY_TIMEOUT = 15  # seconds – Tello auto-lands if no command received

    def __init__(self) -> None:
        # Command socket (send + receive responses)
        self._cmd_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._cmd_socket.bind(("", self.COMMAND_PORT))
        self._cmd_socket.settimeout(self.RESPONSE_TIMEOUT)

        # State socket (receive telemetry)
        self._state_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._state_socket.bind(("", self.STATE_PORT))
        self._state_socket.settimeout(3)

        self._tello_addr = (self.TELLO_IP, self.COMMAND_PORT)
        self._state: dict[str, str | int | float] = {}
        self._state_lock = threading.Lock()
        self._running = False
        self._connected = False
        self._state_thread: threading.Thread | None = None

    # ── Connection ──────────────────────────────────────────────

    def connect(self, retries: int = 3) -> str:
        """Enter SDK mode and start the state receiver thread."""
        self._running = True
        self._state_thread = threading.Thread(target=self._state_receiver, daemon=True)
        self._state_thread.start()

        for attempt in range(1, retries + 1):
            # Flush any stale packets sitting in the command socket buffer
            self._flush_socket(self._cmd_socket)
            time.sleep(0.5)
            self._flush_socket(self._cmd_socket)

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

    @staticmethod
    def _flush_socket(sock: socket.socket) -> None:
        """Drain any buffered packets from a socket."""
        original_timeout = sock.gettimeout()
        sock.settimeout(0.01)
        while True:
            try:
                sock.recvfrom(1518)
            except (TimeoutError, BlockingIOError, OSError):
                break
        sock.settimeout(original_timeout)

    def send_command(self, command: str, timeout: float | None = None) -> str:
        """Send a text command and wait for the response string."""
        timeout = timeout or self.RESPONSE_TIMEOUT
        self._cmd_socket.settimeout(timeout)

        self._cmd_socket.sendto(command.encode("utf-8"), self._tello_addr)

        try:
            data, _ = self._cmd_socket.recvfrom(1518)
            response = data.decode("utf-8", errors="replace").strip()
        except TimeoutError as e:
            raise TelloError(f"Timed out waiting for response to '{command}'") from e

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
