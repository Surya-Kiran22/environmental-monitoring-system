"""Deterministic data-validation & unit-normalisation tool used by the Intake & Validation Agent."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..config import STALE_AFTER_HOURS

CANONICAL_UNITS = {
    "pm2_5": "µg/m³", "pm10": "µg/m³", "no2": "µg/m³", "so2": "µg/m³", "o3": "µg/m³", "co": "mg/m³",
    "ph": "pH", "dissolved_oxygen": "mg/L", "turbidity": "NTU", "conductivity": "µS/cm", "tds": "mg/L",
    "water_temperature": "°C", "noise_laeq": "dB(A)",
}
LABELS = {
    "pm2_5": "PM2.5", "pm10": "PM10", "no2": "NO₂", "so2": "SO₂", "o3": "O₃", "co": "CO", "ph": "pH",
    "dissolved_oxygen": "Dissolved oxygen", "turbidity": "Turbidity", "conductivity": "Conductivity", "tds": "TDS",
    "water_temperature": "Water temperature", "noise_laeq": "Noise LAeq",
}
DOMAIN_OF = {**{p: "air" for p in ("pm2_5", "pm10", "no2", "so2", "o3", "co")},
             **{p: "water" for p in ("ph", "dissolved_oxygen", "turbidity", "conductivity", "tds", "water_temperature")},
             "noise_laeq": "noise"}
PARAM_ALIASES = {
    "pm2.5": "pm2_5", "pm25": "pm2_5", "pm_2_5": "pm2_5", "pm10": "pm10", "no2": "no2", "so2": "so2", "co": "co",
    "o3": "o3", "ozone": "o3", "ph": "ph", "do": "dissolved_oxygen", "dissolved_oxygen": "dissolved_oxygen",
    "dissolved oxygen": "dissolved_oxygen", "turbidity": "turbidity", "conductivity": "conductivity", "ec": "conductivity",
    "tds": "tds", "temperature": "water_temperature", "water_temperature": "water_temperature", "noise": "noise_laeq",
    "noise_level": "noise_laeq", "laeq": "noise_laeq", "noise_laeq": "noise_laeq",
}
UNIT_ALIASES = {
    "ug/m3": "µg/m³", "µg/m3": "µg/m³", "μg/m³": "µg/m³", "µg/m³": "µg/m³", "mg/m3": "mg/m³", "mg/m³": "mg/m³",
    "ppm": "ppm", "ppb": "ppb", "db": "dB(A)", "dba": "dB(A)", "db(a)": "dB(A)", "mg/l": "mg/L", "us/cm": "µS/cm",
    "µs/cm": "µS/cm", "ms/cm": "mS/cm", "c": "°C", "degc": "°C", "°c": "°C", "f": "°F", "°f": "°F", "ntu": "NTU", "ph": "pH", "": "",
}
# (parameter, from_unit) -> factor to canonical unit (25 °C, 1 atm for gases)
CONVERSIONS = {("co", "ppm"): 1.145, ("no2", "ppb"): 1.88, ("so2", "ppb"): 2.62, ("o3", "ppb"): 1.96,
               ("conductivity", "mS/cm"): 1000.0, ("co", "µg/m³"): 0.001}
BOUNDS = {"pm2_5": (0, 1000), "pm10": (0, 2000), "no2": (0, 2000), "so2": (0, 2000), "o3": (0, 1000), "co": (0, 100),
          "ph": (0, 14), "dissolved_oxygen": (0, 20), "turbidity": (0, 4000), "conductivity": (0, 100000),
          "tds": (0, 50000), "water_temperature": (-5, 45), "noise_laeq": (20, 140)}
PARAM_ALIASES.update({p: p for p in CANONICAL_UNITS})
RATE_LIMITS = {"pm2_5": 150, "pm10": 250, "no2": 150, "so2": 150, "o3": 120, "co": 10, "ph": 1.5,
               "dissolved_oxygen": 4, "turbidity": 50, "conductivity": 400, "tds": 300, "water_temperature": 5, "noise_laeq": 25}


def canonical_parameter(name: str) -> str | None:
    return PARAM_ALIASES.get(str(name).strip().lower())


def normalize_unit(parameter: str, value, unit: str):
    """Return (value, canonical_unit, issue_or_None)."""
    canon = CANONICAL_UNITS.get(parameter)
    u = UNIT_ALIASES.get(str(unit or "").strip().lower(), None)
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None, canon, None
    if u is None:
        return value, unit, f"unrecognised unit '{unit}'"
    if u == canon or (u == "" and parameter == "ph"):
        return float(value), canon, None
    if u == "°F" and parameter == "water_temperature":
        return round((float(value) - 32) * 5 / 9, 3), canon, None
    f = CONVERSIONS.get((parameter, u))
    if f:
        return round(float(value) * f, 4), canon, None
    return value, unit, f"unit '{unit}' is not valid for {parameter}"


def validate_long(df: pd.DataFrame, now: datetime | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Validate a long-format frame [id?, station_id, timestamp, parameter, value, unit].

    Returns the frame with quality_flag/flag_reason and a list of issue dicts. Suspicious values
    are flagged, never dropped (duplicates are the only rows removed, and they are reported).
    """
    issues: list[dict] = []
    df = df.copy()
    if "quality_flag" not in df:
        df["quality_flag"] = "valid"
    if "flag_reason" not in df:
        df["flag_reason"] = ""
    df["quality_flag"] = df["quality_flag"].fillna("valid")
    df["flag_reason"] = df["flag_reason"].fillna("")
    # re-evaluate algorithmic flags each run, keep human decisions (invalid/verified)
    auto = df["quality_flag"].isin(["suspect", "missing", "valid"])
    df.loc[auto, "quality_flag"] = "valid"
    df.loc[auto, "flag_reason"] = ""

    dup = df.duplicated(subset=["station_id", "timestamp", "parameter"], keep="first")
    if dup.any():
        for _, r in df[dup].iterrows():
            issues.append({"type": "duplicate_timestamp", "severity": "low", "parameter": r.parameter,
                           "timestamp": r.timestamp, "detail": f"duplicate reading {r.value} ignored (first value kept)"})
        df = df[~dup]

    for p, unit in df.groupby("parameter")["unit"].first().items():
        canon = CANONICAL_UNITS.get(p)
        if canon and unit != canon:
            issues.append({"type": "invalid_unit", "severity": "medium", "parameter": p, "detail": f"unit '{unit}' differs from canonical '{canon}'"})

    miss = df["value"].isna()
    df.loc[miss & auto.reindex(df.index, fill_value=True), "quality_flag"] = "missing"
    if miss.any():
        for p, n in df[miss].groupby("parameter").size().items():
            issues.append({"type": "missing_values", "severity": "low", "parameter": p, "detail": f"{n} missing hourly value(s) in window"})

    for p, (lo, hi) in BOUNDS.items():
        m = (df["parameter"] == p) & df["value"].notna() & ((df["value"] < lo) | (df["value"] > hi))
        for i, r in df[m].iterrows():
            df.at[i, "quality_flag"] = "suspect"
            df.at[i, "flag_reason"] = f"physically impossible value outside [{lo}, {hi}]"
            issues.append({"type": "impossible_reading", "severity": "high", "parameter": p, "timestamp": r.timestamp,
                           "value": r.value, "detail": df.at[i, "flag_reason"]})

    for sid, g in df.groupby("station_id"):
        wide_idx = {}
        for p, s in g[g.value.notna()].sort_values("timestamp").groupby("parameter"):
            v = s["value"].values
            ix = s.index.values
            wide_idx[p] = s.set_index("timestamp")["value"]
            if len(v) < 3:
                continue
            d = np.diff(v)
            mad = np.median(np.abs(d - np.median(d))) * 1.4826 or 1e-6
            lim = max(RATE_LIMITS.get(p, np.inf) * 0.5, 10 * mad)
            last_good = v[0]
            for k in range(1, len(v)):
                jump = v[k] - last_good
                if abs(jump) <= lim or abs(jump) <= RATE_LIMITS.get(p, np.inf) * 0.3:
                    last_good = v[k]
                    continue
                reverts = k + 1 < len(v) and abs(v[k + 1] - last_good) < 0.35 * abs(jump)
                sustained = k + 1 < len(v) and abs(v[k + 1] - v[k]) < 0.35 * abs(jump)
                if reverts or abs(jump) > RATE_LIMITS.get(p, np.inf):
                    i = ix[k]
                    df.at[i, "quality_flag"] = "suspect"
                    df.at[i, "flag_reason"] = (f"unrealistic change of {jump:+.2f} in one hour"
                                               + (" that reverts the next hour" if reverts else
                                                  " (sustained level shift)" if sustained else ""))
                    issues.append({"type": "unrealistic_change", "severity": "high", "parameter": p,
                                   "timestamp": df.at[i, "timestamp"], "value": float(v[k]), "detail": df.at[i, "flag_reason"]})
                    if sustained and not reverts:
                        last_good = v[k]
                else:
                    last_good = v[k]
            # flat-line detection (6+ identical consecutive values)
            run = 1
            for k in range(1, len(v)):
                run = run + 1 if v[k] == v[k - 1] else 1
                if run == 6:
                    issues.append({"type": "flatline", "severity": "medium", "parameter": p, "timestamp": s.iloc[k].timestamp,
                                   "detail": "signal unchanged for 6 consecutive hours"})
        if "pm2_5" in wide_idx and "pm10" in wide_idx:
            both = pd.concat([wide_idx["pm2_5"], wide_idx["pm10"]], axis=1, keys=["a", "b"]).dropna()
            bad = both[both.a > both.b * 1.05]
            for ts in bad.index:
                m = (df.station_id == sid) & (df.parameter == "pm2_5") & (df.timestamp == ts)
                df.loc[m, "quality_flag"] = "suspect"
                df.loc[m, "flag_reason"] = "PM2.5 exceeds PM10 (physically inconsistent)"
                issues.append({"type": "inconsistent_pm", "severity": "medium", "parameter": "pm2_5", "timestamp": ts,
                               "detail": "PM2.5 greater than PM10 at the same timestamp"})

    if now is not None and len(df):
        last = df[df.value.notna()]["timestamp"].max()
        if pd.notna(last) and now - last > timedelta(hours=STALE_AFTER_HOURS):
            issues.append({"type": "stale_sensor", "severity": "high", "parameter": "*", "timestamp": last,
                           "detail": f"no data for {(now - last).total_seconds() / 3600:.1f} h (limit {STALE_AFTER_HOURS} h)"})
    return df, issues
