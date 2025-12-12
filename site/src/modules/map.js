import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

export function createMap(elementId, center = [52.9, 9.8], zoom = 8) {
    const map = L.map(elementId).setView(center, zoom);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    return map;
}

export function createJOSMLink(lat, lng) {
    const delta = 0.001;
    const url = `http://127.0.0.1:8111/load_and_zoom?left=${lng - delta}&right=${lng + delta}&top=${lat + delta}&bottom=${lat - delta}`;

    const container = document.createElement('div');
    const link = document.createElement('a');
    link.href = "#";
    link.textContent = "in JOSM öffnen";
    link.onclick = (e) => {
        e.preventDefault();
        fetch(url).catch(err => {
            console.error(err);
            alert("JOSM nicht erreichbar");
        });
    };
    container.appendChild(link);
    return container;
}
