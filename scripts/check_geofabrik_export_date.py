
import requests
import re
import json
import os
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime

# Constants
GEOFABRIK_URL = "https://download.geofabrik.de/europe/germany/niedersachsen.html"
DETAILED_HISTORY_PATH = os.path.join("site", "public", "detailed_history.json")

def get_remote_date():
    """Fetches the Geofabrik page and extracts the timestamp."""
    try:
        response = requests.get(GEOFABRIK_URL, timeout=10)
        response.raise_for_status()
        
        # Regex to find: "contains all OSM data up to 2025-12-14T21:21:45Z"
        match = re.search(r"contains all OSM data up to ([\d-]{10}T[\d:]{8}Z)", response.text)
        if match:
            return match.group(1)
        else:
            print("Error: Could not find timestamp pattern on Geofabrik page.")
            return None
    except Exception as e:
        print(f"Error fetching Geofabrik page: {e}")
        return None

def get_local_date():
    """Reads the last processed date from detailed_history.json."""
    if not os.path.exists(DETAILED_HISTORY_PATH):
        print(f"Local history not found at {DETAILED_HISTORY_PATH}. Assuming clean slate.")
        return None

    try:
        with open(DETAILED_HISTORY_PATH, "r") as f:
            data = json.load(f)
            global_hist = data.get("global", [])
            if global_hist:
                return global_hist[-1].get("date")
    except Exception as e:
        print(f"Error reading local history: {e}")
        
    return None

def main():
    remote_date_str = get_remote_date()
    if not remote_date_str:
        # If we can't get remote date, be safe and assume no update (or should we fail open?)
        # User goal: avoid unnecessary work. If we fail to check, maybe don't update?
        # But failing effectively requires manual intervention.
        # Let's say: Error -> exit 1 (No update/Error)
        sys.exit(1)

    local_date_str = get_local_date()
    
    print(f"Remote Date: {remote_date_str}")
    print(f"Local Date:  {local_date_str}")

    if local_date_str is None:
        print("No local history found. Update required.")
        sys.exit(0)

    # String comparison for ISO 8601 is valid and sufficient
    if remote_date_str > local_date_str:
        print("Remote is newer. Update required.")
        sys.exit(0)
    else:
        print("Remote is older or same. No update needed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
