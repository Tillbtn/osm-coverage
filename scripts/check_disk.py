#!/usr/bin/env python3
"""Check the free space of the filesystems the pipeline writes to.

Paths on the same filesystem are evaluated together. Each filesystem gets a
level, and a notification goes out when the level rises, as a reminder while it
stays (warn: weekly, critical: daily), and when it is back to ok:

    critical  free < DISK_CRIT_GB (default 2 GB)
    warn      free < DISK_WARN_GB (default 5 GB) or < DISK_WARN_PCT (default 15 %)
              of the filesystem, or full in < 14 days at the recent growth rate
    ok        otherwise

A level only drops once free space is 1 GB above its threshold, so a PBF swap
around a threshold does not flap. The growth rate is a least-squares fit over
the daily free-space samples of the last 14 days (needs 7), stored in
data/.notify_state.json.

With --preflight the script exits 2 when any filesystem is critical, and
run_updates.sh skips the update: a comparison that cannot finish writing its
outputs is worse than one that does not start.

Usage:
    python scripts/check_disk.py
    python scripts/check_disk.py --preflight
"""

import argparse
import datetime
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import notify

PATHS = ["data", "backups", os.path.join("site", "public")]
GB = 1024 ** 3
HYSTERESIS = 1 * GB
FORECAST_DAYS = 14
RATE_WINDOW_DAYS = 14
MIN_SAMPLES = 7
KEEP_SAMPLES = 30
LEVELS = ["ok", "warn", "critical"]
REMIND_EVERY = {"warn": datetime.timedelta(days=7), "critical": datetime.timedelta(days=1)}
TITLES = {"warn": "Speicherplatz knapp", "critical": "Speicherplatz kritisch"}
PRIORITY = {"warn": "default", "critical": "urgent"}
TOP_CONSUMERS = 5


