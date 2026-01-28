/**
 * Census School Data Explorer - Flask Frontend
 */

// Global state
let map = null;
let currentLocation = null;
let isochroneLayers = [];
let schoolMarkers = [];
let mainMarker = null;

// Overture layers state
let overtureLayers = {
    // buildings: null,
    places: null
};
let overtureLayersEnabled = {
    // buildings: false,
    places: true  // Auto-enabled
};
// Cache for pre-fetched Overture GeoJSON data
let overtureDataCache = {
    // buildings: null,
    places: null
};
// Bounding box of the largest isochrone (for Overture queries)
let isochroneBbox = null;
// Store isochrone GeoJSON features for clipping Overture data
let isochroneGeoJSON = null;

// Category filters for places (toggled by UI checkboxes)
// All major Overture top-level categories
let enabledCategories = {
    eat_and_drink: false,
    retail: false,
    health_and_medical: false,
    professional_services: false,
    beauty_and_spa: false,
    active_life: false,
    arts_and_entertainment: false,
    attractions_and_activities: false,
    accommodation: false,
    automotive: false,
    financial_service: false,
    public_service_and_government: false,
    religious_organization: false,
    travel: false,
    pets: false,
    real_estate: false,
    home_service: false
};

// Isochrone colors by drive time
const ISOCHRONE_STYLES = {
    5: { color: 'blue', fillColor: 'blue', fillOpacity: 0.10, weight: 2, opacity: 0.8 },
    10: { color: 'green', fillColor: 'green', fillOpacity: 0.08, weight: 2, opacity: 0.7 },
    15: { color: 'purple', fillColor: 'purple', fillOpacity: 0.06, weight: 2, opacity: 0.6 }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    initMap();
    initEventListeners();
});

/**
 * Initialize the Leaflet map
 */
function initMap() {
    map = L.map('map', {
        center: [25.7617, -80.1918], // Miami default
        zoom: 11,
        scrollWheelZoom: true
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);
}

/**
 * Set up event listeners
 */
function initEventListeners() {
    // Mode toggle
    document.querySelectorAll('input[name="mode"]').forEach(radio => {
        radio.addEventListener('change', handleModeChange);
    });

    // Search button
    document.getElementById('search-btn').addEventListener('click', handleSearch);

    // Enter key in search box
    document.getElementById('geocoder').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            handleSearch();
        }
    });

    // School select dropdown
    document.getElementById('school-select').addEventListener('change', handleSchoolSelect);

    // Metric toggle
    document.querySelectorAll('input[name="metric"]').forEach(radio => {
        radio.addEventListener('change', handleMetricChange);
    });

    // Export buttons
    const be = document.getElementById('export-econ');
    if (be) be.addEventListener('click', () => exportData('income'));
    const bp = document.getElementById('export-pop');
    if (bp) bp.addEventListener('click', () => exportData('population'));
    const bpub = document.getElementById('export-pub');
    if (bpub) bpub.addEventListener('click', () => exportData('publicschool'));
    const bschList = document.getElementById('export-schools-list');
    if (bschList) bschList.addEventListener('click', () => exportData('schools'));
    const bschSummary = document.getElementById('export-schools-summary');
    if (bschSummary) bschSummary.addEventListener('click', () => exportData('schools_summary'));

    // Overture category toggles
    document.querySelectorAll('input[data-category]').forEach(checkbox => {
        checkbox.addEventListener('change', handleOvertureCategoryToggle);
    });

    // Draggable vertical resizer between sidebar and map
    const resizer = document.getElementById('drag-resizer');
    const sidebar = document.querySelector('.sidebar');
    const mapContainer = document.querySelector('.map-container');
    if (resizer && sidebar && mapContainer) {
        let dragging = false;
        let startX = 0;
        let startWidth = 0;

        resizer.addEventListener('mousedown', (e) => {
            dragging = true;
            startX = e.clientX;
            startWidth = sidebar.getBoundingClientRect().width;
            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'col-resize';
        });

        window.addEventListener('mousemove', (e) => {
            if (!dragging) return;
            const dx = e.clientX - startX;
            let newWidth = startWidth + dx;
            const min = 300; const max = window.innerWidth - 300;
            if (newWidth < min) newWidth = min;
            if (newWidth > max) newWidth = max;
            sidebar.style.width = newWidth + 'px';
            // allow map to flex naturally
        });

        window.addEventListener('mouseup', () => {
            if (!dragging) return;
            dragging = false;
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        });

        // double-click resizer to toggle full sidebar
        resizer.addEventListener('dblclick', () => {
            toggleSidebarExpanded();
        });
    }

    // Expand/collapse schools full view button
    const toggleBtn = document.getElementById('toggle-schools-full');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            toggleSidebarExpanded();
        });
    }
}

