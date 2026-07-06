// Per-state ALKIS attribution for the Leaflet attribution control.
// Quellenvermerk wording follows each state's license terms (dl-de/by-2-0
// requires naming the provider as specified; dl-de/zero and courtesy entries
// just credit the source). Keep in sync with the table in README.md.

const DL_DE_BY = '<a href="https://www.govdata.de/dl-de/by-2-0" target="_blank" rel="noopener">dl-de/by-2-0</a>';
const DL_DE_ZERO = '<a href="https://www.govdata.de/dl-de/zero-2-0" target="_blank" rel="noopener">dl-de/zero-2.0</a>';
const CC_BY = '<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>';

const year = new Date().getFullYear();

export const ALKIS_ATTRIBUTION = {
    bb: `Adressdaten: &copy; GeoBasis-DE/LGB, ${DL_DE_BY}`,
    be: `Adressdaten: ALKIS Berlin, ${DL_DE_ZERO}`,
    he: `Adressdaten: HVBG Hessen, ${DL_DE_ZERO}`,
    hh: `Adressdaten: Freie und Hansestadt Hamburg, Landesbetrieb Geoinformation und Vermessung (LGV), ${DL_DE_BY}`,
    mv: `Adressdaten: &copy;GeoBasis-DE/MV/${CC_BY} (Quelle verändert)`,
    nds: `Adressdaten: &copy; GeoBasis-DE/LGLN ${year}, ${CC_BY}`,
    nrw: `Adressdaten: Geobasis NRW, ${DL_DE_ZERO} &middot; Städteregion Aachen`,
    rlp: `Adressdaten: &copy;GeoBasis-DE / LVermGeoRP${year}, ${DL_DE_BY}, <a href="https://lvermgeo.rlp.de" target="_blank" rel="noopener">lvermgeo.rlp.de</a>`,
    sn: `Adressdaten: GeoSN, ${DL_DE_BY}`,
    st: `Adressdaten: &copy; GeoBasis-DE / LVermGeo ST, ${DL_DE_BY}`,
};

const PROJECT_LINKS = '<a href="https://github.com/Tillbtn/osm-coverage" target="_blank" rel="noopener">GitHub</a>'
    + ' &middot; <a href="https://www.openstreetmap.org/user/Till_btn" target="_blank" rel="noopener">Till_btn</a>';

// ALKIS source for the selected state (if any) plus the project links
export function mapAttributions(state) {
    return [ALKIS_ATTRIBUTION[state], PROJECT_LINKS].filter(Boolean);
}
