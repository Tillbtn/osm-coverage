const terminalOutput = document.getElementById('terminal-output');
const refreshBtn = document.getElementById('refresh-btn');
const statusIndicator = document.getElementById('connection-status');
const statusText = document.getElementById('connection-text');

let isFetching = false;
let logPresent = false;   // drives the adaptive poll interval below

async function fetchLogs() {
    if (isFetching) return;
    isFetching = true;

    try {
        // Cache bust using timestamp
        const timestamp = new Date().getTime();
        const response = await fetch(`/update.log?t=${timestamp}`);

        if (response.ok) {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('text/html')) {
                // Dev server returns index.html for a missing file.
                logPresent = false;
                terminalOutput.textContent = 'Kein Protokoll vorhanden (lokaler Dev-Server).';
                statusIndicator.classList.add('offline');
                statusText.textContent = 'Kein Protokoll';
                return;
            }

            const text = await response.text();

            // Only update if text has changed
            if (terminalOutput.textContent !== text) {
                const wasScrolledToBottom = terminalOutput.scrollHeight - terminalOutput.clientHeight <= terminalOutput.scrollTop + 10;

                terminalOutput.textContent = text || 'Protokoll leer.';

                if (wasScrolledToBottom) {
                    terminalOutput.scrollTop = terminalOutput.scrollHeight;
                }
            }

            logPresent = true;
            statusIndicator.classList.remove('offline');
            statusText.textContent = 'Verbunden';
        } else if (response.status === 404) {
            // Expected outside the server (no update.log locally).
            logPresent = false;
            terminalOutput.textContent = 'Kein Protokoll vorhanden (lokaler Dev-Server).';
            statusIndicator.classList.add('offline');
            statusText.textContent = 'Kein Protokoll';
        } else {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
    } catch (error) {
        logPresent = false;
        console.error('Fetch error:', error);
        statusIndicator.classList.add('offline');
        statusText.textContent = 'Fehler bei der Verbindung zum Server';
    } finally {
        isFetching = false;
    }
}

// --- ALKIS / OSM freshness dashboard --------------------------------------
const alkisTbody = document.getElementById('alkis-tbody');
const alkisGenerated = document.getElementById('alkis-generated');

const DASH = '<span class="muted-dash">–</span>';

// A date-only value ('2026-06-19' or '2026-06') -> 'dd.mm.yyyy' / 'mm/yyyy'.
function fmtDate(d) {
    if (!d) return DASH;
    const s = String(d).slice(0, 10);
    const m = s.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?$/);
    if (!m) return `<span class="date">${s}</span>`;
    const out = m[3] ? `${m[3]}.${m[2]}.${m[1]}` : `${m[2]}/${m[1]}`;
    return `<span class="date">${out}</span>`;
}

// A full timestamp -> 'dd.mm.yyyy' with the time on a second line.
function fmtDateTime(ts) {
    if (!ts) return DASH;
    const dt = new Date(ts);
    if (isNaN(dt)) return fmtDate(ts);
    const date = dt.toLocaleDateString('de-DE');
    const time = dt.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    return `<span class="date">${date}</span><span class="cell-sub">${time} Uhr</span>`;
}

function statusBadge(s) {
    if (s.update_available === true) return '<span class="badge update">Update verfügbar</span>';
    if (s.update_available === false) return '<span class="badge current">Aktuell</span>';
    // update_available null: no reliable comparison possible
    if (!s.automated) return '<span class="badge manual">Manuell</span>';
    return '<span class="badge unknown">Unbekannt</span>';
}

async function fetchAlkisStatus() {
    try {
        const res = await fetch(`/alkis_status.json?t=${new Date().getTime()}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const remoteCell = (o) => {
            let html = fmtDate(o.remote_date);
            if (o.remote_date && o.remote_source) {
                html += `<span class="cell-sub">Quelle: ${o.remote_source}</span>`;
            }
            return html;
        };

        // "Verarbeitet": the ALKIS stand we hold, plus when it was processed.
        const processedCell = (o) => {
            let html = fmtDate(o.processed_date);
            if (o.processed_date && o.processed_at) {
                const at = new Date(o.processed_at);
                if (!isNaN(at)) html += `<span class="cell-sub">verarb. ${at.toLocaleDateString('de-DE')}</span>`;
            }
            return html;
        };

        const rows = Object.entries(data.states)
            .sort((a, b) => a[1].name.localeCompare(b[1].name, 'de'))
            .flatMap(([, s]) => {
                const link = s.source_url
                    ? `<a href="${s.source_url}" target="_blank" rel="noopener">${s.name}</a>`
                    : s.name;
                const note = s.note ? `<span class="cell-note">${s.note}</span>` : '';
                const out = [`<tr>
                    <td class="state">${link}${note}</td>
                    <td>${remoteCell(s)}</td>
                    <td>${processedCell(s)}</td>
                    <td>${fmtDate(s.osm_date)}</td>
                    <td>${fmtDateTime(s.compared_at)}</td>
                    <td>${statusBadge(s)}</td>
                </tr>`];
                // Sub-sources (e.g. NRW → Städteregion Aachen, daily WFS).
                for (const sub of s.sub_sources || []) {
                    const cadence = sub.cadence
                        ? `<span class="cadence">${sub.cadence === 'daily' ? 'täglich' : sub.cadence}</span>` : '';
                    out.push(`<tr class="sub-row">
                        <td class="state"><span class="sub-arrow">↳</span> ${sub.label}${cadence}</td>
                        <td>${remoteCell(sub)}</td>
                        <td>${processedCell(sub)}</td>
                        <td>${DASH}</td>
                        <td>${DASH}</td>
                        <td>${statusBadge(sub)}</td>
                    </tr>`);
                }
                return out;
            }).join('');

        alkisTbody.innerHTML = rows;
        if (data.generated_at) {
            alkisGenerated.textContent =
                `Letzte Prüfung: ${new Date(data.generated_at).toLocaleString('de-DE')}`;
        }
    } catch (err) {
        alkisGenerated.textContent = 'Datenstand nicht verfügbar (alkis_status.json fehlt).';
    }
}

// Initial fetch
fetchAlkisStatus();
fetchLogs().then(() => {
    terminalOutput.scrollTop = terminalOutput.scrollHeight;
});

const interval = setInterval(fetchLogs, 86400);

// Manual refresh
refreshBtn.addEventListener('click', () => {
    fetchLogs().then(() => {
        terminalOutput.scrollTop = terminalOutput.scrollHeight;
    });
});
