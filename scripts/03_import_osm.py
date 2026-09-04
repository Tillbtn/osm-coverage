
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
import hashlib
import re

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
    },
    "bb": {
        "pbf_url": "https://download.geofabrik.de/europe/germany/brandenburg-latest.osm.pbf",
        "pbf_file": "brandenburg-latest.osm.pbf"
    },
    "hh": {
        "pbf_url": "https://download.geofabrik.de/europe/germany/hamburg-latest.osm.pbf",
        "pbf_file": "hamburg-latest.osm.pbf"
    },
    "he": {
        "pbf_url": "https://download.geofabrik.de/europe/germany/hessen-latest.osm.pbf",
        "pbf_file": "hessen-latest.osm.pbf"
    },
    "st": {
        "pbf_url": "https://download.geofabrik.de/europe/germany/sachsen-anhalt-latest.osm.pbf",
        "pbf_file": "sachsen-anhalt-latest.osm.pbf"
    },
    "sn": {
        "pbf_url": "https://download.geofabrik.de/europe/germany/sachsen-latest.osm.pbf",
        "pbf_file": "sachsen-latest.osm.pbf"
    },
    "be": {
        "pbf_url": "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf",
        "pbf_file": "berlin-latest.osm.pbf"
    },
    "mv": {
        "pbf_url": "https://download.geofabrik.de/europe/germany/mecklenburg-vorpommern-latest.osm.pbf",
        "pbf_file": "mecklenburg-vorpommern-latest.osm.pbf"
    }
}

# Optimization: Process in chunks
CHUNK_SIZE = 10000  

