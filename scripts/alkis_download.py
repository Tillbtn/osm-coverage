"""
Download and unpack helpers shared by the 01_download_alkis_*.py scripts.

  download()       stream to '<dest>.part', check Content-Length (and an MD5 when
                   one is known), then move into place, so an interrupted download
                   never leaves a truncated file under the final name
  extract_zip()    unpack into a fresh sibling directory and swap it in for the
                   target, so files dropped from a new release don't linger
  needs_extract()  a ZIP is newer than the directory it was unpacked into
  Manifest         per-directory '.downloads.json' recording what each file was
                   downloaded as (size, ETag, Last-Modified, upstream stand), used
                   to skip unchanged files and as the stand of the local data
"""

import os
import re
import json
import shutil
import hashlib
import zipfile
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

import requests
import tqdm

MANIFEST_NAME = ".downloads.json"
TIMEOUT = (30, 300)  # connect, read (seconds without data)


class DownloadError(Exception):
    pass


def md5_etag(etag):
    """The MD5 an ETag stands for, if it is a plain single-part one."""
    m = re.fullmatch(r'(?:W/)?"?([0-9a-fA-F]{32})"?', etag or "")
    return m.group(1).lower() if m else None


def download(url, dest, session=None, verify=True, expected_size=None, expected_md5=None,
             progress=True):
    """
    Stream `url` to `dest`. Raises DownloadError when the body is shorter or
    longer than announced or the MD5 does not match; the partial file is removed.
    Returns the response headers.
    """
    session = session or requests.Session()
    part = dest + ".part"
    md5 = hashlib.md5()
    try:
        with session.get(url, stream=True, verify=verify, timeout=TIMEOUT) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0) or expected_size or 0
            with open(part, "wb") as f, tqdm.tqdm(
                    desc=os.path.basename(dest), total=total or None, unit="iB",
                    unit_scale=True, unit_divisor=1024, disable=not progress, leave=False) as bar:
                for chunk in resp.iter_content(1 << 20):
                    f.write(chunk)
                    md5.update(chunk)
                    bar.update(len(chunk))
            headers = resp.headers
        got = os.path.getsize(part)
        # requests decodes a Content-Encoding, so Content-Length is not the file size then
        announced = 0 if headers.get("Content-Encoding") else int(headers.get("Content-Length") or 0)
        for expected in {announced, expected_size or 0} - {0}:
            if got != expected:
                raise DownloadError(f"{os.path.basename(dest)}: got {got} of {expected} bytes")
        if expected_md5 and md5.hexdigest() != expected_md5.lower():
            raise DownloadError(f"{os.path.basename(dest)}: MD5 mismatch")
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise
    os.replace(part, dest)
    return headers


def http_date(value):
    """'Wed, 26 Aug 2026 09:57:10 GMT' -> '2026-08-26', or None."""
    try:
        return parsedate_to_datetime(value).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def head_attrs(url, session=None, verify=True):
    """size / etag / last_modified of `url` from a HEAD request."""
    session = session or requests.Session()
    resp = session.head(url, allow_redirects=True, verify=verify, timeout=TIMEOUT)
    resp.raise_for_status()
    return {"size": int(resp.headers.get("Content-Length") or 0) or None,
            "etag": resp.headers.get("ETag"),
            "last_modified": resp.headers.get("Last-Modified")}


def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def _matches(path, remote):
    """The local file has the remote size, and its MD5 if the ETag carries one."""
    if not os.path.exists(path) or not remote.get("size") or os.path.getsize(path) != remote["size"]:
        return False
    md5 = md5_etag(remote.get("etag"))
    return md5 is None or file_md5(path) == md5


def fetch(url, directory, name, manifest, remote=None, session=None, verify=True,
          force=False, stand=None, progress=True):
    """
    Download `url` to `directory/name` unless the manifest shows the same remote
    file (by `remote` attributes, from a HEAD request if not given) is already
    there. A local file the manifest does not know yet is adopted when it has the
    remote size (and MD5, if the ETag is one). Records the result in the manifest
    (saved by the caller). Returns True if the file was downloaded.
    """
    session = session or requests.Session()
    if remote is None:
        remote = head_attrs(url, session=session, verify=verify)
    path = os.path.join(directory, name)
    if not force and manifest.is_current(name, directory, **remote):
        print(f"  {name}: unchanged, skipped")
        return False
    if not force and not manifest.get(name) and _matches(path, remote):
        # a file from before the manifest existed: adopt it instead of re-downloading
        manifest.record(name, **{**remote, "url": url, "adopted": True,
                                 "stand": stand or remote.get("stand")})
        print(f"  {name}: already present (same size{', MD5' if md5_etag(remote.get('etag')) else ''}), adopted")
        return False
    headers = download(url, path, session=session, verify=verify,
                       expected_size=remote.get("size"),
                       expected_md5=md5_etag(remote.get("etag")), progress=progress)
    manifest.record(name, url=url, size=os.path.getsize(path),
                    etag=remote.get("etag") or headers.get("ETag"),
                    last_modified=remote.get("last_modified") or headers.get("Last-Modified"),
                    stand=stand or remote.get("stand"))
    return True


