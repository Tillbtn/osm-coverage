"""
Download the NRW gru_vereinfacht GPKG ZIPs (one per Kreis / kreisfreie Stadt)
and unpack them in data/nrw/alkis/.

The opengeodata index lists name, size and build timestamp of every ZIP; a file
is re-downloaded when size or timestamp differ from data/nrw/alkis/.downloads.json
and re-unpacked into <name>/ when the ZIP is newer than that directory. Local
ZIPs the manifest does not know yet are adopted when their size matches. Exits 1
if any file failed; the others are kept.

Usage:
    python scripts/01_download_alkis_nrw.py [--force] [--only Düsseldorf]
"""

import os
import sys
import argparse
import xml.etree.ElementTree as ET

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alkis_sources
import alkis_download as dl

BASE_URL = alkis_sources.download_url("nrw")
ALKIS_DIR = os.path.join("data", "nrw", "alkis")


def index_files(session):
    resp = session.get(BASE_URL, timeout=dl.TIMEOUT)
    resp.raise_for_status()
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        resp = session.get(BASE_URL + "index.html", timeout=dl.TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    return [f.attrib for f in root.findall(".//file") if f.get("name", "").endswith(".zip")]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true", help="download and unpack everything")
    parser.add_argument("--only", help="only files whose name contains this text")
    args = parser.parse_args()

    os.makedirs(ALKIS_DIR, exist_ok=True)
    session = requests.Session()
    items = []
    for f in index_files(session):
        if args.only and args.only not in f["name"]:
            continue
        timestamp = f.get("timestamp")
        items.append({"url": BASE_URL + f["name"], "name": f["name"],
                      "remote": {"size": int(f["size"]) if f.get("size") else None,
                                 "timestamp": timestamp},
                      "stand": timestamp[:10] if timestamp else None})
    print(f"[NRW] {len(items)} ZIPs listed (newest build {max((i['stand'] or '' for i in items), default='') or '?'})")

    manifest = dl.Manifest(ALKIS_DIR)
    downloaded, failed = dl.fetch_many(items, ALKIS_DIR, manifest, force=args.force)
    manifest.save()

    names = [i["name"] for i in items]
    failed.update(dl.extract_each(ALKIS_DIR, [n for n in names if n not in failed], force=args.force))
    if not args.only and (stale := dl.unlisted_zips(ALKIS_DIR, names)):
        print(f"[NRW] Not listed upstream any more (02 still reads them): {', '.join(stale)}")

    print(f"[NRW] {len(downloaded)} downloaded, {len(items) - len(downloaded) - len(failed)} unchanged, "
          f"{len(failed)} failed")
    if failed:
        return 1
    print("[NRW] Next: python scripts/02_extract_alkis.py --state NRW")
    return 0


if __name__ == "__main__":
    sys.exit(main())
