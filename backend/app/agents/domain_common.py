"""Shared parameter analysis used by the Air, Water and Noise agents."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from ..ml.anomaly_model import trend
from ..tools import standards as stdtool
from ..tools.compliance import evaluate
from ..tools.validation import CANONICAL_UNITS, DOMAIN_OF, LABELS
from .base import fmt

STATUS_RANK = {"exceedance": 5, "indicative_exceedance": 3, "indicative_hourly_above": 2, "compliant": 1,
               "insufficient_data": 0, "not_assessable": 0, "no_data": 0}
PREFERRED_PERIOD = {"pm2_5": "24h", "pm10": "24h", "no2": "24h", "so2": "24h", "co": "8h", "o3": "8h", "noise_laeq": "night"}


def analyze_parameter(step, station: dict, wide: pd.DataFrame, p: str) -> dict:
    s = wide[p] if p in wide else pd.Series(dtype=float)
    stds = step.tool("standards.applicable", {"station": station["id"], "parameter": p}, stdtool.applicable(station, p))
    step.tool_calls[-1]["result"] = [x["id"] for x in stds]
    comparisons = [evaluate(s, std) for std in stds]
    step.tool("compliance.evaluate", {"parameter": p, "standards": [x["id"] for x in stds]},
              [{"standard": c["standard"]["id"], "status": c.get("status"), "period_value": c.get("period_value"),
                "difference": c.get("difference"), "pct": c.get("percentage_difference")} for c in comparisons])
    primary = None
    if comparisons:
        primary = max(comparisons, key=lambda c: (STATUS_RANK.get(c.get("status"), 0),
                                                  c["standard"].get("averaging_period") == PREFERRED_PERIOD.get(p)))
    valid = s.dropna()
    latest = {"value": round(float(valid.iloc[-1]), 3), "timestamp": valid.index[-1]} if len(valid) else None
    base = valid[valid.index <= (valid.index.max() - timedelta(hours=48))] if len(valid) else valid
    last24 = valid[valid.index > valid.index.max() - timedelta(hours=24)] if len(valid) else valid
    baseline_median = float(base.median()) if len(base) else None
    mean24 = float(last24.mean()) if len(last24) else None
    change = ((mean24 - baseline_median) / baseline_median * 100) if baseline_median else None
    repeated = 0
    if primary and primary["standard"].get("limit_type") == "max" and len(last24):
        repeated = int((last24 > primary["standard"]["limit"]).sum())
    return {"domain": DOMAIN_OF.get(p), "parameter": p, "label": LABELS.get(p, p), "unit": CANONICAL_UNITS.get(p),
            "measured": latest, "comparisons": comparisons, "primary": primary,
            "status": primary.get("status") if primary else ("no_reference" if latest else "no_data"),
            "trend": trend(s), "baseline_median": round(baseline_median, 3) if baseline_median is not None else None,
            "mean_24h": round(mean24, 3) if mean24 is not None else None,
            "change_vs_baseline_pct": round(change, 1) if change is not None else None,
            "hours_above_limit_24h": repeated}


def template_interpretation(f: dict) -> str:
    lab, u = f["label"], f["unit"]
    pr = f.get("primary")
    if not f.get("measured"):
        return f"No valid {lab} data in the analysis window."
    if not pr:
        t = f"{lab} latest value {fmt(f['measured']['value'], 2)} {u}; no configured reference applies, so it is tracked against its own baseline"
        if f.get("change_vs_baseline_pct") is not None:
            t += f" ({fmt(f['change_vs_baseline_pct'])} % vs. baseline median)"
        return t + "."
    std = pr["standard"]
    basis = "" if std.get("basis") == "regulatory" else f" ({std.get('basis', '').replace('_', ' ')}, not a legal limit)"
    st = pr.get("status")
    head = f"{lab} {pr.get('period_label', '')} = {fmt(pr.get('period_value'), 2)} {u} against the configured {std['averaging_period']} reference {pr['limit_text']}{basis}"
    if st == "exceedance":
        body = f"; calculated difference {fmt(pr['difference'], 2)} {u} ({fmt(pr['percentage_difference'])} %). The value is above the configured reference."
    elif st == "indicative_exceedance":
        body = f"; difference {fmt(pr['difference'], 2)} {u}, but data completeness is {fmt(pr.get('coverage', 0) * 100, 0)} %, so this is indicative only."
    elif st == "indicative_hourly_above":
        body = ". The period mean is within the reference; the latest hourly value is above the numeric limit, which is not comparable with the longer averaging period."
    elif st == "not_assessable":
        body = ". This averaging period cannot be assessed with the available data."
    else:
        body = "; within the configured reference."
    tr = f.get("trend", {}).get("direction")
    if tr in ("increasing", "decreasing"):
        body += f" The 72-h trend is {tr} (Theil–Sen slope {fmt(f['trend']['slope_per_h'], 3)} {u}/h, {_p(f['trend']['p_value'])})."
    return head + body + " This is a monitoring interpretation, not a legal determination."


def _p(p) -> str:
    return "p < 0.001" if p is not None and p < 0.001 else f"p = {fmt(p, 3)}"
