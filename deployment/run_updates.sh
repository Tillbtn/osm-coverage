#!/bin/bash

# Ensure output directories exist
mkdir -p data
# site/public structure
mkdir -p site/public/states
# mkdir -p site/public/tiles

LOG_FILE="site/public/update.log"
if [ -f "$LOG_FILE" ]; then
    THRESHOLD=$(date -d "48 hours ago" '+[%Y-%m-%d %H:%M:%S]')
    awk -v thresh="$THRESHOLD" '
        /^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\]/ {
            timestamp = $1 " " $2
            if (timestamp >= thresh) print $0
        }
        !/^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\]/ {
            if (timestamp >= thresh || timestamp == "") print $0
        }
    ' "$LOG_FILE" > "${LOG_FILE}.tmp"
    mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

exec > >(while IFS= read -r line || [ -n "$line" ]; do echo "[$(date '+%Y-%m-%d %H:%M:%S')] $line"; done | tee -a site/public/update.log) 2>&1

echo "----------------------------------------"

# Exit 2 = a filesystem is critically full: skip the update so 04 cannot run
# out of space halfway through writing its outputs.
python scripts/check_disk.py --preflight
DISK_STATUS=$?

if [ $DISK_STATUS -eq 2 ]; then
    echo "Disk space critical - skipping the update."
    CHECK_STATUS=2
else
    echo "Checking for new data..."

    # Check if update is needed
    python scripts/check_geofabrik_export_date.py
    CHECK_STATUS=$?
fi

if [ $CHECK_STATUS -eq 0 ]; then
    echo "New data found/Update required. Starting update process..."

    # # 1. Download ALKIS (Optional - might fail if endpoint changes/unavailable)
    # echo "Running 01_download_alkis_nds.py..."
    # python scripts/01_download_alkis_nds.py || echo "Warning: Download failed, continuing with existing data..."
    # echo "Running 01_download_alkis_nrw.py..."
    # python scripts/01_download_alkis_nrw.py || echo "Warning: Download failed, continuing with existing data..."
    # echo "Running 01_download_alkis_rlp.py..."
    # python scripts/01_download_alkis_rlp.py || echo "Warning: Download failed, continuing with existing data..."

    # # 2. Extract
    # echo "Running 02_extract_alkis.py..."
    # python scripts/02_extract_alkis.py
    echo "Fetching WFS data..."
    python scripts/fetch_alkis_wfs.py --source aachen

    # 3. Fetch OSM
    # Using 03_import_osm.py (Addresses)
    echo "Running 03_import_osm.py..."
    python scripts/03_import_osm.py

    # 4. Compare
    echo "Running 04_compare.py..."
    python scripts/04_compare.py

    # Backup History logic (persisted in data/backups)
    echo "Backing up history..."
    mkdir -p backups
    
    # Backup state history files
    find site/public/states -name "*_history.json" | while read f; do
         state_name=$(basename "$f" _history.json)
         dest="backups/${state_name}_history_$(date +%F).json.gz"
         if gzip -c "$f" > "${dest}.tmp" && mv "${dest}.tmp" "$dest"; then
             rm -f "${dest%.gz}"
         else
             rm -f "${dest}.tmp"
             echo "Warning: could not back up $f"
         fi
    done

    echo "Update complete."
elif [ $CHECK_STATUS -ne 2 ]; then
    echo "No new data available until next cron run."
fi

# Refresh the ALKIS freshness dashboard
python scripts/check_alkis_dates.py || echo "Warning: ALKIS status check failed."

exit 0
