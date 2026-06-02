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
import argparse
import sys

def normalize_street(street):
    s = str(street).lower()
    s = re.sub(r'\(.*?\)', '', s)
    s = s.replace("ß", "ss")
    s = s.replace("v.", "von")
    s = s.replace("bgm.", "bürgermeister")
    s = s.replace("bgm", "bürgermeister")
    s = s.replace("bürgerm.", "bürgermeister")
    s = s.replace("dr.", "doktor")
    s = s.replace("dr", "doktor")
    s = s.replace("pl.", "platz")
    s = s.replace("st.", "sankt")
    s = s.replace("prof.", "professor")
    s = s.replace("geschw.", "geschwister")
    s = s.replace("str.", "strasse") 
    s = s.replace("str ", "strasse ")
    s = s.replace("bauerschaft", "")
    s = s.replace("gerhard-hauptmann", "gerhart-hauptmann")
    s = s.replace(" ", "").replace("-", "").replace(".", "").replace("/", "").replace(",", "")
    return s

def normalize_key(street, hnr):
    s = normalize_street(street)
    h = str(hnr).lower().replace(" ", "").replace(",", "")
    return f"{s}{h}"

STATES = {
    "nds": { "pbf_file": "niedersachsen-latest.osm.pbf" },
    "nrw": { "pbf_file": "nordrhein-westfalen-latest.osm.pbf" },
    "rlp": { "pbf_file": "rheinland-pfalz-latest.osm.pbf" },
    "bb": { "pbf_file": "brandenburg-latest.osm.pbf" },
    "hh": { "pbf_file": "hamburg-latest.osm.pbf" },
    "he": { "pbf_file": "hessen-latest.osm.pbf" },
    "st": { "pbf_file": "sachsen-anhalt-latest.osm.pbf" },
    "sn": { "pbf_file": "sachsen-latest.osm.pbf" },
    "be": { "pbf_file": "berlin-latest.osm.pbf" },
    "mv": { "pbf_file": "mecklenburg-vorpommern-latest.osm.pbf" }
}

