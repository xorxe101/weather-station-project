// dashboard.js
// Global variables
let charts = {};
let autoRefresh = true;
let currentTimeRange = 24; // hours
let refreshInterval;
let readingIntervalMinutes = 1; // Default, will be updated from API
let refreshTimeout = null;  // <--- ΑΥΤΗ Η ΓΡΑΜΜΗ ΔΙΟΡΘΩΝΕΙ ΤΟ ERROR
let serverTimeOffset = 0;       // <--- Η ΝΕΑ ΜΕΤΑΒΛΗΤΗ
let intervalRefreshTimeout;
let globalHistoryData = [];
const MAX_RETENTION_HOURS = 24;

// ENABLED Chart configuration - Zoom and selection tools are now enabled
const commonChartConfig = {
    height: 350,
    animations: {
    enabled: true,
    easing: 'easein',
    speed: 150,  // CHANGED: from 800 to 150 (faster animation)
    animateGradually: {
        enabled: true,
        delay: 50  // CHANGED: from 150 to 50 (faster initial animation)
    },
    dynamicAnimation: {
        enabled: true,
        speed: 150  // CHANGED: from 350 to 150 (faster updates)
    }
    },
    toolbar: {
    show: true,
    tools: {
        download: true,   // ENABLED download button
        selection: true,  // ENABLED selection
        zoom: true,       // ENABLED zoom button
        zoomin: true,     // ENABLED zoom in
        zoomout: true,    // ENABLED zoom out
        pan: true,        // ENABLED pan button
        reset: true       // Keep reset functionality
    }
    },
    zoom: {
    enabled: true,      // ENABLED zoom entirely
    type: 'x',
    autoScaleYaxis: true
    },
    selection: {
    enabled: true       // ENABLED selection entirely
    }
};

const commonAxisConfig = {
    xaxis: {
    type: 'datetime',
    labels: {
        datetimeUTC: false,
        format: 'HH:mm',
        style: {
        colors: '#666',
        fontSize: '14px'
        }
    }
    },
    yaxis: {
    labels: {
        style: {
        colors: '#666',
        fontSize: '14px'
        }
    }
    },
    grid: {
    borderColor: '#f0f0f0',
    strokeDashArray: 3
    },
    tooltip: {
    x: {
        format: 'HH:mm dd MMM yyyy'
    },
    theme: 'light',
    shared: true,
    intersect: false
    },
    stroke: {
    width: 2,
    curve: 'smooth'
    },
    markers: {
    size: 0,
    hover: {
        size: 4
    }
    }
};

// --- SKELETON LOADING FUNCTION ---
function renderSkeleton() {
    // 1. Skeleton για το Current Weather (#latest)
    const latestContainer = document.getElementById('latest');
    if (latestContainer) {
        let html = '<div class="current-weather">';
        
        // Ένα μεγάλο κουτί για τον τίτλο/ώρα
        html += '<div class="time-box skeleton skeleton-title"></div>';
        
        // 9 κουτάκια για τις μετρήσεις (Temp, Humidity, κλπ)
        for(let i=0; i<9; i++) {
            html += `
                <div class="weather-box" style="border: none; box-shadow: none;">
                    <div class="skeleton skeleton-text"></div>
                    <div class="skeleton skeleton-value"></div>
                </div>
            `;
        }
        html += '</div>';
        latestContainer.innerHTML = html;
    }

    // 2. Skeleton για τα Γραφήματα
    // Βρίσκουμε όλα τα divs που περιέχουν γραφήματα
    const chartIds = ['tempChart', 'humidityChart', 'pressureChart', 'windspeedChart', 'winddirectionChart', 'rainfallrateChart', 'dewpointChart'];
    
    chartIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            // Καθαρίζουμε το παλιό γράφημα για να μπει το skeleton
            el.innerHTML = '<div class="skeleton skeleton-chart"></div>';
        }
    });
}

// Mobile-specific chart adjustments
function getMobileChartConfig() {
    if (window.innerWidth <= 768) {
    return {
        height: 400,
        toolbar: {
        show: true,
        tools: {
            download: false,
            selection: true,
            zoom: true,
            zoomin: true,
            zoomout: true,
            pan: true,
            reset: true
        }
        },
        zoom: {
        enabled: true,
        type: 'x',
        autoScaleYaxis: true
        },
        selection: {
        enabled: true
        }
    };
    }
    return commonChartConfig;
}

// Helper function to parse date without timezone conversion
function parseDate(isoString) {
    try {
        if (!isoString) return new Date();
        // Προσπάθεια για standard JS parsing πρώτα
        const d = new Date(isoString);
        if (!isNaN(d.getTime())) return d;

        // Fallback στον manual διαχωρισμό αν το ISO format είναι περίεργο
        const parts = isoString.split(/[-T: .]/);
        return new Date(
            parts[0], parts[1]-1, parts[2],
            parts[3] || 0, parts[4] || 0, parts[5] || 0
        );
    } catch (e) {
        console.error('Error parsing date:', isoString, e);
        return new Date();
    }
}

function updateCurrentTime() {
    document.getElementById('currentTime').textContent = new Date().toLocaleTimeString();
}

// 1. Detect Interval from Server
async function detectReadingInterval() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        
        // Σιγουρεύουμε ότι είναι αριθμός (π.χ. 5)
        readingIntervalMinutes = parseInt(config.reading_interval_minutes) || 1;
        
        // Ενημέρωση κειμένου
        const updateText = document.querySelector('.last-update');
        if (updateText) {
            updateText.innerHTML = `Data updates every ${readingIntervalMinutes} minute${readingIntervalMinutes > 1 ? 's' : ''} | <span id="currentTime"></span>`;
        }
        
        console.log(`✅ Reading Interval Detected: ${readingIntervalMinutes} minutes`);
        return readingIntervalMinutes;
    } catch (error) {
        console.error('❌ Error detecting interval:', error);
        readingIntervalMinutes = 1; // Default σε 1 λεπτό αν αποτύχει
        return 1;
    }
}

// --- ROBUST SMART AUTO-REFRESH ---
function startAutoRefresh() {
    // Καθαρισμός τυχόν υπάρχοντος timer
    if (refreshTimeout) clearTimeout(refreshTimeout);

    // 1. Βρίσκουμε την ώρα των ΤΕΛΕΥΤΑΙΩΝ ληφθέντων δεδομένων
    // Ψάχνουμε στο DOM γιατί είναι το πιο σίγουρο σημείο
    let lastDataTime = new Date().getTime(); // Default τώρα
    
    if (globalHistoryData && globalHistoryData.length > 0) {
        // Παίρνουμε το πιο πρόσφατο από το ιστορικό
        const times = globalHistoryData.map(d => parseDate(d.Time).getTime());
        lastDataTime = Math.max(...times);
    }

    // 2. Υπολογίζουμε πότε θα έρθει το επόμενο
    const intervalMinutes = readingIntervalMinutes || 5; // Default 5 λεπτά αν χαθεί η ρύθμιση
    const intervalMs = intervalMinutes * 60 * 1000;
    
    // Επόμενο = Τελευταία Μέτρηση + Διάστημα + 1 δευτερόλεπτο "αέρας"
    let nextTarget = lastDataTime + intervalMs + 1000;
    const now = new Date().getTime() + serverTimeOffset; // <--- Server-adjusted 'now'
    
    // 3. Υπολογισμός αναμονής
    let delay = nextTarget - now;

    // --- SAFETY CHECK (Η ΑΣΦΑΛΕΙΑ ΠΟΥ ΕΛΕΙΠΕ) ---
    // Αν η καθυστέρηση είναι αρνητική (τα δεδομένα είναι παλιά) 
    // ή υπερβολικά μεγάλη (πάνω από το διάστημα + 1 λεπτό),
    // τότε κάτι δεν πάει καλά με την ώρα του σταθμού.
    // Σε αυτή την περίπτωση, βάζουμε default αναμονή 1 λεπτό για να μην κολλήσει.
    if (delay <= 0 || delay > (intervalMs + 60000)) {
        console.log("⚠️ Data timing mismatch or old data. Fallback to 60s check.");
        delay = 60000; // 1 Λεπτό
    }

    console.log(`⏱️ Refresh Logic: Last Data ${new Date(lastDataTime).toLocaleTimeString()} | Next Check in ${(delay/1000).toFixed(0)}s`);

    // 4. Ρύθμιση Timeout
    refreshTimeout = setTimeout(() => {
        if (autoRefresh) {
            loadData(true).finally(() => {
                // Αφού τελειώσει, ξανα-καλεί τον εαυτό του για τον επόμενο γύρο
                startAutoRefresh();
            });
        }
    }, delay);
}

function stopAutoRefresh() {
    if (refreshTimeout) {
        clearTimeout(refreshTimeout);
        refreshTimeout = null;
    }
}

