
import os
import requests
import time
import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon, MultiPolygon
import tqdm
import json
import sys

# Configuration
ALKIS_META_URL = "https://arcgis-geojson.s3.eu-de.cloud-object-storage.appdomain.cloud/alkis-vektor/lgln-opengeodata-alkis-vektor.geojson"
DATA_DIR = "data"
OSM_DIR = os.path.join(DATA_DIR, "osm_buildings")
OUTPUT_FILE = os.path.join(DATA_DIR, "osm_buildings.parquet")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

def fetch_osm_buildings(bbox, name):
    """
    Fetch building polygons from Overpass for a given bbox.
    bbox: (minx, miny, maxx, maxy)
    """
    # Overpass query for buildings
    # We use 'out geom' to get coordinates for ways/relations
    overpass_query = f"""
    [out:json][timeout:180];
    (
      way["building"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
      relation["building"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
    );
    out geom;
    """
    
    try:
        response = requests.post(OVERPASS_URL, data={'data': overpass_query})
        response.raise_for_status()
        data = response.json()
        
        elements = data.get('elements', [])
        records = []
        
        for el in elements:
            try:
                geom = None
                tags = el.get('tags', {})
                
                if el['type'] == 'way':
                    if 'geometry' in el:
                        coords = [(pt['lon'], pt['lat']) for pt in el['geometry']]
                        if len(coords) >= 3:
                            geom = Polygon(coords)
                
                elif el['type'] == 'relation':
                    # Relations are harder to reconstruct from simple 'out geom' if they are complex multipolygons
                    # But often simple multipolygons come with 'bounds' or members with geometry
                    # For simplicity in this script, we might skip complex relations or try a best effort
                    # 'out geom' on relations gives geometry of members
                    # Reassembling proper MultiPolygons is non-trivial without a proper library like osmtogeojson or pyosmium
                    # However, simple buildings are usually ways.
                    # Let's try to grab the members if they form outer rings
                    
                    # For now, simplistic approach: iterate members, if outer and way, take it.
                    # This is imperfect (ignores inner rings / complex shapes), but good enough for "is point inside code"
                    # as it covers the area.
                    
                    # Better approach relying on 'center' or 'bounds' is not enough for "inside" check.
                    # Creating a box from bounds? A bit inaccurate.
                    
                    # For now, let's skip relations or just take their members as individual polygons if they are ways.
                    # This might result in duplicate coverage or holes, but it captures the "building area".
                     if 'members' in el:
                        for m in el['members']:
                           if m['type'] == 'way' and m.get('role') == 'outer' and 'geometry' in m:
                                coords = [(pt['lon'], pt['lat']) for pt in m['geometry']]
                                if len(coords) >= 3:
                                    # Treat each outer member as a building part
                                    poly = Polygon(coords)
                                    records.append({
                                        'id': f"{el['type']}/{el['id']}_{m['ref']}",
                                        'geometry': poly
                                    })
                    # Reset geom so we don't double add
                     geom = None

                if geom:
                     records.append({
                        'id': f"{el['type']}/{el['id']}",
                        'geometry': geom
                    })
                    
            except Exception as e:
                # print(f"Error parsing element {el.get('id')}: {e}")
                continue
        
        return gpd.GeoDataFrame(records, crs="EPSG:4326")

    except Exception as e:
        print(f"Error fetching OSM buildings for {name}: {e}")
        return gpd.GeoDataFrame()

def main():
    force_update = "--force" in sys.argv
    
    os.makedirs(OSM_DIR, exist_ok=True)
    
    print("Fetching district metadata...")
    resp = requests.get(ALKIS_META_URL)
    data = resp.json()
    
    features = data['features']
    print(f"Processing {len(features)} districts for OSM buildings...")
    
    all_osm_data = []
    
    # Iterate features to define bboxes (same logic as 03_fetch_osm.py)
    for i, feature in enumerate(tqdm.tqdm(features)):
        try:
            # Flatten geometry logic
            geom = feature['geometry']
            coords = geom['coordinates']
            
            all_coords = []
            def collect_coords(lst):
                if len(lst) == 2 and isinstance(lst[0], (float, int)):
                    all_coords.append(lst)
                else:
                    for x in lst:
                        collect_coords(x)
            
            collect_coords(coords)
            
            if not all_coords:
                continue

            lons = [c[0] for c in all_coords]
            lats = [c[1] for c in all_coords]
            
            bbox = (min(lons), min(lats), max(lons), max(lats))
            
            # Identify district
            props = feature['properties']
            dist_name = props.get('zip', f'district_{i}').split('/')[-1].replace('.gpkg.zip', '')
            
            cache_file = os.path.join(OSM_DIR, f"{dist_name}.parquet")
            
            if os.path.exists(cache_file) and not force_update:
                gdf = gpd.read_parquet(cache_file)
            else:
                time.sleep(1) # Rate limit
                gdf = fetch_osm_buildings(bbox, dist_name)
                if not gdf.empty:
                    gdf.to_parquet(cache_file)
            
            if not gdf.empty:
                all_osm_data.append(gdf)
                
        except Exception as e:
            print(f"Skipping feature {i}: {e}")

    if all_osm_data:
        print("Concatenating OSM building data...")
        full_gdf = pd.concat(all_osm_data, ignore_index=True)
        
        # Deduplicate by geometry or ID
        full_gdf = full_gdf.drop_duplicates(subset=['id'])
        
        print(f"Total OSM buildings: {len(full_gdf)}")
        full_gdf.to_parquet(OUTPUT_FILE)
        print(f"Saved to {OUTPUT_FILE}")
    else:
        print("No OSM building data extracted.")

if __name__ == "__main__":
    main()
