
// State
let currentLayer = null;

// Init Map
const map = L.map('map').setView([52.9, 9.8], 8); // Niedersachsen view

// Basemap
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

// Load Meta Data (Districts & History)
Promise.all([
    fetch('districts.json').then(r => r.json()),
    fetch('history.json').then(r => r.ok ? r.json() : [])
]).then(([districts, history]) => {
    // Populate Select
    const select = document.getElementById('districtSelect');
    districts.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.name;
        opt.textContent = `${d.name} (${d.coverage}%)`;
        select.appendChild(opt);
    });

    // Initial Load
    if (districts.length > 0) {
        select.value = districts[0].name;
        loadDistrict(districts[0].name);
    }

    // Init History Chart
    if (history.length > 0) {
        initChart(history);
    }
});

document.getElementById('districtSelect').addEventListener('change', (e) => {
    loadDistrict(e.target.value);
});

function loadDistrict(name) {
    if (currentLayer) map.removeLayer(currentLayer);

    document.getElementById('stats').innerText = `Lade ${name}...`;

    fetch(`districts/${name}.geojson`)
        .then(response => response.json())
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

                        // JOSM Remote Control URL
                        const lat = layer.getLatLng().lat;
                        const lng = layer.getLatLng().lng;
                        const delta = 0.001;
                        const josmUrl = `http://127.0.0.1:8111/load_and_zoom?left=${lng - delta}&right=${lng + delta}&top=${lat + delta}&bottom=${lat - delta}`;

                        // Create Content
                        const container = document.createElement('div');
                        container.innerHTML = `
                            <strong>Fehlt in OSM:</strong><br>
                            ${street} ${hnr}<br><br>
                            <a href="#" class="josm-link">In JOSM editieren</a>
                        `;

                        // Attach Event Listener for Silent Fetch
                        const link = container.querySelector('.josm-link');
                        link.onclick = (e) => {
                            e.preventDefault();
                            fetch(josmUrl).catch(err => {
                                console.error(err);
                                alert("JOSM nicht erreichbar? (Fernsteuerung aktivieren!)");
                            });
                        };

                        layer.bindPopup(container);
                    }
                }
            });
            currentLayer.addTo(map);
            if (data.features.length > 0) {
                map.fitBounds(currentLayer.getBounds());
            }
            // Update stats text
            document.getElementById('stats').innerText = `${name}: ${data.features.length} fehlende Adressen`;
        })
        .catch(err => {
            console.error(err);
            document.getElementById('stats').innerText = 'Fehler beim Laden.';
        });
}

function initChart(history) {
    const ctx = document.getElementById('historyChart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: history.map(h => h.date),
            datasets: [{
                label: 'Abdeckung (%)',
                data: history.map(h => h.coverage_percent),
                borderColor: 'rgb(75, 192, 192)',
                tension: 0.1
            }]
        }
    });
}

function toggleHistory() {
    const el = document.getElementById('history-container');
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
    setTimeout(() => map.invalidateSize(), 100);
}
