"""
Fetch ALKIS address data from a WFS endpoint and feed it into the pipeline.

Unlike the bulk `01_download_alkis_<state>.py` + `02_extract_alkis.py` pair, a WFS
source is fetched and normalized in a single step. It is meant to be run on its
own (e.g. weekly) cadence, separate from the periodic bulk dumps.

Two modes (configured per source):

  - mode="district": fetch a single district and *replace that district's rows*
    inside an existing state parquet (e.g. refresh "Städteregion Aachen" inside
    data/nrw/alkis.parquet, leaving the rest of NRW untouched).

  - mode="state": fetch a whole state from one WFS link and write/overwrite
    data/<state>/alkis.parquet entirely.

The normalized rows use the exact same schema and the same `generate_alkis_id`
hash as 02_extract_alkis.py, so corrections (matched by alkis_id) stay stable
across the GPKG -> WFS switch.

Usage:
    python scripts/fetch_alkis_wfs.py --list
    python scripts/fetch_alkis_wfs.py --source aachen
    python scripts/fetch_alkis_wfs.py --source aachen --dry-run
    python scripts/fetch_alkis_wfs.py            # run all configured sources
"""

import os
import io
import sys
import json
import argparse
import importlib.util

import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape

DATA_DIR = "data"
TARGET_CRS = "EPSG:25832"

# ---------------------------------------------------------------------------
# Reuse the shared helpers from 02_extract_alkis.py. The module name starts
# with a digit, so it cannot be imported normally; load it by path. This keeps
# generate_alkis_id (the correction-matching hash) single-sourced.
# ---------------------------------------------------------------------------
_EXTRACT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "02_extract_alkis.py")
_spec = importlib.util.spec_from_file_location("extract_alkis", _EXTRACT_PATH)
_extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_extract)
generate_alkis_id = _extract.generate_alkis_id
expand_complex_addresses = _extract.expand_complex_addresses
_write_alkis_meta = _extract.write_alkis_meta  # shared district-keyed sidecar writer


# ---------------------------------------------------------------------------
# WFS source configuration
# ---------------------------------------------------------------------------
# Each source describes one WFS endpoint and how to map its feature properties
# onto the pipeline schema (street, housenumber, postcode, city, district).
#
#   key            : CLI identifier (--source <key>)
#   base_url       : WFS base URL (without request-specific params)
#   typename       : WFS typeName / feature type
#   version        : WFS version (default "1.1.0")
#   count_param    : page-size parameter name ("maxFeatures" for 1.x, "count" for 2.0)
#   srs            : srsName to request; coords come back in this CRS (default 25832)
#   page_size      : features per request
#   state_dir      : subfolder under data/ holding the state's alkis.parquet
#   state_label    : value written to the 'state' column (must match existing rows)
#   mode           : "district" or "state"
#   district       : (district mode) exact district name to REPLACE in the parquet;
#                    also assigned to every fetched row. Must match existing rows.
#   district_field : (state mode) WFS property to use as the district per row
#   field_map      : property mapping, see below
#   extra_separators: housenumber separators to split on (passed to expand_complex_addresses)
#   date_field     : WFS property holding the ALKIS data date (e.g. "datum_auswertung");
#                    recorded per district in data/<state>/alkis_meta.json (optional)
#
# field_map keys:
#   street     : property holding the street name                 (required)
#   hnr        : property holding the house number                (required)
#   hnr_suffix : property holding the suffix (e.g. "a", "/19"), appended to hnr (optional)
#   city       : property holding the municipality / city          (optional)
#   postcode   : property holding the postal code                  (optional)

