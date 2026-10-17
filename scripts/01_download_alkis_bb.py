"""
BB Hauskoordinaten: unpack a Geobroker order (the source 02 uses), or fetch the
same addresses unattended from the LGB gazetteer as a fallback.

Primary source: order "Georeferenzierte Adresse" as GeoPackage at
  https://geobroker.geobasis-bb.de/gbss.php?MODE=GetProductInformation&PRODUCTID=51600a1d-c7a3-4211-aff8-e94fb7dc166d
and put the delivered ZIP into data/bb/alkis/. It is zipped twice
(<n>_data.zip -> pos_1/<…>.zip -> GEOPACKAGE_1/adressen-bb.gpkg); the default run
extracts the GPKG from the newest such ZIP to data/bb/alkis/adressen-bb.gpkg, the
file 02 reads, and keeps the previous one as adressen-bb.gpkg.old.

Fallback (--gazetteer): pages through the gazetteer's Hauskoordinaten collection
(OGC API Features, ogc-api.geobasis-bb.de/datasets/gaz) and writes
data/bb/alkis/adressen-bb-gazetteer.gpkg with the Geobroker GPKG's layer name and
columns. 02 does not read it; to use it, move it to adressen-bb.gpkg.

How it compares (both at stand 2026-09-30, 869 362 addresses): oids, coordinates,
house numbers, adz, Gemeinden and postal fields are identical, but the gazetteer
takes street names from its own street catalogue, which lags behind ALKIS — 1150
addresses have no street name (filled from the abbreviated postal name "…str."
here) and ~770 carry an older spelling ("Groß-Stückenfeld" vs "Großstückenfeld").
Through 02, 1160 alkis_ids (0.13 %) differ from those of the Geobroker GPKG.

Usage:
    python scripts/01_download_alkis_bb.py                       # unpack the newest order ZIP
    python scripts/01_download_alkis_bb.py --gazetteer           # skips if already at the gazetteer's stand
    python scripts/01_download_alkis_bb.py [--gazetteer] --force
"""

import os
import sys
import glob
import time
import shutil
import zipfile
import argparse

import pandas as pd
import geopandas as gpd
import pyogrio
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alkis_sources

ALKIS_DIR = os.path.join("data", "bb", "alkis")
GPKG_NAME = "adressen-bb.gpkg"
GPKG_PATH = os.path.join(ALKIS_DIR, GPKG_NAME)
OUT_PATH = os.path.join(ALKIS_DIR, "adressen-bb-gazetteer.gpkg")
LAYER = "adressen-bb"
URL = alkis_sources.SOURCES["bb"]["url"] + "/items"
CRS = "http://www.opengis.net/def/crs/EPSG/0/25833"
PAGE_SIZE = 10000


def gpkg_stand(path):
    """The 'aud' date of a Geobroker-schema GPKG, or None."""
    if not os.path.exists(path):
        return None
    g = pyogrio.read_dataframe(path, layer=LAYER, columns=["aud"], max_features=1,
                               read_geometry=False)
    return str(g["aud"].iloc[0])[:10] if len(g) else None


def find_order_zip():
    """
    Newest ZIP in ALKIS_DIR that holds an inner ZIP with adressen-bb.gpkg, as
    (outer path, inner ZIP name, GPKG member info), or None.
    """
    found = []
    for path in glob.glob(os.path.join(ALKIS_DIR, "*.zip")):
        try:
            with zipfile.ZipFile(path) as outer:
                for inner_name in outer.namelist():
                    if not inner_name.lower().endswith(".zip"):
                        continue
                    with zipfile.ZipFile(outer.open(inner_name)) as inner:
                        for info in inner.infolist():
                            if os.path.basename(info.filename) == GPKG_NAME:
                                found.append((os.path.getmtime(path), path, inner_name, info))
        except zipfile.BadZipFile:
            print(f"[BB] Skipping unreadable ZIP {os.path.basename(path)}")
    return max(found, key=lambda f: f[0])[1:] if found else None


