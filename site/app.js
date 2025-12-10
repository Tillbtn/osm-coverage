
// State
// State
let currentLayer = null;
let districtsData = [];
let sortCol = 'name';
let sortAsc = true;
let chartInstance = null;

// Init Map
const map = L.map('map').setView([52.9, 9.8], 8); // Niedersachsen view

// Basemap
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

// Load Meta Data (Districts & History)
let historyDataStore = null;

// Add cache buster to prevent stale data issues
const ts = new Date().getTime();

Promise.all([
    fetch(`districts.json?t=${ts}`).then(r => {
        if (!r.ok) throw new Error("Failed to load districts.json");
        return r.json();
    }),
    fetch(`detailed_history.json?t=${ts}`).then(r => {
        if (!r.ok) {
            console.warn("detailed_history.json missing or invalid");
            return null;
        }
        return r.json();
    })
]).then(([districts, history]) => {
    // ... (rest is same until renderHistoryTable)

    function renderHistoryTable(dataset) {
        const tbody = document.querySelector('#historyTable tbody');
        tbody.innerHTML = '';

        // Copy and reverse to show newest first
        const reversed = [...dataset].reverse();

        // Debug logging
        console.log("Rendering table with", reversed.length, "entries", reversed[0]);

        reversed.forEach(h => {
            const tr = document.createElement('tr');
            // Handle varying keys (alkis_count vs total) if schema changed, though standard now is total/missing/coverage
            const total = h.total !== undefined ? h.total : (h.alkis !== undefined ? h.alkis : 0);
            const missing = h.missing !== undefined ? h.missing : (h.missing_count !== undefined ? h.missing_count : 0);
            const cov = h.coverage !== undefined ? h.coverage : (h.coverage_percent !== undefined ? h.coverage_percent : 0);

            tr.innerHTML = `
            <td>${h.date}</td>
            <td>${total}</td>
            <td>${missing}</td>
            <td>${cov}%</td>
        `;
            tbody.appendChild(tr);
        });
    }
    districtsData = districts;
    historyDataStore = history;

    // Populate Main Select
    const select = document.getElementById('districtSelect');
    // Clear existing (except Global)? No, specific Global option is hardcoded in HTML.
    // Ensure we don't duplicate if re-running logic (not issue here).

    districts.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.name;
        opt.textContent = `${d.name} (${d.coverage}%)`;
        select.appendChild(opt);
    });

    // Populate Stats Chart Select
    const statsSelect = document.getElementById('statsChartSelect');
    districts.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.name;
        opt.textContent = d.name;
        statsSelect.appendChild(opt);
    });

    statsSelect.addEventListener('change', (e) => {
        updateChart(e.target.value);
    });

    // Initial Load - default to Global to solve "not loading"
    select.value = "Global";
    loadDistrict("Global");

    // Init History Chart (Global by default)
    if (history) {
        initChart(history);
        initComparisonChart(history);

        // Initial render of table for Global
        if (history.global) renderHistoryTable(history.global);
    }

    // Initial Stats Render
    renderStatsTable();
}).catch(err => {
    console.error("Init Error:", err);
    document.getElementById('stats').innerText = "Fehler beim Initialisieren: " + err.message;
});

document.getElementById('districtSelect').addEventListener('change', (e) => {
    loadDistrict(e.target.value);
});

function loadDistrict(name) {
    if (currentLayer) map.removeLayer(currentLayer);
    currentLayer = null;

    if (name === "Global") {
        document.getElementById('stats').innerText = "Gesamtes Niedersachsen (Karte deaktiviert für Performance)";
        // Optionally fit bounds to Niedersachsen
        map.setView([52.9, 9.8], 8);
        return;
    }

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

function initChart(historyData) {
    const ctx = document.getElementById('historyChart').getContext('2d');

    // Default to global
    const globalData = historyData.global || [];

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: globalData.map(h => h.date),
            datasets: [{
                label: 'Abdeckung (%)',
                data: globalData.map(h => h.coverage || h.coverage_percent),
                borderColor: 'rgb(75, 192, 192)',
                tension: 0.1
            }]
        },
        options: {
            maintainAspectRatio: false,
            responsive: true,
            scales: {
                y: {
                    beginAtZero: false,
                    title: { display: true, text: 'Abdeckung (%)' }
                }
            }
        }
    });
}

function updateChart(districtName) {
    if (!historyDataStore || !chartInstance) return;

    let dataset = [];
    let isGlobal = false;
    if (districtName === "global" || districtName === "Global") {
        dataset = historyDataStore.global || [];
        isGlobal = true;
    } else {
        dataset = (historyDataStore.districts && historyDataStore.districts[districtName]) ? historyDataStore.districts[districtName] : [];
    }

    // Toggle Comparison Chart Visibility
    const compSection = document.getElementById('comparisonChartSection');
    if (compSection) {
        compSection.style.display = isGlobal ? 'block' : 'none';
        // Resize chart if showing?
        if (isGlobal) {
            // window.dispatchEvent(new Event('resize')); // Optional force redraw if needed
        }
    }

    // Existing Update Logic
    chartInstance.data.labels = dataset.map(h => h.date);
    chartInstance.data.datasets[0].data = dataset.map(h => h.coverage || h.coverage_percent);
    chartInstance.data.datasets[0].label = `Abdeckung ${districtName} (%)`;
    chartInstance.update();

    renderHistoryTable(dataset);
}

