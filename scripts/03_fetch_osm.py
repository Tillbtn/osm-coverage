
import os
import requests
import time
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
import tqdm
import json

# Configuration
# Using downloaded ALKIS metadata to get boundings
ALKIS_META_URL = "https://arcgis-geojson.s3.eu-de.cloud-object-storage.appdomain.cloud/alkis-vektor/lgln-opengeodata-alkis-vektor.geojson"
DATA_DIR = "data"
OSM_DIR = os.path.join(DATA_DIR, "osm")
OUTPUT_FILE = os.path.join(DATA_DIR, "osm_addresses.parquet")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

def fetch_osm_addresses(bbox, name):
    """
    Fetch addresses from Overpass for a given bbox.
    bbox: (minx, miny, maxx, maxy)
    """
    overpass_query = f"""
    [out:json][timeout:90];
    (
      node["addr:housenumber"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
      way["addr:housenumber"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
      relation["addr:housenumber"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
    );
    out center;
    """
    
    try:
        response = requests.post(OVERPASS_URL, data={'data': overpass_query})
        response.raise_for_status()
        data = response.json()
        
        elements = data.get('elements', [])
        records = []
        for el in elements:
            tags = el.get('tags', {})
            lat = el.get('lat') or el.get('center', {}).get('lat')
            lon = el.get('lon') or el.get('center', {}).get('lon')
            
            if lat and lon and 'addr:housenumber' in tags and 'addr:street' in tags:
                records.append({
                    'street': tags['addr:street'],
                    'housenumber': tags['addr:housenumber'],
                    'postcode': tags.get('addr:postcode', ''),
                    'city': tags.get('addr:city', ''),
                    'lat': lat,
                    'lon': lon
                })
        
        return pd.DataFrame(records)

    except Exception as e:
        print(f"Error fetching OSM for {name}: {e}")
        return pd.DataFrame()

import sys

def main():
    force_update = "--force" in sys.argv
    
    os.makedirs(OSM_DIR, exist_ok=True)

    
    print("Fetching district metadata...")
    resp = requests.get(ALKIS_META_URL)
    data = resp.json()
    
    features = data['features']
    print(f"Processing {len(features)} districts for OSM data...")
    
    all_osm_data = []
    
    # Iterate features to define bboxes
    # We can use the geometry in GeoJSON to create a bbox
    for i, feature in enumerate(tqdm.tqdm(features)):
        try:
            # Extract geometry to get bbox
            geom = feature['geometry']
            # Quick bbox calc
            coords = geom['coordinates']
            # Flatten coords to get min/max
            # It's a Polygon or MultiPolygon.
            # Flatten recursively
            def flatten(l):
                out = []
                for item in l:
                    if isinstance(item, (float, int)):
                        return [l] 
                    elif isinstance(item[0], (float, int)):
                        out.extend([item])
                    else:
                        out.extend(flatten(item))
                return out
                
            # Flatten logic is a bit tricky for nested lists of varied depth
            # Simpler: Load into shapely if possible, but let's just do a naive recursion that works for GeoJSON coords
            
            all_coords = []
            def collect_coords(lst):
                if len(lst) == 2 and isinstance(lst[0], (float, int)):
                    all_coords.append(lst)
                else:
                    for x in lst:
                        collect_coords(x)
            
            collect_coords(coords)
            
            lons = [c[0] for c in all_coords]
            lats = [c[1] for c in all_coords]
            
            bbox = (min(lons), min(lats), max(lons), max(lats))
            
            # Identify district
            props = feature['properties']
            # Construct a safe name
            dist_name = props.get('zip', f'district_{i}').split('/')[-1].replace('.gpkg.zip', '')
            
            cache_file = os.path.join(OSM_DIR, f"{dist_name}.csv")
            
            if os.path.exists(cache_file) and not force_update:
                df = pd.read_csv(cache_file)
            else:
                # Be nice to Overpass
                time.sleep(1) 
                df = fetch_osm_addresses(bbox, dist_name)
                if not df.empty:
                    df.to_csv(cache_file, index=False)
            
            if not df.empty:
                all_osm_data.append(df)
                
        except Exception as e:
            print(f"Skipping feature {i}: {e}")

    if all_osm_data:
        print("Concatenating OSM data...")
        full_df = pd.concat(all_osm_data, ignore_index=True)
        
        # Enforce string types for columns that might be mixed (like postcode)
        for col in ['street', 'housenumber', 'postcode', 'city']:
            if col in full_df.columns:
                full_df[col] = full_df[col].astype(str)

        # Deduplicate
        # Sometimes lat/lon might shift slightly, but usually same node ID has same lat/lon approx.
        # Ideally we dedup on geometry + attributes.
        full_df.drop_duplicates(subset=['lat', 'lon', 'housenumber', 'street'], inplace=True)

        # Convert to GeoDataFrame
        full_gdf = gpd.GeoDataFrame(
            full_df, geometry=gpd.points_from_xy(full_df.lon, full_df.lat), crs="EPSG:4326"
        )
        # Drop lat/lon cols if not needed
        full_gdf = full_gdf.drop(columns=['lat', 'lon'])
        
        print(f"Total OSM addresses: {len(full_gdf)}")
        full_gdf.to_parquet(OUTPUT_FILE)
        print(f"Saved to {OUTPUT_FILE}")
    else:
        print("No OSM data extracted.")

if __name__ == "__main__":
    main()
