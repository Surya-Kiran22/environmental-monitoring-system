"""Pollution Anomaly & Trend model.

Method (justification in README §Anomaly detection):
  1. Isolation Forest (multivariate, unsupervised) per monitoring domain. Each station's readings are
     robust-standardised against its own history (median / IQR) so one model generalises across stations,
     then combined with first differences, time-of-day encoding and (air) wind/humidity context.
     It catches unusual pollutant *combinations* and abnormal station behaviour without labelled data.
  2. Robust z-score (median/MAD) per parameter — an interpretable univariate baseline that also supplies
     the "top contributing parameters" for explanations.
  3. Theil–Sen slope + Spearman test over 72 h for gradual deterioration.
The model is trained on history older than 48 h so the current event is never part of its own baseline.
Evaluation uses injected ground-truth labels in the synthetic dataset (precision / recall / F1 vs. baseline).
"""
from __future__ import annotations

import json
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import IsolationForest

from ..config import DATA_DIR, MODEL_DIR

FEATURES = {"air": ["pm2_5", "pm10", "no2", "so2", "co", "o3"],
            "water": ["ph", "dissolved_oxygen", "turbidity", "conductivity", "tds", "water_temperature"],
            "noise": ["noise_laeq"]}
CONTAMINATION = 0.03
_MODELS: dict = {}


def robust_stats(wide: pd.DataFrame, cols: list[str]) -> dict:
    out = {}
    for c in cols:
        s = wide[c].dropna() if c in wide else pd.Series(dtype=float)
        med = float(s.median()) if len(s) else 0.0
        iqr = float(s.quantile(0.75) - s.quantile(0.25)) if len(s) else 1.0
        mad = float((s - med).abs().median() * 1.4826) if len(s) else 1.0
        out[c] = {"median": med, "iqr": iqr or 1.0, "mad": mad or 1.0}
    return out


def featurize(wide: pd.DataFrame, domain: str, st: dict, weather: pd.DataFrame | None = None) -> pd.DataFrame:
    cols = FEATURES[domain]
    X = pd.DataFrame(index=wide.index)
    for c in cols:
        v = wide[c] if c in wide else pd.Series(np.nan, index=wide.index)
        z = (v - st[c]["median"]) / st[c]["iqr"]
        X[f"z_{c}"] = z
        X[f"d_{c}"] = z.diff()
    h = wide.index.hour
    X["hour_sin"], X["hour_cos"] = np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)
    if domain == "noise":
        X["is_night"] = ((h >= 22) | (h < 6)).astype(float)
    if domain == "air" and weather is not None and not weather.empty:
        w = weather.reindex(wide.index)
        X["wind_speed"] = w["wind_speed"].values
        X["humidity"] = w["humidity"].values / 100
    return X.ffill(limit=2).fillna(0.0)


def fit_domain(series_by_station: dict[str, pd.DataFrame], domain: str, weather=None) -> dict:
    stats_by_station, frames = {}, []
    for sid, wide in series_by_station.items():
        st = robust_stats(wide, FEATURES[domain])
        stats_by_station[sid] = st
        frames.append(featurize(wide, domain, st, weather))
    X = pd.concat(frames)
    model = IsolationForest(n_estimators=200, contamination=CONTAMINATION, random_state=42).fit(X.values)
    train_scores = -model.score_samples(X.values)
    return {"model": model, "stats": stats_by_station, "columns": list(X.columns), "train_scores": np.sort(train_scores),
            "threshold": float(np.quantile(train_scores, 1 - CONTAMINATION)), "n_train": len(X)}


def score(bundle: dict, wide: pd.DataFrame, domain: str, station_id: str, weather=None) -> pd.DataFrame:
    st = bundle["stats"].get(station_id) or robust_stats(wide, FEATURES[domain])
    X = featurize(wide, domain, st, weather)[bundle["columns"]]
    raw = -bundle["model"].score_samples(X.values)
    pct = np.searchsorted(bundle["train_scores"], raw) / len(bundle["train_scores"])
    out = pd.DataFrame({"raw": raw, "score": pct, "is_anomaly": raw >= bundle["threshold"]}, index=wide.index)
    zcols = [c for c in X.columns if c.startswith("z_")]
    out["top"] = [sorted(((c[2:], round(float(row[c]), 2)) for c in zcols), key=lambda t: -abs(t[1]))[:3] for _, row in X[zcols].iterrows()]
    return out