def unpack_order(force):
    order = find_order_zip()
    if not order:
        print(f"[BB] No Geobroker order ZIP with {GPKG_NAME} in {ALKIS_DIR}. Order it at "
              f"{alkis_sources.download_url('bb')} or use --gazetteer.")
        return 1
    path, inner_name, info = order
    print(f"[BB] Order {os.path.basename(path)}: {inner_name} -> {info.filename} "
          f"({info.file_size} bytes)")
    if (os.path.exists(GPKG_PATH) and os.path.getsize(GPKG_PATH) == info.file_size
            and not force):
        print(f"[BB] {GPKG_PATH} already has that size (stand {gpkg_stand(GPKG_PATH)}), "
              "nothing to do.")
        return 0

    part = GPKG_PATH.replace(".gpkg", ".part.gpkg")
    with zipfile.ZipFile(path) as outer, zipfile.ZipFile(outer.open(inner_name)) as inner:
        with inner.open(info) as src, open(part, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
    new_stand = gpkg_stand(part)
    if os.path.exists(GPKG_PATH):
        old_stand = gpkg_stand(GPKG_PATH)
        os.replace(GPKG_PATH, GPKG_PATH + ".old")
        print(f"[BB] Kept the previous GPKG (stand {old_stand}) as {GPKG_NAME}.old")
    os.replace(part, GPKG_PATH)
    print(f"[BB] Wrote {GPKG_PATH} (stand {new_stand}). "
          "Next: python scripts/02_extract_alkis.py --state BB")
    return 0


def fetch_page(session, offset):
    params = {"f": "json", "landschluessel": "12", "limit": PAGE_SIZE, "offset": offset, "crs": CRS}
    for attempt in range(5):
        try:
            resp = session.get(URL, params=params, headers={"Accept": "application/geo+json"},
                               timeout=120)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"[BB] offset {offset}, attempt {attempt + 1}: {e}")
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"giving up at offset {offset}")


def to_geobroker_schema(features):
    """Gazetteer features -> GeoDataFrame with the Geobroker GPKG's columns."""
    rows = []
    for f in features:
        p = f.get("properties") or {}
        hnr, hnr_adz = p.get("hnr") or "", p.get("hnr_adz") or ""
        # "12 A" / "12/1" / "12/P1" -> adz "A" / "1" / "P1" as in the Geobroker GPKG
        adz = hnr_adz[len(hnr):].strip().lstrip("/") if hnr_adz.startswith(hnr) else ""
        x, y = f["geometry"]["coordinates"][:2]
        rows.append({
            "oid": p.get("id"),
            "landschl": p.get("landschluessel"),
            "land": p.get("landname"),
            "kreisschl": (p.get("kreisschluessel") or "")[-2:],
            "kreis": p.get("kreisname"),
            "gmdschl": (p.get("gemeindeschluessel") or "")[-3:],
            "gmd": p.get("gemeindename"),
            "ott": p.get("ortsteilname") or None,
            "strschl": (p.get("strassenschluessel") or "")[-5:] or None,
            "str": p.get("strassenname") or p.get("post_strname") or None,
            "hnr": hnr,
            "adz": adz or None,
            "ostwert": x,
            "nordwert": y,
            "postplz": p.get("post_plz"),
            "postonm": p.get("post_ortsname"),
            "postonmzus": p.get("post_ortsname_zusatz") or None,
            "postott": p.get("post_ortsteil") or None,
            "poststr": p.get("post_strname"),
            "aud": p.get("akt"),
        })
    df = pd.DataFrame(rows)
    df["aud"] = pd.to_datetime(df["aud"])
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.ostwert, df.nordwert), crs=25833)


def download_gazetteer(force):
    remote, _ = alkis_sources.probe_remote_date("bb")
    local = gpkg_stand(OUT_PATH)
    print(f"[BB] Gazetteer stand: {remote or '?'}, local fallback file: {local or '-'}")
    if remote and local == remote and not force:
        print("[BB] Already current, nothing to do.")
        return 0

    os.makedirs(ALKIS_DIR, exist_ok=True)
    part = OUT_PATH.replace(".gpkg", ".part.gpkg")  # GDAL wants the .gpkg extension
    if os.path.exists(part):
        os.remove(part)
    session = requests.Session()
    offset, matched = 0, None
    while True:
        page = fetch_page(session, offset)
        features = page.get("features") or []
        matched = page.get("numberMatched", matched)
        if not features:
            break
        pyogrio.write_dataframe(to_geobroker_schema(features), part, layer=LAYER,
                                driver="GPKG", append=offset > 0)
        offset += len(features)
        print(f"[BB] {offset}/{matched}")
        if len(features) < PAGE_SIZE:
            break

    if matched is not None and offset != matched:
        os.remove(part)
        print(f"[BB] Got {offset} features, the API reported {matched}; discarded.")
        return 1
    os.replace(part, OUT_PATH)
    print(f"[BB] Wrote {OUT_PATH} ({offset} addresses). 02 reads {GPKG_NAME}, "
          "not this file — see the module docstring before swapping it in.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Unpack a BB Geobroker order, or fetch the gazetteer fallback.")
    parser.add_argument("--gazetteer", action="store_true",
                        help="download the gazetteer fallback instead of unpacking an order")
    parser.add_argument("--force", action="store_true",
                        help="unpack/download even if the local file looks current")
    args = parser.parse_args()
    return download_gazetteer(args.force) if args.gazetteer else unpack_order(args.force)


if __name__ == "__main__":
    sys.exit(main())
