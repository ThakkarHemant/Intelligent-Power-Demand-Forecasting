/* ═══════════════════════════════════════════════════════════
   APU Power Forecast · Frontend Application
   Impeccable-style · Chart.js · Clean editorial
   ═══════════════════════════════════════════════════════════ */

const API = 'http://localhost:8000';

/* ── State ───────────────────────────────────────────────── */
let forecastChart = null;
let weatherChart  = null;
let feederCharts  = {};
let allHolidays   = [];
let weatherBlocks = [];
let currentTarget = 'load';
let currentWeatherView = 'temp';
let currentHolCat = 'all';

/* ── Chart.js global defaults ────────────────────────────── */
Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.color       = '#787672';
Chart.defaults.borderColor = '#E2DFD8';
Chart.defaults.plugins.legend.display = false;

/* ── Colour map ──────────────────────────────────────────── */
const C = {
  forecast: '#0F0F0F',
  temp:     '#FFB800',
  hum:      '#0284C7',
  cloud:    '#78716C',
  wind:     '#16A34A',
  F1:       '#7C3AED',
  F2:       '#0284C7',
  F3:       '#16A34A',
};
const TARGET_COLOR = {
  load: C.forecast,
  F1:   C.F1,
  F2:   C.F2,
  F3:   C.F3,
};
const WEATHER_META = {
  temp:  { label: 'Temperature', unit: '°C',   color: C.temp,  fill: 'rgba(255,184,0,0.08)'  },
  hum:   { label: 'Humidity',    unit: '%',    color: C.hum,   fill: 'rgba(2,132,199,0.08)'  },
  cloud: { label: 'Cloud Cover', unit: '%',    color: C.cloud, fill: 'rgba(120,113,108,0.08)'},
  wind:  { label: 'Wind Speed',  unit: 'km/h', color: C.wind,  fill: 'rgba(22,163,74,0.08)'  },
};

/* ── Utilities ───────────────────────────────────────────── */
function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata'
  });
}
function fmtDate(iso) {
  return new Date(iso).toLocaleDateString('en-IN', {
    day: 'numeric', month: 'short', year: 'numeric'
  });
}
function fmtShort(iso) {
  return new Date(iso).toLocaleDateString('en-IN', {
    day: 'numeric', month: 'short'
  });
}
function safe(v, decimals = 1) {
  if (v == null || isNaN(v) || !isFinite(v)) return null;
  return parseFloat(v.toFixed(decimals));
}

/* ── Live clock ──────────────────────────────────────────── */
function startClock() {
  const el = document.getElementById('live-time');
  const tick = () => {
    el.textContent = new Date().toLocaleTimeString('en-IN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      timeZone: 'Asia/Kolkata'
    });
  };
  tick(); setInterval(tick, 1000);
}

/* ── Status helpers ──────────────────────────────────────── */
function setStatus(msg, done = false) {
  const el  = document.getElementById('status-text');
  const sp  = document.getElementById('s-spinner');
  el.textContent = msg;
  if (done) { sp.classList.add('done'); }
  else      { sp.classList.remove('done'); }
}

/* ── Inline chart tooltip style ─────────────────────────── */
const TOOLTIP_OPTS = {
  backgroundColor: '#0F0F0F',
  titleColor:      '#FFFFFF',
  bodyColor:       '#A09D99',
  borderColor:     '#2A2A2A',
  borderWidth:     1,
  padding:         12,
  titleFont:       { size: 11, weight: '600', family: "'JetBrains Mono', monospace" },
  bodyFont:        { size: 11, family: "'Inter', sans-serif" },
  cornerRadius:    6,
};

