"""
flight/tracking.py — pure follow-control: turn a face detection into rc velocities.

P-controller per axis: yaw centers the face horizontally, ud vertically, fb
holds a target apparent size (a proxy for distance). Detections arrive as plain
frame-fraction tuples — no cv2 here, so this is unit-testable like
FlightController. The detector producing them lives in tello_app/vision/face.py.
"""

# A detection: (cx, cy, width), all as 0..1 fractions of the frame.
Detection = tuple[float, float, float]

YAW_GAIN = 140     # rc units per unit of horizontal error (face at frame edge -> 70)
UD_GAIN = 120
FB_GAIN = 250
TARGET_W = 0.18    # face width fraction to hold ≈ comfortable follow distance
DEADBAND = 0.06    # ignore centering errors smaller than this (detector jitter)
FB_DEADBAND = 0.03
MAX_YAW = 60
MAX_UD = 50
MAX_FB = 35        # approach speed capped low — it flies toward a person
LOST_HOLD_S = 0.5  # coast on the last command this long after losing the face


def _axis(err: float, gain: float, deadband: float, limit: int) -> int:
    if abs(err) <= deadband:
        return 0
    return int(max(-limit, min(limit, gain * err)))


DAMP_GAIN = 4      # rc units per dm/s of reported drift
DAMP_MAX = 25      # gentle by design: a damper, not an autopilot
DAMP_DEADBAND = 1  # dm/s — velocity-estimate noise at rest


def drift_correction(vgx, vgy) -> tuple[int, int, int, int]:
    """Idle-drift damper: oppose the drone's own reported lateral velocity.

    The firmware's position hold goes blind on featureless floors and the
    drone glides off on room air — while its telemetry keeps reporting the
    drift (vgx/vgy, dm/s, body frame). Streamed instead of pure zeros when
    the sticks are quiet. ud/yaw stay 0: baro holds height, yaw doesn't drift.

    Sign convention verified empirically from the 2026-06-12 session logs:
    positive fb command -> positive vgx (59:0 samples), positive lr ->
    positive vgy (76:7) — so the counter-command is the negation.
    """
    fb = -_axis(vgx, DAMP_GAIN, DAMP_DEADBAND, DAMP_MAX) \
        if isinstance(vgx, (int, float)) else 0
    lr = -_axis(vgy, DAMP_GAIN, DAMP_DEADBAND, DAMP_MAX) \
        if isinstance(vgy, (int, float)) else 0
    return (lr, fb, 0, 0)


class FaceFollower:
    """Latest detection + lost-face timeout -> (lr, fb, ud, yaw) velocities.

    Lost-face behavior: hold the last command for LOST_HOLD_S (detector
    flicker must not stutter the flight), then hover. It never searches —
    a blind drone that wanders is how you hit a wall."""

    def __init__(self) -> None:
        self._last_seen = 0.0
        self._vel = (0, 0, 0, 0)

    def update(self, det: Detection | None, now: float) -> tuple[int, int, int, int]:
        if det is None:
            if now - self._last_seen > LOST_HOLD_S:
                self._vel = (0, 0, 0, 0)
            return self._vel
        self._last_seen = now
        cx, cy, w = det
        yaw = _axis(cx - 0.5, YAW_GAIN, DEADBAND, MAX_YAW)   # face right -> yaw right
        ud = _axis(0.5 - cy, UD_GAIN, DEADBAND, MAX_UD)      # face high -> climb
        fb = _axis(TARGET_W - w, FB_GAIN, FB_DEADBAND, MAX_FB)  # face small -> approach
        self._vel = (0, fb, ud, yaw)
        return self._vel
