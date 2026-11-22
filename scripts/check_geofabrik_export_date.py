"""Update gate for run_updates.sh.

Exit 0 if Geofabrik has a newer export than the last processed one for at least
one state, else 1. The export date is the timestamp in the extract's replication
state file (updates/state.txt), the same value 04 reads from the PBF header
(osmosis_replication_timestamp). The internal server is asked first when a login
cookie is available (it publishes earlier), otherwise the public one.
"""

import requests
import re
import json
import os
import sys
import zoneinfo
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geofabrik_auth
import notify

# Configuration matches 03_import_osm.py
STATES = {
    "nds": {
        "url": "https://download.geofabrik.de/europe/germany/niedersachsen/updates/state.txt",
        "history_file": os.path.join("site", "public", "states", "nds", "nds_history.json")
    },
    "nrw": {
        "url": "https://download.geofabrik.de/europe/germany/nordrhein-westfalen/updates/state.txt",
        "history_file": os.path.join("site", "public", "states", "nrw", "nrw_history.json")
    },
    "rlp": {
        "url": "https://download.geofabrik.de/europe/germany/rheinland-pfalz/updates/state.txt",
        "history_file": os.path.join("site", "public", "states", "rlp", "rlp_history.json")
    },
    "bb": {
        "url": "https://download.geofabrik.de/europe/germany/brandenburg/updates/state.txt",
        "history_file": os.path.join("site", "public", "states", "bb", "bb_history.json")
    },
    "hh": {
        "url": "https://download.geofabrik.de/europe/germany/hamburg/updates/state.txt",
        "history_file": os.path.join("site", "public", "states", "hh", "hh_history.json")
    },
    "he": {
        "url": "https://download.geofabrik.de/europe/germany/hessen/updates/state.txt",
        "history_file": os.path.join("site", "public", "states", "he", "he_history.json")
    },
    "st": {
        "url": "https://download.geofabrik.de/europe/germany/sachsen-anhalt/updates/state.txt",
        "history_file": os.path.join("site", "public", "states", "st", "st_history.json")
    },
    "sn": {
        "url": "https://download.geofabrik.de/europe/germany/sachsen/updates/state.txt",
        "history_file": os.path.join("site", "public", "states", "sn", "sn_history.json")
    },
    "be": {
        "url": "https://download.geofabrik.de/europe/germany/berlin/updates/state.txt",
        "history_file": os.path.join("site", "public", "states", "be", "be_history.json")
    },
    "mv": {
        "url": "https://download.geofabrik.de/europe/germany/mecklenburg-vorpommern/updates/state.txt",
        "history_file": os.path.join("site", "public", "states", "mv", "mv_history.json")
    }
}

# Replication state files escape the colons: "timestamp=2026-11-21T21\:20\:51Z"
STATE_TIMESTAMP = re.compile(r"^timestamp=(\d{4}-\d{2}-\d{2}T[\d:\\]+Z)\s*$", re.MULTILINE)


def read_state_date(session, url):
    """Fetches a replication state.txt and returns its timestamp in local time.

    Returns None if the response carries no timestamp (e.g. an HTML login page).
    """
    response = session.get(url, timeout=10)
    response.raise_for_status()

    match = STATE_TIMESTAMP.search(response.text)
    if not match:
        return None

    stamp = match.group(1).replace("\\", "")
    dt = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
    return dt.astimezone(zoneinfo.ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%dT%H:%M:%S")


def open_internal_session(force_refresh=False):
    """A session for the internal server, or None without a usable cookie."""
    cookie = (geofabrik_auth.refresh_download_cookie() if force_refresh
              else geofabrik_auth.get_download_cookie())
    return geofabrik_auth.internal_session(cookie) if cookie else None


def read_internal_page(session, url):
    """(date, problem, cookie_rejected) for one state file on the internal server."""
    try:
        date = read_state_date(session, url)
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else None
        # 401/403 points at the cookie. A 5xx says nothing about the login and
        # must not trigger one.
        return None, f"internal state file answered HTTP {code}", code in (401, 403)
    except Exception as e:
        return None, f"error fetching the internal state file: {e}", False
    if date:
        return date, None, False
    # An expired cookie is answered with the OSM login page: HTTP 200, no date.
    return None, "no timestamp in the internal state file (login not accepted?)", True


def get_remote_date(public_url, public_session, internal):
    """Export date for one state, preferring the internal server.

    'internal' holds the shared internal session ({"session": ...}). A rejected
    cookie triggers one fresh login, which the remaining states reuse; if the
    renewed cookie is rejected too, the run gives up on the internal server. A
    server error sends only this state to the public server, is logged once per
    run, and the next state tries the internal server again.
    """
    for attempt in (1, 2):  # the second attempt runs with a renewed cookie
        if internal["session"] is None:
            break
        url = geofabrik_auth.internal_url(public_url)
        date, problem, rejected = read_internal_page(internal["session"], url)
        if date:
            return date, "internal"
        if rejected and attempt == 1:
            internal["session"] = open_internal_session(force_refresh=True)
            if internal["session"] is not None:
                continue
        elif rejected:
            internal["session"] = None  # the renewed cookie is rejected too
        gave_up = internal["session"] is None
        if gave_up or not internal.get("warned"):
            internal["warned"] = True
            print(f"[{url}] {problem}; using the public server"
                  f"{' for the rest of this run' if gave_up else ''}.")
        break

    try:
        date = read_state_date(public_session, public_url)
        if date is None:
            print(f"[{public_url}] Error: no timestamp in the state file.")
        return date, "public"
    except Exception as e:
        print(f"[{public_url}] Error fetching the Geofabrik state file: {e}")
        return None, "public"

def get_local_date(history_path):
    """Reads the last processed date from the state history file."""
    if not os.path.exists(history_path):
        return None

    try:
        with open(history_path, "r") as f:
            data = json.load(f)
            global_hist = data.get("global", [])
            if global_hist:
                return global_hist[-1].get("date")
    except Exception as e:
        print(f"Error reading local history {history_path}: {e}")
        
    return None

def main():
    update_needed = False
    
    print("Checking for updates...")

    internal = {"session": open_internal_session()}
    public_session = requests.Session()
    public_session.headers.update(geofabrik_auth.HEADERS)

    with notify.batch():
        for state_key, config in STATES.items():
            remote_date, source = get_remote_date(config["url"], public_session, internal)
            local_date = get_local_date(config["history_file"])

            print(f"[{state_key}] Remote ({source}): {remote_date} | Local: {local_date}")
        
            if not remote_date:
                print(f"[{state_key}] Warning: Could not fetch remote date. Skipping check.")
                notify.track_failure(f"gate:{state_key}",
                                     "No export date in the internal or the public Geofabrik state file.",
                                     threshold=3, priority="default",
                                     title=f"Geofabrik-Exportdatum {state_key.upper()} nicht lesbar")
                continue
            notify.track_success(f"gate:{state_key}")

            if local_date is None:
                print(f"[{state_key}] No local history. Update needed.")
                update_needed = True
            elif remote_date > local_date:
                print(f"[{state_key}] New data available.")
                update_needed = True
            else:
                print(f"[{state_key}] Up to date.")

    if update_needed:
        print("Update required for at least one state.")
        sys.exit(0) # 0 means "Success, proceed" in run_updates.sh logic
    else:
        print("All states up to date.")
        sys.exit(1) # 1 means "Failure/No Update"

if __name__ == "__main__":
    main()
