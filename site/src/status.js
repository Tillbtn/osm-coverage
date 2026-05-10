const terminalOutput = document.getElementById('terminal-output');
const refreshBtn = document.getElementById('refresh-btn');
const statusIndicator = document.getElementById('connection-status');
const statusText = document.getElementById('connection-text');

let isFetching = false;

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
                terminalOutput.textContent = 'Logdatei noch nicht vorhanden';
                statusIndicator.classList.add('offline');
                statusText.textContent = 'Logdatei fehlt (lokaler Dev-Server)';
                return;
            }

            const text = await response.text();

            // Only update if text has changed
            if (terminalOutput.textContent !== text) {
                const wasScrolledToBottom = terminalOutput.scrollHeight - terminalOutput.clientHeight <= terminalOutput.scrollTop + 10;

                terminalOutput.textContent = text || 'Logdatei leer.';

                if (wasScrolledToBottom) {
                    terminalOutput.scrollTop = terminalOutput.scrollHeight;
                }
            }

            statusIndicator.classList.remove('offline');
            statusText.textContent = 'Verbunden';
        } else if (response.status === 404) {
            terminalOutput.textContent = 'Logdatei noch nicht vorhanden';
            statusIndicator.classList.add('offline');
            statusText.textContent = 'Fehler 404: update.log nicht gefunden';
        } else {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
    } catch (error) {
        console.error('Fetch error:', error);
        statusIndicator.classList.add('offline');
        statusText.textContent = 'Fehler bei der Verbindung zum Server';
    } finally {
        isFetching = false;
    }
}

// Initial fetch
fetchLogs().then(() => {
    terminalOutput.scrollTop = terminalOutput.scrollHeight;
});

// Auto-refresh every 5 seconds
const interval = setInterval(fetchLogs, 5000);

// Manual refresh
refreshBtn.addEventListener('click', () => {
    fetchLogs().then(() => {
        terminalOutput.scrollTop = terminalOutput.scrollHeight;
    });
});