WFS_SOURCES = [
    {
        "key": "aachen",
        "base_url": "https://geodienste.staedteregion-aachen.de/?MAP=gebaeudereferenzen.qgs",
        "typename": "Gebaeudereferenzen_StaedteregionAachen",
        "version": "1.1.0",
        "count_param": "maxFeatures",
        "srs": "EPSG:25832",
        "page_size": 50000,
        "state_dir": "nrw",
        "state_label": "NRW",
        "mode": "district",
        # Must match the district name produced by process_nrw in 02_extract_alkis.py
        # and used by 04_compare corrections (see merge_history.py rename).
        "district": "Städteregion Aachen",
        "date_field": "datum_auswertung",
        "field_map": {
            "street": "strasse_lage",
            "hnr": "hsnr",
            "hnr_suffix": "hsnrzus",
            "city": "gmdname",
            # no postcode in this dataset
        },
        # Aachen house numbers use "/" as a range separator (e.g. 17/19),
        # matching the existing process_nrw handling.
        "extra_separators": ["/"],
    },
]


# ---------------------------------------------------------------------------
# WFS fetching
# ---------------------------------------------------------------------------
def fetch_wfs_features(source, session=None, timeout=300):
    """
    Page through a WFS endpoint and return a flat list of GeoJSON feature dicts.
    """
    session = session or requests.Session()
    version = source.get("version", "1.1.0")
    count_param = source.get("count_param", "maxFeatures")
    page_size = source.get("page_size", 50000)
    srs = source.get("srs", TARGET_CRS)

    features = []
    start = 0
    while True:
        params = {
            "service": "WFS",
            "version": version,
            "request": "GetFeature",
            "typeName": source["typename"],
            "srsName": srs,
            "outputFormat": "application/vnd.geo+json",
            "startIndex": start,
            count_param: page_size,
        }
        resp = session.get(source["base_url"], params=params, timeout=timeout)
        resp.raise_for_status()

        try:
            data = resp.json()
        except json.JSONDecodeError:
            data = json.load(io.BytesIO(resp.content))

        page = data.get("features", [])
        if not page:
            break

        features.extend(page)
        print(f"  fetched {len(features)} features (last page: {len(page)})")

        if len(page) < page_size:
            break
        start += page_size

    return features


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def normalize_features(features, source):
    """
    Turn raw GeoJSON features into a GeoDataFrame with the pipeline schema:
    street, housenumber, postcode, city, district, state, geometry.
    """
    fm = source["field_map"]
    street_f = fm["street"]
    hnr_f = fm["hnr"]
    suffix_f = fm.get("hnr_suffix")
    city_f = fm.get("city")
    postcode_f = fm.get("postcode")
    district_field = source.get("district_field")
    fixed_district = source.get("district")

    records = []
    geoms = []

    for feat in features:
        geom_json = feat.get("geometry")
        if not geom_json:
            continue
        props = feat.get("properties", {}) or {}

        street = props.get(street_f)
        if street is None or str(street).strip() == "":
            continue

        hnr = props.get(hnr_f)
        if hnr is None or str(hnr).strip() == "":
            continue
        housenumber = str(hnr).strip()

        if suffix_f:
            suffix = props.get(suffix_f)
            if suffix is not None and str(suffix).strip() != "":
                housenumber = f"{housenumber}{str(suffix).strip()}"

        if district_field:
            district = props.get(district_field)
        else:
            district = fixed_district

        try:
            geom = shape(geom_json)
        except Exception:
            continue
        if geom is None or geom.is_empty:
            continue

        records.append({
            "street": str(street).strip(),
            "housenumber": housenumber,
            "postcode": props.get(postcode_f) if postcode_f else None,
            "city": props.get(city_f) if city_f else None,
            "district": district,
            "state": source["state_label"],
        })
        geoms.append(geom)

    if not records:
        return gpd.GeoDataFrame(
            columns=["street", "housenumber", "postcode", "city", "district", "state", "geometry"],
            geometry="geometry", crs=source.get("srs", TARGET_CRS),
        )

    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs=source.get("srs", TARGET_CRS))

    # Reduce any non-point geometries (e.g. building polygons) to a single point.
    non_point = gdf.geometry.geom_type != "Point"
    if non_point.any():
        gdf.loc[non_point, "geometry"] = gdf.loc[non_point, "geometry"].representative_point()

    if str(gdf.crs).upper() != TARGET_CRS:
        gdf = gdf.to_crs(TARGET_CRS)

    # Split complex / range house numbers exactly like 02_extract_alkis.py.
    gdf = expand_complex_addresses(gdf, extra_separators=source.get("extra_separators"))

    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=TARGET_CRS)
    gdf = gdf.drop_duplicates(subset=["street", "housenumber", "district", "city"])

    # Same id hash as the bulk extractor -> corrections stay matched.
    gdf["alkis_id"] = gdf.apply(generate_alkis_id, axis=1)

    return gdf.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def _write_parquet_atomic(gdf, path):
    tmp = f"{path}.tmp"
    gdf.to_parquet(tmp)
    os.replace(tmp, path)


