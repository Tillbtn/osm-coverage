"""
Canonical ALKIS source registry + cheap "remote freshness" probes.

One entry per participating state describing where its ALKIS data comes from and
how to read the latest available export date without downloading the full
dataset.

check_alkis_dates.py builds the status dashboard JSON from this.

Probe strategies (the `probe` field):
  http_last_modified  HEAD the file, parse the HTTP Last-Modified header
  nrw_index           GET the opengeodata index, take max of <file timestamp=...>
  nds_metadata        GET the metadata GeoJSON, take max of the aktualitaet field
  hh_ckan             search the transparenz.hamburg.de CKAN for the current ALKIS
                      Adressen dataset, newest YYYY-MM-DD in its ZIP file names
  mv_zip_header       stream the first bytes of a few Gemeinde ZIPs from the MV
                      download service and read the member date of the first local
                      file header (the date the service built the ZIP)
  sn_changelog        GET the geodaten.sachsen.de Atom changelog, newest entry whose
                      title mentions HK (Hauskoordinaten — the address product)
  he_downloadcenter   GET the JSON behind the HVBG Downloadcenter page, Ausgabe
                      'YYYY/N' from the newest download's name
  lgb_gazetteer       GET one feature of the LGB gazetteer (OGC API Features) for the
                      state's landschluessel and read its 'akt' date; the gazetteer
                      carries the Hauskoordinaten of Brandenburg and Berlin

A source with `release_months` publishes the product we ingest only at the end of
those months, while its probe tracks a more frequent upstream update; the probed
date is rounded down to the last such release (e.g. 2026-10-30 -> 2026-09-30).
  none                no cheap remote probe (manual portal / order process)

`automated` reflects whether 01 can fetch the data unattended; a source can be
automated (RLP, ST) yet still have no per-file date embedded, or manual (BB, SN)
yet carry a date once downloaded (handled post-download by detect_alkis_date in
02_extract_alkis.py).
"""

import re
import json
import struct
import datetime
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

# Reuse the frontend's display names so the dashboard labels match the map.
STATE_NAMES = {
    "bb": "Brandenburg",
    "be": "Berlin",
    "hh": "Hamburg",
    "mv": "Mecklenburg-Vorpommern",
    "nds": "Niedersachsen",
    "nrw": "Nordrhein-Westfalen",
    "rlp": "Rheinland-Pfalz",
    "he": "Hessen",
    "sn": "Sachsen",
    "st": "Sachsen-Anhalt",
}

_NDS_METADATA_URL = (
    "https://arcgis-geojson.s3.eu-de.cloud-object-storage.appdomain.cloud/"
    "alkis-vektor/lgln-opengeodata-alkis-vektor.geojson"
)
_NRW_INDEX_URL = "https://www.opengeodata.nrw.de/produkte/geobasis/lk/akt/gru_vereinfacht_gpkg/"
_RLP_ZIP_URL = "https://geobasis-rlp.de/data/hk/current/zip/HAUSKOORDINATEN_RP.zip"
_ST_ZIP_URL = ("https://geodatenportal.sachsen-anhalt.de/gfds_webshare/download/"
               "LVermGeo/Geodatenportal/externedaten/GBIS_Gebaeude.zip")
# The dataset is re-created under a new id (…hamburg25, …hamburg26) now and
# then, so it is looked up by name pattern, newest first.
_HH_CKAN_URL = ("https://suche.transparenz.hamburg.de/api/3/action/package_search"
                "?q=name:alkis-adressen-hamburg*&sort=metadata_modified%20desc&rows=1")
_MV_ATOM_URL = "https://www.geoportal-mv.de/portal/Geodatenviewer/Datenaktualisierungen/Atom"
_MV_DOWNLOAD_PATTERN = ("https://www.geodaten-mv.de/dienste/alkis_nas_download?index=1&"
                        "dataset=32538df8-6b74-4582-8591-c77e85fbf929&file={id}_SHP_{name}.zip")
