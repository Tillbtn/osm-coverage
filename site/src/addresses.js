import './style.css';
import L from 'leaflet';
import { createMap, createJOSMLink } from './modules/map';
import { fetchDistricts, fetchHistory, fetchGeoJSON } from './modules/api';
import { StatsModal } from './modules/StatsModal';

// State
let currentLayer = null;
let districtsData = [];
let sortCol = 'name';
let sortAsc = true;
let historyDataStore = null;

const STATE_CONFIG = {
    nds: { center: [52.9, 9.8], zoom: 8, name: "Niedersachsen" },
    nrw: { center: [51.4, 7.6], zoom: 8, name: "Nordrhein-Westfalen" },
    rlp: { center: [49.9, 7.3], zoom: 8, name: "Rheinland-Pfalz" }
};

let currentDistrictName = "";

// Configuration from URL or Body
const params = new URLSearchParams(window.location.search);
const stateFromUrl = params.get('state');
const districtFromUrl = params.get('district');
const state = stateFromUrl || document.body.dataset.state;

const config = STATE_CONFIG[state] || { center: [51.16, 10.45], zoom: 6, name: "Deutschland" };

// Update Page Title if State is present
if (state && config.name) {
    document.title = `OSM-ALKIS Adressenvergleich - ${config.name}`;
    const h1 = document.querySelector('h1');
    if (h1) h1.innerText = `OSM-ALKIS Adressenvergleich (${config.name})`;
}

// Path Construction
const districtsUrl = state ? `/states/${state}/${state}_districts.json` : '/districts.json';
const historyUrl = state ? `/states/${state}/${state}_history.json` : '/detailed_history.json';

// Init Map
const map = createMap('map');

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
                            <option value="ignore">Adresse ignorieren</option>
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

            if (e.target.value === 'single') this.fieldsSingle.style.display = 'block';
            if (e.target.value === 'street') this.fieldsStreet.style.display = 'block';
            if (e.target.value === 'ignore') this.fieldsIgnore.style.display = 'block';
        });

        this.submitBtn.addEventListener('click', () => this.submit());
    }

    open(street, hnr, alkisId) {
        this.street = street;
        this.hnr = hnr;
        this.alkisId = alkisId;
        this.displayAddress.textContent = `${street} ${hnr}`;

        // Reset fields
        this.typeSelect.value = 'single';
        this.fieldsSingle.style.display = 'block';
        this.fieldsStreet.style.display = 'none';
        this.fieldsIgnore.style.display = 'none';

        this.inputSingleStreet.value = street;
        this.inputSingleHnr.value = hnr;
        this.inputStreetAll.value = street;
        this.inputComment.value = '';
        this.msgDiv.textContent = '';
        this.msgDiv.className = '';
        this.submitBtn.disabled = false;
        this.submitBtn.textContent = 'Absenden';
        this.submitBtn.style.backgroundColor = '#3b82f6';

        this.modal.style.display = 'block';
    }

    hide() {
        this.modal.style.display = 'none';
    }

    submit() {
        const type = this.typeSelect.value;
        let correction = {};

        const comment = this.inputComment.value.trim();
        if (!comment) {
            this.msgDiv.textContent = 'Kommentar fehlt.';
            this.msgDiv.style.color = '#ef4444';
            return;
        }
        correction.comment = comment;

        if (type === 'street') {
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
            }
        }

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


Promise.all([
    state ? fetchDistricts(districtsUrl) : Promise.resolve([]),
    state ? fetchHistory(historyUrl) : Promise.resolve({ global: [], districts: {} })
]).then(([districts, history]) => {
    if (!state) {
        districts = [];
        history = { global: [], districts: {} };
    }
    districtsData = districts;
    historyDataStore = history;

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
        // Add Default Option
        const defaultOpt = document.createElement('option');
        defaultOpt.value = "";
        defaultOpt.textContent = "Deutschland";
        stateSelect.appendChild(defaultOpt);

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

    // Handle "Statistiken anzeigen" button (if present in HTML)
    // attach listener to existing button instead of inline onclick
    const statsBtn = document.querySelector('#controls button');
    if (statsBtn) {
        statsBtn.removeAttribute('onclick');
        statsBtn.addEventListener('click', () => statsModal.toggle());
    }

    // Initial Load
    const foundDistrict = districtFromUrl ? districts.find(d => d.name.toLowerCase() === districtFromUrl.toLowerCase()) : null;

    if (foundDistrict) {
        const sel = document.getElementById('districtSelect');
        if (sel) sel.value = foundDistrict.name;
        loadDistrict(foundDistrict.name);
    } else {
        loadDistrict("Global");
    }

}).catch(err => {
    console.error("Init Error:", err);
    document.getElementById('stats').innerText = `Fehler: Daten für ${state} konnten nicht geladen werden.`;
});