def robust_z(series: pd.Series, value: float, st: dict | None = None) -> float:
    s = series.dropna()
    if st is None:
        med, mad = float(s.median()), float((s - s.median()).abs().median() * 1.4826) or 1.0
    else:
        med, mad = st["median"], st["mad"]
    return (value - med) / (mad or 1.0)


def trend(series: pd.Series, hours: int = 72) -> dict:
    s = series.dropna()
    s = s[s.index > s.index.max() - timedelta(hours=hours)] if len(s) else s
    if len(s) < 12:
        return {"direction": "insufficient_data"}
    x = (s.index - s.index[0]).total_seconds() / 3600
    slope, intercept, lo, hi = stats.theilslopes(s.values, x)
    rho, p = stats.spearmanr(x, s.values)
    direction = "stable"
    if p < 0.05 and lo > 0:
        direction = "increasing"
    elif p < 0.05 and hi < 0:
        direction = "decreasing"
    return {"window_h": hours, "slope_per_h": round(float(slope), 4), "slope_ci": [round(float(lo), 4), round(float(hi), 4)],
            "spearman_rho": round(float(rho), 3), "p_value": round(float(p), 4), "direction": direction}


# ------------------------------------------------------------------ evaluation on the labelled dataset
def evaluate_on_dataset() -> dict:
    """Train on the first 20 days, test on the last 10 days of the CSV dataset with injected labels."""
    meas = pd.read_csv(DATA_DIR / "measurements.csv", parse_dates=["timestamp"])
    labels = pd.read_csv(DATA_DIR / "event_labels.csv", parse_dates=["timestamp"])
    wx = pd.read_csv(DATA_DIR / "weather.csv", parse_dates=["timestamp"]).set_index("timestamp")
    stations = pd.read_csv(DATA_DIR / "stations.csv")
    split = meas.timestamp.max() - pd.Timedelta(days=10)
    dom_map = {"air_quality": "air", "water_quality": "water", "noise": "noise"}
    results = {}
    for mt, domain in dom_map.items():
        sids = stations[stations.monitoring_type == mt].station_id.tolist()
        wides = {}
        for sid in sids:
            d = meas[meas.station_id == sid].drop_duplicates(["timestamp", "parameter"])
            wides[sid] = d.pivot(index="timestamp", columns="parameter", values="value").sort_index()
        train = {s: w[w.index < split] for s, w in wides.items()}
        bundle = fit_domain(train, domain, wx)
        y_true, y_if, y_z = [], [], []
        for sid, w in wides.items():
            test = w[w.index >= split]
            sc = score(bundle, test, domain, sid, wx)
            lab = set(labels[labels.station_id == sid].timestamp)
            st = bundle["stats"][sid]
            z = np.nanmax(np.abs(np.column_stack([(test[c] - st[c]["median"]) / st[c]["mad"] for c in FEATURES[domain] if c in test])), axis=1)
            y_true += [t in lab for t in test.index]
            y_if += list(sc.is_anomaly.values)
            y_z += list(np.nan_to_num(z) > 3.5)
        y_true, y_if, y_z = map(np.array, (y_true, y_if, y_z))

        def prf(pred):
            tp = int((pred & y_true).sum()); fp = int((pred & ~y_true).sum()); fn = int((~pred & y_true).sum())
            p = tp / (tp + fp) if tp + fp else 0.0; r = tp / (tp + fn) if tp + fn else 0.0
            return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
                    "tp": tp, "fp": fp, "fn": fn}
        results[domain] = {"isolation_forest": prf(y_if), "robust_zscore_baseline": prf(y_z),
                           "test_rows": int(len(y_true)), "labelled_events": int(y_true.sum()), "train_rows": bundle["n_train"],
                           "features": bundle["columns"]}
    out = {"algorithm": "IsolationForest(n_estimators=200, contamination=0.03) + robust z-score + Theil-Sen trend",
           "split": "train: first 20 days, test: last 10 days (chronological)", "domains": results}
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / "anomaly_metrics.json").write_text(json.dumps(out, indent=2))
    return out


def get_metrics() -> dict:
    f = MODEL_DIR / "anomaly_metrics.json"
    if "metrics" not in _MODELS:
        _MODELS["metrics"] = json.loads(f.read_text()) if f.exists() else evaluate_on_dataset()
    return _MODELS["metrics"]
