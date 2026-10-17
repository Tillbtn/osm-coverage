"""
Download the MV ALKIS shapefile ZIPs (one per Gemeinde) into data/mv/alkis/.

The download service gives no size, date or ETag, so a refresh downloads every
Gemeinde (~1 GB) into data/mv/alkis.new/ and swaps it in only when all of them
succeeded; ZIPs of Gemeinden no longer listed (mergers) disappear with the old
directory. 02 unpacks the new ZIPs. --missing-only just fills in Gemeinden that
have no ZIP yet.

The Gemeinden come from data/mv/Gemeinde_Gemarkung_Kreis.csv (historical ones
skipped); file names keep the URL-encoded form 02 and earlier downloads use.

Usage:
    python scripts/01_download_alkis_mv.py                  # full refresh
    python scripts/01_download_alkis_mv.py --missing-only
"""

import os
import sys
import csv
import shutil
import argparse
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alkis_sources
import alkis_download as dl

DATA_DIR = "data"
ALKIS_DIR = os.path.join(DATA_DIR, "mv", "alkis")
STAGING_DIR = ALKIS_DIR + ".new"
CSV_FILE = os.path.join(DATA_DIR, "mv", "Gemeinde_Gemarkung_Kreis.csv")


def gemeinde_items(csv_path):
    """[{url, name}] per current Gemeinde, sorted by id."""
    gemeinden = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            gid, name = row.get("id_Gemeinde"), row.get("Gemeinde_Name")
            if gid and name and "hist." not in name:
                gemeinden[gid] = name
    pattern = alkis_sources.download_url("mv")
    items = []
    for gid in sorted(gemeinden):
        transformed = gemeinden[gid]
        for ch in ",./()- ":
            transformed = transformed.replace(ch, "_")
        url = pattern.format(id=gid, name=urllib.parse.quote(transformed))
        items.append({"url": url, "name": url.split("file=")[-1].split("&")[0], "remote": {}})
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--missing-only", action="store_true",
                        help="only download Gemeinden without a ZIP in data/mv/alkis/")
    args = parser.parse_args()

    items = gemeinde_items(CSV_FILE)
    print(f"[MV] {len(items)} Gemeinden in {CSV_FILE}")

    if args.missing_only:
        os.makedirs(ALKIS_DIR, exist_ok=True)
        items = [i for i in items if not os.path.exists(os.path.join(ALKIS_DIR, i["name"]))]
        print(f"[MV] {len(items)} without a ZIP")
        downloaded, failed = dl.fetch_many(items, ALKIS_DIR, dl.Manifest(ALKIS_DIR), force=True)
        print(f"[MV] {len(downloaded)} downloaded, {len(failed)} failed")
        return 1 if failed else 0

    shutil.rmtree(STAGING_DIR, ignore_errors=True)
    os.makedirs(STAGING_DIR)
    manifest = dl.Manifest(STAGING_DIR)
    downloaded, failed = dl.fetch_many(items, STAGING_DIR, manifest, force=True)
    manifest.save()
    if failed:
        print(f"[MV] {len(failed)} of {len(items)} failed, keeping the previous data; "
              f"partial download left in {STAGING_DIR}:")
        for name, err in sorted(failed.items()):
            print(f"  {name}: {err}")
        return 1

    old = ALKIS_DIR + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(ALKIS_DIR):
        os.rename(ALKIS_DIR, old)
    os.rename(STAGING_DIR, ALKIS_DIR)
    shutil.rmtree(old, ignore_errors=True)
    print(f"[MV] {len(downloaded)} Gemeinden downloaded to {ALKIS_DIR}. "
          "Next: python scripts/02_extract_alkis.py --state MV")
    return 0


if __name__ == "__main__":
    sys.exit(main())
