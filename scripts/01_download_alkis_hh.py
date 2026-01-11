
import os
import requests
import sys

# Attempt to find the file or download via WFS
DATA_DIR = "data/hh"
os.makedirs(DATA_DIR, exist_ok=True)

# 1. Try direct ZIP download (Best effort guesses)
# Based on recent search results
CANDIDATE_URLS = [
    "https://daten-hamburg.de/inspire/INSPIRE_Adressen_Hauskoordinaten_HH_2024-07-02.zip",
    "https://daten-hamburg.de/inspire/INSPIRE_Adressen_Hauskoordinaten_HH_2024-05-24.zip",
    "https://daten-hamburg.de/inspire/INSPIRE_Adressen_Hauskoordinaten_HH_2024-07-01.zip",
    "https://daten-hamburg.de/inspire/INSPIRE_Adressen_Hauskoordinaten_HH_2024-01-01.zip"
]

def download_file(url, local_filename):
    print(f"Attempting download from {url}...")
    try:
        with requests.get(url, stream=True, timeout=10) as r:
            r.raise_for_status()
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        print(f"Downloaded {local_filename}")
        return True
    except Exception as e:
        print(f"Failed: {e}")
        if os.path.exists(local_filename):
            os.remove(local_filename)
        return False

def main():
    target_zip = os.path.join(DATA_DIR, "alkis.zip")
    
    if os.path.exists(target_zip):
        print(f"{target_zip} already exists. Skipping download.")
        return

    print("Searching for Hamburg Hauskoordinaten (INSPIRE GML)...")
    
    success = False
    for url in CANDIDATE_URLS:
        if download_file(url, target_zip):
            success = True
            break
            
    if not success:
        print("\nCould not automatically download the file.")
        print("Please visit: http://suche.transparenz.hamburg.de/")
        print("Search for 'INSPIRE HH Adressen Hauskoordinaten' (GML Format).")
        print(f"Download the ZIP file and save it as: {os.path.abspath(target_zip)}")
        print("Alternatively, you can provide the expanded GML file in the data/hh directory.")

if __name__ == "__main__":
    main()
