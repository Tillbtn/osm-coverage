import os
import requests
import tqdm
import csv
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ALKIS_DIR = os.path.join(DATA_DIR, "mv", "alkis")
CSV_FILE = os.path.join(DATA_DIR, "mv", "Gemeinde_Gemarkung_Kreis.csv")

def generate_urls(csv_path):
    urls = []
    # Base URL pattern
    base_url = "https://www.geodaten-mv.de/dienste/alkis_nas_download?index=1&dataset=32538df8-6b74-4582-8591-c77e85fbf929&file={id}_SHP_{name}.zip"
    
    # Store unique municipalities to avoid duplicates
    # Key: id_Gemeinde, Value: Gemeinde_Name (original)
    municipalities = {}

    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return []

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            
            for row in reader:
                id_gemeinde = row.get('id_Gemeinde')
                gemeinde_name = row.get('Gemeinde_Name')
                
                if id_gemeinde and gemeinde_name:
                    if 'hist.' in gemeinde_name:
                        continue
                    municipalities[id_gemeinde] = gemeinde_name
                    
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return []

    # Sort by ID
    for id_gemeinde in sorted(municipalities.keys()):
        original_name = municipalities[id_gemeinde]
        
        # Replace comma, dot, space etc. with underscore
        transformed_name = original_name.replace(',', '_').replace('.', '_').replace('/', '_').replace('(', '_').replace(")", '_').replace(')', '_').replace('-', '_').replace(' ', '_')
        
        encoded_name = urllib.parse.quote(transformed_name)
        
        link = base_url.format(id=id_gemeinde, name=encoded_name)
        urls.append(link)
    
    return urls

def download_file(url, dest_path):
    if os.path.exists(dest_path):
        print(f"Skipping {os.path.basename(dest_path)}, already exists.")
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
    
    print(f"Reading municipalities from {CSV_FILE}...")
    urls = generate_urls(CSV_FILE)
    
    if not urls:
        print("No URLs generated. Please check the CSV file.")
        return

    print(f"Generated {len(urls)} download links.")
    
    download_tasks = []
    
    for url in urls:
        # Extract filename from URL
        try:
            if 'file=' in url:
                filename_part = url.split('file=')[-1]
                filename = filename_part.split('&')[0]
                
                dest_path = os.path.join(ALKIS_DIR, filename)
                download_tasks.append((url, dest_path))
            else:
                print(f"Warning: Could not extract filename from {url}, skipping.")
                continue
            
        except Exception as e:
            print(f"Error parsing URL {url}: {e}")

    print(f"Starting download of {len(download_tasks)} files to {ALKIS_DIR}...")
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        for url, path in download_tasks:
            executor.submit(download_file, url, path)

if __name__ == "__main__":
    main()
