
import os
import glob
import zipfile
import geopandas as gpd
import pandas as pd
import tqdm
import re 

# Configuration
DATA_DIR = "data"
# Subfolders
DIR_NDS = os.path.join(DATA_DIR, "nds")
DIR_NRW = os.path.join(DATA_DIR, "nrw")
DIR_RLP = os.path.join(DATA_DIR, "rlp")


def normalize_columns(gdf):
    """
    Normalizes columns to 'street', 'housenumber', 'postcode', 'city', 'geometry'.
    """
    cols = gdf.columns.str.lower()
    
    # Heuristics
    street = None
    hnr = None
    city = None
    postcode = None
    
    # Street
    if 'strasse' in cols: street = gdf.columns[cols == 'strasse'][0]
    elif 'str_name' in cols: street = gdf.columns[cols == 'str_name'][0]
    elif 'lagebezeichnung' in cols: street = gdf.columns[cols == 'lagebezeichnung'][0]
    elif 'bez' in cols: street = gdf.columns[cols == 'bez'][0]
    
    # NRW Special Case: 'lagebeztxt' contains "Street 123b"
    if "lagebeztxt" in cols and street is None: 
        col_name = gdf.columns[cols == 'lagebeztxt'][0]
        
        # Filter out rows where lagebeztxt is missing
        gdf = gdf[gdf[col_name].notna()].copy()

        # Regex split
        # Pattern: Starts with non-digits (Street), then space, then Digit (Housenumber)
        # "Musterstraße 123 a"
        # Using a custom function to split
        def split_addr(val):
            if not isinstance(val, str): return None, None
            # Find first digit which signifies start of housenumber usually
            match = re.search(r'\s+(\d.*)$', val)
            if match:
                s = val[:match.start()].strip()
                h = match.group(1).strip()
                return s, h
            return val, None # Fallback
            
        gdf[['street_split', 'hnr_split']] = gdf[col_name].apply(lambda x: pd.Series(split_addr(x)))
        street = 'street_split'
        hnr = 'hnr_split'
    
    # Standard Hnr
    if not hnr:
        if 'hausnummer' in cols: hnr = gdf.columns[cols == 'hausnummer'][0]
        elif 'haus_nr' in cols: hnr = gdf.columns[cols == 'haus_nr'][0]
        elif 'hsnr' in cols: hnr = gdf.columns[cols == 'hsnr'][0]
        elif 'hnr' in cols: hnr = gdf.columns[cols == 'hnr'][0]
    
    # City
    if 'ort' in cols: city = gdf.columns[cols == 'ort'][0]
    elif 'gemeinde' in cols: city = gdf.columns[cols == 'gemeinde'][0]
    elif 'landkreis' in cols: city = gdf.columns[cols == 'landkreis'][0]
    elif 'ort_name' in cols: city = gdf.columns[cols == 'ort_name'][0]
    elif 'gem_name' in cols: city = gdf.columns[cols == 'gem_name'][0]
    
    # Postcode
    if 'plz' in cols: postcode = gdf.columns[cols == 'plz'][0]
    elif 'postleitzahl' in cols: postcode = gdf.columns[cols == 'postleitzahl'][0]

    if not street or not hnr:
        return None
        
    rename = {street: 'street', hnr: 'housenumber'}
    if city: rename[city] = 'city'
    if postcode: rename[postcode] = 'postcode'
    
    gdf = gdf.rename(columns=rename)
    
    # Filter out empty streets (NaN or whitespace only)
    gdf = gdf[gdf['street'].notna() & (gdf['street'].astype(str).str.strip() != "")]
    
    # Add missing
    if 'city' not in gdf.columns: gdf['city'] = None
    if 'postcode' not in gdf.columns: gdf['postcode'] = None
    
    # Convert Polygon to Point
    if not gdf.empty and (gdf.geometry.type.iloc[0] == 'Polygon' or gdf.geometry.type.iloc[0] == 'MultiPolygon'):
        gdf['geometry'] = gdf.geometry.buffer(0)
        
        # Filter out invalid/empty geometries
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty & gdf.geometry.is_valid].copy()
        
        if not gdf.empty:
            if gdf.crs and gdf.crs.is_geographic:
                try:
                    # Project to UTM 32N for centroid calculation
                    temp_gdf = gdf.to_crs(epsg=25832)
                    temp_gdf['geometry'] = temp_gdf.geometry.buffer(0)
                    gdf['geometry'] = temp_gdf.geometry.centroid.to_crs(gdf.crs)
                except Exception as e:
                    print(f"Warning during centroid calculation: {e}, falling back to representative_point")
                    gdf['geometry'] = gdf.geometry.representative_point()
            else:
                gdf['geometry'] = gdf.geometry.centroid
        
    return gdf[['street', 'housenumber', 'postcode', 'city', 'geometry']]


