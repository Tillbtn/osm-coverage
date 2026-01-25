
import os
import glob
import zipfile
import geopandas as gpd
import pandas as pd
import tqdm
import re 
import numpy as np 
from shapely.geometry import Point 
import hashlib 
import osmium
from shapely import wkb

# Configuration
DATA_DIR = "data"
# Subfolders
DIR_NDS = os.path.join(DATA_DIR, "nds")
DIR_NRW = os.path.join(DATA_DIR, "nrw")
DIR_RLP = os.path.join(DATA_DIR, "rlp")
DIR_BB = os.path.join(DATA_DIR, "bb")
DIR_HH = os.path.join(DATA_DIR, "hh")
DIR_HE = os.path.join(DATA_DIR, "he")

def remove_ortsteil(text):
    """
    Removes 'Ortsteil ...' from the address string.
    """
    if not isinstance(text, str): return text
    return re.sub(r',\s*Ortsteil\s+[^;]+', '', text, flags=re.IGNORECASE).strip()

def generate_alkis_id(row):
    """
    Generates a unique ID for an ALKIS row based on its content and coordinates.
    """
    try:
        geo_str = f"{row.geometry.x:.3f}_{row.geometry.y:.3f}" if row.geometry else "no_geo"
    except:
        geo_str = "invalid_geo"
        
    raw_str = f"{row.get('district', '')}_{row.get('street', '')}_{row.get('housenumber', '')}_{geo_str}"
    return hashlib.md5(raw_str.encode('utf-8')).hexdigest()[:12]


def split_alkis_address_string(original_street, original_hnr_string, extra_separators=None):
    """
    Parses "Straße 1, 2, Weg 3" into [("Straße", "1"), ("Straße", "2"), ("Weg", "3")]
    """
    if not isinstance(original_hnr_string, str): 
         return [(original_street, original_hnr_string)]
         
    if extra_separators:
        for sep in extra_separators:
            original_hnr_string = original_hnr_string.replace(sep, ',')

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
            
    return resultsdefault

def expand_complex_addresses(df, extra_separators=None, desc="Splitting Addresses"):
    """
    Splits rows where housenumber contains commas/semicolons.
    """
    if 'housenumber' not in df.columns: return df
    
    regex = r'[,;]'
    if extra_separators:
        # Escape separators if needed
        escaped_seps = "".join([re.escape(s) for s in extra_separators])
        regex = f"[{escaped_seps},;]"
    
    mask = df['housenumber'].astype(str).str.contains(regex, regex=True)
    if not mask.any():
        return df
        
    print(f"  Found {mask.sum()} complex address rows to split.")
    
    rows_to_split = df[mask]
    clean_rows = df[~mask]
    
    new_data = []
    
    for idx, row in rows_to_split.iterrows():
        street = row['street']
        hnr = row['housenumber']
        
        splits = split_alkis_address_string(street, hnr, extra_separators=extra_separators)
        
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


class DistrictHandler(osmium.SimpleHandler):
    def __init__(self):
        super(DistrictHandler, self).__init__()
        self.boundaries = []
        self.wkbfab = osmium.geom.WKBFactory()

    def area(self, a):
        try:
            if 'boundary' in a.tags and a.tags['boundary'] == 'administrative':
                if a.tags.get('admin_level') == '10':
                    wkb_data = self.wkbfab.create_multipolygon(a)
                    name = a.tags.get('name')
                    if name:
                        self.boundaries.append({'name': name, 'wkb': wkb_data})
        except:
            pass

def extract_osm_boundaries(pbf_path):
    print(f"[HH] Extracting district boundaries from {pbf_path}...")
    handler = DistrictHandler()
    am = osmium.area.AreaManager()
    
    # 2-pass approach generally required for Relations -> Areas
    try:
        reader1 = osmium.io.Reader(pbf_path)
        osmium.apply(reader1, am.first_pass_handler())
        reader1.close()

        reader2 = osmium.io.Reader(pbf_path)
        # build geometries for node locations
        idx = osmium.index.create_map("sparse_file_array")
        lh = osmium.NodeLocationsForWays(idx)
        lh.ignore_errors()
        
        osmium.apply(reader2, lh, handler, am.second_pass_handler(handler))
        reader2.close()
    except Exception as e:
        print(f"[HH] Error reading OSM PBF: {e}")
        return None
    
    if not handler.boundaries:
        print("[HH] No boundaries found in OSM PBF.")
        return None

    df = pd.DataFrame(handler.boundaries)
    df['geometry'] = df['wkb'].apply(lambda x: wkb.loads(x, hex=True))
    gdf = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")
    gdf = gdf.to_crs("EPSG:25832")
    return gdf


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
        
        # Generate Unique IDs
        print(f"[{state_name}] Generating ALKIS IDs...")
        if 'alkis_id' not in full_gdf.columns:
            full_gdf['alkis_id'] = full_gdf.apply(generate_alkis_id, axis=1)

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
                        
                        extra_seps = None
                        if district in ["Aachen Städteregion", "Aachen_Städteregion", "Aachen, Städteregion"]:
                             extra_seps = ['/']
                             
                        norm_gdf = expand_complex_addresses(norm_gdf, extra_separators=extra_seps)
                        
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