def apply_corrections(alkis_df, corrections_file, state):
    """
    Applies corrections from a JSON file to the ALKIS dataframe.
    """
    # Initialize correction columns if they don't exist
    if 'correction_type' not in alkis_df.columns:
        alkis_df['correction_type'] = None
        alkis_df['correction_type'] = alkis_df['correction_type'].astype('object')
    if 'correction_comment' not in alkis_df.columns:
        alkis_df['correction_comment'] = None
        alkis_df['correction_comment'] = alkis_df['correction_comment'].astype('object')
    if 'original_street' not in alkis_df.columns:
        alkis_df['original_street'] = None
        alkis_df['original_street'] = alkis_df['original_street'].astype('object')
    if 'original_housenumber' not in alkis_df.columns:
        alkis_df['original_housenumber'] = None
        alkis_df['original_housenumber'] = alkis_df['original_housenumber'].astype('object')
    if 'official_report' not in alkis_df.columns:
        alkis_df['official_report'] = False
        alkis_df['official_report'] = alkis_df['official_report'].astype('bool')

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
        replace_in_street = corr.get("replace_in_street")
        tag = corr.get("tag", corr.get("type", "corrected")) # Allow custom tag or type from JSON, default to "corrected"
        comment = corr.get("comment", None)
        official_report = corr.get("official_report", False)
        if official_report:
             official_report = True
        
        # Check for ID-based correction first
        if "alkis_id" in corr:
            mask = alkis_df['alkis_id'] == corr["alkis_id"]
            
            if not mask.any():
                continue
                
            rows_affected = mask.sum()
            count += rows_affected
            
            # Save original values if needed (for first time correction)
            mask_orig_street_nan = mask & alkis_df['original_street'].isna()
            if mask_orig_street_nan.any():
                 alkis_df.loc[mask_orig_street_nan, 'original_street'] = alkis_df.loc[mask_orig_street_nan, 'street']

            mask_orig_hnr_nan = mask & alkis_df['original_housenumber'].isna()
            if mask_orig_hnr_nan.any():
                 alkis_df.loc[mask_orig_hnr_nan, 'original_housenumber'] = alkis_df.loc[mask_orig_hnr_nan, 'housenumber']
            
            # Apply changes
            if official_report:
                 alkis_df.loc[mask, 'official_report'] = True

            if corr.get("ignore"):
                alkis_df.loc[mask, 'correction_type'] = 'ignored'
                if comment:
                    alkis_df.loc[mask, 'correction_comment'] = comment
            elif corr.get("already_mapped"):
                 alkis_df.loc[mask, 'correction_type'] = 'already_mapped'
                 if comment:
                    alkis_df.loc[mask, 'correction_comment'] = comment
            else:
                if "to_street" in corr:
                    alkis_df.loc[mask, 'street'] = corr["to_street"]
                    alkis_df.loc[mask, 'correction_type'] = tag
                    if comment:
                        alkis_df.loc[mask, 'correction_comment'] = comment
                    
                if "to_housenumber" in corr:
                    alkis_df.loc[mask, 'housenumber'] = corr["to_housenumber"]
                    alkis_df.loc[mask, 'correction_type'] = tag
                    if comment:
                        alkis_df.loc[mask, 'correction_comment'] = comment
                    
        elif from_street:
            mask = alkis_df['street'] == from_street
            
            if "city" in corr:
                # map city to district if column exists
                if 'district' in alkis_df.columns:
                     mask &= (alkis_df['district'] == corr["city"])
            
            if "from_housenumber" in corr:
                 mask &= (alkis_df['housenumber'] == corr["from_housenumber"])
            
            # Radius-based filtering
            if "reference_alkis_id" in corr:
                 ref_id = corr["reference_alkis_id"]
                 ref_row = alkis_df[alkis_df['alkis_id'] == ref_id]
                 if not ref_row.empty:
                     ref_geom = ref_row.iloc[0].geometry
                     # Calculate distance to reference point for ALL candidates
                     candidate_indices = alkis_df[mask].index
                     if not candidate_indices.empty:
                         candidates = alkis_df.loc[candidate_indices]
                         max_dist = corr.get("max_distance", 2000)
                         if candidates.crs and candidates.crs.is_geographic:
                             dists = candidates.geometry.distance(ref_geom)
                             mask &= (dists < (max_dist / 111320)) # degrees
                         else:
                             dists = candidates.geometry.distance(ref_geom)
                             mask &= (dists <= max_dist) # meters

            if not mask.any():
                continue
                
            rows_affected = mask.sum()
            
            # Save original street for affected rows where it's not set yet
            mask_no_orig = mask & alkis_df['original_street'].isna()
            if mask_no_orig.any():
                 alkis_df.loc[mask_no_orig, 'original_street'] = alkis_df.loc[mask_no_orig, 'street']

            mask_orig_hnr_nan = mask & alkis_df['original_housenumber'].isna()
            if mask_orig_hnr_nan.any():
                 alkis_df.loc[mask_orig_hnr_nan, 'original_housenumber'] = alkis_df.loc[mask_orig_hnr_nan, 'housenumber']
            
            count += rows_affected
            
            # Apply changes
            if official_report:
                 alkis_df.loc[mask, 'official_report'] = True

            if corr.get("ignore"):
                alkis_df.loc[mask, 'correction_type'] = 'ignored'
                if comment:
                    alkis_df.loc[mask, 'correction_comment'] = comment
            elif corr.get("already_mapped"):
                 alkis_df.loc[mask, 'correction_type'] = 'already_mapped'
                 if comment:
                    alkis_df.loc[mask, 'correction_comment'] = comment
            else:
                if "to_street" in corr:
                    alkis_df.loc[mask, 'street'] = corr["to_street"]
                    alkis_df.loc[mask, 'correction_type'] = tag
                    if comment:
                        alkis_df.loc[mask, 'correction_comment'] = comment
                
                if "to_housenumber" in corr:
                    alkis_df.loc[mask, 'housenumber'] = corr["to_housenumber"]
                    alkis_df.loc[mask, 'correction_type'] = tag
                    if comment:
                        alkis_df.loc[mask, 'correction_comment'] = comment

        elif replace_in_street:
            replace_with = corr.get("replace_with", "")
            mask = alkis_df['street'].astype(str).str.contains(replace_in_street, regex=False)
            
            if "city" in corr:
                if 'district' in alkis_df.columns:
                     mask &= (alkis_df['district'] == corr["city"])
            
            if mask.any():
                rows_affected = mask.sum()
                
                # Save original street
                mask_no_orig = mask & alkis_df['original_street'].isna()
                if mask_no_orig.any():
                     alkis_df.loc[mask_no_orig, 'original_street'] = alkis_df.loc[mask_no_orig, 'street']
                
                count += rows_affected
                count += rows_affected
                if official_report:
                     alkis_df.loc[mask, 'official_report'] = True

                if corr.get("ignore"):
                     alkis_df.loc[mask, 'correction_type'] = 'ignored'
                     if comment:
                         alkis_df.loc[mask, 'correction_comment'] = comment
                elif corr.get("already_mapped"):
                     alkis_df.loc[mask, 'correction_type'] = 'already_mapped'
                     if comment:
                         alkis_df.loc[mask, 'correction_comment'] = comment
                else: 
                     alkis_df.loc[mask, 'street'] = alkis_df.loc[mask, 'street'].str.replace(replace_in_street, replace_with, regex=False)
                     alkis_df.loc[mask, 'correction_type'] = tag
                     if comment:
                        alkis_df.loc[mask, 'correction_comment'] = comment

    print(f"[{state}] Applied corrections to {count} rows.")
    return alkis_df

