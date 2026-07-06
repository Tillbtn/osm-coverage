import './style.css';
import L from 'leaflet';
import { createMap, createJOSMLink, createOSMLink } from './modules/map';
import { mapAttributions } from './modules/attribution';
import { fetchDistricts, fetchHistory, fetchGeoJSON } from './modules/api';
import { StatsModal } from './modules/StatsModal';
import { createLegend } from './modules/Legend';

// State
let currentLayer = null;
let currentGeoJSONData = null;
let districtsData = [];
let sortCol = 'name';
let sortAsc = true;
let historyDataStore = null;

let boundariesLayer = null;
let globalBoundariesGeoJSON = null;

function mapDistrictName(shapeName, stateStr, dData) {
    if (dData) {
        let match = dData.find(d => d.name === shapeName);
        if (match) return match.name;

        let underscored = shapeName.replace(/ /g, '_');
        match = dData.find(d => d.name === underscored);
        if (match) return match.name;
    }
    return shapeName;
}

function getCoverageColor(coverage) {
    if (coverage === undefined || coverage === null) return '#94a3b8'; // Slate 400
    if (coverage > 98) return '#059669'; // Green 600
    if (coverage > 95) return '#34d399'; // Green 400
    if (coverage > 85) return '#fbbf24'; // Amber 400
    if (coverage > 75) return '#f59e0b'; // Amber 500
    if (coverage > 50) return '#f97316'; // Orange 500
    return '#ef4444'; // Red 500
}

function renderBoundaries() {
    if (!boundariesLayer || !globalBoundariesGeoJSON) return;
    boundariesLayer.clearLayers();
    boundariesLayer.addData(globalBoundariesGeoJSON);
    boundariesLayer.bringToBack();
}

function zoomToDistrictBoundary(name) {
    if (!globalBoundariesGeoJSON) return;
    const feature = globalBoundariesGeoJSON.features.find(f => {
        const bName = f.properties.LANDKREIS || f.properties.GEN || f.properties.NAM;
        const mappedName = mapDistrictName(bName, state, districtsData);
        return mappedName === name;
    });
    if (feature) {
        const tempLayer = L.geoJSON(feature);
        map.fitBounds(tempLayer.getBounds());
    }
}

// Legend Visibility State
const defaultVisibility = {
    missing: true,
    wrong_street: true,
    wrong_street_abbreviation: true,
    wrong_street_typo: true,
    corrected_osm: true,
    corrected_not_osm: true,
    ignored: true,
    done: true
};

let visibilityState = defaultVisibility;
try {
    const savedState = localStorage.getItem('osm_alkis_coverage_legend_state');
    if (savedState) {
        visibilityState = { ...defaultVisibility, ...JSON.parse(savedState) };
    }
} catch (e) {
    console.warn("Could not load Legend state", e);
}

function shouldHideFeature(feature) {
    const props = feature.properties;
    if (props && props.correction_type === 'abbreviation') {
        return true;
    }
    if (props && isValid(props.correction_comment)) {
        const comment = props.correction_comment.toLowerCase();
        if (comment.includes('abkürzung') || comment.includes('abgekürzt') || comment.includes('ausgeschriebener name')) {
            return true;
        }
    }
    return false;
}

