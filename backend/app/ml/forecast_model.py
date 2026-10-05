"""PM2.5 (or any parameter) forecasting with gradient-boosted trees on lag + weather + time features.

Model: HistGradientBoostingRegressor (handles missing values natively, fast on CPU, strong on tabular lags).
Features: lags 1,2,3,6,24 h; rolling means 6/24 h; temperature, humidity, wind speed; hour/day-of-week encodings.
Evaluation: chronological hold-out (last 5 days): one-step MAE/RMSE/MAPE plus recursive 24-h backtests,
compared with a persistence baseline (value 24 h earlier). Forecasts are produced recursively; future weather
comes from the live Open-Meteo hourly forecast when reachable, otherwise diurnal persistence (stated in output).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

LAGS = [1, 2, 3, 6, 24]
_CACHE: dict = {}


def _features(y: pd.Series, wx: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=y.index)
    for l in LAGS:
        X[f"lag_{l}"] = y.shift(l)
    X["roll_6"] = y.shift(1).rolling(6, min_periods=3).mean()
    X["roll_24"] = y.shift(1).rolling(24, min_periods=12).mean()
    w = wx.reindex(y.index)
    for c in ("temperature", "humidity", "wind_speed"):
        X[c] = w[c].values if c in w else np.nan
    X["hour_sin"], X["hour_cos"] = np.sin(2 * np.pi * y.index.hour / 24), np.cos(2 * np.pi * y.index.hour / 24)
    X["dow"] = y.index.dayofweek
    return X


def _metrics(y, p) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    m = ~np.isnan(y) & ~np.isnan(p)
    y, p = y[m], p[m]
    if not len(y):
        return {}
    err = p - y
    nz = y > 1e-6
    return {"mae": round(float(np.mean(np.abs(err))), 3), "rmse": round(float(np.sqrt(np.mean(err ** 2))), 3),
            "mape_pct": round(float(np.mean(np.abs(err[nz] / y[nz])) * 100), 2), "n": int(len(y))}


def _model():
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=0.1, random_state=42)


def _recursive(model, hist: pd.Series, wx: pd.DataFrame, steps: int) -> list[float]:
    y = hist.copy()
    preds = []
    for _ in range(steps):
        t = y.index[-1] + pd.Timedelta(hours=1)
        y.loc[t] = np.nan
        X = _features(y, wx).iloc[[-1]]
        v = float(max(model.predict(X.values)[0], 0))
        y.loc[t] = v
        preds.append(v)
    return preds


def train_and_forecast(y: pd.Series, wx: pd.DataFrame, horizon: int = 24, future_wx: pd.DataFrame | None = None,
                       cache_key: str | None = None) -> dict:
    y = y.asfreq("h")
    X = _features(y, wx)
    data = X.assign(target=y).dropna(subset=["target", "lag_1", "lag_24"])
    split = data.index.max() - pd.Timedelta(days=5)
    tr, te = data[data.index <= split], data[data.index > split]
    model = _model().fit(tr.drop(columns="target").values, tr.target.values)
    one_step = _metrics(te.target, model.predict(te.drop(columns="target").values))
    persistence = _metrics(te.target, te["lag_24"])
    # recursive 24-h backtests starting at each midnight of the test period
    errs_m, errs_p, horizon_resid = [], [], []
    for start in pd.date_range(split.ceil("D"), y.index.max() - pd.Timedelta(hours=24), freq="D"):
        hist = y[y.index < start].dropna()
        truth = y[(y.index >= start) & (y.index < start + pd.Timedelta(hours=24))]
        p = _recursive(model, y[y.index < start], wx, 24)
        errs_m.append(_metrics(truth.values, p)); errs_p.append(_metrics(truth.values, y.shift(24).reindex(truth.index).values))
        horizon_resid += list(np.asarray(truth.values) - np.asarray(p))
    def avg(lst, k):
        v = [e[k] for e in lst if e]
        return round(float(np.mean(v)), 3) if v else None
    backtest = {"windows": len(errs_m), "model_mae": avg(errs_m, "mae"), "model_rmse": avg(errs_m, "rmse"), "model_mape_pct": avg(errs_m, "mape_pct"),
                "persistence_mae": avg(errs_p, "mae"), "persistence_rmse": avg(errs_p, "rmse")}
    # refit on everything, forecast forward
    full = _model().fit(data.drop(columns="target").values, data.target.values)
    wx_ext = wx.copy()
    wx_source = "open-meteo hourly forecast"
    future_idx = pd.date_range(y.index.max() + pd.Timedelta(hours=1), periods=horizon, freq="h")
    if future_wx is None or future_wx.reindex(future_idx).dropna(how="all").empty:
        wx_source = "diurnal persistence (same hour previous day) - live forecast unavailable"
        fw = wx.reindex(future_idx - pd.Timedelta(hours=24))
        fw.index = future_idx
    else:
        fw = future_wx.reindex(future_idx).ffill()
    wx_ext = pd.concat([wx_ext[~wx_ext.index.isin(fw.index)], fw]).sort_index()
    preds = _recursive(full, y, wx_ext, horizon)
    sd = float(np.nanstd(horizon_resid)) if horizon_resid else float(one_step.get("rmse", 0))
    fc = [{"timestamp": t.isoformat(), "value": round(v, 2), "lower": round(max(v - 1.28 * sd, 0), 2), "upper": round(v + 1.28 * sd, 2)}
          for t, v in zip(future_idx, preds)]
    return {"model": "HistGradientBoostingRegressor (recursive multi-step)", "features": list(X.columns),
            "train_rows": int(len(tr)), "test_rows": int(len(te)), "split": f"chronological, test = last 5 days (after {split:%Y-%m-%d %H:%M})",
            "metrics_one_step": one_step, "persistence_baseline_one_step": persistence, "backtest_24h": backtest,
            "interval": "≈80 % band from 24-h backtest residual spread", "future_weather_source": wx_source, "forecast": fc}
