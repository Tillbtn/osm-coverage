
import os
import glob
import zipfile
import geopandas as gpd
import pandas as pd
import tqdm
import re 
import numpy as np 

# Configuration
DATA_DIR = "data"
# Subfolders
DIR_NDS = os.path.join(DATA_DIR, "nds")
DIR_NRW = os.path.join(DATA_DIR, "nrw")
DIR_RLP = os.path.join(DATA_DIR, "rlp")

def remove_ortsteil(text):
    """
    Removes 'Ortsteil ...' from the address string.
    """
    if not isinstance(text, str): return text
    return re.sub(r',\s*Ortsteil\s+[^;]+', '', text, flags=re.IGNORECASE).strip()

def split_alkis_address_string(original_street, original_hnr_string):
    """
    Parses "Straße 1, 2, Weg 3" into [("Straße", "1"), ("Straße", "2"), ("Weg", "3")]
    """
    if not isinstance(original_hnr_string, str): 
         return [(original_street, original_hnr_string)]
         
    original_hnr_string = original_hnr_string.replace(';', ',')

    if ',' not in original_hnr_string:
        return [(original_street, original_hnr_string)]
        
    parts = original_hnr_string.split(',')
    results = []
    
    current_street = original_street
    
    # Pattern: Matches "New Street Name 123"
    # Group 1: Non-digit characters (Street)
    # Group 2: Digit characters (House Number start)
    street_pattern = re.compile(r'^\s*([^\d].*?)\s+([0-9].*)$')
    
    first = True
    for part in parts:
        part = part.strip()
        if not part: continue
        
        if first:
            results.append((current_street, part))
            first = False
            continue
                
        match = street_pattern.match(part)
        if match:
            current_street = match.group(1)
            hnr = match.group(2)
            results.append((current_street, hnr))
        else:
            results.append((current_street, part))
            
    return results

def expand_complex_addresses(df, desc="Splitting Addresses"):
    """
    Splits rows where housenumber contains commas/semicolons.
    """
    if 'housenumber' not in df.columns: return df
    
    mask = df['housenumber'].astype(str).str.contains(r'[,;]', regex=True)
    if not mask.any():
        return df
        
    print(f"  Found {mask.sum()} complex address rows to split.")
    
    rows_to_split = df[mask]
    clean_rows = df[~mask]
    
    new_data = []
    
    for idx, row in rows_to_split.iterrows():
        street = row['street']
        hnr = row['housenumber']
        
        splits = split_alkis_address_string(street, hnr)
        
        for s_new, h_new in splits:
            entry = row.to_dict()
            entry['street'] = s_new
            entry['housenumber'] = h_new
            new_data.append(entry)
            
    split_df = pd.DataFrame(new_data)
    
    if not split_df.empty:
        if isinstance(df, gpd.GeoDataFrame):
             split_df = gpd.GeoDataFrame(split_df, geometry='geometry', crs=df.crs)
        
        combined = pd.concat([clean_rows, split_df], ignore_index=True)
        return combined
    
    return df

def clean_nrw_street_suffixes(df):
    """
    Removes 2-letter suffixes from street names found in some NRW datasets (e.g. "Frankenstr. Ju")
    """
    if 'street' not in df.columns: return df
    
    # Check if we have any streets ending in Space + 2 letters
    # Exclude common valid 2-letter endings like "Au" or "Aa", and Roman numerals
    regex = r'\s+(?!(?:Au|Aa|Oy|Ut|II|IV|VI|IX|XI)$)[A-Za-zäöüßÄÖÜ]{2}$'
    df['street'] = df['street'].astype(str).str.replace(regex, "", regex=True).str.strip()
    return df

def clean_nds_street_suffixes(df):
    """
    Removes suffixes starting with a comma followed by text (non-digits) from NDS data.
    """
    if 'street' not in df.columns: return df
    
    # Pattern: comma, optional whitespace, non-digits until end of string
    regex = r',\s*[^0-9]+$'
    df['street'] = df['street'].astype(str).str.replace(regex, "", regex=True).str.strip()
    return df

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
        
        # Clean Ortsteil before splitting
        gdf[col_name] = gdf[col_name].apply(remove_ortsteil)

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
                
                # Apply NDS specific cleaning
                gdf = clean_nds_street_suffixes(gdf)
                
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
                        
                        # Apply NRW specific cleaning & Splitting
                        norm_gdf = clean_nrw_street_suffixes(norm_gdf)
                        norm_gdf = expand_complex_addresses(norm_gdf)
                        
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
    csv_path = os.path.join(directory, "HAUSKOORDINATEN_RP", "HAUSKOORDINATEN_RP_hk.csv")
    
    if not os.path.exists(csv_path):
        print(f"[RLP] CSV file not found at {csv_path}")
        return []
        
    print(f"[RLP] Reading CSV from {csv_path}...")
    
    try:
        # Columns: nba;oid;qua;landschl;land;regbezschl;regbez;kreisschl;kreis;gmdschl;gmd;ottschl;ott;strschl;str;hnr;adz;zone;ostwert;nordwert
        df = pd.read_csv(csv_path, sep=';', dtype=str)
        
        df = df.dropna(subset=['str', 'hnr', 'ostwert', 'nordwert'])
        
        # Filter out invalid housenumbers (0)
        df = df[df['hnr'] != '0']
        
        df['housenumber'] = df['hnr'] + df['adz'].fillna('')
        
        df = df.rename(columns={
            'str': 'street',
            'gmd': 'district',
            'plz': 'postcode'
        })
        
        df['postcode'] = None
        df['city'] = df['district']
        
        x = pd.to_numeric(df['ostwert'], errors='coerce')
        y = pd.to_numeric(df['nordwert'], errors='coerce')
        
        gdf = gpd.GeoDataFrame(
            df[['street', 'housenumber', 'postcode', 'city', 'district']],
            geometry=gpd.points_from_xy(x, y),
            crs="EPSG:25832"
        )
        
        # Remove invalid geometries
        gdf = gdf[gdf.geometry.is_valid & ~gdf.geometry.is_empty]
        
        gdf['state'] = 'RLP'
        
        return [gdf]
        
    except Exception as e:
        print(f"[RLP] Error processing CSV: {e}")
        return []

def main():
    process_state("NDS", DIR_NDS, process_lgln)
    process_state("NRW", DIR_NRW, process_nrw)
    process_state("RLP", DIR_RLP, process_rlp)

if __name__ == "__main__":
    main()
