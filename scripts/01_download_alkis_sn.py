"""
Download the SN Hauskoordinaten (hk_sn_ascii.zip from the GeoSN cloud share)
and unpack hk_sn_adressen_<YYYYMMDD>.txt into data/sn/alkis/.

The share answers HEAD with 401, so the remote file is identified by a ranged
GET of its last 64 KB: ETag, total size and the ZIP's central directory, whose
member name carries the stand. Earlier hk_sn_adressen_* files are renamed to
*.old (02 reads only the newest one anyway).

Usage:
    python scripts/01_download_alkis_sn.py [--force]
"""

import io
import os
import re
import sys
import glob
import zipfile
import argparse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alkis_sources
import alkis_download as dl

URL = alkis_sources.download_url("sn")
ALKIS_DIR = os.path.join("data", "sn", "alkis")
ZIP_NAME = "hk_sn_ascii.zip"
MEMBER_RE = re.compile(r"hk_sn_adressen_(\d{4})(\d{2})(\d{2})\.(txt|csv)$")


def remote_attrs(session):
    """size / etag / last_modified / member / stand of the remote ZIP."""
    resp = session.get(URL, headers={"Range": "bytes=-65536"}, timeout=dl.TIMEOUT)
    resp.raise_for_status()
    if resp.status_code != 206:
        raise RuntimeError(f"no range support (HTTP {resp.status_code})")
    size = int(resp.headers["Content-Range"].rsplit("/", 1)[1])
    members = [i.filename for i in zipfile.ZipFile(io.BytesIO(resp.content)).infolist()
               if MEMBER_RE.search(i.filename)]
    if len(members) != 1:
        raise RuntimeError(f"expected one hk_sn_adressen_* member, found {members}")
    y, m, d, _ = MEMBER_RE.search(members[0]).groups()
    return {"size": size, "etag": resp.headers.get("ETag"),
            "last_modified": resp.headers.get("Last-Modified"),
            "member": members[0], "stand": f"{y}-{m}-{d}"}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true", help="download and unpack even if unchanged")
    args = parser.parse_args()

    os.makedirs(ALKIS_DIR, exist_ok=True)
    session = requests.Session()
    remote = remote_attrs(session)
    print(f"[SN] {ZIP_NAME}: {remote['member']} (stand {remote['stand']}), {remote['size']} bytes")
    manifest = dl.Manifest(ALKIS_DIR)
    member = remote.pop("member")
    if dl.fetch(URL, ALKIS_DIR, ZIP_NAME, manifest, remote=remote, session=session, force=args.force):
        manifest.save()

    txt_path = os.path.join(ALKIS_DIR, os.path.basename(member))
    if os.path.exists(txt_path) and not args.force:
        print(f"[SN] {os.path.basename(txt_path)} already unpacked.")
    else:
        print(f"[SN] Unpacking {member}")
        with zipfile.ZipFile(os.path.join(ALKIS_DIR, ZIP_NAME)) as zf:
            with zf.open(member) as src, open(txt_path + ".part", "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
        os.replace(txt_path + ".part", txt_path)

    for path in glob.glob(os.path.join(ALKIS_DIR, "*")):
        if MEMBER_RE.search(os.path.basename(path)) and path != txt_path:
            print(f"[SN] Renaming superseded {os.path.basename(path)} to *.old")
            os.replace(path, path + ".old")
    print("[SN] Done. Next: python scripts/02_extract_alkis.py --state SN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
