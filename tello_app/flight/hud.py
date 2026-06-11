"""
flight/hud.py — the data layer for the HUD.

snapshot() collects everything a renderer needs from drone telemetry and the
flight controller; HELP_LINES is the on-screen control reference. Rendering
lives in tello_app/shells/hud_render.py — this module stays presentation-free
so it's unit-testable without cv2.
"""
from tello_app.flight.controller import FlightController
from tello_app.tello import Tello

# On-screen control reference. Mirrors controller.MOVES / DISCRETES;
# test_hud.py asserts every mapped key appears here so the two can't drift.
# ASCII only — OpenCV's Hershey fonts render anything else as '?'.
HELP_LINES = (
    "W/S fwd-back   A/D strafe   I/K up-down   J/L yaw   "
    "t/g/f/h   y/u speed   SPACE emergency   Esc/q quit",
)


def snapshot(drone: Tello, fc: FlightController) -> dict:
    """Everything a HUD renderer needs, in one dict. Values that haven't
    arrived in telemetry yet are None (attitude defaults to level)."""
    st = drone.state

    def num(key: str) -> int | float | None:
        v = st.get(key)
        return v if isinstance(v, (int, float)) else None

    vgx, vgy, vgz = num("vgx"), num("vgy"), num("vgz")
    vel = None
    if vgx is not None and vgy is not None and vgz is not None:
        vel = (vgx * vgx + vgy * vgy + vgz * vgz) ** 0.5 / 10.0  # dm/s -> m/s
    return {
        "bat": num("bat"),
        "alt": num("h"),          # cm
        "tof": num("tof"),        # cm
        "temp": num("temph"),     # deg C
        "time": num("time"),      # flight seconds
        "vel": vel,               # m/s ground velocity magnitude
        "pitch": num("pitch") or 0,
        "roll": num("roll") or 0,
        "yaw": num("yaw") or 0,
        "speed": fc.speed,
        "flying": fc.flying,
        "emergency": fc.emergency,
    }
