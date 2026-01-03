import os
import requests
import xml.etree.ElementTree as ET
import tqdm
from concurrent.futures import ThreadPoolExecutor

# Configuration
BASE_URL = "https://www.opengeodata.nrw.de/produkte/geobasis/lk/akt/gru_vereinfacht_gpkg/"
INDEX_URL = BASE_URL + "index.html" 
DATA_DIR = "data"
ALKIS_DIR = os.path.join(DATA_DIR, "nrw", "alkis")

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
        if os.path.exists(dest_path):
            os.remove(dest_path)

def main():
    os.makedirs(ALKIS_DIR, exist_ok=True)
    
    print(f"Fetching index from {BASE_URL}...")
    resp = requests.get(BASE_URL)
    resp.raise_for_status()
    
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        print("Direct parse failed, trying index.html...")
        resp = requests.get(BASE_URL + "index.html")
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

    files = []
    for file_node in root.findall(".//file"):
        name = file_node.get("name")
        if name and name.endswith(".zip"):
            files.append(name)
            
    print(f"Found {len(files)} files.")
    
    download_tasks = []
    for filename in files:
        url = BASE_URL + filename
        dest_path = os.path.join(ALKIS_DIR, filename)
        download_tasks.append((url, dest_path))
        
    print(f"Starting download of {len(download_tasks)} files...")
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        for url, path in download_tasks:
            executor.submit(download_file, url, path)

if __name__ == "__main__":
    main()
