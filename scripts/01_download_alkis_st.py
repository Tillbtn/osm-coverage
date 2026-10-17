"""
Download the ST GBIS_Gebaeude ZIP and unpack it to
data/st/alkis/GBIS_Gebaeude/ (what 02 reads).

The ZIP is rebuilt every night, so its Last-Modified and the timeStamp in the
XMLs are the date of that build. The ZIP (~180 MB) is not kept: the unpacked
directory is replaced as a whole, which also drops stale GDAL .gfs files.

Usage:
    python scripts/01_download_alkis_st.py [--force]
"""

import os
import sys
import argparse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alkis_sources
import alkis_download as dl

URL = alkis_sources.download_url("st")
ALKIS_DIR = os.path.join("data", "st", "alkis")
ZIP_NAME = "GBIS_Gebaeude.zip"
TARGET_DIR = os.path.join(ALKIS_DIR, "GBIS_Gebaeude")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true",
                        help="download even if the local data is from the same build")
    args = parser.parse_args()

    os.makedirs(ALKIS_DIR, exist_ok=True)
    session = requests.Session()
    manifest = dl.Manifest(ALKIS_DIR)
    remote = dl.head_attrs(URL, session=session)
    stand = dl.http_date(remote["last_modified"])
    print(f"[ST] {URL}: {remote['size']} bytes, built {remote['last_modified']}")
    if (not args.force and os.path.isdir(TARGET_DIR)
            and manifest.get(ZIP_NAME).get("etag") == remote["etag"]):
        print(f"[ST] {TARGET_DIR} is from this build already, nothing to do.")
        return 0

    zip_path = os.path.join(ALKIS_DIR, ZIP_NAME)
    dl.download(URL, zip_path, session=session, expected_size=remote["size"])
    print(f"[ST] Unpacking to {TARGET_DIR}")
    try:
        dl.extract_zip(zip_path, TARGET_DIR)
    finally:
        os.remove(zip_path)
    manifest.record(ZIP_NAME, url=URL, size=remote["size"], etag=remote["etag"],
                    last_modified=remote["last_modified"], stand=stand)
    manifest.save()
    print("[ST] Done. Next: python scripts/02_extract_alkis.py --state ST")
    return 0


if __name__ == "__main__":
    sys.exit(main())
