"""
Download the newest ALKIS Adressen Hamburg ZIP (Transparenzportal) into
data/hh/alkis/ and unpack its GML there.

The ZIP is found through the CKAN API (scripts/alkis_sources.py,
hh_latest_download); its file name carries the stand. ZIPs of earlier stands are
removed, the GML is replaced.

Usage:
    python scripts/01_download_alkis_hh.py [--force]
"""

import os
import sys
import glob
import zipfile
import argparse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alkis_sources
import alkis_download as dl

ALKIS_DIR = os.path.join("data", "hh", "alkis")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true", help="download and unpack even if unchanged")
    args = parser.parse_args()

    os.makedirs(ALKIS_DIR, exist_ok=True)
    session = requests.Session()
    latest = alkis_sources.hh_latest_download(session=session)
    if not latest:
        print("[HH] No ALKIS_Adressen_HH_*.zip listed in the current CKAN dataset.")
        return 1
    print(f"[HH] Newest: {latest['name']} ({latest['size']} bytes)")
    manifest = dl.Manifest(ALKIS_DIR)
    zip_path = os.path.join(ALKIS_DIR, latest["name"])
    downloaded = dl.fetch(latest["url"], ALKIS_DIR, latest["name"], manifest,
                          remote={"size": latest["size"]}, session=session, force=args.force,
                          stand=latest["date"])
    manifest.save()

    gmls = glob.glob(os.path.join(ALKIS_DIR, "*.gml"))
    if downloaded or args.force or not gmls or any(os.path.getmtime(zip_path) > os.path.getmtime(g)
                                                   for g in gmls):
        with zipfile.ZipFile(zip_path) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith(".gml")]
            if not members:
                print(f"[HH] {latest['name']} contains no GML.")
                return 1
            new = [os.path.join(ALKIS_DIR, os.path.basename(n)) for n in members]
            for n, path in zip(members, new):
                print(f"[HH] Unpacking {n}")
                with zf.open(n) as src, open(path + ".part", "wb") as dst:
                    while chunk := src.read(1 << 20):
                        dst.write(chunk)
        for g in set(gmls) - set(new):
            os.remove(g)
        for path in new:
            os.replace(path + ".part", path)
    else:
        print("[HH] GML is up to date.")

    for old in glob.glob(os.path.join(ALKIS_DIR, "ALKIS_Adressen_HH_*.zip")):
        if os.path.basename(old) != latest["name"]:
            print(f"[HH] Removing {os.path.basename(old)}")
            os.remove(old)
            manifest.drop(os.path.basename(old))
    manifest.save()
    print("[HH] Done. Next: python scripts/02_extract_alkis.py --state HH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
