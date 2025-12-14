
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
import os
import json
import datetime
import osmium

# Configuration
DATA_DIR = "data"
ALKIS_FILE = os.path.join(DATA_DIR, "alkis_addresses.parquet")
OSM_FILE = os.path.join(DATA_DIR, "osm_addresses.parquet")
PBF_FILE = os.path.join(DATA_DIR, "niedersachsen-latest.osm.pbf")
OUTPUT_DIR = "site/public"
STATS_DIR = os.path.join(OUTPUT_DIR, "districts")
DETAILED_HISTORY_FILE = os.path.join(OUTPUT_DIR, "detailed_history.json")


def main():
    if not os.path.exists(ALKIS_FILE) or not os.path.exists(OSM_FILE):
        print("Data files not found")
        return

    print("Loading datasets...")
    alkis = gpd.read_parquet(ALKIS_FILE)
    osm = gpd.read_parquet(OSM_FILE)
    
    print(f"ALKIS: {len(alkis)}, OSM: {len(osm)}")
    
    # Normalize
    # Normalize (Vectorized)
    print("Normalizing addresses (Vectorized)...")
    
    # Pre-cleaning to ensure string type
    alkis['street'] = alkis['street'].astype(str)
    alkis['housenumber'] = alkis['housenumber'].astype(str)
    osm['street'] = osm['street'].astype(str)
    osm['housenumber'] = osm['housenumber'].astype(str)

    # Define replacements
    replacements = {
        "straße": "str.",
        "str.": "str.", # normalize existing abbr
        "strasse": "str.",
        "platz": "pl.",
        # "weg": "weg" # 'weg' -> 'weg' is no-op
    }
    
    # ALKIS Street
    alkis['street_norm'] = alkis['street'].str.lower().str.strip()
    for k, v in replacements.items():
        alkis['street_norm'] = alkis['street_norm'].str.replace(k, v, regex=False)
        
    # ALKIS Hnr
    alkis['hnr_norm'] = alkis['housenumber'].str.lower().str.strip().str.replace(" ", "", regex=False)
    
    # OSM Street
    osm['street_norm'] = osm['street'].str.lower().str.strip()
    for k, v in replacements.items():
        osm['street_norm'] = osm['street_norm'].str.replace(k, v, regex=False)

    # OSM Hnr
    osm['hnr_norm'] = osm['housenumber'].str.lower().str.strip().str.replace(" ", "", regex=False)

    # Keys
    alkis['key'] = alkis['street_norm'] + " " + alkis['hnr_norm']
    osm['key'] = osm['street_norm'] + " " + osm['hnr_norm']
    

    alkis = alkis.to_crs(epsg=25832)
    osm = osm.to_crs(epsg=25832)
    
    # Prepare for merge
    # track ALKIS indices to mark them as found later
    alkis['alkis_idx'] = alkis.index
    
    # Comparing
    print("Comparing (Attribute + Spatial)...")
    
    # Reproject for distance calc
    print("  Reprojecting to EPSG:25832...")
    alkis = alkis.to_crs(epsg=25832)
    osm = osm.to_crs(epsg=25832)
    
    # Prepare for merge
    alkis['alkis_idx'] = alkis.index
    found_indices = set()
    
    # Chunked Matching to avoid OOM
    # Common names (Hauptstr 1) explode in merge
    CHUNK_SIZE = 50000
    total_chunks = (len(alkis) // CHUNK_SIZE) + 1
    
    print(f"  Matching in {total_chunks} chunks...")
    
    import numpy as np
    
    # Split ALKIS into chunks for processing
    # We cannot split OSM easily because we need random access by key
    # But we can filter OSM per chunk
    
    for i in range(0, len(alkis), CHUNK_SIZE):
        chunk = alkis.iloc[i : i + CHUNK_SIZE].copy()
        
        # Filter OSM to only relevant keys (Optimization)
        # This reduces the right-side table size significantly for each chunk
        relevant_keys = chunk['key'].unique()
        osm_subset = osm[osm['key'].isin(relevant_keys)]
        
        if osm_subset.empty:
            continue
            
        merged = pd.merge(
            chunk[['key', 'geometry', 'alkis_idx']],
            osm_subset[['key', 'geometry']],
            on='key',
            how='inner',
            suffixes=('_alkis', '_osm')
        )
        
        if merged.empty:
            continue
            
        # Distances
        # Use vectorized numpy distance if possible or geopandas
        # Geopandas is safer for consistency
        distances = merged['geometry_alkis'].distance(merged['geometry_osm'])
        
        valid = merged[distances < 50]
        found_indices.update(valid['alkis_idx'].unique())
        
        # Cleanup
        del chunk, osm_subset, merged, distances, valid
        
    print(f"  Valid Matches: {len(found_indices)} (out of {len(alkis)} ALKIS records)")
    
    # Mark in original DF
    alkis['found_in_osm'] = alkis['alkis_idx'].isin(found_indices)
    
    # Revert to 4326 for export
    print("  Reprojecting back to EPSG:4326...")
    alkis = alkis.to_crs(epsg=4326)
    
    missing = alkis[~alkis['found_in_osm']]
    print(f"Total Missing: {len(missing)} / {len(alkis)}")
    
    # History Tracking
    # Load existing history
    history_store = {"global": [], "districts": {}}
    if os.path.exists(DETAILED_HISTORY_FILE):
        try:
            with open(DETAILED_HISTORY_FILE, 'r') as f:
                history_store = json.load(f)
                if "districts" not in history_store: history_store["districts"] = {}
        except:
            pass # corrupted or old format

    # get the snaphot date
    reader = osmium.io.Reader(PBF_FILE)
    export_date = reader.header().get("osmosis_replication_timestamp")
    print(f"OSM Snapshot Timestamp: {export_date}")
    
    # Global Stat
    global_stat = {
        "date": export_date,
        "alkis": len(alkis),
        "osm": len(osm),
        "missing": len(missing),
        "coverage": round((len(alkis) - len(missing)) / len(alkis) * 100, 2)
    }
    
    # Update global (avoid dupes for today)
    # Check last entry
    if not history_store["global"] or history_store["global"][-1]["date"] != export_date:
        history_store["global"].append(global_stat)
    else:
        history_store["global"][-1] = global_stat

    # Group by District
    os.makedirs(STATS_DIR, exist_ok=True)
    
    # Make sure 'district' column exists (it should after updated extraction)
    if 'district' not in alkis.columns:
        print("Warning: No 'district' column in ALKIS data. Saving global diff only.")
        alkis['district'] = 'Global'
        
    districts = alkis['district'].unique()
    district_list = []
    
    for district in districts:
        print(f"Processing {district}...")
        district_alkis = alkis[alkis['district'] == district]
        district_missing = district_alkis[~district_alkis['found_in_osm']]
        
        # Stats
        d_stats = {
            "name": district,
            "total": len(district_alkis),
            "missing": len(district_missing),
            "coverage": round((len(district_alkis) - len(district_missing)) / len(district_alkis) * 100, 1)
        }
        district_list.append(d_stats)
        
        # Update District History
        d_hist_entry = {
            "date": export_date,
            "total": d_stats["total"],
            "missing": d_stats["missing"],
            "coverage": d_stats["coverage"]
        }
        
        if district not in history_store["districts"]:
            history_store["districts"][district] = []
            
        d_hist = history_store["districts"][district]
        if not d_hist or d_hist[-1]["date"] != export_date:
            d_hist.append(d_hist_entry)
        else:
            d_hist[-1] = d_hist_entry
        
        # Export GeoJSON
        export_cols = ['street', 'housenumber', 'geometry']
        missing_export = district_missing[export_cols]
        
        if missing_export.crs != "EPSG:4326":
            missing_export = missing_export.to_crs("EPSG:4326")
            
        out_path = os.path.join(STATS_DIR, f"{district}.geojson")
        if len(missing_export) > 0:
            try:
                missing_export.to_file(out_path, driver="GeoJSON")
            except Exception as e:
                print(f"Error saving {district}: {e}")
        else:
            # Create empty feature collection
            with open(out_path, 'w') as f:
                json.dump({"type": "FeatureCollection", "features": []}, f)
                
    # Save Detailed History
    with open(DETAILED_HISTORY_FILE, 'w') as f:
        json.dump(history_store, f, indent=2)
        
    # Save list of districts for frontend selector
    district_list.sort(key=lambda x: x['name'])
    with open(os.path.join(OUTPUT_DIR, "districts.json"), 'w') as f:
        json.dump(district_list, f, indent=2)
        
    print("Comparison complete.")

if __name__ == "__main__":
    main()
