"""
Download the NDS ALKIS district GPKG ZIPs and unpack them in data/nds/alkis/.

The district list comes from the LGLN metadata GeoJSON. ZIP names stay the same
across releases, so a file is re-downloaded when its size or ETag (the MD5 on
this S3 bucket) differs from data/nds/alkis/.downloads.json, and re-unpacked
into <name>/ when the ZIP is newer than that directory. Exits 1 if any district
failed; the others are kept.

Usage:
    python scripts/01_download_alkis_nds.py [--force] [--only Braunschweig]
"""

import os
import sys
import argparse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alkis_sources
import alkis_download as dl

GEOJSON_URL = alkis_sources.download_url("nds")
ALKIS_DIR = os.path.join("data", "nds", "alkis")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true", help="download and unpack everything")
    parser.add_argument("--only", help="only districts whose ZIP name contains this text")
    args = parser.parse_args()

    os.makedirs(ALKIS_DIR, exist_ok=True)
    session = requests.Session()
    features = session.get(GEOJSON_URL, timeout=dl.TIMEOUT).json()["features"]
    items = []
    for feature in features:
        props = feature["properties"]
        url = props.get("zip")
        if not url:
            continue
        name = url.rsplit("/", 1)[-1]
        if args.only and args.only not in name:
            continue
        stand = next((str(v)[:10] for k, v in props.items() if k.startswith("aktualitaet") and v), None)
        items.append({"url": url, "name": name, "stand": stand})
    print(f"[NDS] {len(items)} district ZIPs listed (stand {max((i['stand'] or '' for i in items), default='') or '?'})")

    for item in items:
        item["remote"] = dl.head_attrs(item["url"], session=session)
    manifest = dl.Manifest(ALKIS_DIR)
    downloaded, failed = dl.fetch_many(items, ALKIS_DIR, manifest, force=args.force)
    manifest.save()

    names = [i["name"] for i in items]
    failed.update(dl.extract_each(ALKIS_DIR, [n for n in names if n not in failed], force=args.force))
    if not args.only and (stale := dl.unlisted_zips(ALKIS_DIR, names)):
        print(f"[NDS] Not listed upstream any more (02 still reads them): {', '.join(stale)}")

    print(f"[NDS] {len(downloaded)} downloaded, {len(items) - len(downloaded) - len(failed)} unchanged, "
          f"{len(failed)} failed")
    if failed:
        return 1
    print("[NDS] Next: python scripts/02_extract_alkis.py --state NDS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
