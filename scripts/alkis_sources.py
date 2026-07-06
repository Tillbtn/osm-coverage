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
  hh_ckan             GET the transparenz.hamburg.de CKAN dataset, newest YYYY-MM
                      embedded in the "Download ALKIS Adressen …" resource names
  mv_atom             GET the GeoPortal.MV update Atom feed, newest <updated> among
                      the ALKIS entries (MV publishes per-Kreis, updated continuously)
  sn_changelog        GET the geodaten.sachsen.de Atom changelog, newest entry whose
                      title mentions HK (Hauskoordinaten — the address product)
  st_page             scrape the LVermGeo open-data page for the "Gebäudereferenzen
                      Stand: MM/YYYY" text (the ZIP's Last-Modified is a nightly
                      rebuild and does NOT reflect the data currency)
  none                no cheap remote probe (manual portal / order process)

`automated` reflects whether 01 can fetch the data unattended; a source can be
automated (RLP, ST) yet still have no per-file date embedded, or manual (HE, SN)
yet carry a date once downloaded (handled post-download by detect_alkis_date in
02_extract_alkis.py).
"""

import re
import html
import json
import datetime
import xml.etree.ElementTree as ET

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
_ST_PAGE_URL = "https://www.lvermgeo.sachsen-anhalt.de/de/gdp-open-data.html"
_HH_CKAN_URL = ("https://suche.transparenz.hamburg.de/api/3/action/"
                "package_show?id=alkis-adressen-hamburg26")
_MV_ATOM_URL = "https://www.geoportal-mv.de/portal/Geodatenviewer/Datenaktualisierungen/Atom"
_MV_DOWNLOAD_PATTERN = ("https://www.geodaten-mv.de/dienste/alkis_nas_download?index=1&"
                        "dataset=32538df8-6b74-4582-8591-c77e85fbf929&file={id}_SHP_{name}.zip")
_SN_CHANGELOG_URL = "https://www.geodaten.sachsen.de/changelog.xml"

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
    "page_size": 50000,
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
        "note": "Landesweit alle quartalsweise; Städteregion Aachen täglich per WFS",
        "sub_sources": [_AACHEN_WFS],
    },
    "rlp": {
        "automated": True, "source_type": "direct_zip",
        "probe": "http_last_modified", "url": _RLP_ZIP_URL, "verify": False,
        "download": {"method": "direct_zip", "url": _RLP_ZIP_URL, "verify": False},
    },
    "st": {
        # The GBIS_Gebaeude.zip is rebuilt nightly, so its Last-Modified is
        # always "today" and useless as a data-currency signal. The open-data
        # page carries the real "Stand: MM/YYYY".
        "automated": True, "source_type": "direct_zip",
        "probe": "st_page", "url": _ST_PAGE_URL,
        "download": {"method": "direct_zip", "url": _ST_ZIP_URL},
    },
    "mv": {
        "automated": True, "source_type": "download_service",
        "probe": "mv_atom", "url": _MV_ATOM_URL,
        "download": {"method": "nas_download_service", "url": _MV_DOWNLOAD_PATTERN},
        "note": "Fortlaufend je Landkreis aktualisiert (GeoPortal.MV Atom-Feed)",
    },
    "hh": {
        "automated": False, "source_type": "portal",
        "probe": "hh_ckan", "url": _HH_CKAN_URL,
        "download": {"method": "manual", "url": "https://suche.transparenz.hamburg.de/dataset/alkis-adressen-hamburg26"},
        "note": "transparenz.hamburg.de; Update quartalsweise",
    },
    "he": {
        "automated": False, "source_type": "portal",
        "probe": "none",
        "url": ("https://gds.hessen.de/INTERSHOP/web/WFS/HLBG-Geodaten-Site/de_DE/-/EUR/"
                "ViewDownloadcenter-Start?path=Liegenschaftskataster/"
                "Hauskoordinaten%20ohne%20Postalische%20Angaben%20(txt)"),
        "download": {"method": "manual", "url": "https://gds.hessen.de"},
        "note": "HLBG Downloadcenter; Datum steht auf der Seite, aber automatisch auslesbar",
    },
    "bb": {
        "automated": False, "source_type": "order",
        "probe": "none", "url": "https://geobroker.geobasis-bb.de",
        "download": {"method": "manual", "url": "https://geobroker.geobasis-bb.de"},
        "note": "Bestellung über Geobroker nötig",
    },
    "be": {
        "automated": False, "source_type": "portal",
        "probe": "none", "url": "https://gdi.berlin.de/geonetwork",
        "download": {"method": "manual", "url": "https://gdi.berlin.de/geonetwork"},
        "note": "GDI Berlin; Stand in info-be.txt (Auslesedatum) nach Entpacken, manuell",
    },
    "sn": {
        "automated": False, "source_type": "portal",
        "probe": "sn_changelog", "url": _SN_CHANGELOG_URL,
        "download": {"method": "manual", "url": "https://www.geodaten.sachsen.de"},
        "note": "Downloadbereich Hauskoordinaten, Download manuell",
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


def _hh_ckan_date(url, session=None, timeout=60):
    """Newest YYYY-MM embedded in the CKAN dataset's ALKIS resource names."""
    session = session or requests.Session()
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    resources = (resp.json().get("result") or {}).get("resources", [])
    dates = set()
    for r in resources:
        name = (r.get("name") or "").upper()
        m = re.search(r"(\d{4}-\d{2})", name)
        if "ALKIS" in name and m:
            dates.add(m.group(1))
    return max(dates) if dates else None