function loadDistrict(name, preserveView = false) {
    if (currentLayer) map.removeLayer(currentLayer);
    currentLayer = null;
    currentDistrictName = name;

    // Update URL
    const historyUrl = new URL(window.location);
    const currentParam = historyUrl.searchParams.get('district');
    const newParam = name === "Global" ? null : name;

    if (currentParam !== newParam) {
        if (name === "Global") {
            historyUrl.searchParams.delete('district');
        } else {
            historyUrl.searchParams.set('district', name);
        }
        window.history.pushState(null, null, historyUrl.toString() + window.location.hash);

    }

    if (name === "Global") {
        if (!state) {
            document.getElementById('stats').innerText = "";
            if (!preserveView) map.setView([initialLat, initialLng], initialZoom);
            return;
        }
        let totalMissing = 0;
        if (districtsData && districtsData.length > 0) {
            totalMissing = districtsData.reduce((sum, d) => sum + (d.missing || 0), 0);
        }
        document.getElementById('stats').innerText = `gesamt: ${totalMissing} fehlende Adressen`;
        if (!preserveView) map.setView([initialLat, initialLng], initialZoom);
        if (typeof renderBoundaries === 'function') renderBoundaries();
        return;
    }

    document.getElementById('stats').innerText = `Lade ${name}...`;

    // Construct URL
    let url = "";

    url = `/districts/${name}.geojson`;
    if (districtsData) {
        const meta = districtsData.find(d => d.name === name);
        if (meta) {
            if (meta.state && meta.filename) {
                url = `/states/${meta.state}/districts/${meta.filename}`;
            }
            else if (meta.path) {
                if (meta.path.startsWith('states/')) {
                    url = '/' + meta.path;
                } else {
                    url = `/districts/${meta.path}`;
                }
            }
        }
    }

    fetchGeoJSON(url)
        .then(data => {
            // Guard against stale requests
            if (currentDistrictName !== name) {
                console.log(`Ignoring stale response for ${name}`);
                return;
            }

            // Save raw data globally so we can re-filter without losing features
            currentGeoJSONData = data;

            // Remove 'done' IDs that are no longer in the GeoJSON
            try {
                const doneData = getDoneData();
                if (doneData[name] && doneData[name].length > 0) {
                    const validIds = new Set();
                    data.features.forEach(f => {
                        if (f.properties && f.properties.alkis_id) {
                            validIds.add(f.properties.alkis_id);
                        }
                    });

                    const originalCount = doneData[name].length;
                    const cleanedList = doneData[name].filter(id => validIds.has(id));

                    if (cleanedList.length !== originalCount) {
                        console.log(`Cleaned up ${originalCount - cleanedList.length} stale 'done' IDs for ${name}.`);
                        doneData[name] = cleanedList;
                        localStorage.setItem('osm_alkis_done_by_district', JSON.stringify(doneData));
                    }
                }
            } catch (cleanupErr) {
                console.warn("Cleanup of done IDs failed", cleanupErr);
            }

            currentLayer = L.geoJSON(data, {
                filter: function (feature) {
                    const props = feature.properties;
                    if (props.matched && shouldHideFeature(feature)) return false;
                    if (props && props.correction_type === 'already_mapped') return false;

                    let cat = 'missing';

                    if (props && isValid(props.correction_type)) {
                        if (props.correction_type === 'ignored') {
                            cat = 'ignored';
                        } else if (props.correction_type && props.correction_type.startsWith('wrong_street')) {
                            cat = props.correction_type;
                        } else if (props.matched) {
                            cat = 'corrected_osm';
                        } else {
                            cat = 'corrected_not_osm';
                        }
                    } else if (props && props.matched) {
                        cat = 'corrected_osm'; // Fallback
                    }

                    if (props && props.alkis_id && isDone(props.alkis_id)) {
                        cat = 'done';
                    }

                    return visibilityState[cat] !== false;
                },
                pointToLayer: function (feature, latlng) {
                    let fillColor = "#ff4444";

                    const props = feature.properties;

                    if (props && isValid(props.correction_type)) {
                        if (props.correction_type === 'ignored') {
                            fillColor = "#9ca3af"; // Gray
                        } else if (props.correction_type === 'wrong_street') {
                            fillColor = "#ea580c"; // Orange 600
                        } else if (props.correction_type === 'wrong_street_abbreviation') {
                            fillColor = "#f97316"; // Orange 500
                        } else if (props.correction_type === 'wrong_street_typo') {
                            fillColor = "#fb923c"; // Orange 400
                        } else if (props.matched) {
                            fillColor = "#3b82f6"; // Blue
                        } else {
                            fillColor = "#8b5cf6"; // Purple
                        }
                    } else if (props && props.matched) {
                        fillColor = "#10b981"; // Green
                    }

                    // Check local done state
                    if (props && props.alkis_id && isDone(props.alkis_id)) {
                        fillColor = "#22c55e";
                    }

                    return L.circleMarker(latlng, {
                        radius: 6,
                        fillColor: fillColor,
                        color: "#fff",
                        weight: 1,
                        opacity: 1,
                        fillOpacity: 0.8
                    });
                },
                onEachFeature: function (feature, layer) {
                    if (feature.properties) {
                        layer.bindPopup(() => {
                            const props = feature.properties;

                            const street = props.street || '';
                            const hnr = props.housenumber || '';
                            const isMatched = props.matched;
                            const comment = isValid(props.correction_comment) ? props.correction_comment : '';
                            const origStreet = props.original_street ? props.original_street : street;
                            const origHnr = props.original_housenumber ? props.original_housenumber : hnr;
                            const hasRealCorrection = (origStreet !== street) || (origHnr !== hnr);
                            const alkisId = props.alkis_id;

                            const lat = layer.getLatLng().lat;
                            const lng = layer.getLatLng().lng;

                            let title = "Fehlt in OSM:";
                            if (isMatched) {
                                if (props.correction_type === 'ignored') {
                                    title = "Ignoriert:";
                                } else {
                                    title = "Abweichung vom ALKIS:";
                                }
                            } else if (props.correction_type === 'wrong_street_abbreviation') {
                                title = "Abkürzung / Zusatz?";
                            } else if (props.correction_type === 'wrong_street_typo') {
                                title = "Typo?";
                            } else if (props.correction_type === 'wrong_street') {
                                title = "Falsche Straßenzuordnung?";
                            }

                            const container = document.createElement('div');
                            let content = "";

                            // ALKIS ignored
                            if (props.correction_type === 'ignored') {
                                content = `<strong>${title}</strong><br>
                                                <div style="margin-bottom: 4px;">
                                                    <span style="color: #666; font-size: 0.9em;">ALKIS:</span><br>
                                                    ${origStreet} ${origHnr}
                                                </div>`;
                                // wrong street
                            } else if (props.correction_type && props.correction_type.startsWith('wrong_street')) {
                                // normal
                                if (!hasRealCorrection) {
                                    content = `<strong>${title}</strong><br>
                                                    <div style="margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid #eee;">
                                                        <span style="color: #666; font-size: 0.9em;">ALKIS:</span><br>
                                                        ${origStreet} ${origHnr}
                                                    </div>
                                                    <div style="margin-bottom: 8px;">
                                                        <span style="color: #666; font-size: 0.9em;">OSM:</span><br>
                                                        ${props.osm_street || '-'} ${hnr}
                                                    </div>`;
                                    // ALKIS corrected, still wrong street
                                } else {
                                    content = `<strong>${title}</strong><br>
                                                    <div style="margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid #eee;">
                                                        <span style="color: #666; font-size: 0.9em;">ALKIS (korrigiert):</span><br>
                                                        ${street} ${hnr}
                                                    </div>
                                                     <div style="margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid #eee;">
                                                        <span style="color: #666; font-size: 0.9em;">ALKIS (original):</span><br>
                                                        ${origStreet} ${origHnr}
                                                    </div>
                                                    <div style="margin-bottom: 8px;">
                                                        <span style="color: #666; font-size: 0.9em;">OSM:</span><br>
                                                        ${props.osm_street || '-'} ${hnr}
                                                    </div>`;
                                }
                                // ALKIS corrected, matched
                            } else if (isMatched && hasRealCorrection) {
                                content = `<strong>${title}</strong><br>
                                                <div style="margin-bottom: 4px;">
                                                    <span style="color: #666; font-size: 0.9em;">ALKIS:</span><br>
                                                    ${origStreet} ${origHnr}
                                                </div>
                                                <div style="margin-bottom: 8px;">
                                                    <span style="color: #666; font-size: 0.9em;">OSM:</span><br>
                                                    ${street} ${hnr}
                                                </div>`;
                                // ALKIS corrected, not matched
                            } else if (hasRealCorrection) {
                                content = `<strong>${title}</strong><br>
                                                <div style="margin-bottom: 4px;">
                                                    <span style="color: #666; font-size: 0.9em;">ALKIS (korrigiert):</span><br>
                                                    ${street} ${hnr}
                                                </div>
                                                <div style="margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid #eee;">
                                                        <span style="color: #666; font-size: 0.9em;">ALKIS (original):</span><br>
                                                        ${origStreet} ${origHnr}
                                                </div>`;
                            }
                            // normal missing
                            else {
                                content = `<strong>${title}</strong><br>${street} ${hnr}<br><br>`;
                            }

                            // Sub-address separator is ambiguous: ALKIS stores e.g. "hnr=17, adz=1"
                            // but OSM may use ".", "/" or "-"
                            if (/\d\s*[./-]\s*\d/.test(hnr)) {
                                content += `<div style="color:#92400e; background:#fef3c7; border-radius:4px; padding:3px 6px; font-size:0.8em; margin-bottom:5px;">Trennzeichen unklar – vlt. „.“, „/“ oder „-“</div>`;
                            }

                            if (comment) {
                                content += `<div style="font-style: italic; margin-bottom: 5px; color: #555;">${comment}</div>`;
                            }

                            if (!isMatched) {
                                content += `<button class="correction-init-btn" style="background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 0.375rem; cursor: pointer; font-weight: 500; width: 100%; margin-bottom: 5px;">Falschmeldung?</button>`;
                            }

                            const contentDiv = document.createElement('div');
                            contentDiv.innerHTML = content;
                            container.appendChild(contentDiv);

                            const footerContainer = document.createElement('div');
                            footerContainer.style.display = 'flex';
                            footerContainer.style.justifyContent = 'space-between';
                            footerContainer.style.alignItems = 'flex-end';
                            footerContainer.style.marginTop = '10px';

                            const linksWrapper = document.createElement('div');
                            linksWrapper.style.display = 'flex';
                            linksWrapper.style.flexDirection = 'column';
                            linksWrapper.style.gap = '5px';

                            const osmLinkContainer = createOSMLink(lat, lng, map.getZoom());
                            osmLinkContainer.style.display = 'flex';
                            osmLinkContainer.style.gap = '10px';
                            linksWrapper.appendChild(osmLinkContainer);

                            const josmLinkContainer = createJOSMLink(lat, lng);
                            const josmWrapper = document.createElement('div');
                            josmWrapper.style.display = 'flex';
                            josmWrapper.style.gap = '10px';
                            josmWrapper.appendChild(josmLinkContainer);
                            linksWrapper.appendChild(josmWrapper);

                            footerContainer.appendChild(linksWrapper);

                            if (alkisId) {
                                const isCurrentlyDone = isDone(alkisId);
                                const doneBtn = document.createElement('button');
                                doneBtn.className = 'done-btn';
                                doneBtn.innerHTML = '✔';
                                doneBtn.style.background = 'transparent';
                                doneBtn.style.border = 'none';
                                doneBtn.style.cursor = 'pointer';
                                doneBtn.style.fontSize = '1.5rem';
                                doneBtn.style.lineHeight = '1';
                                doneBtn.style.padding = '0 5px';
                                doneBtn.style.marginBottom = '3px';
                                doneBtn.style.color = isCurrentlyDone ? '#22c55e' : '#cbd5e1';
                                doneBtn.title = isCurrentlyDone ? "Als nicht erledigt markieren" : "Lokal als erledigt markieren";

                                doneBtn.addEventListener('click', (e) => {
                                    e.stopPropagation();
                                    const newDoneState = toggleDone(alkisId);
                                    doneBtn.style.color = newDoneState ? '#22c55e' : '#cbd5e1';
                                    doneBtn.title = newDoneState ? "Als nicht erledigt markieren" : "Lokal als erledigt markieren";
                                    if (newDoneState) {
                                        layer.setStyle({ fillColor: "#22c55e" });
                                    } else {
                                        let fillColor = "#ff4444";
                                        if (props && isValid(props.correction_type)) {
                                            if (props.correction_type === 'ignored') fillColor = "#9ca3af";
                                            else if (props.correction_type === 'wrong_street') fillColor = "#ea580c";
                                            else if (props.correction_type === 'wrong_street_abbreviation') fillColor = "#f97316";
                                            else if (props.correction_type === 'wrong_street_typo') fillColor = "#fb923c";
                                            else if (props.matched) fillColor = "#3b82f6";
                                            else fillColor = "#8b5cf6";
                                        } else if (props && props.matched) {
                                            fillColor = "#10b981";
                                        }
                                        layer.setStyle({ fillColor: fillColor });
                                    }
                                });

                                footerContainer.appendChild(doneBtn);
                            }

                            container.appendChild(footerContainer);

                            const corrBtn = container.querySelector('.correction-init-btn');
                            if (corrBtn) {
                                corrBtn.addEventListener('click', (e) => {
                                    e.stopPropagation();
                                    correctionModal.open(street, hnr, props.alkis_id, props);
                                    map.closePopup();
                                });
                            }

                            return container;
                        }, { maxWidth: 300 });
                    }
                }
            });
            currentLayer.addTo(map);
            if (data.features.length > 0 && !preserveView) {
                map.fitBounds(currentLayer.getBounds());
            } else if (data.features.length === 0 && !preserveView) {
                zoomToDistrictBoundary(name);
            }

            const missingCount = data.features.filter(f => !f.properties.matched).length;
            document.getElementById('stats').innerText = `${missingCount} fehlende Adressen`;
            if (typeof renderBoundaries === 'function') renderBoundaries();
        })
        .catch(err => {
            console.error(err);
            document.getElementById('stats').innerText = 'Fehler beim Laden (oder keine Daten vorhanden).';
            if (!preserveView) zoomToDistrictBoundary(name);
            if (typeof renderBoundaries === 'function') renderBoundaries();
        });
}