class AddressHandler(osmium.SimpleHandler):
    def __init__(self, state_key=None):
        super(AddressHandler, self).__init__()
        self.state_key = state_key
        self.buffer = []
        self.chunks = []
        self.wkbfab = osmium.geom.WKBFactory()
        self.pbar = tqdm.tqdm(desc=f"Proc {state_key}", unit=" obj", position=0, leave=True, disable=not sys.stdout.isatty())
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
                    hnr = tags['addr:housenumber']
                    h_name = None
                    
                    # Extract 'name' if it starts with 'Haus'
                    name = tags.get('name')
                    if name and name.lower().startswith('haus'):
                            h_name = name

                    wkb_data = geom_func(obj)
                    self.buffer.append({
                        'street': street_val,
                        'housenumber': hnr,
                        'housename': h_name,
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


# Result codes of download_pbf()
DOWNLOADED = "downloaded"   # a new, verified PBF is in place
UNCHANGED = "unchanged"     # local PBF is at least as new as the remote one
FAILED = "failed"           # download/verification failed; previous PBF (if any) kept


def _fetch_remote_md5(url, headers):
    """Geofabrik publishes '<file>.md5' next to every PBF. Returns the hex digest or None."""
    try:
        r = requests.get(url + ".md5", headers=headers, timeout=30)
        if r.status_code != 200:
            return None
        token = r.text.strip().split()[0].lower()
        if re.fullmatch(r"[0-9a-f]{32}", token):
            return token
        print(f"  Warning: unexpected checksum file content: {r.text.strip()[:80]!r}")
    except Exception as e:
        print(f"  Warning: could not fetch checksum {url}.md5: {e}")
    return None


def _file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _remove_quietly(path):
    try:
        if os.path.lexists(path):
            os.remove(path)
    except OSError as e:
        print(f"  Warning: could not remove {path}: {e}")


def download_pbf(url, local_path):
    """Download the PBF if the remote copy is newer.

    The file is streamed to '<local_path>.part', verified against Content-Length
    and Geofabrik's published .md5, and only then moved into place. A broken
    connection therefore never leaves a truncated PBF at local_path; the previous
    complete file (if any) stays untouched.
    """
    print(f"Checking {url}...")

    part_path = local_path + ".part"
    _remove_quietly(part_path)  # leftover from a crashed run

    try:
        head_response = requests.head(url, allow_redirects=True, timeout=30)
        head_response.raise_for_status()
        last_modified = head_response.headers.get("Last-Modified")

        if last_modified and os.path.exists(local_path):
            remote_time = parsedate_to_datetime(last_modified)
            local_time = datetime.fromtimestamp(os.path.getmtime(local_path), tz=timezone.utc)
            
            # If local is newer or same, we skip.
            if remote_time <= local_time:
                print(f"  Local file is up-to-date (Remote: {remote_time}, Local: {local_time}). Skipping download.")
                return UNCHANGED

    except Exception as e:
        print(f"Warning: Could not check timestamp: {e}. Proceeding with download attempt.")

    print(f"Downloading {url} to {local_path}...")
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            received = 0
            block_size = 8192
            with open(part_path, 'wb') as f, tqdm.tqdm(total=total_size, unit='iB', unit_scale=True, desc=f"DL {url.split('/')[-1]}", position=1, leave=False, disable=not sys.stdout.isatty()) as t:
                for chunk in r.iter_content(chunk_size=block_size):
                    t.update(len(chunk))
                    f.write(chunk)
                    received += len(chunk)

        # Verification 1: byte count (when the server announced one)
        if total_size and received != total_size:
            raise IOError(f"incomplete download: {received} of {total_size} bytes received")

        # Verification 2: Geofabrik's published checksum (when available)
        expected_md5 = _fetch_remote_md5(url, {})
        if expected_md5:
            actual_md5 = _file_md5(part_path)
            if actual_md5 != expected_md5:
                raise IOError(f"checksum mismatch: got {actual_md5}, expected {expected_md5}")
            print(f"  Checksum OK ({received} bytes).")
        else:
            print(f"  No checksum published; size check passed ({received} bytes).")

        os.replace(part_path, local_path)
        print("Download complete.")
        return DOWNLOADED
    except Exception as e:
        _remove_quietly(part_path)
        print(f"Failed to download {url}: {e}")
        if os.path.exists(local_path):
            print(f"  Keeping previous PBF {local_path}.")
        return FAILED


# Messages osmium produces when a PBF is truncated or otherwise unreadable.
_CORRUPT_PBF_MARKERS = ("pbf error", "eof", "uncompress", "invalid", "blob", "corrupt", "checksum", "truncat")


def looks_like_corrupt_pbf(exc):
    msg = str(exc).lower()
    return isinstance(exc, RuntimeError) and any(m in msg for m in _CORRUPT_PBF_MARKERS)


def process_state(state_key, config):
    state_dir = os.path.join(DATA_DIR, state_key)
    pbf_dir = os.path.join(state_dir, "osm")
    os.makedirs(pbf_dir, exist_ok=True)
    
    pbf_path = os.path.join(pbf_dir, config["pbf_file"])
    output_parquet = os.path.join(state_dir, "osm.parquet")

    # Special case: Berlin (be) can reuse Brandenburg (bb) data
    if state_key == "be":
        bb_config = STATES.get("bb")
        bb_dir = os.path.join(DATA_DIR, "bb")
        bb_parquet = os.path.join(bb_dir, "osm.parquet")
        
        if bb_config and os.path.exists(bb_parquet):
            print(f"[{state_key}] Brandenburg data found at {bb_parquet}. Reusing it for Berlin.")
            import shutil
            shutil.copy2(bb_parquet, output_parquet)
            
            # Also handle PBF for timestamp in script 04
            bb_pbf_path = os.path.join(bb_dir, "osm", bb_config["pbf_file"])
            if os.path.exists(bb_pbf_path):
                if os.path.exists(pbf_path) and not os.path.islink(pbf_path):
                     os.remove(pbf_path)
                
                if not os.path.exists(pbf_path):
                    try:
                        os.symlink(os.path.abspath(bb_pbf_path), pbf_path)
                        print(f"[{state_key}] Symlinked {bb_pbf_path} to {pbf_path}")
                    except Exception as e:
                        print(f"[{state_key}] Failed to symlink PBF: {e}. Copying instead...")
                        shutil.copy2(bb_pbf_path, pbf_path)
            return True
    
    status = download_pbf(config["pbf_url"], pbf_path)
    failed = status == FAILED

    if failed:
        if not os.path.exists(pbf_path):
            print(f"[{state_key}] Download failed and no previous PBF exists. Skipping.")
            return False
        print(f"[{state_key}] Download failed; continuing with the previous PBF.")
    
    if status != DOWNLOADED and os.path.exists(output_parquet):
        pbf_time = os.path.getmtime(pbf_path)
        parq_time = os.path.getmtime(output_parquet)
        if parq_time > pbf_time:
            print(f"[{state_key}] Parquet is newer than PBF. Skipping processing.")
            return not failed

    print(f"[{state_key}] Extracting addresses from PBF in chunks of {CHUNK_SIZE}...")
    handler = AddressHandler(state_key=state_key)
    
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
        if looks_like_corrupt_pbf(e) and os.path.isfile(pbf_path) and not os.path.islink(pbf_path):
            print(f"[{state_key}] PBF appears to be corrupt; deleting {pbf_path} so the next run re-downloads it.")
            _remove_quietly(pbf_path)
        return False
    
    handler.pbar.close()
    
    if not handler.chunks:
        print(f"[{state_key}] No addresses found.")
        return False
        
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
    return not failed


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    
    failed_states = []
    for state_key, config in STATES.items():
        if not process_state(state_key, config):
            failed_states.append(state_key)

    if failed_states:
        print(f"All processing complete. FAILED states: {', '.join(failed_states)}")
        sys.exit(1)
    print("All processing complete.")

if __name__ == "__main__":
    main()