/* ══════════════════════════════════════════════════════════
   FORECAST CHART
══════════════════════════════════════════════════════════ */
function buildForecastChart(blocks, holidays) {
  const labels   = blocks.map(b => fmtTime(b.timestamp));
  const demand   = blocks.map(b => safe(b.forecast_mw));
  const temps    = blocks.map(b => safe(b.temp));

  /* Holiday annotation boxes */
  const annotations = {};
  (holidays || []).forEach((h, i) => {
    const dateStr = h.date;
    const idx = blocks.findIndex(b => b.timestamp.startsWith(dateStr));
    if (idx !== -1) {
      annotations[`hol${i}`] = {
        type: 'box',
        xMin: idx, xMax: Math.min(idx + 47, blocks.length - 1),
        backgroundColor: 'rgba(255,184,0,0.07)',
        borderColor:     'rgba(255,184,0,0.35)',
        borderWidth: 1,
        label: {
          display: true,
          content: h.name,
          font: { size: 9, family: "'JetBrains Mono', monospace" },
          color: '#CC8E00',
          position: { x: 'start', y: 'start' },
          padding: { top: 4, left: 6 },
        },
      };
    }
  });

  const canvas = document.getElementById('forecast-chart');
  const ctx    = canvas.getContext('2d');

  const lineColor = TARGET_COLOR[currentTarget];
  const rgb = lineColor === '#0F0F0F' ? '15,15,15' : lineColor.replace('#','').match(/../g).map(h=>parseInt(h,16)).join(',');

  if (forecastChart) forecastChart.destroy();
  forecastChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: `Demand (${currentTarget === 'load' ? 'System' : currentTarget}) MW`,
          data: demand,
          borderColor: lineColor,
          backgroundColor: `rgba(${rgb},0.06)`,
          fill: true, tension: 0.35,
          borderWidth: 2, pointRadius: 0, pointHoverRadius: 4,
          pointHoverBackgroundColor: lineColor,
          pointHoverBorderColor: '#fff',
          pointHoverBorderWidth: 2,
          yAxisID: 'y',
        },
        {
          label: 'Temperature (°C)',
          data: temps,
          borderColor: C.temp,
          borderDash: [5,3],
          fill: false, tension: 0.35,
          borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 3,
          yAxisID: 'yT',
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      animation: { duration: 500 },
      plugins: {
        legend: { display: true,
          labels: { padding: 18, usePointStyle: true, pointStyleWidth: 20, font: { size: 11 } }
        },
        tooltip: { ...TOOLTIP_OPTS,
          callbacks: {
            label: ctx2 => ctx2.dataset.yAxisID === 'yT'
              ? ` Temp: ${ctx2.parsed.y?.toFixed(1)} °C`
              : ` Demand: ${ctx2.parsed.y?.toFixed(2)} MW`,
          },
        },
        annotation: { annotations },
      },
      scales: {
        x: {
          grid: { color: '#F0EEE9' },
          ticks: { maxTicksLimit: 12, maxRotation: 0, font: { size: 10 } },
        },
        y: {
          grid: { color: '#F0EEE9' },
          title: { display: true, text: 'Demand (MW)', color: '#787672', font: { size: 10 } },
          ticks: { font: { size: 10 } },
        },
        yT: {
          position: 'right',
          grid: { drawOnChartArea: false },
          title: { display: true, text: '°C', color: C.temp, font: { size: 10 } },
          ticks: { color: C.temp, font: { size: 10 } },
        },
      },
    },
  });
}

/* ══════════════════════════════════════════════════════════
   WEATHER CHART
══════════════════════════════════════════════════════════ */
function buildWeatherChart(blocks, view) {
  const labels = blocks.map(b => fmtTime(b.timestamp));
  const data   = blocks.map(b => safe(b[view]));
  const meta   = WEATHER_META[view];

  const canvas = document.getElementById('weather-chart');
  const ctx    = canvas.getContext('2d');

  if (weatherChart) weatherChart.destroy();
  weatherChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: `${meta.label} (${meta.unit})`,
        data,
        borderColor: meta.color,
        backgroundColor: meta.fill,
        fill: true, tension: 0.4,
        borderWidth: 2, pointRadius: 0, pointHoverRadius: 3,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      animation: { duration: 350 },
      plugins: {
        legend: { display: false },
        tooltip: { ...TOOLTIP_OPTS,
          callbacks: {
            label: ctx2 => ` ${meta.label}: ${ctx2.parsed.y?.toFixed(1)} ${meta.unit}`,
          },
        },
      },
      scales: {
        x: {
          grid: { color: '#F0EEE9' },
          ticks: { maxTicksLimit: 8, font: { size: 9 } },
        },
        y: {
          grid: { color: '#F0EEE9' },
          ticks: { font: { size: 9 } },
          title: { display: true, text: meta.unit, color: meta.color, font: { size: 9 } },
        },
      },
    },
  });
}

