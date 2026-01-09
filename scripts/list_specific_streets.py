import pandas as pd
import os
import sys

# Path to the parquet file (relative to project root)
FILE_PATH = os.path.join("data", "nds", "osm.parquet")
SEARCH_TERM = "Gerhard-Hauptmann"

def main():
    try:
        if not os.path.exists(FILE_PATH):
             print(f"Error: File not found at {FILE_PATH}")
             return

        # Load the parquet file
        df = pd.read_parquet(FILE_PATH)
        
        # Ensure 'street' column exists
        if 'street' not in df.columns:
            print(f"Error: 'street' column not found in {FILE_PATH}")
            print(f"Available columns: {df.columns.tolist()}")
            return

        # Filter streets containing SEARCH_TERM
        # Handle possible NaN values in 'street' column
        mask = df['street'].astype(str).str.contains(SEARCH_TERM, case=False, na=False)
        matching_streets = df[mask]
        
        # Get unique street names with district
        cols_to_use = ['street']
        if 'district' in df.columns:
            cols_to_use.append('district')
            
        unique_results = matching_streets[cols_to_use].drop_duplicates().sort_values(by=cols_to_use)
        
        # Print results
        print(f"Found {len(unique_results)} unique items containing '{SEARCH_TERM}':")
        for _, row in unique_results.iterrows():
            if 'district' in row:
                print(f"{row['street']} ({row['district']})")
            else:
                print(f"{row['street']}")
                
        print(f"Total number of addresses: {len(matching_streets)}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
