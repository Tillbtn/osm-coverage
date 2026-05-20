# Address Coverage Tracker (ALKIS vs OSM)

Compare data from ALKIS (Amtliches Liegenschaftskatasterinformationssystem) with OSM to find missing addresses.


## Data

- OSM data extracted from Geofabrik PBFs

- ALKIS data from official state geoportals in different formats. Currently 10/16 states (those with permission for OSM) are part of the comparison:

|  |  |
|------|-------|
| `be` | Berlin |
| `bb` | Brandenburg |
| `hh` | Hamburg |
| `he` | Hessen |
| `mv` | Mecklenburg-Vorpommern | 
| `nds` | Niedersachsen |
| `nrw` | Nordrhein-Westfalen |
| `rlp` | Rheinland-Pfalz |
| `sn` | Sachsen |
| `st` | Sachsen-Anhalt |

Depending on the data source, addresses are grouped based on admin_level 6 (Kreise), 8 (Gemeinden), 9 (Bezirke), or 10 (Stadtteile).

Users can report false positive entries (abbreviations, ALKIS errors) on the map which are saved per state and applied with the next update run. It saves a "reference_alkis_id" computed from cooordinates, street and housenumber since ALKIS data can contain duplicate addresses per district. The corrections will be collectively reported to the official ALKIS authorities.

## Scripts

- `01_download_alkis_<state>.py`: Download ALKIS data (manually executed from time to time since states have very different update cycles)
- `02_extract_alkis.py`: Extract and normalize ALKIS data with lots of state specific logic.
- `03_import_osm.py`: Import and normalize OSM data (run daily when Geofabrik updates their data)
- `04_compare.py`: Compare ALKIS and OSM addresses. (show missing when there is no match inside 150m distance, or "wrong" street if the closest match has the correct housenumber but a different street name)
- `05_process_boundaries.py`: Process administrative boundaries

## Map

The map shows boundaries of states / districts and color codes them based on the address coverage. Each district can be clicked to load the specific geojson file and display the addresses that are missing in OSM but present in ALKIS.
There is a statistics overview per state with the top 10 districts from the last 1/7/30 days as well as the evolution of the address coverage (total and relative) per district.