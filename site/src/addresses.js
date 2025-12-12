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

// Init Map
const map = createMap('map');

Promise.all([
    fetchDistricts(),
    fetchHistory()
]).then(([districts, history]) => {
    districtsData = districts;
    historyDataStore = history;

    // Populate Main Select
    const select = document.getElementById('districtSelect');
    if (select) {
        districts.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.name;
            opt.textContent = `${d.name} (${d.coverage}%)`;
            select.appendChild(opt);
        });

        select.value = "Global";
        select.addEventListener('change', (e) => loadDistrict(e.target.value));
    }

    // Init Stats Modal
    const statsModal = new StatsModal(districts, history, (name) => {
        const sel = document.getElementById('districtSelect');
        if (sel) {
            sel.value = name;
            loadDistrict(name);
        }
    });

    // Handle "Statistiken anzeigen" button (if present in HTML)
    // We attach listener to existing button instead of inline onclick
    const statsBtn = document.querySelector('#controls button');
    if (statsBtn) {
        statsBtn.removeAttribute('onclick');
        statsBtn.addEventListener('click', () => statsModal.toggle());
    }

    // Initial Load
    loadDistrict("Global");

}).catch(err => {
    console.error("Init Error:", err);
});


function loadDistrict(name) {
    if (currentLayer) map.removeLayer(currentLayer);
    currentLayer = null;

    if (name === "Global") {
        let totalMissing = 0;
        if (districtsData && districtsData.length > 0) {
            totalMissing = districtsData.reduce((sum, d) => sum + (d.missing || 0), 0);
        }
        document.getElementById('stats').innerText = `${totalMissing} fehlende Adressen`;
        map.setView([52.9, 9.8], 8);
        return;
    }

    document.getElementById('stats').innerText = `Lade ${name}...`;

    // Note: Vite will serve these from public/districts/
    fetchGeoJSON(`/districts/${name}.geojson`)
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
            // document.getElementById('stats').innerText = `${name}: ${data.features.length} fehlende Adressen`;
            document.getElementById('stats').innerText = `${data.features.length} fehlende Adressen`;
        })
        .catch(err => {
            console.error(err);
            document.getElementById('stats').innerText = 'Fehler beim Laden.';
        });
}

// Globals removed - using StatsModal

