
import os
import requests
import json
import tqdm
from concurrent.futures import ThreadPoolExecutor


# Configuration
GEOJSON_URL = "https://arcgis-geojson.s3.eu-de.cloud-object-storage.appdomain.cloud/alkis-vektor/lgln-opengeodata-alkis-vektor.geojson"
DATA_DIR = "data"
ALKIS_DIR = os.path.join(DATA_DIR, "nds", "alkis")


def download_file(url, dest_path):
    if os.path.exists(dest_path):
        print(f"Skipping {dest_path}, already exists.")
        return

    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        
        with open(dest_path, 'wb') as f, tqdm.tqdm(
            desc=os.path.basename(dest_path),
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
        ) as bar:
            for data in response.iter_content(chunk_size=1024):
                size = f.write(data)
                bar.update(size)
    except Exception as e:
        print(f"Error downloading {url}: {e}")

def main():
    os.makedirs(ALKIS_DIR, exist_ok=True)
    
    print("Fetching metadata GeoJSON...")
    resp = requests.get(GEOJSON_URL)
    resp.raise_for_status()
    data = resp.json()
    
    download_tasks = []
    
    print(f"Found {len(data['features'])} districts.")
    
    for feature in data['features']:
        props = feature['properties']
        zip_url = props.get('zip')
        if not zip_url:
            continue
            
        filename = zip_url.split('/')[-1]
        dest_path = os.path.join(ALKIS_DIR, filename)
        download_tasks.append((zip_url, dest_path))
        
    print(f"Starting download of {len(download_tasks)} files...")
    
    # Download in parallel (conservative 4 threads)
    with ThreadPoolExecutor(max_workers=4) as executor:
        for url, path in download_tasks:
            executor.submit(download_file, url, path)

if __name__ == "__main__":
    main()