function toggleSidebarExpanded() {
    const sidebar = document.querySelector('.sidebar');
    const resizer = document.getElementById('drag-resizer');
    const mapContainer = document.querySelector('.map-container');
    const btn = document.getElementById('toggle-schools-full');
    if (!sidebar) return;

    const expanding = !sidebar.classList.contains('expanded');
    if (expanding) {
        sidebar.classList.add('expanded');
        if (resizer) resizer.style.display = 'none';
        if (mapContainer) mapContainer.style.display = 'none';
        // remove max height to show whole table
        const grid = document.getElementById('schools-grid-container');
        if (grid) { grid.style.maxHeight = 'none'; grid.style.overflow = 'visible'; }
        if (btn) btn.textContent = 'Collapse';
    } else {
        sidebar.classList.remove('expanded');
        if (resizer) resizer.style.display = '';
        if (mapContainer) mapContainer.style.display = '';
        const grid = document.getElementById('schools-grid-container');
        if (grid) { grid.style.maxHeight = ''; grid.style.overflow = ''; }
        if (btn) btn.textContent = 'Expand';
        // trigger map invalidate size after a small delay so tiles reposition
        if (typeof map !== 'undefined' && map) setTimeout(() => map.invalidateSize(), 250);
    }
}

/**
 * Handle mode toggle between Search and Choose
 */
function handleModeChange(e) {
    const mode = e.target.value;
    document.getElementById('search-panel').style.display = mode === 'search' ? 'block' : 'none';
    document.getElementById('choose-panel').style.display = mode === 'choose' ? 'block' : 'none';

    // If switching to choose and there's a selected school, search it
    if (mode === 'choose') {
        const select = document.getElementById('school-select');
        if (select.value) {
            searchAddress(select.value);
        }
    }
}

/**
 * Handle search button click
 */
function handleSearch() {
    const address = document.getElementById('geocoder').value.trim();
    if (address) {
        searchAddress(address);
    }
}

/**
 * Handle school dropdown selection
 */
function handleSchoolSelect(e) {
    const address = e.target.value;
    if (address) {
        searchAddress(address);
    }
}

/**
 * Handle metric panel toggle
 */
function handleMetricChange(e) {
    const metric = e.target.value;

    // Hide all panels
    document.querySelectorAll('.data-panel').forEach(panel => {
        panel.style.display = 'none';
    });

    // Show selected panel
    const panelMap = {
        'econ': 'econ-panel',
        'pop': 'pop-panel',
        'pub': 'pub-panel',
        'school': 'school-panel'
    };
    document.getElementById(panelMap[metric]).style.display = 'block';

    // If we have a location, reload data for the selected metric
    if (currentLocation) {
        loadDataForMetric(metric);
    }
}

/**
 * Geocode address and update map
 */
async function searchAddress(address) {
    showLoading(true);

    try {
        const response = await fetch('/api/geocode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address })
        });

        const data = await response.json();

        if (data.error) {
            alert(`Geocoding error: ${data.error}`);
            showLoading(false);
            return;
        }

        currentLocation = { lat: data.lat, lon: data.lon, place: data.place };

        // Update map view
        map.setView([data.lat, data.lon], 12);

        // Load isochrones and all data
        await loadIsochrones();
        await loadAllData();

    } catch (error) {
        console.error('Search error:', error);
        alert('Error searching address. Please try again.');
    } finally {
        showLoading(false);
    }
}

/**
 * Load isochrones and update map
 */
async function loadIsochrones() {
    if (!currentLocation) return;

    // Clear existing layers
    clearIsochrones();
    clearSchoolMarkers();
    clearMainMarker();

    try {
        const response = await fetch('/api/isochrones', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lon: currentLocation.lon, lat: currentLocation.lat })
        });

        const data = await response.json();

        if (data.error) {
            console.error('Isochrone error:', data.error);
            return;
        }

        // Add isochrone polygons (sorted by time descending so smaller rings appear on top)
        const features = data.features.sort((a, b) => b.properties.Time - a.properties.Time);

        // Calculate bounding box from largest isochrone (first after sort = 15-min)
        isochroneBbox = calculateIsochroneBbox(features);
        // Store isochrone features for clipping Overture data
        isochroneGeoJSON = features;
        console.log('Isochrone bbox:', isochroneBbox);

        features.forEach(feature => {
            const time = feature.properties.Time;
            const style = ISOCHRONE_STYLES[time] || ISOCHRONE_STYLES[15];

            const layer = L.geoJSON(feature, {
                style: () => style
            }).addTo(map);

            isochroneLayers.push(layer);
        });

        // Add main location marker
        addMainMarker();

        // Load school markers
        await loadSchoolMarkers();

        // Reload any enabled Overture layers for new location
        await reloadOvertureLayers();

    } catch (error) {
        console.error('Isochrone loading error:', error);
    }
}

/**
 * Add the main location marker with popup
 */
function addMainMarker() {
    if (!currentLocation) return;

    const blueIcon = L.icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
    });

    mainMarker = L.marker([currentLocation.lat, currentLocation.lon], { icon: blueIcon })
        .bindPopup(`<b>${currentLocation.place || 'Selected Location'}</b>`)
        .addTo(map);
}

/**
 * Load school markers for map
 */
async function loadSchoolMarkers() {
    if (!currentLocation) return;

    try {
        const response = await fetch('/api/schools_map', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lon: currentLocation.lon, lat: currentLocation.lat })
        });

        const data = await response.json();

        if (data.error || !data.schools) return;

        data.schools.forEach(school => {
            const marker = L.circleMarker([school.lat, school.lon], {
                radius: 5,
                fillColor: '#d00',
                color: '#d00',
                weight: 1,
                opacity: 1,
                fillOpacity: 1
            })
            .bindPopup(school.name)
            .addTo(map);

            schoolMarkers.push(marker);
        });

    } catch (error) {
        console.error('School markers error:', error);
    }
}

/**
 * Load all data for current location
 */
