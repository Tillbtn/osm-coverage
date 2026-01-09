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
                        container.innerHTML = `<strong>Fehlt in OSM:</strong><br>${street} ${hnr}<br><br>`;
                        container.appendChild(createJOSMLink(lat, lng));

                        layer.bindPopup(container);
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