def process_bb(directory):
    gpkg_path = os.path.join(directory, "adressen-bb.gpkg")

    if not os.path.exists(gpkg_path):
        print(f"[BB] GPKG not found at {gpkg_path}")
        return []
        
    print(f"[BB] Reading GPKG from {gpkg_path}...")
    
    try:
        gdf = gpd.read_file(gpkg_path, layer='adressen-bb', engine='pyogrio')
        
        gdf = gdf.dropna(subset=['str', 'hnr'])
        
        # Combine HNR + ADZ
        gdf['housenumber'] = gdf['hnr'].astype(str) + gdf['adz'].fillna('').astype(str)
        
        gdf = gdf.rename(columns={
            'str': 'street',
            'postplz': 'postcode',
            'gmd': 'district'
        })
        
        gdf['city'] = gdf['district']
        
        # Ensure geometry validity
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty & gdf.geometry.is_valid]
        
        cols = ['street', 'housenumber', 'postcode', 'city', 'district', 'geometry']
        gdf = gdf[cols].copy()
        
        gdf['state'] = 'Brandenburg'
        
        return [gdf]
        
    except Exception as e:
        print(f"[BB] Error processing GPKG: {e}")
        return []

def process_hh(directory):
    # Expects data/hh/alkis.zip or data/hh/*.gml
    # Usually "INSPIRE_Adressen_Hauskoordinaten_HH_*.gml" inside zip
    
    # 1. Check for GML files directly
    gmls = glob.glob(os.path.join(directory, "*.gml"))
    gmls += glob.glob(os.path.join(directory, "*.GML"))
    
    # 2. Check for ZIP
    if not gmls:
        zips = glob.glob(os.path.join(directory, "*.zip"))
        if zips:
             for z in zips:
                 try:
                     print(f"[HH] Extracting {z}...")
                     with zipfile.ZipFile(z, 'r') as zf:
                         # Extract only GMLs if possible, to avoid clutter
                         for n in zf.namelist():
                             if n.lower().endswith('.gml'):
                                 zf.extract(n, directory)
                 except Exception as e:
                     print(f"[HH] Error extracting {z}: {e}")
        
        gmls = glob.glob(os.path.join(directory, "*.gml"))

    if not gmls:
        # Fallback: Check parent directory (data/hh)
        parent = os.path.dirname(directory)
        gmls = glob.glob(os.path.join(parent, "*.gml"))
        
        if not gmls:
             # Check for zip in parent
             zips = glob.glob(os.path.join(parent, "*.zip"))
             if zips:
                 for z in zips:
                      try:
                         print(f"[HH] Extracting {z}...")
                         with zipfile.ZipFile(z, 'r') as zf:
                             for n in zf.namelist():
                                 if n.lower().endswith('.gml'):
                                     zf.extract(n, directory) # Extract to alkis folder
                      except: pass
             gmls = glob.glob(os.path.join(directory, "*.gml"))

    if not gmls:
        print(f"[HH] No GML files found in {directory} or parent.")
        return []
        
    results = []
    
    import xml.etree.ElementTree as ET
    
    # Namespaces usually found in INSPIRE GML
    ns = {
        'gml': 'http://www.opengis.net/gml/3.2',
        'ad': 'http://inspire.ec.europa.eu/schemas/ad/4.0', # Version might vary (3.0 or 4.0)
        'base': 'http://inspire.ec.europa.eu/schemas/base/3.3'
    }
    
    # Alternative namespaces if above fail
    # We will try to detect or just use wildcard search or local-name() in XPath if possible
    # But ET only supports simple dict.
    
    for gml_path in gmls:
        print(f"[HH] Parsing {os.path.basename(gml_path)} (this may take a while)...")
        
        # We need to handle two types of objects:
        # 1. Address (contains housenumber, geometry, and link to component)
        # 2. ThoroughfareName (contains street name) OR AddressComponent (Street)
        
        # Strategy: Pass 1 to build Street Map, Pass 2 to build Addresses
        # Or if file is small enough, load all. INSPIRE GML can be 500MB+.
        # Iterparse is recommended.
        
        streets = {} # id -> name
        addresses = []
        
        try:
            context = ET.iterparse(gml_path, events=('end',))
            
            for event, elem in context:
                # Remove namespace for easier checking (hacky but effective for varied GML versions)
                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                
                if tag == "ThoroughfareName":
                    # Structure: <ad:ThoroughfareName gml:id="..."> ... <ad:name> <ad:GeographicalName> ... <ad:spelling> <ad:SpellingOfName> <ad:text>Name</ad:text>
                    # This is DEEP.
                    # Simplified check:
                    gml_id = elem.get(f"{{{ns['gml']}}}id")
                    if not gml_id: gml_id = elem.get("id") # fallback
                     
                    # Find name text
                    # We look for 'text' element deeply
                    name_text = None
                    for text_node in elem.iter():
                        if text_node.tag.endswith('text') and text_node.text:
                            name_text = text_node.text
                            break
                    
                    if gml_id and name_text:
                        gml_id = gml_id.strip()
                        streets[f"#{gml_id}"] = name_text
                        streets[gml_id] = name_text
                        
                    elem.clear()
                    
                elif tag == "Address":
                    # <ad:Address gml:id="...">
                    #   <ad:position> ... <gml:Point> ... <gml:pos>X Y</gml:pos>
                    #   <ad:locator> ... <ad:designator> ... <ad:text>123</ad:text> or <ad:designator>123</ad:designator>
                    #   <ad:component xlink:href="#id_of_street"/>
                    
                    # Extract Geometry
                    pos_text = None
                    for pos in elem.iter():
                         if pos.tag.endswith('pos'): 
                             pos_text = pos.text
                             break
                    
                    # Extract Housenumber
                    # Extract Housenumber
                    hnr_parts = []
                    for node in elem.iter():
                        if node.tag.endswith('designator') and node.text and node.text.strip():
                             hnr_parts.append(node.text.strip())
                    
                    if hnr_parts:
                        hnr_text = hnr_parts[0]
                        for part in hnr_parts[1:]:
                            if part.lower().startswith("haus"):
                                hnr_text += f", {part}"
                            else:
                                hnr_text += part
                    else:
                        hnr_text = None
                    
                    # Improve HNR extraction: Look specifically inside AddressLocator
                    # But iter() is depth-first.
                    
                    # Extract Street Ref
                    street_ref = None
                    street_ref = None
                    for comp in elem.iter():
                        if comp.tag.endswith('component'):
                            href = comp.get('{http://www.w3.org/1999/xlink}href')
                            if href and ("ThoroughfareName" in href or "thoroughfare" in href.lower()):
                                street_ref = href.strip()
                                break
                    
                    if pos_text and hnr_text and street_ref:
                         addresses.append({
                             'hnr': hnr_text,
                             'pos': pos_text,
                             'street_ref': street_ref
                         })
                         
                    elem.clear()

        except Exception as e:
            print(f"[HH] Error parsing {gml_path}: {e}")
            continue
            
        print(f"[HH] Found {len(streets)} streets and {len(addresses)} addresses.")
        
        # Build GDF
        data = []
        
        for addr in addresses:
            s_ref = addr['street_ref']
            street_name = streets.get(s_ref)
            
            # If not found directly, try cleaning ref
            if not street_name:
                 # Check for urn stripping or hash mismatch
                 # Example s_ref: "urn:ogc:def:crs:EPSG::25832" -> this is NOT a street ref usually
                 # Example s_ref: "#DEHH..." 
                 
                 if s_ref.startswith('#'):
                     street_name = streets.get(s_ref[1:])
                 elif s_ref in streets:
                     street_name = streets[s_ref]
                 else:
                     # Try finding by partial match?
                     pass
            
            if not street_name and len(data) < 5:
                # Debug failed lookups for first few
                 print(f"DEBUG: Failed lookup for ref '{s_ref}'")
            s_ref = addr['street_ref']
            street_name = streets.get(s_ref)
            
            # If not found directly, try cleaning ref
            if not street_name:
                 # sometimes refs are urns: urn:ogc:def:crs... no, refs to objects.
                 # "urn:x:y:StreetID"
                 pass
                 
            if street_name:
                try:
                    coords = addr['pos'].strip().split()
                    if len(coords) >= 2:
                        x, y = float(coords[0]), float(coords[1])
                        
                        data.append({
                            'street': street_name,
                            'housenumber': addr['hnr'],
                            'postcode': None,
                            'city': 'Hamburg',
                            'district': 'Hamburg', # Single district for now
                            'geometry': Point(x, y)
                        })
                except: pass
                
        if data:
            gdf = gpd.GeoDataFrame(data, crs="EPSG:25832") # INSPIRE usually 25832 or 4258. Check GML srsName.
            # Assuming 25832 for Germany/Hamburg usually.
            # If coordinates are small (lat/lon), it's 4258.
            # 300000 5000000 -> UTM.
            
            # Check first coord magnitude
            if not gdf.empty:
                x_sample = gdf.geometry.iloc[0].x
                if x_sample < 180:
                    gdf.set_crs("EPSG:4258", inplace=True, allow_override=True)
                    gdf = gdf.to_crs("EPSG:25832")
            
            # Spatial Join with Districts
            # Load OSM boundaries
            pbf_path = os.path.join(directory, "osm", "hamburg-latest.osm.pbf")
            if not os.path.exists(pbf_path):
                 pbf_path = os.path.join(os.path.dirname(directory), "hh", "osm", "hamburg-latest.osm.pbf")
            
            districts_gdf = None
            pbf_path = os.path.join(os.path.dirname(directory), "osm", "hamburg-latest.osm.pbf")
            
            if os.path.exists(pbf_path):
                districts_gdf = extract_osm_boundaries(pbf_path)
                
            if districts_gdf is not None and not districts_gdf.empty:
                print(f"[HH] Assigning districts using {len(districts_gdf)} polygons...")
                # sjoin
                # Ensure same CRS
                if gdf.crs != districts_gdf.crs:
                    districts_gdf = districts_gdf.to_crs(gdf.crs)
                
                joined = gpd.sjoin(gdf, districts_gdf[['geometry', 'name']], how='left', predicate='intersects')
                
                # Update district column
                # If match found, use 'name' from index_right
                joined['district'] = joined['name'].fillna('kein Stadtteil gefunden')
                
                # Cleanup sjoin columns
                if 'index_right' in joined.columns: del joined['index_right']
                if 'name' in joined.columns: del joined['name']
                
                gdf = joined
            else:
                 print("[HH] No district boundaries found for address")

            gdf['state'] = 'Hamburg'
            results.append(gdf)
            
    return results


