"""
shells/hud_render.py — arcade flight-sim HUD drawn with OpenCV primitives.

Implements the "Tello FPV HUD concept" sheet: hero battery with segmented bar,
heading strip, ALT/TIME panel, attitude ladder + reticle, mini telemetry,
dual virtual sticks, status bar + controls legend, and the low-battery /
emergency / connecting state variants. Pure presentation — all flight data
arrives via hud.snapshot(); nothing here touches the drone.

All on-screen strings must be ASCII (OpenCV's Hershey fonts render anything
else as '?').
"""
import math

import cv2
import numpy as np

from tello_app.flight import hud

# Palette (BGR) — from the design sheet.
BG = (24, 18, 12)          # panel background
STROKE = (70, 58, 42)      # panel stroke
TEXT = (235, 245, 245)     # primary text
TEXT2 = (180, 205, 205)    # secondary text
CYAN = (255, 220, 60)      # accent cyan
BLUE = (235, 160, 40)      # accent blue
OK = (90, 220, 90)         # ok green
WARN = (40, 190, 255)      # caution amber
DANGER = (70, 70, 255)     # danger red

FONT = cv2.FONT_HERSHEY_SIMPLEX
HERO = cv2.FONT_HERSHEY_DUPLEX  # blockier face for the big values

LOW_BATTERY_PCT = 20


def _ascii(s: str) -> str:
    return "".join(ch if 32 <= ord(ch) < 127 else "-" for ch in s)


def _text(frame, s, org, scale, color, thick=1, font=FONT):
    cv2.putText(frame, _ascii(s), org, font, scale, color, thick, cv2.LINE_AA)


def _width(s, scale, thick=1, font=FONT) -> int:
    return cv2.getTextSize(_ascii(s), font, scale, thick)[0][0]


def _panel(frame, x0, y0, x1, y1, stroke=STROKE, alpha=0.6):
    """Semi-transparent dark panel with a 1-px stroke."""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    if x1 <= x0 or y1 <= y0:
        return
    roi = frame[y0:y1, x0:x1]
    overlay = np.empty_like(roi)
    overlay[:] = BG
    cv2.addWeighted(overlay, alpha, roi, 1 - alpha, 0, dst=roi)
    cv2.rectangle(frame, (x0, y0), (x1 - 1, y1 - 1), stroke, 1, cv2.LINE_AA)


def _battery_color(level):
    if level is None:
        return TEXT2
    return DANGER if level <= LOW_BATTERY_PCT else WARN if level <= 50 else OK


_LEGEND = "   ".join(hud.HELP_LINES)
_LEGEND_W = _width(_LEGEND, 0.4)


# ── HUD elements ────────────────────────────────────────────