def process_state(state_name, state_dir, process_func):
    alkis_source_dir = os.path.join(state_dir, "alkis")
    output_file = os.path.join(state_dir, "alkis.parquet")
    
    if not os.path.exists(alkis_source_dir):
        print(f"[{state_name}] No ALKIS folder found at {alkis_source_dir}, skipping.")
        return

    print(f"[{state_name}] Processing addresses...")
    
    results = process_func(alkis_source_dir)
    
    if results:
        full_gdf = pd.concat(results, ignore_index=True)
        # Deduplicate
        full_gdf = full_gdf.drop_duplicates()
        
        full_gdf.to_parquet(output_file)
        print(f"[{state_name}] Saved {len(full_gdf)} addresses to {output_file}")
    else:
        print(f"[{state_name}] No addresses found.")

def process_lgln(directory):
    # LGLN: Zips containing GPKGs
    results = []
    zips = glob.glob(os.path.join(directory, "*.zip"))
    for z in tqdm.tqdm(zips, desc="Extracting NDS Zips"):
        folder = os.path.splitext(z)[0]
        if not os.path.exists(folder):
            try:
                with zipfile.ZipFile(z, 'r') as zf:
                    zf.extractall(folder)
            except: pass
            
    gpkgs = glob.glob(os.path.join(directory, "**/*.gpkg"), recursive=True)
    print(f"Found {len(gpkgs)} potential GPKG files/dirs in {directory}")
    for gpath in tqdm.tqdm(gpkgs, desc="Processing NDS GPKGs"):
        if os.path.isdir(gpath): continue
        
        try:
            base = os.path.basename(gpath)
            parts = base.split('_')
            district = base
            if len(parts) >= 4:
                district = parts[2]
                if len(parts) == 5: district += f"_{parts[3]}"
            
            try:
                gdf = gpd.read_file(gpath, layer='gebaeude', engine='pyogrio')
            except ValueError:
                layers = gpd.list_layers(gpath)
                print(f"  Layer 'gebaeude' not found in {base}. Layers: {layers['name'].tolist()}")
                continue
                
            gdf = normalize_columns(gdf)
            if gdf is not None:
                gdf['district'] = district
                gdf['state'] = 'Niedersachsen'
                results.append(gdf)
            else:
                print(f"  Normalization failed for {base}")
                print(f"  Columns: {gpd.read_file(gpath, layer='gebaeude', rows=0).columns.tolist()}")
        except Exception as e:
            print(f"  Error processing {gpath}: {e}")
            pass
    return results

def process_nrw(directory):

    results = []
    zips = glob.glob(os.path.join(directory, "*.zip"))
    for z in tqdm.tqdm(zips, desc="Extracting NRW Zips"):
        folder = os.path.splitext(z)[0]
        if not os.path.exists(folder):
            try:
                with zipfile.ZipFile(z, 'r') as zf:
                    zf.extractall(folder)
            except: pass
            
    gpkgs = glob.glob(os.path.join(directory, "**/*.gpkg"), recursive=True)
    for gpath in tqdm.tqdm(gpkgs, desc="Processing NRW GPKGs"):
        try:
            base = os.path.basename(gpath)
            parts = base.split('_')
            
            # parts structure: gru, vereinf, ID, NamePart1, NamePart2..., EPSG..., GeoPackage.gpkg
            # Name starts at index 3. Ends before the part starting with EPSG.
            name_parts = []
            for p in parts[3:]:
                if p.startswith("EPSG"):
                    break
                name_parts.append(p)
            
            district = " ".join(name_parts)
            if not district: district = "Unknown"

            # Layer selection
            layers = gpd.list_layers(gpath)
            target_layer = None
            
            # "GebauedeBauwerk" is the layer suffix for NRW
            for lname in layers['name']:
                if "GebauedeBauwerk" in lname:
                    target_layer = lname
                    break
            
            if target_layer:
                try:
                    gdf = gpd.read_file(gpath, layer=target_layer, engine='pyogrio')
                    norm_gdf = normalize_columns(gdf)
                    
                    if norm_gdf is not None:
                        norm_gdf['district'] = district
                        norm_gdf['state'] = 'NRW'
                        results.append(norm_gdf)
                    else:
                        print(f"  [DEBUG] Normalization failed for {base} (Layer: {target_layer})")
                        print(f"  [DEBUG] Columns found: {gdf.columns.tolist()}")
                except Exception as e:
                    print(f"  [DEBUG] Error reading {gpath}: {e}")
            else:
                print(f"  [DEBUG] No layer with 'GebauedeBauwerk' found in {base}. Layers: {layers['name'].tolist()}")
                pass
        except Exception as e: 
             print(f"Error processing {gpath}: {e}")
             pass
    return results

