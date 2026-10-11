# APU Power Demand Forecasting

> **Intelligent 24-hour electricity demand forecasting for Apex Power & Utilities (APU), Dhanbad, Jharkhand.**
> Built as a full-stack prototype for the Exascale Deeptech & AI Data Developer Intern assignment.

---

## Project Overview

This system forecasts electricity demand in **48 half-hour blocks (24 hours)** for the APU grid using:

- **LightGBM** ratio model (predicts `load(t) / load(t-24h)`)
- **Calendar features** (time of day, day of week, cyclic encodings)
- **Real-time weather** from the Open-Meteo API (temperature, humidity, cloud cover, wind)
- **Localized Dhanbad holiday calendar** (festivals, national, tribal, industrial, religious minority)
- **Historical load data** from `Utility_consumption.csv` (cleaned & resampled to 30-min blocks)

**Hold-out MAPE (Oct–Dec 2017): ~1.94%** vs. 3.27% for naïve "same as yesterday" baseline.

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                         Docker                             │
│                                                            │
│  ┌─────────────────┐        ┌──────────────────────────┐   │
│  │  FastAPI Backend │        │  Frontend (HTML/CSS/JS)  │   │
│  │  :8000           │◄──────►│  Nginx :3000 / :80       │   │
│  │                  │        │                          │   │
│  │  /api/forecast   │        │  Chart.js Dashboard       │   │
│  │  /api/weather    │        │  • 24h Forecast Chart     │   │
│  │  /api/holidays   │        │  • Weather Panel          │   │
│  │  /api/metadata   │        │  • Holiday Calendar       │   │
│  │  /health         │        │  • Feeder Breakdown       │   │
│  └──────┬───────────┘        └──────────────────────────┘   │
│         │                                                   │
│  ┌──────▼───────────────────────────────────────────────┐   │
│  │                  models/                             │   │
│  │  load_forecaster.joblib    (calendar-only LightGBM)  │   │
│  │  load_forecaster_full.joblib (+ weather/holiday)     │   │
│  │  forecast_utils.py                                   │   │
│  │  holidays_dhanbad.csv                                │   │
│  │  recent_history.csv        (9-day 30-min history)    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                            │
│  External: Open-Meteo API (free, no key required)          │
└────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Option A — Docker Compose (recommended)

```bash
# 1. Clone / extract the project
cd power-demand-forecasting

# 2. Build and start all services
docker compose up --build

# 3. Open your browser
#    Dashboard:  http://localhost:3000
#    API docs:   http://localhost:8000/docs
```

### Option B — Run locally without Docker

#### Backend

```bash
cd backend
pip install -r requirements.txt

# Start the API server
uvicorn main:app --reload --port 8000
```

#### Frontend

The frontend is plain HTML/CSS/JS – just serve it with any static server:

```bash
# Option 1: Python
cd frontend
python -m http.server 3000

# Option 2: VS Code Live Server (open index.html → Go Live)

# Option 3: npx serve
npx serve frontend -p 3000
```

Then open `http://localhost:3000` in your browser.

> **Note:** Make sure the backend is running on port 8000 before opening the frontend.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/forecast?target=load` | 48-block 24h forecast (load\|F1\|F2\|F3) |
| GET | `/api/forecast/summary` | Dashboard summary cards |
| GET | `/api/weather` | 48-block weather forecast (Open-Meteo) |
| GET | `/api/holidays?days_ahead=30` | Upcoming Dhanbad holidays |
| GET | `/api/holidays/all` | Full holiday dataset |
| GET | `/api/metadata` | Model metadata & training info |

**Interactive API docs:** `http://localhost:8000/docs`

### Sample response – `/api/forecast`

```json
{
  "target": "load",
  "generated_at": "2026-10-10T23:00:00",
  "blocks": 48,
  "forecast_window": { "start": "...", "end": "..." },
  "model_info": { "variant": "selected", "n_features": 7, "holdout_mape_pct": 1.94 },
  "forecast": [
    {
      "timestamp": "2026-10-11T00:00:00",
      "block": 0,
      "forecast_mw": 52.3,
      "forecast_kwh": 52300.0,
      "temp": 24.1, "hum": 68.0, "cloud": 15.0, "wind": 8.2
    },
    ...
  ],
  "holidays_in_window": []
}
```