// 4. Toggle Button
function toggleAutoRefresh() {
    autoRefresh = !autoRefresh;
    const statusEl = document.getElementById('refreshStatus');
    if (statusEl) statusEl.textContent = autoRefresh ? 'Enabled' : 'Disabled';
    
    if (autoRefresh) startAutoRefresh();
    else stopAutoRefresh();
}

function changeTimeRange(hours) {
    currentTimeRange = hours;
    loadData();
}

function exportChartData(chartId, title) {
    const chart = charts[chartId];
    if (!chart) return;
    
    const series = chart.w.config.series;
    
    // Use proper CSV format with UTF-8 BOM to support special characters
    let csvContent = '\uFEFF'; // UTF-8 BOM for Excel compatibility
    
    // Create headers with proper units for each measurement type
    const headers = ['Timestamp', ...series.map(s => {
        const name = s.name;
        // Add proper units based on the measurement type
        if (name.includes('Humidity')) {
            return name.includes('(%)') ? name : name + ' (%)';
        } else if (name.includes('Wind Speed')) {
            return name.includes('(km/h)') ? name : name + ' (km/h)';
        } else if (name.includes('Wind Direction')) {
            return name.includes('°') ? name : name + ' (°)';
        } else if (name.includes('Pressure')) {
            return name.includes('(hPa)') ? name : name + ' (hPa)';
        } else if (name.includes('Temp') || name.includes('Dew Point')) {
            return name.includes('°C') ? name : name + ' (°C)';
        } else if (name.includes('Rain') && name.includes('Rate')) {
            return name.includes('(mm/h)') ? name : name + ' (mm/h)';
        } else if (name.includes('Rain')) {
            return name.includes('(mm)') ? name : name + ' (mm)';
        }
        return name;
    })];
    csvContent += headers.join(',') + '\r\n';
    
    // Get the longest series for timestamps
    const mainSeries = series.reduce((longest, current) => 
        current.data.length > longest.data.length ? current : longest, 
        series[0]
    );
    
    // Create rows
    mainSeries.data.forEach((point, index) => {
        const row = [];
        
        // Format timestamp
        const date = new Date(point.x);
        const timestamp = date.toLocaleString(); // Full date and time
        row.push(`"${timestamp}"`);
        
        // Add values from all series
        series.forEach(seriesItem => {
            const value = seriesItem.data[index] ? seriesItem.data[index].y : '';
            row.push(value);
        });
        
        csvContent += row.join(',') + '\r\n';
    });
    
    // Create Blob with explicit UTF-8 encoding
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    
    // Trigger download
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `${title}_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    // Clean up URL
    setTimeout(() => URL.revokeObjectURL(url), 100);
    // ΠΡΟΣΘΗΚΗ: Ενημέρωση επιτυχίας
    showToast(`Exported ${title} successfully!`, 'success');
}

function addCustomExportButtons() {
    const controls = document.querySelector('.controls');
    
    // Ασφάλεια: Αν δεν βρει το controls div, σταματάει
    if (!controls) {
        console.log('Controls element not found');
        return;
    }
    
    // Ασφάλεια: Αν το κουμπί υπάρχει ήδη, δεν το ξαναφτιάχνει
    if (document.getElementById('export-btn-new')) {
        return;
    }
    
    // 1. Δημιουργία του Κουμπιού
    const btn = document.createElement('button');
    btn.id = 'export-btn-new';
    btn.className = 'control-btn'; // Χρησιμοποιούμε το ίδιο στυλ με τα άλλα κουμπιά (Refresh, Last Hour κλπ)
    
    // Το κείμενο του κουμπιού
    btn.innerHTML = 'Export Data';

    // ΕΛΕΓΧΟΣ GUEST: Αν δεν είναι συνδεδεμένος
    if (typeof isUserLoggedIn !== 'undefined' && !isUserLoggedIn) {
        
        // 1. Εφαρμογή των INLINE STYLES ακριβώς όπως τα έστειλες
        btn.style.cssText = `
            display: flex; 
            align-items: center; 
            justify-content: center; 
            gap: 8px; 
            opacity: 0.6; 
            cursor: not-allowed; 
            filter: grayscale(100%);
        `;
        
        // 2. Τίτλος (Tooltip)
        btn.title = "🔒 Requires Account";

        // 3. Εικονίδιο & Κείμενο
        // Χρησιμοποιούμε το lock.png ή save.png (εδώ έβαλα lock.png γιατί ταιριάζει με το 'Requires Account')
        // Αν προτιμάς το εικονίδιο Save, άλλαξε το src σε '/static/img_icon/save.png'
        btn.innerHTML = `Export Data`;
        
        // Προσθέτουμε και την κλάση για τυχόν extra CSS overrides
        btn.classList.add('disabled-guest');

    } else {
        // Κανονική κατάσταση (Logged in)
        btn.innerHTML = 'Export Data';
    }
    
    // 2. Η ΛΕΙΤΟΥΡΓΙΑ: Όταν πατηθεί, ανοίγει το νέο Modal
    // (Δεν χρειάζεται να ελέγξουμε εδώ για Guest, το κάνει η openExportModal μόνη της)
    btn.onclick = openExportModal;
    
    // 3. Προσθήκη στη σελίδα
    controls.appendChild(btn);
    
    console.log('New Export button added');
}

async function loadData(isBackgroundUpdate = false) {
    try {
        // --- SILENT REFRESH FIX ---
        if (!isBackgroundUpdate) {
            document.body.classList.add('loading');
            renderSkeleton();
        }
        
        console.log('Loading data for', currentTimeRange, 'hours...');
        
        const [latestRes, historyRes] = await Promise.all([
            fetch('/api/latest'),
            fetch(`/api/history/last/${currentTimeRange}hours`)
        ]);

        if (!latestRes.ok || !historyRes.ok) throw new Error('API request failed');

        // --- Η ΜΑΓΕΙΑ ΕΔΩ: Παίρνουμε την ώρα του Server ---
        const serverDateStr = latestRes.headers.get('Date');
        if (serverDateStr) {
            const serverTime = new Date(serverDateStr).getTime();
            serverTimeOffset = serverTime - Date.now();
            console.log("⏱️ Server-Client Sync Offset:", serverTimeOffset, "ms");
        }

        const latestText = await latestRes.text();
        const historyText = await historyRes.text();
        
        const cleanLatestText = latestText.replace(/NaN/g, 'null');
        const cleanHistoryText = historyText.replace(/NaN/g, 'null');

        const latest = JSON.parse(cleanLatestText);
        const history = JSON.parse(cleanHistoryText);

        // Αποθήκευση για το Export
        globalHistoryData = history; 

        updateDisplay(latest, history);
        
        // Απλή ενημέρωση ώρας (χωρίς animation)
        const now = new Date();
        const lastUpdateEl = document.getElementById('lastUpdate');
        if (lastUpdateEl) {
            lastUpdateEl.textContent = now.toLocaleTimeString('el-GR', { hour12: false });
        }

    } catch (error) {
        console.error('Error loading data:', error);
        if (!isBackgroundUpdate) {
             const latestEl = document.getElementById('latest');
             if(latestEl) latestEl.innerHTML = `<div class="error-msg">Error: ${error.message}</div>`;
        }
    } finally {
        if (!isBackgroundUpdate) {
            document.body.classList.remove('loading');
        }
    }
}

function startClock() {
    function update() {
        // Χρήση του offset για να δείχνει την ώρα του server
        const now = new Date(Date.now() + serverTimeOffset);
        const el = document.getElementById('currentTime');
        if (el) el.textContent = now.toLocaleTimeString('el-GR', { hour12: false });
    }
    update();
    setInterval(update, 1000);
}

// Safe data access function
function getValue(obj, key) {
    if (!obj || typeof obj !== 'object') return null;
    
    // Try different key variations
    const keys = [key, key.toLowerCase(), key.replace(' ', ''), key.replace(' ', '').toLowerCase()];
    
    for (const k of keys) {
    if (obj[k] !== undefined && obj[k] !== null) {
        const value = obj[k];
        // Convert to number if possible, otherwise return as-is
        const numValue = parseFloat(value);
        return isNaN(numValue) ? null : numValue;
    }
    }
    return null;
}

function updateDisplay(latest, history) {
    console.log('Updating display with data...');

    // Αν το 'latest' είναι άδειο (συμβαίνει συχνά στις 12), πάρε την τελευταία τιμή από το history
    if ((!latest || !latest.Time) && history && history.length > 0) {
        latest = history[0]; // Το ιστορικό είναι συνήθως ταξινομημένο από το πιο πρόσφατο
        console.log("⚠️ Latest data missing at rollover, using last history point.");
    }
    
    // Update current weather display
    if (latest && latest.Time) {
    const nowText = parseDate(latest.Time).toLocaleTimeString('el-GR', { hour12: false });
    document.getElementById('latest').innerHTML = `
        <div class="current-weather">
        <div class="time-box">
            <h3>Current Weather: ${nowText}</h3>
        </div>
        ${createWeatherBox('Air Temp', getValue(latest, 'Air Temperature'), '°C')}
        ${createWeatherBox('Ground Temp', getValue(latest, 'Soil Temperature'), '°C')}
        ${createWeatherBox('Humidity', getValue(latest, 'Humidity'), '%')}
        ${createWeatherBox('Wind Speed', getValue(latest, 'WindSpeed'), ' km/h')}
        ${createWindCompassBox(getValue(latest, 'WindDirection'))}
        ${createWeatherBox('Rainfall', getValue(latest, 'RainFall'), 'mm')}
        ${createWeatherBox('Rainrate', getValue(latest, 'RainRate'), 'mm/h')}
        ${createWeatherBox('Dew Point', getValue(latest, 'DewPoint'), '°C')}
        ${createWeatherBox('Pressure', getValue(latest, 'Pressure'), 'hPa')}
        </div>
    `;
    } else {
    document.getElementById('latest').innerHTML = '<div class="current-weather"><h3>No current data available</h3></div>';
    }

    // Check if we have history data
    if (!history || !Array.isArray(history) || history.length === 0) {
    console.log('No history data available');
    // Clear all charts
    Object.keys(charts).forEach(chartId => {
        if (charts[chartId]) {
        charts[chartId].destroy();
        }
        document.getElementById(chartId).innerHTML = '<div class="no-data">No data available</div>';
    });
    return;
    }

    // Prepare chart data with NaN handling
    const tempSeries = [
    { 
        name: 'Air Temp (°C)', 
        data: history.map(row => {
        const value = getValue(row, 'Air Temperature');
        return { 
            x: parseDate(row.Time).getTime(), 
            y: value
        };
        }).filter(point => point.x && !isNaN(point.x)) // Filter out invalid points
    },
    { 
        name: 'Ground Temp (°C)', 
        data: history.map(row => {
        const value = getValue(row, 'Soil Temperature');
        return { 
            x: parseDate(row.Time).getTime(), 
            y: value
        };
        }).filter(point => point.x && !isNaN(point.x))
    }
    ];

    const rainfallSeries = [
    { 
        name: 'RainFall (mm)', 
        data: history.map(row => {
        const value = getValue(row, 'RainFall');
        return { 
            x: parseDate(row.Time).getTime(), 
            y: value
        };
        }).filter(point => point.x && !isNaN(point.x))
    },
    { 
        name: 'RainRate (mm/h)', 
        data: history.map(row => {
        const value = getValue(row, 'RainRate');
        return { 
            x: parseDate(row.Time).getTime(), 
            y: value
        };
        }).filter(point => point.x && !isNaN(point.x))
    }
    ];

    // Initialize or update charts with mobile-optimized config
    const mobileConfig = getMobileChartConfig();
    
    console.log('Creating charts...');
    
    // Create individual series for each chart with NaN handling
    createChart('tempChart', 'Temperature (°C)', tempSeries, ['#FF4560', '#00E396'], mobileConfig);
    createChart('humidityChart', 'Humidity (%)', 
    [{ 
        name: 'Humidity', 
        data: history.map(row => {
        const value = getValue(row, 'Humidity');
        return { 
            x: parseDate(row.Time).getTime(), 
            y: value
        };
        }).filter(point => point.x && !isNaN(point.x))
    }], 
    ['#775DD0'], mobileConfig);
    createChart('pressureChart', 'Pressure (hPa)', 
    [{ 
        name: 'Pressure', 
        data: history.map(row => {
        const value = getValue(row, 'Pressure');
        return { 
            x: parseDate(row.Time).getTime(), 
            y: value
        };
        }).filter(point => point.x && !isNaN(point.x))
    }], 
    ['#546E7A'], mobileConfig);
    createChart('windspeedChart', 'Wind Speed (km/h)', 
    [{ 
        name: 'Wind Speed', 
        data: history.map(row => {
        const value = getValue(row, 'WindSpeed');
        return { 
            x: parseDate(row.Time).getTime(), 
            y: value
        };
        }).filter(point => point.x && !isNaN(point.x))
    }], 
    ['#00D9E9'], mobileConfig);
    createChart('winddirectionChart', 'Wind Direction (°)', 
    [{ 
        name: 'Wind Direction', 
        data: history.map(row => {
        const value = getValue(row, 'WindDirection');
        return { 
            x: parseDate(row.Time).getTime(), 
            y: value
        };
        }).filter(point => point.x && !isNaN(point.x))
    }], 
    ['#FFB800'], mobileConfig);
    createChart('rainfallrateChart', 'Rainfall & Rain Rate', rainfallSeries, ['#008FFB', '#FEB019'], mobileConfig);
    createChart('dewpointChart', 'Dew Point (°C)', 
    [{ 
        name: 'Dew Point', 
        data: history.map(row => {
        const value = getValue(row, 'DewPoint');
        return { 
            x: parseDate(row.Time).getTime(), 
            y: value
        };
        }).filter(point => point.x && !isNaN(point.x))
    }], 
    ['#8E44AD'], mobileConfig);
    
    console.log('Charts created successfully');
}

// --- DYNAMIC COLOR LOGIC ---
function getColorClass(label, value) {
    if (value === null || value === undefined) return '';

    // Καθαρίζουμε το label για να κάνουμε εύκολα ελέγχους (π.χ. "Air Temp" -> "temp")
    const type = label.toLowerCase();

    // 1. ΘΕΡΜΟΚΡΑΣΙΑ (Temperature)
    if (type.includes('temp') || type.includes('dew point')) {
        if (value <= 5) return 'val-cold';       // Κρύο (<= 5°C)
        if (value <= 15) return 'val-cool';      // Δροσιά (6-15°C)
        if (value <= 28) return 'val-optimal';   // Ιδανικά (16-28°C)
        if (value <= 35) return 'val-caution';   // Ζέστη (29-35°C)
        return 'val-danger';                     // Καύσωνας (> 35°C)
    }

    // 2. ΥΓΡΑΣΙΑ (Humidity)
    if (type.includes('humidity')) {
        if (value < 30) return 'val-caution';    // Πολύ ξηρό (< 30%)
        if (value <= 70) return 'val-optimal';   // Φυσιολογικό (30-70%)
        return 'val-cold';                       // Υγρό (> 70% - Μπλε)
    }

    // 3. ΑΝΕΜΟΣ (Wind Speed)
    if (type.includes('wind speed')) {
        if (value <= 10) return 'val-optimal';   // Άπνοια/Λίγο
        if (value <= 40) return 'val-caution';   // Ισχυρός
        if (value <= 70) return 'val-danger';    // Θύελλα
        return 'val-extreme';                    // Τυφώνας
    }

    // 4. ΒΡΟΧΗ (Rain)
    if (type.includes('rain')) {
        if (value === 0) return '';              // Τίποτα (Default χρώμα)
        if (value <= 10) return 'val-cold';      // Βροχή (Μπλε)
        return 'val-danger';                     // Καταιγίδα (Κόκκινο)
    }

    // 5. ΠΙΕΣΗ (Pressure)
    if (type.includes('pressure')) {
        if (value < 1000) return 'val-cool';     // Χαμηλή (Συνήθως έρχεται βροχή)
        if (value > 1025) return 'val-caution';  // Πολύ Υψηλή
        return 'val-optimal';                    // Κανονική
    }

    return ''; // Default (κανένα ειδικό χρώμα)
}

// --- UPDATED: Weather Box (Air, Ground, Humidity, Wind) ---
function createWeatherBox(label, value, unit) {
    let displayValue = value;
    let displayClass = 'weather-value';
    let colorClass = ''; 

    if (value === null || value === undefined || isNaN(value)) {
        displayValue = '--';
        displayClass += ' no-data';
    } else {
        colorClass = getColorClass(label, value);
        if (colorClass) displayClass += ' ' + colorClass;
    }

    // --- 1. AIR TEMP (Θερμόμετρο) ---
    if (label === 'Air Temp') {
        const minTemp = -5; const maxTemp = 45;
        let percent = ((value - minTemp) / (maxTemp - minTemp)) * 100;
        percent = Math.max(0, Math.min(100, percent));
        return `
        <div class="weather-box">
            <div class="weather-label">${label}</div>
            <div class="thermometer-widget ${colorClass}">
                <div class="thermometer-stem"><div class="thermometer-fill" style="height: ${percent}%;"></div></div>
                <div class="thermometer-bulb"></div>
                <div class="thermometer-tick tick-high"></div><div class="thermometer-tick tick-mid"></div><div class="thermometer-tick tick-low"></div>
            </div>
            <div class="${displayClass}" style="margin-top: 5px;">${displayValue}<span class="unit">${unit}</span></div>
        </div>`;
    }

    // --- 2. GROUND TEMP (Θερμόμετρο Εδάφους) ---
    if (label === 'Ground Temp') {
        const minTemp = -5; const maxTemp = 45;
        let percent = ((value - minTemp) / (maxTemp - minTemp)) * 100;
        percent = Math.max(0, Math.min(100, percent));
        return `
        <div class="weather-box">
            <div class="weather-label">${label}</div>
            <div class="ground-widget-wrapper">
                <div class="ground-section"></div>
                <div class="thermometer-widget ${colorClass}" style="margin-bottom: -5px;">
                    <div class="thermometer-stem"><div class="thermometer-fill" style="height: ${percent}%;"></div></div>
                    <div class="thermometer-bulb"></div>
                    <div class="thermometer-tick tick-high"></div><div class="thermometer-tick tick-mid"></div>
                </div>
            </div>
            <div class="${displayClass}" style="margin-top: 5px;">${displayValue}<span class="unit">${unit}</span></div>
        </div>`;
    }

    // --- 3. HUMIDITY (Σταγόνα) ---
    if (label === 'Humidity') {
        let percent = value || 0; percent = Math.max(0, Math.min(100, percent));
        const gradID = 'humGradient';
        return `
        <div class="weather-box">
            <div class="weather-label">${label}</div>
            <div class="humidity-widget ${colorClass}">
                <svg class="humidity-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <defs>
                        <linearGradient id="${gradID}" x1="0%" y1="100%" x2="0%" y2="0%">
                            <stop offset="${percent}%" style="stop-color:currentColor; stop-opacity:1" />
                            <stop offset="${percent}%" style="stop-color:currentColor; stop-opacity:0.2" />
                        </linearGradient>
                    </defs>
                    <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z" fill="url(#${gradID})" stroke="currentColor" stroke-width="1.5"/>
                </svg>
            </div>
            <div class="${displayClass}" style="margin-top: 5px;">${displayValue}<span class="unit">${unit}</span></div>
        </div>`;
    }

    // --- 4. WIND SPEED (Ταχύμετρο - Gauge) ---
    if (label === 'Wind Speed') {
        // Υπολογισμός Γωνίας: 0 έως 100 (μονάδες) -> -90 έως 90 μοίρες
        // Αν η ταχύτητα είναι πάνω από 100, η βελόνα τερματίζει δεξιά (+90)
        let safeValue = value || 0;
        let maxSpeed = 100; // Ανώτατο όριο γραφικού
        
        // Τύπος: (Value / Max) * 180 - 90
        let rotation = (safeValue / maxSpeed) * 180 - 90;
        rotation = Math.max(-90, Math.min(90, rotation)); // Κόφτης

        return `
        <div class="weather-box">
            <div class="weather-label">${label}</div>
            
            <div class="gauge-widget ${colorClass}">
                <div class="gauge-needle" style="transform: rotate(${rotation}deg);"></div>
                <div class="gauge-pivot"></div>
            </div>

            <div class="${displayClass}" style="margin-top: 5px;">${displayValue}<span class="unit">${unit}</span></div>
        </div>`;
    }

    // --- 5. RAINFALL (Rain Gauge) ---
    if (label === 'Rainfall') {
        // Υπολογισμός ποσοστού: Έστω 50mm είναι το "γεμάτο" δοχείο
        let maxRain = 50; 
        let percent = (value / maxRain) * 100;
        percent = Math.max(0, Math.min(100, percent)); // Κόφτης 0-100%

        return `
        <div class="weather-box">
            <div class="weather-label">${label}</div>
            
            <div class="rain-widget-wrapper">
                <div class="rain-gauge">
                    <div class="rain-water" style="height: ${percent}%;"></div>
                </div>
            </div>

            <div class="${displayClass}" style="margin-top: 5px;">${displayValue}<span class="unit">${unit}</span></div>
        </div>`;
    }

    // --- 6. RAINRATE (Animated Cloud) ---
    if (label === 'Rainrate') {
        let speed = "0s";
        let activeClass = "";
        
        if (value > 0) {
            activeClass = "rain-active";
            // Όσο μεγαλύτερο το value, τόσο μικρότερο το duration (πιο γρήγορη βροχή)
            // 0.1mm/hr -> 1.5s (αργά), 20mm/hr -> 0.3s (πολύ γρήγορα)
            let calculatedSpeed = 1.5 - (Math.min(value, 20) / 20) * 1.2;
            speed = calculatedSpeed + "s";
        }

        return `
        <div class="weather-box">
            <div class="weather-label">${label}</div>
            
            <div class="rainrate-widget ${colorClass} ${activeClass}" style="--rain-speed: ${speed}">
                <svg class="cloud-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M18 10h-1.26A8 8 0 1 0 4 15.25"></path>
                    <path d="M20 16.58A5 5 0 0 0 18 7h-1.26A8 8 0 1 0 4 15.25"></path>
                </svg>
                
                <div class="rain-drops-container">
                    <div class="rain-drop"></div>
                    <div class="rain-drop"></div>
                    <div class="rain-drop"></div>
                </div>
            </div>

            <div class="${displayClass}" style="margin-top: 5px;">${displayValue}<span class="unit">${unit}</span></div>
        </div>`;
    }

    // --- 7. DEW POINT (Thermometer with Floating Drop) ---
    if (label === 'Dew Point') {
        const minTemp = -5;
        const maxTemp = 45;
        let percent = ((value - minTemp) / (maxTemp - minTemp)) * 100;
        percent = Math.max(0, Math.min(100, percent));
        
        // Υπολογίζουμε τη θέση της σταγόνας ώστε να ακολουθεί τη στάθμη (περίπου 15px-55px)
        let dropPos = 15 + (percent * 0.4); 

        return `
        <div class="weather-box">
            <div class="weather-label">${label}</div>
            
            <div class="dew-point-widget ${colorClass}">
                <div class="dew-indicator-drop" style="--drop-position: ${dropPos}px"></div>
                
                <div class="thermometer-widget ${colorClass}">
                    <div class="thermometer-stem">
                        <div class="thermometer-fill" style="height: ${percent}%;"></div>
                    </div>
                    <div class="thermometer-bulb"></div>
                </div>
            </div>

            <div class="${displayClass}" style="margin-top: 5px;">${displayValue}<span class="unit">${unit}</span></div>
        </div>`;
    }

    // --- 8. PRESSURE (Analog Barometer) ---
    if (label === 'Pressure') {
        const minP = 950;
        const maxP = 1050;
        // Περιορισμός τιμής στα όρια
        let safeValue = Math.max(minP, Math.min(maxP, value || 1013));
        
        // Υπολογισμός γωνίας: 950 -> -120deg, 1050 -> 120deg
        let rotation = ((safeValue - minP) / (maxP - minP)) * 240 - 120;

        return `
        <div class="weather-box">
            <div class="weather-label">${label}</div>
            
            <div class="pressure-widget">
                <div class="pressure-needle" style="transform: rotate(${rotation}deg);"></div>
                <div class="pressure-center"></div>
            </div>

            <div class="${displayClass}" style="margin-top: 5px;">${displayValue}<span class="unit">${unit}</span></div>
        </div>`;
    }

    // --- 9. DEFAULT ΓΙΑ ΟΤΙΔΗΠΟΤΕ ΑΛΛΟ ---
    return `
    <div class="weather-box">
        <div class="weather-label">${label}</div>
        <div class="weather-content-wrapper">
            <div class="${displayClass}">${displayValue}<span class="unit">${unit}</span></div>
        </div>
    </div>`;
}

// --- NEW: Custom Wind Compass Box (Pro Version + Ticks) ---
function createWindCompassBox(value) {
    let displayValue = value;
    let rotation = 0;
    
    if (value === null || value === undefined || isNaN(value)) {
        displayValue = '--';
    } else {
        rotation = value;
    }

    // 1. Δημιουργία των 36 γραμμών (Ticks)
    let ticksHTML = '';
    for (let i = 0; i < 360; i += 10) { // Από 0 έως 360, ανά 10 μοίρες
        const isMajor = (i % 90 === 0); // Κάθε 90 μοίρες είναι "Major" (N, E, S, W)
        const tickClass = isMajor ? 'compass-tick major' : 'compass-tick';
        
        // Τις περιστρέφουμε ανάλογα με τις μοίρες τους
        ticksHTML += `<div class="${tickClass}" style="transform: rotate(${i}deg);"></div>`;
    }

    return `
    <div class="weather-box">
        <div class="weather-label">Wind Direction</div>
        
        <div class="compass-wrapper">
            <div class="compass-dial">
                ${ticksHTML}

                <span class="compass-label label-n">N</span>
                <span class="compass-label label-e">E</span>
                <span class="compass-label label-s">S</span>
                <span class="compass-label label-w">W</span>
                
                <div class="compass-needle" style="transform: rotate(${rotation}deg);"></div>
                <div class="compass-pivot"></div>
            </div>
            
            <div class="weather-value">${displayValue}°</div>
        </div>
    </div>
    `;
}

function createChart(elementId, title, series, colors, config = commonChartConfig) {
    const element = document.getElementById(elementId);
    if (!element) {
        console.error('Element not found:', elementId);
        return;
    }
    
    // Clear previous chart
    if (charts[elementId]) {
        charts[elementId].destroy();
    }
    
    element.innerHTML = '';

    // Ρυθμίσεις Dark Mode
    const isDark = localStorage.getItem('theme') === 'dark';
    const textColor = isDark ? '#ffffff' : '#666666';
    const gridColor = isDark ? '#404040' : '#f0f0f0';
    const tooltipTheme = isDark ? 'dark' : 'light';
    
    try {
        const chart = new ApexCharts(element, {
            ...config,
            ...commonAxisConfig,
            series: series,
            colors: colors,
            title: {
                text: title,
                align: 'left',
                style: {
                    fontSize: window.innerWidth <= 768 ? '16px' : '14px',
                    fontWeight: 'bold',
                    color: textColor
                }
            },
            chart: {
                ...config.chart,
                type: 'line',
                background: 'transparent', // <--- ΣΗΜΑΝΤΙΚΗ ΑΛΛΑΓΗ: Κάνει το φόντο διάφανο
                foreColor: textColor,
                animations: {
                    enabled: series[0].data.length > 0
                }
            },
            grid: {
                borderColor: gridColor,
                strokeDashArray: 3  // <--- ΑΥΤΟ ΕΔΩ ΚΑΝΕΙ ΤΙΣ ΓΡΑΜΜΕΣ ΔΙΑΚΕΚΟΜΜΕΝΕΣ
            },
            tooltip: {
                ...commonAxisConfig.tooltip,
                theme: tooltipTheme
            },
            noData: {
                text: 'No data available',
                align: 'center',
                verticalAlign: 'middle',
                style: {
                    color: isDark ? '#888' : '#999',
                    fontSize: '14px'
                }
            }
        });
    
        chart.render();
        charts[elementId] = chart;
    } catch (error) {
        console.error('Error creating chart', elementId, ':', error);
        element.innerHTML = '<div class="no-data">Error loading chart</div>';
    }
}

// Save scroll position
window.addEventListener("beforeunload", () => {
    sessionStorage.setItem("scrollY", window.scrollY);
});

// Handle window resize for responsive charts
window.addEventListener('resize', function() {
    Object.values(charts).forEach(chart => {
    setTimeout(() => {
        try {
        chart.updateOptions(getMobileChartConfig());
        } catch (error) {
        console.error('Error updating chart on resize:', error);
        }
    }, 300);
    });
});

// Initialize dashboard
window.addEventListener("load", () => {
    setTimeout(async () => {
        const savedY = sessionStorage.getItem("scrollY");
        if (savedY !== null) {
            window.scrollTo({ top: parseInt(savedY), left: 0, behavior: "auto" });
        }
        
        if (document.getElementById('latest')) {
            // 1. Ρυθμίσεις
            await detectReadingInterval();
            await loadData();
            addCustomExportButtons();
            
            // 2. Ξεκινάμε το Smart Refresh
            if (autoRefresh) startAutoRefresh(); 
            
            // 3. Ξεκινάμε το απλό ρολόι (αντί για το προβληματικό TimeSync)
            startClock(); 
        }
    }, 100);
});

// --- 1. CUSTOM POPUP SYSTEM ---
function createModalHTML() {
    if (document.getElementById('custom-modal')) return;
    const div = document.createElement('div');
    div.id = 'custom-modal';
    div.className = 'modal-overlay';
    div.innerHTML = `
        <div class="modal-box">
            <h3 id="modal-title" class="modal-title"></h3>
            <div id="modal-content"></div>
            <div id="modal-actions" class="modal-actions"></div>
        </div>
    `;
    document.body.appendChild(div);
}

// --- UPDATED SHOW MODAL (With Scroll Lock) ---
function showModal(title, contentHTML, actions, extraClass = '') {
    createModalHTML();
    
    // 1. ΚΛΕΙΔΩΜΑ SCROLL: Αυτή η γραμμή παγώνει το πίσω μέρος
    document.body.style.overflow = 'hidden';

    const modal = document.getElementById('custom-modal');
    const modalBox = modal.querySelector('.modal-box');
    
    // Reset classes
    modalBox.className = 'modal-box'; 
    if (extraClass) modalBox.classList.add(extraClass);

    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-content').innerHTML = contentHTML;
    
    const actionContainer = document.getElementById('modal-actions');
    actionContainer.innerHTML = '';
    
    const newModal = modal.cloneNode(true);
    modal.parentNode.replaceChild(newModal, modal);
    const currentModal = document.getElementById('custom-modal');
    const currentActionContainer = currentModal.querySelector('.modal-actions');
    
    if (actions && actions.length > 0) {
        actions.forEach(action => {
            const btn = document.createElement('button');
            btn.textContent = action.text;
            btn.className = `modal-btn ${action.class || 'modal-btn-primary'}`;
            btn.onclick = () => {
                if (action.onClick) action.onClick();
                if (action.close !== false) closeModal();
            };
            currentActionContainer.appendChild(btn);
        });
    }
    
    setTimeout(() => {
        currentModal.classList.add('show');
        
        // Auto-focus logic
        const dangerBtn = currentModal.querySelector('.modal-btn-danger');
        const primaryBtn = currentModal.querySelector('.modal-btn-primary');
        const secondaryBtn = currentModal.querySelector('.modal-btn-secondary');
        
        if (dangerBtn) dangerBtn.focus(); 
        else if (primaryBtn) primaryBtn.focus(); 
        else if (secondaryBtn) secondaryBtn.focus();

        // Key handler (Enter/Escape)
        const keyHandler = (e) => {
            if (!currentModal.classList.contains('show')) {
                document.removeEventListener('keydown', keyHandler);
                return;
            }
            if (e.key === 'Enter') {
                if (document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
                    e.preventDefault();
                    if (dangerBtn) dangerBtn.click();
                    else if (primaryBtn) primaryBtn.click();
                    else if (secondaryBtn) secondaryBtn.click();
                }
            }
            if (e.key === 'Escape') {
                closeModal();
            }
        };
        document.addEventListener('keydown', keyHandler, { once: true });
        
    }, 10);
}

// --- UPDATED CLOSE MODAL (With Scroll Unlock) ---
function closeModal() {
    const modal = document.getElementById('custom-modal');
    if (modal) {
        modal.classList.remove('show');
        
        // 2. ΞΕΚΛΕΙΔΩΜΑ SCROLL: Επαναφέρει το scrolling
        document.body.style.overflow = '';

        setTimeout(() => {
            // Optional cleanup
        }, 300);
    }
}

// Override standard alert
window.alert = function(message) {
    showModal('Notification', `<p class="modal-message">${message}</p>`, [
        { text: 'OK', class: 'modal-btn-primary' }
    ]);
};

function saveCurrentMoment() {
    // --- 1. GUEST CHECK ---
    if (typeof isUserLoggedIn !== 'undefined' && !isUserLoggedIn) {
        showModal('Access Restricted', 
            `<div style="text-align: center;">
                <p class="modal-message" style="margin-bottom: 20px;">
                    Saving moments requires an account
                </p>
                <img src="/static/img_icon/lock.png" style="width: 50px; opacity: 0.5; margin-bottom: 15px;">
                
                <p style="font-size: 0.95rem; color: #666;">
                    Please <a href="/login" style="color: #0066cc; font-weight: bold;">Login</a> or 
                    <a href="/signup" style="color: #0066cc; font-weight: bold;">Sign Up</a>
                </p>
            </div>`, 
            [{ text: 'Close', class: 'modal-btn-secondary' }]
        );
        return; 
    }

    // --- 2. INPUT FORM (Αυτό παραμένει Modal γιατί χρειάζεται πληκτρολόγηση) ---
    showModal('Save Moment', 
        `<p class="modal-message">Give this weather snapshot a name:</p>
         <input type="text" id="moment-note" class="modal-input" placeholder="e.g. Heavy Storm" value="Weather Snapshot" autocomplete="off">`, 
        [
            { text: 'Cancel', class: 'modal-btn-secondary' },
            { 
                text: 'Save', 
                class: 'modal-btn-primary',
                close: false, // Δεν κλείνει αυτόματα για να προλάβουμε να κάνουμε το save
                onClick: async () => {
                    const note = document.getElementById('moment-note').value;
                    const saveBtn = document.querySelector('.modal-btn-primary');
                    
                    // Ένδειξη ότι κάτι γίνεται
                    if(saveBtn) { saveBtn.textContent = 'Saving...'; saveBtn.style.opacity = '0.7'; }
                    
                    try {
                        const r = await fetch('/api/save_moment', {
                            method: 'POST', 
                            headers: { 'Content-Type': 'application/json' }, 
                            body: JSON.stringify({ note: note })
                        });
                        const result = await r.json(); 
                        
                        // Κλείνουμε τη φόρμα εισαγωγής
                        closeModal();
                        
                        // --- ΕΔΩ ΕΙΝΑΙ Η ΑΛΛΑΓΗ ΣΕ TOAST ---
                        if (result.success) {
                            // ΕΠΙΤΥΧΙΑ: Εμφάνιση Toast αντί για Modal
                            showToast('Moment saved successfully!', 'success');
                        } else {
                            // ΣΦΑΛΜΑ SERVER: Εμφάνιση Toast Error
                            showToast('Failed to save: ' + result.error, 'error');
                        }

                    } catch (e) { 
                        closeModal(); 
                        // ΣΦΑΛΜΑ ΣΥΝΔΕΣΗΣ: Εμφάνιση Toast Error
                        showToast('Connection failed.', 'error'); 
                    }
                }
            }
        ]
    );
    
    // Focus στο input πεδίο
    setTimeout(() => { 
        const i = document.getElementById('moment-note'); 
        if(i){ 
            i.focus(); 
            i.addEventListener("keypress", (e)=>{
                if(e.key==="Enter"){
                    e.preventDefault(); 
                    document.querySelector('.modal-btn-primary').click();
                }
            });
        } 
    }, 100);
}

// --- NEW SHARED FUNCTION: DELETE ACCOUNT ---
function deleteAccount() {
    showModal("⚠️ Delete Account", 
        `<p class="modal-message">Are you sure you want to delete your account? <br><br><b>This cannot be undone</b></p>`, 
        [
            { text: "Cancel", class: "modal-btn-secondary" },
            { 
                text: "Permanently Delete", 
                class: "modal-btn-danger", 
                onClick: async () => { 
                    try { 
                        const r = await fetch('/api/delete_account', { method: 'DELETE' }); 
                        const j = await r.json(); 
                        if(j.success) {
                            window.location.href = "/"; 
                        } else {
                            setTimeout(() => showModal("Error", `<p>${j.error}</p>`, [{text:"OK"}]), 300); 
                        }
                    } catch(e) {
                        alert("Connection failed");
                    } 
                } 
            }
        ]
    );
}

// --- MOBILE-STYLE PASSWORD LOGIC ---
function initMobilePassword(visibleId, hiddenId, btn) {
    const visible = document.getElementById(visibleId);
    const hidden = document.getElementById(hiddenId);
    const img = btn.querySelector('img');
    let timeout;
    let isVisible = false;

    // 1. Λογική Κουμπιού (Ματάκι)
    btn.onclick = () => {
        isVisible = !isVisible;
        if (isVisible) {
            // Εμφάνιση κωδικού
            visible.value = hidden.value;
            img.src = "/static/img_icon/hide.png";
        } else {
            // Απόκρυψη (όλα τελείες)
            visible.value = "•".repeat(hidden.value.length);
            img.src = "/static/img_icon/show.png";
        }
    };

    // 2. Λογική Πληκτρολόγησης
    visible.addEventListener('input', (e) => {
        // Αν το ματάκι είναι ανοιχτό, απλά αντιγράφουμε στο κρυφό πεδίο
        if (isVisible) {
            hidden.value = visible.value;
            return;
        }

        // --- ΕΙΔΙΚΗ ΔΙΑΧΕΙΡΙΣΗ ---
        if (e.inputType === 'insertText' && e.data) {
            // Προσθήκη χαρακτήρα
            hidden.value += e.data;
            
            // Εμφάνιση: Τελείες + Τελευταίος χαρακτήρας
            const len = hidden.value.length;
            visible.value = "•".repeat(len - 1) + e.data;

            // Χρονόμετρο 1 δευτερολέπτου για απόκρυψη
            clearTimeout(timeout);
            timeout = setTimeout(() => {
                if (!isVisible) visible.value = "•".repeat(hidden.value.length);
            }, 1000);
            
        } else if (e.inputType === 'deleteContentBackward') {
            // Backspace (Διαγραφή)
            hidden.value = hidden.value.slice(0, -1);
            visible.value = "•".repeat(hidden.value.length);
        } else {
            // Άλλες περιπτώσεις (π.χ. paste), απλό reset
            hidden.value = visible.value; // Προσωρινή αποθήκευση
            visible.value = "•".repeat(hidden.value.length);
        }
    });
}

// --- DARK MODE SYSTEM (Global) ---

// 1. Βασική συνάρτηση που φορτώνει το CSS αρχείο
function enableDarkMode() {
    if (!document.getElementById('dark-theme-style')) {
        const head = document.getElementsByTagName('head')[0];
        const link = document.createElement('link');
        link.id = 'dark-theme-style';
        link.rel = 'stylesheet';
        link.type = 'text/css';
        link.href = '/static/style-dark.css'; // Φόρτωση του νέου αρχείου
        head.appendChild(link);
    }
}

// 2. Συνάρτηση που αφαιρεί το CSS αρχείο
function disableDarkMode() {
    const link = document.getElementById('dark-theme-style');
    if (link) link.remove();
}

// 2. Ενημέρωσε τη συνάρτηση toggleTheme (αντικατάστησέ την ή πρόσθεσε τη γραμμή)
// --- UPDATED TOGGLE THEME FUNCTION ---
function toggleTheme() {
    const currentTheme = localStorage.getItem('theme');
    
    // Εικόνες
    const sunIcon = "/static/img_icon/sun.png";
    const moonIcon = "/static/img_icon/moon.png";

    if (currentTheme === 'dark') {
        // --- ΓΥΡΙΣΜΑ ΣΕ LIGHT MODE ---
        disableDarkMode();
        localStorage.setItem('theme', 'light');
        
        // Αλλαγή ΟΛΩΝ των εικονιδίων σε Φεγγάρι (για να πατήσεις και να πας σε Dark)
        document.querySelectorAll('.theme-icon').forEach(icon => {
            icon.src = moonIcon;
        });
        
        updateChartsTheme('light');
        updateTrashIcons('light'); 

    } else {
        // --- ΓΥΡΙΣΜΑ ΣΕ DARK MODE ---
        enableDarkMode();
        localStorage.setItem('theme', 'dark');
        
        // Αλλαγή ΟΛΩΝ των εικονιδίων σε Ήλιο (για να πατήσεις και να πας σε Light)
        document.querySelectorAll('.theme-icon').forEach(icon => {
            icon.src = sunIcon;
        });

        updateChartsTheme('dark');
        updateTrashIcons('dark');
    }
}

// 4. Helper για τα γραφήματα (αν υπάρχουν στη σελίδα)
function updateChartsTheme(mode) {
    if (typeof charts === 'undefined' || Object.keys(charts).length === 0) return;
    
    // ΑΛΛΑΓΗ ΕΔΩ: Το '#e0e0e0' έγινε '#ffffff'
    const color = mode === 'dark' ? '#ffffff' : '#666666';
    const gridColor = mode === 'dark' ? '#404040' : '#f0f0f0';
    
    Object.values(charts).forEach(chart => {
        chart.updateOptions({
            chart: { foreColor: color },
            grid: { borderColor: gridColor },
            theme: { mode: mode }
        });
    });
}

// 3. Ενημέρωσε τον EventListener για να τρέχει και στην αρχή
document.addEventListener('DOMContentLoaded', () => {
    const savedTheme = localStorage.getItem('theme');
    const sunIcon = "/static/img_icon/sun.png";
    const moonIcon = "/static/img_icon/moon.png";

    const header = document.querySelector('.dashboard-header');

    // Ασφάλεια: Αν δεν βρει το header (π.χ. σε άλλη σελίδα), να μην σκάσει λάθος
    if (!header) return;

    window.addEventListener('scroll', () => {
        // Αν έχουμε κατέβει περισσότερο από 10px
        if (window.scrollY > 5) {
            header.classList.add('stuck');
        } else {
            // Αν είμαστε τέρμα πάνω
            header.classList.remove('stuck');
        }
    });

    if (savedTheme === 'dark') {
        enableDarkMode();
        setTimeout(() => updateChartsTheme('dark'), 500);
        updateTrashIcons('dark');
        
        // Αρχική ρύθμιση εικονιδίων σε Ήλιο (αφού είμαστε Dark)
        document.querySelectorAll('.theme-icon').forEach(icon => {
            icon.src = sunIcon;
        });
    } else {
        updateTrashIcons('light');
        // Αρχική ρύθμιση εικονιδίων σε Φεγγάρι (αφού είμαστε Light)
        document.querySelectorAll('.theme-icon').forEach(icon => {
            icon.src = moonIcon;
        });
    }
    // Χρωματίζει τα My Moments αν υπάρχουν στη σελίδα
    colorAllMoments();
    setupBackToTop();
    checkPersistentToast();
});

// 1. Πρόσθεσε αυτή τη ΝΕΑ συνάρτηση στο τέλος του αρχείου
function updateTrashIcons(mode) {
    const icons = document.querySelectorAll('.trash-icon');
    if (icons.length === 0) return;

    const blackIcon = "/static/img_icon/trash_b.png";
    const whiteIcon = "/static/img_icon/trash_w.png";

    icons.forEach(icon => {
        icon.src = (mode === 'dark') ? whiteIcon : blackIcon;
    });
}

// --- BACK TO TOP BUTTON LOGIC ---

function setupBackToTop() {
    // 1. Δημιουργία του κουμπιού (αν δεν υπάρχει ήδη)
    if (!document.getElementById('back-to-top-btn')) {
        const btn = document.createElement('button');
        btn.id = 'back-to-top-btn';
        btn.innerHTML = '<img src="/static/img_icon/arrow.png" alt="Up" class="back-to-top-icon">';
        btn.title = "Go to top";
        document.body.appendChild(btn);

        // 2. Λειτουργία Scroll-to-Top όταν πατηθεί
        btn.addEventListener('click', function() {
            window.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
            
            // ΝΕΑ ΕΝΤΟΛΗ: Κάνει "αποεπιλογή" (Blur) στο κουμπί αμέσως μόλις πατηθεί
            // Έτσι σταματάει να φαίνεται πατημένο στα κινητά
            this.blur(); 
        });
    }

    // 3. Έλεγχος Scroll για εμφάνιση/απόκρυψη
    const btn = document.getElementById('back-to-top-btn');
    
    window.addEventListener('scroll', () => {
        // Αν κατέβουμε πάνω από 300px, εμφάνισε το κουμπί
        if (window.scrollY > 300) {
            btn.classList.add('show');
        } else {
            btn.classList.remove('show');
        }
    });
}

// --- MY MOMENTS COLORING (Auto-Scan) ---
function colorAllMoments() {
    // 1. Βρες όλα τα κουτάκια που έχουν την κλάση 'weather-box'
    const boxes = document.querySelectorAll('.weather-box');

    boxes.forEach(box => {
        // 2. Βρες την ετικέτα (π.χ. "Air Temp") και την τιμή (π.χ. "25.4°C")
        const labelEl = box.querySelector('.weather-label');
        const valueEl = box.querySelector('.weather-value');

        if (labelEl && valueEl) {
            const label = labelEl.textContent.trim(); // π.χ. "Air Temp"
            const text = valueEl.textContent.trim();  // π.χ. "12.5°C"
            
            // 3. Μετατροπή κειμένου σε αριθμό (το parseFloat αγνοεί τα °C, %, κλπ)
            const value = parseFloat(text);

            // Αν δεν είναι αριθμός (π.χ. "--"), προχώρα
            if (isNaN(value)) return;

            // 4. Υπολογισμός χρώματος (χρησιμοποιούμε την ίδια συνάρτηση με το Dashboard!)
            const colorClass = getColorClass(label, value);

            // 5. Προσθήκη της κλάσης χρώματος
            if (colorClass) {
                valueEl.classList.add(colorClass);
            }
        }
    });
}

// --- PERSISTENT TOAST SYSTEM ---
function showToast(message, type = 'info', duration = 2000, fromStorage = false) {
    // 1. Δημιουργία Container
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }

    // 2. Αποθήκευση στο Session Storage (ΜΟΝΟ αν είναι νέο Toast)
    // Έτσι, αν αλλάξεις σελίδα, η επόμενη σελίδα θα βρει τα δεδομένα.
    if (!fromStorage) {
        const toastData = {
            message: message,
            type: type,
            endTime: Date.now() + duration // Πότε πρέπει να εξαφανιστεί
        };
        sessionStorage.setItem('persistentToast', JSON.stringify(toastData));
    }

    // 3. Επιλογή Εικονιδίου
    let iconHtml = '';
    const imgStyle = 'width: 24px; height: 24px; vertical-align: middle;';

    if (type === 'success') {
        iconHtml = `<img src="/static/img_icon/check.png" alt="Success" style="${imgStyle}">`;
    } else if (type === 'error') {
        iconHtml = `<img src="/static/img_icon/error.png" alt="Error" style="${imgStyle}">`;
    } else {
        iconHtml = `<span style="font-size: 1.2rem; font-weight: bold;">ℹ</span>`;
    }

    // 4. Δημιουργία HTML
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: center;">
            ${iconHtml}
        </div>
        <span style="margin-left: 8px;">${message}</span>
    `;

    container.appendChild(toast);

    // 5. Animation Εμφάνισης
    // Χρησιμοποιούμε requestAnimationFrame για να βεβαιωθούμε ότι το CSS transition θα παίξει σωστά
    requestAnimationFrame(() => {
        setTimeout(() => {
            toast.classList.add('show');
        }, 10);
    });

    // 6. Αυτόματη Αφαίρεση (με βάση το duration)
    setTimeout(() => {
        toast.classList.remove('show');
        
        // Όταν τελειώσει το fade-out transition, το διαγράφουμε από το DOM
        toast.addEventListener('transitionend', () => {
            toast.remove();
            
            // ΚΑΘΑΡΙΣΜΟΣ ΜΝΗΜΗΣ:
            // Αν το toast που μόλις έσβησε είναι αυτό που έχουμε στη μνήμη, το διαγράφουμε.
            // (Ώστε να μην εμφανιστεί ξανά αν κάνουμε refresh αργότερα)
            const stored = sessionStorage.getItem('persistentToast');
            if (stored) {
                const data = JSON.parse(stored);
                // Αν το μήνυμα είναι ίδιο, το καθαρίζουμε
                if (data.message === message) {
                    sessionStorage.removeItem('persistentToast');
                }
            }
        });
    }, duration);
}

// --- CHECK FOR SAVED TOASTS (ON PAGE LOAD) ---
function checkPersistentToast() {
    const stored = sessionStorage.getItem('persistentToast');
    if (stored) {
        const data = JSON.parse(stored);
        const now = Date.now();
        const remainingTime = data.endTime - now;

        // Αν υπάρχει ακόμα χρόνος (δεν έχει λήξει)
        if (remainingTime > 0) {
            // Εμφάνισέ το για τον χρόνο που απομένει
            // true = δηλώνει ότι έρχεται από storage για να μην το ξανα-αποθηκεύσει
            showToast(data.message, data.type, remainingTime, true);
        } else {
            // Αν έχει λήξει, καθάρισέ το από τη μνήμη
            sessionStorage.removeItem('persistentToast');
        }
    }
}

// --- NEW MODERN EXPORT UI ---

// Οι διαθέσιμες μετρήσεις (Πίνακας με Label και Key από τη βάση δεδομένων)
const exportMetrics = [
    { label: 'Air Temperature (°C)', key: 'Air Temperature' },
    { label: 'Ground Temp (°C)', key: 'Soil Temperature' },
    { label: 'Humidity (%)', key: 'Humidity' },
    { label: 'Pressure (hPa)', key: 'Pressure' },
    { label: 'Wind Speed (km/h)', key: 'WindSpeed' },
    { label: 'Wind Direction (°)', key: 'WindDirection' },
    { label: 'RainFall (mm)', key: 'RainFall' },
    { label: 'Rain Rate (mm/h)', key: 'RainRate' },
    { label: 'Dew Point (°C)', key: 'DewPoint' }
];

function openExportModal() {
    // 1. Guest Check - ΑΚΡΙΒΕΣ ΑΝΤΙΓΡΑΦΟ ΑΠΟ saveCurrentMoment
    if (typeof isUserLoggedIn !== 'undefined' && !isUserLoggedIn) {
        showModal('Access Restricted', 
                `<div style="text-align: center;">
                    <p class="modal-message" style="margin-bottom: 20px;">
                        Exporting data requires an account
                    </p>
                    <img src="/static/img_icon/lock.png" style="width: 50px; opacity: 0.5; margin-bottom: 15px;">
                    
                    <p style="font-size: 0.95rem; color: #666;">
                        Please <a href="/login" style="color: #0066cc; font-weight: bold;">Login</a> or 
                        <a href="/signup" style="color: #0066cc; font-weight: bold;">Sign Up</a>
                    </p>
                </div>`, 
                [{ text: 'Close', class: 'modal-btn-secondary' }]
            );
        return;
    }

    const now = new Date();
    const yesterday = new Date(now.getTime() - (24 * 60 * 60 * 1000));
    const minDate = new Date(now.getTime() - (MAX_RETENTION_HOURS * 60 * 60 * 1000));

    const formatDateTime = (date) => {
        const pad = (n) => n < 10 ? '0' + n : n;
        return date.getFullYear() + '-' + 
               pad(date.getMonth() + 1) + '-' + 
               pad(date.getDate()) + 'T' + 
               pad(date.getHours()) + ':' + 
               pad(date.getMinutes());
    };

    const nowStr = formatDateTime(now);
    const yesterdayStr = formatDateTime(yesterday);
    const minDateStr = formatDateTime(minDate);

    // ΝΕΟ ΚΑΘΑΡΟ HTML STRUCTURE
    let html = `
        <div class="export-date-group">
            <div class="date-input-wrapper">
                <label for="export-start">Start Time</label>
                <input type="datetime-local" id="export-start" class="export-date-input" 
                       value="${yesterdayStr}" max="${nowStr}" min="${minDateStr}">
            </div>
            <div class="date-input-wrapper">
                <label for="export-end">End Time</label>
                <input type="datetime-local" id="export-end" class="export-date-input" 
                       value="${nowStr}" max="${nowStr}" min="${minDateStr}">
            </div>
        </div>

        <div style="text-align: center;">
            <span class="history-limit-text">
                Max history limit: ${Math.round(MAX_RETENTION_HOURS/24)} days
            </span>
        </div>

        <div class="export-section-header">
            <p>Select Parameters:</p>
            <button id="btn-select-all" type="button">Select All</button>
        </div>

        <div class="export-grid">
            ${exportMetrics.map((m) => `
                <div class="export-option selected" data-key="${m.key}" onclick="toggleExportOption(this)">
                    ${m.label}
                </div>
            `).join('')}
        </div>
    `;

    showModal('Export History', html, [
        { text: 'Cancel', class: 'modal-btn-secondary' },
        { 
            text: 'Download CSV', 
            class: 'modal-btn-primary', 
            close: false, 
            onClick: generateCustomCSV 
        }
    ]);

    // Λογική Select All & Date Events
    setTimeout(() => {
        const btnAll = document.getElementById('btn-select-all');
        let allSelected = true;
        btnAll.textContent = "Deselect All";

        btnAll.onclick = function() {
            const allOptions = document.querySelectorAll('.export-option');
            if (allSelected) {
                allOptions.forEach(opt => opt.classList.remove('selected'));
                btnAll.textContent = "Select All";
                allSelected = false;
            } else {
                allOptions.forEach(opt => opt.classList.add('selected'));
                btnAll.textContent = "Deselect All";
                allSelected = true;
            }
        };
        
        const startInput = document.getElementById('export-start');
        const endInput = document.getElementById('export-end');
        startInput.addEventListener('change', () => { endInput.min = startInput.value; });
    }, 50);
}

// Μικρή αλλαγή και εδώ για να ενημερώνεται το κουμπί αν πατάμε τα chips ένα-ένα
function toggleExportOption(el) {
    el.classList.toggle('selected');
    
    // Έλεγχος: Αν τα ξε-επιλέξαμε όλα με το χέρι, το κουμπί να γίνει "Select All"
    const allOptions = document.querySelectorAll('.export-option');
    const selectedCount = document.querySelectorAll('.export-option.selected').length;
    const btnAll = document.getElementById('btn-select-all');
    
    if (btnAll) {
        if (selectedCount === allOptions.length) {
            btnAll.textContent = "Deselect All";
        } else {
            btnAll.textContent = "Select All"; // Αν έστω και ένα λείπει, δίνουμε επιλογή να τα πάρει όλα
        }
    }
}

// --- UPDATED EXPORT LOGIC (Range Calculation) ---
async function generateCustomCSV() {
    // 1. Λήψη Επιλογών
    const selectedOptions = document.querySelectorAll('.export-option.selected');
    if (selectedOptions.length === 0) {
        showToast('Please select at least one metric', 'error');
        return;
    }
    const selectedKeys = Array.from(selectedOptions).map(el => el.dataset.key);
    const selectedLabels = Array.from(selectedOptions).map(el => el.innerText);

    // 2. Λήψη Ημερομηνιών
    const startVal = document.getElementById('export-start').value;
    const endVal = document.getElementById('export-end').value;

    if (!startVal || !endVal) {
        showToast('Please select valid Start and End times', 'error');
        return;
    }

    const startDate = new Date(startVal);
    const endDate = new Date(endVal);
    const now = new Date();

    // Validations
    if (startDate > endDate) {
        showToast('Start time cannot be after End time', 'error');
        return;
    }
    if (startDate > now) {
        showToast('Start time cannot be in the future', 'error');
        return;
    }

    // 3. ΥΠΟΛΟΓΙΣΜΟΣ: Πόσες ώρες πίσω πρέπει να πάμε;
    // Βρίσκουμε τη διαφορά του ΤΩΡΑ με το START DATE σε ώρες.
    // Π.χ. Αν θέλω από "Προχθές" μέχρι "Χθες", πρέπει να ζητήσω 48 ώρες από το API
    // και μετά να πετάξω ότι είναι πιο καινούργιο από το "Χθες".
    
    const diffMs = now - startDate;
    let hoursToFetch = Math.ceil(diffMs / (1000 * 60 * 60));
    
    // Ασφάλεια: Να ζητήσουμε τουλάχιστον 1 ώρα
    if (hoursToFetch < 1) hoursToFetch = 1;
    
    // Έλεγχος Ορίου
    if (hoursToFetch > MAX_RETENTION_HOURS) {
        // Αν ζητάει παραπάνω, το κόβουμε στο μέγιστο
        hoursToFetch = MAX_RETENTION_HOURS;
    }

    // UI Feedback
    const downloadBtn = document.querySelector('.modal-btn-primary');
    const originalText = downloadBtn.textContent;
    downloadBtn.textContent = 'Fetching & Filtering...';
    downloadBtn.style.opacity = '0.7';

    try {
        // 4. API CALL
        console.log(`Requesting last ${hoursToFetch} hours to cover the range...`);
        const response = await fetch(`/api/history/last/${hoursToFetch}hours`);
        
        if (!response.ok) throw new Error('Failed to fetch history');
        
        const rawText = await response.text();
        const cleanText = rawText.replace(/NaN/g, 'null');
        const data = JSON.parse(cleanText);

        if (!data || data.length === 0) {
            showToast('No data found for this period.', 'info');
            downloadBtn.textContent = originalText;
            downloadBtn.style.opacity = '1';
            return;
        }

        // 5. CLIENT-SIDE FILTERING (Το φιλτράρισμα που λέγαμε)
        // Κρατάμε μόνο όσα είναι: Start <= Time <= End
        const filteredData = data.filter(row => {
            const rowDate = parseDate(row.Time); // Η συνάρτηση που έχεις ήδη
            return rowDate >= startDate && rowDate <= endDate;
        });

        if (filteredData.length === 0) {
            showToast('Data fetched but nothing found in exact range.', 'info');
            downloadBtn.textContent = originalText;
            downloadBtn.style.opacity = '1';
            return;
        }

        // 6. Δημιουργία CSV (με τα filteredData πλέον)
        let csvContent = '\uFEFF'; // BOM για UTF-8
        csvContent += '"Timestamp",' + selectedLabels.map(l => `"${l}"`).join(',') + '\r\n';

        filteredData.forEach(row => {
            let dateVal = parseDate(row.Time);
            const timestamp = `"${dateVal.toLocaleString('el-GR', { hour12: false })}"`;
            let rowStr = timestamp;

            selectedKeys.forEach(key => {
                let val = getValue(row, key);
                if (val === null || val === undefined) val = '';
                else val = val.toString();
                rowStr += ',' + val;
            });
            csvContent += rowStr + '\r\n';
        });

        // 7. Download
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.setAttribute("href", url);
        // Όνομα αρχείου με ημερομηνίες
        const filename = `Weather_${startVal.replace('T', '_')}_to_${endVal.replace('T', '_')}.csv`;
        
        link.setAttribute("download", filename);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        closeModal();
        showToast(`Exported ${filteredData.length} records successfully!`, 'success');

    } catch (error) {
        console.error('Export Error:', error);
        showToast('Error processing data.', 'error');
        downloadBtn.textContent = originalText;
        downloadBtn.style.opacity = '1';
    }
}