function setWeatherView(view, btn) {
  currentWeatherView = view;
  document.querySelectorAll('.wtab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  if (weatherBlocks.length) buildWeatherChart(weatherBlocks, view);
}

/* ══════════════════════════════════════════════════════════
   FEEDER MINI CHARTS
══════════════════════════════════════════════════════════ */
async function buildFeederCharts() {
  for (const feeder of ['F1', 'F2', 'F3']) {
    try {
      const res  = await fetch(`${API}/api/forecast?target=${feeder}`);
      const json = await res.json();
      if (!json.forecast) continue;

      const labels = json.forecast.map(b => fmtTime(b.timestamp));
      const data   = json.forecast.map(b => safe(b.forecast_mw));
      const color  = C[feeder];
      const canvas = document.getElementById(`fc-${feeder}`);
      const ctx    = canvas.getContext('2d');

      if (feederCharts[feeder]) feederCharts[feeder].destroy();
      feederCharts[feeder] = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            data, borderColor: color,
            backgroundColor: color + '15',
            fill: true, tension: 0.4,
            borderWidth: 1.5, pointRadius: 0,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          animation: { duration: 400 },
          plugins: { legend: { display: false }, tooltip: { ...TOOLTIP_OPTS,
            callbacks: { label: ctx2 => ` ${feeder}: ${ctx2.parsed.y?.toFixed(2)} MW` }
          }},
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 5, font: { size: 8 } } },
            y: { grid: { color: '#F0EEE9' }, ticks: { font: { size: 8 } } },
          },
        },
      });
    } catch (e) { console.warn(`Feeder ${feeder}:`, e); }
  }
}

/* ══════════════════════════════════════════════════════════
   HOLIDAY TABLE
══════════════════════════════════════════════════════════ */
function renderHolidayTable(data) {
  allHolidays = data;
  applyHolFilter(currentHolCat);
}

