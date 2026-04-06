import os
import json
import argparse
import geopandas as gpd
import pandas as pd
import osmium
from shapely import wkb

class DistrictHandler(osmium.SimpleHandler):
    def __init__(self, admin_levels=['10']):
        super(DistrictHandler, self).__init__()
        self.boundaries = []
        self.wkbfab = osmium.geom.WKBFactory()
        self.admin_levels = admin_levels

    def area(self, a):
        try:
            if 'boundary' in a.tags and a.tags['boundary'] == 'administrative':
                if a.tags.get('admin_level') in self.admin_levels:
                    wkb_data = self.wkbfab.create_multipolygon(a)
                    name = a.tags.get('name')
                    level = a.tags.get('admin_level')
                    if name:
                        self.boundaries.append({'GEN': name, 'wkb': wkb_data, 'admin_level': level})
        except:
            pass

def extract_osm_boundaries(pbf_path, admin_levels=['10']):
    print(f"Extracting district boundaries from {pbf_path} (levels={admin_levels})...")
    handler = DistrictHandler(admin_levels=admin_levels)
    am = osmium.area.AreaManager()
    
    try:
        reader1 = osmium.io.Reader(pbf_path)
        osmium.apply(reader1, am.first_pass_handler())
        reader1.close()

        reader2 = osmium.io.Reader(pbf_path)
        idx = osmium.index.create_map("sparse_file_array")
        lh = osmium.NodeLocationsForWays(idx)
        lh.ignore_errors()
        osmium.apply(reader2, lh, handler, am.second_pass_handler(handler))
        reader2.close()
    except Exception as e:
        print(f"Error reading OSM PBF: {e}")
        return None
    
    if not handler.boundaries:
        print("No boundaries found in OSM PBF.")
        return None

    df = pd.DataFrame(handler.boundaries)
    df['geometry'] = df['wkb'].apply(lambda x: wkb.loads(x, hex=True))
    gdf = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")
    return gdf

CONFIG = {
    "nds": {
        "type": "file",
        "input": "data/boundaries/nds/verwaltungseinheiten/NDS_Landkreise.shp", # https://ni-lgln-opengeodata.hub.arcgis.com/pages/alkis-verwaltungsgrenzen~6bb4d994aff345e995cf1d252aa9f00b
        "tolerance": 0.005,
    },
    "nrw": {
        "type": "file",
        "input": "data/boundaries/nrw/dvg2_EPSG25832_Shape/dvg2krs_nw.shp", # https://www.opengeodata.nrw.de/produkte/geobasis/vkg/dvg/dvg2/
        "tolerance": 0.005,
    },
    "st": {
        "type": "osm",
        "input": "data/st/osm/sachsen-anhalt-latest.osm.pbf",
        "admin_levels": ['6', '8'],
        "tolerance": 0.0005,
    },
    "he": {
        "type": "file",
        "input": "data/boundaries/he/DigVGr-epsg25832-shp/GEMEINDE_LA.shp", # https://www.gds-srv.hessen.de/atomfeed/DigVGr-epsg25832-shp.zip
        "tolerance": 0.002,
    },
    "bb": {
        "type": "file",
        "input": "data/boundaries/bb/pos_1/GRENZE_170590-5688771_gemeinden.json", # https://geobroker.geobasis-bb.de/gbss.php?MODE=GetProductInformation&PRODUCTID=00fdc3fb-3bc1-4548-bca2-e735fb11c974
        "tolerance": 0.001,
        "force_crs": "EPSG:25833"
    },
    "sn": {
        "type": "file",
        "input": "data/boundaries/sn/vwg20250101_33_sachsen/gem.shp", # https://www.geodaten.sachsen.de/downloadbereich-verwaltungsgrenzen-4344.html
        "tolerance": 0.001,
    },
    "hh": {
        "type": "osm",
        "input": "data/hh/osm/hamburg-latest.osm.pbf",
        "admin_levels": ['10'],
        "tolerance": 0.0005,
    },
    "rlp": {
        "type": "file",
        "input": "data/boundaries/rlp/dlkm_au.gml", # https://geobasis-rlp.de/data/inspire-annexi/current/xml/dlkm_au.zip
        "name_col": "text", 
        "tolerance": 0.001,
        "is_rlp": True
    }
}

def resolve_name_col(gdf, specified_col=None):
    if specified_col and specified_col in gdf.columns:
        return specified_col
    candidates = ["GEN", "GEMEINDE", "GN", "KRS_NAME", "NAM", "NAME", "LANDKREIS", "GEM_NAME", "GMDE_BZ", "text", "ORTSNAME"]
    for c in candidates:
        if c in gdf.columns:
            return c
    return None