def fetch_many(items, directory, manifest, workers=4, force=False, verify=True):
    """
    fetch() each item ({url, name, remote?, stand?}) with `workers` threads,
    saving the manifest after every download. Returns (downloaded names,
    {name: error} for failures).
    """
    lock = threading.Lock()
    downloaded, failed = [], {}

    def one(item):
        session = requests.Session()
        try:
            if fetch(item["url"], directory, item["name"], manifest, remote=item.get("remote"),
                     session=session, verify=verify, force=force, stand=item.get("stand"),
                     progress=False):
                manifest.save()
                with lock:
                    downloaded.append(item["name"])
                print(f"  {item['name']}: downloaded")
        except Exception as e:
            with lock:
                failed[item["name"]] = str(e)
            print(f"  {item['name']}: FAILED ({e})")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, items))
    return downloaded, failed


def extract_zip(zip_path, target_dir, members=None):
    """
    Unpack `zip_path` (only `members` if given) into `target_dir`, replacing it.
    Raises zipfile.BadZipFile / OSError on failure, leaving `target_dir` as it was.
    """
    parent = os.path.dirname(os.path.abspath(target_dir))
    tmp = tempfile.mkdtemp(prefix=".extract-", dir=parent)
    umask = os.umask(0)
    os.umask(umask)
    os.chmod(tmp, 0o777 & ~umask)  # mkdtemp creates it 0700
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp, members=members)
        if os.path.isdir(target_dir):
            old = tempfile.mkdtemp(prefix=".old-", dir=parent)
            os.rmdir(old)
            os.rename(target_dir, old)
            os.rename(tmp, target_dir)
            shutil.rmtree(old)
        else:
            os.rename(tmp, target_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def needs_extract(zip_path, target_dir):
    return not os.path.isdir(target_dir) or os.path.getmtime(zip_path) > os.path.getmtime(target_dir)


def extract_each(directory, names, force=False):
    """
    Unpack each ZIP `directory/name` into '<name without .zip>/' when needed
    (or always with `force`). Returns {name: error} for ZIPs that failed.
    """
    failed = {}
    for name in names:
        zip_path = os.path.join(directory, name)
        target = os.path.splitext(zip_path)[0]
        if not os.path.exists(zip_path) or not (force or needs_extract(zip_path, target)):
            continue
        print(f"  unpacking {name}")
        try:
            extract_zip(zip_path, target)
        except Exception as e:
            failed[name] = f"unpack: {e}"
            print(f"  {name}: unpack FAILED ({e})")
    return failed


def unlisted_zips(directory, names):
    """ZIPs in `directory` that are not among `names` (dropped upstream)."""
    return sorted(f for f in os.listdir(directory) if f.endswith(".zip") and f not in set(names))


class Manifest:
    """'.downloads.json' in a data directory: file name -> download record."""

    def __init__(self, directory):
        self.path = os.path.join(directory, MANIFEST_NAME)
        self._lock = threading.Lock()
        try:
            with open(self.path, encoding="utf-8") as f:
                self.entries = json.load(f)
        except (OSError, ValueError):
            self.entries = {}

    def get(self, name):
        return self.entries.get(name) or {}

    def is_current(self, name, directory, **remote):
        """True if `name` exists locally and was downloaded with the same remote
        attributes (e.g. size=…, etag=…); attributes that are None are ignored."""
        entry = self.get(name)
        if not entry or not os.path.exists(os.path.join(directory, name)):
            return False
        known = {k: v for k, v in remote.items() if v is not None}
        return bool(known) and all(entry.get(k) == v for k, v in known.items())

    def record(self, name, **fields):
        with self._lock:
            self.entries[name] = {k: v for k, v in fields.items() if v is not None}

    def drop(self, name):
        with self._lock:
            self.entries.pop(name, None)

    def save(self):
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, indent=2, ensure_ascii=False, sort_keys=True)
            os.replace(tmp, self.path)

    def stand(self):
        """Newest upstream stand recorded for any file, or None."""
        stands = [e["stand"] for e in self.entries.values() if e.get("stand")]
        return max(stands) if stands else None
