
import os
import requests
import sys
import osmium
import pandas as pd
import geopandas as gpd
from shapely import wkb
import tqdm
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import gc

# Configuration
DATA_DIR = "data"
PBF_URL = "https://download.geofabrik.de/europe/germany/niedersachsen-latest.osm.pbf"
PBF_FILE = os.path.join(DATA_DIR, "niedersachsen-latest.osm.pbf")
OUTPUT_FILE = os.path.join(DATA_DIR, "osm_addresses.parquet")

# Optimization: Process in chunks
CHUNK_SIZE = 10000  

class AddressHandler(osmium.SimpleHandler):
    def __init__(self):
        super(AddressHandler, self).__init__()
        self.buffer = []
        self.chunks = []
        self.wkbfab = osmium.geom.WKBFactory()
        self.pbar = tqdm.tqdm(desc="Processing objects", unit=" obj")
        self.total_addresses = 0

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
                    self.buffer.append({
                        'street': street_val,
                        'housenumber': tags['addr:housenumber'],
                        # 'postcode': tags.get('addr:postcode', ''), # Optional: drop to save more RAM if not used
                        # 'city': tags.get('addr:city', ''),         # Optional: drop to save more RAM
                        'wkb': wkb_data
                    })
                    
                    if len(self.buffer) >= CHUNK_SIZE:
                        self.flush_buffer()
                        
                except Exception:
                    pass
    
    def flush_buffer(self):
        if not self.buffer:
            return

        # Convert buffer to DataFrame -> GeoDataFrame -> Centroids -> Minimal DataFrame
        df = pd.DataFrame(self.buffer)
        
        # Parse Geometry
        # We process geometry immediately to drop the heavy WKB and dict overhead
        df['geometry'] = df['wkb'].apply(lambda x: wkb.loads(x, hex=True) if isinstance(x, str) else wkb.loads(x))
        df['geometry'] = df['geometry'].apply(lambda g: g.centroid)
        
        # Drop WKB immediately
        df.drop(columns=['wkb'], inplace=True)
        
        # Convert to GeoDataFrame (lightweight wrapper at this point)
        gdf = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")
        
        # Deduplicate locally (saves memory for the final merge)
        # Note: We can't fully dedup until the end, but we can remove local dupes
        gdf['lon'] = gdf.geometry.x
        gdf['lat'] = gdf.geometry.y
        gdf.drop_duplicates(subset=['street', 'housenumber', 'lat', 'lon'], inplace=True)
        gdf.drop(columns=['lat', 'lon'], inplace=True)

        self.chunks.append(gdf)
        self.total_addresses += len(gdf)
        
        # Clear buffer and force GC
        self.buffer = []
        gc.collect() 
    
    def __del__(self):
        if hasattr(self, 'pbar'):
            self.pbar.close()

    def node(self, n):
        self.process_object(n, self.wkbfab.create_point)

    def way(self, w):
        try:
             self.process_object(w, lambda x: self.wkbfab.create_linestring(x))
        except:
             pass

    def relation(self, r):
        try:
             self.process_object(r, lambda x: self.wkbfab.create_multipolygon(x))
        except:
             pass

def download_pbf():
    print(f"Checking {PBF_URL}...")
    try:
        head_response = requests.head(PBF_URL)
        head_response.raise_for_status()
        last_modified = head_response.headers.get("Last-Modified")

        if last_modified and os.path.exists(PBF_FILE):
            remote_time = parsedate_to_datetime(last_modified)
            local_time = datetime.fromtimestamp(os.path.getmtime(PBF_FILE), tz=timezone.utc)
            
            print(f"Remote: {remote_time}, Local: {local_time}")
            
            if remote_time <= local_time:
                print("Local file is newer or same age as remote. Skipping download.")
                return

    except Exception as e:
        print(f"Warning: Could not check timestamp: {e}. Proceeding with download attempt.")

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
    # Check if update is needed
    try:
        import check_geofabrik_export_date
        print("Checking if OSM update is required...")
        remote_date = check_geofabrik_export_date.get_remote_date()
        local_date = check_geofabrik_export_date.get_local_date()
        
        if remote_date and local_date and remote_date <= local_date:
            print(f"No update needed. Remote ({remote_date}) <= Local ({local_date})")
            return
    except ImportError:
        print("Warning: Could not import check_geofabrik_export_date. Skipping Date Check.")

    os.makedirs(DATA_DIR, exist_ok=True)
    download_pbf()
    
    print(f"Extracting addresses from PBF in chunks of {CHUNK_SIZE}...")
    handler = AddressHandler()
    
    try:
        handler.apply_file(PBF_FILE, locations=True, idx="sparse_file_array")
        # Final flush
        handler.flush_buffer()
    except Exception as e:
        print(f"\nError processing PBF: {e}")
        return
    
    handler.pbar.close()
    
    print(f"\nProcessed {handler.total_addresses} addresses in {len(handler.chunks)} chunks.")
    
    if not handler.chunks:
        print("No addresses found?")
        return
        
    print("Concatenating chunks...")
    # This might momentarily spike memory, but much less than the list-of-dicts approach
    full_gdf = pd.concat(handler.chunks, ignore_index=True)
    
    # Release chunks memory
    handler.chunks = None
    gc.collect()
    
    print("Global Deduplication...")
    full_gdf['lon'] = full_gdf.geometry.x
    full_gdf['lat'] = full_gdf.geometry.y
    full_gdf.drop_duplicates(subset=['street', 'housenumber', 'lat', 'lon'], inplace=True)
    full_gdf.drop(columns=['lat', 'lon'], inplace=True)
    
    print(f"Total unique OSM addresses: {len(full_gdf)}")
    
    full_gdf.to_parquet(OUTPUT_FILE)
    print(f"Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
