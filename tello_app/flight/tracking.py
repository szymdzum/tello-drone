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


# Marker hold (press 'm'): the same controller with a tighter size band (a
# marker at hold distance spans only a few % of frame width) and the target
# size CAPTURED at engagement — hold distance is wherever the drone was when
# 'm' was pressed, independent of the physical marker size (phone vs print).
MARKER_FB_DEADBAND = 0.012
CAPTURE_W_MIN = 0.03   # captured setpoint clamps: engaging from very far makes
CAPTURE_W_MAX = 0.20   # distance control noisy; very close is just unsafe
LR_GAIN = 90           # strafe-centering gain (marker hold)
MAX_LR = 30


class FaceFollower:
    """Latest detection + lost-target timeout -> (lr, fb, ud, yaw) velocities.

    Works for any centered-box target: faces by default; marker_holder()
    builds one tuned for ArUco hold. Lost-target behavior: hold the last
    command for LOST_HOLD_S (detector flicker must not stutter the flight),
    then hover. It never searches — a blind drone that wanders is how you
    hit a wall."""

    def __init__(self, target_w: float | None = TARGET_W,
                 fb_deadband: float = FB_DEADBAND,
                 strafe_centering: bool = False) -> None:
        """strafe_centering: correct horizontal error with lr instead of yaw.
        REQUIRED for static targets (marker hold): yaw cannot counter lateral
        translation, so yaw-centering a fixed marker is structurally unstable —
        any sideways drift becomes a runaway orbit around the target (the
        2026-06-12 screen-test incident; VPS was blind so the drift damper saw
        zeros). Strafe opposes translation directly; heading stays put. Faces
        keep yaw-centering — a follower should turn to face a moving person.

        target_w=None: capture the setpoint from the first detection — 'hold
        the distance at which you engaged'. reset() re-arms the capture."""
        self._target_w = target_w
        self._capture = target_w is None
        self._fb_deadband = fb_deadband
        self._strafe = strafe_centering
        self._last_seen = 0.0
        self._vel = (0, 0, 0, 0)

    def reset(self) -> None:
        """Fresh engagement: drop coast state and re-arm setpoint capture."""
        self._last_seen = 0.0
        self._vel = (0, 0, 0, 0)
        if self._capture:
            self._target_w = None

    def update(self, det: Detection | None, now: float) -> tuple[int, int, int, int]:
        if det is None:
            if now - self._last_seen > LOST_HOLD_S:
                self._vel = (0, 0, 0, 0)
            return self._vel
        self._last_seen = now
        cx, cy, w = det
        if self._target_w is None:
            self._target_w = min(max(w, CAPTURE_W_MIN), CAPTURE_W_MAX)
        if self._strafe:
            lr = _axis(cx - 0.5, LR_GAIN, DEADBAND, MAX_LR)  # target right -> strafe right
            yaw = 0
        else:
            lr = 0
            yaw = _axis(cx - 0.5, YAW_GAIN, DEADBAND, MAX_YAW)  # target right -> yaw right
        ud = _axis(0.5 - cy, UD_GAIN, DEADBAND, MAX_UD)      # target high -> climb
        fb = _axis(self._target_w - w, FB_GAIN, self._fb_deadband, MAX_FB)
        self._vel = (lr, fb, ud, yaw)
        return self._vel


def marker_holder() -> FaceFollower:
    """Position hold relative to an ArUco marker (see vision/marker.py):
    strafe-centered, holding the distance at which 'm' was pressed."""
    return FaceFollower(target_w=None, fb_deadband=MARKER_FB_DEADBAND,
                        strafe_centering=True)
