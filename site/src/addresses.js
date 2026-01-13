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
                        <h2 style="margin: 0; font-size: 1.25rem;">Korrektur</h2>
                        <span class="close-correction-button" style="cursor: pointer; font-size: 1.5rem; line-height: 1;">&times;</span>
                    </div>
                    <div style="padding: 1.5rem;">
                        <div style="margin-bottom: 1rem; background: #f3f4f6; padding: 0.75rem; border-radius: 4px;">
                            <strong>Adresse:</strong><br>
                            <span id="corr-modal-address"></span>
                        </div>

                        <select id="corr-type" style="width: 100%; margin-bottom: 1rem; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem;">
                            <option value="single">Adresse korrigieren</option>
                            <option value="street">Straßenname korrigieren</option>
                            <option value="ignore">Adresse ignorieren</option>
                        </select>
                        
                        <div id="corr-fields-single">
                            <label style="display: block; margin-bottom: 0.25rem; font-size: 0.9em; color: #4b5563;">OSM-Straßenname</label>
                            <input id="corr-single-street" style="width: 100%; margin-bottom: 0.75rem; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem;">
                            
                            <label style="display: block; margin-bottom: 0.25rem; font-size: 0.9em; color: #4b5563;">OSM-Hausnummer</label>
                            <input id="corr-single-hnr" style="width: 100%; margin-bottom: 0.75rem; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem;">
                        </div>

                        <div id="corr-fields-street" style="display:none;">
                            <label style="display: block; margin-bottom: 0.25rem; font-size: 0.9em; color: #4b5563;">OSM-Straßenname</label>
                            <input id="corr-street-all" style="width: 100%; margin-bottom: 0.75rem; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 0.375rem;">
                        </div>

                        <div id="corr-fields-ignore" style="display:none;">
                        </div>

                        <label style="display: block; margin-bottom: 0.25rem; font-size: 0.9em; color: #4b5563;">Kommentar (optional)</label>
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

    open(street, hnr) {
        this.street = street;
        this.hnr = hnr;
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
        if (comment) {
            correction.comment = comment;
        }

        if (type === 'street') {
            correction.from_street = this.street;
            correction.city = currentDistrictName;
            correction.to_street = this.inputStreetAll.value;
        } else if (type === 'single') {
            correction.from_street = this.street;
            correction.from_housenumber = this.hnr;
            correction.city = currentDistrictName;
            correction.to_street = this.inputSingleStreet.value;
            correction.to_housenumber = this.inputSingleHnr.value;
        } else if (type === 'ignore') {
            correction.from_street = this.street;
            correction.from_housenumber = this.hnr;
            correction.city = currentDistrictName;
            correction.ignore = true;
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
                    this.msgDiv.textContent = 'Korrektur gespeichert!';
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
    loadDistrict("Global");

}).catch(err => {
    console.error("Init Error:", err);
    document.getElementById('stats').innerText = `Fehler: Daten für ${state} konnten nicht geladen werden.`;
});


function loadDistrict(name) {
    if (currentLayer) map.removeLayer(currentLayer);
    currentLayer = null;

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
                    return L.circleMarker(latlng, {
                        radius: 6,
                        fillColor: "#ff4444",
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

                        const lat = layer.getLatLng().lat;
                        const lng = layer.getLatLng().lng;

                        const container = document.createElement('div');
                        container.innerHTML = `
                            <strong>Fehlt in OSM:</strong><br>${street} ${hnr}<br><br>
                            <button class="correction-init-btn" style="background: #3b82f6; color: white; border: none; padding: 0.5rem 1rem; border-radius: 0.375rem; cursor: pointer; font-weight: 500; width: 100%; margin-bottom: 5px;">Korrektur</button>
                        `;
                        container.appendChild(createJOSMLink(lat, lng));

                        // Bind event for modal
                        const btn = container.querySelector('.correction-init-btn');
                        btn.addEventListener('click', (e) => {
                            e.stopPropagation(); // prevent map events
                            correctionModal.open(street, hnr);
                            map.closePopup();
                        });

                        layer.bindPopup(container, { maxWidth: 300 });
                    }
                }
            });
            currentLayer.addTo(map);
            if (data.features.length > 0) {
                map.fitBounds(currentLayer.getBounds());
            }
            document.getElementById('stats').innerText = `${data.features.length} fehlende Adressen`;
        })
        .catch(err => {
            console.error(err);
            document.getElementById('stats').innerText = 'Fehler beim Laden.';
        });
}
