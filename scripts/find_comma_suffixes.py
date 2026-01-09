import pandas as pd
import os
import sys

# Path to the parquet file (relative to project root)
FILE_PATH = os.path.join("data", "nds", "alkis.parquet")

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
            return

        # Filter streets that contain a comma followed by non-digits only
        # regex=True is default for contains, but explicit is better
        # Pattern: comma, anything, end of string. 
        # But we need to ensure "no new number".
        # So we look for a comma, then any character EXCEPT digits, until the end.
        pattern = r',[^0-9]*$'
        
        mask = df['street'].astype(str).str.contains(pattern, regex=True, na=False)
        matching_streets_df = df[mask]
        
        # Get unique street names
        unique_streets = matching_streets_df['street'].unique()
        unique_streets.sort()
        
        print(f"Found {len(unique_streets)} unique streets ending with comma and text (no numbers):")
        
        # also extracting just the suffix might be interesting?
        # But user asked to list the streets.
        
        for street in unique_streets:
            # Maybe show the suffix?
            try:
                # split by last comma
                parts = street.rsplit(',', 1)
                if len(parts) > 1:
                    suffix = parts[1].strip()
                    # Just printing the street for now as requested
                    print(f"{street}")
            except:
                print(street)
                
        print(f"\nTotal Matching Rows: {len(matching_streets_df)}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
