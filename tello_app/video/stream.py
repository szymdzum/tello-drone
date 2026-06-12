"""
video/stream.py — background H.264 reader with latest-frame-wins delivery.

Prefers PyAV (what DJITelloPy switched to in 2.5.0 to cut the ~1 s latency of
cv2's FFMPEG capture); falls back to cv2.VideoCapture when `av` isn't installed.
Either way decoding runs on its own daemon thread and only the newest frame is
kept, so decode hiccups can never stall the control loop.
"""
import os
import threading
import time

import cv2

try:
    import av  # PyAV — lower-latency H.264 decode than cv2's FFMPEG capture
    _HAVE_AV = True
except ImportError:
    _HAVE_AV = False

# FFmpeg tuning for reliable H.264 sync: a large probesize/analyzeduration lets
# the decoder wait for a keyframe carrying the SPS/PPS parameter sets before
# decoding. Do NOT add `fflags;nobuffer` or a small probesize — joining mid-GOP
# then floods the log with "non-existing PPS 0 referenced" and never decodes.
CAP_OPTIONS = "timeout;10000000|analyzeduration;6000000|probesize;6000000"
CAP_URL = "udp://0.0.0.0:11111?overrun_nonfatal=1&fifo_size=50000000"

AV_URL = "udp://@0.0.0.0:11111"


class VideoStream:
    """Background H.264 reader; read() returns the newest decoded frame."""

    def __init__(self, log=None) -> None:
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._log = log
        self._last_frame_at = 0.0
        self.backend = "pyav" if _HAVE_AV else "opencv"

    def _store(self, frame) -> None:
        """Keep the newest frame; log video stalls (>1 s between frames) —
        weak signal degrades video long before commands/telemetry, and
        pilots read a frozen feed as 'lost connection'."""
        now = time.monotonic()
        if self._log is not None and self._last_frame_at \
                and now - self._last_frame_at > 1.0:
            self._log.event("video", stall=round(now - self._last_frame_at, 2))
        self._last_frame_at = now
        with self._lock:
            self._frame = frame

    def start(self) -> None:
        self._running = True
        target = self._loop_av if _HAVE_AV else self._loop_cv2
        threading.Thread(target=target, daemon=True).start()

    def _loop_av(self) -> None:
        while self._running:
            try:
                # (open, read) timeouts — without a read timeout a mid-session
                # stall blocks decode() forever and the reopen path never runs.
                container = av.open(AV_URL, timeout=(5.0, 5.0))
                try:
                    for frame in container.decode(video=0):
                        if not self._running:
                            break
                        self._store(frame.to_ndarray(format="bgr24"))
                finally:
                    container.close()
            except Exception:
                time.sleep(1)  # stream hiccup / not up yet — reopen

    def _loop_cv2(self) -> None:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = CAP_OPTIONS
        cap = cv2.VideoCapture(CAP_URL, cv2.CAP_FFMPEG)
        fails = 0
        while self._running:
            ok, frame = cap.read()
            if not ok:
                fails += 1
                if fails > 30:  # stream stalled — rebuild the capture
                    cap.release()
                    time.sleep(1)
                    cap = cv2.VideoCapture(CAP_URL, cv2.CAP_FFMPEG)
                    fails = 0
                continue
            fails = 0
            self._store(frame)
        cap.release()

    def read(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self) -> None:
        self._running = False
