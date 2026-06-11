"""
util.py — host-side helpers that aren't about the drone protocol itself.
"""
import subprocess
import time

# Default Tello AP for this project's flight unit. macOS likes to roam back to
# an internet-capable network; ensure_on_tello can force en0 back here.
DEFAULT_SSID = "TELLO-E95548"
WIFI_IFACE = "en0"


def _en0_ip() -> str:
    try:
        out = subprocess.run(
            ["ipconfig", "getifaddr", WIFI_IFACE],
            capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def ensure_on_tello(ssid: str, quiet: bool = False) -> bool:
    """If en0 isn't on the Tello, join the Tello AP (when its Wi-Fi is up).

    Returns True once en0 holds a 192.168.10.x address. Internet is expected to
    live on a separate (wired) interface, so taking en0 for the Tello is safe.
    """
    if _en0_ip().startswith("192.168.10."):
        return True
    if not ssid:
        return False
    if not quiet:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] en0 not on the Tello — joining {ssid}...", flush=True)
    try:
        subprocess.run(
            ["networksetup", "-setairportnetwork", WIFI_IFACE, ssid],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        pass
    for _ in range(8):  # wait for association + DHCP
        if _en0_ip().startswith("192.168.10."):
            return True
        time.sleep(1)
    return _en0_ip().startswith("192.168.10.")


def warn_if_awdl_active() -> None:
    """macOS AWDL (AirDrop/AirPlay) hops the Wi-Fi radio to 5 GHz every ~1 s,
    stalling UDP for 50-100 ms bursts — enough to drop rc/command packets to the
    Tello. Take it down automatically if the passwordless sudoers rule is
    installed; otherwise tell the pilot exactly what to run."""
    try:
        out = subprocess.run(["ifconfig", "awdl0"],
                             capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return
    if "status: active" not in out:
        return
    # Non-interactive sudo: succeeds silently if /etc/sudoers.d/awdl exists,
    # fails fast (no password prompt) if it doesn't.
    try:
        r = subprocess.run(["sudo", "-n", "/sbin/ifconfig", "awdl0", "down"],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            print("✓ AWDL (AirDrop) taken down for a cleaner drone link.")
            return
    except Exception:
        pass
    print("⚠ macOS AWDL (AirDrop/AirPlay) is ACTIVE — it stalls Wi-Fi every ~1 s.")
    print("  Take it down for this session:")
    print("    sudo ifconfig awdl0 down")
    print("  One-time setup so these scripts can do it automatically, no password:")
    print("    echo \"$USER ALL=(ALL) NOPASSWD: /sbin/ifconfig awdl0 down\" | sudo tee /etc/sudoers.d/awdl")
