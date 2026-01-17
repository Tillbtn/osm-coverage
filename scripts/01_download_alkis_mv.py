import os
import requests
import tqdm
from concurrent.futures import ThreadPoolExecutor

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ALKIS_DIR = os.path.join(DATA_DIR, "mv", "alkis")
LINKS_FILE = os.path.join(DATA_DIR, "mv", "shapefile_links.txt")

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
    if not os.path.exists(LINKS_FILE):
        print(f"Error: {LINKS_FILE} not found. Please ensure it exists.")
        return

    os.makedirs(ALKIS_DIR, exist_ok=True)
    
    download_tasks = []
    
    with open(LINKS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            url = line.strip()
            if not url:
                continue
            
            # Extract filename from URL
            # URL format: ...&file=13003000_SHP_Rostock...zip
            try:
                # Find the 'file=' parameter
                if 'file=' in url:
                    filename_part = url.split('file=')[-1]
                    # In case there are other params after (though in this dataset there aren't likely)
                    filename = filename_part.split('&')[0]
                else:
                    # Fallback if format is different, just take last part of path? 
                    # But here the filename is a defined query param.
                    # Let's assume the previous generation logic which puts file at the end.
                    print(f"Warning: Could not extract filename from {url}, skipping.")
                    continue
                
                dest_path = os.path.join(ALKIS_DIR, filename)
                download_tasks.append((url, dest_path))
            except Exception as e:
                print(f"Error parsing URL {url}: {e}")

    print(f"Found {len(download_tasks)} files to download.")
    print(f"Starting download to {ALKIS_DIR}...")
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        for url, path in download_tasks:
            executor.submit(download_file, url, path)

if __name__ == "__main__":
    main()
