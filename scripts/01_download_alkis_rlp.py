import os
import requests
import json
import tqdm

# Configuration
WFS_URL = "https://geo5.service24.rlp.de/wfs/alkis_rp.fcgi"
LAYER = "ave:GebaeudeBauwerk"
DATA_DIR = "data"
ALKIS_DIR = os.path.join(DATA_DIR, "rlp", "alkis")
PAGE_SIZE = 10000

def download_chunk(start_index, chunk_id):
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": LAYER,
        "STARTINDEX": start_index,
        "COUNT": PAGE_SIZE,
        "OUTPUTFORMAT": "application/json; subtype=geojson"
    }
    
    try:
        response = requests.get(WFS_URL, params=params, stream=True)
        response.raise_for_status()
        
        # Check if it's a valid GeoJSON response or XML error
        if 'xml' in response.headers.get('Content-Type', ''):
            content = response.content
            if b"ExceptionReport" in content:
                print(f"Error fetching chunk {chunk_id}: {content}")
                return 0
        
        filename = f"alkis_rlp_chunk_{chunk_id:04d}.geojson"
        dest_path = os.path.join(ALKIS_DIR, filename)
        
        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return 1
        
    except Exception as e:
        print(f"Failed to download chunk {chunk_id}: {e}")
        return 0

def check_feature_count(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return len(data.get('features', []))
    except:
        return 0

def main():
    os.makedirs(ALKIS_DIR, exist_ok=True)
    
    start_index = 0
    chunk_id = 0
    
    print(f"Starting WFS download for layer {LAYER}...")
    
    while True:
        print(f"Downloading chunk {chunk_id} (Start: {start_index})...")
        success = download_chunk(start_index, chunk_id)
        
        if not success:
            print("Download failed, stopping.")
            break
            
        filename = f"alkis_rlp_chunk_{chunk_id:04d}.geojson"
        path = os.path.join(ALKIS_DIR, filename)
        
        count = check_feature_count(path)
        print(f"Chunk {chunk_id} contained {count} features.")
        
        if count < PAGE_SIZE:
            print("Reached end of data.")
            break
            
        start_index += count
        chunk_id += 1

if __name__ == "__main__":
    main()
