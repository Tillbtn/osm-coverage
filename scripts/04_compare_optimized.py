import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
import os
import json
import datetime
import osmium
import re
import numpy as np
import tqdm

def normalize_key(street, hnr):
    s = str(street).lower()
    s = re.sub(r'\(.*?\)', '', s)
    s = s.replace("ß", "ss")
    s = s.replace("bgm.", "bürgermeister")
    s = s.replace("pl.", "platz")
    s = s.replace("prof.", "professor")
    s = s.replace("str.", "strasse") 
    s = s.replace("str ", "strasse ")
    s = s.replace(" ", "").replace("-", "").replace(".", "").replace("/", "")
    
    h = str(hnr).lower().replace(" ", "")
    return f"{s}{h}"

STATES = {
    "nds": { "pbf_file": "niedersachsen-latest.osm.pbf" },
    "nrw": { "pbf_file": "nordrhein-westfalen-latest.osm.pbf" },
    "rlp": { "pbf_file": "rheinland-pfalz-latest.osm.pbf" }
}


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

def process_complex_addresses(alkis_df, state_name):
    """
    Splits rows with commas in housenumber.
    """
    mask = alkis_df['housenumber'].astype(str).str.contains(r'[,;]', regex=True)
    if not mask.any():
        return alkis_df
        
    print(f"[{state_name}] Found {mask.sum()} complex address rows. Splitting...")
    
    rows_to_split = alkis_df[mask]
    clean_rows = alkis_df[~mask]
    
    new_data = []
    
    for idx, row in tqdm.tqdm(rows_to_split.iterrows(), total=len(rows_to_split), desc=f"[{state_name}] Splitting Addresses", ascii=True):
        street = row['street']
        hnr = row['housenumber']
        
        splits = split_alkis_address_string(street, hnr)
        
        for s_new, h_new in splits:
            entry = row.to_dict()
            entry['street'] = s_new
            entry['housenumber'] = h_new
            new_data.append(entry)
            
    split_df = pd.DataFrame(new_data)
    
    # Convert back to GeoDataFrame
    if not split_df.empty:
        split_gdf = gpd.GeoDataFrame(split_df, geometry='geometry', crs=alkis_df.crs)
        combined = pd.concat([clean_rows, split_gdf], ignore_index=True)
        return combined
    
    return alkis_df

def clean_nrw_data(alkis_df):
    """
    Cleans Köln specific data issues:
    - Removes 2-letter suffixes from street names (e.g. "Frankenstr. Ju" -> "Frankenstr.")
    """
    if 'district' not in alkis_df.columns:
        return alkis_df

    mask_koeln = alkis_df['district'].str.contains("Köln", case=False, na=False)
    
    if not mask_koeln.any():
        return alkis_df
        
    print(f"[NRW] Cleaning {mask_koeln.sum()} rows for Köln...")
    
    regex = r'\s+[A-Za-zäöüßÄÖÜ]{2}$'
    original = alkis_df.loc[mask_koeln, 'street'].astype(str)
    cleaned = original.str.replace(regex, "", regex=True).str.strip()
    
    alkis_df.loc[mask_koeln, 'street'] = cleaned
    
    return alkis_df


def apply_corrections(alkis_df, corrections_file, state):
    """
    Applies corrections from a JSON file to the ALKIS dataframe.
    """
    if not os.path.exists(corrections_file):
        return alkis_df
        
    print(f"[{state}] Applying corrections from {corrections_file}...")
    try:
        with open(corrections_file, 'r', encoding='utf-8') as f:
            corrections = json.load(f)
    except Exception as e:
        print(f"[{state}] Error loading corrections file: {e}")
        return alkis_df
        
    count = 0
    for corr in corrections:
        from_street = corr.get("from_street")
        if not from_street: continue
        
        mask = alkis_df['street'] == from_street
        
        if "city" in corr:
            # map city to district if column exists
            if 'district' in alkis_df.columns:
                 mask &= (alkis_df['district'] == corr["city"])
        
        if "from_housenumber" in corr:
             mask &= (alkis_df['housenumber'] == corr["from_housenumber"])
             
        if not mask.any():
            continue
            
        rows_affected = mask.sum()
        count += rows_affected
        
        # Apply changes
        if "to_street" in corr:
            alkis_df.loc[mask, 'street'] = corr["to_street"]
            
        if "to_housenumber" in corr:
            alkis_df.loc[mask, 'housenumber'] = corr["to_housenumber"]

    print(f"[{state}] Applied corrections to {count} rows.")
    return alkis_df

