"""
main.py – FastAPI backend for APU Power Demand Forecasting
Endpoints:
  GET /api/forecast         → 48 half-hour blocks for the next 24 h
  GET /api/weather          → weather forecast for the next 24 h
  GET /api/holidays         → upcoming holidays for Dhanbad, Jharkhand
  GET /api/metadata         → model metadata
  GET /health               → health check
"""

import sys
import json
import datetime as dt
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import requests as http_requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ── paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "models"
sys.path.insert(0, str(MODELS_DIR))

import forecast_utils as fu  # noqa: E402 – after sys.path patch

# ── config ─────────────────────────────────────────────────────────────────────
LAT, LON = 23.80, 86.43          # Dhanbad, Jharkhand
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
HISTORY_FALLBACK_CSV = MODELS_DIR / "recent_history.csv"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ── module-level state (populated at startup) ──────────────────────────────────
_bundle: dict = {}
_holidays: pd.DataFrame = pd.DataFrame()
_history: pd.DataFrame = pd.DataFrame()


# ── helpers defined early so lifespan can call them ────────────────────────────

def _load_history() -> pd.DataFrame:
    """Load recent 30-min history from CSV (fallback when live data is unavailable)."""
    try:
        df = pd.read_csv(str(HISTORY_FALLBACK_CSV), parse_dates=["ts"], index_col="ts")
        rename = {}
        for col in df.columns:
            if "F1" in col:
                rename[col] = "F1"
            elif "F2" in col:
                rename[col] = "F2"
            elif "F3" in col:
                rename[col] = "F3"
        if rename:
            df = df.rename(columns=rename)
        if "load" not in df.columns and all(c in df.columns for c in ["F1", "F2", "F3"]):
            df["load"] = df["F1"] + df["F2"] + df["F3"]
        df.index.name = "ts"
        df = df.sort_index()
        return df
    except Exception as e:
        log.warning("Could not load history CSV: %s", e)
        return pd.DataFrame()


def _shift_history_to_now(hist: pd.DataFrame) -> pd.DataFrame:
    """
    Shift the stored 2017 history forward so its last timestamp aligns with
    the most recent completed 30-min block in the current wall-clock time.

    This is required because the model needs lag features (load 24h ago,
    48h ago, etc.) anchored to *current* time, but the reference CSV only
    covers Dec 2017.
    """
    if hist.empty:
        return hist
    # Round now down to the most recent complete 30-min boundary
    now = pd.Timestamp.now().floor("30min") - pd.Timedelta("30min")
    offset = now - hist.index[-1]
    hist_shifted = hist.copy()
    hist_shifted.index = hist.index + offset
    return hist_shifted


# ── lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app_):
    global _bundle, _holidays, _history

    # ── startup ──
    try:
        _bundle = fu.load_bundle(str(MODELS_DIR / "load_forecaster.joblib"))
        log.info("Model loaded: variant=%s, features=%d", _bundle.get("variant"), len(_bundle.get("features", [])))
    except Exception as e:
        log.error("Failed to load model: %s", e)
        raise RuntimeError(f"Cannot start without model: {e}")

    try:
        _holidays = fu.load_holidays(str(MODELS_DIR / "holidays_dhanbad.csv"))
        log.info("Holidays loaded: %d entries", len(_holidays))
    except Exception as e:
        log.error("Failed to load holidays: %s", e)

    _history = _load_history()
    log.info("History loaded: %d rows, last=%s", len(_history), _history.index[-1] if len(_history) else "N/A")

    yield  # app runs here

    # ── shutdown (nothing to clean up) ──


# ── application ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="APU Power Demand Forecasting API",
    description="Intelligent 24-hour electricity demand forecasting for Dhanbad, Jharkhand",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── weather helpers ────────────────────────────────────────────────────────────