async function loadAllData() {
    if (!currentLocation) return;

    // Load all data in parallel
    await Promise.all([
        loadIncomeData(),
        loadPopulationData(),
        loadPublicSchoolData(),
        loadSchoolsData()
    ]);
}

/**
 * Load data for specific metric only
 */
async function loadDataForMetric(metric) {
    switch (metric) {
        case 'econ':
            await loadIncomeData();
            break;
        case 'pop':
            await loadPopulationData();
            break;
        case 'pub':
            await loadPublicSchoolData();
            break;
        case 'school':
            await loadSchoolsData();
            break;
    }
}

/**
 * Load income/economic data
 */
async function loadIncomeData() {
    if (!currentLocation) return;

    try {
        const response = await fetch('/api/income', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lon: currentLocation.lon, lat: currentLocation.lat })
        });

        const data = await response.json();

        if (data.error) {
            console.error('Income data error:', data.error);
            return;
        }

        updateEconTable(data.rows);

    } catch (error) {
        console.error('Income loading error:', error);
    }
}

/**
 * Update the economic profile table
 */
function updateEconTable(rows) {
    const tbody = document.querySelector('#econ-table tbody');

    // Create lookup by zone
    const byZone = {};
    rows.forEach(row => { byZone[row.zone] = row; });

    tbody.innerHTML = `
        <tr>
            <td>Med. Income</td>
            <td>${byZone['5-min']?.med_income || '-'}</td>
            <td>${byZone['10-min']?.med_income || '-'}</td>
            <td>${byZone['15-min']?.med_income || '-'}</td>
        </tr>
        <tr>
            <td>&lt;$50k</td>
            <td>${byZone['5-min']?.under50k || '-'}</td>
            <td>${byZone['10-min']?.under50k || '-'}</td>
            <td>${byZone['15-min']?.under50k || '-'}</td>
        </tr>
        <tr>
            <td>$50–$75k</td>
            <td>${byZone['5-min']?.['50_75k'] || '-'}</td>
            <td>${byZone['10-min']?.['50_75k'] || '-'}</td>
            <td>${byZone['15-min']?.['50_75k'] || '-'}</td>
        </tr>
        <tr>
            <td>Cash Assist.</td>
            <td>${byZone['5-min']?.cash_assist || '-'}</td>
            <td>${byZone['10-min']?.cash_assist || '-'}</td>
            <td>${byZone['15-min']?.cash_assist || '-'}</td>
        </tr>
    `;
}

/**
 * Load population data
 */
async function loadPopulationData() {
    if (!currentLocation) return;

    try {
        const response = await fetch('/api/population', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lon: currentLocation.lon, lat: currentLocation.lat })
        });

        const data = await response.json();

        if (data.error) {
            console.error('Population data error:', data.error);
            return;
        }

        updatePopTable(data.rows);

    } catch (error) {
        console.error('Population loading error:', error);
    }
}

/**
 * Update the population table
 */
function updatePopTable(rows) {
    const tbody = document.querySelector('#pop-table tbody');

    const byZone = {};
    rows.forEach(row => { byZone[row.zone] = row; });

    tbody.innerHTML = `
        <tr>
            <td>Total Pop</td>
            <td>${byZone['5-min']?.total_pop || '-'}</td>
            <td>${byZone['10-min']?.total_pop || '-'}</td>
            <td>${byZone['15-min']?.total_pop || '-'}</td>
        </tr>
        <tr>
            <td>KG</td>
            <td>${byZone['5-min']?.pop_k || '-'}</td>
            <td>${byZone['10-min']?.pop_k || '-'}</td>
            <td>${byZone['15-min']?.pop_k || '-'}</td>
        </tr>
        <tr>
            <td>1–4</td>
            <td>${byZone['5-min']?.pop_1_4 || '-'}</td>
            <td>${byZone['10-min']?.pop_1_4 || '-'}</td>
            <td>${byZone['15-min']?.pop_1_4 || '-'}</td>
        </tr>
        <tr>
            <td>5–8</td>
            <td>${byZone['5-min']?.pop_5_8 || '-'}</td>
            <td>${byZone['10-min']?.pop_5_8 || '-'}</td>
            <td>${byZone['15-min']?.pop_5_8 || '-'}</td>
        </tr>
        <tr>
            <td>9–12</td>
            <td>${byZone['5-min']?.pop_9_12 || '-'}</td>
            <td>${byZone['10-min']?.pop_9_12 || '-'}</td>
            <td>${byZone['15-min']?.pop_9_12 || '-'}</td>
        </tr>
        <tr>
            <td>Non-white</td>
            <td>${byZone['5-min']?.pct_nonwhite || '-'}</td>
            <td>${byZone['10-min']?.pct_nonwhite || '-'}</td>
            <td>${byZone['15-min']?.pct_nonwhite || '-'}</td>
        </tr>
        <tr>
            <td>BA+</td>
            <td>${byZone['5-min']?.pct_ba_plus || '-'}</td>
            <td>${byZone['10-min']?.pct_ba_plus || '-'}</td>
            <td>${byZone['15-min']?.pct_ba_plus || '-'}</td>
        </tr>
    `;
}

/**
 * Load public school enrollment data
 */
