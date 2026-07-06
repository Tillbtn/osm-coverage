# OSM-ALKIS address comparison

Compares the official German ALKIS ("Amtliches Liegenschaftskatasterinformationssystem")
addresses against OpenStreetMap and shows the differences on a map - visit [addresses.tillb.de](https://addresses.tillb.de).

Addresses are a core part of OSM but far from complete in Germany. Most
federal states have released their ALKIS data under terms compatible with OSM,
so it can be used as a reference to find areas where mapping addresses is
worthwhile. This tool does the comparison per state/district, publishes the
missing addresses as GeoJSON on a Leaflet map (with JOSM remote-control links
per point), and tracks coverage over time. Currently more than 1.1 million
ALKIS addresses have no OSM counterpart.

One thing up front: the goal is to show *where* work is needed, not to
encourage blindly copying everything from ALKIS to pretty up the statistics.
ALKIS contains errors too (that's what the correction feature is for), and
on-the-ground survey data is one of OSM's most valuable properties.

## Data sources

OSM data comes from the daily [Geofabrik](https://download.geofabrik.de/)
state extracts. ALKIS data comes from each state's own geoportal; formats
(GeoPackage, CSV, GML, Shapefile, XML, WFS), delivery granularity
(state-wide, per Kreis, per Gemeinde) and update cycles differ per state, so
`scripts/02_extract_alkis.py` is a registry of per-state readers with a fair
amount of state-specific normalization logic.

10 of 16 states have released their ALKIS data for OSM use and are part of
the comparison:

| Key | State | | Key | State |
|-----|-------|-|-----|-------|
| `bb` | Brandenburg | | `mv` | Mecklenburg-Vorpommern |
| `be` | Berlin | | `nds` | Niedersachsen |
| `he` | Hessen | | `nrw` | Nordrhein-Westfalen |
| `hh` | Hamburg | | `rlp` | Rheinland-Pfalz |
| `sn` | Sachsen | | `st` | Sachsen-Anhalt |

Depending on the state, addresses are grouped by admin_level 6 (Kreise),
8 (Gemeinden), 9 (Bezirke) or 10 (Stadtteile).

ALKIS update cycles vary wildly between states, so downloads are mostly
manual and irregular. Optionally, `scripts/fetch_alkis_wfs.py` pulls updates
automatically from a WFS feed as part of the regular update runs. `scripts/alkis_sources.py` plus
`check_alkis_dates.py` probe each source's remote export date (HTTP
Last-Modified, Atom feeds, CKAN metadata, page scraping - whatever the portal
offers) and feed the freshness dashboard on `status.html`.

## Pipeline

Python with GeoPandas and pyosmium; intermediates are Parquet, outputs are
static GeoJSON/JSON served by nginx. Scripts run in number order:

- `01_download_alkis_<state>.py` — fetch raw ALKIS data (mostly manual, per state)
- `02_extract_alkis.py` — normalize the raw formats into a unified schema
  (`street, housenumber, postcode, city, district, state, geometry, alkis_id`,
  EPSG:25832) at `data/<st>/alkis.parquet`
- `fetch_alkis_wfs.py` — WFS-based ALKIS refresh, can replace 01+02 where
  a suitable WFS exists
- `03_import_osm.py` — stream the Geofabrik PBF with osmium (nodes plus
  way/relation centroids) into `data/<st>/osm.parquet`
- `04_compare.py` — the core: match both sides, apply user corrections,
  write all site outputs (per-district GeoJSON, stats, history)
- `05_process_boundaries.py` — administrative boundary GeoJSONs

### Matching

Both sides get a normalized key: `normalize_street` lowercases, expands ~15
common German abbreviations (Str., Dr., St., ...), strips spaces/punctuation
and folds ß→ss; `normalize_hnr` collapses the sub-address separators `/` and
`-` to `.`, so ALKIS `17.1` matches OSM `17/1` but stays distinct from `171`.
House numbers are expanded on both sides: `1,3` splits, `11a-c` and `7-13`
(stepping by parity) expand, and OSM `addr:housename` values spawn synthetic
extra rows.

A match is the same key within 150 m (spatial join). Unmatched ALKIS
addresses are classified `missing`; a second pass looks for a nearest OSM
neighbor within 20 m with the same house number but a different street and
flags those as `wrong_street` (subdivided into abbreviation/typo via difflib
similarity), recording the OSM street for comparison.

Every run appends to per-district history (`<st>_history.json`), which powers
the coverage-over-time charts.

### Corrections

ALKIS is not error-free, so users can report false positives directly on the
map: abbreviations, addresses that don't exist on the ground, addresses that
are actually mapped, or street renames. Reports go through a tiny Flask
backend (`server.py`, single endpoint) into a per-state JSON file and are
applied on the next pipeline run.

Since ALKIS can contain duplicate addresses per district, corrections are
keyed on an `alkis_id`: an md5 over district, street, house number and the
coordinate quantized to a 100 m grid, so it survives re-extraction and small
coordinate shifts. The plan is to forward the collected error reports to the
responsible cadastre authorities.

## Frontend

`site/` — Vite, vanilla ES modules, Leaflet, Chart.js.The main
map (`addresses.html`) starts with states colored by coverage rate, drills
down to district level, and loads each district's GeoJSON on click. Point
categories (missing / wrong street / reported) can be toggled via the legend;
each point pops up links to osm.org and JOSM remote control. The stats modal
shows coverage history per district/state plus top-10 lists over the last
1/7/30 days. "Done" markers and filter settings persist in localStorage.

## Deployment

Production runs as three containers (`deployment/docker-compose.yml`): nginx
serving the built frontend and the generated data, the Flask backend, and a
worker that an hourly cron starts via `docker compose run --rm worker`. The
worker only does real work when `check_geofabrik_export_date.py` detects a
new OSM export; it then refreshes WFS sources, reimports OSM, recompares and
backs up the history files. See `deployment/DEPLOYMENT.md`.

## Licensing and attribution

The code is MIT-licensed (see `LICENSE`). The data has its own terms:

OSM data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright),
licensed under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/) —
this covers both the compared address data (via Geofabrik extracts) and the
map tiles.