function renderHistoryTable(dataset) {
    const tbody = document.querySelector('#historyTable tbody');
    tbody.innerHTML = '';

    // Copy and reverse to show newest first
    const reversed = [...dataset].reverse();

    reversed.forEach(h => {
        const tr = document.createElement('tr');
        // Handle varying keys (alkis_count vs total) if schema changed, though standard now is total/missing/coverage
        const total = h.total || h.alkis || 0;
        const missing = h.missing || h.missing_count || 0;
        const cov = h.coverage || h.coverage_percent || 0;

        tr.innerHTML = `
            <td>${h.date}</td>
            <td>${total}</td>
            <td>${missing}</td>
            <td>${cov}%</td>
        `;
        tbody.appendChild(tr);
    });
}

function initComparisonChart(historyData) {
    console.log("Initializing Comparison Chart...", historyData);
    const ctx = document.getElementById('comparisonChart').getContext('2d');
    const districts = historyData.districts || {};

    console.log("Districts keys:", Object.keys(districts).length);

    const datasets = [];

    // Define a simple color generator
    const getColor = (str) => {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            hash = str.charCodeAt(i) + ((hash << 5) - hash);
        }
        const c = (hash & 0x00FFFFFF).toString(16).toUpperCase();
        return '#' + "00000".substring(0, 6 - c.length) + c;
    };

    Object.keys(districts).forEach(name => {
        const dHist = districts[name];
        if (!dHist || dHist.length === 0) return;

        datasets.push({
            label: name,
            data: dHist.map(h => h.coverage || h.coverage_percent),
            borderColor: getColor(name),
            points: false,
            pointRadius: 0,
            borderWidth: 1,
            fill: false,
            tension: 0.1
        });
    });

    console.log("Generated datasets:", datasets.length);

    // Use dates from Global as X-Axis source (assuming all sync approx same days)
    // Or collect all unique dates.
    const uniqueDates = new Set();
    if (historyData.global) historyData.global.forEach(h => uniqueDates.add(h.date));
    Object.values(districts).forEach(arr => arr.forEach(h => uniqueDates.add(h.date)));
    const labels = Array.from(uniqueDates).sort();

    console.log("Labels:", labels);

    // Map data to labels to handle missing dates in some series?
    // Chart.js handles this by index usually unless we parse Time.
    // For simplicity, assuming data is generated daily for all. 
    // If mismatch, Chart.js might show misaligned.
    // Ideally we map {x: date, y: val}.

    // Let's use Object format for safety
    const safeDatasets = datasets.map(ds => {
        return {
            ...ds,
            // Find correct data point for each label? 
            // Or just rely on order if consistent. 
            // '04_compare.py' runs for all districts at once, so dates match.
            // Simple mapping is fine.
        };
    });

    if (datasets.length === 0) {
        console.warn("No datasets for comparison chart!");
        return;
    }

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: safeDatasets
        },
        options: {
            maintainAspectRatio: false,
            responsive: true,
            interaction: {
                mode: 'nearest',
                axis: 'x',
                intersect: false
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { boxWidth: 10, font: { size: 9 } }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false
                }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    title: { display: true, text: 'Abdeckung (%)' }
                }
            }
        }
    });
}

function toggleStats() {
    const modal = document.getElementById('stats-modal');
    const isShowing = modal.style.display === 'block';
    modal.style.display = isShowing ? 'none' : 'block';

    if (!isShowing && chartInstance) {
        // We just opened it
        setTimeout(() => {
            chartInstance.resize();
        }, 100);
    }
}

function renderStatsTable() {
    const tbody = document.querySelector('#statsTable tbody');
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
            // Optional: Click row to load district
            document.getElementById('districtSelect').value = d.name;
            loadDistrict(d.name);
            toggleStats(); // Close modal on selection
        };
        tr.style.cursor = 'pointer';
        tbody.appendChild(tr);
    });

    // Update header arrow indicators if desired (simple version)
    document.querySelectorAll('#statsTable th').forEach(th => {
        if (th.textContent.includes('↕')) {
            // Reset
        }
    });
}

function sortStats(col) {
    if (sortCol === col) {
        sortAsc = !sortAsc;
    } else {
        sortCol = col;
        sortAsc = true;
    }
    renderStatsTable();
}

// Close modal when clicking outside
window.onclick = function (event) {
    const modal = document.getElementById('stats-modal');
    if (event.target == modal) {
        modal.style.display = "none";
    }
}
