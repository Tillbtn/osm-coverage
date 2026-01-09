
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

STATES = {
    "nds": {
        "pbf_url": "https://download.geofabrik.de/europe/germany/niedersachsen-latest.osm.pbf",
        "pbf_file": "niedersachsen-latest.osm.pbf"
    },
    "nrw": {
        "pbf_url": "https://download.geofabrik.de/europe/germany/nordrhein-westfalen-latest.osm.pbf",
        "pbf_file": "nordrhein-westfalen-latest.osm.pbf"
    },
    "rlp": {
        "pbf_url": "https://download.geofabrik.de/europe/germany/rheinland-pfalz-latest.osm.pbf",
        "pbf_file": "rheinland-pfalz-latest.osm.pbf"
    }
}

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
                        # 'postcode': tags.get('addr:postcode', ''), 
                        'city': tags.get('addr:city', ''),
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

    def area(self, a):
        try:
             self.process_object(a, lambda x: self.wkbfab.create_multipolygon(x))
        except:
             pass


def download_pbf(url, local_path):
    print(f"Checking {url}...")
    try:
        head_response = requests.head(url)
        head_response.raise_for_status()
        last_modified = head_response.headers.get("Last-Modified")

        if last_modified and os.path.exists(local_path):
            remote_time = parsedate_to_datetime(last_modified)
            local_time = datetime.fromtimestamp(os.path.getmtime(local_path), tz=timezone.utc)
            
            # Allow 1 hour buffer or exact match
            # If local is newer or same, we skip.
            if remote_time <= local_time:
                print(f"  Local file is up-to-date (Remote: {remote_time}, Local: {local_time}). Skipping download.")
                return False

    except Exception as e:
        print(f"Warning: Could not check timestamp: {e}. Proceeding with download attempt.")

    print(f"Downloading {url} to {local_path}...")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        total_size = int(r.headers.get('content-length', 0))
        block_size = 8192
        with open(local_path, 'wb') as f, tqdm.tqdm(total=total_size, unit='iB', unit_scale=True) as t:
            for chunk in r.iter_content(chunk_size=block_size):
                t.update(len(chunk))
                f.write(chunk)
    print("Download complete.")
    return True

def process_state(state_key, config):
    state_dir = os.path.join(DATA_DIR, state_key)
    pbf_dir = os.path.join(state_dir, "osm")
    os.makedirs(pbf_dir, exist_ok=True)
    
    pbf_path = os.path.join(pbf_dir, config["pbf_file"])
    output_parquet = os.path.join(state_dir, "osm.parquet")
    
    downloaded = download_pbf(config["pbf_url"], pbf_path)
    
    if not downloaded and os.path.exists(output_parquet):
        pbf_time = os.path.getmtime(pbf_path)
        parq_time = os.path.getmtime(output_parquet)
        if parq_time > pbf_time:
            print(f"[{state_key}] Parquet is newer than PBF. Skipping processing.")
            return

    print(f"[{state_key}] Extracting addresses from PBF in chunks of {CHUNK_SIZE}...")
    handler = AddressHandler()
    
    try:
        am = osmium.area.AreaManager()
        
        # Pass 1
        print(f"[{state_key}] Pass 1: Scanning relations...")
        reader1 = osmium.io.Reader(pbf_path)
        osmium.apply(reader1, am.first_pass_handler())
        reader1.close()
        
        # Pass 2
        print(f"[{state_key}] Pass 2: Assembling areas and extracting addresses...")
        reader2 = osmium.io.Reader(pbf_path)
        idx = osmium.index.create_map("sparse_file_array")
        lh = osmium.NodeLocationsForWays(idx)
        lh.ignore_errors()
        
        osmium.apply(reader2, lh, handler, am.second_pass_handler(handler))
        reader2.close()
        
        # Final flush
        handler.flush_buffer()
    except Exception as e:
        print(f"[{state_key}] Error processing PBF: {e}")
        return
    
    handler.pbar.close()
    
    if not handler.chunks:
        print(f"[{state_key}] No addresses found.")
        return
        
    print(f"[{state_key}] Concatenating chunks...")
    full_gdf = pd.concat(handler.chunks, ignore_index=True)
    
    # Release chunks memory
    handler.chunks = None
    gc.collect()
    
    print(f"[{state_key}] Global Deduplication...")
    full_gdf['lon'] = full_gdf.geometry.x
    full_gdf['lat'] = full_gdf.geometry.y
    full_gdf.drop_duplicates(subset=['street', 'housenumber', 'lat', 'lon'], inplace=True)
    full_gdf.drop(columns=['lat', 'lon'], inplace=True)
    
    print(f"[{state_key}] Total unique OSM addresses: {len(full_gdf)}")
    
    full_gdf.to_parquet(output_parquet)
    print(f"[{state_key}] Saved to {output_parquet}")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    
    for state_key, config in STATES.items():
        process_state(state_key, config)

if __name__ == "__main__":
    main()
