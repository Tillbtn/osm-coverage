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

def normalize_key(street, hnr):
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
    
    h = str(hnr).lower().replace(" ", "").replace(",", "")
    return f"{s}{h}"

STATES = {
    "nds": { "pbf_file": "niedersachsen-latest.osm.pbf" },
    "nrw": { "pbf_file": "nordrhein-westfalen-latest.osm.pbf" },
    "rlp": { "pbf_file": "rheinland-pfalz-latest.osm.pbf" },
    "bb": { "pbf_file": "brandenburg-latest.osm.pbf" },
    "hh": { "pbf_file": "hamburg-latest.osm.pbf" },
    "he": { "pbf_file": "hessen-latest.osm.pbf" },
    "st": { "pbf_file": "sachsen-anhalt-latest.osm.pbf" }
}


def apply_corrections(alkis_df, corrections_file, state):
    """
    Applies corrections from a JSON file to the ALKIS dataframe.
    """
    # Initialize correction columns if they don't exist
    if 'correction_type' not in alkis_df.columns:
        alkis_df['correction_type'] = pd.NA
        alkis_df['correction_type'] = alkis_df['correction_type'].astype('object')
    if 'correction_comment' not in alkis_df.columns:
        alkis_df['correction_comment'] = pd.NA
        alkis_df['correction_comment'] = alkis_df['correction_comment'].astype('object')
    if 'original_street' not in alkis_df.columns:
        alkis_df['original_street'] = pd.NA
        alkis_df['original_street'] = alkis_df['original_street'].astype('object')
    if 'original_housenumber' not in alkis_df.columns:
        alkis_df['original_housenumber'] = pd.NA
        alkis_df['original_housenumber'] = alkis_df['original_housenumber'].astype('object')

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
        tag = corr.get("tag", "corrected") # Allow custom tag from JSON, default to "corrected"
        comment = corr.get("comment", None)
        
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
            if corr.get("ignore"):
                alkis_df.loc[mask, 'correction_type'] = 'ignored'
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
                         if candidates.crs and candidates.crs.is_geographic:
                             dists = candidates.geometry.distance(ref_geom)
                             mask &= (dists < 0.02) # degrees
                         else:
                             dists = candidates.geometry.distance(ref_geom)
                             mask &= (dists <= 2000) # meters

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
            if corr.get("ignore"):
                alkis_df.loc[mask, 'correction_type'] = 'ignored'
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
                if corr.get("ignore"):
                     alkis_df.loc[mask, 'correction_type'] = 'ignored'
                     if comment:
                         alkis_df.loc[mask, 'correction_comment'] = comment
                else: 
                     alkis_df.loc[mask, 'street'] = alkis_df.loc[mask, 'street'].str.replace(replace_in_street, replace_with, regex=False)
                     alkis_df.loc[mask, 'correction_type'] = tag
                     if comment:
                        alkis_df.loc[mask, 'correction_comment'] = comment

    print(f"[{state}] Applied corrections to {count} rows.")
    return alkis_df

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
    # STATES_LIST = ["nds", "nrw", "rlp", "bb", "hh", "st", "he", "mv"]
    STATES_LIST = ["nds", "nrw", "rlp", "bb", "hh", "st"]
    
    DATA_DIR = "data"
    SITE_DIR = "site/public/states"

    parser = argparse.ArgumentParser(description="Compare ALKIS and OSM data.")
    parser.add_argument("--adjust-history", action="store_true", help="Adjust historical statistics based on the delta from the current run.")
    args = parser.parse_args()
    
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

        # Expand Aachen Addresses
        if state == "nrw":
             alkis = expand_aachen_addresses(alkis)
             osm = expand_aachen_addresses(osm)

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
            # Exclude ignored addresses from missing
            district_missing = district_alkis[~district_alkis['found_in_osm']]
            if 'correction_type' in district_alkis.columns:
                 district_missing = district_missing[district_missing['correction_type'] != 'ignored']
            
            d_total = len(district_alkis)
            d_missing = len(district_missing)
            d_coverage = round((d_total - d_missing) / d_total * 100, 1) if d_total > 0 else 100.0
            
            unique_name = f"{district}" 
            
            clean_name = "".join([c if c.isalnum() else "_" for c in str(district)])
            out_filename = f"{clean_name}.geojson" 
            
            # Count corrections
            d_corrections = 0
            if 'correction_type' in district_alkis.columns:
                 # Count corrections that result in a match or are ignored
                 d_corrections = int(((district_alkis['correction_type'].notna() & district_alkis['found_in_osm']) | (district_alkis['correction_type'] == 'ignored')).sum())

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
                matches_corrected = district_alkis[
                    (district_alkis['found_in_osm'] & district_alkis['correction_type'].notna()) |
                    (district_alkis['correction_type'] == 'ignored')
                ].copy()
            matches_corrected['matched'] = True
            
            # Combine missing with corrected matches
            missing_export = district_missing.copy()
            missing_export['matched'] = False
            
            combined_export = pd.concat([missing_export, matches_corrected], ignore_index=True)
            
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
             # Count corrections that result in a match or are ignored
             global_corrections = int(((alkis['correction_type'].notna() & alkis['found_in_osm']) | (alkis['correction_type'] == 'ignored')).sum())

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

    if not found_any:
        print("No data processed.")
    else:
        print("Comparison complete.")

if __name__ == "__main__":
    main()