const STATE_CONFIG = {
    bb: { center: [52.36, 13.0], zoom: 9, name: "Brandenburg" },
    be: { center: [52.52, 13.405], zoom: 11, name: "Berlin" },
    hh: { center: [53.55, 10.0], zoom: 11, name: "Hamburg" },
    mv: { center: [53.87601, 12.81555], zoom: 9, name: "Mecklenburg-Vorpommern" },
    nds: { center: [52.9, 9.8], zoom: 9, name: "Niedersachsen" },
    nrw: { center: [51.4, 7.6], zoom: 9, name: "Nordrhein-Westfalen" },
    rlp: { center: [49.9, 7.3], zoom: 9, name: "Rheinland-Pfalz" },
    he: { center: [50.65, 9.16], zoom: 9, name: "Hessen" },
    sn: { center: [50.9, 12.7], zoom: 9, name: "Sachsen" },
    st: { center: [52.0, 11.7], zoom: 9, name: "Sachsen-Anhalt" }
};

let currentDistrictName = "";

const params = new URLSearchParams(window.location.search);
const stateFromUrl = params.get('state');
const districtFromUrl = params.get('district');
const state = stateFromUrl || document.body.dataset.state;

const config = STATE_CONFIG[state] || { center: [51.16, 10.45], zoom: 6, name: "Deutschland" };