def process_he(directory):
    txts = glob.glob(os.path.join(directory, "*.txt"))
    if not txts:
        print(f"[HE] No .txt files found in {directory}.")
        return []

    results = []
    
    for txt_path in txts:
        print(f"[HE] Processing {os.path.basename(txt_path)}...")
        try:
             # Columns: nba;oid;qua;landschl;land;regbezschl;regbez;kreisschl;kreis;gmdschl;gmd;ottschl;ott;strschl;str;hnr;adz;zone;ostwert;nordwert
             df = pd.read_csv(txt_path, sep=';', dtype=str, encoding='utf-8', on_bad_lines='skip')
             
             df.columns = df.columns.str.lower()
             
             required = ['str', 'hnr', 'ostwert', 'nordwert']
             if not all(col in df.columns for col in required):
                 print(f"[HE] Missing columns in {txt_path}. Found: {df.columns.tolist()}")
                 continue

             df = df.dropna(subset=required)
             
             # Filter out invalid housenumbers (0)
             df = df[df['hnr'] != '0']
             
             df['housenumber'] = df['hnr'] + df['adz'].fillna('')
             
             df = df.rename(columns={
                'str': 'street',
                'gmd': 'district',
             })
             
             df['postcode'] = None
             df['city'] = df['district']
             
             # Coordinates Hessen UTM32 (EPSG:25832)
             x = pd.to_numeric(df['ostwert'], errors='coerce')
             y = pd.to_numeric(df['nordwert'], errors='coerce')
             
             gdf = gpd.GeoDataFrame(
                df[['street', 'housenumber', 'postcode', 'city', 'district']],
                geometry=gpd.points_from_xy(x, y),
                crs="EPSG:25832"
             )
             
             # Remove invalid geometries
             gdf = gdf[gdf.geometry.is_valid & ~gdf.geometry.is_empty]
             
             gdf['state'] = 'Hessen'
             results.append(gdf)
             
        except Exception as e:
            print(f"[HE] Error processing {txt_path}: {e}")
            
    return results


def main():
    process_state("NDS", DIR_NDS, process_lgln)
    process_state("NRW", DIR_NRW, process_nrw)
    process_state("RLP", DIR_RLP, process_rlp)
    process_state("BB", DIR_BB, process_bb)
    process_state("HH", DIR_HH, process_hh)
    process_state("HE", DIR_HE, process_he)

if __name__ == "__main__":
    main()