_MV_PROBE_URLS = [
    _MV_DOWNLOAD_PATTERN.format(id="13004000", name="Schwerin__Landeshauptstadt"),
    _MV_DOWNLOAD_PATTERN.format(id="13003000", name="Rostock__Hanse__und_Universit%C3%A4tsstadt"),
]
_SN_CHANGELOG_URL = "https://www.geodaten.sachsen.de/changelog.xml"
_SN_ZIP_URL = ("https://geocloud.landesvermessung.sachsen.de/public.php/dav/files/"
               "B3HnXbDDgAkw69a/hk_sn_ascii.zip")
# JSON endpoint the Downloadcenter page's script renders from.
_HE_DOWNLOADCENTER_URL = (
    "https://gds.hessen.de/INTERSHOP/rest/WFS/HLBG-Geodaten-Site/-/downloadcenter"
    "?path=Liegenschaftskataster/Hauskoordinaten%20ohne%20Postalische%20Angaben%20(txt)")
_HE_DOWNLOAD_HOST = "https://gds.hessen.de"
_LGB_GAZETTEER_URL = "https://ogc-api.geobasis-bb.de/datasets/gaz/collections/Hauskoordinaten"

# The Städteregion Aachen publishes its Gebäudereferenzen as a WFS that refreshes
# daily — far more current than NRW's state-wide gru_vereinfacht_gpkg product. It
# is modelled as an NRW sub-source: fetch_alkis_wfs.py replaces just that district
# inside data/nrw/alkis.parquet, and 04 surfaces its own date on the map.
_AACHEN_WFS = {
    "key": "aachen",
    "label": "Städteregion Aachen",
    "type": "wfs",              # registry classification (see wfs_sub_sources())
    "cadence": "daily",
    "probe": "wfs_field",       # 1-feature GetFeature reading date_field
    # --- fetch_alkis_wfs.py fields ---
    "base_url": "https://geodienste.staedteregion-aachen.de/?MAP=gebaeudereferenzen.qgs",
    "typename": "Gebaeudereferenzen_StaedteregionAachen",
    "version": "1.1.0",
    "count_param": "maxFeatures",
    "srs": "EPSG:25832",
    "page_size": 25000,         # smaller pages fail less often (see _fetch_page)
    "state_dir": "nrw",
    "state_label": "NRW",
    "mode": "district",         # fetch_alkis_wfs behaviour: replace one district
    "district": "Städteregion Aachen",
    "date_field": "datum_auswertung",
    "field_map": {
        "street": "strasse_lage",
        "hnr": "hsnr",
        "hnr_suffix": "hsnrzus",
        "city": "gmdname",
    },
    "extra_separators": ["/"],
}

