#!/bin/bash

# Ensure output directories exist
mkdir -p data
mkdir -p site/public/districts
mkdir -p site/public/tiles

echo "Starting Update Loop..."

while true; do
    echo "[$(date)] Checking for new data..."
    
    # Check if update is needed
    python scripts/check_geofabrik_export_date.py
    CHECK_STATUS=$?

    if [ $CHECK_STATUS -eq 0 ]; then
        echo "[$(date)] New data found/Update required. Starting update process..."

        # 1. Download ALKIS (Optional - might fail if endpoint changes/unavailable)
        echo "Running 01_download_alkis.py..."
        python scripts/01_download_alkis.py || echo "Warning: Download failed, continuing with existing data..."

        # 2. Extract
        echo "Running 02_extract_alkis.py..."
        python scripts/02_extract_alkis.py

        # 3. Fetch OSM
        # Using 03_import_pbf.py (Addresses)
        echo "Running 03_import_pbf_optimized.py..."
        #python scripts/03_import_pbf.py
        python scripts/03_import_pbf_optimized.py

        # 4. Compare
        echo "Running 04_compare_optimized.py..."
        # python scripts/04_compare.py
        python scripts/04_compare_optimized.py

        # 5. Generate Tiles
        # echo "Running 05_generate_mvt.py..."
        # python scripts/05_generate_mvt.py

        echo "[$(date)] Update complete. Exiting successfully."
        exit 0
    else
        echo "[$(date)] No new data available. Retrying in 1 hour..."
        sleep 3600
    fi
done
