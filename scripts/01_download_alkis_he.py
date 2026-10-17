"""
Download the newest HE Hauskoordinaten (HVBG Downloadcenter) into data/he/alkis/.

The Downloadcenter lists its files as JSON (scripts/alkis_sources.py,
he_latest_download); the ZIP link in it is only valid on the day it is listed.
The ZIP holds one .txt, extracted as '<download name>.txt' so the Ausgabe stays
readable from the filename (detect_alkis_date in 02). 02 reads every *.txt in
data/he/alkis/, so the .txt of an older Ausgabe is removed; the ZIPs are kept.

Skips the download when the newest Ausgabe is already extracted (--force
downloads anyway).

Usage:
    python scripts/01_download_alkis_he.py
    python scripts/01_download_alkis_he.py --force
"""

import os
import sys
import glob
import zipfile
import argparse

import requests
import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alkis_sources

ALKIS_DIR = os.path.join("data", "he", "alkis")


def extracted_dates():
    """Ausgabe dates of the .txt files 02 would read."""
    return {p: alkis_sources.he_filename_date(os.path.basename(p))
            for p in glob.glob(os.path.join(ALKIS_DIR, "*.txt"))}


def download(url, zip_path, session):
    """Stream to '<zip>.part', check the length, then move into place."""
    part = zip_path + ".part"
    with session.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        with open(part, "wb") as f, tqdm.tqdm(desc="Downloading", total=total, unit="iB",
                                              unit_scale=True, unit_divisor=1024) as bar:
            for chunk in resp.iter_content(1 << 20):
                bar.update(f.write(chunk))
    got = os.path.getsize(part)
    if total and got != total:
        os.remove(part)
        raise IOError(f"incomplete download: {got} of {total} bytes")
    os.replace(part, zip_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true",
                        help="download even if the newest Ausgabe is already extracted")
    args = parser.parse_args()

    session = requests.Session()
    latest = alkis_sources.he_latest_download(session=session)
    if not latest:
        print("[HE] Downloadcenter lists no Hauskoordinaten download.")
        return 1
    print(f"[HE] Newest Ausgabe: {latest['date']} ({latest['name']}, "
          f"created {latest['created']}, {latest['size']})")

    existing = extracted_dates()
    if latest["date"] in existing.values() and not args.force:
        print("[HE] Already extracted, nothing to do.")
        return 0

    os.makedirs(ALKIS_DIR, exist_ok=True)
    zip_path = os.path.join(ALKIS_DIR, latest["name"] + ".zip")
    txt_path = os.path.join(ALKIS_DIR, latest["name"] + ".txt")
    print(f"[HE] Downloading {latest['url']}")
    download(latest["url"], zip_path, session)

    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(".txt")]
        if len(members) != 1:
            print(f"[HE] Expected one .txt in the ZIP, found {members}.")
            return 1
        print(f"[HE] Extracting {members[0]} -> {txt_path}")
        with zf.open(members[0]) as src, open(txt_path + ".part", "wb") as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)
    os.replace(txt_path + ".part", txt_path)

    for path in existing:
        if os.path.abspath(path) != os.path.abspath(txt_path):
            print(f"[HE] Removing superseded {os.path.basename(path)}")
            os.remove(path)

    print(f"[HE] Done. Next: python scripts/02_extract_alkis.py --state HE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
