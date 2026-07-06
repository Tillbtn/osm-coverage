"""
Build the ALKIS freshness dashboard data: for every registered state, compare
the export date we last processed against the latest date available at the source,
and write site/public/alkis_status.json for the status page to render.

  processed_date : from data/<st>/alkis_meta.json's __state__ entry (alkis_date),
                   written by 02_extract_alkis.py / fetch_alkis_wfs.py.
  remote_date    : probed cheaply via scripts/alkis_sources.py (no full download).
  update_available: remote_date is newer than processed_date -> reprocess ALKIS.

Usage:
    python scripts/check_alkis_dates.py
    python scripts/check_alkis_dates.py --state rlp        # probe one state
    python scripts/check_alkis_dates.py --print            # just show
"""

import os
import sys
import json
import argparse
import datetime
import importlib.util

import requests

DATA_DIR = "data"
STATES_DIR = os.path.join("site", "public", "states")
OUTPUT_FILE = os.path.join("site", "public", "alkis_status.json")
STATE_META_KEY = "__state__"

_SRC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alkis_sources.py")
_spec = importlib.util.spec_from_file_location("alkis_sources", _SRC_PATH)
_sources = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sources)
SOURCES = _sources.SOURCES
STATE_NAMES = _sources.STATE_NAMES
probe_remote_date = _sources.probe_remote_date
probe_wfs_date = _sources.probe_wfs_date


def read_processed(state):
    """Return (processed_date, processed_at) from the state's alkis_meta sidecar."""
    meta_path = os.path.join(DATA_DIR, state, "alkis_meta.json")
    if not os.path.exists(meta_path):
        return None, None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return None, None
    entry = meta.get(STATE_META_KEY) or {}
    return entry.get("alkis_date"), entry.get("fetched_at")


def read_district_processed(state, district):
    """(alkis_date, fetched_at) for one district's alkis_meta entry (sub-sources)."""
    meta_path = os.path.join(DATA_DIR, state, "alkis_meta.json")
    if not os.path.exists(meta_path):
        return None, None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return None, None
    entry = meta.get(district) or {}
    return entry.get("alkis_date"), entry.get("fetched_at")


def probe_sub_sources(state, src, session):
    """Probe each WFS sub-source and pair it with its processed district date."""
    subs = []
    for sub in src.get("sub_sources", []):
        if sub.get("type") != "wfs":
            continue
        try:
            remote = probe_wfs_date(sub, session=session)
        except Exception as e:
            remote = None
            print(f"[{state}/{sub.get('key')}] WFS probe failed: {e}")
        processed, processed_at = read_district_processed(state, sub.get("district"))
        subs.append({
            "key": sub.get("key"),
            "label": sub.get("label") or sub.get("district"),
            "district": sub.get("district"),
            "cadence": sub.get("cadence"),
            "automated": True,
            "remote_date": remote,
            "processed_date": processed,
            "processed_at": processed_at,
            "update_available": is_newer(remote, processed),
        })
        print(f"  [{state}/{sub.get('key')}] processed={processed or '-'} "
              f"remote={remote or '-'} cadence={sub.get('cadence') or '-'}")
    return subs


def read_osm_and_comparison(state):
    """
    Return (osm_date, compared_at) from the published outputs of 04_compare:
      osm_date    = the OSM PBF snapshot the latest comparison reflects
                    (<st>_history.json global[-1].date)
      compared_at = when 04 last wrote the outputs (mtime of <st>_districts.json)
    """
    osm_date = None
    hist_path = os.path.join(STATES_DIR, state, f"{state}_history.json")
    if os.path.exists(hist_path):
        try:
            with open(hist_path, "r", encoding="utf-8") as f:
                g = (json.load(f) or {}).get("global", [])
            if g:
                osm_date = g[-1].get("date")
        except Exception:
            pass

    compared_at = None
    districts_path = os.path.join(STATES_DIR, state, f"{state}_districts.json")
    if os.path.exists(districts_path):
        try:
            compared_at = datetime.datetime.fromtimestamp(
                os.path.getmtime(districts_path)).isoformat(timespec="seconds")
        except Exception:
            pass

    return osm_date, compared_at


def is_newer(remote, processed):
    """
    Heuristic date compare tolerant of mixed precision ('2026-09' vs
    '2026-09-15'). Returns True only when we're confident remote is newer.
    """
    if not remote or not processed:
        return None
    r, p = remote[:10], processed[:10]
    n = min(len(r), len(p))          # compare only the overlapping precision
    return r[:n] > p[:n]


def build(states):
    session = requests.Session()
    out = {}
    for state in states:
        src = SOURCES[state]
        processed_date, processed_at = read_processed(state)
        remote_date, note = probe_remote_date(state, session=session)
        osm_date, compared_at = read_osm_and_comparison(state)
        update = is_newer(remote_date, processed_date)

        print(f"[{state}] processed={processed_date or '-'} "
              f"remote={remote_date or '-'} osm={osm_date or '-'} "
              f"compared={compared_at or '-'} "
              f"update={'yes' if update else ('no' if update is False else '?')}"
              f"{' (' + note + ')' if note else ''}")

        out[state] = {
            "name": STATE_NAMES.get(state, state.upper()),
            "source_type": src.get("source_type"),
            "automated": src.get("automated", False),
            "source_url": src.get("url"),
            "processed_date": processed_date,
            "processed_at": processed_at,
            "remote_date": remote_date,
            "osm_date": osm_date,
            "compared_at": compared_at,
            "update_available": update,
            "note": note,
        }
        subs = probe_sub_sources(state, src, session)
        if subs:
            out[state]["sub_sources"] = subs
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", help="Only probe this state key (default: all)")
    parser.add_argument("--print", dest="print_only", action="store_true",
                        help="Print the JSON to stdout instead of writing the file")
    args = parser.parse_args()

    states = list(SOURCES.keys())
    if args.state:
        if args.state not in SOURCES:
            print(f"Unknown state '{args.state}'. Known: {', '.join(SOURCES)}")
            sys.exit(1)
        states = [args.state]

    payload = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "states": build(states),
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.print_only:
        print(text)
        return

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    tmp = f"{OUTPUT_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, OUTPUT_FILE)
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
