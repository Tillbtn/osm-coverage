import './style.css';
import L from 'leaflet';
import { createMap, createJOSMLink } from './modules/map';
import { fetchDistricts, fetchHistory, fetchGeoJSON } from './modules/api';
import { initHistoryChart, updateChart, renderHistoryTable, initComparisonChart } from './modules/ui';

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

    // Populate Stats Chart Select
    const statsSelect = document.getElementById('statsChartSelect');
    if (statsSelect) {
        districts.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.name;
            opt.textContent = d.name;
            statsSelect.appendChild(opt);
        });
        statsSelect.addEventListener('change', (e) => {
            const dataset = updateChart(e.target.value, historyDataStore);
            renderHistoryTable(dataset, '#historyTable tbody');
        });
    }

    // Init Charts
    if (history) {
        const historyCtx = document.getElementById('historyChart').getContext('2d');
        initHistoryChart(historyCtx, history);

        const compCtx = document.getElementById('comparisonChart').getContext('2d');
        initComparisonChart(compCtx, history);

        if (history.global) renderHistoryTable(history.global, '#historyTable tbody');
    }

    // Initial Stats Render
    renderStatsTable();

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

function renderStatsTable() {
    const tbody = document.querySelector('#statsTable tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const sortedData = [...districtsData].sort((a, b) => {
        let valA = a[sortCol];
        let valB = b[sortCol];

        if (typeof valA === 'string') valA = valA.toLowerCase();
        if (typeof valB === 'string') valB = valB.toLowerCase();

        if (valA < valB) return sortAsc ? -1 : 1;
        if (valA > valB) return sortAsc ? 1 : -1;
        return 0;
    });

    sortedData.forEach(d => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${d.name}</td>
            <td>${d.total}</td>
            <td>${d.missing}</td>
            <td>${d.coverage}%</td>
        `;
        tr.onclick = () => {
            document.getElementById('districtSelect').value = d.name;
            loadDistrict(d.name);
            const modal = document.getElementById('stats-modal');
            if (modal) modal.style.display = "none";
        };
        tr.style.cursor = 'pointer';
        tbody.appendChild(tr);
    });
}

// Window globals for HTML onclick handlers (e.g. toggleStats)
// Since we are module, we need to attach to window explicitly if keeping inline onclicks
// But better to convert to listeners.
// For now, attaching to window for backward compatibility with HTML
window.toggleStats = function () {
    const modal = document.getElementById('stats-modal');
    if (modal) {
        modal.style.display = modal.style.display === 'block' ? 'none' : 'block';
    }
};

window.sortStats = function (col) {
    if (sortCol === col) {
        sortAsc = !sortAsc;
    } else {
        sortCol = col;
        sortAsc = true;
    }
    renderStatsTable();
};