def _fetch_open_meteo_forecast() -> pd.DataFrame:
    """
    Fetch 48-block (24 h) weather forecast from Open-Meteo for Dhanbad.
    Returns DataFrame with columns [temp, hum, cloud, wind], 48 rows.
    """
    params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": "temperature_2m,relativehumidity_2m,cloudcover,windspeed_10m",
        "forecast_days": 2,
        "timezone": "Asia/Kolkata",
    }
    try:
        resp = http_requests.get(OPEN_METEO_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        hourly = data["hourly"]
        df_h = pd.DataFrame({
            "ts": pd.to_datetime(hourly["time"]),
            "temp": hourly["temperature_2m"],
            "hum": hourly["relativehumidity_2m"],
            "cloud": hourly["cloudcover"],
            "wind": hourly["windspeed_10m"],
        }).set_index("ts")

        # Resample hourly → 30-min
        df_30 = df_h.resample("30min").ffill()

        # 48 rows starting from the next 30-min boundary
        now_ist = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
        mins = now_ist.minute
        if mins < 30:
            start = now_ist.replace(minute=30, second=0, microsecond=0)
        else:
            start = (now_ist + pd.Timedelta("1h")).replace(minute=0, second=0, microsecond=0)

        idx_48 = pd.date_range(start, periods=48, freq="30min")
        df_out = df_30.reindex(idx_48, method="nearest", tolerance="30min").ffill().bfill()
        df_out.index.name = "ts"
        return df_out[["temp", "hum", "cloud", "wind"]]

    except Exception as e:
        log.warning("Open-Meteo fetch failed (%s); using seasonal fallback.", e)
        return _seasonal_weather_fallback(48)


def _seasonal_weather_fallback(n: int = 48) -> pd.DataFrame:
    """Plausible October weather for Dhanbad when the API is unavailable."""
    now = pd.Timestamp.now()
    mins = now.minute
    if mins < 30:
        start = now.replace(minute=30, second=0, microsecond=0)
    else:
        start = (now + pd.Timedelta("1h")).replace(minute=0, second=0, microsecond=0)
    idx = pd.date_range(start, periods=n, freq="30min")
    hours = np.array([t.hour + t.minute / 60 for t in idx])
    rng = np.random.default_rng(42)
    temp  = 26 + 5 * np.sin(np.pi * (hours - 6) / 12) + rng.normal(0, 0.5, n)
    hum   = 65 - 10 * np.sin(np.pi * (hours - 6) / 12) + rng.normal(0, 2, n)
    cloud = np.clip(20 + 10 * rng.standard_normal(n), 0, 100)
    wind  = np.clip(8 + 3 * rng.standard_normal(n), 0, 30)
    return pd.DataFrame({"temp": temp, "hum": hum, "cloud": cloud, "wind": wind}, index=idx)


def _build_history_with_weather(weather_df: pd.DataFrame) -> pd.DataFrame:
    """Return time-shifted history with weather columns filled in."""
    hist = _shift_history_to_now(_history)
    for col in ["temp", "hum", "cloud", "wind"]:
        if col not in hist.columns:
            hist[col] = np.nan
    return hist


# ─── routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "model_variant": _bundle.get("variant", "unknown")}


@app.get("/api/metadata")
def metadata():
    safe = {k: v for k, v in _bundle.items() if k not in ("models",)}
    def _serialize(obj):
        if isinstance(obj, np.integer):  return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.ndarray):  return obj.tolist()
        return str(obj)
    return JSONResponse(content=json.loads(json.dumps(safe, default=_serialize)))


@app.get("/api/weather")
def get_weather():
    """
    Return 48 half-hour weather forecast blocks for Dhanbad.
    Includes temp (°C), humidity (%), cloud cover (%), wind speed (km/h).
    """
    try:
        weather = _fetch_open_meteo_forecast()
        records = [
            {
                "timestamp": ts.isoformat(),
                "temp":  round(float(row["temp"]),  1),
                "hum":   round(float(row["hum"]),   1),
                "cloud": round(float(row["cloud"]), 1),
                "wind":  round(float(row["wind"]),  1),
            }
            for ts, row in weather.iterrows()
        ]
        return {"source": "open-meteo", "location": "Dhanbad, Jharkhand", "blocks": records}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/holidays")
def get_holidays(days_ahead: int = Query(default=30, ge=1, le=365)):
    """Return upcoming Dhanbad-localized holidays for the next `days_ahead` days."""
    today = pd.Timestamp.now().normalize()
    end   = today + pd.Timedelta(days=days_ahead)
    mask  = (_holidays["date"] >= today) & (_holidays["date"] <= end)
    subset = _holidays[mask].copy()
    subset["date"] = subset["date"].dt.strftime("%Y-%m-%d")
    return {
        "location": "Dhanbad, Jharkhand",
        "days_ahead": days_ahead,
        "count": len(subset),
        "holidays": subset.to_dict(orient="records"),
    }


@app.get("/api/holidays/all")
def get_all_holidays():
    """Return the full holiday dataset."""
    df = _holidays.copy()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return {"holidays": df.to_dict(orient="records")}