// Update Page Title
if (config.name) {
    document.title = `OSM-ALKIS Adressenvergleich - ${config.name}`;
    const h1 = document.querySelector('h1');
    if (h1) h1.innerText = `OSM-ALKIS Adressenvergleich (${config.name})`;
}

// Path Construction
const districtsUrl = state ? `/states/${state}/${state}_districts.json` : '/districts.json';
const historyUrl = state ? `/states/${state}/${state}_history.json` : '/detailed_history.json';
const boundariesUrl = state ? `/states/${state}/${state}_district_boundaries.geojson` : null;

// Init Map
const map = createMap('map', mapAttributions(state));


// Initialize Hamburger Menu
const menuToggle = document.getElementById('menu-toggle');
const headerControls = document.querySelector('.header-controls');
if (menuToggle && headerControls) {
    menuToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        headerControls.classList.toggle('open');
        menuToggle.setAttribute('aria-expanded', headerControls.classList.contains('open'));
    });

    // Close menu when clicking outside
    document.addEventListener('click', (e) => {
        if (!headerControls.contains(e.target) && !menuToggle.contains(e.target)) {
            headerControls.classList.remove('open');
            menuToggle.setAttribute('aria-expanded', 'false');
        }
    });
}

// Map View
const initialLat = parseFloat(document.body.dataset.centerLat) || config.center[0];
const initialLng = parseFloat(document.body.dataset.centerLng) || config.center[1];
const initialZoom = parseInt(document.body.dataset.zoom) || config.zoom;

// --- Correction Modal Logic ---
class CorrectionModal {
    constructor() {
        this.render();
        this.attachEvents();
    }