# key -> descriptor. Single source of truth for downloading, freshness probing,
# and the per-district timestamps 04 writes into the stat reports.
#   probe / url        : cheap remote freshness probe (dashboard "latest upstream")
#   download           : {method, url, ...} consumed by 01_download_alkis_*.py
#   sub_sources        : nested per-district sources (e.g. WFS) with own cadence
SOURCES = {
    "nds": {
        "automated": True, "source_type": "metadata_geojson",
        "probe": "nds_metadata", "url": _NDS_METADATA_URL,
        "download": {"method": "metadata_geojson", "url": _NDS_METADATA_URL},
    },
    "nrw": {
        "automated": True, "source_type": "index_xml",
        "probe": "nrw_index", "url": _NRW_INDEX_URL,
        "download": {"method": "opengeodata_index", "url": _NRW_INDEX_URL},
        # The index timestamp is the build date of the product we ingest
        # (gru_vereinfacht_gpkg). NRW also offers a newer Gebäudereferenzen feed
        # via ogc-api.nrw.de/gebref — a possible future migration.
        "note": "Landesweites Update quartalsweise",
        "sub_sources": [_AACHEN_WFS],
    },
    "rlp": {
        "automated": True, "source_type": "direct_zip",
        "probe": "http_last_modified", "url": _RLP_ZIP_URL,
        "download": {"method": "direct_zip", "url": _RLP_ZIP_URL},
    },
    "st": {
        # GBIS_Gebaeude.zip is a nightly export of the ALKIS-vereinfacht
        # GebaeudeBauwerk layer that the OpenData WFS ST_LVermGeo_ALKIS_WFS_OpenData
        # also serves; it carries changes up to the previous working day. Its
        # Last-Modified and the XMLs' timeStamp are the date of that export. The
        # open-data page does not link the ZIP (its "Gebäudereferenzen Stand"
        # belongs to a different, quarterly product).
        "automated": True, "source_type": "direct_zip", "cadence": "daily",
        "probe": "http_last_modified", "url": _ST_ZIP_URL,
        "download": {"method": "direct_zip", "url": _ST_ZIP_URL},
        "note": "Nächtlicher Export",
    },
    "mv": {
        "automated": True, "source_type": "download_service",
        "probe": "mv_zip_header", "url": _MV_ATOM_URL, "probe_urls": _MV_PROBE_URLS,
        "download": {"method": "nas_download_service", "url": _MV_DOWNLOAD_PATTERN},
        "note": "Shape-ZIPs des Downloaddienstes, monatlich neu gebaut",
    },
    "hh": {
        "automated": True, "source_type": "portal",
        "probe": "hh_ckan", "url": _HH_CKAN_URL,
        "download": {"method": "hh_ckan", "url": _HH_CKAN_URL},
        "note": "Transparenzportal Hamburg; Update quartalsweise",
    },
    "he": {
        # The download link carries the request date (/downloadcenter/YYYYMMDD/…)
        # and 404s on any other day, so 01 reads it fresh from the same JSON.
        "automated": True, "source_type": "download_center",
        "probe": "he_downloadcenter",
        "url": ("https://gds.hessen.de/INTERSHOP/web/WFS/HLBG-Geodaten-Site/de_DE/-/EUR/"
                "ViewDownloadcenter-Start?path=Liegenschaftskataster/"
                "Hauskoordinaten%20ohne%20Postalische%20Angaben%20(txt)"),
        "download": {"method": "he_downloadcenter", "url": _HE_DOWNLOADCENTER_URL},
        "note": "HVBG Downloadcenter",
    },
    "bb": {
        # The gazetteer carries the same addresses as the Geobroker product but
        # lagging street names; 01_download_alkis_bb.py fetches it only as a
        # fallback. Its 'akt' is the stand of the Geobroker 'aud' column; the
        # gazetteer is updated monthly, the Geobroker product only with the
        # stands 31.03. and 30.09. (its 'aud' then reads e.g. 2026-03-31).
        "automated": False, "source_type": "order",
        "probe": "lgb_gazetteer", "url": _LGB_GAZETTEER_URL, "landschluessel": "12",
        "release_months": (3, 9),
        "download": {"method": "manual", "url": "https://geobroker.geobasis-bb.de"},
        "note": "Halbjährlich (Stand 31.03./30.09.); Bestellung über Geobroker",
    },
    "be": {
        "automated": False, "source_type": "portal",
        "probe": "lgb_gazetteer", "url": _LGB_GAZETTEER_URL, "landschluessel": "11",
        "download": {"method": "manual", "url": "https://gdi.berlin.de/geonetwork"},
        "note": "Stand aus dem LGB-Gazetteer; Download manuell über GDI Berlin",
    },
    "sn": {
        # public share linked from the Downloadbereich Hauskoordinaten
        "automated": True, "source_type": "direct_zip",
        "probe": "sn_changelog", "url": _SN_CHANGELOG_URL,
        "download": {"method": "direct_zip", "url": _SN_ZIP_URL},
        "note": "Downloadbereich Hauskoordinaten (GeoSN)",
    },
}


def download_url(state):
    """Canonical download URL for a state (what 01_download_alkis_*.py fetches)."""
    return (SOURCES.get(state, {}).get("download") or {}).get("url")


def wfs_sub_sources():
    """Flatten all WFS sub-sources across states (consumed by fetch_alkis_wfs.py)."""
    out = []
    for cfg in SOURCES.values():
        for sub in cfg.get("sub_sources", []):
            if sub.get("type") == "wfs":
                out.append(sub)
    return out