// Helper to check if a property is valid (not null/undefined and not "<NA>" string from pandas)
function isValid(val) {
    return val !== null && val !== undefined && val !== "<NA>" && val !== "nan" && val !== "";
}

function loadDistrict(name) {
    if (currentLayer) map.removeLayer(currentLayer);
    currentLayer = null;

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

        // If only case matched (canonicalization), use replaceState. Otherwise pushState.
        const isJustCaseDiff = currentParam && newParam && currentParam.toLowerCase() === newParam.toLowerCase();

        if (isJustCaseDiff) {
            window.history.replaceState({}, '', historyUrl);
        } else {
            window.history.pushState({}, '', historyUrl);
        }
    }

    if (name === "Global") {
        if (!state) {
            document.getElementById('stats').innerText = "";
            map.setView([initialLat, initialLng], initialZoom);
            return;
        }
        let totalMissing = 0;
        if (districtsData && districtsData.length > 0) {
            totalMissing = districtsData.reduce((sum, d) => sum + (d.missing || 0), 0);
        }
        document.getElementById('stats').innerText = `gesamt: ${totalMissing} fehlende Adressen`;
        map.setView([initialLat, initialLng], initialZoom);
        return;
    }

    document.getElementById('stats').innerText = `Lade ${name}...`;
    currentDistrictName = name;

    // Calculate URL
    let url = `/districts/${name}.geojson`; // Fallback (Legacy)
    if (districtsData) {
        const meta = districtsData.find(d => d.name === name);
        if (meta) {
            if (meta.state && meta.filename) {
                url = `/states/${meta.state}/districts/${meta.filename}`;
            }
            // Fallback to path property
            else if (meta.path) {
                if (meta.path.startsWith('states/')) {
                    url = '/' + meta.path;
                } else {
                    url = `/districts/${meta.path}`;
                }
            }
        }
    }

    // Note: Vite will serve these from public directory
    fetchGeoJSON(url)
        .then(data => {
            currentLayer = L.geoJSON(data, {
                pointToLayer: function (feature, latlng) {
                    let fillColor = "#ff4444"; // Red (Missing)

                    const props = feature.properties;
                    // If correction_type is valid:
                    // - If matched: Blue (#3b82f6)
                    // - If NOT matched: Purple (#8b5cf6)
                    // If matched but no correction_type: Green (#10b981)

                    if (props && isValid(props.correction_type)) {
                        if (props.correction_type === 'ignored') {
                            fillColor = "#9ca3af"; // Gray for ignored
                        } else if (props.matched) {
                            fillColor = "#3b82f6"; // Blue for corrected matches
                        } else {
                            fillColor = "#8b5cf6"; // Purple for corrected but unmatched
                        }
                    } else if (props && props.matched) {
                        fillColor = "#10b981"; // Green (Found without explicit correction)
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
                        const street = feature.properties.street || '';
                        const hnr = feature.properties.housenumber || '';
                        const isMatched = feature.properties.matched;
                        const comment = isValid(feature.properties.correction_comment) ? feature.properties.correction_comment : '';
                        const origStreet = feature.properties.original_street || street;
                        const origHnr = feature.properties.original_housenumber || hnr;

                        const lat = layer.getLatLng().lat;
                        const lng = layer.getLatLng().lng;

                        let title = "Fehlt in OSM:";
                        if (isMatched) {
                            if (feature.properties.correction_type === 'ignored') {
                                title = "Ignoriert:";
                            } else {
                                title = "Abweichung vom ALKIS:";
                            }
                        }

                        const container = document.createElement('div');
                        let content = "";

                        if (feature.properties.correction_type === 'ignored') {
                            content = `<strong>${title}</strong><br>
                                        <div style="margin-bottom: 4px;">
                                            <span style="color: #666; font-size: 0.9em;">ALKIS:</span><br>
                                            ${origStreet} ${origHnr}
                                        </div>`;
                        } else if (isMatched && (feature.properties.original_street || feature.properties.original_housenumber)) {
                            content = `<strong>${title}</strong><br>
                                        <div style="margin-bottom: 4px;">
                                            <span style="color: #666; font-size: 0.9em;">ALKIS:</span><br>
                                            ${origStreet} ${origHnr}
                                        </div>
                                        <div style="margin-bottom: 8px;">
                                            <span style="color: #666; font-size: 0.9em;">OSM:</span><br>
                                            ${street} ${hnr}
                                        </div>`;
                        } else {
                            // Standard Display
                            content = `<strong>${title}</strong><br>${street} ${hnr}<br><br>`;
                        }

                        // Show comment if valid, regardless of match status
                        if (comment) {
                            content += `<div style="font-style: italic; margin-bottom: 5px; color: #555;">${comment}</div>`;
                        }

                        if (!isMatched) {
                            content += `<button class="correction-init-btn" style="background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 0.375rem; cursor: pointer; font-weight: 500; width: 100%; margin-bottom: 5px;">ALKIS fehlerhaft?</button>`;
                        }

                        container.innerHTML = content;
                        container.appendChild(createJOSMLink(lat, lng));

                        // Bind event for modal only if button exists
                        const btn = container.querySelector('.correction-init-btn');
                        if (btn) {
                            btn.addEventListener('click', (e) => {
                                e.stopPropagation(); // prevent map events
                                correctionModal.open(street, hnr, feature.properties.alkis_id);
                                map.closePopup();
                            });
                        }

                        layer.bindPopup(container, { maxWidth: 300 });
                    }
                }
            });
            currentLayer.addTo(map);
            if (data.features.length > 0) {
                map.fitBounds(currentLayer.getBounds());
            }

            // Calculate stats based on matched property
            const missingCount = data.features.filter(f => !f.properties.matched).length;
            document.getElementById('stats').innerText = `${missingCount} fehlende Adressen`;
        })
        .catch(err => {
            console.error(err);
            document.getElementById('stats').innerText = 'Fehler beim Laden.';
        });
}