def split_complex_house_numbers(df):
    """
    Splits house numbers with separators (comma, semicolon) into individual rows.
    """
    if df.empty or 'housenumber' not in df.columns:
        return df
        
    # Regex to find separators: , ;
    mask_complex = df['housenumber'].astype(str).str.contains(r'[,;]', regex=True)
    
    if not mask_complex.any():
        return df

    print(f"  Found {mask_complex.sum()} rows with complex house numbers (comma/semicolon) to split.")

    rows_to_split = df[mask_complex]
    clean_rows = df[~mask_complex]
    
    new_data = []
    
    for idx, row in rows_to_split.iterrows():
        hnr = str(row['housenumber'])
        # Replace separators with comma
        hnr_clean = re.sub(r'[;]', ',', hnr)
        parts = [p.strip() for p in hnr_clean.split(',') if p.strip()]
        
        for part in parts:
            new_row = row.copy()
            new_row['housenumber'] = part
            new_data.append(new_row)
            
    if new_data:
        df_split = pd.DataFrame(new_data)
        if isinstance(df, gpd.GeoDataFrame):
             df_split = gpd.GeoDataFrame(df_split, geometry='geometry', crs=df.crs)
        return pd.concat([clean_rows, df_split], ignore_index=True)
        
    return df

def expand_alphanumeric_ranges(df):
    """
    Expands rows with alphanumeric ranges like "11a-c" or "11a-11c".
    """
    if df.empty or 'housenumber' not in df.columns:
        return df

    # Case 1: "11a-c" -> prefix "11", start "a", end "c"
    pattern_short = re.compile(r'^(\d+)([a-zA-Z])\s*-\s*([a-zA-Z])$')
    # Case 2: "11a-11c" -> prefix "11", start "a", end "c"
    pattern_long = re.compile(r'^(\d+)([a-zA-Z])\s*-\s*(\d+)([a-zA-Z])$')
    # Case 3: "11-11c" -> prefix "11", start (implicit), end "c"
    pattern_mixed = re.compile(r'^(\d+)\s*-\s*(\d+)([a-zA-Z])$')

    mask_short = df['housenumber'].astype(str).str.match(pattern_short)
    mask_long = df['housenumber'].astype(str).str.match(pattern_long)
    mask_mixed = df['housenumber'].astype(str).str.match(pattern_mixed)
    
    mask = mask_short | mask_long | mask_mixed
    
    if not mask.any():
        return df
        
    print(f"  Found {mask.sum()} rows with alphanumeric ranges to expand.")
    
    rows_to_expand = df[mask]
    clean_rows = df[~mask]
    
    new_data = []
    
    for idx, row in rows_to_expand.iterrows():
        hnr = str(row['housenumber']).strip()
        
        processed = False

        # Try short pattern
        match = pattern_short.match(hnr)
        if match:
            num = match.group(1)
            start_char = match.group(2)
            end_char = match.group(3)
            
            if ord(start_char) < ord(end_char):
                for i in range(ord(start_char), ord(end_char) + 1):
                    new_row = row.copy()
                    new_row['housenumber'] = f"{num}{chr(i)}"
                    new_data.append(new_row)
                processed = True

        if not processed:
            # Try long pattern
            match = pattern_long.match(hnr)
            if match:
                num1 = match.group(1)
                start_char = match.group(2)
                num2 = match.group(3)
                end_char = match.group(4)
                
                if num1 == num2 and ord(start_char) < ord(end_char):
                     for i in range(ord(start_char), ord(end_char) + 1):
                         new_row = row.copy()
                         new_row['housenumber'] = f"{num1}{chr(i)}"
                         new_data.append(new_row)
                     processed = True

        if not processed:
            # Try mixed pattern
            match = pattern_mixed.match(hnr)
            if match:
                num1 = match.group(1)
                num2 = match.group(2)
                end_char = match.group(3)
                
                if num1 == num2:
                     # Add base number (e.g. 11)
                     new_row = row.copy()
                     new_row['housenumber'] = num1
                     new_data.append(new_row)
                     
                     # Add suffixes (a to end_char)
                     for i in range(ord('a'), ord(end_char) + 1):
                         new_row = row.copy()
                         new_row['housenumber'] = f"{num1}{chr(i)}"
                         new_data.append(new_row)
                     processed = True
        
        # Fallback if regex matched but logic failed
        if not processed:
            new_data.append(row)

    if new_data:
        df_expanded = pd.DataFrame(new_data)
        if isinstance(df, gpd.GeoDataFrame):
             df_expanded = gpd.GeoDataFrame(df_expanded, geometry='geometry', crs=df.crs)
        return pd.concat([clean_rows, df_expanded], ignore_index=True)

    return df