# rigin of each probe strategy, shown on the dashboard so it is
# clear *where* an "upstream" date comes from
PROBE_LABELS = {
    "http_last_modified": "HTTP Last-Modified",
    "nrw_index": "opengeodata-Index (timestamp)",
    "nds_metadata": "GeoJSON-Metadaten",
    "hh_ckan": "Transparenzportal (CKAN)",
    "mv_zip_header": "Downloaddienst (ZIP-Datum)",
    "sn_changelog": "changelog.xml (HK/HU)",
    "wfs_field": "WFS (datum_auswertung)",
    "he_downloadcenter": "Downloadcenter (Ausgabe)",
    "lgb_gazetteer": "LGB-Gazetteer (akt)",
    "none": None,
}


def probe_label(probe):
    """Display label for a probe strategy (the origin of a remote/upstream date)."""
    return PROBE_LABELS.get(probe)


def describe_meta_source(src):
    """
    Turn the `source` string stored in alkis_meta.json (written by 02 /
    fetch_alkis_wfs) into a readable origin for the 'Verarbeitet' date.
    """
    if not src:
        return None
    if src.startswith("remote:"):
        probe = src.split(":", 1)[1]
        label = PROBE_LABELS.get(probe) or probe
        return f"{label} (beim Abruf)"
    if src.startswith("wfs:"):
        return f"WFS {src.split(':', 1)[1]}"
    if src.startswith("metadata:"):
        return src.split(":", 1)[1]
    if src.startswith("column:"):
        return f"GPKG-Spalte „{src.split(':', 1)[1]}“"
    return {"filename": "Dateiname", "manual": "manuell",
            "download manifest": "Download-Protokoll (01)"}.get(src, src)


