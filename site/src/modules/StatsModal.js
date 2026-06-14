
import { initHistoryChart, updateChart, updateComparisonChart, renderHistoryTable, calculateGlobalDiff } from './ui.js';

export class StatsModal {
    constructor(districtsData, historyData, onSelectDistrict, stateName = "Niedersachsen") {
        this.districtsData = districtsData;
        this.historyData = historyData;
        this.onSelectDistrict = onSelectDistrict;
        this.stateName = stateName;

        this.sortCol = 'name';
        this.sortAsc = true;
        this.isVisible = false;
        this.activeDistrict = null;

        // State-wide ALKIS export date, provided by the pipeline (history JSON).
        // Used for the state ("global") view and as a fallback for districts
        // without their own timestamp. Null when the state has no bulk date.
        this.stateAlkisDate = (historyData && historyData.alkis_date) || null;

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
                    <div style="margin-bottom: 10px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                        <label for="statsChartSelect">Anzeige für:</label>
                        <select id="statsChartSelect" style="padding: 5px; border-radius: 4px; border: 1px solid #ccc;">
                            <option value="global">${this.stateName} (gesamt)</option>
                            <!-- Options populated by JS -->
                        </select>
                        <button id="resetToGlobalBtn" style="padding: 5px 10px; background: white; color: black; border: 1px solid #3b82f6; border-radius: 4px; cursor: pointer; font-size: 0.9em; min-width: 150px;"></button>
                    </div>
                    <div class="chart-container">
                        <canvas id="historyChart"></canvas>
                    </div>
                    <div id="alkisStand" class="alkis-stand" title="Stand der ALKIS-Daten" style="display:none;"></div>

                    <div style="max-height: 200px; overflow-y: auto; overflow-x: auto; margin-top: 10px;">
                        <table id="historyTable" style="width: 100%; font-size: 0.9em; min-width: 300px;">
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
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <h3>Top 10<span id="globalDiffDisplay" style="font-size: 0.8em; color: #666; margin-left: 10px;"></span></h3>
                        
                        <select id="compChartMode" style="padding: 5px;">
                            <option value="top1">1 Tag</option>
                            <option value="top7" selected>7 Tage</option>
                            <option value="top30">30 Tage</option>
                            <!-- <option value="lines">Linien</option> -->
                        </select>
                    </div>
                    <div class="chart-container" style="position: relative; height: 300px; width: 100%;">
                        <canvas id="comparisonChart"></canvas>
                    </div>
                </div>

                <div id="statsTableSection" class="stats-section">
                    <h3>Details pro Landkreis / Gemeinde</h3>
                    <div style="max-height: 300px; overflow-y: auto; overflow-x: auto;">
                        <table id="statsTable" style="width: 100%; min-width: 400px;">
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
            </div>
        </div>`;

        // Append to body or container
        document.body.insertAdjacentHTML('beforeend', modalHtml);

        this.modalElement = document.getElementById('stats-modal');
        this.statsSelect = document.getElementById('statsChartSelect');
        this.compModeSelect = document.getElementById('compChartMode');
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
        if (this.historyData && this.historyData.states) {
            const stateGroup = document.createElement('optgroup');
            stateGroup.label = "Bundesländer";
            Object.keys(this.historyData.states).forEach(stateName => {
                const opt = document.createElement('option');
                opt.value = stateName;
                opt.textContent = stateName;
                stateGroup.appendChild(opt);
            });
            this.statsSelect.appendChild(stateGroup);
        }

        if (this.districtsData) {
            const districtGroup = document.createElement('optgroup');
            districtGroup.label = "Landkreise / Gemeinden";
            this.districtsData.forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.name;
                opt.textContent = d.name.replace(/_/g, ' ');
                districtGroup.appendChild(opt);
            });
            this.statsSelect.appendChild(districtGroup);
        }

        this.statsSelect.addEventListener('change', (e) => {
            const dataset = updateChart(e.target.value, this.historyData);
            renderHistoryTable(dataset, '#historyTable tbody');
            this.updateAlkisStand(e.target.value);

            // Toggle Comparison Section visibility based on Global selection
            const isGlobal = (e.target.value === "global");
            const compSection = document.getElementById('comparisonChartSection');
            if (compSection) compSection.style.display = isGlobal ? 'block' : 'none';

            const tableSection = document.getElementById('statsTableSection');
            if (tableSection) tableSection.style.display = isGlobal ? 'block' : 'none';

            this.updateToggleButton();
        });

        // Reset to Global Button
        const toggleBtn = document.getElementById('resetToGlobalBtn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                if (this.statsSelect.value === 'global') {
                    if (this.activeDistrict) {
                        this.statsSelect.value = this.activeDistrict;
                    }
                } else {
                    this.statsSelect.value = 'global';
                }
                this.statsSelect.dispatchEvent(new Event('change'));
            });
        }

        // Comparison Chart Mode Select
        if (this.compModeSelect) {
            this.compModeSelect.addEventListener('change', (e) => {
                const ctx = document.getElementById('comparisonChart').getContext('2d');
                updateComparisonChart(ctx, this.historyData, e.target.value);

                const gDiff = calculateGlobalDiff(this.historyData, e.target.value);
                const gSpan = document.getElementById('globalDiffDisplay');
                if (gSpan) {
                    const sign = gDiff >= 0 ? '+' : '';
                    gSpan.textContent = `(gesamt: ${sign}${gDiff} Adressen)`;
                }
            });
        }

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
            // Default to 'top7'
            updateComparisonChart(compCtx, this.historyData, 'top7');

            const gDiff = calculateGlobalDiff(this.historyData, 'top7');
            const gSpan = document.getElementById('globalDiffDisplay');
            if (gSpan) {
                const sign = gDiff >= 0 ? '+' : '';
                gSpan.textContent = `(gesamt: ${sign}${gDiff} Adressen)`;
            }

            if (this.historyData.global) {
                renderHistoryTable(this.historyData.global, '#historyTable tbody');
            }
        }

        this.updateAlkisStand(this.statsSelect.value);
    }

    // Formats an ALKIS date ("YYYY-MM-DD" or "YYYY-MM") as German "DD.MM.YYYY"
    // / "MM.YYYY".
    formatAlkisDate(alkisDate) {
        const parts = String(alkisDate).split('-');
        if (parts.length === 3) return `${parts[2]}.${parts[1]}.${parts[0]}`;
        if (parts.length === 2) return `${parts[1]}.${parts[0]}`;
        return alkisDate;
    }

    // Updates the ALKIS-Stand line below the history chart for the selected
    // entry. Uses the district's own date, falling back to the state-level
    // newest date; hides the line entirely when no date is available.
    updateAlkisStand(value) {
        const el = document.getElementById('alkisStand');
        if (!el) return;

        let date = null;
        if (value === 'global') {
            date = this.stateAlkisDate;
        } else if (this.districtsData) {
            const d = this.districtsData.find(x => x.name === value);
            // Districts of this state fall back to the state date; other
            // Bundesländer (no district data here) show nothing.
            if (d) date = d.alkis_date || this.stateAlkisDate;
        }

        if (date) {
            el.textContent = `ALKIS-Stand: ${this.formatAlkisDate(date)}`;
            el.style.display = '';
        } else {
            el.textContent = '';
            el.style.display = 'none';
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
                <td>${d.name.replace(/_/g, ' ')}</td>
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

    toggle(show, selectedDistrict) {
        if (typeof show === 'boolean') {
            this.isVisible = show;
        } else {
            this.isVisible = !this.isVisible;
        }

        if (this.isVisible) {
            if (selectedDistrict) {
                if (selectedDistrict !== "Global") {
                    this.activeDistrict = selectedDistrict;
                }
                const val = selectedDistrict === "Global" ? "global" : selectedDistrict;
                if (this.statsSelect.value !== val) {
                    this.statsSelect.value = val;
                    // Trigger change logic
                    const dataset = updateChart(val, this.historyData);
                    renderHistoryTable(dataset, '#historyTable tbody');

                    const isGlobal = (val === "global");
                    const compSection = document.getElementById('comparisonChartSection');
                    if (compSection) compSection.style.display = isGlobal ? 'block' : 'none';

                    const tableSection = document.getElementById('statsTableSection');
                    if (tableSection) tableSection.style.display = isGlobal ? 'block' : 'none';
                }
            }
            this.updateAlkisStand(this.statsSelect.value);
            this.updateToggleButton();
        }

        this.modalElement.style.display = this.isVisible ? 'block' : 'none';
    }

    updateToggleButton() {
        const toggleBtn = document.getElementById('resetToGlobalBtn');
        if (!toggleBtn) return;

        if (this.statsSelect.value === 'global') {
            if (this.activeDistrict) {
                toggleBtn.textContent = `${this.activeDistrict.replace(/_/g, ' ')} anzeigen`;
                toggleBtn.style.display = 'inline-block';
            } else {
                toggleBtn.style.display = 'none';
            }
        } else {
            toggleBtn.textContent = `${this.stateName} anzeigen`;
            toggleBtn.style.display = 'inline-block';
        }
    }
}
