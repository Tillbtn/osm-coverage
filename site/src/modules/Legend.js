import L from 'leaflet';

export function createLegend(map, initialVisibilityState, onChange) {
    const legend = L.control({ position: 'bottomleft' });

    legend.onAdd = function (map) {
        const container = L.DomUtil.create('div', 'info legend');
        container.style.background = '#3b82f6';
        container.style.color = 'white';
        container.style.padding = '8px 12px';
        container.style.borderRadius = '5px';
        container.style.boxShadow = '0 0 15px rgba(0,0,0,0.2)';

        // Stop click propagation to map
        L.DomEvent.disableClickPropagation(container);

        // Title / Button
        const title = L.DomUtil.create('div', '', container);
        title.innerHTML = '<span style="font-size: 0.8em">▼</span>';
        title.style.fontSize = '14px';
        title.style.userSelect = 'none';
        title.style.cursor = 'pointer';

        // Content (Hidden by default)
        const content = L.DomUtil.create('div', '', container);
        content.style.display = 'none';
        content.style.marginTop = '10px';
        content.style.fontSize = '13px';
        content.style.lineHeight = '1.8';

        // Legend items format: [key, color, label]
        const legendItems = [
            ['missing', '#ff4444', 'Existiert im ALKIS, fehlt in OSM'],
            ['wrong_street', '#ff7214', 'Abweichender Straßenname'],
            ['corrected_osm', '#3b82f6', 'ALKIS korrigiert, in OSM gefunden'],
            ['corrected_not_osm', '#8b5cf6', 'ALKIS korrigiert, fehlt in OSM'],
            ['ignored', '#9ca3af', 'ALKIS ignoriert'],
            ['done', '#22c55e', 'Lokal als erledigt markiert']
        ];

        let contentHTML = '';
        legendItems.forEach(item => {
            const checkedStr = initialVisibilityState[item[0]] ? 'checked' : '';
            contentHTML += `
                <label style="display:flex; align-items:center; cursor:pointer;">
                    <input type="checkbox" class="legend-filter" data-key="${item[0]}" ${checkedStr} style="margin-right:8px; cursor:pointer;" />
                    <span style="display:inline-block;width:12px;height:12px;background:${item[1]};border-radius:50%;margin-right:6px; border:1px solid rgba(255,255,255,0.5);"></span>
                    ${item[2]}
                </label>
            `;
        });
        content.innerHTML = contentHTML;

        // Filter Logic
        content.querySelectorAll('.legend-filter').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const key = e.target.dataset.key;
                const isChecked = e.target.checked;
                onChange(key, isChecked);
            });
        });

        // Toggle Logic
        let expanded = false;
        title.onclick = function () {
            expanded = !expanded;
            if (expanded) {
                content.style.display = 'block';
                title.innerHTML = '<strong>Filter / Legende</strong> <span style="font-size: 0.8em">▲</span>';
                container.style.background = 'white';
                container.style.color = '#333';
            } else {
                content.style.display = 'none';
                title.innerHTML = '<span style="font-size: 0.8em">▼</span>';
                container.style.background = '#3b82f6';
                container.style.color = 'white';
            }
        };

        return container;
    };

    legend.addTo(map);
    return legend;
}