@app.get("/api/forecast")
def get_forecast(target: str = Query(default="load", pattern="^(load|F1|F2|F3)$")):
    """
    Generate a 24-hour (48 block) forecast.
    target: 'load' (system total) | 'F1' | 'F2' | 'F3'
    """
    if len(_history) == 0:
        raise HTTPException(status_code=503, detail="No history data available.")

    # 1. Weather
    weather = _fetch_open_meteo_forecast()

    # 2. History with weather columns
    hist = _build_history_with_weather(weather)

    # 3. Run model
    try:
        fc = fu.forecast_next_24h(_bundle, hist, weather, _holidays, target=target)
    except Exception as e:
        log.error("Forecast failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Forecast error: {e}")

    # 4. Align weather to forecast index
    weather_aligned = weather.reindex(fc.index, method="nearest", tolerance=pd.Timedelta("30min"))

    # 5. Build response records (sanitize NaN / Inf to None for JSON compliance)
    def _safe(v):
        """Return float or None; guards against NaN/Inf from model."""
        if v is None:
            return None
        try:
            f = float(v)
            return None if (f != f or f == float("inf") or f == float("-inf")) else f
        except (TypeError, ValueError):
            return None

    forecast_records = []
    for ts in fc.index:
        w_ok = ts in weather_aligned.index
        raw_mw = _safe(fc.loc[ts, "forecast"])
        forecast_records.append({
            "timestamp":    ts.isoformat(),
            "block":        int(ts.hour * 2 + ts.minute // 30),
            "forecast_mw":  round(raw_mw / 1000, 3) if raw_mw is not None else None,
            "forecast_kwh": round(raw_mw, 1) if raw_mw is not None else None,
            "temp":  _safe(weather_aligned.loc[ts, "temp"])  if w_ok else None,
            "hum":   _safe(weather_aligned.loc[ts, "hum"])   if w_ok else None,
            "cloud": _safe(weather_aligned.loc[ts, "cloud"]) if w_ok else None,
            "wind":  _safe(weather_aligned.loc[ts, "wind"])  if w_ok else None,
        })

    # 6. Holidays in forecast window
    start_date = fc.index[0].normalize()
    end_date   = fc.index[-1].normalize()
    hol_mask   = (_holidays["date"] >= start_date) & (_holidays["date"] <= end_date)
    hols_in_window = _holidays[hol_mask].copy()
    hols_in_window["date"] = hols_in_window["date"].dt.strftime("%Y-%m-%d")

    payload = {
        "target": target,
        "generated_at": dt.datetime.now().isoformat(),
        "blocks": 48,
        "forecast_window": {
            "start": fc.index[0].isoformat(),
            "end":   fc.index[-1].isoformat(),
        },
        "model_info": {
            "variant":          _bundle.get("variant"),
            "n_features":       len(_bundle.get("features", [])),
            "holdout_mape_pct": _bundle.get("holdout_MAPE_percent_selected_total"),
        },
        "forecast": forecast_records,
        "holidays_in_window": hols_in_window.to_dict(orient="records"),
    }
    # Use a NaN-safe serializer to avoid JSON encode errors
    import math

    def _nan_safe(obj):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, np.floating):
            v = float(obj)
            return None if (math.isnan(v) or math.isinf(v)) else v
        if isinstance(obj, np.integer):
            return int(obj)
        raise TypeError(f"Object of type {type(obj)} not JSON serializable")

    return JSONResponse(content=json.loads(json.dumps(payload, default=_nan_safe)))


@app.get("/api/forecast/summary")
def get_forecast_summary():
    """
    Lightweight summary: peak, valley, avg demand, total energy,
    weather summary, next holiday – for dashboard header cards.
    """
    if len(_history) == 0:
        raise HTTPException(status_code=503, detail="No history available.")

    weather = _fetch_open_meteo_forecast()
    hist    = _build_history_with_weather(weather)

    try:
        fc = fu.forecast_next_24h(_bundle, hist, weather, _holidays, target="load")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    vals      = fc["forecast"].values / 1000  # → approximate MW
    avg_temp  = float(weather["temp"].mean())
    avg_hum   = float(weather["hum"].mean())
    avg_cloud = float(weather["cloud"].mean())

    today    = pd.Timestamp.now().normalize()
    hol_mask = (_holidays["date"] >= today) & (_holidays["date"] <= today + pd.Timedelta(days=1))
    upcoming = _holidays[_holidays["date"] >= today]
    next_hol = upcoming.iloc[0] if len(upcoming) else None

    return {
        "peak_mw":    round(float(vals.max()),  2),
        "valley_mw":  round(float(vals.min()),  2),
        "avg_mw":     round(float(vals.mean()), 2),
        "total_mwh":  round(float(vals.sum() * 0.5), 2),
        "weather_summary": {
            "avg_temp_c":      round(avg_temp,  1),
            "avg_humidity_pct": round(avg_hum,  1),
            "avg_cloud_pct":   round(avg_cloud, 1),
        },
        "next_holiday": {
            "name":     str(next_hol["name"]),
            "date":     str(next_hol["date"].strftime("%Y-%m-%d")),
            "category": str(next_hol["category"]),
        } if next_hol is not None else None,
        "is_holiday_today": bool(len(_holidays[hol_mask]) > 0),
        "generated_at": dt.datetime.now().isoformat(),
    }
