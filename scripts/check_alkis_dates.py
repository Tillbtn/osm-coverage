"""
Build the ALKIS freshness dashboard data: for every registered state, compare
the export date the published comparison reflects against the latest date
available at the source, and write site/public/alkis_status.json for the status
page to render.

  processed_date : the ALKIS stand 04_compare.py last compared against OSM, read
                   back from its own outputs in site/public/states/<st>/. A new
                   extract only shows up here once a comparison has used it.
  extracted_date : the stand staged in data/<st>/ (alkis_meta.json, written by
                   02_extract_alkis.py / fetch_alkis_wfs.py). Ahead of
                   processed_date between an extraction and the next comparison.
  remote_date    : probed cheaply via scripts/alkis_sources.py (no full download).
  update_available: remote_date is newer than processed_date -> reprocess ALKIS.

Prints one summary line; pass --verbose for the per-state values (the default
when run interactively) - the hourly cron run keeps the log short because the
numbers are on the status page anyway.

Usage:
    python scripts/check_alkis_dates.py
    python scripts/check_alkis_dates.py --state rlp        # probe one state
    python scripts/check_alkis_dates.py --print            # just show
"""

import os
import sys
import json
import argparse
import collections
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
probe_label = _sources.probe_label
describe_meta_source = _sources.describe_meta_source