def process_state(state, cfg):
    print(f"\n--- Processing {state.upper()} ---", flush=True)
    out_dir = f"site/public/states/{state}"
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"{state}_district_boundaries.geojson")
    
    input_path = cfg["input"]
    if not os.path.exists(input_path):
        print(f"Skipping {state}: Input {input_path} not found.")
        return
        
    gdf = None
    if cfg["type"] == "osm":
        levels = cfg.get("admin_levels", ['10'])
        gdf = extract_osm_boundaries(input_path, admin_levels=levels)
    else:
        print(f"Reading file {input_path}...", flush=True)
        try:
            gdf = gpd.read_file(input_path, engine="pyogrio")
        except Exception as e:
            print(f"Failed to read file: {e}")
            return

    if gdf is None or gdf.empty:
        print(f"No geometry parsed for {state}.")
        return

    # Handle Special RLP Case
    if cfg.get("is_rlp"):
        districts_file = 'site/public/states/rlp/rlp_districts.json'
        if os.path.exists(districts_file):
            with open(districts_file, 'r', encoding='utf-8') as f:
                ddata = json.load(f)
            expected_names = {d['name'] for d in ddata}
            name_c = cfg.get("name_col", "text")
            
            initial = len(gdf)
            if name_c in gdf.columns:
                gdf = gdf[gdf[name_c].isin(expected_names)].copy()
                
            if 'LocalisedCharacterString' in gdf.columns:
                gdf = gdf[gdf['LocalisedCharacterString'].isna() | (gdf['LocalisedCharacterString'] == '')]
                
            print(f"RLP Filter: {initial} down to {len(gdf)}")

    # Resolve Name Column
    found_col = resolve_name_col(gdf, cfg.get("name_col"))
    if found_col and found_col != 'GEN':
        gdf = gdf.rename(columns={found_col: 'GEN'})
    elif not found_col and 'GEN' not in gdf.columns:
        print(f"Warning: No valid name column found in {list(gdf.columns)}")

    # Apply Mappings
    if 'GEN' in gdf.columns:
        if state == 'nds':
            mapping = {
                'Grafschaft Bentheim': 'Grafschaft_Bentheim',
                'Nienburg (Weser)': 'Nienburg',
                'Region Hannover': 'Region_Hannover',
                'Rotenburg (Wümme)': 'Rotenburg_Wümme',
                'Stadt Braunschweig (kreisfrei)': 'Stadt_Braunschweig',
                'Stadt Delmenhorst (kreisfrei)': 'Stadt_Delmenhorst',
                'Stadt Emden (kreisfrei)': 'Stadt_Emden',
                'Stadt Oldenburg (Oldb) (kreisfrei)': 'Stadt_Oldenburg',
                'Stadt Osnabrück (kreisfrei)': 'Stadt_Osnabrück',
                'Stadt Salzgitter (kreisfrei)': 'Stadt_Salzgitter',
                'Stadt Wilhelmshaven (kreisfrei)': 'Stadt_Wilhelmshaven',
                'Stadt Wolfsburg (kreisfrei)': 'Stadt_Wolfsburg'
            }
            gdf['GEN'] = gdf['GEN'].apply(lambda x: mapping.get(x, x))
            
        elif state == 'nrw':
            mapping = {
                'Städteregion Aachen': 'Aachen, Städteregion',
                'Oberbergischer Kreis': 'Oberberg.-Kreis',
                'Rheinisch-Bergischer Kreis': 'Rhein.-Berg.-Kreis',
                'Mülheim a.d. Ruhr': 'Mülheim Ruhr',
            }
            gdf['GEN'] = gdf['GEN'].apply(lambda x: mapping.get(x, x))
            
        elif state == 'sn':
            districts_file = os.path.join(out_dir, f"{state}_districts.json")
            if os.path.exists(districts_file):
                with open(districts_file, 'r', encoding='utf-8') as f:
                    ddata = json.load(f)
                alkis_names = {d['name'] for d in ddata}
                
                def map_sn(name):
                    if not isinstance(name, str): return name
                    if f"Stadt {name}" in alkis_names: return f"Stadt {name}"
                    return name
                    
                gdf['GEN'] = gdf['GEN'].apply(map_sn)

    # Convert to 4326 if needed
    if "force_crs" in cfg:
        print(f"Forcing CRS to {cfg['force_crs']}...")
        gdf = gdf.set_crs(cfg["force_crs"], allow_override=True)

    if gdf.crs and gdf.crs != "EPSG:4326":
        print("Converting CRS to EPSG:4326...")
        gdf = gdf.to_crs("EPSG:4326")
    elif not gdf.crs:
        print("Warning: No CRS found! Setting to EPSG:4326 by default.")
        gdf = gdf.set_crs("EPSG:4326")

    # State specific filters
    if state == "nds":
        if 'GEN' in gdf.columns:
            initial_len = len(gdf)
            gdf = gdf[~gdf['GEN'].astype(str).str.contains("Küstenmeer", case=False, na=False)]
            print(f"NDS Filter: Removed {initial_len - len(gdf)} 'Küstenmeer' regions.")
            
    elif state == "hh":
        if 'GEN' in gdf.columns:
            initial_len = len(gdf)
            gdf = gdf[~gdf['GEN'].astype(str).str.contains("Stove", case=False, na=False)]
            print(f"HH Filter: Removed {initial_len - len(gdf)} 'Stove' regions.")

    elif state == "he":
        if 'GEN' in gdf.columns:
            initial_len = len(gdf)
            gdf = gdf[~gdf['GEN'].isin(["Gutsbezirk Kaufunger Wald", "Gemarkung Michelbuch (gemeindefrei)"])]
            if initial_len != len(gdf):
                print(f"HE Filter: Removed {initial_len - len(gdf)} out-of-bounds regions.")
    
    elif state == "st":
        if 'GEN' in gdf.columns:
            initial_len = len(gdf)
            gdf = gdf[~gdf['GEN'].isin(["Thierschneck", "Walpernhain", "Dommitzsch", "Rühstädt"])]
            if initial_len != len(gdf):
                print(f"ST Filter: Removed {initial_len - len(gdf)} out-of-bounds regions.")

        if 'admin_level' in gdf.columns:
            l8 = gdf[gdf['admin_level'] == '8']
            l6 = gdf[gdf['admin_level'] == '6']
            
            # Reproject temporarily to a metric CRS for accurate area calculations
            l8_proj = l8.to_crs("EPSG:25832")
            l6_proj = l6.to_crs("EPSG:25832")
            
            # Find level 6 boundaries that intersect with level 8 boundaries
            l6_to_keep = []
            for idx, row in l6_proj.iterrows():
                # Check if it overlaps with any level 8. For Kreisfreie Städte, this will be mostly False.
                # A small buffer/overlap might exist, so we check if overlapping area is small
                overlaps = l8_proj[l8_proj.geometry.intersects(row.geometry)]
                if len(overlaps) == 0:
                    l6_to_keep.append(True)
                else:
                    intersection_area = overlaps.geometry.intersection(row.geometry).area.sum()
                    if intersection_area < (row.geometry.area * 0.1): # Less than 10% overlap
                        l6_to_keep.append(True)
                    else:
                        l6_to_keep.append(False)
            
            l6_filtered = l6[l6_to_keep]
            gdf = pd.concat([l8, l6_filtered]).copy()
            print(f"ST Filter: Kept {len(l8)} level 8 and {len(l6_filtered)} level 6 fallback features.")

    # Simplify boundaries
    tol = cfg.get("tolerance", 0.0)
    if tol > 0.0:
        print(f"Simplifying geometries (tolerance {tol})...")
        gdf.geometry = gdf.geometry.simplify(tolerance=tol, preserve_topology=True)

    # Filter out empty geometries
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.is_valid]

    # Keep only GEN and geometry
    cols_to_keep = ['geometry']
    if 'GEN' in gdf.columns: 
        cols_to_keep.insert(0, 'GEN')
    elif 'admin_level' in gdf.columns:
        pass
        
    try:
        gdf = gdf[[c for c in cols_to_keep if c in gdf.columns]]
    except Exception as e:
        print(f"Warning filtering columns: {e}")

    print(f"Writing GeoJSON to {out_file}...")
    try:
        districts_file = os.path.join(out_dir, f"{state}_districts.json")
        if os.path.exists(districts_file):
            with open(districts_file, 'r', encoding='utf-8') as f:
                ddata = json.load(f)
            expected_names = {d['name'] for d in ddata}
            
            if 'GEN' in gdf.columns:
                matched_mask = gdf['GEN'].isin(expected_names)
                unmatched = gdf[~matched_mask]['GEN'].unique()
                matched_alkis = set(gdf[matched_mask]['GEN'])
                
                unmapped_expected = expected_names - matched_alkis
                if len(unmatched) > 0 or len(unmapped_expected) > 0:
                    print(f"\n[Validation] {state.upper()} has unmatched districts:")
                    if len(unmatched) > 0:
                        print(f"  Only in boundaries ({len(unmatched)}):")
                        for n in unmatched:
                            print(f"    - {n}")
                    if len(unmapped_expected) > 0:
                        print(f"  Only in districts list ({len(unmapped_expected)}):")
                        for n in sorted(list(unmapped_expected)):
                            print(f"    - {n}")
                else:
                    print(f"\n[Validation] {state.upper()} matched all districts!")

        gdf.to_file(out_file, driver="GeoJSON")
        print(f"Done processing {state}. Features: {len(gdf)}")
    except Exception as e:
        print(f"Failed to write output: {e}")

def main():
    parser = argparse.ArgumentParser(description="Process boundary shapes into GeoJSON.")
    parser.add_argument("--state", type=str, help="Process a specific state (e.g. nds, nrw).")
    args = parser.parse_args()
    
    if args.state:
        state = args.state.lower()
        if state in CONFIG:
            process_state(state, CONFIG[state])
        else:
            print(f"Unknown state: {state}")
    else:
        for state, cfg in CONFIG.items():
            process_state(state, cfg)

if __name__ == "__main__":
    main()
