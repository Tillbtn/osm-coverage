import os
import requests
import zipfile
import shutil
import tqdm

# Configuration
DOWNLOAD_URL = "https://geobasis-rlp.de/data/hk/current/zip/HAUSKOORDINATEN_RP.zip"
DATA_DIR = "data"
RLP_ALKIS_DIR = os.path.join(DATA_DIR, "rlp", "alkis")
TARGET_DIR = os.path.join(RLP_ALKIS_DIR, "HAUSKOORDINATEN_RP")

def main():
    os.makedirs(RLP_ALKIS_DIR, exist_ok=True)
    
    zip_filename = "HAUSKOORDINATEN_RP.zip"
    zip_path = os.path.join(RLP_ALKIS_DIR, zip_filename)
    
    print(f"Downloading {DOWNLOAD_URL}...")
    try:
        # Disable SSL verification to handle cert issues
        requests.packages.urllib3.disable_warnings()
        response = requests.get(DOWNLOAD_URL, stream=True, verify=False)
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
        
        print(f"Extracting to {TARGET_DIR}...")
        if os.path.exists(TARGET_DIR):
             shutil.rmtree(TARGET_DIR)
        os.makedirs(TARGET_DIR, exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(TARGET_DIR)
            
        print("Extraction complete.")
        
        # Cleanup ZIP
        os.remove(zip_path)
        print("Removed ZIP file.")
        
    except Exception as e:
        print(f"Error executing download/extraction: {e}")

if __name__ == "__main__":
    main()