def _read_json(path):
    """Parsed JSON, or None when the file is missing or unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_extracted(state, district=None):
    """(alkis_date, fetched_at, source) of the ALKIS extract staged in data/<state>/.

    From the alkis_meta.json sidecar that 02_extract_alkis.py /
    fetch_alkis_wfs.py write, so it describes what alkis.parquet holds - which
    04_compare.py has not necessarily compared yet. district=None reads the
    state-wide entry.
    """
    meta = _read_json(os.path.join(DATA_DIR, state, "alkis_meta.json")) or {}
    entry = meta.get(STATE_META_KEY if district is None else district) or {}
    return entry.get("alkis_date"), entry.get("fetched_at"), entry.get("source")


def read_compared_districts(state):
    """The district entries 04_compare.py published for this state."""
    districts = _read_json(os.path.join(STATES_DIR, state, f"{state}_districts.json"))
    return districts if isinstance(districts, list) else []


def read_compared_alkis(state, district=None):
    """The ALKIS stand the published comparison actually used.

    04_compare.py records it in <st>_history.json ('alkis_date', state-wide) and
    per district in <st>_districts.json every time it writes a state, so it only
    advances once a comparison has run with a new extract.

    State-wide outputs written before that key existed fall back to the district
    dates, where the state's stand is the one most districts share (a single
    district can be newer, e.g. Aachen's daily WFS).
    """
    if district is not None:
        for entry in read_compared_districts(state):
            if district in (entry.get("district"), entry.get("name")):
                return entry.get("alkis_date")
        return None

    history = _read_json(os.path.join(STATES_DIR, state, f"{state}_history.json")) or {}
    if history.get("alkis_date"):
        return history["alkis_date"]
    dates = [e.get("alkis_date") for e in read_compared_districts(state) if e.get("alkis_date")]
    return collections.Counter(dates).most_common(1)[0][0] if dates else None


def processed_fields(compared, extracted, extracted_at, extracted_source):
    """The dashboard's freshness block for one state or sub-source.

    processed_* is what the live comparison reflects; extracted_* is what is
    staged for the next one. fetched_at/source come from the sidecar in data/ and
    only describe the compared stand while the staged extract is still the same.
    """
    same = compared is not None and extracted == compared
    return {
        "processed_date": compared,
        "processed_at": extracted_at if same else None,
        "processed_source": describe_meta_source(extracted_source) if same else None,
        "extracted_date": extracted,
        "extracted_at": extracted_at,
        "extracted_source": describe_meta_source(extracted_source),
    }


def probe_sub_sources(state, src, session, verbose=False):
    """Probe each WFS sub-source and pair it with the date its comparison used."""
    subs = []
    for sub in src.get("sub_sources", []):
        if sub.get("type") != "wfs":
            continue
        try:
            remote = probe_wfs_date(sub, session=session)
        except Exception as e:
            remote = None
            print(f"[{state}/{sub.get('key')}] WFS probe failed: {e}")
        district = sub.get("district")
        compared = read_compared_alkis(state, district)
        extracted, extracted_at, extracted_src = read_extracted(state, district)
        subs.append({
            "key": sub.get("key"),
            "label": sub.get("label") or district,
            "district": district,
            "cadence": sub.get("cadence"),
            "automated": True,
            "remote_date": remote,
            "remote_source": probe_label(sub.get("probe")),
            **processed_fields(compared, extracted, extracted_at, extracted_src),
            "update_available": is_newer(remote, compared),
        })
        if verbose:
            print(f"  [{state}/{sub.get('key')}] compared={compared or '-'} "
                  f"extracted={extracted or '-'} remote={remote or '-'} "
                  f"cadence={sub.get('cadence') or '-'}")
    return subs


def read_osm_and_comparison(state):
    """
    Return (osm_date, compared_at) from the published outputs of 04_compare:
      osm_date    = the OSM PBF snapshot the latest comparison reflects
                    (<st>_history.json global[-1].date)
      compared_at = when 04 last wrote the outputs (mtime of <st>_districts.json)
    """
    osm_date = None
    g = (_read_json(os.path.join(STATES_DIR, state, f"{state}_history.json")) or {}).get("global")
    if g:
        osm_date = g[-1].get("date")

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


def build(states, verbose=False):
    session = requests.Session()
    out = {}
    for state in states:
        src = SOURCES[state]
        compared = read_compared_alkis(state)
        extracted, extracted_at, extracted_src = read_extracted(state)
        remote_date, note = probe_remote_date(state, session=session)
        osm_date, compared_at = read_osm_and_comparison(state)
        update = is_newer(remote_date, compared)

        if verbose:
            print(f"[{state}] compared={compared or '-'} extracted={extracted or '-'} "
                  f"remote={remote_date or '-'} osm={osm_date or '-'} "
                  f"at={compared_at or '-'} "
                  f"update={'yes' if update else ('no' if update is False else '?')}"
                  f"{' (' + note + ')' if note else ''}")

        out[state] = {
            "name": STATE_NAMES.get(state, state.upper()),
            "source_type": src.get("source_type"),
            "automated": src.get("automated", False),
            "source_url": src.get("url"),
            **processed_fields(compared, extracted, extracted_at, extracted_src),
            "remote_date": remote_date,
            "remote_source": probe_label(src.get("probe")),
            "osm_date": osm_date,
            "compared_at": compared_at,
            "update_available": update,
            "note": note,
        }
        subs = probe_sub_sources(state, src, session, verbose=verbose)
        if subs:
            out[state]["sub_sources"] = subs
    return out


def summarize(states):
    """'10 states; newer source data: nds, nrw/aachen' for the cron log."""
    pending = []
    for state, entry in states.items():
        if entry.get("update_available"):
            pending.append(state)
        pending += [f"{state}/{sub['key']}" for sub in entry.get("sub_sources", [])
                    if sub.get("update_available")]
    summary = f"{len(states)} state{'' if len(states) == 1 else 's'}"
    if pending:
        summary += f"; newer source data: {', '.join(sorted(pending))}"
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", help="Only probe this state key (default: all)")
    parser.add_argument("--print", dest="print_only", action="store_true",
                        help="Print the JSON to stdout instead of writing the file")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print the per-state values (default when on a terminal)")
    args = parser.parse_args()
    verbose = args.verbose or (sys.stdout.isatty() and not args.print_only)

    states = list(SOURCES.keys())
    if args.state:
        if args.state not in SOURCES:
            print(f"Unknown state '{args.state}'. Known: {', '.join(SOURCES)}")
            sys.exit(1)
        states = [args.state]

    payload = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "states": build(states, verbose=verbose),
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
    print(f"Wrote {OUTPUT_FILE} ({summarize(payload['states'])})")


if __name__ == "__main__":
    main()
