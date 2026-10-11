"""forecast_utils.py: everything the backend needs to turn the saved model into a 24-hour forecast."""
import joblib
import numpy as np
import pandas as pd

WEATHER_COLS = ['temp', 'hum', 'cloud', 'wind']
LOAD_COLS = ['F1', 'F2', 'F3', 'load']


def holiday_frame(index, hol):
    # Per-day holiday features for any DatetimeIndex (reused at serving time).
    days = pd.DatetimeIndex(index.normalize().unique())
    hd = hol.groupby('date').category.agg(set)
    f = pd.DataFrame(index=days)
    f['is_hol'] = f.index.isin(hd.index).astype(int)
    for cat in ['national', 'festival', 'tribal', 'industrial', 'religious_minority']:
        f['hol_' + cat] = [int(d in hd.index and cat in hd[d]) for d in f.index]
    hd_days = np.sort(hol.date.unique()).astype('datetime64[D]')
    dd = f.index.values.astype('datetime64[D]')
    to_, since_ = [], []
    for d in dd:
        fut = hd_days[hd_days >= d]; past = hd_days[hd_days <= d]
        to_.append(min(int((fut[0] - d).astype(int)), 7) if len(fut) else 7)
        since_.append(min(int((d - past[-1]).astype(int)), 7) if len(past) else 7)
    f['days_to_hol'] = to_; f['days_since_hol'] = since_
    big = hol[hol['name'].str.contains('Diwali|Durga|Chhath|Holi|Dussehra|Vijayadashami')].date.values.astype('datetime64[D]')
    f['big_festival'] = [int(np.any(np.abs((big - d).astype(int)) <= 1)) for d in dd]
    return f


def build_features(d, hf, target='load', use_cloud=True):
    X = pd.DataFrame(index=d.index)
    blk_ = d.index.hour * 2 + d.index.minute // 30
    X['block'] = blk_; X['dow'] = d.index.dayofweek; X['is_weekend'] = (X.dow >= 5).astype(int)
    X['blk_sin'] = np.sin(2 * np.pi * blk_ / 48); X['blk_cos'] = np.cos(2 * np.pi * blk_ / 48)
    X['dow_sin'] = np.sin(2 * np.pi * X.dow / 7); X['dow_cos'] = np.cos(2 * np.pi * X.dow / 7)
    # weather (known for the target time from a forecast)
    X['temp'] = d.temp; X['hum'] = d.hum; X['wind'] = d.wind
    if use_cloud and 'cloud' in d and d.cloud.notna().any(): X['cloud'] = d.cloud
    X['temp_roll24'] = d.temp.rolling(48, min_periods=1).mean()
    X['temp_d24'] = d.temp - d.temp.shift(48); X['hum_d24'] = d.hum - d.hum.shift(48); X['wind_d24'] = d.wind - d.wind.shift(48)
    X['temp_d168'] = d.temp - d.temp.shift(336)
    X['cdd'] = (d.temp - 24).clip(lower=0); X['hdd'] = (18 - d.temp).clip(lower=0); X['temp_x_hum'] = d.temp * d.hum / 100
    # holidays (daily -> block)
    h = hf.reindex(d.index.normalize()).set_index(d.index)
    for c in h: X[c] = h[c].values
    X['hol_lag48'] = X['is_hol'].shift(48); X['hol_lag336'] = X['is_hol'].shift(336)
    # load lags, all >= 24 h
    y = d[target]
    X['lag48'] = y.shift(48); X['lag96'] = y.shift(96); X['lag336'] = y.shift(336)
    stack = pd.concat([y.shift(48 * k) for k in range(1, 8)], axis=1)
    X['same_blk_mean7d'] = stack.mean(axis=1, skipna=False); X['same_blk_std7d'] = stack.std(axis=1, skipna=False)
    X['prev_day_mean'] = y.shift(48).rolling(48).mean(); X['prev_day_max'] = y.shift(48).rolling(48).max()
    # scale-free versions of the lags (what the final model actually uses)
    X['r96'] = X.lag96 / X.lag48; X['r336'] = X.lag336 / X.lag48; X['rmean7'] = X.same_blk_mean7d / X.lag48
    X['rday'] = X.prev_day_mean / X.lag48; X['rmax'] = X.prev_day_max / X.lag48; X['rstd7'] = X.same_blk_std7d / X.same_blk_mean7d
    return X


def load_bundle(path='models/load_forecaster.joblib'):
    """Load the saved model bundle (models for load, F1, F2, F3 + the feature list)."""
    return joblib.load(path)


def load_holidays(path='models/holidays_dhanbad.csv'):
    h = pd.read_csv(path, parse_dates=['date'])
    return h


def forecast_next_24h(bundle, history, future_weather, holidays, target='load'):
    """Forecast the next 48 half-hour blocks (24 h).

    history        : DataFrame, 30-min index, columns F1, F2, F3, load (+ temp, hum, cloud, wind if the
                     bundle uses weather). Must contain at least the last 8 days and end at the last
                     observed block.
    future_weather : DataFrame with 48 rows (the next 24 h, 30-min steps), columns temp, hum, cloud, wind.
                     Ignored by the default (calendar-only) model, needed by the full model.
    holidays       : DataFrame from load_holidays().
    target         : 'load' (system total), 'F1', 'F2' or 'F3'.
    Returns a DataFrame with a 'forecast' column indexed by the 48 future timestamps.
    """
    history = history.sort_index()
    idx = pd.date_range(history.index[-1] + pd.Timedelta('30min'), periods=48, freq='30min')
    if len(future_weather) != 48:
        raise ValueError('future_weather must have exactly 48 rows (next 24 h at 30-min steps)')
    fw = future_weather.copy(); fw.index = idx
    fw = fw.reindex(columns=WEATHER_COLS)
    hist = history.reindex(columns=LOAD_COLS + WEATHER_COLS)
    frame = pd.concat([hist, pd.concat([pd.DataFrame(np.nan, index=idx, columns=LOAD_COLS), fw], axis=1)])
    hf = holiday_frame(frame.index, holidays)
    X = build_features(frame, hf, target, use_cloud=bundle['use_cloud'])
    Xf = X.loc[idx]
    feats = bundle['features']
    if Xf[feats].isna().any().any():
        bad = Xf[feats].columns[Xf[feats].isna().any()].tolist()
        raise ValueError('Not enough history or weather to build these inputs: %s' % bad)
    ratio = bundle['models'][target].predict(Xf[feats])
    return pd.DataFrame({'forecast': ratio * Xf['lag48'].values}, index=idx)
