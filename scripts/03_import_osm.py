
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
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geofabrik_auth

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
REJECTED = "rejected"       # internal only: the login cookie was rejected


def _looks_like_html(response):
    """True for login/error pages served where a PBF was requested."""
    return "html" in response.headers.get("Content-Type", "").lower()


def _fetch_remote_md5(session, url):
    """Geofabrik publishes '<file>.md5' next to every PBF. Returns the hex digest or None."""
    try:
        r = session.get(url + ".md5", timeout=30)
        if r.status_code != 200:
            return None
        token = r.text.strip().split()[0].lower()
        return token if re.fullmatch(r"[0-9a-f]{32}", token) else None
    except Exception:
        return None


def _file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _remove_quietly(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        print(f"  Warning: could not remove {path}: {e}")


def _human_size(num_bytes):
    return f"{num_bytes / 1048576:.0f} MB" if num_bytes else "unknown size"


def _download_from(session, url, local_path, source):
    """One attempt against one server. Returns (status, detail).

    detail is a short phrase the caller folds into its single log line for this
    file; for FAILED it carries the reason. Nothing is printed here, so a
    successful attempt stays at one line in the cron log.

    The file is streamed to '<local_path>.part', verified against Content-Length,
    the PBF header magic and Geofabrik's published .md5, and only then moved into
    place. A broken connection or a login page served in place of the file
    therefore never leaves a bad PBF at local_path; the previous complete file
    (if any) stays untouched.
    """
    part_path = local_path + ".part"

    head_response = None
    try:
        head_response = session.head(url, allow_redirects=True, timeout=30)
        head_response.raise_for_status()
    except Exception as e:
        if source == "internal":
            # No answer from server for this file. Only 401/403 are cookie related, 5xx not.
            code = getattr(getattr(e, "response", None), "status_code", None)
            return (REJECTED if code in (401, 403) else FAILED), f"HEAD request failed: {e}"
        # The public server may still answer the GET; try it without a timestamp.
        head_response = None

    if head_response is not None:
        # A rejected cookie does not produce an error: the internal server
        # answers HTTP 200 with the OSM login page. Only the content type gives
        # it away.
        if _looks_like_html(head_response):
            if source == "internal":
                return REJECTED, "HTML instead of a PBF: login cookie not accepted"
            return FAILED, "HTML instead of a PBF"

        last_modified = head_response.headers.get("Last-Modified")
        if last_modified and os.path.exists(local_path):
            remote_time = parsedate_to_datetime(last_modified)
            local_time = datetime.fromtimestamp(os.path.getmtime(local_path), tz=timezone.utc)

            # Local copy is at least as new.
            if remote_time <= local_time:
                return UNCHANGED, (f"up-to-date ({source} server, "
                                   f"remote {remote_time:%Y-%m-%d %H:%M %Z})")

    started = time.monotonic()
    try:
        with session.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            if _looks_like_html(r):
                raise IOError("server sent an HTML page instead of a PBF (login rejected?)")
            total_size = int(r.headers.get('content-length', 0))
            received = 0
            block_size = 8192
            # Without the isatty guard the bar fills the cron log with refreshes.
            with open(part_path, 'wb') as f, tqdm.tqdm(
                    total=total_size, unit='iB', unit_scale=True,
                    desc=f"DL {os.path.basename(local_path)}", position=1, leave=False,
                    disable=not sys.stdout.isatty()) as bar:
                for data in r.iter_content(block_size):
                    f.write(data)
                    received += len(data)
                    bar.update(len(data))

        # Verification 1: byte count
        if total_size and received != total_size:
            raise IOError(f"incomplete download: {received} of {total_size} bytes received")

        # Verification 2: it has to be a PBF at all
        with open(part_path, "rb") as f:
            if b"OSMHeader" not in f.read(32):
                raise IOError("downloaded file does not start with an OSM PBF header")

        # Verification 3: Geofabrik's published checksum (when available)
        expected_md5 = _fetch_remote_md5(session, url)
        if expected_md5:
            actual_md5 = _file_md5(part_path)
            if actual_md5 != expected_md5:
                raise IOError(f"checksum mismatch: got {actual_md5}, expected {expected_md5}")
            checked = "md5 OK"
        else:
            checked = "no .md5 published, size checked"

        os.replace(part_path, local_path)
        return DOWNLOADED, (f"downloaded {_human_size(received)} from the {source} server "
                            f"in {time.monotonic() - started:.0f} s, {checked}")
    except Exception as e:
        _remove_quietly(part_path)
        return FAILED, str(e)


def download_pbf(public_url, local_path, label):
    """Download the PBF for one state if the remote copy is newer.

    Tries the internal server first when a cookie is available, then the public
    one. A rejected cookie (answered with a login page instead of an error) is
    renewed once, so a cookie that expired since the run started costs at most
    one state its internal download. Returns (status, detail); the caller prints
    detail as part of its one line for this file. Only a failed attempt logs a
    line of its own here.
    """
    _remove_quietly(local_path + ".part")  # leftover from a crashed run

    cookie = geofabrik_auth.get_download_cookie()
    for attempt in (1, 2):  # the second attempt runs with a renewed cookie
        if not cookie:
            break
        with geofabrik_auth.internal_session(cookie) as session:
            status, detail = _download_from(
                session, geofabrik_auth.internal_url(public_url), local_path, "internal")
        if status not in (FAILED, REJECTED):
            return status, detail
        cookie = (geofabrik_auth.refresh_download_cookie()
                  if status == REJECTED and attempt == 1 else None)
        if not cookie:
            print(f"[{label}] Internal server did not deliver ({detail}); "
                  "falling back to the public server.")

    with requests.Session() as session:
        session.headers.update(geofabrik_auth.HEADERS)
        status, detail = _download_from(session, public_url, local_path, "public")
    if status == FAILED:
        return status, f"download failed ({detail})"
    return status, detail


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
    
    pbf_name = config["pbf_file"]
    status, detail = download_pbf(config["pbf_url"], pbf_path, state_key)
    failed = status == FAILED

    if failed:
        if not os.path.exists(pbf_path):
            print(f"[{state_key}] {pbf_name}: {detail}, no previous PBF - skipping state.")
            return False
        detail += ", continuing with the previous PBF"

    if status != DOWNLOADED and os.path.exists(output_parquet):
        pbf_time = os.path.getmtime(pbf_path)
        parq_time = os.path.getmtime(output_parquet)
        if parq_time > pbf_time:
            print(f"[{state_key}] {pbf_name}: {detail}, parquet is newer - nothing to do.")
            return not failed

    print(f"[{state_key}] {pbf_name}: {detail}, extracting addresses "
          f"in chunks of {CHUNK_SIZE}...")
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