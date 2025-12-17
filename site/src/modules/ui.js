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
                rawData: globalData,
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
                    title: { display: true, text: 'Abdeckung (%)' },
                    ticks: { callback: (val) => val.toFixed(2) + '%' }
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += context.parsed.y.toFixed(2) + '%';
                            }
                            return label;
                        },
                        afterLabel: function (context) {
                            const index = context.dataIndex;
                            const dataset = context.dataset.data;
                            const rawData = context.dataset.rawData;

                            if (index > 0) {
                                const current = dataset[index];
                                const previous = dataset[index - 1];
                                const diff = (current - previous).toFixed(2);
                                const sign = diff >= 0 ? '+' : '';

                                let lines = [`${sign}${diff}%`];

                                if (rawData) {
                                    const currMiss = rawData[index].missing ?? rawData[index].missing_count ?? 0;
                                    const prevMiss = rawData[index - 1].missing ?? rawData[index - 1].missing_count ?? 0;
                                    const absDiff = prevMiss - currMiss;
                                    const absSign = absDiff >= 0 ? '+' : '';
                                    lines.push(`${absSign}${absDiff} Adressen`);
                                }

                                return lines;
                            }
                            return null;
                        }
                    }
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
    chartInstance.data.datasets[0].rawData = dataset;
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
            <td>${cov.toFixed(2)}%</td>
        `;
        tbody.appendChild(tr);
    });
}

let comparisonChartInstance = null;

export function updateComparisonChart(ctx, historyData, mode = 'lines') {
    if (comparisonChartInstance) {
        comparisonChartInstance.destroy();
    }

    const districts = historyData.districts || {};

    // --- MODE: LINES (All Districts) ---
    // if (mode === 'lines') {
    //     const datasets = [];
    //     const getColor = (str) => {
    //         let hash = 0;
    //         for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
    //         const c = (hash & 0x00FFFFFF).toString(16).toUpperCase();
    //         return '#' + "00000".substring(0, 6 - c.length) + c;
    //     };

    //     Object.keys(districts).forEach(name => {
    //         const dHist = districts[name];
    //         if (!dHist || dHist.length === 0) return;
    //         datasets.push({
    //             label: name,
    //             data: dHist.map(h => h.coverage || h.coverage_percent),
    //             borderColor: getColor(name),
    //             points: false, pointRadius: 0, borderWidth: 1, fill: false, tension: 0.1
    //         });
    //     });

    //     const uniqueDates = new Set();
    //     if (historyData.global) historyData.global.forEach(h => uniqueDates.add(h.date));
    //     Object.values(districts).forEach(arr => arr.forEach(h => uniqueDates.add(h.date)));
    //     const labels = Array.from(uniqueDates).sort();

    //     comparisonChartInstance = new Chart(ctx, {
    //         type: 'line',
    //         data: { labels, datasets },
    //         options: {
    //             maintainAspectRatio: false, responsive: true,
    //             interaction: { mode: 'nearest', axis: 'x', intersect: false },
    //             plugins: { legend: { display: false } }, // Hide legend for 40+ lines
    //             scales: {
    //                 y: {
    //                     beginAtZero: false,
    //                     title: { display: true, text: 'Abdeckung (%)' },
    //                     ticks: { callback: (val) => val.toFixed(2) + '%' }
    //                 }
    //             }
    //         }
    //     });
    //     return;
    // }

    // --- MODE: TOP IMPROVERS (Bar Chart) ---
    // mode = 'top1', 'top7' or 'top30'
    let days = 7;
    if (mode === 'top30') days = 30;
    if (mode === 'top1') days = 1;

    // Calculate improvements
    const improvers = [];

    Object.keys(districts).forEach(name => {
        const dHist = districts[name];
        if (!dHist || dHist.length < 2) return;

        // Sort by date just in case
        // Assuming date format YYYY-MM-DD which sorts alphabetically correctly
        // But better be safe if logic evolves
        // dHist is already sorted by append logic usually.

        const latest = dHist[dHist.length - 1];
        const latestDate = new Date(latest.date);

        // Find past entry
        const targetDate = new Date(latestDate);
        targetDate.setDate(latestDate.getDate() - days);
        const targetDateStr = targetDate.toISOString().split('T')[0];

        // Find entry closest to targetDate (but <= targetDate or just close?)
        // Let's find first entry >= targetDate
        // Simple search
        let past = dHist.find(h => h.date >= targetDateStr);
        if (!past) past = dHist[0]; // Fallback to oldest

        // Use MISSING COUNT for absolute improvement
        const currentMissing = latest.missing !== undefined ? latest.missing : (latest.missing_count || 0);
        const pastMissing = past.missing !== undefined ? past.missing : (past.missing_count || 0);

        // Improvement = Reduction in missing addresses
        const delta = pastMissing - currentMissing;

        improvers.push({ name: name.replace(/_/g, ' '), delta, currentMissing, pastMissing });
    });

    // Sort descending
    improvers.sort((a, b) => b.delta - a.delta);

    // Top 10
    const top10 = improvers.slice(0, 10);

    comparisonChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: top10.map(i => i.name),
            datasets: [{
                label: `hinzugefügte Adressen (letzte ${days} Tage)`,
                data: top10.map(i => i.delta),
                backgroundColor: 'rgba(75, 192, 192, 0.6)',
                borderColor: 'rgba(75, 192, 192, 1)',
                borderWidth: 1
            }]
        },
        options: {
            maintainAspectRatio: false, responsive: true,
            indexAxis: 'y', // Horizontal bars are easier to read for names
            scales: {
                x: { beginAtZero: true, title: { display: true, text: 'Adressen abgearbeitet (Anzahl)' } }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const item = top10[ctx.dataIndex];
                            return `+${item.delta} (von ${item.pastMissing} auf ${item.currentMissing} fehlende Adressen)`;
                        }
                    }
                }
            }
        }
    });
}

export function calculateGlobalDiff(historyData, mode) {
    if (!historyData || !historyData.global) return 0;

    let days = 7;
    if (mode === 'top30') days = 30;
    if (mode === 'top1') days = 1;

    const globalHist = historyData.global;
    if (globalHist.length < 2) return 0;

    const latest = globalHist[globalHist.length - 1];
    const latestDate = new Date(latest.date);

    const targetDate = new Date(latestDate);
    targetDate.setDate(latestDate.getDate() - days);
    const targetDateStr = targetDate.toISOString().split('T')[0];

    let past = globalHist.find(h => h.date >= targetDateStr);
    if (!past) past = globalHist[0];

    const currentMissing = latest.missing ?? latest.missing_count ?? 0;
    const pastMissing = past.missing ?? past.missing_count ?? 0;

    return pastMissing - currentMissing;
}