// Add Legend
const legend = L.control({ position: 'bottomleft' });

legend.onAdd = function (map) {
    const container = L.DomUtil.create('div', 'info legend');
    container.style.background = '#3b82f6';
    container.style.color = 'white';
    container.style.padding = '8px 12px';
    container.style.borderRadius = '5px';
    container.style.boxShadow = '0 0 15px rgba(0,0,0,0.2)';
    container.style.cursor = 'pointer';

    // Stop click propagation to map
    L.DomEvent.disableClickPropagation(container);

    // Title / Button
    const title = L.DomUtil.create('div', '', container);
    title.innerHTML = '<span style="font-size: 0.8em">▼</span>';
    title.style.fontSize = '14px';
    title.style.userSelect = 'none';

    // Content (Hidden by default)
    const content = L.DomUtil.create('div', '', container);
    content.style.display = 'none';
    content.style.marginTop = '10px';
    content.style.fontSize = '12px';
    content.style.lineHeight = '1.5';

    content.innerHTML = `
        <div><span style="display:inline-block;width:10px;height:10px;background:#ff4444;border-radius:50%;margin-right:5px;"></span> Existiert im ALKIS, fehlt in OSM</div>
        <div><span style="display:inline-block;width:10px;height:10px;background:#3b82f6;border-radius:50%;margin-right:5px;"></span> ALKIS korrigiert, deshalb in OSM gefunden</div>
        <div><span style="display:inline-block;width:10px;height:10px;background:#8b5cf6;border-radius:50%;margin-right:5px;"></span> ALKIS korrigiert, nicht in OSM gefunden</div>
        <div><span style="display:inline-block;width:10px;height:10px;background:#9ca3af;border-radius:50%;margin-right:5px;"></span> ALKIS ignoriert</div>
    `;

    // Toggle Logic
    let expanded = false;
    container.onclick = function () {
        expanded = !expanded;
        if (expanded) {
            content.style.display = 'block';
            title.innerHTML = '<strong>Legende</strong> <span style="font-size: 0.8em">▲</span>';
            container.style.background = 'white';
            container.style.color = 'black';
        } else {
            content.style.display = 'none';
            title.innerHTML = '<span style="font-size: 0.8em">▼</span>';
            container.style.background = '#3b82f6';
            container.style.color = 'white';
        }
    };

    return container;
};

legend.addTo(map);