def expand_aachen_addresses(df):
    if df.empty or 'city' not in df.columns or 'housenumber' not in df.columns:
        return df
        
    # Filter for Aachen
    mask_city = df['city'] == 'Aachen'
    if not mask_city.any():
        return df
        
    # Regex to find separators: / , ;
    mask_complex = df['housenumber'].astype(str).str.contains(r'[/,;]', regex=True)
    
    mask = mask_city & mask_complex
    
    if not mask.any():
        return df

    rows_to_split = df[mask]
    clean_rows = df[~mask]
    
    new_data = []
    
    for idx, row in rows_to_split.iterrows():
        hnr = str(row['housenumber'])
        # Replace all separators with one common separator (comma)
        hnr_clean = re.sub(r'[/;]', ',', hnr)
        parts = [p.strip() for p in hnr_clean.split(',') if p.strip()]
        
        for part in parts:
            new_row = row.copy()
            new_row['housenumber'] = part
            new_data.append(new_row)
            
    if new_data:
        df_split = pd.DataFrame(new_data)
        if isinstance(df, gpd.GeoDataFrame):
             df_split = gpd.GeoDataFrame(df_split, geometry='geometry', crs=df.crs)
        return pd.concat([clean_rows, df_split], ignore_index=True)
        
    return df

def expand_address_ranges(df):
    """
    Expands rows with address ranges (e.g., "7-13") into individual rows 
    (7, 9, 11, 13).
    """
    if df.empty or 'housenumber' not in df.columns:
        return df

    # Regex for "123 - 456" or "12-14"
    # Capture groups: 1=Start, 2=End
    range_pattern = re.compile(r'^(\d+)\s*-\s*(\d+)$')

    mask = df['housenumber'].astype(str).str.contains('-', na=False)
    
    if not mask.any():
        return df
    
    print(f"  Found {mask.sum()} rows with ranges to potentially expand.")
    
    df_ranges = df[mask].copy()
    df_clean = df[~mask]

    new_rows = []
    
    for idx, row in df_ranges.iterrows():
        hnr = str(row['housenumber']).strip()
        match = range_pattern.match(hnr)
        
        if match:
            start = int(match.group(1))
            end = int(match.group(2))
                            
            # Determine step
            # If both even or both odd -> step 2
            # If mixed -> step 1
            if (start % 2) == (end % 2):
                step = 2
            else:
                step = 1
                
            for num in range(start, end + 1, step):
                new_row = row.copy()
                new_row['housenumber'] = str(num)
                new_rows.append(new_row)
        else:
            new_rows.append(row)

    if new_rows:
        df_expanded = pd.DataFrame(new_rows)
        if isinstance(df, gpd.GeoDataFrame):
             df_expanded = gpd.GeoDataFrame(df_expanded, geometry='geometry', crs=df.crs)
             
        return pd.concat([df_clean, df_expanded], ignore_index=True)
    
    return df