def extract_alkis_date(features, source):
    """
    Read the ALKIS data date (e.g. "datum_auswertung") from the raw features.
    The value is uniform per feed; if several appear, keep the latest.
    """
    field = source.get("date_field")
    if not field:
        return None
    dates = {
        str((f.get("properties") or {}).get(field)).strip()
        for f in features
        if (f.get("properties") or {}).get(field)
    }
    return max(dates) if dates else None


def write_alkis_meta(source, districts, alkis_date, dry_run=False):
    """
    Record ALKIS source freshness per district in data/<state>/alkis_meta.json.
    This sidecar is read by 04_compare.py to surface 'alkis_date' on the map,
    independent of when the comparison runs.
    """
    state_dir = os.path.join(DATA_DIR, source["state_dir"])
    meta_path = os.path.join(state_dir, "alkis_meta.json")

    print(f"[{source['key']}] alkis_date={alkis_date} for {len(districts)} district(s)")

    if dry_run:
        print(f"[{source['key']}] dry-run: not writing {meta_path}")
        return

    # A WFS run refreshes a single district, not the whole state, so it must not
    # claim the state-wide date (state_wide=False).
    _write_alkis_meta(state_dir, districts, alkis_date, f"wfs:{source['key']}", state_wide=False)
    print(f"[{source['key']}] wrote {meta_path}")


def update_district(new_gdf, source, dry_run=False):
    """
    Replace one district's rows inside an existing state parquet, leaving every
    other district untouched. Aborts if the target district is not present.
    """
    state_dir = os.path.join(DATA_DIR, source["state_dir"])
    parquet_path = os.path.join(state_dir, "alkis.parquet")
    district = source["district"]

    if not os.path.exists(parquet_path):
        print(f"[{source['key']}] ERROR: {parquet_path} does not exist. "
              f"District mode replaces a district inside an existing state parquet; "
              f"run the bulk pipeline first.")
        return False

    existing = gpd.read_parquet(parquet_path)
    if "district" not in existing.columns:
        print(f"[{source['key']}] ERROR: {parquet_path} has no 'district' column.")
        return False

    matched = int((existing["district"] == district).sum())
    if matched == 0:
        present = sorted(existing["district"].dropna().unique().tolist())
        print(f"[{source['key']}] ERROR: district '{district}' not found in "
              f"{parquet_path}; aborting without changes.")
        print(f"[{source['key']}] Districts present ({len(present)}): "
              f"{', '.join(present[:30])}{' ...' if len(present) > 30 else ''}")
        return False

    retained = existing[existing["district"] != district].copy()

    # Align the fetched rows to the existing parquet's columns.
    aligned = new_gdf.reindex(columns=existing.columns)
    if "geometry" not in aligned.columns:
        print(f"[{source['key']}] ERROR: fetched data has no geometry after alignment.")
        return False

    combined = pd.concat([retained, aligned], ignore_index=True)
    combined = gpd.GeoDataFrame(combined, geometry="geometry", crs=existing.crs)

    district_diff = len(new_gdf) - matched
    state_diff = len(combined) - len(existing)
    print(f"[{source['key']}] district '{district}': "
          f"{matched} old rows -> {len(new_gdf)} new rows (diff: {district_diff:+d})")
    print(f"[{source['key']}] state '{source['state_label']}' total: "
          f"{len(existing)} -> {len(combined)} (diff: {state_diff:+d})")

    if dry_run:
        print(f"[{source['key']}] dry-run: not writing {parquet_path}")
        return True

    _write_parquet_atomic(combined, parquet_path)
    print(f"[{source['key']}] wrote {parquet_path}")
    return True