def _mv_atom_date(url, session=None, timeout=60):
    """Newest <updated> among the ALKIS entries in the GeoPortal.MV Atom feed."""
    session = session or requests.Session()
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    text = resp.content.decode("utf-8", "replace")
    dates = []
    for entry in re.findall(r"<entry>(.*?)</entry>", text, re.S):
        title = re.search(r"<title>(.*?)</title>", entry, re.S)
        updated = re.search(r"<updated>(\d{4}-\d{2}-\d{2})", entry)
        if title and updated and re.search(r"ALKIS", title.group(1), re.I):
            dates.append(updated.group(1))
    return max(dates) if dates else None


def _sn_changelog_date(url, session=None, timeout=60):
    """Newest changelog entry whose title mentions HK (Hauskoordinaten)."""
    session = session or requests.Session()
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    text = resp.content.decode("utf-8", "replace")
    dates = []
    for entry in re.findall(r"<entry>(.*?)</entry>", text, re.S):
        title = re.search(r"<title>(.*?)</title>", entry, re.S)
        date = re.search(r"(\d{4}-\d{2}-\d{2})", entry)
        if title and date and re.search(r"\bHK\b|Hauskoord", title.group(1), re.I):
            dates.append(date.group(1))
    return max(dates) if dates else None


def _st_page_date(url, session=None, timeout=60):
    """Scrape 'Gebäudereferenzen … Stand: MM/YYYY' -> 'YYYY-MM' from the LVermGeo page."""
    session = session or requests.Session()
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    text = re.sub(r"<[^>]+>", " ", resp.content.decode("utf-8", "replace"))
    text = re.sub(r"\s+", " ", html.unescape(text))
    m = re.search(r"Gebäudereferenzen\s+Stand:?\s*(\d{2})/(\d{4})", text)
    return f"{m.group(2)}-{m.group(1)}" if m else None


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
        if probe == "http_last_modified":
            return _last_modified_date(src["url"], verify=src.get("verify", True), session=session), note
        if probe == "nrw_index":
            return _nrw_index_date(src["url"], session=session), note
        if probe == "nds_metadata":
            return _nds_metadata_date(src["url"], session=session), note
        if probe == "hh_ckan":
            return _hh_ckan_date(src["url"], session=session), note
        if probe == "mv_atom":
            return _mv_atom_date(src["url"], session=session), note
        if probe == "sn_changelog":
            return _sn_changelog_date(src["url"], session=session), note
        if probe == "st_page":
            return _st_page_date(src["url"], session=session), note
    except Exception as e:
        return None, f"Fernabruf fehlgeschlagen: {e}"

    return None, note