    render() {
        const modalHtml = `
            <div id="correction-modal" class="modal" style="display:none; z-index: 3000;">
                <div class="modal-content" style="max-width: 450px; border-radius: 8px; overflow: hidden; padding: 0;">
                    <div style="background: #3b82f6; color: white; padding: 1rem; display: flex; justify-content: space-between; align-items: center;">
                        <h2 style="margin: 0; font-size: 1.25rem;">Korrektur für den Abgleich</h2>
                        <span class="close-correction-button" style="cursor: pointer; font-size: 1.5rem; line-height: 1;">&times;</span>
                    </div>
                    <div style="padding: 1.5rem;">
                        <div style="margin-bottom: 1rem; background: #f3f4f6; padding: 0.75rem; border-radius: 4px;">
                            <strong>Adresse im ALKIS:</strong><br>
                            <span id="corr-modal-address"></span>
                        </div>

                        <select id="corr-type" style="width: 100%; margin-bottom: 1rem; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem;">
                            <option value="single">Adresse korrigieren</option>
                            <option value="street">Straßenname korrigieren (alle Nummern)</option>
                            <option value="abbreviation">Abkürzung ersetzen (alle Nummern)</option>
                            <option value="ignore">Adresse ignorieren</option>
                            <option value="ignore_street">Straße ignorieren (alle Nummern)</option>
                            <option value="already_mapped">Adresse bereits eingetragen</option>
                        </select>
                        
                        <div id="corr-fields-single">
                            <label style="display: block; margin-bottom: 0.25rem; font-size: 0.9em; color: #4b5563;">OSM-Straßenname (OTG)</label>
                            <input id="corr-single-street" style="width: 100%; margin-bottom: 0.75rem; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem;">
                            
                            <label style="display: block; margin-bottom: 0.25rem; font-size: 0.9em; color: #4b5563;">OSM-Hausnummer (OTG)</label>
                            <input id="corr-single-hnr" style="width: 100%; margin-bottom: 0.75rem; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem;">
                        </div>

                        <div id="corr-fields-street" style="display:none;">
                            <label style="display: block; margin-bottom: 0.25rem; font-size: 0.9em; color: #4b5563;">OSM-Straßenname (OTG)</label>
                            <input id="corr-street-all" style="width: 100%; margin-bottom: 0.75rem; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem;">
                        </div>

                        <div id="corr-fields-ignore" style="display:none;">
                        </div>

                        <label style="display: block; margin-bottom: 0.25rem; font-size: 0.9em; color: #4b5563;">Kommentar</label>
                        <textarea id="corr-comment" rows="3" style="width: 100%; margin-bottom: 1rem; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem; font-family: inherit;"></textarea>

                        <div id="corr-msg" style="margin-bottom: 1rem; text-align: center; font-weight: 600;"></div>

                        <button id="corr-submit-btn" style="width: 100%; background: #3b82f6; color: white; border: none; padding: 0.75rem; border-radius: 0.375rem; font-weight: 600; cursor: pointer;">Absenden</button>
                    </div>
                </div>
            </div>`;
        document.body.insertAdjacentHTML('beforeend', modalHtml);

        this.modal = document.getElementById('correction-modal');
        this.closeBtn = this.modal.querySelector('.close-correction-button');
        this.typeSelect = document.getElementById('corr-type');
        this.submitBtn = document.getElementById('corr-submit-btn');
        this.msgDiv = document.getElementById('corr-msg');

        // Field containers
        this.fieldsSingle = document.getElementById('corr-fields-single');
        this.fieldsStreet = document.getElementById('corr-fields-street');

        this.fieldsIgnore = document.getElementById('corr-fields-ignore');

        // Inputs
        this.inputSingleStreet = document.getElementById('corr-single-street');
        this.inputSingleHnr = document.getElementById('corr-single-hnr');
        this.inputStreetAll = document.getElementById('corr-street-all');
        this.inputComment = document.getElementById('corr-comment');
        this.displayAddress = document.getElementById('corr-modal-address');
    }

    attachEvents() {
        this.closeBtn.addEventListener('click', () => this.hide());
        window.addEventListener('click', (e) => {
            if (e.target === this.modal) this.hide();
        });

        this.typeSelect.addEventListener('change', (e) => {
            this.fieldsSingle.style.display = 'none';
            this.fieldsStreet.style.display = 'none';
            this.fieldsIgnore.style.display = 'none';

            if (e.target.value === 'single') { this.fieldsSingle.style.display = 'block'; }
            if (e.target.value === 'street') { this.fieldsStreet.style.display = 'block'; }
            if (e.target.value === 'abbreviation') { this.fieldsStreet.style.display = 'block'; }
            if (e.target.value === 'ignore') { this.fieldsIgnore.style.display = 'block'; }
            if (e.target.value === 'ignore_street') { this.fieldsIgnore.style.display = 'block'; }
            if (e.target.value === 'already_mapped') { this.fieldsIgnore.style.display = 'block'; }
        });

        this.submitBtn.addEventListener('click', () => this.submit());
    }

