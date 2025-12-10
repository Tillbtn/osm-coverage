
import os
import geopandas as gpd
import pandas as pd
import json

# Configuration
DATA_DIR = "data"
ALKIS_FILE = os.path.join(DATA_DIR, "alkis_addresses.parquet")
OSM_BUILDINGS_FILE = os.path.join(DATA_DIR, "osm_buildings.parquet")
SITE_DIR = "site"
OUTPUT_FILE = os.path.join(SITE_DIR, "missing_buildings.geojson")

def main():
    if not os.path.exists(ALKIS_FILE):
        print(f"Error: {ALKIS_FILE} not found. Run previous scripts first.")
        return
    if not os.path.exists(OSM_BUILDINGS_FILE):
        print(f"Error: {OSM_BUILDINGS_FILE} not found. Run 03b_fetch_osm_buildings.py first.")
        return

    print("Loading data...")
    alkis = gpd.read_parquet(ALKIS_FILE)
    osm_buildings = gpd.read_parquet(OSM_BUILDINGS_FILE)
    
    print(f"ALKIS addresses: {len(alkis)}")
    print(f"OSM buildings: {len(osm_buildings)}")
    
    # Ensure CRS match
    if alkis.crs != osm_buildings.crs:
        print("Reprojecting OSM buildings to match ALKIS CRS...")
        osm_buildings = osm_buildings.to_crs(alkis.crs)

    print("Performing spatial join (ALKIS within OSM Buildings)...")
    # We want to find ALKIS addresses that are NOT within any OSM building
    # sjoin with how='left' and predicate='within' will attach building info to addresses
    # if they are inside.
    
    # "within" checks if the point is inside the polygon.
    joined = gpd.sjoin(alkis, osm_buildings, how='left', predicate='within')
    
    # Filter for those that didn't match a building (index_right is NaN)
    missing_buildings = joined[joined.index_right.isna()]
    
    print(f"Found {len(missing_buildings)} addresses not inside any OSM building.")
    
    if len(missing_buildings) == 0:
        print("Great! All addresses are inside buildings (or something went wrong).")
        return

    # Clean up columns for export
    # We keep street, housenumber, municipality (district), and maybe geometry
    cols_to_keep = ['street', 'housenumber', 'district', 'geometry']
    
    final_gdf = missing_buildings[cols_to_keep].copy()

    # Ensure District Column exists
    if 'district' not in final_gdf.columns:
         final_gdf['district'] = 'Global'

    # Reproject globally if needed (optimization)
    if final_gdf.crs != "EPSG:4326":
        print("Converting to EPSG:4326 for web output...")
        final_gdf = final_gdf.to_crs("EPSG:4326")

    # Output Directory for split files
    BUILDINGS_OUT_DIR = os.path.join(SITE_DIR, "buildings")
    os.makedirs(BUILDINGS_OUT_DIR, exist_ok=True)
    
    districts = final_gdf['district'].unique()
    districts_list = []
    
    print(f"Splitting into {len(districts)} districts...")
    
    for district in districts:
        d_gdf = final_gdf[final_gdf['district'] == district]
        count = len(d_gdf)
        
        # Save GeoJSON
        out_path = os.path.join(BUILDINGS_OUT_DIR, f"{district}.geojson")
        d_gdf.to_file(out_path, driver='GeoJSON')
        
        districts_list.append({
            "name": district,
            "count": count
        })
        
    # Save districts meta
    districts_list.sort(key=lambda x: x['name'])
    with open(os.path.join(BUILDINGS_OUT_DIR, "districts.json"), 'w') as f:
        json.dump(districts_list, f, indent=2)

    # Also save the full file for backward compatibility or global view (optional, but requested structure implies split)
    # Keeping the global file for now as 'missing_buildings.geojson' for the default view or fallback
    print(f"Saving global file to {OUTPUT_FILE}...")
    final_gdf.to_file(OUTPUT_FILE, driver='GeoJSON')
    print("Done.")

if __name__ == "__main__":
    main()
