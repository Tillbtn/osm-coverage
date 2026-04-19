
import os
import pandas as pd
import glob
import geopandas as gpd
import argparse

def check_duplicates(state, directory):
    print(f"--- Analyzing duplicates for {state.upper()} in {directory} ---")
    
    if state.lower() == 'rlp':
        csv_path = os.path.join(directory, "HAUSKOORDINATEN_RP", "HAUSKOORDINATEN_RP_hk.csv")
        if not os.path.exists(csv_path):
            print(f"Error: {csv_path} not found.")
            return
        df = pd.read_csv(csv_path, sep=';', dtype=str, usecols=['kreis', 'gmd', 'gmdschl', 'kreisschl'])
    
    elif state.lower() in ['sn', 'he']:
        files = glob.glob(os.path.join(directory, "*.csv")) + glob.glob(os.path.join(directory, "*.txt"))
        if not files:
            print(f"Error: No CSV/TXT files found in {directory}.")
            return
        # Assume same structure for SN/HE
        dfs = []
        for f in files:
            dfs.append(pd.read_csv(f, sep=';', dtype=str, usecols=['kreis', 'gmd', 'gmdschl', 'kreisschl'], on_bad_lines='skip'))
        df = pd.concat(dfs)
        
    elif state.lower() == 'bb':
        gpkg_path = os.path.join(directory, "adressen-bb.gpkg")
        if not os.path.exists(gpkg_path):
            print(f"Error: {gpkg_path} not found.")
            return
        # We try to read all columns to see what's available
        try:
            gdf = gpd.read_file(gpkg_path, layer='adressen-bb', engine='pyogrio', rows=1000) # Sample first 1000
            print(f"Available columns in BB: {gdf.columns.tolist()}")
            # Re-read specific columns if possible, fallback to what we find
            cols = [c for c in ['kreis', 'gmd', 'landkreis', 'gmdschl', 'kreisschl'] if c in gdf.columns or c.lower() in [gc.lower() for gc in gdf.columns]]
            df = gpd.read_file(gpkg_path, layer='adressen-bb', engine='pyogrio', columns=cols)
            df.columns = df.columns.str.lower()
        except Exception as e:
            print(f"Error reading BB GPKG: {e}")
            return
            
    else:
        print(f"State {state} not specifically handled in this script yet.")
        return

    # Standardize columns for analysis
    if 'gmd' not in df.columns:
        print("Error: 'gmd' column (municipality name) not found.")
        return
        
    district_col = 'kreis' if 'kreis' in df.columns else ('landkreis' if 'landkreis' in df.columns else None)
    code_col = 'gmdschl' if 'gmdschl' in df.columns else None

    # Drop duplicates of (municipality, district/code) to see unique entities
    subset = ['gmd']
    if district_col: subset.append(district_col)
    if code_col: subset.append(code_col)
    
    municipalities = df[subset].drop_duplicates()

    # Find duplicate names (gmd)
    duplicates = municipalities[municipalities.duplicated(subset=['gmd'], keep=False)].sort_values('gmd')

    if duplicates.empty:
        print(f"No duplicate municipality names found in {state.upper()}.")
    else:
        print(f"Found {duplicates['gmd'].nunique()} municipality names that exist in multiple districts/with different codes:")
        print(duplicates.to_string(index=False))
        
        print("\nSummary of collisions:")
        summary = duplicates.groupby('gmd').size().reset_index(name='count').sort_values('count', ascending=False)
        print(summary[summary['count'] > 1].head(10).to_string(index=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="List duplicate municipality names in ALKIS data.")
    parser.add_argument("state", help="State code (rlp, sn, he, bb)")
    parser.add_argument("--dir", help="Directory containing ALKIS data (default: data/<state>/alkis)")
    
    args = parser.parse_args()
    
    data_dir = args.dir if args.dir else f"data/{args.state.lower()}/alkis"
    check_duplicates(args.state, data_dir)
