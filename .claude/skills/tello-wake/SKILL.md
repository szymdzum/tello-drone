---
name: tello-wake
description: Connect to the Tello drone fast and keep it awake so it doesn't idle-power-off. Use whenever the user wants to connect to the Tello, "wake" the drone, keep it from turning off, hold a session open while tinkering, or get the link ready before running a flight/camera script. Knows the dual-NIC network setup and the VPN/ping gotcha specific to this machine.
---

# Tello: fast connect + keep awake

The Tello powers itself off after a few minutes idle (and auto-lands after 15 s
of silence in flight). `keepalive.py` holds an SDK session open and pings it
every ~8 s so it stays ready.

## 1. Network model (do NOT trust ping — a VPN fakes it)

This machine connects the Tello on **Wi-Fi `en0`** while keeping internet on a
**wired adapter `en5`**, so you don't lose the internet. The flight unit's AP is
**`TELLO-E95548`**. `keepalive.py` now **auto-rejoins that SSID** via
`networksetup` whenever macOS roams `en0` back to home Wi-Fi, so you normally
don't touch the Wi-Fi menu at all.

Quick sanity check if needed:
```bash
echo "en0=$(ipconfig getifaddr en0)  en5=$(ipconfig getifaddr en5)"
```
- `en0` should be `192.168.10.x` (Tello AP); `en5` a `192.168.1.x` (wired internet).
- **Reachability = a bound-8889 `command` handshake returning `ok`**, NOT ping
  (Tailscale/`utun0` answers `192.168.10.1` even with no drone connected).

## 2. Run keepalive (in the background so it holds while you work)

```bash
python /Users/DZUMAS02/Developer/tello-drone/keepalive.py
```
It force-joins the Tello AP if needed, connects fast, then prints
`awake — battery NN%` every ~8 s and stays glued (auto-rejoin on roam, full
reconnect on link loss). Flags: `--interval <sec>` (default 8), `--quiet`,
`--ssid <name>` (default `TELLO-E95548`; pass empty to disable auto-rejoin).

## 3. It owns port 8889 while running

Only one process can hold the command port. Before running `main.py` or
`video_stream.py`, **stop keepalive** (those scripts keep the drone awake via
their own commands). Restart keepalive afterwards for idle periods.

## Facts about this unit
- Standard Tello on **SDK 1.3-era firmware** (NOT EDU): `sdk?`, `sn?`,
  `hardware?`, `motoron`/`motoroff` all return "unknown command".
- A brand-new Tello must be **activated once in the official Tello app** before
  the SDK works — until then the command port replies in binary (`0xcc`) and
  ignores `command`.
- Video decode: use a sync-priority FFMPEG config (large `probesize` /
  `analyzeduration`, no `nobuffer`) or the decoder floods "non-existing PPS 0".
