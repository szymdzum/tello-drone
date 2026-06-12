#!/usr/bin/env python3
"""
analyze.py — summarize (and optionally plot) a JSONL flight log.

    python analyze.py                       # newest file in logs/
    python analyze.py logs/<file>.jsonl
    python analyze.py --plot                # + charts (needs matplotlib)

The summary is stdlib-only: session length, battery drain, altitude, command
round-trips/timeouts, follow-mode share, and — the crash signature — the
longest gap in the rc stream while airborne.
"""
import argparse
import glob
import json
import os
import statistics
import sys


def load(path: str) -> list[dict]:
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # truncated tail line from a hard kill
    return events


def flight_intervals(events: list[dict]) -> list[tuple[float, float]]:
    """(takeoff, land) mono spans, from action events. An unclosed flight
    (crash / power loss) runs to the last event in the file."""
    spans, start = [], None
    for e in events:
        if e["type"] != "action":
            continue
        if e["action"] == "takeoff" and start is None:
            start = e["mono"]
        elif e["action"] in ("land", "emergency") and start is not None:
            spans.append((start, e["mono"]))
            start = None
    if start is not None and events:
        spans.append((start, events[-1]["mono"]))
    return spans


def max_rc_gap(events: list[dict], spans: list[tuple[float, float]]) -> float:
    """Longest silence in the rc stream while airborne — the crash signature."""
    worst = 0.0
    for t0, t1 in spans:
        ticks = [t0] + [e["mono"] for e in events
                        if e["type"] == "rc" and t0 <= e["mono"] <= t1] + [t1]
        worst = max(worst, max(b - a for a, b in zip(ticks, ticks[1:], strict=False)))
    return worst


def summarize(path: str) -> list[dict]:
    events = load(path)
    if not events:
        sys.exit(f"{path}: empty log")
    by_type: dict[str, list[dict]] = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)

    print(f"log:       {path}  ({len(events)} events)")
    started = by_type.get("session", [{}])[0].get("started", "?")
    span = events[-1]["mono"] - events[0]["mono"]
    print(f"session:   {started}, {span:.0f} s")

    states = by_type.get("state", [])
    if states:
        batts = [e["bat"] for e in states if "bat" in e]
        alts = [e["h"] for e in states if "h" in e]
        if batts:
            print(f"battery:   {batts[0]}% -> {batts[-1]}%  (drain {batts[0] - batts[-1]}%)")
        if alts:
            print(f"altitude:  max {max(alts)} cm")
    else:
        print("telemetry: none recorded")

    cmds = by_type.get("cmd", [])
    rtts = [e["rtt"] for e in cmds if "rtt" in e]
    timeouts = [e for e in cmds if e.get("error") == "timeout"]
    if rtts:
        print(f"commands:  {len(cmds)} sent, rtt median {statistics.median(rtts) * 1000:.0f} ms"
              f" / max {max(rtts) * 1000:.0f} ms, {len(timeouts)} timeouts,"
              f" {len(by_type.get('stale', []))} stale replies")
    for e in timeouts:
        print(f"  ⚠ timeout: '{e['cmd']}' at mono {e['mono']:.1f}")

    spans = flight_intervals(events)
    airtime = sum(t1 - t0 for t0, t1 in spans)
    print(f"flights:   {len(spans)}, airtime {airtime:.0f} s")
    if spans:
        gap = max_rc_gap(events, spans)
        flag = "  ⚠ rc stream starved (>1 s airborne)" if gap > 1.0 else ""
        print(f"rc stream: {len(by_type.get('rc', []))} sends,"
              f" max airborne gap {gap:.2f} s{flag}")

    rcs = by_type.get("rc", [])
    follow_rc = [e for e in rcs if e.get("src") == "follow"]
    if follow_rc:
        print(f"follow:    steered {len(follow_rc)}/{len(rcs)} rc sends"
              f" ({100 * len(follow_rc) / len(rcs):.0f}%),"
              f" {len(by_type.get('det', []))} face detections")
    for e in by_type.get("action", []):
        print(f"  [{e['mono']:8.1f}] {e['action']}: {e.get('result', '')}")
    return events


def plot(events: list[dict]) -> None:
    import matplotlib.pyplot as plt

    t0 = events[0]["mono"]
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, sharex=True, figsize=(12, 8))

    st = [e for e in events if e["type"] == "state"]
    ax1.plot([e["mono"] - t0 for e in st if "h" in e], [e["h"] for e in st if "h" in e],
             label="alt (cm)")
    ax1b = ax1.twinx()
    ax1b.plot([e["mono"] - t0 for e in st if "bat" in e],
              [e["bat"] for e in st if "bat" in e], "r--", label="bat (%)")
    ax1.set_ylabel("alt (cm)")
    ax1b.set_ylabel("bat (%)")
    ax1.legend(loc="upper left")

    rc = [e for e in events if e["type"] == "rc"]
    for axis in ("fb", "ud", "yaw"):
        ax2.plot([e["mono"] - t0 for e in rc], [e[axis] for e in rc], label=axis)
    for e in rc:
        if e.get("src") == "follow":
            ax2.axvspan(e["mono"] - t0, e["mono"] - t0 + 0.05, color="g", alpha=0.05)
    ax2.set_ylabel("rc")
    ax2.legend(loc="upper left")

    det = [e for e in events if e["type"] == "det"]
    ax3.plot([e["mono"] - t0 for e in det], [e["cx"] - 0.5 for e in det], ".",
             ms=2, label="face x-error")
    ax3.axhline(0, color="k", lw=0.5)
    ax3.set_ylabel("error")
    ax3.set_xlabel("flight time (s)")
    ax3.legend()

    fig.tight_layout()
    plt.show()


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize a JSONL flight log.")
    ap.add_argument("path", nargs="?", help="log file (default: newest in logs/)")
    ap.add_argument("--plot", action="store_true",
                    help="show charts (requires matplotlib)")
    args = ap.parse_args()

    path = args.path
    if path is None:
        candidates = sorted(glob.glob(os.path.join("logs", "*.jsonl")))
        if not candidates:
            sys.exit("no logs/*.jsonl found — fly first (or pass a path)")
        path = candidates[-1]

    events = summarize(path)
    if args.plot:
        plot(events)


if __name__ == "__main__":
    main()
