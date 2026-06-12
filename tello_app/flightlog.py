"""
flightlog.py — JSONL flight recorder.

One file per session under logs/, one event per line:

    {"t": 1781234567.123, "mono": 12.4501, "type": "rc", "lr": 0, "fb": 20, ...}

`t` is wall-clock (cross-session reference), `mono` is time.monotonic()
(interval math — immune to NTP jumps). Event types: session, state, cmd,
stale, rc, emergency, action, mode, det, close.

Stdlib only. Every write is fail-silent: logging must never touch the
flight path. NullLog is the no-op stand-in so call sites need no `if log`
checks and a failed open degrades to "no log" rather than "no flight".
"""
import json
import os
import threading
import time


class FlightLog:
    """Append-only JSONL writer, thread-safe, fail-silent."""

    def __init__(self, path: str) -> None:
        self.path: str | None = path
        self._lock = threading.Lock()
        self._file = open(path, "a", buffering=1, encoding="utf-8")  # line-buffered
        self.event("session", started=time.strftime("%Y-%m-%dT%H:%M:%S%z"))

    def event(self, type_: str, **fields) -> None:
        self.event_fields(type_, fields)

    def event_fields(self, type_: str, fields: dict) -> None:
        """Dict form — safe for arbitrary parsed keys (e.g. raw state packets)."""
        try:
            rec = {"t": round(time.time(), 3), "mono": round(time.monotonic(), 4),
                   "type": type_}
            rec.update(fields)
            line = json.dumps(rec, separators=(",", ":"), default=str)
            with self._lock:
                self._file.write(line + "\n")
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.event("close")
            with self._lock:
                self._file.close()
        except Exception:
            pass


class NullLog:
    """No-op logger: same surface as FlightLog, writes nothing."""

    path: str | None = None

    def event(self, type_: str, **fields) -> None:
        pass

    def event_fields(self, type_: str, fields: dict) -> None:
        pass

    def close(self) -> None:
        pass


def open_session_log(directory: str = "logs") -> FlightLog | NullLog:
    """logs/<timestamp>.jsonl, or a NullLog if the filesystem says no."""
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, time.strftime("%Y-%m-%d_%H%M%S") + ".jsonl")
        return FlightLog(path)
    except Exception:
        return NullLog()
