
import os
import glob
import zipfile
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
import tqdm
import sqlite3

# Configuration
DATA_DIR = "data"
ALKIS_DIR = os.path.join(DATA_DIR, "alkis")
OUTPUT_FILE = os.path.join(DATA_DIR, "alkis_addresses.parquet")

def extract_addresses_from_gpkg(gpkg_path):
    """
    Extracts addresses from the 'gebaeude' layer of a GPKG.
    Refines selection to only include buildings with addresses.
    Returns a GeoDataFrame.
    """
    try:
        # Read 'gebaeude' layer. 
        # Note: We might need to adjust columns based on strict schema inspection,
        # but 'lagebezeichnung' (street) and 'hausnummer' are standard ALKIS terms usually mapped.
        # However, the previous inspection showed: 'objid', 'gfk', and no clear address columns in the LIMIT 1 sample.
        # Wait, the previous sample inspection output was:
        # (..., 'Herzbergweg', '7') which looks like address data!
        # The columns listed were just 'fid', 'geom', 'objid', 'gfk'. 
        # But the sample output had MORE fields. 
        # Let's rely on geopandas to read all columns and then filter.
        
        gdf = gpd.read_file(gpkg_path, layer='gebaeude', engine='pyogrio')
        
        # Identify address columns. 
        # Standard ALKIS usually has fields like 'lag' (Lage) or similar. 
        # Based on the sample output 'Herzbergweg', '7', these are likely near the end.
        # We'll look for columns that look like addresses.
        
        # Common column names in converted ALKIS: 'str_name', 'haus_nr', or simply 'lagebezeichnung', 'hausnummer'
        # Or sometimes they are just descriptive text fields.
        
        # Let's inspect columns dynamically if needed, but for now assuming standard names
        # derived from the sample: likely 'lagebezeichnung'/'strasse' and 'hausnummer'.
        
        # If columns are not obvious, we might need a mapping.
        # Let's dump columns if we fail to find standard ones.
        
        candidates_street = [c for c in gdf.columns if 'str' in c.lower() or 'lage' in c.lower() or 'name' in c.lower()]
        candidates_hnr = [c for c in gdf.columns if 'haus' in c.lower() or 'nr' in c.lower()]
        
        # Simplified heuristics based on common OGD conversions
        street_col = None
        hnr_col = None
        
        if 'strasse' in gdf.columns: street_col = 'strasse'
        elif 'str_name' in gdf.columns: street_col = 'str_name'
        elif 'lagebezeichnung' in gdf.columns: street_col = 'lagebezeichnung'
        elif 'bez' in gdf.columns: street_col = 'bez'
        
        if 'hausnummer' in gdf.columns: hnr_col = 'hausnummer'
        elif 'haus_nr' in gdf.columns: hnr_col = 'haus_nr'
        elif 'hsnr' in gdf.columns: hnr_col = 'hsnr'
        elif 'hnr' in gdf.columns: hnr_col = 'hnr'
        
        if not street_col or not hnr_col:
            # Try to guess based on content text
            # This is a bit risky but needed if names vary
            print(f"  Warning: Standard columns not found in {os.path.basename(gpkg_path)}. Columns: {gdf.columns.tolist()}")
            # Simple heuristic: Look for columns 'str' and 'nr'
            for c in gdf.columns:
                if 'str' in c.lower() and not street_col: street_col = c
                if 'nr' in c.lower() and not hnr_col: hnr_col = c
        
        if street_col and hnr_col:
            # print(f"  Using columns: {street_col}, {hnr_col}")
            # Ensure we don't modify the original slice warning
            gdf = gdf.copy()
            gdf = gdf[gdf[hnr_col].notna() & gdf[street_col].notna()]
            gdf = gdf[[street_col, hnr_col, 'geometry']]
            gdf = gdf.rename(columns={street_col: 'street', hnr_col: 'housenumber'})
            
            # Convert to points (centroids) if they are polygons
            # ALKIS buildings are polygons
            if gdf.geometry.type.iloc[0] == 'Polygon' or gdf.geometry.type.iloc[0] == 'MultiPolygon':
                 gdf['geometry'] = gdf.geometry.centroid
            
            return gdf

        
        return None

    except Exception as e:
        print(f"Error processing {gpkg_path}: {e}")
        return None

def main():
    zip_files = glob.glob(os.path.join(ALKIS_DIR, "*.zip"))
    
    all_addresses = []
    
    print(f"Found {len(zip_files)} ZIP files.")
    
    for zip_file in tqdm.tqdm(zip_files):
        # Unzip to temp location
        dirname = os.path.splitext(zip_file)[0]
        if not os.path.exists(dirname):
            try:
                with zipfile.ZipFile(zip_file, 'r') as zf:
                    zf.extractall(dirname)
            except zipfile.BadZipFile:
                print(f"Skipping bad zip: {zip_file}")
                continue
        
        # Get District Name from filename (e.g. lkr_03157_Peine_kon.gpkg.zip -> Peine)
        # format is usually lkr_XXXXX_Name_kon...
        # Simple parse:
        base = os.path.basename(zip_file)
        parts = base.split('_')
        if len(parts) >= 4:
            district_name = parts[2] # Adjust index based on actual filenames
            # If name has spaces or multiple parts? Usually joined by underscore in these files
            # Let's clean it up slightly if needed, but 'Peine', 'Harburg' seem simple.
            # Example: lkr_03252_Hameln-Pyrmont_kon.gpkg.zip
        else:
            district_name = base
            
        # Find gpkg
        gpkgs = glob.glob(os.path.join(dirname, "*.gpkg"))
        for gpkg in gpkgs:
            gdf = extract_addresses_from_gpkg(gpkg)
            if gdf is not None and not gdf.empty:
                gdf['district'] = district_name
                all_addresses.append(gdf)

        
        # Cleanup (optional, keeping extracted might be useful for debugging)
        # shutil.rmtree(dirname)

    if all_addresses:
        print("Concatenating...")
        full_gdf = pd.concat(all_addresses, ignore_index=True)
        
        print(f"Total addresses found: {len(full_gdf)}")
        
        # Save to Parquet
        full_gdf.to_parquet(OUTPUT_FILE)
        print(f"Saved to {OUTPUT_FILE}")
    else:
        print("No addresses extracted!")

if __name__ == "__main__":
    main()
