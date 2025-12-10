
import os
import requests
import sys
import osmium
import pandas as pd
import geopandas as gpd
from shapely import wkb
import tqdm

# Configuration
DATA_DIR = "data"
PBF_URL = "https://download.geofabrik.de/europe/germany/niedersachsen-latest.osm.pbf"
PBF_FILE = os.path.join(DATA_DIR, "niedersachsen-latest.osm.pbf")
OUTPUT_FILE = os.path.join(DATA_DIR, "osm_addresses.parquet")

class AddressHandler(osmium.SimpleHandler):
    def __init__(self):
        super(AddressHandler, self).__init__()
        self.addresses = []
        self.wkbfab = osmium.geom.WKBFactory()
        # Estimate: Niedersachsen has ~3 million nodes/ways? 
        # Actually total objects is much higher (~60M). 
        # Just use a running counter.
        self.pbar = tqdm.tqdm(desc="Processing objects", unit=" obj")

    def process_object(self, obj, geom_func):
        self.pbar.update(1)
        tags = obj.tags
        if 'addr:housenumber' in tags:
            street = tags.get('addr:street')
            place = tags.get('addr:place')
            
            street_val = street if street else place
            
            if street_val:
                try:
                    wkb_data = geom_func(obj)
                    self.addresses.append({
                        'street': street_val,
                        'housenumber': tags['addr:housenumber'],
                        'postcode': tags.get('addr:postcode', ''),
                        'city': tags.get('addr:city', ''),
                        'wkb': wkb_data
                    })
                except Exception:
                    pass
    
    def __del__(self):
        if hasattr(self, 'pbar'):
            self.pbar.close()

    def node(self, n):
        self.process_object(n, self.wkbfab.create_point)

    def way(self, w):
        try:
             # Ways are LineStrings in PBF terms. 
             # We can check if closed? 
             # For address purposes, we just need the geometry to get a centroid.
             self.process_object(w, lambda x: self.wkbfab.create_linestring(x))
        except:
             pass

    def relation(self, r):
        try:
             self.process_object(r, lambda x: self.wkbfab.create_multipolygon(x))
        except:
             pass

def download_pbf():
    if os.path.exists(PBF_FILE):
        print(f"PBF file exists: {PBF_FILE}")
        return

    print(f"Downloading {PBF_URL}...")
    with requests.get(PBF_URL, stream=True) as r:
        r.raise_for_status()
        total_size = int(r.headers.get('content-length', 0))
        block_size = 8192
        with open(PBF_FILE, 'wb') as f, tqdm.tqdm(total=total_size, unit='iB', unit_scale=True) as t:
            for chunk in r.iter_content(chunk_size=block_size):
                t.update(len(chunk))
                f.write(chunk)
    print("Download complete.")

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    download_pbf()
    
    print("Extracting addresses from PBF (this WILL take a few minutes)...")
    handler = AddressHandler()
    
    try:
        handler.apply_file(PBF_FILE, locations=True, idx="sparse_file_array")
    except Exception as e:
        print(f"\nError processing PBF: {e}")
        return
    
    handler.pbar.close()
    
    print(f"\nFound {len(handler.addresses)} addresses.")
    
    if not handler.addresses:
        print("No addresses found?")
        return
        
    print("Creating GeoDataFrame...")
    df = pd.DataFrame(handler.addresses)
    
    # Convert WKB to Shapely
    df['geometry'] = df['wkb'].apply(lambda x: wkb.loads(x, hex=True) if isinstance(x, str) else wkb.loads(x))
    
    # Convert Polygons/LineStrings to Centroids
    # Fix: Use apply for Series operation
    # Also, for Ways (LineStrings), we might want to cast to Polygon if closed to get true center,
    # but LineString.centroid is usually close enough for "Address Point" purposes.
    print("Calculating centroids...")
    df['geometry'] = df['geometry'].apply(lambda g: g.centroid)
    
    # Drop WKB
    df.drop(columns=['wkb'], inplace=True)
    
    gdf = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")
    
    # Deduplicate
    print("Deduplicating...")
    gdf['lon'] = gdf.geometry.x
    gdf['lat'] = gdf.geometry.y
    gdf.drop_duplicates(subset=['street', 'housenumber', 'lat', 'lon'], inplace=True)
    gdf.drop(columns=['lat', 'lon'], inplace=True)
    
    print(f"Total Unique OSM Addresses: {len(gdf)}")
    
    gdf.to_parquet(OUTPUT_FILE)
    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
