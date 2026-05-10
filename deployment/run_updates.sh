#!/bin/bash

# Ensure output directories exist
mkdir -p data
# site/public structure
mkdir -p site/public/districts
mkdir -p site/public/states
mkdir -p site/public/tiles

echo "Starting Update Log..." > site/public/update.log
exec > >(awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush() }' | tee -a site/public/update.log) 2>&1

echo "Starting Update Check..."

echo "Checking for new data..."

# Check if update is needed
python scripts/check_geofabrik_export_date.py
CHECK_STATUS=$?

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
         cp "$f" "backups/${state_name}_history_$(date +%F).json"
    done

    echo "Update complete. Exiting successfully."
    exit 0
else
    echo "No new data available. Exiting until next cron run."
    exit 0
fi