    open(street, hnr, alkisId, props = {}) {
        this.street = street;
        this.hnr = hnr;
        this.alkisId = alkisId;
        this.displayAddress.textContent = `${street} ${hnr}`;

        // Preselect a correction type based on the detected discrepancy.
        // The OSM name (on-the-ground name) is used as best guess for the correction.
        const correctionType = props.correction_type;
        const osmStreet = isValid(props.osm_street) ? props.osm_street : '';

        let preselectType = 'single';
        if (correctionType === 'wrong_street_abbreviation') {
            preselectType = 'abbreviation';
        } else if (correctionType === 'wrong_street_typo') {
            preselectType = 'street';
        } else if (correctionType === 'wrong_street') {
            preselectType = 'single';
        }

        this.typeSelect.value = preselectType;

        // Prefill the inputs. For street/abbreviation we prefill the street-all
        // field, for single we prefill the street + keep the housenumber.
        // Fall back to the ALKIS name when no OSM name is available.
        this.inputSingleStreet.value = osmStreet || street;
        this.inputSingleHnr.value = hnr;
        this.inputStreetAll.value = osmStreet || street;
        this.inputComment.value = '';
        this.msgDiv.textContent = '';
        this.msgDiv.className = '';
        this.submitBtn.disabled = false;
        this.submitBtn.textContent = 'Absenden';
        this.submitBtn.style.backgroundColor = '#3b82f6';

        // Show the fields matching the preselected type (reuses the change handler).
        this.typeSelect.dispatchEvent(new Event('change'));

        this.modal.style.display = 'block';
    }

    hide() {
        this.modal.style.display = 'none';
    }

    submit() {
        const type = this.typeSelect.value;
        let correction = {};

        const comment = this.inputComment.value.trim();
        if (!comment && type !== 'abbreviation') {
            this.msgDiv.textContent = 'Kommentar fehlt.';
            this.msgDiv.style.color = '#ef4444';
            return;
        }
        correction.comment = type === 'abbreviation' ? (comment ? 'Abkürzung: ' + comment : 'Abkürzung') : comment;

        if (type === 'street' || type === 'abbreviation') {
            correction.from_street = this.street;
            correction.city = currentDistrictName;

            const toStreet = this.inputStreetAll.value.trim();
            if (!toStreet) {
                this.msgDiv.textContent = 'Korrigierter Straßenname fehlt.';
                this.msgDiv.style.color = '#ef4444';
                return;
            }
            if (toStreet === this.street) {
                this.msgDiv.textContent = 'Bitte korrigierten Straßennamen eingeben.';
                this.msgDiv.style.color = '#ef4444';
                return;
            }
            correction.to_street = toStreet;

            if (this.alkisId) {
                correction.reference_alkis_id = this.alkisId;
            }
        } else if (type === 'ignore_street') {
            correction.from_street = this.street;
            correction.city = currentDistrictName;
            correction.ignore = true;
            if (this.alkisId) {
                correction.reference_alkis_id = this.alkisId;
            }
        } else {
            // Add alkis_id if available for single/ignore corrections
            if (this.alkisId) {
                correction.alkis_id = this.alkisId;
            }

            if (type === 'single') {
                const newStreet = this.inputSingleStreet.value.trim();
                const newHnr = this.inputSingleHnr.value.trim();

                if (!newStreet || !newHnr) {
                    this.msgDiv.textContent = 'Straße und Hausnummer dürfen nicht leer sein.';
                    this.msgDiv.style.color = '#ef4444';
                    return;
                }

                if (newStreet === this.street && newHnr === this.hnr) {
                    this.msgDiv.textContent = 'Bitte korrigierte Adresse eingeben.';
                    this.msgDiv.style.color = '#ef4444';
                    return;
                }

                correction.from_street = this.street;
                correction.from_housenumber = this.hnr;
                correction.city = currentDistrictName;
                correction.to_street = newStreet;
                correction.to_housenumber = newHnr;
            } else if (type === 'ignore') {
                correction.from_street = this.street;
                correction.from_housenumber = this.hnr;
                correction.city = currentDistrictName;
                correction.ignore = true;
            } else if (type === 'already_mapped') {
                correction.from_street = this.street;
                correction.from_housenumber = this.hnr;
                correction.city = currentDistrictName;
                correction.already_mapped = true;
            }
        }

        correction.type = type;

        this.submitBtn.disabled = true;
        this.submitBtn.textContent = 'Sende...';

        fetch('/api/save_correction', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                state: state || 'unknown',
                correction: correction
            }),
        })
            .then(response => {
                if (response.ok) {
                    this.msgDiv.textContent = 'Korrektur gespeichert. Erscheint ab ca. 7:00 Uhr auf der Karte';
                    this.msgDiv.style.color = '#10b981';
                    this.submitBtn.textContent = 'Gespeichert';
                    setTimeout(() => this.hide(), 1500);
                } else {
                    throw new Error('Server error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                this.msgDiv.textContent = 'Fehler beim Speichern.';
                this.msgDiv.style.color = '#ef4444';
                this.submitBtn.disabled = false;
                this.submitBtn.textContent = 'Absenden';
            });
    }
}
const correctionModal = new CorrectionModal();


let loadPromise;