---

## Dashboard Features

| Feature | Description |
|---------|-------------|
| **24h Forecast Chart** | Interactive line chart with temperature overlay & holiday annotations |
| **Feeder Switch** | Toggle between System Total, F1, F2, F3 132 KV feeders |
| **Weather Panel** | Temperature, humidity, cloud cover chart + summary cards |
| **Holiday Calendar** | Filterable list of Dhanbad-localized holidays by category |
| **Feeder Breakdown** | Individual mini-charts for each 132 KV feeder |
| **Summary Cards** | Peak, valley, average, total energy, temperature, next holiday |
| **Live Clock** | Real-time IST clock in the navbar |
| **Auto-refresh** | Data refreshes every 5 minutes automatically |

---

## Model Details

### Architecture
- **Type:** LightGBM Regressor (ratio target)
- **Target:** `load(t) / load(t-24h)` — predicts the *change* from yesterday
- **Final prediction:** `predicted_ratio × load(t-24h)`
- **Variant:** Calendar-only (7 features) — best on hold-out, avoids noise from 1-year data

### Feature Groups
| Group | Features |
|-------|----------|
| Calendar | block, dow, is_weekend, blk_sin, blk_cos, dow_sin, dow_cos |
| Weather (full model) | temp, hum, wind, cloud, temp_d24, hum_d24, temp_d168, cdd, hdd… |
| Holiday (full model) | is_hol, hol_festival, hol_national, days_to_hol, big_festival… |
| Lag ratios (full model) | r96, r336, rmean7, rday, rmax, rstd7 |

### Performance (Oct–Dec 2017 hold-out)
| Model | MAPE% |
|-------|-------|
| Naïve (same as yesterday) | 3.27% |
| Ridge regression | 2.63% |
| **LightGBM calendar-only** | **1.94%** |
| LightGBM + weather + holiday | 1.99% |

---

## Data Sources

| Source | Details |
|--------|---------|
| **Load data** | `Utility_consumption.csv` — 10-min readings, resampled to 30-min |
| **Weather** | Open-Meteo API — `api.open-meteo.com` (no API key required) |
| **Holidays** | Hand-curated list of Dhanbad, Jharkhand holidays (national, festival, tribal, industrial, religious minority) |

### Holiday Categories
- **National** — Republic Day, Independence Day, Gandhi Jayanti
- **Festival** — Diwali, Chhath Puja, Durga Puja, Holi, Dussehra
- **Tribal** — Sarhul, Hul Diwas, Karma Puja, Sohrai, Jharkhand Foundation Day
- **Industrial** — Vishwakarma Puja, Labour Day (key for Dhanbad mining/industrial sector)
- **Religious minority** — Eid, Christmas, Good Friday, Buddha Purnima

---

## Project Structure

```
power-demand-forecasting/
├── backend/
│   ├── main.py                   # FastAPI application
│   ├── requirements.txt
│   └── models/
│       ├── forecast_utils.py     # Model inference utilities (from notebook)
│       ├── load_forecaster.joblib          # Calendar-only LightGBM model
│       ├── load_forecaster_full.joblib     # Full model (weather + holiday)
│       ├── holidays_dhanbad.csv            # Localized holiday data
│       └── recent_history.csv             # 9-day 30-min history (2017 sample)
├── frontend/
│   ├── index.html               # Dashboard SPA
│   ├── style.css                # Premium dark theme
│   └── app.js                   # Chart.js + API integration
├── Dockerfile                   # Backend container
├── docker-compose.yml           # Full-stack orchestration
├── nginx.conf                   # Nginx frontend + API proxy
└── README.md
```

---

## Environment & Dependencies

### Backend (Python 3.11)
- `fastapi` 0.115 — REST API framework
- `uvicorn` — ASGI server
- `lightgbm` 4.5 — gradient boosting model
- `pandas`, `numpy` — data manipulation
- `joblib` — model serialization
- `requests` — Open-Meteo weather API

### Frontend
- `Chart.js` 4.4 — interactive charts
- `chartjs-plugin-annotation` — holiday annotations on chart
- Google Fonts (Inter, Space Grotesk)
- Vanilla HTML5 / CSS3 / JS (no framework needed)


