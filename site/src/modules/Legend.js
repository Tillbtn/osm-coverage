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

        // Legend items format: [key, color, label, isSubItem]
        const legendItems = [
            ['missing', '#ff4444', 'Existiert im ALKIS, fehlt in OSM', false],
            ['wrong_street_all', 'none', 'Abweichender Straßenname', false],
            ['wrong_street', '#ea580c', '↳ Anderer Straßenname', true],
            ['wrong_street_abbreviation', '#f97316', '↳ Abkürzung / Zusatz', true],
            ['wrong_street_typo', '#fb923c', '↳ Typo', true],
            ['corrected_osm', '#3b82f6', 'ALKIS korrigiert, in OSM gefunden', false],
            ['corrected_not_osm', '#8b5cf6', 'ALKIS korrigiert, fehlt in OSM', false],
            ['ignored', '#9ca3af', 'ALKIS ignoriert', false],
            ['done', '#22c55e', 'Lokal als erledigt markiert', false]
        ];

        let contentHTML = '';
        legendItems.forEach(item => {
            const isGroup = item[0] === 'wrong_street_all';
            let isChecked = true;
            if (isGroup) {
                isChecked = initialVisibilityState['wrong_street'] !== false &&
                    initialVisibilityState['wrong_street_abbreviation'] !== false &&
                    initialVisibilityState['wrong_street_typo'] !== false;
            } else {
                isChecked = initialVisibilityState[item[0]] !== false;
            }

            const checkedStr = isChecked ? 'checked' : '';
            const indentStyle = item[3] ? 'margin-left: 20px; font-size: 0.95em;' : (isGroup ? 'font-weight: 500;' : '');
            const circleHtml = isGroup ? '' : `<span style="display:inline-block;width:12px;height:12px;background:${item[1]};border-radius:50%;margin-right:6px; border:1px solid rgba(255,255,255,0.5);"></span>`;

            contentHTML += `
                <label style="display:flex; align-items:center; cursor:pointer; ${indentStyle}">
                    <input type="checkbox" class="legend-filter" data-key="${item[0]}" ${checkedStr} style="margin-right:8px; cursor:pointer;" />
                    ${circleHtml}
                    ${item[2]}
                </label>
            `;
        });
        content.innerHTML = contentHTML;

        // Filter Logic
        const checkboxes = content.querySelectorAll('.legend-filter');
        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const key = e.target.dataset.key;
                const isChecked = e.target.checked;

                if (key !== 'wrong_street_all') {
                    onChange(key, isChecked);
                }

                if (key === 'wrong_street_all') {
                    // Toggle children
                    checkboxes.forEach(cb => {
                        if (['wrong_street', 'wrong_street_abbreviation', 'wrong_street_typo'].includes(cb.dataset.key)) {
                            if (cb.checked !== isChecked) {
                                cb.checked = isChecked;
                                onChange(cb.dataset.key, isChecked);
                            }
                        }
                    });
                } else if (['wrong_street', 'wrong_street_abbreviation', 'wrong_street_typo'].includes(key)) {
                    // Update parent state if all children are unchecked/checked
                    const parentCb = Array.from(checkboxes).find(cb => cb.dataset.key === 'wrong_street_all');
                    const wsCb = Array.from(checkboxes).find(cb => cb.dataset.key === 'wrong_street');
                    const abbrCb = Array.from(checkboxes).find(cb => cb.dataset.key === 'wrong_street_abbreviation');
                    const typoCb = Array.from(checkboxes).find(cb => cb.dataset.key === 'wrong_street_typo');

                    if (wsCb.checked && abbrCb.checked && typoCb.checked && !parentCb.checked) {
                        parentCb.checked = true;
                    } else if (!wsCb.checked && !abbrCb.checked && !typoCb.checked && parentCb.checked) {
                        parentCb.checked = false;
                    }
                }
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