def _battery(frame, bat) -> None:
    """Hero battery: big % + 5-segment bar, top-left."""
    _panel(frame, 14, 14, 200, 72)
    _text(frame, "BATTERY", (26, 34), 0.4, TEXT2)
    color = _battery_color(bat)
    _text(frame, f"{bat}%" if bat is not None else "--%", (24, 62), 0.75, color, 1, HERO)
    filled = 0 if bat is None else max(0, min(5, (bat + 19) // 20))
    for i in range(5):
        x0 = 112 + i * 16
        if i < filled:
            cv2.rectangle(frame, (x0, 48), (x0 + 12, 62), color, -1)
        else:
            cv2.rectangle(frame, (x0, 48), (x0 + 12, 62), STROKE, 1)


def _yaw_tape(frame, yaw, w) -> None:
    """Sliding yaw tape, top-center. The Tello has no compass: yaw is relative
    to the heading at power-on, so this shows signed degrees (0 = boot heading)
    rather than pretending to know where north is."""
    cx = w // 2
    x0, x1, y0, y1 = cx - 170, cx + 170, 14, 66
    _panel(frame, x0, y0, x1, y1)
    _text(frame, "YAW", (x0 + 10, 32), 0.38, TEXT2)
    rel = (int(yaw) + 180) % 360 - 180  # wrap to -180..180
    ppd = 2.4  # pixels per degree
    # Walk the 15-degree grid around the current yaw; label 45-multiples.
    first = (rel // 15) * 15 - 60
    for d in range(first, first + 135, 15):
        x = int(cx + (d - rel) * ppd)
        if not x0 + 40 < x < x1 - 12:
            continue
        if d % 45 == 0:
            label = str((d + 180) % 360 - 180)
            _text(frame, label, (x - _width(label, 0.38) // 2, 32), 0.38, TEXT)
            cv2.line(frame, (x, 38), (x, 46), TEXT2, 1, cv2.LINE_AA)
        else:
            cv2.line(frame, (x, 40), (x, 46), TEXT2, 1, cv2.LINE_AA)
    cv2.fillConvexPoly(frame, np.array([[cx - 6, y0 + 2], [cx + 6, y0 + 2],
                                        [cx, y0 + 10]]), CYAN)
    val = f"{rel:+d}" if rel else "0"
    _text(frame, val, (cx - _width(val, 0.55, 2) // 2, 61), 0.55, CYAN, 2)


def _alt_time(frame, alt, secs, w) -> None:
    """ALT + TIME panel, top-right."""
    x1 = w - 14
    x0 = x1 - 200
    _panel(frame, x0, 14, x1, 72)
    _text(frame, "ALT", (x0 + 14, 38), 0.45, TEXT2)
    _text(frame, f"{alt} cm" if alt is not None else "-- cm",
          (x0 + 72, 40), 0.6, TEXT, 1, HERO)
    _text(frame, "TIME", (x0 + 14, 64), 0.45, TEXT2)
    _text(frame, f"{secs} s" if secs is not None else "-- s",
          (x0 + 72, 66), 0.6, TEXT, 1, HERO)


def _ladder(frame, pitch, roll, w, h) -> None:
    """Attitude ladder (rolls/slides with the drone) + fixed center reticle."""
    cx, cy = w // 2, h // 2
    a = math.radians(-roll)
    cos_a, sin_a = math.cos(a), math.sin(a)

    def pt(x: float, y: float) -> tuple[int, int]:
        return (int(cx + x * cos_a - y * sin_a), int(cy + x * sin_a + y * cos_a))

    ppd = 3.5  # pixels per degree of pitch
    for p in (-20, -10, 0, 10, 20):
        dy = (pitch - p) * ppd
        half = 100 if p == 0 else 55
        gap = 28
        col = TEXT if p == 0 else TEXT2
        cv2.line(frame, pt(-half, dy), pt(-gap, dy), col, 1, cv2.LINE_AA)
        cv2.line(frame, pt(gap, dy), pt(half, dy), col, 1, cv2.LINE_AA)
        if p:
            for side in (-1, 1):
                lx, ly = pt(side * (half + 20), dy + 4)
                _text(frame, str(p), (lx - 10, ly), 0.38, TEXT2)
    # Fixed reticle: center circle + wing bars (does not roll).
    cv2.circle(frame, (cx, cy), 9, OK, 1, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), 2, OK, -1, cv2.LINE_AA)
    for side in (-1, 1):
        cv2.line(frame, (cx + side * 40, cy), (cx + side * 70, cy), OK, 1, cv2.LINE_AA)
        cv2.line(frame, (cx + side * 40, cy), (cx + side * 40, cy + 6), OK, 1, cv2.LINE_AA)


def _mini_telemetry(frame, snap, w, h) -> None:
    """ToF / temp / velocity panel, right edge above the stick."""
    rows = [
        ("ToF", f"{snap['tof']} cm" if snap["tof"] is not None else "--"),
        ("TEMP", f"{snap['temp']} C" if snap["temp"] is not None else "--"),
        ("VEL", f"{snap['vel']:.1f} m/s" if snap["vel"] is not None else "--"),
    ]
    x1 = w - 14
    x0 = x1 - 185
    y0 = h // 2 - 140
    _panel(frame, x0, y0, x1, y0 + 14 + len(rows) * 26)
    for i, (label, value) in enumerate(rows):
        y = y0 + 30 + i * 26
        _text(frame, label, (x0 + 12, y), 0.45, CYAN)
        _text(frame, value, (x1 - 12 - _width(value, 0.45, 1), y), 0.45, TEXT)


def _stick(frame, cx, cy, r, xval, yval, labels, active) -> None:
    """Virtual stick: ring + crosshair + input dot. labels = (top, bottom, left, right)."""
    cv2.circle(frame, (cx, cy), r, STROKE, 2, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), int(r * 0.55), STROKE, 1, cv2.LINE_AA)
    cv2.line(frame, (cx - r, cy), (cx + r, cy), STROKE, 1, cv2.LINE_AA)
    cv2.line(frame, (cx, cy - r), (cx, cy + r), STROKE, 1, cv2.LINE_AA)
    top, bottom, left, right = labels
    _text(frame, top, (cx - _width(top, 0.4) // 2, cy - r - 8), 0.4, TEXT2)
    _text(frame, bottom, (cx - _width(bottom, 0.4) // 2, cy + r + 16), 0.4, TEXT2)
    _text(frame, left, (cx - r - 10 - _width(left, 0.4), cy + 4), 0.4, TEXT2)
    _text(frame, right, (cx + r + 10, cy + 4), 0.4, TEXT2)
    px = int(cx + xval / 100 * (r - 14))
    py = int(cy - yval / 100 * (r - 14))
    color = OK if active else BLUE
    cv2.circle(frame, (px, py), 9, color, -1, cv2.LINE_AA)
    cv2.circle(frame, (px, py), 9, TEXT, 1, cv2.LINE_AA)


def _status_bar(frame, snap, status, w, h, emergency, down_hint=False) -> None:
    """SPEED | STATE | STATUS cells, bottom-center, with the legend below."""
    x0, x1 = w // 2 - 280, w // 2 + 280
    y0, y1 = h - 92, h - 50
    _panel(frame, x0, y0, x1, y1, stroke=DANGER if emergency else STROKE)
    c1, c2 = x0 + 110, x0 + 300
    cv2.line(frame, (c1, y0 + 6), (c1, y1 - 6), STROKE, 1)
    cv2.line(frame, (c2, y0 + 6), (c2, y1 - 6), STROKE, 1)
    # Big value = ACTUAL velocity (0.0 while parked); the y/u rc-speed
    # setting rides along small next to the label.
    _text(frame, "SPEED", (x0 + 14, y0 + 16), 0.38, TEXT2)
    _text(frame, f"set {snap['speed']}",
          (x0 + 14 + _width("SPEED", 0.38) + 8, y0 + 16), 0.38, BLUE)
    vel = 0.0 if emergency else snap["vel"]
    vel_txt = f"{vel:.1f}" if vel is not None else "--"
    _text(frame, vel_txt, (x0 + 14, y1 - 9), 0.65, TEXT, 1, HERO)
    _text(frame, "m/s", (x0 + 18 + _width(vel_txt, 0.65, 1, HERO), y1 - 9), 0.38, TEXT2)
    if emergency:
        state, state_col = "DISARMED", DANGER
    elif snap["flying"] and down_hint:
        # Telemetry says grounded while we believe airborne (crash?) — stop
        # claiming AIRBORNE, tell the pilot how to resync.
        state, state_col = "DOWN? (g)", WARN
    elif snap["flying"]:
        state, state_col = "AIRBORNE", OK
    else:
        state, state_col = "ON GROUND", TEXT2
    _text(frame, "STATE", (c1 + 14, y0 + 16), 0.38, TEXT2)
    _text(frame, state, (c1 + 14, y1 - 9), 0.65, state_col, 1, HERO)
    _text(frame, "STATUS", (c2 + 14, y0 + 16), 0.38, TEXT2)
    _text(frame, _ascii(status)[:30], (c2 + 14, y1 - 11), 0.48, WARN if status else TEXT2)
    # Controls legend.
    lx0 = max(10, (w - _LEGEND_W) // 2 - 10)
    _panel(frame, lx0, h - 42, min(w - 10, lx0 + _LEGEND_W + 20), h - 16, alpha=0.5)
    _text(frame, _LEGEND, ((w - _LEGEND_W) // 2, h - 24), 0.4, TEXT2)


def draw_face(frame, box, following: bool) -> None:
    """Face-detection box with corner ticks; cyan = seen, green = steering."""
    x, y, bw, bh = box
    color = OK if following else CYAN
    t = max(10, bw // 5)
    for cx, sx in ((x, 1), (x + bw, -1)):
        for cy, sy in ((y, 1), (y + bh, -1)):
            cv2.line(frame, (cx, cy), (cx + sx * t, cy), color, 2, cv2.LINE_AA)
            cv2.line(frame, (cx, cy), (cx, cy + sy * t), color, 2, cv2.LINE_AA)
    if following:
        _text(frame, "LOCK", (x, y - 8), 0.45, color)


def _autopilot_badge(frame, w, locked: bool, mode: str) -> None:
    """Autopilot mode indicator under the yaw tape (FOLLOW / MARKER)."""
    label = mode.upper() if locked else f"{mode.upper()} (no target)"
    color = OK if locked else WARN
    lw = _width(label, 0.5, 1)
    x0 = (w - lw) // 2 - 12
    _panel(frame, x0, 74, x0 + lw + 24, 100, stroke=color)
    _text(frame, label, ((w - lw) // 2, 92), 0.5, color)


def draw_discs(frame, boxes) -> None:
    """Floor-disc detections: ellipse outlines, nearest labelled. Display-only
    for now — the objective mission will steer on these later."""
    for i, (x, y, w, h) in enumerate(boxes):
        cv2.ellipse(frame, (x + w // 2, y + h // 2), (w // 2 + 4, h // 2 + 4),
                    0, 0, 360, CYAN, 2, cv2.LINE_AA)
        if i == 0:
            _text(frame, "DISC", (x, y - 8), 0.45, CYAN)


def draw_marker(frame, corners, locked: bool, marker_id: int) -> None:
    """ArUco marker outline; cyan = seen, green = actively holding on it."""
    color = OK if locked else CYAN
    pts = corners.reshape(-1, 1, 2)
    cv2.polylines(frame, [pts], True, color, 2, cv2.LINE_AA)
    x, y = int(corners[:, 0].min()), int(corners[:, 1].min())
    _text(frame, f"M{marker_id}" + (" LOCK" if locked else ""), (x, y - 8), 0.45, color)


# ── State variants ──────────────────────────────────────────


def _low_battery_warning(frame, w, h) -> None:
    x0, x1 = w // 2 - 160, w // 2 + 160
    y0, y1 = h // 2 + 56, h // 2 + 120
    _panel(frame, x0, y0, x1, y1, stroke=WARN, alpha=0.7)
    tri = np.array([[x0 + 28, y0 + 44], [x0 + 44, y0 + 44], [x0 + 36, y0 + 20]])
    cv2.polylines(frame, [tri], True, WARN, 2, cv2.LINE_AA)
    _text(frame, "!", (x0 + 33, y0 + 41), 0.45, WARN, 2)
    _text(frame, "LOW BATTERY", (x0 + 62, y0 + 28), 0.6, WARN, 2)
    _text(frame, "RETURN SOON", (x0 + 62, y0 + 52), 0.5, TEXT2, 1)


def _emergency_overlay(frame, w, h) -> None:
    cv2.rectangle(frame, (3, 3), (w - 4, h - 4), DANGER, 2)
    cv2.rectangle(frame, (9, 9), (w - 10, h - 10), DANGER, 1)
    x0, x1 = w // 2 - 190, w // 2 + 190
    y0, y1 = h // 2 - 76, h // 2 + 4
    _panel(frame, x0, y0, x1, y1, stroke=DANGER, alpha=0.8)
    msg = "EMERGENCY STOP"
    _text(frame, msg, ((w - _width(msg, 0.9, 2, HERO)) // 2, y0 + 44), 0.9, DANGER, 2, HERO)
    sub = "MOTORS CUT"
    _text(frame, sub, ((w - _width(sub, 0.5)) // 2, y0 + 68), 0.5, TEXT2)


def draw(frame, snap: dict, rc: tuple[int, int, int, int], status: str,
         face_locked: bool = False, down_hint: bool = False) -> None:
    """Render the full HUD onto a video frame (in place)."""
    h, w = frame.shape[:2]
    emergency = snap["emergency"]  # real state, not a status-text parse
    lr, fb, ud, yaw_in = rc

    _ladder(frame, snap["pitch"], snap["roll"], w, h)
    _battery(frame, snap["bat"])
    _yaw_tape(frame, snap["yaw"], w)
    _alt_time(frame, snap["alt"], snap["time"], w)
    _mini_telemetry(frame, snap, w, h)
    # Sticks match the hands: left circle = WASD (forward/back + strafe),
    # right circle = IJKL (throttle + yaw).
    _stick(frame, 112, h - 136, 60, lr, fb, ("FWD", "BACK", "LEFT", "RIGHT"),
           snap["flying"])
    _stick(frame, w - 112, h - 136, 60, yaw_in, ud, ("UP", "DOWN", "L", "R"),
           snap["flying"])
    _status_bar(frame, snap, status, w, h, emergency, down_hint)
    if snap.get("autopilot"):
        _autopilot_badge(frame, w, face_locked, snap["autopilot"])

    if emergency:
        _emergency_overlay(frame, w, h)
    elif snap["flying"] and snap["bat"] is not None and snap["bat"] <= LOW_BATTERY_PCT:
        _low_battery_warning(frame, w, h)


def draw_connecting(frame, line1: str = "CONNECTING TO TELLO...",
                    line2: str = "VIDEO LINK INIT") -> None:
    """Boot screen for frames before the video link is up."""
    h, w = frame.shape[:2]
    for cx, sx in ((40, 1), (w - 40, -1)):
        for cy, sy in ((40, 1), (h - 40, -1)):
            cv2.line(frame, (cx, cy), (cx + sx * 36, cy), CYAN, 2, cv2.LINE_AA)
            cv2.line(frame, (cx, cy), (cx, cy + sy * 36), CYAN, 2, cv2.LINE_AA)
    _text(frame, line1, ((w - _width(line1, 0.7, 2)) // 2, h // 2 - 24), 0.7, CYAN, 2)
    _text(frame, line2, ((w - _width(line2, 0.55, 1)) // 2, h // 2 + 8), 0.55, TEXT2)
    cv2.drawMarker(frame, (w // 2, h // 2 + 48), CYAN, cv2.MARKER_DIAMOND, 14, 1, cv2.LINE_AA)
    _text(frame, "Please wait...", ((w - _width("Please wait...", 0.45)) // 2,
                                    h // 2 + 92), 0.45, TEXT2)
