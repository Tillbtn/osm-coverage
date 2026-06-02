#!/usr/bin/env python3
import json
import glob
import sys
import os
import argparse

def merge_history(file_path, old_name, new_name):
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        return
        
    with open(file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print(f"Error reading {file_path}")
            return
        
    if "districts" not in data:
        return
        
    districts = data["districts"]
    if old_name not in districts:
        print(f"Notice: '{old_name}' not found in {file_path}")
        return
        
    print(f"Found '{old_name}' in {file_path}, merging into '{new_name}'...")
    
    old_history = districts.pop(old_name)
    new_history = districts.get(new_name, [])
    
    # Merge lists and deduplicate by date
    history_by_date = {}
    
    # Add old entries first
    for entry in old_history:
        if "date" in entry:
            history_by_date[entry["date"]] = entry
            
    # Add new entries (overwriting old ones if they share the exact same date)
    for entry in new_history:
        if "date" in entry:
            history_by_date[entry["date"]] = entry
            
    # Reconstruct sorted list by date
    sorted_history = [history_by_date[date] for date in sorted(history_by_date.keys())]
    
    districts[new_name] = sorted_history
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Successfully merged '{old_name}' into '{new_name}' in {file_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge history of a renamed district across history JSON files.")
    parser.add_argument("--old", required=True, help="Old district name (e.g., 'Aachen, Städteregion')")
    parser.add_argument("--new", required=True, help="New district name (e.g., 'Städteregion Aachen')")
    parser.add_argument("--file", help="Specific JSON file to modify. If not provided, searches all history files in site/public/.")
    
    args = parser.parse_args()
    
    if args.file:
        files = [args.file]
    else:
        # Automatically find all history JSON files in site/public/
        base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site", "public")
        files = glob.glob(os.path.join(base_dir, "**", "*history.json"), recursive=True)
            
    if not files:
        print("No history files found.")
        sys.exit(0)
    old_name = args.old.encode('utf-8').decode('unicode_escape')
    new_name = args.new.encode('utf-8').decode('unicode_escape')
    
    for f in files:
        merge_history(f, old_name, new_name)
