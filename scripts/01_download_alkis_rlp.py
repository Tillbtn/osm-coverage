"""
Download the RLP Hauskoordinaten ZIP and unpack it to
data/rlp/alkis/HAUSKOORDINATEN_RP/ (what 02 reads).

Skips the download when the remote ZIP (size/ETag/Last-Modified) matches the one
recorded in data/rlp/alkis/.downloads.json, and the unpacking when the directory
is newer than the ZIP. A failed download or unpack leaves the previous data in place.

Usage:
    python scripts/01_download_alkis_rlp.py [--force]
"""

import os
import sys
import argparse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alkis_sources
import alkis_download as dl

SOURCE = alkis_sources.SOURCES["rlp"]["download"]
ALKIS_DIR = os.path.join("data", "rlp", "alkis")
ZIP_NAME = "HAUSKOORDINATEN_RP.zip"
TARGET_DIR = os.path.join(ALKIS_DIR, "HAUSKOORDINATEN_RP")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true", help="download and unpack even if unchanged")
    args = parser.parse_args()

    os.makedirs(ALKIS_DIR, exist_ok=True)
    session = requests.Session()
    verify = SOURCE.get("verify", True)
    manifest = dl.Manifest(ALKIS_DIR)
    remote = dl.head_attrs(SOURCE["url"], session=session, verify=verify)
    print(f"[RLP] {SOURCE['url']}: {remote['size']} bytes, Last-Modified {remote['last_modified']}")
    if dl.fetch(SOURCE["url"], ALKIS_DIR, ZIP_NAME, manifest, remote=remote, session=session,
                verify=verify, force=args.force, stand=dl.http_date(remote["last_modified"])):
        manifest.save()

    zip_path = os.path.join(ALKIS_DIR, ZIP_NAME)
    if args.force or dl.needs_extract(zip_path, TARGET_DIR):
        print(f"[RLP] Unpacking to {TARGET_DIR}")
        dl.extract_zip(zip_path, TARGET_DIR)
        print("[RLP] Done. Next: python scripts/02_extract_alkis.py --state RLP")
    else:
        print(f"[RLP] {TARGET_DIR} is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
