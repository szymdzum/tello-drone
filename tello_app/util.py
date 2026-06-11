"""
util.py — host-side helpers that aren't about the drone protocol itself.
"""
import subprocess


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
