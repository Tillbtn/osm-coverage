export async function fetchDistricts(url = '/districts.json') {
    const ts = new Date().getTime();
    try {
        const response = await fetch(`${url}?t=${ts}`);
        if (!response.ok) throw new Error(`Failed to load ${url}`);
        return await response.json();
    } catch (err) {
        console.error(err);
        return [];
    }
}

export async function fetchHistory(url = '/detailed_history.json') {
    const ts = new Date().getTime();
    try {
        const response = await fetch(`${url}?t=${ts}`);
        if (!response.ok) return null;
        return await response.json();
    } catch (err) {
        console.warn("History not available", err);
        return null;
    }
}

export async function fetchGeoJSON(path) {
    try {
        const response = await fetch(path);
        if (!response.ok) throw new Error(`Failed to load ${path}`);
        return await response.json();
    } catch (err) {
        throw err;
    }
}
