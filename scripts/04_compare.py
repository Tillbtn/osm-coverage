
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
import os
import json
import datetime

# Configuration
DATA_DIR = "data"
ALKIS_FILE = os.path.join(DATA_DIR, "alkis_addresses.parquet")
OSM_FILE = os.path.join(DATA_DIR, "osm_addresses.parquet")
OUTPUT_DIR = "site"
STATS_DIR = os.path.join(OUTPUT_DIR, "districts") # New structure
HISTORY_FILE = os.path.join(OUTPUT_DIR, "history.json")

def normalize_street(name):
    if not isinstance(name, str):
        return ""
    name = name.lower()
    name = name.replace("straße", "str.")
    name = name.replace("str.", "str.") 
    name = name.replace("strasse", "str.")
    name = name.replace("platz", "pl.")
    name = name.replace("weg", "weg")
    return name.strip()

def normalize_hnr(hnr):
    if not isinstance(hnr, str):
        return str(hnr).lower()
    return hnr.lower().strip()

def main():
    if not os.path.exists(ALKIS_FILE) or not os.path.exists(OSM_FILE):
        print("Data files not found. Run extract steps first.")
        return

    print("Loading datasets...")
    alkis = gpd.read_parquet(ALKIS_FILE)
    osm = gpd.read_parquet(OSM_FILE)
    
    print(f"ALKIS: {len(alkis)}, OSM: {len(osm)}")
    
    # Normalize
    print("Normalizing addresses...")
    alkis['street_norm'] = alkis['street'].apply(normalize_street)
    alkis['hnr_norm'] = alkis['housenumber'].apply(normalize_hnr)
    alkis['key'] = alkis['street_norm'] + " " + alkis['hnr_norm']
    
    osm['street_norm'] = osm['street'].apply(normalize_street)
    osm['hnr_norm'] = osm['housenumber'].apply(normalize_hnr)
    osm['key'] = osm['street_norm'] + " " + osm['hnr_norm']
    
    print("Comparing (Attribute + Spatial)...")
    
    # Reproject to metric CRS (ETRS89 / UTM 32N) for accurate distance
    print("  Reprojecting to EPSG:25832...")
    alkis = alkis.to_crs(epsg=25832)
    osm = osm.to_crs(epsg=25832)
    
    # Prepare for merge
    # We need to track ALKIS indices to mark them as found later
    alkis['alkis_idx'] = alkis.index
    
    # Merge on Address Key
    # This creates a potential many-to-many relationship (wrongly matched villages)
    print("  Merging datasets...")
    merged = pd.merge(
        alkis[['key', 'geometry', 'alkis_idx']],
        osm[['key', 'geometry']],
        on='key',
        how='inner',
        suffixes=('_alkis', '_osm')
    )
    
    # Calculate distance
    print("  Calculating distances...")
    # Vectorized distance calculation
    # merged['geometry_alkis'] and merged['geometry_osm'] are GeoSeries
    # We can use geopandas distance
    # Converting back to GeoSeries to be sure, although merge output usually has objects
    distances =  gpd.GeoSeries(merged['geometry_alkis']).distance(gpd.GeoSeries(merged['geometry_osm']))
    
    # Filter spatial validity (1000m threshold)
    # 2km is very safe for different villages, usually <500m is enough for "same town error"
    # But let's stick to 1000m (1km) as a robust middle ground.
    valid_matches = merged[distances < 1000]
    
    # Identify found ALKIS IDs
    found_indices = set(valid_matches['alkis_idx'].unique())
    
    print(f"  Valid Matches: {len(found_indices)} (out of {len(alkis)} ALKIS records)")
    
    # Mark in original DF
    alkis['found_in_osm'] = alkis['alkis_idx'].isin(found_indices)
    
    # Revert to 4326 for export
    alkis = alkis.to_crs(epsg=4326)
    
    missing = alkis[~alkis['found_in_osm']]
    print(f"Total Missing: {len(missing)} / {len(alkis)}")
    
    # History Tracking Structure
    DETAILED_HISTORY_FILE = os.path.join(OUTPUT_DIR, "detailed_history.json")
    
    # Load existing history
    history_store = {"global": [], "districts": {}}
    if os.path.exists(DETAILED_HISTORY_FILE):
        try:
            with open(DETAILED_HISTORY_FILE, 'r') as f:
                history_store = json.load(f)
                if "districts" not in history_store: history_store["districts"] = {}
        except:
            pass # corrupted or old format
            
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # Global Stat
    global_stat = {
        "date": today,
        "alkis": len(alkis),
        "osm": len(osm),
        "missing": len(missing),
        "coverage": round((len(alkis) - len(missing)) / len(alkis) * 100, 2)
    }
    
    # Update global (avoid dupes for today)
    # Check last entry
    if not history_store["global"] or history_store["global"][-1]["date"] != today:
        history_store["global"].append(global_stat)
    else:
        history_store["global"][-1] = global_stat

    # Keep legacy history.json for compatibility for now (optional)
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history_store["global"], f, indent=2)

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
            "date": today,
            "total": d_stats["total"],
            "missing": d_stats["missing"],
            "coverage": d_stats["coverage"]
        }
        
        if district not in history_store["districts"]:
            history_store["districts"][district] = []
            
        d_hist = history_store["districts"][district]
        if not d_hist or d_hist[-1]["date"] != today:
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

    # Save list of districts for frontend selector
    district_list.sort(key=lambda x: x['name'])
    with open(os.path.join(OUTPUT_DIR, "districts.json"), 'w') as f:
        json.dump(district_list, f, indent=2)
        
    print("Comparison complete.")

if __name__ == "__main__":
    main()
