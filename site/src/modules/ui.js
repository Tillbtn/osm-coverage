import Chart from 'chart.js/auto';

let chartInstance = null;

export function initHistoryChart(ctx, historyData) {
    const globalData = historyData.global || [];

    if (chartInstance) {
        chartInstance.destroy();
    }

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
    return chartInstance;
}

export function updateChart(districtName, historyData) {
    if (!historyData || !chartInstance) return;

    let dataset = [];
    if (districtName === "Global" || districtName === "global") {
        dataset = historyData.global || [];
    } else {
        dataset = (historyData.districts && historyData.districts[districtName]) ? historyData.districts[districtName] : [];
    }

    // Update chart
    chartInstance.data.labels = dataset.map(h => h.date);
    chartInstance.data.datasets[0].data = dataset.map(h => h.coverage || h.coverage_percent);
    chartInstance.data.datasets[0].label = `Abdeckung ${districtName} (%)`;
    chartInstance.update();

    return dataset; // Return for table render
}

export function renderHistoryTable(dataset, tableBodyId) {
    const tbody = document.querySelector(tableBodyId);
    if (!tbody) return;
    tbody.innerHTML = '';

    const reversed = [...dataset].reverse();

    reversed.forEach(h => {
        const tr = document.createElement('tr');
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

export function initComparisonChart(ctx, historyData) {
    // console.log("Initializing Comparison Chart...", historyData);
    const districts = historyData.districts || {};
    const datasets = [];

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

    const uniqueDates = new Set();
    if (historyData.global) historyData.global.forEach(h => uniqueDates.add(h.date));
    Object.values(districts).forEach(arr => arr.forEach(h => uniqueDates.add(h.date)));
    const labels = Array.from(uniqueDates).sort();

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets
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