def main():
    STATES_LIST = ["nds", "nrw", "rlp", "bb", "hh", "he", "st", "sn", "be", "mv"]
    
    ENABLE_FLEXIBLE_PARSING = True
    
    DATA_DIR = "data"
    SITE_DIR = "site/public/states"

    parser = argparse.ArgumentParser(description="Compare ALKIS and OSM data.")
    parser.add_argument("--adjust-history", action="store_true", help="Adjust historical statistics based on the delta from the current run.")
    parser.add_argument("--force", action="store_true", help="Force comparison even if up-to-date.")
    args = parser.parse_args()
    
    today = datetime.date.today().isoformat()
    
    found_any = False

    for state in STATES_LIST:
        alkis_path = os.path.join(DATA_DIR, state, "alkis.parquet")
        osm_path = os.path.join(DATA_DIR, state, "osm.parquet")
        corrections_file = os.path.join(SITE_DIR, state, f"{state}_alkis_corrections.json")
        history_file = os.path.join(SITE_DIR, state, f"{state}_history.json")
        
        pbf_path = os.path.join(DATA_DIR, state, "osm", STATES[state]["pbf_file"])
        
        if not os.path.exists(alkis_path):
            print(f"[{state}] ALKIS file not found: {alkis_path}. Skipping.")
            continue
        if not os.path.exists(osm_path):
            print(f"[{state}] OSM file not found: {osm_path}. Skipping.")
            continue
            
        # Optimization: Compare PBF timestamp with the latest history entry
        if not args.force and os.path.exists(history_file) and os.path.exists(pbf_path):
            try:
                reader = osmium.io.Reader(pbf_path)
                header_ts = reader.header().get("osmosis_replication_timestamp")
                reader.close()
                
                if header_ts:
                    pbf_date_str = str(header_ts)
                    with open(history_file, 'r') as f:
                        history_store = json.load(f)
                    
                    if "global" in history_store and history_store["global"]:
                        latest_history_date = history_store["global"][-1].get("date")
                        if latest_history_date == pbf_date_str:
                            print(f"[{state}] PBF timestamp ({pbf_date_str}) matches latest history. Skipping comparison.")
                            found_any = True
                            continue
            except Exception as e:
                print(f"[{state}] Error checking PBF timestamp for optimization: {e}")
            
        found_any = True
        print(f"[{state}] Loading data...")
        try:
           alkis = gpd.read_parquet(alkis_path)
           osm = gpd.read_parquet(osm_path)
        except Exception as e:
           print(f"[{state}] Error loading data: {e}")
           continue

        # Apply Generic Corrections
        alkis = apply_corrections(alkis, corrections_file, state)

        # Apply KGV Filter (Brandenburg specific)
        FILTER_KGV = True 
        if FILTER_KGV and state == 'bb':
            # Filter addresses containing "Kleingarten" or starting with "KGV/KGA"
            mask_kgv = alkis['street'].str.contains(r'Kleingarten|KGV|KGA', case=False, regex=True, na=False)
            
            if mask_kgv.any():
                print(f"[{state}] Marking {mask_kgv.sum()} KGV/Kleingarten/KGA addresses as ignored.")                
                mask_apply = mask_kgv & alkis['correction_type'].isna()
                if mask_apply.any():
                    # Save original before ignoring
                    if 'original_street' not in alkis.columns:
                        alkis['original_street'] = None
                    if 'original_housenumber' not in alkis.columns:
                        alkis['original_housenumber'] = None

                    mask_no_orig = mask_apply & alkis['original_street'].isna()
                    if mask_no_orig.any():
                         alkis.loc[mask_no_orig, 'original_street'] = alkis.loc[mask_no_orig, 'street']

                    mask_orig_hnr_nan = mask_apply & alkis['original_housenumber'].isna()
                    if mask_orig_hnr_nan.any():
                         alkis.loc[mask_orig_hnr_nan, 'original_housenumber'] = alkis.loc[mask_orig_hnr_nan, 'housenumber']

                    alkis.loc[mask_apply, 'correction_type'] = 'ignored'
                    alkis.loc[mask_apply, 'correction_comment'] = 'Automatisch ignoriert: Kleingarten'

        # Expand Aachen Addresses
        if state == "nrw":
             alkis = expand_aachen_addresses(alkis)
             osm = expand_aachen_addresses(osm)

        if ENABLE_FLEXIBLE_PARSING:
             print(f"[{state}] Applying flexible OSM parsing...")
             osm = split_complex_house_numbers(osm)
             osm = expand_alphanumeric_ranges(osm)

        # Expand Address Ranges (e.g. 7-13 -> 7, 9, 11, 13)
        print(f"[{state}] Expanding address ranges...")
        alkis = expand_address_ranges(alkis)
        osm = expand_address_ranges(osm)

        # Generate Keys
        print(f"[{state}] Generating keys...")
        # alkis
        alkis['street'] = alkis['street'].fillna("").astype(str)
        alkis['housenumber'] = alkis['housenumber'].fillna("").astype(str)
        alkis['key'] = alkis.apply(lambda row: normalize_key(row['street'], row['housenumber']), axis=1)
        
        # osm
        osm['street'] = osm['street'].fillna("").astype(str)
        osm['housenumber'] = osm['housenumber'].fillna("").astype(str)
        
        # Expand OSM if 'housename' exists
        if 'housename' in osm.columns:
            # Create a copy for the extended key
            mask_has_name = osm['housename'].notna() & (osm['housename'] != "")
            
            if mask_has_name.any():
                print(f"[{state}] Exploding {mask_has_name.sum()} OSM rows with housenames for flexible matching...")
                osm_expanded = osm[mask_has_name].copy()
                
                # Update housenumber to include name for the expanded rows
                # Format: "number, name"
                osm_expanded['housenumber'] = osm_expanded['housenumber'] + ", " + osm_expanded['housename']
                
                # Append to original
                osm = pd.concat([osm, osm_expanded], ignore_index=True)

        osm['key'] = osm.apply(lambda row: normalize_key(row['street'], row['housenumber']), axis=1)

        # Align CRS
        if alkis.crs is not None and osm.crs is not None and not alkis.crs.equals(osm.crs):
            #  print(f"[{state}] Reprojecting OSM from {osm.crs} to {alkis.crs}")
             osm = osm.to_crs(alkis.crs)

        # Matching Logic
        print(f"[{state}] Matching...")
        
        alkis = alkis.reset_index(drop=True)
        alkis['alkis_idx'] = alkis.index
        
        found_indices = set()
        
        # Chunked Matching
        CHUNK_SIZE = 50000
        for i in tqdm.tqdm(range(0, len(alkis), CHUNK_SIZE), desc=f"[{state}] Matching", ascii=True, disable=not sys.stdout.isatty()):
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
        
        # Identify Missing
        missing = alkis[~alkis['found_in_osm']].copy()
        
        # Wrong Street Detection
        print(f"[{state}] Identifying 'wrong_street' candidates for {len(missing)} missing addresses...")
        if len(missing) > 0 and len(osm) > 0:
            try:
                # sjoin_nearest with max_distance
                nn_join = gpd.sjoin_nearest(
                    missing[['geometry', 'alkis_idx', 'street', 'housenumber']], 
                    osm[['geometry', 'street', 'housenumber']], 
                    how='left',
                    distance_col='dist_nn',
                    max_distance=20.0
                )
                
                # Handle duplicates (nearest first)
                nn_join = nn_join[~nn_join.index.duplicated(keep='first')]
                
                # Filter for matching house numbers but differing street names
                def is_wrong_street(row):
                    if pd.isna(row['street_right']):
                        return False
                    s_alkis = normalize_street(row['street_left'])
                    s_osm = normalize_street(row['street_right'])
                    h_alkis = str(row['housenumber_left']).lower().strip()
                    h_osm = str(row['housenumber_right']).lower().strip()
                    
                    return (s_alkis != s_osm) and (h_alkis == h_osm)
                
                mask_wrong_street_join = nn_join.apply(is_wrong_street, axis=1)
                wrong_street_indices = nn_join[mask_wrong_street_join]['alkis_idx'].values
                
                print(f"[{state}] Found {len(wrong_street_indices)} 'wrong_street' cases.")
                
                # Apply 'wrong_street' correction type to alkis
                mask_apply = alkis['alkis_idx'].isin(wrong_street_indices)
                alkis.loc[mask_apply, 'correction_type'] = 'wrong_street'
                
                # Create a mapping from alkis_idx to the found OSM street
                osm_street_map = nn_join[mask_wrong_street_join].set_index('alkis_idx')['street_right'].to_dict()
                
                # Vectorized map approach for speed using alkis_idx
                alkis['osm_street'] = alkis['alkis_idx'].map(osm_street_map)

            except Exception as e:
                print(f"[{state}] Error during wrong_street detection: {e}")
        
        missing = alkis[~alkis['found_in_osm']]
        
        # Export preparation
        if alkis.crs != "EPSG:4326":
            alkis = alkis.to_crs(epsg=4326)
        state_total = len(alkis)
        
        # Identify Missing (global)
        state_missing_df = alkis[~alkis['found_in_osm']]
        if 'correction_type' in alkis.columns:
            state_missing_df = state_missing_df[~state_missing_df['correction_type'].isin(['ignored', 'already_mapped'])]
        state_missing = len(state_missing_df)
        
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
             reader = osmium.io.Reader(pbf_path)
             header_ts = reader.header().get("osmosis_replication_timestamp")
             reader.close()
             if header_ts:
                 export_date = str(header_ts)
        except Exception as e:
            print(f"[{state}] Warning: Could not read PBF timestamp: {e}")

        # print(f"Export date: {export_date}")
        districts = alkis['district'].unique()
        
        district_list = []
        
        for district in tqdm.tqdm(districts, desc=f"[{state}] Processing Districts", ascii=True, disable=not sys.stdout.isatty()):
            district_alkis = alkis[alkis['district'] == district]
            # Exclude ignored and already_mapped addresses from missing
            district_missing = district_alkis[~district_alkis['found_in_osm']]
            if 'correction_type' in district_alkis.columns:
                 district_missing = district_missing[~district_missing['correction_type'].isin(['ignored', 'already_mapped'])]
            
            d_total = len(district_alkis)
            d_missing = len(district_missing)
            d_coverage = round((d_total - d_missing) / d_total * 100, 1) if d_total > 0 else 100.0
            
            unique_name = f"{district}" 
            
            clean_name = "".join([c if c.isalnum() else "_" for c in str(district)])
            out_filename = f"{clean_name}.geojson" 
            
            # Count corrections
            d_corrections = 0
            if 'correction_type' in district_alkis.columns:
                 # Count corrections that result in a match or are ignored or already_mapped
                 d_corrections = int(((district_alkis['correction_type'].notna() & district_alkis['found_in_osm']) | district_alkis['correction_type'].isin(['ignored', 'already_mapped'])).sum())

            d_stats = {
                "name": unique_name,
                "state": state,
                "district": district,
                "total": d_total,
                "missing": d_missing,
                "coverage": d_coverage,
                "corrections": int(d_corrections),
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
                "coverage": d_coverage,
                "corrections": int(d_corrections)
            }
            
            if hist_key not in history_store["districts"]:
                history_store["districts"][hist_key] = []
            
            d_hist = history_store["districts"][hist_key]
            
            # History Adjustment (District)
            if d_hist:
                ref_entry = d_hist[-1]
                
                # Calculate deltas
                delta_total = d_total - ref_entry["total"]
                delta_missing = d_missing - ref_entry["missing"]
                delta_corrections = d_corrections - ref_entry.get("corrections", 0)
                
                #Correction changes should always propagate to past
                if delta_corrections != 0:
                     print(f"      [Auto-Adjust] District '{district}': {delta_corrections} correction change propagated.")
                     for h_entry in d_hist:
                         # 1. Update corrections count
                         current_corrs = h_entry.get("corrections", 0)
                         # Set original_corrections if not present (Snapshot logic)
                         if "original_corrections" not in h_entry: h_entry["original_corrections"] = current_corrs
                         if "corrections" not in h_entry: h_entry["corrections"] = current_corrs

                         h_entry["corrections"] = current_corrs + delta_corrections
                         
                         # 2. Update Missing (symmetric to corrections)
                         h_entry["missing"] -= delta_corrections
                         if h_entry["missing"] < 0: h_entry["missing"] = 0
                         
                         # Recalculate Coverage
                         ht = h_entry["total"]
                         hm = h_entry["missing"]
                         h_entry["coverage"] = round((ht - hm) / ht * 100, 1) if ht > 0 else 100.0

                # Manual Flag
                # Adjusts Total and Missing based on logic shifts (processing changes).
                if args.adjust_history:
                    if ref_entry["date"] != export_date:
                        print(f"      [Info] Adjusting against previous date ({ref_entry['date']}). Today's progress will be flattened to 0 relative to history.")
                    
                    # subtract delta_corrections from delta_missing logic check because we already applied it above.
                    residual_missing = delta_missing + delta_corrections 
                    
                    if delta_total != 0 or residual_missing != 0:
                        print(f"      [Adjust] District '{district}': Delta Total={delta_total}, Residual Delta Missing={residual_missing}")
                        for h_entry in d_hist:
                             h_entry["total"] += delta_total
                             h_entry["missing"] += residual_missing
                             
                             ht = h_entry["total"]
                             hm = h_entry["missing"]
                             h_entry["coverage"] = round((ht - hm) / ht * 100, 1) if ht > 0 else 100.0



            if not d_hist or d_hist[-1]["date"] != export_date:
                d_hist.append(d_hist_entry)
            else:
                d_hist[-1] = d_hist_entry
                
            # GeoJSON Export
            matches_corrected = pd.DataFrame()
            if 'correction_type' in district_alkis.columns:
                # Corrected matches OR explicitly ignored (exclude wrong_street, which are essentially 'missing')
                matches_corrected = district_alkis[
                    (district_alkis['found_in_osm'] & district_alkis['correction_type'].notna()) |
                    (district_alkis['correction_type'] == 'ignored')
                ].copy()
                
                missing_export = district_missing.copy()
                missing_export['matched'] = False
                matches_corrected['matched'] = True
                
                combined_export = pd.concat([missing_export, matches_corrected], ignore_index=True)
            else:
                missing_export = district_missing.copy()
                missing_export['matched'] = False
                combined_export = missing_export
            
            cols_to_export = ['street', 'housenumber', 'geometry', 'matched']
            if 'correction_type' in combined_export.columns:
                cols_to_export.append('correction_type')
            if 'correction_comment' in combined_export.columns:
                cols_to_export.append('correction_comment')
            if 'original_street' in combined_export.columns:
                 cols_to_export.append('original_street')
            if 'original_housenumber' in combined_export.columns:
                 cols_to_export.append('original_housenumber')
            if 'alkis_id' in combined_export.columns:
                 cols_to_export.append('alkis_id')
            if 'official_report' in combined_export.columns:
                 cols_to_export.append('official_report')
            if 'osm_street' in combined_export.columns:
                 cols_to_export.append('osm_street')
                
            final_export = combined_export[cols_to_export]
            
            out_path = os.path.join(districts_dir, out_filename)
            if len(final_export) > 0:
                final_export.to_file(out_path, driver="GeoJSON")
            else:
                 with open(out_path, 'w') as f:
                    json.dump({"type": "FeatureCollection", "features": []}, f)

        # State Global Stats
        global_coverage = round((state_total - state_missing) / state_total * 100, 2) if state_total > 0 else 100.0
        
        global_corrections = 0
        if 'correction_type' in alkis.columns:
             # Count corrections that result in a match or are ignored or already_mapped
             global_corrections = int(((alkis['correction_type'].notna() & alkis['found_in_osm']) | alkis['correction_type'].isin(['ignored', 'already_mapped'])).sum())

        g_entry = {
             "date": export_date,
             "alkis": state_total,
             "osm": state_osm_count,
             "missing": state_missing,
             "coverage": global_coverage,
             "corrections": int(global_corrections)
        }
        
        if not history_store["global"] or history_store["global"][-1]["date"] != export_date:
            # History Adjustment (Global)
            if history_store["global"]:
                 ref_entry = history_store["global"][-1]
                 delta_total = state_total - ref_entry["alkis"]
                 delta_missing = state_missing - ref_entry["missing"]
                 delta_corrections = global_corrections - ref_entry.get("corrections", 0)
                 
                 # Unconditional: Propagate Correction Changes
                 if delta_corrections != 0:
                     print(f"[{state}] Correction Propagation: {delta_corrections} changes applied.")
                     for h_entry in history_store["global"]:
                         current_corrs = h_entry.get("corrections", 0)
                         # Set snapshot if missing
                         if "original_corrections" not in h_entry: h_entry["original_corrections"] = current_corrs
                         if "corrections" not in h_entry: h_entry["corrections"] = current_corrs
                         
                         h_entry["corrections"] = current_corrs + delta_corrections
                         
                         h_entry["missing"] -= delta_corrections
                         if h_entry["missing"] < 0: h_entry["missing"] = 0
                         
                         ht = h_entry["alkis"]
                         hm = h_entry["missing"]
                         h_entry["coverage"] = round((ht - hm) / ht * 100, 2) if ht > 0 else 100.0

                 # Manual Flag: Propagate Residual Logic Changes (Total/Missing)
                 if args.adjust_history:
                     if ref_entry["date"] != export_date:
                        print(f"      [Info] Global adjust against previous date ({ref_entry['date']}).")

                     residual_missing = delta_missing + delta_corrections
                     
                     if delta_total != 0 or residual_missing != 0:
                         print(f"[{state}] Global Adjustment (Flag): Delta Total={delta_total}, Residual Delta Missing={residual_missing}")
                         for h_entry in history_store["global"]:
                             h_entry["alkis"] += delta_total
                             h_entry["missing"] += residual_missing
                             
                             ht = h_entry["alkis"]
                             hm = h_entry["missing"]
                             h_entry["coverage"] = round((ht - hm) / ht * 100, 2) if ht > 0 else 100.0

            history_store["global"].append(g_entry)
        else:
            # Entry exists for today (we are overwriting it).
            # If adjusting, we still compare against the last entry in the list (which is today's entry before overwrite)
            # This allows correcting a run from earlier today.
            
            if args.adjust_history and history_store["global"]:
                 ref_entry = history_store["global"][-1]
                 delta_total = state_total - ref_entry["alkis"]
                 delta_missing = state_missing - ref_entry["missing"]
                 delta_corrections = global_corrections - ref_entry.get("corrections", 0)

                 if delta_total != 0 or delta_missing != 0:
                     print(f"[{state}] Global Adjustment (Overwrite): Delta Total={delta_total}, Delta Missing={delta_missing}, Delta Corrections={delta_corrections}")
                     for h_entry in history_store["global"]: 
                         h_entry["alkis"] += delta_total
                         h_entry["missing"] += delta_missing
                         
                         if "corrections" in h_entry:
                             h_entry["corrections"] += delta_corrections
                         else:
                             h_entry["corrections"] = max(0, delta_corrections)

                         ht = h_entry["alkis"]
                         hm = h_entry["missing"]
                         h_entry["coverage"] = round((ht - hm) / ht * 100, 2) if ht > 0 else 100.0

            history_store["global"][-1] = g_entry
            
        # Write State Files
        with open(history_file, 'w') as f:
            json.dump(history_store, f, indent=2)
            
        district_list.sort(key=lambda x: x['name'])
        with open(districts_file, 'w') as f:
            json.dump(district_list, f, indent=2)

        print(f"Successfully processed {state}!")

    if not found_any:
        print("No data processed.")
    else:
        print("Comparison complete.")

if __name__ == "__main__":
    main()