async function loadPublicSchoolData() {
    if (!currentLocation) return;

    try {
        const response = await fetch('/api/publicschool', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lon: currentLocation.lon, lat: currentLocation.lat })
        });

        const data = await response.json();

        if (data.error) {
            console.error('Public school data error:', data.error);
            return;
        }

        updatePubTable(data.rows);

    } catch (error) {
        console.error('Public school loading error:', error);
    }
}

/**
 * Update the public school table
 */
function updatePubTable(rows) {
    const tbody = document.querySelector('#pub-table tbody');

    const byZone = {};
    rows.forEach(row => { byZone[row.zone] = row; });

    tbody.innerHTML = `
        <tr>
            <td>KG</td>
            <td>${byZone['5-min']?.pct_k || '-'}</td>
            <td>${byZone['10-min']?.pct_k || '-'}</td>
            <td>${byZone['15-min']?.pct_k || '-'}</td>
        </tr>
        <tr>
            <td>1–4</td>
            <td>${byZone['5-min']?.pct_1_4 || '-'}</td>
            <td>${byZone['10-min']?.pct_1_4 || '-'}</td>
            <td>${byZone['15-min']?.pct_1_4 || '-'}</td>
        </tr>
        <tr>
            <td>5–8</td>
            <td>${byZone['5-min']?.pct_5_8 || '-'}</td>
            <td>${byZone['10-min']?.pct_5_8 || '-'}</td>
            <td>${byZone['15-min']?.pct_5_8 || '-'}</td>
        </tr>
        <tr>
            <td>9–12</td>
            <td>${byZone['5-min']?.pct_9_12 || '-'}</td>
            <td>${byZone['10-min']?.pct_9_12 || '-'}</td>
            <td>${byZone['15-min']?.pct_9_12 || '-'}</td>
        </tr>
    `;
}

/**
 * Load schools data
 */
async function loadSchoolsData() {
    if (!currentLocation) return;

    try {
        const response = await fetch('/api/schools', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lon: currentLocation.lon, lat: currentLocation.lat })
        });

        const data = await response.json();

        if (data.error) {
            console.error('Schools data error:', data.error);
            return;
        }

        updateSchoolSummary(data.summary);
        updateSchoolsTable(data.schools);

    } catch (error) {
        console.error('Schools loading error:', error);
    }
}

/**
 * Update school summary table
 */
function updateSchoolSummary(summary) {
    const tbody = document.querySelector('#school-summary-table tbody');

    if (!summary || summary.length === 0) {
        tbody.innerHTML = `
            <tr><td>5-min</td><td>-</td><td>-</td><td>-</td></tr>
            <tr><td>10-min</td><td>-</td><td>-</td><td>-</td></tr>
            <tr><td>15-min</td><td>-</td><td>-</td><td>-</td></tr>
        `;
        return;
    }

    tbody.innerHTML = summary.map(row => `
        <tr>
            <td>${row.drive_time}</td>
            <td>${row.enrollment}</td>
            <td>${row.capacity}</td>
            <td>${row.cap_enroll}</td>
        </tr>
    `).join('');
}

/**
 * Update schools list table
 */
function updateSchoolsTable(schools) {
    const container = document.getElementById('schools-grid-container');
    const table = document.getElementById('schools-table');
    const tbody = table.querySelector('tbody');
    const thead = table.querySelector('thead');

    const count5 = document.getElementById('schools-count-5');
    const count10 = document.getElementById('schools-count-10');
    const count15 = document.getElementById('schools-count-15');

    if (!schools || schools.length === 0) {
        if (count5) count5.querySelector('.badge').textContent = '0';
        if (count10) count10.querySelector('.badge').textContent = '0';
        if (count15) count15.querySelector('.badge').textContent = '0';
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No schools found in drive-time zones</td></tr>';
        return;
    }

    // Count schools by drive time (robust parsing)
    let c5 = 0, c10 = 0, c15 = 0;
    schools.forEach(s => {
        let dt = s['Drive Time'] ?? s['DriveTime'] ?? s['DriveTimeMin'] ?? s['Drive Time (min)'];
        if (dt === null || dt === undefined) return;
        if (typeof dt === 'string') {
            // handle values like '5', '5-min', '5-min', '5.0', or '5-min'
            const m = dt.match(/(\d{1,2})/);
            dt = m ? Number(m[1]) : NaN;
        } else {
            dt = Number(dt);
        }
        if (!isFinite(dt)) return;
        if (dt === 5) c5 += 1;
        else if (dt === 10) c10 += 1;
        else if (dt === 15) c15 += 1;
    });

    if (count5) count5.querySelector('.badge').textContent = String(c5);
    if (count10) count10.querySelector('.badge').textContent = String(c10);
    if (count15) count15.querySelector('.badge').textContent = String(c15);

    // Determine columns to display from the first record, exclude lat/lon and geometry
    const first = schools[0];
    const excludeRegex = /lat|lon|geometry/i;

    // Preferred ordering if present
    const preferred = ['Drive Time', 'DriveTime', 'DriveTimeMin', 'District', 'District Name', 'School', 'School Name', '# of Students', 'Student #', 'Grade', 'Capacity', '% Eco. Disadv.', '% ESE', '% ESOL', '% Abs. 10-21', '% Abs. 21+'];

    const keys = [];
    // add preferred keys in order if present
    preferred.forEach(k => { if (k in first && !excludeRegex.test(k)) keys.push(k); });
    // then add any remaining keys from the object
    Object.keys(first).forEach(k => { if (!keys.includes(k) && !excludeRegex.test(k) && k !== 'geometry') keys.push(k); });

    // build header
    thead.innerHTML = '<tr>' + keys.map(k => `<th>${k}</th>`).join('') + '</tr>';

    // build rows
    tbody.innerHTML = schools.map(school => {
        return '<tr>' + keys.map(k => `<td>${(school[k] !== undefined && school[k] !== null) ? school[k] : '-'}</td>`).join('') + '</tr>';
    }).join('');
}