def _env_number(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        print(f"[disk] Ignoring invalid {name}={os.environ.get(name)!r}")
        return default


def limits_from_env():
    return {
        "crit": _env_number("DISK_CRIT_GB", 2) * GB,
        "warn": _env_number("DISK_WARN_GB", 5) * GB,
        "pct": _env_number("DISK_WARN_PCT", 15) / 100,
    }


def filesystems(paths):
    """{label: [path, ...]} for the existing paths, one entry per filesystem."""
    groups = {}
    for path in paths:
        if os.path.exists(path):
            groups.setdefault(os.stat(path).st_dev, []).append(path)
    return {"+".join(group): group for group in groups.values()}


def loss_per_day(samples, today):
    """Bytes of free space lost per day (negative = space freed), or None.

    samples: [[iso date, free bytes], ...]; only the last RATE_WINDOW_DAYS count.
    """
    start = today - datetime.timedelta(days=RATE_WINDOW_DAYS)
    points = [((datetime.date.fromisoformat(d) - start).days, free) for d, free in samples
              if datetime.date.fromisoformat(d) >= start]
    if len(points) < MIN_SAMPLES:
        return None
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    var_x = sum((x - mean_x) ** 2 for x, _ in points)
    if not var_x:
        return None
    return -sum((x - mean_x) * (y - mean_y) for x, y in points) / var_x


def classify(free, total, days_left, previous, limits):
    """The level for one filesystem; `previous` adds the hysteresis margin."""
    crit_margin = HYSTERESIS if previous == "critical" else 0
    warn_margin = HYSTERESIS if previous in ("warn", "critical") else 0
    if free < limits["crit"] + crit_margin:
        return "critical"
    if (free < limits["warn"] + warn_margin
            or free < total * limits["pct"] + warn_margin
            or (days_left is not None and days_left < FORECAST_DAYS)):
        return "warn"
    return "ok"


def _size(num_bytes):
    if num_bytes >= GB:
        return f"{num_bytes / GB:.1f} GB"
    return f"{num_bytes / 1024 ** 2:.0f} MB"


def top_consumers(paths):
    """'path 1.2 GB, ...' for the largest entries directly below the paths."""
    children = [os.path.join(p, c) for p in paths for c in sorted(os.listdir(p))]
    if not children:
        return None
    try:
        out = subprocess.run(["du", "-sk", "--one-file-system", *children],
                             capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    sizes = []
    for line in out.splitlines():
        kb, _, name = line.partition("\t")
        if kb.isdigit():
            sizes.append((int(kb) * 1024, name))
    sizes.sort(reverse=True)
    return ", ".join(f"{name} {_size(size)}" for size, name in sizes[:TOP_CONSUMERS])


def describe(free, total, loss, days_left):
    text = f"{free / GB:.1f} GB frei von {total / GB:.0f} GB ({free / total:.0%})."
    if loss is not None and loss > 0:
        text += f" Verbrauch ~{loss / 1024 ** 2:.0f} MB/Tag, voll in ~{days_left:.0f} Tagen."
    return text


def _mark_sent(label, fields, when):
    with notify.edit_state() as state:
        entry = state.get("disk", {}).get(label)
        if entry:
            entry.update({field: when for field in fields})


def _parse_time(value):
    try:
        return datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def check(paths, limits, now):
    """Evaluate every filesystem, update the stored state, notify on changes.

    Returns {label: level}.
    """
    today = now.date().isoformat()
    groups = filesystems(paths)
    results = {}
    with notify.edit_state() as state:
        disks = state.setdefault("disk", {})
        for label in [l for l in disks if l not in groups]:
            del disks[label]  # the mount layout changed
        for label, group in groups.items():
            usage = shutil.disk_usage(group[0])
            entry = disks.setdefault(label, {"level": "ok", "samples": []})
            if not entry["samples"] or entry["samples"][-1][0] != today:
                entry["samples"].append([today, usage.free])
                del entry["samples"][:-KEEP_SAMPLES]
            loss = loss_per_day(entry["samples"], now.date())
            days_left = usage.free / loss if loss and loss > 0 else None
            previous = entry.get("level", "ok")
            level = classify(usage.free, usage.total, days_left, previous, limits)
            entry["level"] = level
            if level == "ok":
                alerted = entry.pop("alerted_at", None)
                entry.pop("reminded_at", None)
            else:
                alerted = entry.get("alerted_at")
            results[label] = {"group": group, "level": level, "previous": previous,
                              "alerted": alerted, "reminded": entry.get("reminded_at"),
                              "text": describe(usage.free, usage.total, loss, days_left)}
            print(f"[disk] {label}: {usage.free / GB:.1f} GB free "
                  f"({usage.free / usage.total:.0%}), {level}")

    stamp = now.isoformat()
    for label, r in results.items():
        level = r["level"]
        if level == "ok":
            if r["previous"] != "ok" and r["alerted"]:
                notify.deliver("alerts", f"Speicherplatz wieder ok: {label}", r["text"],
                               "low", ("white_check_mark",))
            continue
        rose = LEVELS.index(level) > LEVELS.index(r["previous"])
        last = _parse_time(r["reminded"]) or _parse_time(r["alerted"])
        if rose or not r["alerted"]:
            title, fields = f"{TITLES[level]}: {label}", ("alerted_at", "reminded_at")
        elif last is None or now - last >= REMIND_EVERY[level]:
            title, fields = f"Weiterhin: {TITLES[level]}: {label}", ("reminded_at",)
        else:
            continue
        consumers = top_consumers(r["group"])
        message = r["text"] + (f"\nGrößte Verzeichnisse: {consumers}" if consumers else "")
        notify.deliver("alerts", title, message, PRIORITY[level], ("floppy_disk",),
                       on_sent=lambda label=label, fields=fields: _mark_sent(label, fields, stamp))

    if all(r["level"] == "ok" for r in results.values()):
        notify.track_success("disk:enospc")
    return {label: r["level"] for label, r in results.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--preflight", action="store_true",
                        help="exit 2 when any filesystem is critical")
    args = parser.parse_args()

    with notify.batch():
        levels = check(PATHS, limits_from_env(), datetime.datetime.now().replace(microsecond=0))
    if args.preflight and "critical" in levels.values():
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
