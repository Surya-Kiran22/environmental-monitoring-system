"""Agent 3 — Water Quality Analysis Agent."""
from __future__ import annotations

import json
from datetime import timedelta

from ..tools import llm
from ..utils import clean
from .base import Step, event, fmt
from .domain_common import analyze_parameter, template_interpretation
from .prompts import PROMPTS

WATER = ["ph", "dissolved_oxygen", "turbidity", "conductivity", "tds", "water_temperature"]


def detect_changes(wide, params, lookback_h: int = 6) -> list[dict]:
    out = []
    for p in params:
        if p not in wide:
            continue
        s = wide[p].dropna()
        if len(s) < 48:
            continue
        end = s.index.max()
        prev = s[s.index <= end - timedelta(hours=lookback_h)]
        if prev.empty:
            continue
        prev_v, cur = float(prev.iloc[-1]), float(s.iloc[-1])
        hist = s[s.index <= end - timedelta(hours=48)]
        sd = float((hist.diff(lookback_h)).abs().quantile(0.95)) or 1e-6
        delta = cur - prev_v
        rel = delta / prev_v * 100 if prev_v else None
        if abs(delta) > 2.5 * sd and (rel is None or abs(rel) >= 25):
            rising_hours = int((s.diff().tail(lookback_h) > 0).sum())
            out.append({"parameter": p, "previous_value": round(prev_v, 3), "previous_time": prev.index[-1], "current_value": round(cur, 3),
                        "current_time": end, "change": round(delta, 3), "change_pct": round(rel, 1) if rel is not None else None,
                        "typical_6h_change_p95": round(sd, 3), "consecutive_direction_hours": rising_hours,
                        "classification": "pending (anomaly agent)"})
    return out


def water_agent(state: dict) -> dict:
    st, wide = state["station"], state["wide"]
    params = [p for p in WATER if p in st["parameters"]]
    with Step("Water Quality Analysis Agent", "water_quality", {"station_id": st["id"], "parameters": params, "water_class": st.get("water_class")}) as step:
        findings = [analyze_parameter(step, st, wide, p) for p in params]
        for f in findings:
            f["ai_interpretation"] = template_interpretation(f)
        changes = step.tool("water.detect_changes", {"lookback_h": 6}, detect_changes(wide, params))
        for c in changes:
            f = next(x for x in findings if x["parameter"] == c["parameter"])
            f["change_event"] = c
            f["ai_interpretation"] += (f" {f['label']} changed from {fmt(c['previous_value'], 2)} to {fmt(c['current_value'], 2)} {f['unit']} in 6 h "
                                       f"({fmt(c['change_pct'])} %); this may be a valid environmental change, a sensor anomaly or a data-quality issue and is passed to the anomaly agent for classification.")
        gen = llm.generate(PROMPTS["water"], json.dumps(clean({"findings": [{k: f.get(k) for k in ("label", "unit", "measured", "status", "change_event")} for f in findings]}), default=str))
        step.llm_used = bool(gen)
        summary = gen or ("Significant change detected in " + ", ".join(f"{c['parameter']} ({fmt(c['previous_value'],2)} → {fmt(c['current_value'],2)})" for c in changes) + "."
                          if changes else "No significant short-term water-quality change detected.")
        step.output = {"findings": [{"parameter": f["parameter"], "status": f["status"]} for f in findings], "changes": changes, "summary": summary}
    return {"findings": findings, "water_changes": changes, "domain_summary": summary, "trace": [step.record()],
            "events": [event("DOMAIN_ANALYZED", {"agent": "water", "changes": [c["parameter"] for c in changes],
                                                  "exceedances": [f["parameter"] for f in findings if f["status"] == "exceedance"]})]}
