import './style.css';
import L from 'leaflet';
import { createMap, createJOSMLink } from './modules/map';
import { fetchGeoJSON } from './modules/api';

const map = createMap('map');
let currentLayer = null;
let districtsData = [];

// Populate District Select
// Note: buildings/districts.json might be different from root districts.json
// It seems it was fetched from 'buildings/districts.json'
fetch('/buildings/districts.json') // Absolute path for public
    .then(response => {
        if (!response.ok) throw new Error("No districts file");
        return response.json();
    })
    .then(districts => {
        districtsData = districts;
        const select = document.getElementById('districtSelect');
        if (select) {
            districts.forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.name;
                opt.textContent = `${d.name} (${d.count})`;
                select.appendChild(opt);
            });

            select.addEventListener('change', (e) => {
                const val = e.target.value;
                if (val === 'Global') loadGlobal();
                else loadDistrict(val);
            });
        }
        loadGlobal();
    })
    .catch(err => {
        console.log("Districts metadata not found, loading global file directly.", err);
        loadGlobal();
    });


function loadGlobal() {
    // Attempt to determine state name from context or default
    const state = document.body.dataset.state;
    let label = "Gesamtes Gebiet";
    if (state === 'nds') label = "Gesamtes Niedersachsen";
    else if (state === 'nrw') label = "Gesamtes NRW";
    else if (state === 'rlp') label = "Gesamtes Rheinland-Pfalz";

    loadData('/missing_buildings.geojson', label);
}

function loadDistrict(name) {
    let url = `/buildings/${name}.geojson`;
    if (districtsData) {
        const meta = districtsData.find(d => d.name === name);
        if (meta && meta.path) {
            url = `/buildings/${meta.path}`;
        }
    }
    loadData(url, name);
}

function loadData(url, label) {
    if (currentLayer) {
        map.removeLayer(currentLayer);
        currentLayer = null;
    }

    document.getElementById('stats').innerText = `Lade ${label}...`;

    fetchGeoJSON(url)
        .then(data => renderData(data))
        .catch(err => {
            console.error(err);
            document.getElementById('stats').innerText = 'Konnte Daten nicht laden.';
        });
}

function renderData(data) {
    currentLayer = L.geoJSON(data, {
        pointToLayer: function (feature, latlng) {
            return L.circleMarker(latlng, {
                radius: 5,
                fillColor: "#ffa500", // Orange
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
                const district = feature.properties.district || '';

                const lat = layer.getLatLng().lat;
                const lng = layer.getLatLng().lng;

                const container = document.createElement('div');
                container.innerHTML = `
                    <strong>Adresse ohne Gebäude:</strong><br>
                    ${street} ${hnr}<br>
                    <small>${district}</small><br><br>
                `;
                container.appendChild(createJOSMLink(lat, lng));

                layer.bindPopup(container);
            }
        }
    });

    currentLayer.addTo(map);

    const count = data.features ? data.features.length : 0;
    document.getElementById('stats').innerText = `${count} Adressen angezeigt.`;

    if (count > 0) {
        map.fitBounds(currentLayer.getBounds());
    }
}
