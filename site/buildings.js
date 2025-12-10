
// Init Map
const map = L.map('map').setView([52.9, 9.8], 8); // Niedersachsen view

// Basemap
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

let currentLayer = null;

// Initial Load
// Try to load district list first, if fails, fallback to loadGlobal (backward compat)
fetch('buildings/districts.json')
    .then(response => {
        if (!response.ok) throw new Error("No districts file");
        return response.json();
    })
    .then(districts => {
        // Populate Select
        const select = document.getElementById('districtSelect');
        districts.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.name;
            opt.textContent = `${d.name} (${d.count})`;
            select.appendChild(opt);
        });

        // Load first district by default? Or Global? 
        // User probably prefers Global if powerful enough, or first district if global is too heavy.
        // Let's stick to Global as default, which is pre-selected.
        loadGlobal();
    })
    .catch(err => {
        console.log("Districts metadata not found, loading global file directly.", err);
        loadGlobal();
    });

document.getElementById('districtSelect').addEventListener('change', (e) => {
    const val = e.target.value;
    if (val === 'Global') {
        loadGlobal();
    } else {
        loadDistrict(val);
    }
});

function loadGlobal() {
    loadData('missing_buildings.geojson', 'Gesamtes Niedersachsen');
}

function loadDistrict(name) {
    loadData(`buildings/${name}.geojson`, name);
}

function loadData(url, label) {
    if (currentLayer) {
        map.removeLayer(currentLayer);
        currentLayer = null;
    }

    document.getElementById('stats').innerText = `Lade ${label}...`;

    fetch(url)
        .then(response => {
            if (!response.ok) throw new Error("HTTP " + response.status);
            return response.json();
        })
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
                fillColor: "#ffa500", // Orange for buildings
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

                // JOSM Remote Control URL
                const lat = layer.getLatLng().lat;
                const lng = layer.getLatLng().lng;
                const delta = 0.0005; // Slightly closer zoom for building editing
                const josmUrl = `http://127.0.0.1:8111/load_and_zoom?left=${lng - delta}&right=${lng + delta}&top=${lat + delta}&bottom=${lat - delta}`;

                // Create Content
                const container = document.createElement('div');
                container.innerHTML = `
                    <strong>Adresse ohne Gebäude:</strong><br>
                    ${street} ${hnr}<br>
                    <small>${district}</small><br><br>
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

    const count = data.features ? data.features.length : 0;
    document.getElementById('stats').innerText = `${count} Adressen angezeigt.`;

    if (count > 0) {
        map.fitBounds(currentLayer.getBounds());
    }
}