function applyHolFilter(cat) {
  const tbody    = document.getElementById('hol-tbody');
  const filtered = cat === 'all' ? allHolidays : allHolidays.filter(h => h.category === cat);

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="3" class="hol-loading">No ${cat} holidays in dataset</td></tr>`;
    return;
  }
  tbody.innerHTML = filtered.map(h => {
    const d      = new Date(h.date);
    const now    = new Date();
    const isNear = Math.abs(d - now) < 7 * 86400000;
    const row    = isNear ? 'style="background:#FFFBEB"' : '';
    return `<tr ${row}>
      <td class="hol-date-cell">${fmtShort(h.date)}</td>
      <td class="hol-name-cell">${h.name}</td>
      <td><span class="cat-badge cat-${h.category}">${h.category.replace('_',' ')}</span></td>
    </tr>`;
  }).join('');
}

function filterHols(cat, btn) {
  currentHolCat = cat;
  document.querySelectorAll('.hf').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyHolFilter(cat);
}

/* ══════════════════════════════════════════════════════════
   SUMMARY CARDS
══════════════════════════════════════════════════════════ */
function updateKPIs(s) {
  document.getElementById('val-peak').textContent   = s.peak_mw?.toFixed(1)   ?? '—';
  document.getElementById('val-valley').textContent = s.valley_mw?.toFixed(1) ?? '—';
  document.getElementById('val-avg').textContent    = s.avg_mw?.toFixed(1)    ?? '—';
  document.getElementById('val-energy').textContent = s.total_mwh?.toFixed(0) ?? '—';

  const w = s.weather_summary ?? {};
  document.getElementById('val-temp').textContent   = w.avg_temp_c?.toFixed(1) ?? '—';

  document.getElementById('ws-temp').textContent   = w.avg_temp_c?.toFixed(1)      ?? '—';
  document.getElementById('ws-hum').textContent    = w.avg_humidity_pct?.toFixed(0) ?? '—';
  document.getElementById('ws-cloud').textContent  = w.avg_cloud_pct?.toFixed(0)    ?? '—';

  if (s.next_holiday) {
    document.getElementById('meta-nextholiday').textContent =
      `${s.next_holiday.name} · ${s.next_holiday.date}`;
  }
}

/* ══════════════════════════════════════════════════════════
   TARGET SWITCH
══════════════════════════════════════════════════════════ */
async function setTarget(target, btn) {
  currentTarget = target;
  document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  document.getElementById('chart-loader').classList.remove('hidden');
  try {
    const res  = await fetch(`${API}/api/forecast?target=${target}`);
    const json = await res.json();
    if (json.forecast) buildForecastChart(json.forecast, json.holidays_in_window ?? []);
  } catch (e) { console.error(e); }
  document.getElementById('chart-loader').classList.add('hidden');
}

/* ══════════════════════════════════════════════════════════
   MAIN LOADER
══════════════════════════════════════════════════════════ */
async function loadAll() {
  document.getElementById('chart-loader').classList.remove('hidden');
  setStatus('Fetching summary…');

  try {
    /* 1 — Summary */
    const sumRes = await fetch(`${API}/api/forecast/summary`);
    const sum    = await sumRes.json();
    updateKPIs(sum);

    /* 2 — Forecast (system total) */
    setStatus('Generating 24-hour forecast…');
    const fcRes  = await fetch(`${API}/api/forecast?target=${currentTarget}`);
    const fcJson = await fcRes.json();

    if (fcJson.forecast) {
      const win = fcJson.forecast_window;
      document.getElementById('forecast-window').textContent =
        `${new Date(win.start).toLocaleString('en-IN',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Kolkata'})} → ${new Date(win.end).toLocaleString('en-IN',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Kolkata'})} IST`;

      const mi = fcJson.model_info ?? {};
      document.getElementById('model-tag').textContent =
        `LightGBM · ${mi.n_features ?? 7} features · MAPE ${mi.holdout_mape_pct ?? '~1.94'} %`;
      document.getElementById('meta-variant').textContent =
        `LightGBM · ${mi.variant ?? 'selected'} variant`;
      document.getElementById('meta-features').textContent =
        `${mi.n_features ?? 7} calendar inputs`;
      if (mi.holdout_mape_pct)
        document.getElementById('meta-mape').textContent = mi.holdout_mape_pct + ' %';

      buildForecastChart(fcJson.forecast, fcJson.holidays_in_window ?? []);
    }

    /* 3 — Weather */
    setStatus('Fetching weather from Open-Meteo…');
    const wRes  = await fetch(`${API}/api/weather`);
    const wJson = await wRes.json();
    if (wJson.blocks) {
      weatherBlocks = wJson.blocks;
      buildWeatherChart(wJson.blocks, currentWeatherView);

      /* avg wind for the wstat */
      const winds = wJson.blocks.map(b => b.wind).filter(v => v != null);
      const avgWind = winds.reduce((a,b) => a+b, 0) / (winds.length || 1);
      document.getElementById('ws-wind').textContent = avgWind.toFixed(1);
    }

    /* 4 — Holidays */
    setStatus('Loading holiday calendar…');
    const hRes  = await fetch(`${API}/api/holidays/all`);
    const hJson = await hRes.json();
    renderHolidayTable(hJson.holidays ?? []);

    /* 5 — Feeders */
    setStatus('Building feeder charts…');
    await buildFeederCharts();

    document.getElementById('chart-loader').classList.add('hidden');
    setStatus(`Updated ${new Date().toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata'})}`, true);

  } catch (err) {
    document.getElementById('chart-loader').classList.add('hidden');
    setStatus(`⚠ ${err.message} — is the backend running on :8000?`);
    console.error(err);
  }
}

/* ── Boot ────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  startClock();
  loadAll();
  setInterval(loadAll, 5 * 60 * 1000); // auto-refresh every 5 min
});
