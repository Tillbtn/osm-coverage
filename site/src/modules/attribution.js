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

const GITHUB_ICON = '<svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" style="vertical-align: -1px;"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>';
const PROJECT_LINKS = `<a href="https://github.com/Tillbtn/osm-coverage" target="_blank" rel="noopener" aria-label="GitHub" title="GitHub">${GITHUB_ICON}</a>`
    + ' &middot; <a href="https://www.openstreetmap.org/user/Till_btn" target="_blank" rel="noopener">Till_btn</a>';

// ALKIS source for the selected state (if any) plus the project links
export function mapAttributions(state) {
    return [ALKIS_ATTRIBUTION[state], PROJECT_LINKS].filter(Boolean);
}