def write_state(new_gdf, source, dry_run=False):
    """
    Write/overwrite a whole state parquet from a single WFS source.
    """
    state_dir = os.path.join(DATA_DIR, source["state_dir"])
    parquet_path = os.path.join(state_dir, "alkis.parquet")
    os.makedirs(state_dir, exist_ok=True)

    old_count = None
    if os.path.exists(parquet_path):
        try:
            import pyarrow.parquet as pq
            old_count = pq.read_metadata(parquet_path).num_rows
        except Exception:
            try:
                old_count = len(pd.read_parquet(parquet_path))
            except Exception:
                pass

    new_count = len(new_gdf)
    if old_count is not None:
        diff = new_count - old_count
        print(f"[{source['key']}] state '{source['state_label']}': "
              f"{new_count} rows (previously {old_count}, diff: {diff:+d})")
    else:
        print(f"[{source['key']}] state '{source['state_label']}': {new_count} rows (new file)")

    if dry_run:
        print(f"[{source['key']}] dry-run: not writing {parquet_path}")
        return True

    _write_parquet_atomic(new_gdf, parquet_path)
    print(f"[{source['key']}] wrote {parquet_path}")
    return True


def run_source(source, dry_run=False):
    print(f"\n[{source['key']}] fetching WFS '{source['typename']}' ...")
    features = fetch_wfs_features(source)
    print(f"[{source['key']}] {len(features)} raw features fetched.")

    gdf = normalize_features(features, source)
    print(f"[{source['key']}] {len(gdf)} normalized addresses.")

    if gdf.empty:
        print(f"[{source['key']}] no usable addresses; skipping write.")
        return False

    mode = source.get("mode", "district")
    if mode == "district":
        ok = update_district(gdf, source, dry_run=dry_run)
    elif mode == "state":
        ok = write_state(gdf, source, dry_run=dry_run)
    else:
        print(f"[{source['key']}] ERROR: unknown mode '{mode}'.")
        return False

    if ok:
        alkis_date = extract_alkis_date(features, source)
        districts = sorted(gdf["district"].dropna().unique().tolist())
        write_alkis_meta(source, districts, alkis_date, dry_run=dry_run)

    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=str, help="Run only this source key (default: all)")
    parser.add_argument("--list", action="store_true", help="List configured sources and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and normalize but do not write any parquet")
    args = parser.parse_args()

    if args.list:
        print("Configured WFS sources:")
        for s in WFS_SOURCES:
            target = s.get("district") if s.get("mode") == "district" else f"whole state"
            print(f"  {s['key']:<12} mode={s.get('mode'):<9} "
                  f"-> data/{s['state_dir']}/alkis.parquet ({target})")
        return

    sources = WFS_SOURCES
    if args.source:
        sources = [s for s in WFS_SOURCES if s["key"] == args.source]
        if not sources:
            print(f"No source with key '{args.source}'. "
                  f"Known: {', '.join(s['key'] for s in WFS_SOURCES)}")
            sys.exit(1)

    ok = True
    for source in sources:
        try:
            if not run_source(source, dry_run=args.dry_run):
                ok = False
        except Exception as e:
            ok = False
            print(f"[{source['key']}] ERROR: {e}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