def load_kreise_mapping(csv_path):
    mapping = {}
    if not os.path.exists(csv_path):
        print(f"Warning: Mapping file {csv_path} not found.")
        return mapping
        
    try:
        # Try utf-8 first, fallback to latin1 (common for german gov data)
        encodings = ['utf-8', 'latin1', 'cp1252']
        
        lines = []
        for enc in encodings:
            try:
                with open(csv_path, 'r', encoding=enc) as f:
                    lines = f.readlines()
                break
            except UnicodeDecodeError:
                continue
                
        for line in lines:
            parts = line.strip().split(';')
            if len(parts) > 2:
                key = parts[0]
                name = parts[2]
                # 5 digit keys for ARS/Regionalschlüssel
                key = key.strip()
                if key.isdigit() and len(key) == 5:
                    mapping[key] = name
    except Exception as e:
        print(f"Error reading mapping file: {e}")
    
    return mapping

def process_rlp(directory):
    results = []
    
    mapping_file = os.path.join(DATA_DIR, "rlp", "rlp-districts-mapping.csv")
    kreise_map = load_kreise_mapping(mapping_file)
    print(f"Loaded {len(kreise_map)} mappings from {mapping_file}")

    geojsons = glob.glob(os.path.join(directory, "*.geojson"))
    for gpath in tqdm.tqdm(geojsons, desc="Processing RLP chunks"):
        try:
            gdf = gpd.read_file(gpath, engine='pyogrio')
            
            # Check for UTM-like coordinates (X > 180 is a strong signal it's not degrees)
            if not gdf.empty:
                min_x = gdf.total_bounds[0]
                if min_x > 180:
                     # It's likely UTM Zone 32N (EPSG:25832)
                     # Force set CRS
                     gdf.set_crs(epsg=25832, allow_override=True, inplace=True)

            # Determine district BEFORE normalization because normalize_columns drops extra columns
            district_series = None
            cols_lower = gdf.columns.str.lower()
            
            if 'gmdschl' in cols_lower:
                d_col = gdf.columns[cols_lower == 'gmdschl'][0]
                # Extract first 5 digits
                # robust string conversion: Handle potential float/int representation
                raw_codes = gdf[d_col].astype(str).str.replace(r'\.0$', '', regex=True)
                # Pad with zeros if necessary (though usually RLP gmdschl are 8 digits starting with 07...)
                raw_codes = raw_codes.str.zfill(8) 
                
                district_codes = raw_codes.str[:5]
                # Map to names
                district_series = district_codes.map(kreise_map)
                
                district_series = district_series.fillna(district_codes) # Fallback to code if name not found 
            elif 'gemeinde' in cols_lower:
                d_col = gdf.columns[cols_lower == 'gemeinde'][0]
                # Try to use this as is, or same mapping
                district_series = gdf[d_col].astype(str)

            gdf = normalize_columns(gdf)
            if gdf is not None:
                if district_series is not None:
                    gdf['district'] = district_series
                else:
                    gdf['district'] = 'RLP_Chunk' # Todo: Map by spatial join if needed
                
                
                gdf['state'] = 'RLP'
                results.append(gdf)
            else:
                pass
        except Exception as e: 
            pass
    return results

def main():
    process_state("NDS", DIR_NDS, process_lgln)
    process_state("NRW", DIR_NRW, process_nrw)
    process_state("RLP", DIR_RLP, process_rlp)

if __name__ == "__main__":
    main()
