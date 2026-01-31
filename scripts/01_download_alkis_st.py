import os
import requests
import zipfile
import shutil
import tqdm

# Configuration
DOWNLOAD_URL = "https://www.geodatenportal.sachsen-anhalt.de/gfds_webshare/download/LVermGeo/Geodatenportal/externedaten/GBIS_Gebaeude.zip"
DATA_DIR = "data/st/alkis"
ZIP_FILENAME = "GBIS_Gebaeude.zip"

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    zip_path = os.path.join(DATA_DIR, ZIP_FILENAME)
    
    print(f"Downloading {DOWNLOAD_URL}...")
    try:
        response = requests.get(DOWNLOAD_URL, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        block_size = 1024
        
        with open(zip_path, 'wb') as f, tqdm.tqdm(
            desc="Downloading",
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
        ) as bar:
            for data in response.iter_content(block_size):
                size = f.write(data)
                bar.update(size)
                
        print("Download complete.")
        
        print(f"Extracting to {DATA_DIR}...")
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            first_item = zip_ref.namelist()[0]
            if "/" in first_item:
                zip_ref.extractall(DATA_DIR)
            else:
                target_subdir = os.path.join(DATA_DIR, "GBIS_Gebaeude")
                os.makedirs(target_subdir, exist_ok=True)
                zip_ref.extractall(target_subdir)
                 
        print("Extraction complete.")
        
        os.remove(zip_path)
        print("Removed ZIP file.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()