The ALKIS data is open data of the respective state survey authorities. The
map shows the matching source line next to the OSM attribution whenever a
state is selected (`site/src/modules/attribution.js`); the licenses as of
July 2026:

| Key | Provider | License | Attribution (shown on the map) |
|-----|----------|---------|--------------------------------|
| `bb` | LGB Brandenburg | [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0) | © GeoBasis-DE/LGB, dl-de/by-2-0 |
| `be` | Geoportal Berlin | [dl-de/zero-2.0](https://www.govdata.de/dl-de/zero-2-0) | ALKIS Berlin |
| `he` | HVBG Hessen | [dl-de/zero-2.0](https://www.govdata.de/dl-de/zero-2-0) | HVBG Hessen |
| `hh` | LGV Hamburg | [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0) | Freie und Hansestadt Hamburg, Landesbetrieb Geoinformation und Vermessung (LGV) |
| `mv` | LAiV M-V | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | ©GeoBasis-DE/MV/CC BY 4.0 |
| `nds` | LGLN Niedersachsen | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | © GeoBasis-DE/LGLN \<Jahr\>s |
| `nrw` | Geobasis NRW | [dl-de/zero-2.0](https://www.govdata.de/dl-de/zero-2-0) | Geobasis NRW · Städteregion Aachen |
| `rlp` | LVermGeo RLP | [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0) | ©GeoBasis-DE / LVermGeoRP\<Jahr\>, dl-de/by-2-0, www.lvermgeo.rlp.de |
| `sn` | GeoSN Sachsen | [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0) | Quelle: GeoSN, dl-de/by-2-0 |
| `st` | LVermGeo Sachsen-Anhalt | [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0) | © GeoBasis-DE / LVermGeo ST, dl-de/by-2-0 |


## AI Disclosure

Parts of this codebase were developed using AI coding assistants
(Claude Code, Google Antigravity), primarily frontend + documentation