/**
 * Show/hide loading indicator
 */
function showLoading(show) {
    document.getElementById('loading-indicator').style.display = show ? 'block' : 'none';
}

/**
 * Clear isochrone layers from map
 */
function clearIsochrones() {
    isochroneLayers.forEach(layer => map.removeLayer(layer));
    isochroneLayers = [];
}

/**
 * Clear school markers from map
 */
function clearSchoolMarkers() {
    schoolMarkers.forEach(marker => map.removeLayer(marker));
    schoolMarkers = [];
}

/**
 * Clear main marker from map
 */
function clearMainMarker() {
    if (mainMarker) {
        map.removeLayer(mainMarker);
        mainMarker = null;
    }
}


/**
 * Export data for a given type by calling the server export endpoint and
 * triggering a browser download of the returned XLSX.
 */
async function exportData(type) {
    if (!currentLocation) {
        alert('Please select a location first');
        return;
    }

    try {
        // Derive a short street-name hint from the place string (first segment)
        let nameHint = currentLocation.place || '';
        let part = String(nameHint).split(',')[0].trim();
        part = part.replace(/^[\d#\s]+/, '');
        part = part.replace(/\s+/g, '_').replace(/[^A-Za-z0-9_-]/g, '');

        const resp = await fetch(`/api/export/${type}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lon: currentLocation.lon, lat: currentLocation.lat, name: part })
        });

        if (!resp.ok) {
            let j = null;
            try { j = await resp.json(); } catch (e) {}
            alert('Export failed: ' + (j?.error || resp.statusText));
            return;
        }

        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        // Suggest filename based on type if header not present
        const header = resp.headers.get('content-disposition');
        let filename = (type || 'export') + '.xlsx';
        if (header) {
            const m = /filename\*=UTF-8''([^;]+)|filename="?([^;\"]+)"?/.exec(header);
            if (m) filename = decodeURIComponent(m[1] || m[2]);
        }
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (err) {
        console.error('Export error:', err);
        alert('Error exporting data. See console for details.');
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// OVERTURE MAPS LAYER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Handle Overture category toggle checkbox change
 */
function handleOvertureCategoryToggle(e) {
    const category = e.target.dataset.category;
    const enabled = e.target.checked;
    enabledCategories[category] = enabled;

    // Re-render places layer with updated category filter
    if (currentLocation && overtureDataCache.places) {
        renderFilteredPlaces();
    }
}

/**
 * Render places layer filtered by enabled categories
 */
function renderFilteredPlaces() {
    // Remove existing places layer
    if (overtureLayers.places) {
        map.removeLayer(overtureLayers.places);
        overtureLayers.places = null;
    }

    const geojson = overtureDataCache.places;
    if (!geojson || !geojson.features || geojson.features.length === 0) {
        console.log('No cached places data');
        return;
    }

    // Get list of enabled categories
    const activeCategories = Object.entries(enabledCategories)
        .filter(([_, enabled]) => enabled)
        .map(([cat, _]) => cat);

    if (activeCategories.length === 0) {
        console.log('No categories enabled');
        return;
    }

    // Filter features by enabled categories
    // Overture uses hierarchical categories like "restaurant" under "eat_and_drink"
    // We match if any top-level category in the hierarchy is enabled
    const filteredFeatures = geojson.features.filter(feature => {
        const props = feature.properties || {};
        const categories = props.categories;
        if (!categories) return false;

        // Collect all category strings from primary and alternate
        const featureCats = [];
        if (categories.primary) {
            const p = Array.isArray(categories.primary) ? categories.primary : [categories.primary];
            featureCats.push(...p);
        }
        if (categories.alternate) {
            const a = Array.isArray(categories.alternate) ? categories.alternate : [categories.alternate];
            featureCats.push(...a);
        }

        // Check if any feature category matches or is a subcategory of an enabled category
        // Overture categories are hierarchical: e.g., "restaurant" falls under "eat_and_drink"
        // We check both exact match and if the category starts with enabled category + "_"
        return featureCats.some(cat => {
            // Exact match
            if (activeCategories.includes(cat)) return true;
            // Check if this is a subcategory (e.g., "restaurant" matches "eat_and_drink")
            // Note: Overture's taxonomy has top-level categories that contain others
            // We need to check if the feature's category belongs to any enabled top-level
            return activeCategories.some(enabledCat => {
                // Direct match
                if (cat === enabledCat) return true;
                // Check common top-level mappings (Overture taxonomy)
                const subcategoryMappings = {
                    eat_and_drink: ['restaurant', 'bar', 'cafe', 'coffee_shop', 'bakery', 'ice_cream', 'fast_food', 'food_court'],
                    retail: ['shopping', 'grocery_store', 'supermarket', 'convenience_store', 'clothing_store', 'department_store', 'pharmacy', 'food'],
                    health_and_medical: ['hospital', 'doctor', 'dentist', 'clinic', 'pharmacy', 'veterinarian', 'urgent_care'],
                    professional_services: ['lawyer', 'accountant', 'real_estate_agent', 'insurance', 'bank'],
                    beauty_and_spa: ['hair_salon', 'barber', 'nail_salon', 'spa', 'massage'],
                    active_life: ['gym', 'fitness', 'sports', 'yoga', 'swimming_pool', 'golf'],
                    arts_and_entertainment: ['cinema', 'theater', 'museum', 'casino', 'nightclub', 'arcade'],
                    attractions_and_activities: ['park', 'beach', 'zoo', 'aquarium', 'amusement_park', 'tourist_attraction'],
                    accommodation: ['hotel', 'motel', 'hostel', 'resort', 'bed_and_breakfast', 'campground'],
                    automotive: ['gas_station', 'car_dealer', 'car_wash', 'auto_repair', 'parking'],
                    financial_service: ['bank', 'atm', 'credit_union', 'insurance'],
                    public_service_and_government: ['post_office', 'library', 'police', 'fire_station', 'government_office'],
                    religious_organization: ['church', 'mosque', 'synagogue', 'temple', 'buddhist_temple'],
                    travel: ['airport', 'train_station', 'bus_station', 'ferry_terminal', 'car_rental'],
                    pets: ['pet_store', 'veterinarian', 'pet_grooming', 'animal_shelter'],
                    real_estate: ['real_estate_agent', 'apartment_complex', 'property_management'],
                    home_service: ['plumber', 'electrician', 'contractor', 'landscaping', 'cleaning_service'],
                    education: ['school', 'university', 'college', 'preschool', 'tutoring', 'child_care']
                };
                // Check if cat contains the enabled category name or is in its known subcategories
                if (cat.includes(enabledCat)) return true;
                if (subcategoryMappings[enabledCat] && subcategoryMappings[enabledCat].some(sub => cat.includes(sub))) return true;
                return false;
            });
        });
    });

    if (filteredFeatures.length === 0) {
        console.log('No places match enabled categories');
        return;
    }

    const filteredGeojson = {
        type: 'FeatureCollection',
        features: filteredFeatures
    };

    const style = getOvertureLayerStyle('places');
    const layer = L.geoJSON(filteredGeojson, {
        style: (feature) => style.polygon,
        pointToLayer: (feature, latlng) => {
            return L.circleMarker(latlng, style.point);
        },
        onEachFeature: (feature, layer) => {
            const props = feature.properties || {};
            const name = extractOvertureName(props);
            const popup = buildOverturePopup('places', props, name);
            if (popup) layer.bindPopup(popup);
        }
    });

    overtureLayers.places = layer;
    layer.addTo(map);
    console.log(`Rendered ${filteredFeatures.length} places for categories: ${activeCategories.join(', ')}`);
}

// Keep old function for compatibility (commented out layer toggle)
/*
function handleOvertureLayerToggle(e) {
    const layerName = e.target.dataset.layer;
    const enabled = e.target.checked;
    overtureLayersEnabled[layerName] = enabled;

    if (enabled && currentLocation) {
        if (overtureDataCache[layerName]) {
            showOvertureLayerFromCache(layerName);
        } else {
            loadOvertureLayer(layerName);
        }
    } else if (!enabled && overtureLayers[layerName]) {
        map.removeLayer(overtureLayers[layerName]);
        overtureLayers[layerName] = null;
    }
}
*/

/**
 * Load an Overture layer for the current location
 */
async function loadOvertureLayer(layerName) {
    if (!currentLocation) return;

    // Remove existing layer if any
    if (overtureLayers[layerName]) {
        map.removeLayer(overtureLayers[layerName]);
        overtureLayers[layerName] = null;
    }

    try {
        const requestBody = isochroneBbox ? {
            bbox: [isochroneBbox.xmin, isochroneBbox.ymin, isochroneBbox.xmax, isochroneBbox.ymax],
            lon: currentLocation.lon,
            lat: currentLocation.lat,
            isochrones: isochroneGeoJSON ? { type: 'FeatureCollection', features: isochroneGeoJSON } : null
        } : {
            lon: currentLocation.lon,
            lat: currentLocation.lat,
            radius_km: 3.0
        };

        const response = await fetch(`/api/overture/${layerName}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });

        const geojson = await response.json();

        if (geojson.error) {
            console.error(`Overture ${layerName} error:`, geojson.error);
            return;
        }

        const style = getOvertureLayerStyle(layerName);
        const layer = L.geoJSON(geojson, {
            style: (feature) => {
                // Use line style for LineString/MultiLineString, polygon style otherwise
                const geomType = feature.geometry?.type;
                if (geomType === 'LineString' || geomType === 'MultiLineString') {
                    return style.line || style.polygon;
                }
                return style.polygon;
            },
            pointToLayer: (feature, latlng) => {
                return L.circleMarker(latlng, style.point);
            },
            onEachFeature: (feature, layer) => {
                const props = feature.properties || {};
                const name = extractOvertureName(props);
                const popup = buildOverturePopup(layerName, props, name);
                if (popup) layer.bindPopup(popup);
            }
        });

        overtureLayers[layerName] = layer;
        layer.addTo(map);

    } catch (error) {
        console.error(`Error loading Overture ${layerName}:`, error);
    }
}

/**
 * Get style configuration for an Overture layer
 */
function getOvertureLayerStyle(layerName) {
    // Colors chosen to avoid isochrone colors (blue, green, purple)
    // Very translucent so isochrones remain prominent
    const styles = {
        // buildings removed — not used
        // buildings: {
        //     // Very light tan for buildings
        //     polygon: { color: '#d2691e', weight: 0.5, fillOpacity: 0.1, fillColor: '#deb887' },
        //     point: { radius: 2, fillColor: '#d2691e', color: '#d2691e', weight: 0.5, fillOpacity: 0.15 }
        // },
        places: {
            // Yellow for places (POIs) - small dots
            polygon: { color: '#ffd700', weight: 0.5, fillOpacity: 0.15, fillColor: '#ffeb3b' },
            point: { radius: 3, fillColor: '#ffd700', color: '#b8860b', weight: 1, fillOpacity: 0.6 }
        },
        // roads removed — not used
    };
    return styles[layerName] || styles.buildings;
}

/**
 * Extract name from Overture feature properties
 */
function extractOvertureName(props) {
    if (!props.names) return null;
    // Overture names can be { primary: "...", common: {...}, ... }
    if (typeof props.names === 'string') return props.names;
    if (props.names.primary) return props.names.primary;
    if (props.names.common) {
        const common = props.names.common;
        if (typeof common === 'string') return common;
        // Could be keyed by language
        const keys = Object.keys(common);
        if (keys.length > 0) return common[keys[0]];
    }
    return null;
}

/**
 * Format Overture categories for display
 */
function formatOvertureCategories(categories) {
    if (!categories) return null;

    // Already a string
    if (typeof categories === 'string') return categories;

    // Array of strings
    if (Array.isArray(categories)) {
        return categories.filter(Boolean).join(', ');
    }

    // Object structure (e.g., { primary: [...], alternate: [...] })
    if (typeof categories === 'object') {
        const primary = categories.primary;
        const alternate = categories.alternate;
        const parts = [];
        if (primary) {
            const p = Array.isArray(primary) ? primary : [primary];
            const pText = p.filter(Boolean).join(', ');
            if (pText) parts.push(pText);
        }
        if (alternate) {
            const a = Array.isArray(alternate) ? alternate : [alternate];
            const aText = a.filter(Boolean).join(', ');
            if (aText) parts.push(aText);
        }
        return parts.length ? parts.join(' | ') : null;
    }

    return null;
}

/**
 * Build popup content for an Overture feature
 */
function buildOverturePopup(layerName, props, name) {
    let html = '<div class="overture-popup">';

    if (name) {
        html += `<strong>${name}</strong><br>`;
    }

    switch (layerName) {
        // buildings removed — not used
        // case 'buildings':
        //     if (props.height) html += `Height: ${props.height}m<br>`;
        //     if (props.num_floors) html += `Floors: ${props.num_floors}<br>`;
        //     if (props.class) html += `Class: ${props.class}<br>`;
        //     break;
        case 'places':
            if (props.addresses && props.addresses.length > 0) {
                const addr = props.addresses[0];
                if (addr.freeform) html += `Address: ${addr.freeform}<br>`;
            }
            const categories = formatOvertureCategories(props.categories);
            if (categories) html += `Categories: ${categories}<br>`;
            if (props.websites && props.websites.length > 0) {
                html += `<a href="${props.websites[0]}" target="_blank">Website</a><br>`;
            }
            break;
        case 'roads':
            if (props.class) html += `Road class: ${props.class}<br>`;
            if (props.surface) html += `Surface: ${props.surface}<br>`;
            break;
        case 'infrastructure':
            if (props.class) html += `Type: ${props.class}<br>`;
            if (props.subtype) html += `Subtype: ${props.subtype}<br>`;
            break;
    }

    html += `<small class="text-muted">Source: Overture Maps</small>`;
    html += '</div>';

    return html;
}

/**
 * Reload all enabled Overture layers (called after location change)
 */
async function reloadOvertureLayers() {
    // Pre-fetch ALL Overture layers in parallel for instant toggling
    await prefetchAllOvertureLayers();

    // Auto-render places with category filtering (places is always enabled now)
    renderFilteredPlaces();
}

/**
 * Pre-fetch all Overture layers for the current location (runs in parallel)
 */
async function prefetchAllOvertureLayers() {
    if (!currentLocation) return;

    // Clear cache
    for (const key of Object.keys(overtureDataCache)) {
        overtureDataCache[key] = null;
    }

    // Use isochrone bbox if available, otherwise fall back to radius
    let requestBody;
    if (isochroneBbox) {
        requestBody = {
            bbox: [isochroneBbox.xmin, isochroneBbox.ymin, isochroneBbox.xmax, isochroneBbox.ymax],
            lon: currentLocation.lon,
            lat: currentLocation.lat,
            isochrones: isochroneGeoJSON ? { type: 'FeatureCollection', features: isochroneGeoJSON } : null
        };
        console.log('Using isochrone bbox for Overture query:', isochroneBbox);
    } else {
        requestBody = {
            lon: currentLocation.lon,
            lat: currentLocation.lat,
            radius_km: 5.0  // Fallback radius
        };
    }

    const layerNames = [
        // 'buildings',
        'places'
    ];
    const totalLayers = layerNames.length;
    let completedLayers = 0;

    // Show progress bar
    showOvertureProgress(true);
    updateOvertureProgress(0, totalLayers, 'Loading Overture data...');

    // Fetch all layers in parallel, but track completion
    const fetchPromises = layerNames.map(async (layerName) => {
        try {
            const response = await fetch(`/api/overture/${layerName}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody)
            });

            const geojson = await response.json();

            if (!geojson.error) {
                overtureDataCache[layerName] = geojson;
                console.log(`Prefetched ${layerName}: ${geojson.features?.length || 0} features`);
            } else {
                console.warn(`Overture ${layerName} error:`, geojson.error);
            }
        } catch (error) {
            console.error(`Error prefetching Overture ${layerName}:`, error);
        } finally {
            // Update progress regardless of success/failure
            completedLayers++;
            updateOvertureProgress(completedLayers, totalLayers, `Loaded ${layerName}`);
        }
    });

    await Promise.all(fetchPromises);
    console.log('All Overture layers prefetched');

    // Hide progress bar after a short delay
    setTimeout(() => showOvertureProgress(false), 500);
}

/**
 * Show/hide the Overture loading progress bar
 */
function showOvertureProgress(show) {
    const progressEl = document.getElementById('overture-progress');
    if (progressEl) {
        progressEl.style.display = show ? 'block' : 'none';
    }
}

/**
 * Update the Overture loading progress bar
 */
function updateOvertureProgress(completed, total, text) {
    const progressBar = document.getElementById('overture-progress-bar');
    const progressText = document.getElementById('overture-progress-text');
    const progressCount = document.getElementById('overture-progress-count');

    if (progressBar) {
        const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
        progressBar.style.width = `${pct}%`;
        progressBar.setAttribute('aria-valuenow', pct);

        // Change color when complete
        if (completed >= total) {
            progressBar.classList.remove('progress-bar-animated', 'bg-info');
            progressBar.classList.add('bg-success');
        } else {
            progressBar.classList.add('progress-bar-animated', 'bg-info');
            progressBar.classList.remove('bg-success');
        }
    }
    if (progressText) {
        progressText.textContent = text || 'Loading Overture data...';
    }
    if (progressCount) {
        progressCount.textContent = `${completed}/${total}`;
    }
}

/**
 * Show an Overture layer from cache (instant, no fetch)
 */
function showOvertureLayerFromCache(layerName) {
    // Remove existing layer if any
    if (overtureLayers[layerName]) {
        map.removeLayer(overtureLayers[layerName]);
        overtureLayers[layerName] = null;
    }

    const geojson = overtureDataCache[layerName];
    if (!geojson || !geojson.features || geojson.features.length === 0) {
        console.log(`No cached data for ${layerName}`);
        return;
    }

    const style = getOvertureLayerStyle(layerName);
    const layer = L.geoJSON(geojson, {
        style: (feature) => {
            // Use line style for LineString/MultiLineString, polygon style otherwise
            const geomType = feature.geometry?.type;
            if (geomType === 'LineString' || geomType === 'MultiLineString') {
                return style.line || style.polygon;
            }
            return style.polygon;
        },
        pointToLayer: (feature, latlng) => {
            return L.circleMarker(latlng, style.point);
        },
        onEachFeature: (feature, layer) => {
            const props = feature.properties || {};
            const name = extractOvertureName(props);
            const popup = buildOverturePopup(layerName, props, name);
            if (popup) layer.bindPopup(popup);
        }
    });

    overtureLayers[layerName] = layer;
    layer.addTo(map);
}

/**
 * Calculate bounding box from isochrone GeoJSON features
 * Returns { xmin, ymin, xmax, ymax } or null
 */
function calculateIsochroneBbox(features) {
    if (!features || features.length === 0) return null;

    let xmin = Infinity, ymin = Infinity, xmax = -Infinity, ymax = -Infinity;

    // Process all features to get combined bbox (covers all isochrones)
    features.forEach(feature => {
        const coords = extractAllCoordinates(feature.geometry);
        coords.forEach(([lon, lat]) => {
            if (lon < xmin) xmin = lon;
            if (lon > xmax) xmax = lon;
            if (lat < ymin) ymin = lat;
            if (lat > ymax) ymax = lat;
        });
    });

    if (xmin === Infinity) return null;

    // Add small buffer (~100m) to ensure we get features at the edges
    const buffer = 0.001; // ~111m at equator
    return {
        xmin: xmin - buffer,
        ymin: ymin - buffer,
        xmax: xmax + buffer,
        ymax: ymax + buffer
    };
}

/**
 * Extract all coordinates from a GeoJSON geometry (handles Polygon, MultiPolygon, etc.)
 */
function extractAllCoordinates(geometry) {
    if (!geometry) return [];

    const coords = [];

    function processCoords(arr, depth = 0) {
        if (!Array.isArray(arr)) return;

        // If it's a coordinate pair [lon, lat]
        if (arr.length >= 2 && typeof arr[0] === 'number' && typeof arr[1] === 'number') {
            coords.push([arr[0], arr[1]]);
            return;
        }

        // Otherwise recurse
        arr.forEach(item => processCoords(item, depth + 1));
    }

    if (geometry.coordinates) {
        processCoords(geometry.coordinates);
    }

    return coords;
}

/**
 * Clear all Overture layers from the map
 */
function clearOvertureLayers() {
    for (const layerName of Object.keys(overtureLayers)) {
        if (overtureLayers[layerName]) {
            map.removeLayer(overtureLayers[layerName]);
            overtureLayers[layerName] = null;
        }
    }
}