if (state) {
    loadPromise = Promise.all([
        fetchDistricts(districtsUrl),
        fetchHistory(historyUrl),
        boundariesUrl ? fetchGeoJSON(boundariesUrl).catch(() => null) : Promise.resolve(null)
    ]);
} else {
    // Deutschland (Gesamt) Mode: Aggregate all states
    const statesToLoad = Object.keys(STATE_CONFIG);
    loadPromise = Promise.all([
        Promise.all(statesToLoad.map(s =>
            Promise.all([
                fetch(`/states/${s}/${s}_districts.json`).then(res => res.json()).catch(() => []),
                fetch(`/states/${s}/${s}_history.json`).then(res => res.json()).catch(() => ({ global: [], districts: {} }))
            ]).then(([d, h]) => ({ state: s, districts: d, history: h }))
        )),
        fetchGeoJSON('/state_boundaries.geojson').catch(() => null)
    ]).then(([allStateData, stateBoundaries]) => {
        let mergedDistricts = [];
        let mergedHistory = { global: [], districts: {}, states: {} };

        // Prepare unique dates and state histories
        const allDatesSet = new Set();
        const stateHistoryMaps = {};
        const firstPointByState = {};

        allStateData.forEach(item => {
            const stateHist = item.history.global || [];
            const historyMap = {};
            stateHist.forEach(h => {
                const d = h.date.split('T')[0];
                historyMap[d] = h;
                allDatesSet.add(d);
            });
            stateHistoryMaps[item.state] = historyMap;
            if (stateHist.length > 0) {
                firstPointByState[item.state] = stateHist[0];
            }
        });

        const sortedDates = Array.from(allDatesSet).sort();

        // Global aggregation with stabilization
        mergedHistory.global = sortedDates.map(date => {
            const aggregated = { date: date + "T12:00:00Z", total: 0, missing: 0, osm: 0 };

            allStateData.forEach(item => {
                const historyMap = stateHistoryMaps[item.state];
                let point = historyMap[date];

                if (!point) {
                    // Stabilization: Use the earliest known point if we are before the state's range
                    point = firstPointByState[item.state];
                }

                if (point) {
                    aggregated.total += (point.total || point.alkis || 0);
                    aggregated.missing += (point.missing || point.missing_count || 0);
                    aggregated.osm += (point.osm || 0);
                }
            });

            aggregated.coverage = aggregated.total > 0 ? (1 - (aggregated.missing / aggregated.total)) * 100 : 0;
            return aggregated;
        });

        // Districts and States
        allStateData.forEach(item => {
            const stateConf = STATE_CONFIG[item.state];
            const stateName = stateConf ? stateConf.name : item.state;

            item.districts.forEach(d => {
                const districtCopy = { ...d };
                districtCopy.name = `${d.name} (${item.state.toUpperCase()})`;
                districtCopy.originalName = d.name;
                mergedDistricts.push(districtCopy);
            });

            mergedHistory.states[stateName] = item.history.global || [];

            if (item.history.districts) {
                Object.entries(item.history.districts).forEach(([dName, dHist]) => {
                    mergedHistory.districts[`${dName} (${item.state.toUpperCase()})`] = dHist;
                });
            }
        });

        return [mergedDistricts, mergedHistory, stateBoundaries];
    });
}

