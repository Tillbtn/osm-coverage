"""Update gate for run_updates.sh.

Exit 0 if Geofabrik has a newer export than the last processed one for at least
one state, else 1. Reads the internal server's pages first when a login cookie
is available (published earlier), otherwise the public ones.
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

# Configuration matches 03_import_osm.py
STATES = {
    "nds": {
        "url": "https://download.geofabrik.de/europe/germany/niedersachsen.html",
        "history_file": os.path.join("site", "public", "states", "nds", "nds_history.json")
    },
    "nrw": {
        "url": "https://download.geofabrik.de/europe/germany/nordrhein-westfalen.html",
        "history_file": os.path.join("site", "public", "states", "nrw", "nrw_history.json")
    },
    "rlp": {
        "url": "https://download.geofabrik.de/europe/germany/rheinland-pfalz.html",
        "history_file": os.path.join("site", "public", "states", "rlp", "rlp_history.json")
    },
    "bb": {
        "url": "https://download.geofabrik.de/europe/germany/brandenburg.html",
        "history_file": os.path.join("site", "public", "states", "bb", "bb_history.json")
    },
    "hh": {
        "url": "https://download.geofabrik.de/europe/germany/hamburg.html",
        "history_file": os.path.join("site", "public", "states", "hh", "hh_history.json")
    },
    "he": {
        "url": "https://download.geofabrik.de/europe/germany/hessen.html",
        "history_file": os.path.join("site", "public", "states", "he", "he_history.json")
    },
    "st": {
        "url": "https://download.geofabrik.de/europe/germany/sachsen-anhalt.html",
        "history_file": os.path.join("site", "public", "states", "st", "st_history.json")
    },
    "sn": {
        "url": "https://download.geofabrik.de/europe/germany/sachsen.html",
        "history_file": os.path.join("site", "public", "states", "sn", "sn_history.json")
    },
    "be": {
        "url": "https://download.geofabrik.de/europe/germany/berlin.html",
        "history_file": os.path.join("site", "public", "states", "be", "be_history.json")
    },
    "mv": {
        "url": "https://download.geofabrik.de/europe/germany/mecklenburg-vorpommern.html",
        "history_file": os.path.join("site", "public", "states", "mv", "mv_history.json")
    }
}

def scrape_date(session, url):
    """Fetches the Geofabrik page and extracts the timestamp.

    Returns None if the page carries no timestamp.
    """
    response = session.get(url, timeout=10)
    response.raise_for_status()

    # Regex to find: "contains all OSM data up to 2025-12-14T21:21:45Z"
    match = re.search(r"contains all OSM data up to ([\d-]{10}T[\d:]{8}Z)", response.text)
    if not match:
        return None

    dt = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
    return dt.astimezone(zoneinfo.ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%dT%H:%M:%S")


def open_internal_session(force_refresh=False):
    """A session for the internal server, or None without a usable cookie."""
    cookie = (geofabrik_auth.refresh_download_cookie() if force_refresh
              else geofabrik_auth.get_download_cookie())
    return geofabrik_auth.internal_session(cookie) if cookie else None


def read_internal_page(session, url):
    """(date, problem, cookie_rejected) for one page on the internal server."""
    try:
        date = scrape_date(session, url)
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else None
        # 401/403 points at the cookie. A 5xx says nothing about the login and
        # must not trigger one.
        return None, f"internal page answered HTTP {code}", code in (401, 403)
    except Exception as e:
        return None, f"error fetching the internal page: {e}", False
    if date:
        return date, None, False
    # An expired cookie is answered with the OSM login page: HTTP 200, no date.
    return None, "no timestamp on the internal page (login not accepted?)", True


def get_remote_date(public_url, public_session, internal):
    """Export date for one state, preferring the internal server.

    'internal' holds the shared internal session ({"session": ...}). A rejected
    cookie triggers one fresh login, which the remaining states reuse; if the
    renewed cookie is rejected too, the run gives up on the internal server. A
    server error sends only this state to the public pages, is logged once per
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
        date = scrape_date(public_session, public_url)
        if date is None:
            print(f"[{public_url}] Error: Could not find timestamp pattern.")
        return date, "public"
    except Exception as e:
        print(f"[{public_url}] Error fetching Geofabrik page: {e}")
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

    for state_key, config in STATES.items():
        remote_date, source = get_remote_date(config["url"], public_session, internal)
        local_date = get_local_date(config["history_file"])

        print(f"[{state_key}] Remote ({source}): {remote_date} | Local: {local_date}")
        
        if not remote_date:
            print(f"[{state_key}] Warning: Could not fetch remote date. Skipping check.")
            continue
            
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
