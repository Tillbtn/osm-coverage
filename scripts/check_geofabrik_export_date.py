
import requests
import re
import json
import os
import sys

# Configuration matches 03_import_pbf_optimized.py
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
    }
}

def get_remote_date(url):
    """Fetches the Geofabrik page and extracts the timestamp."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Regex to find: "contains all OSM data up to 2025-12-14T21:21:45Z"
        match = re.search(r"contains all OSM data up to ([\d-]{10}T[\d:]{8}Z)", response.text)
        if match:
            return match.group(1)
        else:
            print(f"[{url}] Error: Could not find timestamp pattern.")
            return None
    except Exception as e:
        print(f"[{url}] Error fetching Geofabrik page: {e}")
        return None

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
    
    for state_key, config in STATES.items():
        remote_date = get_remote_date(config["url"])
        local_date = get_local_date(config["history_file"])
        
        print(f"[{state_key}] Remote: {remote_date} | Local: {local_date}")
        
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