loadPromise.then(([districts, history, boundariesGeoJSON]) => {
    districtsData = districts;
    historyDataStore = history;
    globalBoundariesGeoJSON = boundariesGeoJSON;

    if (globalBoundariesGeoJSON) {
        boundariesLayer = L.geoJSON(null, {
            filter: function (feature) {
                if (!feature.properties) return false;
                if (!state) return true; // Show all states in Deutschland mode
                const name = feature.properties.LANDKREIS || feature.properties.GEN || feature.properties.NAM;
                const mappedName = mapDistrictName(name, state, districtsData);
                return mappedName !== currentDistrictName;
            },
            style: function (feature) {
                const name = feature.properties.GEN || feature.properties.NAME || feature.properties.NAM;
                let coverage = null;

                if (!state) {
                    // colourize by state coverage
                    const stateHistory = historyDataStore.states ? historyDataStore.states[name] : null;
                    if (stateHistory && stateHistory.length > 0) {
                        const last = stateHistory[stateHistory.length - 1];
                        coverage = last.coverage;
                    }
                } else {
                    // colourize by district coverage
                    const mappedName = mapDistrictName(name, state, districtsData);
                    const dStats = districtsData ? districtsData.find(d => d.name === mappedName) : null;
                    coverage = dStats ? dStats.coverage : null;
                }

                const color = getCoverageColor(coverage);

                return {
                    color: color,
                    weight: state ? 2 : 3,
                    fillColor: color,
                    fillOpacity: 0.2,
                    opacity: 0.6
                };
            },
            onEachFeature: function (feature, layer) {
                const name = feature.properties.GEN || feature.properties.NAME || feature.properties.NAM;

                layer.on({
                    mouseover: function (e) {
                        const target = e.target;
                        target.setStyle({
                            fillOpacity: 0.3,
                            weight: state ? 3 : 5
                        });
                    },
                    mouseout: function (e) {
                        if (boundariesLayer) boundariesLayer.resetStyle(e.target);
                    },
                    click: function (e) {
                        if (!state) {
                            // redirect to state
                            const stateEntry = Object.entries(STATE_CONFIG).find(([id, config]) => config.name === name);
                            if (stateEntry) {
                                window.location.href = `addresses.html?state=${stateEntry[0]}`;
                            }
                        } else {
                            // redirect to district
                            const mappedName = mapDistrictName(name, state, districtsData);
                            const sel = document.getElementById('districtSelect');
                            if (sel) {
                                sel.value = mappedName;
                                loadDistrict(mappedName);
                            }
                        }
                    }
                });

                let label = name;
                if (state) {
                    const mappedName = mapDistrictName(name, state, districtsData);
                    label = mappedName.replace(/_/g, ' ');
                }
                layer.bindTooltip(label, { className: 'district-tooltip', direction: 'center', permanent: false });
            }
        }).addTo(map);
        boundariesLayer.addData(globalBoundariesGeoJSON);
    }

    // Populate Main Select
    const select = document.getElementById('districtSelect');
    if (select) {
        // Update Global Option Text
        const globalOpt = select.querySelector('option[value="Global"]');
        if (globalOpt) {
            globalOpt.textContent = `${config.name} (Gesamt)`;
        }

        districts.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.name;
            opt.textContent = `${d.name.replace(/_/g, ' ')} (${d.coverage}%)`;
            select.appendChild(opt);
        });

        select.value = "Global";
        select.addEventListener('change', (e) => loadDistrict(e.target.value));
    }

    // Init State Select
    const stateSelect = document.getElementById('stateSelect');
    if (stateSelect) {

        Object.entries(STATE_CONFIG).forEach(([key, conf]) => {
            const opt = document.createElement('option');
            opt.value = key;
            opt.textContent = conf.name;
            stateSelect.appendChild(opt);
        });

        if (state) {
            stateSelect.value = state;
        }

        stateSelect.addEventListener('change', (e) => {
            if (e.target.value) {
                window.location.href = `addresses.html?state=${e.target.value}`;
            } else {
                window.location.href = `addresses.html`;
            }
        });
    }

    // Init Stats Modal
    const statsModal = new StatsModal(districts, history, (name) => {
        const sel = document.getElementById('districtSelect');
        if (sel) {
            sel.value = name;
            loadDistrict(name);
        }
    }, config.name);

    // Handle stats button
    const statsBtn = document.querySelector('#controls button');
    if (statsBtn) {
        statsBtn.removeAttribute('onclick');
        statsBtn.addEventListener('click', () => statsModal.toggle(true, currentDistrictName));
    }

    // Initial Load
    const foundDistrict = districtFromUrl ? districts.find(d => d.name.toLowerCase() === districtFromUrl.toLowerCase()) : null;

    // Parse Hash
    const hashParams = window.location.hash.match(/#map=(\d+)\/([\d.-]+)\/([\d.-]+)/);
    let startView = null;
    if (hashParams) {
        startView = {
            zoom: parseInt(hashParams[1]),
            lat: parseFloat(hashParams[2]),
            lng: parseFloat(hashParams[3])
        };
    }

    // Map Events for Hash
    map.on('moveend zoomend', () => {
        const center = map.getCenter();
        const zoom = map.getZoom();
        const hash = `#map=${zoom}/${center.lat.toFixed(5)}/${center.lng.toFixed(5)}`;
        window.history.replaceState(null, null, window.location.pathname + window.location.search + hash);
    });

    if (startView) {
        map.setView([startView.lat, startView.lng], startView.zoom);
    }

    // Listen to manual hash changes
    window.addEventListener('hashchange', () => {
        const hashParams = window.location.hash.match(/#map=(\d+)\/([\d.-]+)\/([\d.-]+)/);
        if (hashParams) {
            const zoom = parseInt(hashParams[1]);
            const lat = parseFloat(hashParams[2]);
            const lng = parseFloat(hashParams[3]);
            map.setView([lat, lng], zoom);
        }
    });

    if (foundDistrict) {
        const sel = document.getElementById('districtSelect');
        if (sel) sel.value = foundDistrict.name;
        loadDistrict(foundDistrict.name, !!startView);
    } else {
        loadDistrict("Global", !!startView);
    }

}).catch(err => {
    console.error("Init Error:", err);
    document.getElementById('stats').innerText = `Fehler: Daten für ${state} konnten nicht geladen werden.`;
});


// Helper to check if a property is valid (not null/undefined/empty)
function isValid(val) {
    return val !== null && val !== undefined && val !== "nan" && val !== "";
}

// Helper to get done list from localStorage
function getDoneData() {
    try {
        const stored = localStorage.getItem('osm_alkis_done_by_district');
        return stored ? JSON.parse(stored) : {};
    } catch (e) {
        console.error("Error reading from localStorage", e);
        return {};
    }
}

function toggleDone(alkisId) {
    if (!alkisId || !currentDistrictName) return false;
    const data = getDoneData();
    // Ensure district array exists
    if (!data[currentDistrictName]) {
        data[currentDistrictName] = [];
    }

    const list = data[currentDistrictName];
    const index = list.indexOf(alkisId);
    let isDone = false;

    if (index > -1) {
        list.splice(index, 1);
        isDone = false;
    } else {
        list.push(alkisId);
        isDone = true;
    }

    localStorage.setItem('osm_alkis_done_by_district', JSON.stringify(data));
    return isDone;
}

function isDone(alkisId) {
    if (!alkisId || !currentDistrictName) return false;
    const data = getDoneData();
    const list = data[currentDistrictName]; // Only check current district
    return list ? list.includes(alkisId) : false;
}


// Add Legend
createLegend(map, visibilityState, (key, isChecked) => {
    visibilityState[key] = isChecked;

    try {
        localStorage.setItem('osm_alkis_coverage_legend_state', JSON.stringify(visibilityState));
    } catch (err) {
        console.warn("Could not save legend state", err);
    }

    // Re-render layer if exist
    if (currentLayer && currentGeoJSONData) {
        currentLayer.clearLayers();
        currentLayer.addData(currentGeoJSONData);
    }
});
