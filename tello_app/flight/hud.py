"""
flight/hud.py — render-agnostic HUD content for the FPV overlay.

Decides WHAT the heads-up display shows (telemetry, rc vector, control help);
the shell decides HOW to render it. The on-screen control reference lives in
one place — next to a test that checks it against the keymap in controller.py.
"""
from tello_app.flight.controller import FlightController
from tello_app.tello import Tello

# On-screen control reference. Mirrors controller.MOVES / DISCRETES;
# test_hud.py asserts every mapped key appears here so the two can't drift.
HELP_LINES = (
    "W/S fwd/back   A/D strafe   I/K up/down   J/L yaw",
    "t takeoff   g land   f flip   h hover   y/u speed",
    "SPACE = EMERGENCY (drops!)        Esc/q = quit",
)


def telemetry_parts(drone: Tello, fc: FlightController) -> list[tuple[str, str]]:
    """(label, value) pairs so a renderer can style each readout individually."""
    st = drone.state
    return [
        ("battery", f"{st.get('bat', '?')}%"),
        ("alt", f"{st.get('h', '?')}cm"),
        ("speed", str(fc.speed)),
        ("flying", str(fc.flying)),
    ]


def telemetry_line(drone: Tello, fc: FlightController) -> str:
    """Battery / altitude / speed / flying — from pushed state + controller."""
    return "   ".join(f"{label} {value}" for label, value in telemetry_parts(drone, fc))


def battery_level(drone: Tello) -> int | None:
    """Battery % as an int, or None while telemetry hasn't arrived yet."""
    bat = drone.state.get("bat")
    return bat if isinstance(bat, int) else None


def rc_line(rc: tuple[int, int, int, int]) -> str:
    """The rc vector currently being streamed to the drone."""
    lr, fb, ud, yaw = rc
    return f"rc  lr={lr:+d} fb={fb:+d} ud={ud:+d} yaw={yaw:+d}"
