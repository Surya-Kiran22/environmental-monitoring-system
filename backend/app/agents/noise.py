"""Agent 4 — Noise Pollution Analysis Agent."""
from __future__ import annotations

import json

import pandas as pd

from ..tools import llm
from ..tools.compliance import noise_periods
from ..utils import clean
from .base import Step, event, fmt
from .domain_common import analyze_parameter
from .prompts import PROMPTS


def noise_agent(state: dict) -> dict:
    st, wide = state["station"], state["wide"]
    with Step("Noise Pollution Analysis Agent", "noise", {"station_id": st["id"], "zone": st["zone_category"]}) as step:
        f = analyze_parameter(step, st, wide, "noise_laeq")
        s = wide["noise_laeq"] if "noise_laeq" in wide else None
        periods = step.tool("compliance.noise_periods", {"days": 7}, noise_periods(s) if s is not None else [])
        hourly = {}
        if s is not None and s.notna().any():
            recent = s[s.index > s.index.max() - pd.Timedelta(days=7)]
            hourly = {int(k): round(float(v), 1) for k, v in recent.groupby(recent.index.hour).mean().items()}
        day = next((c for c in f["comparisons"] if c["standard"]["averaging_period"] == "day"), None)
        night = next((c for c in f["comparisons"] if c["standard"]["averaging_period"] == "night"), None)
        repeated_night = bool(night and night.get("repeated"))
        f["noise"] = {"day": day, "night": night, "hourly_profile": hourly, "repeated_night_exceedance": repeated_night,
                      "repeated_day_exceedance": bool(day and day.get("repeated"))}
        if night and night.get("comparison_valid"):
            text = (f"Night-time Leq: {night.get('exceedance_count', 0)} of the last {night.get('periods_assessed', 0)} complete nights exceed the "
                    f"configured {st['zone_category']} night reference {night['limit_text']}. Latest complete night Leq {fmt(night.get('period_value'))} dB(A).")
        else:
            text = "Night-time periods could not be assessed."
        if day and day.get("comparison_valid"):
            text += (f" Day-time: {day.get('exceedance_count', 0)} of {day.get('periods_assessed', 0)} days exceed {day['limit_text']}"
                     f" (latest Leq {fmt(day.get('period_value'))} dB(A)).")
        if repeated_night:
            text += " Repeated high night-time noise is present."
        f["ai_interpretation"] = text + " This is a monitoring interpretation, not a legal determination."
        gen = llm.generate(PROMPTS["noise"], json.dumps(clean({"zone": st["zone_category"], "day": day, "night": night}), default=str))
        step.llm_used = bool(gen)
        step.output = {"day_leq": day and day.get("period_value"), "night_leq": night and night.get("period_value"),
                       "night_exceedances": night and night.get("exceedance_count"), "repeated_night": repeated_night,
                       "interpretation": f["ai_interpretation"]}
    return {"findings": [f], "noise_periods": periods, "domain_summary": gen or text, "trace": [step.record()],
            "events": [event("DOMAIN_ANALYZED", {"agent": "noise", "repeated_night_exceedance": repeated_night})]}
