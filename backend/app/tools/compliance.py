"""Deterministic regulatory comparison tool.

No LLM is involved in any number produced here. Every comparison:
  * uses the configured standard record (limit, unit, averaging period, source),
  * builds the average that matches the standard's averaging period,
  * checks data completeness (MIN_COVERAGE) before declaring an exceedance,
  * reports Measured Value, Applicable Reference Limit and Calculated Exceedance separately.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..config import MIN_COVERAGE

PERIOD_HOURS = {"1h": 1, "8h": 8, "24h": 24, "annual": 8760}


def difference(measured: float, std: dict) -> tuple[float | None, float | None, bool]:
    """Return (difference, percentage_difference, exceeded) per the standard's limit type.

    max:   difference = measured - limit
    min:   difference = limit - measured     (positive when below the minimum)
    range: difference = distance outside the [min, max] band (positive when outside)
    Percentage difference = difference / limit * 100 (for range, relative to the violated bound).
    """
    if measured is None or (isinstance(measured, float) and math.isnan(measured)):
        return None, None, False
    lt = std.get("limit_type", "max")
    if lt == "max":
        lim = float(std["limit"])
        d = measured - lim
    elif lt == "min":
        lim = float(std["limit"])
        d = lim - measured
    else:
        lo, hi = float(std["min"]), float(std["max"])
        if measured > hi:
            lim, d = hi, measured - hi
        elif measured < lo:
            lim, d = lo, lo - measured
        else:
            lim = hi if abs(measured - hi) < abs(measured - lo) else lo
            d = -min(abs(measured - hi), abs(measured - lo))
    pct = (d / lim * 100) if lim else None
    return round(d, 3), (round(pct, 1) if pct is not None else None), d > 0


def limit_text(std: dict) -> str:
    if std.get("limit_type") == "range":
        return f"{std['min']}–{std['max']} {std['unit']}"
    prefix = "≥ " if std.get("limit_type") == "min" else "≤ "
    return f"{prefix}{std['limit']} {std['unit']}"


def std_ref(std: dict) -> dict:
    keys = ("id", "standard_name", "issuer", "parameter", "limit_type", "limit", "min", "max", "averaging_period",
            "unit", "source_doc", "section", "version", "basis", "note")
    return {k: std.get(k) for k in keys if std.get(k) is not None}


def evaluate(series: pd.Series, std: dict, sensor_interval: str = "1h") -> dict:
    """Compare an hourly series (DatetimeIndex, valid values only, NaN = missing) with one standard."""
    s = series.sort_index()
    out = {"standard": std_ref(std), "limit_text": limit_text(std), "sensor_averaging": sensor_interval}
    valid = s.dropna()
    if valid.empty:
        out.update(status="no_data", comparison_valid=False, note="No valid measurements in window.")
        return out
    latest_ts = valid.index.max()
    out["measured_latest"] = {"value": round(float(valid.iloc[-1]), 3), "timestamp": latest_ts, "averaging": sensor_interval}
    period = std.get("averaging_period")

    if period == "instantaneous":
        val = float(valid.iloc[-1])
        d, pct, exc = difference(val, std)
        out.update(period_value=round(val, 3), period_label="latest instantaneous reading", coverage=1.0,
                   comparison_valid=True, difference=d, percentage_difference=pct, exceeded=exc,
                   status="exceedance" if exc else "compliant",
                   averaging_note="Grab/online instantaneous criterion compared with the latest reading.")
        return out

    if period in ("day", "night"):
        return {**out, **noise_period_eval(s, std)}

    hours = PERIOD_HOURS.get(period)
    if hours is None:
        out.update(status="not_assessable", comparison_valid=False, note=f"Unsupported averaging period '{period}'.")
        return out
    span_h = (s.index.max() - s.index.min()).total_seconds() / 3600 + 1
    if hours == 8760 and span_h < 8760 * MIN_COVERAGE:
        avg = float(valid.mean())
        d, pct, exc = difference(avg, std)
        out.update(status="not_assessable", comparison_valid=False, period_value=round(avg, 3),
                   period_label=f"mean of available {int(span_h)} h", coverage=round(span_h / 8760, 3),
                   difference=d, percentage_difference=pct, exceeded=False,
                   averaging_note=f"Annual standard needs ≥{int(MIN_COVERAGE*100)} % of a year; only {span_h/24:.0f} days available. Shown for context only.")
        return out
    window = s[s.index > latest_ts - pd.Timedelta(hours=hours)]
    coverage = window.notna().sum() / hours
    avg = float(window.mean())
    d, pct, exc = difference(avg, std)
    hourly_d, _, hourly_exc = difference(float(valid.iloc[-1]), std)
    valid_cmp = coverage >= MIN_COVERAGE or hours == 1
    if valid_cmp:
        status = "exceedance" if exc else ("indicative_hourly_above" if hourly_exc and hours > 1 else "compliant")
    else:
        status = "indicative_exceedance" if exc else "insufficient_data"
    note = (f"{hours}-h rolling mean ending {latest_ts:%Y-%m-%d %H:%M} compared with the {period} limit."
            if hours > 1 else "1-h value compared with 1-h limit.")
    if status == "indicative_hourly_above":
        note += " The latest 1-h value is above the numeric limit, but a single hourly value is not comparable with a longer averaging period; no exceedance declared."
    if not valid_cmp:
        note += f" Data completeness {coverage:.0%} is below {MIN_COVERAGE:.0%}; result is indicative only."
    out.update(period_value=round(avg, 3), period_label=f"{hours}-h mean", coverage=round(float(coverage), 3),
               comparison_valid=bool(valid_cmp), difference=d, percentage_difference=pct, exceeded=bool(exc and valid_cmp),
               status=status, averaging_note=note)
    return out


def leq(levels) -> float:
    arr = np.asarray([x for x in levels if x is not None and not np.isnan(x)], dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(10 * np.log10(np.mean(10 ** (arr / 10))))


def noise_periods(s: pd.Series, days: int = 7) -> list[dict]:
    """Return day (06-22) and night (22-06) Leq per period for the last `days` days."""
    s = s.sort_index()
    if s.dropna().empty:
        return []
    df = s.to_frame("v")
    hrs = df.index.hour
    df["kind"] = np.where((hrs >= 22) | (hrs < 6), "night", "day")
    # night of D = 22:00 D .. 05:59 D+1  -> label by start date
    shifted = df.index - pd.to_timedelta(np.where(hrs < 6, 1, 0), unit="D")
    df["period_date"] = shifted.date
    end = s.index.max()
    df = df[df.index > end - pd.Timedelta(days=days)]
    out = []
    for (d, kind), g in df.groupby(["period_date", "kind"]):
        expected = 16 if kind == "day" else 8
        cov = g.v.notna().sum() / expected
        out.append({"date": str(d), "period": kind, "leq": round(leq(g.v.values), 1) if g.v.notna().any() else None,
                    "max_hourly": round(float(g.v.max()), 1) if g.v.notna().any() else None,
                    "hours": int(g.v.notna().sum()), "coverage": round(float(cov), 2)})
    return out


def noise_period_eval(s: pd.Series, std: dict) -> dict:
    periods = [p for p in noise_periods(s) if p["period"] == std["averaging_period"]]
    complete = [p for p in periods if p["coverage"] >= MIN_COVERAGE and p["leq"] is not None]
    for p in periods:
        d, pct, exc = difference(p["leq"], std) if p["leq"] is not None else (None, None, False)
        p.update(difference=d, percentage_difference=pct, exceeded=bool(exc and p["coverage"] >= MIN_COVERAGE))
    if not complete:
        return {"status": "insufficient_data", "comparison_valid": False, "periods": periods,
                "averaging_note": "No complete day/night period available."}
    last = complete[-1]
    n_exc = sum(1 for p in complete if p["exceeded"])
    return {"period_value": last["leq"], "period_label": f"{std['averaging_period']}-time Leq ({last['date']})",
            "coverage": last["coverage"], "comparison_valid": True, "difference": last["difference"],
            "percentage_difference": last["percentage_difference"], "exceeded": last["exceeded"],
            "status": "exceedance" if last["exceeded"] else "compliant", "periods": periods,
            "exceedance_count": n_exc, "periods_assessed": len(complete), "repeated": n_exc >= 3,
            "averaging_note": f"{std['averaging_period'].title()}-time Leq per Noise Rules definition; {n_exc} of the last {len(complete)} complete {std['averaging_period']} periods exceed {std['limit']} dB(A)."}