def main():
    STATES_LIST = ["nds", "nrw", "rlp"] 
    
    DATA_DIR = "data"
    SITE_DIR = "site/public/states"
    
    today = datetime.date.today().isoformat()
    
    found_any = False

    for state in STATES_LIST:
        alkis_path = os.path.join(DATA_DIR, state, "alkis.parquet")
        osm_path = os.path.join(DATA_DIR, state, "osm.parquet")
        
        if not os.path.exists(alkis_path):
            print(f"[{state}] ALKIS file not found: {alkis_path}. Skipping.")
            continue
        if not os.path.exists(osm_path):
            print(f"[{state}] OSM file not found: {osm_path}. Skipping.")
            continue
            
        found_any = True
        print(f"[{state}] Loading data...")
        try:
           alkis = gpd.read_parquet(alkis_path)
           osm = gpd.read_parquet(osm_path)
        except Exception as e:
           print(f"[{state}] Error loading data: {e}")
           continue

        # Apply Generic Corrections
        corrections_file = os.path.join(SITE_DIR, state, f"{state}_alkis_corrections.json")
        alkis = apply_corrections(alkis, corrections_file, state)

        # Address Splitting
        if state in ["nrw"]:
            alkis = process_complex_addresses(alkis, state)

        # NRW Specific Cleaning
        if state == "nrw":
            alkis = clean_nrw_data(alkis)

        # Generate Keys
        print(f"[{state}] Generating keys...")
        # alkis
        alkis['street'] = alkis['street'].fillna("").astype(str)
        alkis['housenumber'] = alkis['housenumber'].fillna("").astype(str)
        alkis['key'] = alkis.apply(lambda row: normalize_key(row['street'], row['housenumber']), axis=1)
        
        # osm
        osm['street'] = osm['street'].fillna("").astype(str)
        osm['housenumber'] = osm['housenumber'].fillna("").astype(str)
        osm['key'] = osm.apply(lambda row: normalize_key(row['street'], row['housenumber']), axis=1)

        # Align CRS
        if alkis.crs is not None and osm.crs is not None and not alkis.crs.equals(osm.crs):
             print(f"[{state}] Reprojecting OSM from {osm.crs} to {alkis.crs}")
             osm = osm.to_crs(alkis.crs)

        # Matching Logic
        print(f"[{state}] Matching...")
        
        alkis = alkis.reset_index(drop=True)
        alkis['alkis_idx'] = alkis.index
        
        found_indices = set()
        
        # Chunked Matching
        CHUNK_SIZE = 50000
        for i in tqdm.tqdm(range(0, len(alkis), CHUNK_SIZE), desc=f"[{state}] Matching", ascii=True):
            chunk = alkis.iloc[i : i + CHUNK_SIZE].copy()
            relevant_keys = chunk['key'].unique()
            osm_subset = osm[osm['key'].isin(relevant_keys)]
            
            if osm_subset.empty: continue
                
            merged = pd.merge(
                chunk[['key', 'geometry', 'alkis_idx']],
                osm_subset[['key', 'geometry']],
                on='key',
                how='inner',
                suffixes=('_alkis', '_osm')
            )
            
            if merged.empty: continue
                
            distances = merged['geometry_alkis'].distance(merged['geometry_osm'])
            valid = merged[distances < 150] # allow 150m distance because OSM node may not be aligned with Alkis node
            found_indices.update(valid['alkis_idx'].unique())
            
        print(f"[{state}] Valid Matches: {len(found_indices)} / {len(alkis)}")
        
        alkis['found_in_osm'] = alkis['alkis_idx'].isin(found_indices)
        
        # Export preparation
        if alkis.crs != "EPSG:4326":
            alkis = alkis.to_crs(epsg=4326)
        
        missing = alkis[~alkis['found_in_osm']]
        
        state_total = len(alkis)
        state_missing = len(missing)
        state_osm_count = len(osm)
        
        # Directories
        state_out_dir = os.path.join(SITE_DIR, state)
        districts_dir = os.path.join(state_out_dir, "districts")
        os.makedirs(districts_dir, exist_ok=True)
        
        history_file = os.path.join(state_out_dir, f"{state}_history.json")
        districts_file = os.path.join(state_out_dir, f"{state}_districts.json")
        
        # Load History
        history_store = {"global": [], "districts": {}}
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    history_store = json.load(f)
            except: pass

        # Districts Processing
        if 'district' not in alkis.columns:
            alkis['district'] = f"Unknown_{state}"
        
        # Get OSM Snapshot Timestamp from PBF
        pbf_path = os.path.join("data", state, "osm", STATES[state]["pbf_file"])
        export_date = today 
        try:
             import osmium
             reader = osmium.io.Reader(pbf_path)
             header_ts = reader.header().get("osmosis_replication_timestamp")
             reader.close()
             if header_ts:
                 export_date = str(header_ts)
        except Exception as e:
            print(f"[{state}] Warning: Could not read PBF timestamp: {e}")

        districts = alkis['district'].unique()
        
        district_list = []
        
        for district in tqdm.tqdm(districts, desc=f"[{state}] Processing Districts", ascii=True):
            district_alkis = alkis[alkis['district'] == district]
            district_missing = district_alkis[~district_alkis['found_in_osm']]
            
            d_total = len(district_alkis)
            d_missing = len(district_missing)
            d_coverage = round((d_total - d_missing) / d_total * 100, 1) if d_total > 0 else 100.0
            
            unique_name = f"{district}" 
            
            clean_name = "".join([c if c.isalnum() else "_" for c in str(district)])
            out_filename = f"{clean_name}.geojson" 
            
            d_stats = {
                "name": unique_name,
                "state": state,
                "district": district,
                "total": d_total,
                "missing": d_missing,
                "coverage": d_coverage,
                "path": f"states/{state}/districts/{out_filename}",
                "filename": out_filename
            }
            district_list.append(d_stats)
            
            # History
            hist_key = unique_name
            d_hist_entry = {
                "date": export_date,
                "total": d_total,
                "missing": d_missing,
                "coverage": d_coverage
            }
            
            if hist_key not in history_store["districts"]:
                history_store["districts"][hist_key] = []
            
            d_hist = history_store["districts"][hist_key]
            if not d_hist or d_hist[-1]["date"] != export_date:
                d_hist.append(d_hist_entry)
            else:
                d_hist[-1] = d_hist_entry
                
            # GeoJSON Export
            missing_export = district_missing[['street', 'housenumber', 'geometry']]
            
            out_path = os.path.join(districts_dir, out_filename)
            if len(missing_export) > 0:
                missing_export.to_file(out_path, driver="GeoJSON")
            else:
                 with open(out_path, 'w') as f:
                    json.dump({"type": "FeatureCollection", "features": []}, f)

        # State Global Stats
        global_coverage = round((state_total - state_missing) / state_total * 100, 2) if state_total > 0 else 100.0
        g_entry = {
             "date": export_date,
             "alkis": state_total,
             "osm": state_osm_count,
             "missing": state_missing,
             "coverage": global_coverage
        }
        
        if not history_store["global"] or history_store["global"][-1]["date"] != export_date:
            history_store["global"].append(g_entry)
        else:
            history_store["global"][-1] = g_entry
            
        # Write State Files
        with open(history_file, 'w') as f:
            json.dump(history_store, f, indent=2)
            
        district_list.sort(key=lambda x: x['name'])
        with open(districts_file, 'w') as f:
            json.dump(district_list, f, indent=2)

    if not found_any:
        print("No data processed.")
    else:
        print("Comparison complete.")

if __name__ == "__main__":
    main()
