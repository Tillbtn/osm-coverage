export async function fetchDistricts() {
    const ts = new Date().getTime();
    try {
        const response = await fetch(`/districts.json?t=${ts}`); // Absolute path since it's in public
        if (!response.ok) throw new Error("Failed to load districts.json");
        return await response.json();
    } catch (err) {
        console.error(err);
        return [];
    }
}

export async function fetchHistory() {
    const ts = new Date().getTime();
    try {
        const response = await fetch(`/detailed_history.json?t=${ts}`);
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
