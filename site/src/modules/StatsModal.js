
import { initHistoryChart, updateChart, initComparisonChart, renderHistoryTable } from './ui.js';

export class StatsModal {
    constructor(districtsData, historyData, onSelectDistrict) {
        this.districtsData = districtsData;
        this.historyData = historyData;
        this.onSelectDistrict = onSelectDistrict;

        this.sortCol = 'name';
        this.sortAsc = true;
        this.isVisible = false;

        this.init();
    }

    init() {
        this.renderModal();
        this.attachEvents();
        this.initCharts();
        this.renderStatsTable();
    }

    renderModal() {
        const modalHtml = `
        <div id="stats-modal" class="modal" style="display:none;">
            <div class="modal-content">
                <span class="close-button">&times;</span>
                <h2>Statistiken</h2>

                <div class="stats-section">
                    <h3>Verlauf der Abdeckung</h3>
                    <div style="margin-bottom: 10px;">
                        <label for="statsChartSelect">Anzeige für:</label>
                        <select id="statsChartSelect">
                            <option value="global">Niedersachsen (gesamt)</option>
                            <!-- Options populated by JS -->
                        </select>
                    </div>
                    <div class="chart-container">
                        <canvas id="historyChart"></canvas>
                    </div>

                    <div style="max-height: 200px; overflow-y: auto; margin-top: 10px;">
                        <table id="historyTable" style="width: 100%; font-size: 0.9em;">
                            <thead>
                                <tr>
                                    <th>Datum</th>
                                    <th>Gesamt</th>
                                    <th>Fehlend</th>
                                    <th>%</th>
                                </tr>
                            </thead>
                            <tbody></tbody>
                        </table>
                    </div>
                </div>

                <div id="comparisonChartSection" class="stats-section">
                    <h3>Vergleich aller Landkreise</h3>
                    <div class="chart-container" style="height: 400px;">
                        <canvas id="comparisonChart"></canvas>
                    </div>
                </div>

                <div class="stats-section">
                    <h3>Details pro Landkreis / Gemeinde</h3>
                    <table id="statsTable">
                        <thead>
                            <tr>
                                <th data-sort="name" style="cursor: pointer;">Name ↕</th>
                                <th data-sort="total" style="cursor: pointer;">Alle Adressen ↕</th>
                                <th data-sort="missing" style="cursor: pointer;">Fehlend ↕</th>
                                <th data-sort="coverage" style="cursor: pointer;">Abdeckung (%) ↕</th>
                            </tr>
                        </thead>
                        <tbody>
                            <!-- Rows will be populated by JS -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>`;

        // Append to body or container
        document.body.insertAdjacentHTML('beforeend', modalHtml);

        this.modalElement = document.getElementById('stats-modal');
        this.statsSelect = document.getElementById('statsChartSelect');
    }

    attachEvents() {
        // Close button
        const closeBtn = this.modalElement.querySelector('.close-button');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.toggle(false));
        }

        // Click outside to close
        window.addEventListener('click', (event) => {
            if (event.target === this.modalElement) {
                this.toggle(false);
            }
        });

        // Stats Chart Select
        if (this.districtsData) {
            this.districtsData.forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.name;
                opt.textContent = d.name;
                this.statsSelect.appendChild(opt);
            });
        }

        this.statsSelect.addEventListener('change', (e) => {
            const dataset = updateChart(e.target.value, this.historyData);
            renderHistoryTable(dataset, '#historyTable tbody');
        });

        // Table headers for sorting
        const headers = this.modalElement.querySelectorAll('#statsTable th[data-sort]');
        headers.forEach(th => {
            th.addEventListener('click', () => {
                const col = th.getAttribute('data-sort');
                this.sortStats(col);
            });
        });
    }

    initCharts() {
        if (this.historyData) {
            const historyCtx = document.getElementById('historyChart').getContext('2d');
            initHistoryChart(historyCtx, this.historyData);

            const compCtx = document.getElementById('comparisonChart').getContext('2d');
            initComparisonChart(compCtx, this.historyData);

            if (this.historyData.global) {
                renderHistoryTable(this.historyData.global, '#historyTable tbody');
            }
        }
    }

    renderStatsTable() {
        const tbody = document.querySelector('#statsTable tbody');
        if (!tbody) return;
        tbody.innerHTML = '';

        const sortedData = [...this.districtsData].sort((a, b) => {
            let valA = a[this.sortCol];
            let valB = b[this.sortCol];

            if (typeof valA === 'string') valA = valA.toLowerCase();
            if (typeof valB === 'string') valB = valB.toLowerCase();

            if (valA < valB) return this.sortAsc ? -1 : 1;
            if (valA > valB) return this.sortAsc ? 1 : -1;
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
                if (this.onSelectDistrict) {
                    this.onSelectDistrict(d.name);
                }
                this.toggle(false);
            };
            tr.style.cursor = 'pointer';
            tbody.appendChild(tr);
        });
    }

    sortStats(col) {
        if (this.sortCol === col) {
            this.sortAsc = !this.sortAsc;
        } else {
            this.sortCol = col;
            this.sortAsc = true;
        }
        this.renderStatsTable();
    }

    toggle(show) {
        if (typeof show === 'boolean') {
            this.isVisible = show;
        } else {
            this.isVisible = !this.isVisible;
        }
        this.modalElement.style.display = this.isVisible ? 'block' : 'none';
    }
}