def _last_modified_date(url, verify=True, session=None, timeout=30):
    """HEAD `url` and return its Last-Modified as 'YYYY-MM-DD', or None."""
    session = session or requests.Session()
    if not verify:
        requests.packages.urllib3.disable_warnings()
    resp = session.head(url, verify=verify, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    lm = resp.headers.get("Last-Modified")
    if not lm:
        return None
    dt = datetime.datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S %Z")
    return dt.strftime("%Y-%m-%d")


def _nrw_index_date(url, session=None, timeout=60):
    """Max of the <file timestamp="..."> attributes in the opengeodata index."""
    session = session or requests.Session()
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        resp = session.get(url.rstrip("/") + "/index.html", timeout=timeout)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    stamps = [f.get("timestamp") for f in root.findall(".//file") if f.get("timestamp")]
    if not stamps:
        return None
    return max(stamps)[:10]


def _nds_metadata_date(url, session=None, timeout=120):
    """Max of the 'aktualitaet-*' date field across the metadata GeoJSON features."""
    session = session or requests.Session()
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    dates = []
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        for k, v in props.items():
            if k.startswith("aktualitaet") and v:
                dates.append(str(v)[:10])
    return max(dates) if dates else None


def hh_latest_download(session=None, timeout=60):
    """
    Newest ALKIS_Adressen_HH_<YYYY-MM-DD>.zip of the current CKAN dataset, as
    {url, name, date, size}, or None. The date comes from the file name: the
    resource names do not always match it ("2020-04" links the 2019-04 file).
    """
    session = session or requests.Session()
    resp = session.get(_HH_CKAN_URL, timeout=timeout)
    resp.raise_for_status()
    results = (resp.json().get("result") or {}).get("results") or []
    entries = []
    for r in (results[0].get("resources") or []) if results else []:
        url = r.get("url") or ""
        m = re.search(r"/(ALKIS_Adressen_HH_(\d{4}-\d{2}-\d{2})\.zip)$", url)
        if m:
            entries.append({"url": url, "name": m.group(1), "date": m.group(2),
                            "size": int(r["size"]) if r.get("size") else None})
    return max(entries, key=lambda e: e["date"]) if entries else None


def _hh_ckan_date(session=None, timeout=60):
    latest = hh_latest_download(session=session, timeout=timeout)
    return latest["date"] if latest else None


def _zip_first_member_date(url, session, timeout):
    """
    Date of the first member of the ZIP at `url`, read from its local file
    header (bytes 0-29) of a streamed GET that is closed right after. None when
    the response does not start with a ZIP local file header.
    """
    with session.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        head = b""
        for chunk in resp.iter_content(chunk_size=64):
            head += chunk
            if len(head) >= 30:
                break
    if len(head) < 30 or head[:4] != b"PK\x03\x04":
        return None
    dos_date = struct.unpack("<H", head[12:14])[0]
    return datetime.date(1980 + (dos_date >> 9), (dos_date >> 5) & 15, dos_date & 31).isoformat()


def _mv_zip_header_date(urls, session=None, timeout=60):
    """
    Newest build date among the MV Gemeinde ZIPs at `urls`: the date 02 records
    for the local files (newest ZIP member date). The service sends neither
    Last-Modified nor Range support, so the date comes from the ZIP itself.
    The GeoPortal.MV Atom feed is no substitute: its "Stand" is the daily update
    of the cadastre database, not of the shapefile ZIPs.
    """
    session = session or requests.Session()
    dates = [d for d in (_zip_first_member_date(u, session, timeout) for u in urls) if d]
    return max(dates) if dates else None


def _sn_changelog_date(url, session=None, timeout=60):
    """
    Newest Hauskoordinaten data stand from the SN changelog. The real date
    is the "Stand DD.MM.YYYY" in the entry <summary> — NOT <updated>, which is
    when the changelog note was posted.
    """
    session = session or requests.Session()
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    text = resp.content.decode("utf-8", "replace")
    dates = []
    for entry in re.findall(r"<entry>(.*?)</entry>", text, re.S):
        title = re.search(r"<title>(.*?)</title>", entry, re.S)
        if not (title and re.search(r"\bHK\b|Hauskoord", title.group(1), re.I)):
            continue
        summary = re.search(r"<summary>(.*?)</summary>", entry, re.S)
        stand = re.search(r"Stand\s+(\d{2})\.(\d{2})\.(\d{4})", summary.group(1)) if summary else None
        if stand:
            dates.append(f"{stand.group(3)}-{stand.group(2)}-{stand.group(1)}")
    return max(dates) if dates else None


# German month names -> number, for parsing "Ausgabedatum September 2025" style dates.
_GERMAN_MONTHS = {
    "januar": "01", "februar": "02", "märz": "03", "maerz": "03", "april": "04",
    "mai": "05", "juni": "06", "juli": "07", "august": "08", "september": "09",
    "oktober": "10", "november": "11", "dezember": "12",
}


def he_filename_date(name):
    """
    Extract the HE Ausgabe from a download name. HVBG numbers its releases per
    year ("2026-01" is Ausgabe 2026/1, published in June), so those come back as
    'YYYY/N'; only the older "Ausgabedatum <Monat>" names carry a month:
      "...-2026-01.txt"                     -> 2026/1
      "HK-2025-2_Hessen_DC.txt"             -> 2025/2
      "...Ausgabedatum September 2025.zip"  -> 2025-09
    Returns None if none matches.
    """
    base = name.lower()
    m = (re.search(r"-(\d{4})-(\d{2})(?:\b|\()", base)
         or re.search(r"\bhk-(\d{4})-(\d)(?!\d)", base))
    if m:
        return f"{m.group(1)}/{int(m.group(2))}"
    m = re.search(r"ausgabedatum\s+([a-zäöü]+)\s+(\d{4})", base)
    if m and m.group(1) in _GERMAN_MONTHS:
        return f"{m.group(2)}-{_GERMAN_MONTHS[m.group(1)]}"
    return None


def he_latest_download(session=None, timeout=60):
    """
    Newest Hauskoordinaten download listed by the HVBG Downloadcenter, as
    {name, date, created, url, size}. `url` is absolute and only valid on the
    day it was fetched. Returns None if nothing is listed.
    """
    session = session or requests.Session()
    resp = session.get(_HE_DOWNLOADCENTER_URL, headers={"Accept": "application/json"},
                       timeout=timeout)
    resp.raise_for_status()
    downloads = (resp.json().get("searchresult") or {}).get("downloads") or []
    entries = []
    for d in downloads:
        uri = (d.get("downloadLink") or {}).get("uri")
        date = he_filename_date(d.get("name") or "")
        if uri and date:
            entries.append({
                "name": d["name"],
                "date": date,
                "created": d.get("creationDate"),
                "url": _HE_DOWNLOAD_HOST + quote(uri, safe="/()-_.~"),
                "size": d.get("fileSize"),
            })
    return max(entries, key=lambda e: e["date"]) if entries else None


def _he_downloadcenter_date(session=None, timeout=60):
    latest = he_latest_download(session=session, timeout=timeout)
    return latest["date"] if latest else None


def _lgb_gazetteer_date(url, landschluessel, session=None, timeout=60):
    """
    'akt' of one Hauskoordinaten feature of the given Land in the LGB gazetteer.
    The date is uniform per Land, so a single feature is enough.
    """
    session = session or requests.Session()
    resp = session.get(url.rstrip("/") + "/items",
                       params={"f": "json", "limit": 1, "landschluessel": landschluessel},
                       headers={"Accept": "application/geo+json"}, timeout=timeout)
    resp.raise_for_status()
    feats = resp.json().get("features") or []
    akt = (feats[0].get("properties") or {}).get("akt") if feats else None
    return str(akt)[:10] if akt else None


def latest_release(date, months):
    """
    Last day of the newest month in `months` that is not after `date`'s month,
    as 'YYYY-MM-DD' ('2026-10-30', (3, 9) -> '2026-09-30'; '2027-01-31' ->
    '2026-09-30'). An upstream date inside a release month counts as that release.
    """
    d = datetime.date.fromisoformat(date[:10])
    year = d.year
    past = [m for m in months if m <= d.month]
    if not past:
        year, past = year - 1, list(months)
    month = max(past)
    nxt = datetime.date(year + (month == 12), month % 12 + 1, 1)
    return (nxt - datetime.timedelta(days=1)).isoformat()


def probe_wfs_date(sub, session=None, timeout=60):
    """
    Cheaply read a WFS sub-source's date_field by fetching a single feature (the
    date is uniform per feed). Returns the date string or None. Shared by
    fetch_alkis_wfs.py and the freshness dashboard.
    """
    field = sub.get("date_field")
    if not field:
        return None
    session = session or requests.Session()
    params = {
        "service": "WFS",
        "version": sub.get("version", "1.1.0"),
        "request": "GetFeature",
        "typeName": sub["typename"],
        "srsName": sub.get("srs", "EPSG:25832"),
        "outputFormat": "application/vnd.geo+json",
        "startIndex": 0,
        sub.get("count_param", "maxFeatures"): 1,
    }
    resp = session.get(sub["base_url"], params=params, timeout=timeout)
    resp.raise_for_status()
    try:
        data = resp.json()
    except json.JSONDecodeError:
        import io
        data = json.load(io.BytesIO(resp.content))
    feats = data.get("features", [])
    if not feats:
        return None
    return str((feats[0].get("properties") or {}).get(field) or "").strip() or None


def probe_remote_date(state, session=None):
    """
    Return (remote_date 'YYYY-MM-DD' or None, note_or_error).

    `note` carries the static per-source note on success, or an error string when
    the probe raised. Sources with probe == "none" return (None, static_note).
    """
    src = SOURCES.get(state)
    if not src:
        return None, f"unknown state '{state}'"

    probe = src.get("probe", "none")
    note = src.get("note")
    if probe == "none":
        return None, note

    try:
        date = _probe_date(src, probe, session)
    except Exception as e:
        return None, f"Fernabruf fehlgeschlagen: {e}"
    if date and src.get("release_months"):
        date = latest_release(date, src["release_months"])
    return date, note


def _probe_date(src, probe, session):
    """Raw upstream date of one probe strategy, or None for an unknown strategy."""
    if probe == "http_last_modified":
        return _last_modified_date(src["url"], verify=src.get("verify", True), session=session)
    if probe == "nrw_index":
        return _nrw_index_date(src["url"], session=session)
    if probe == "nds_metadata":
        return _nds_metadata_date(src["url"], session=session)
    if probe == "hh_ckan":
        return _hh_ckan_date(session=session)
    if probe == "mv_zip_header":
        return _mv_zip_header_date(src["probe_urls"], session=session)
    if probe == "sn_changelog":
        return _sn_changelog_date(src["url"], session=session)
    if probe == "he_downloadcenter":
        return _he_downloadcenter_date(session=session)
    if probe == "lgb_gazetteer":
        return _lgb_gazetteer_date(src["url"], src["landschluessel"], session=session)
    return None
