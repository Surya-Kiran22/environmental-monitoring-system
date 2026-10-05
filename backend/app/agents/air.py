"""Agent 2 — Air Quality Analysis Agent."""
from __future__ import annotations

import json

from ..tools import llm
from ..tools.cross_station import cross_station
from ..utils import clean
from .base import Step, event
from .domain_common import analyze_parameter, template_interpretation
from .prompts import PROMPTS

AIR = ["pm2_5", "pm10", "no2", "so2", "co", "o3"]


def air_agent(state: dict) -> dict:
    st, wide = state["station"], state["wide"]
    params = [p for p in AIR if p in st["parameters"]]
    with Step("Air Quality Analysis Agent", "air_quality", {"station_id": st["id"], "parameters": params}) as step:
        findings = [analyze_parameter(step, st, wide, p) for p in params]
        for f in findings:
            f["ai_interpretation"] = template_interpretation(f)
        # cross-station comparison for the most elevated pollutant
        ranked = sorted([f for f in findings if f.get("primary") and f["primary"].get("period_value") is not None],
                        key=lambda f: (f["primary"].get("percentage_difference") or -999), reverse=True)
        key = ranked[0]["parameter"] if ranked else "pm2_5"
        cs = step.tool("cross_station.compare", {"station_id": st["id"], "parameter": key}, cross_station(st["id"], key, state["now"]))
        gen = llm.generate(PROMPTS["air"], json.dumps(clean({"station": st["id"], "findings": [
            {k: f[k] for k in ("label", "unit", "measured", "status", "mean_24h", "trend")} | {"primary": f.get("primary")} for f in findings],
            "cross_station": cs}), default=str))
        step.llm_used = bool(gen)
        summary = gen or _summary(findings, cs)
        step.output = {"findings": [{"parameter": f["parameter"], "status": f["status"], "interpretation": f["ai_interpretation"]} for f in findings],
                       "cross_station": {"classification": cs.get("classification"), "summary": cs.get("summary")}, "summary": summary}
    return {"findings": findings, "cross_station": cs, "domain_summary": summary, "trace": [step.record()],
            "events": [event("DOMAIN_ANALYZED", {"agent": "air", "exceedances": [f["parameter"] for f in findings if f["status"] == "exceedance"],
                                                  "spatial_pattern": cs.get("classification")})]}


def _summary(findings, cs) -> str:
    exc = [f for f in findings if f["status"] == "exceedance"]
    if not exc:
        return "All assessed air pollutants are within their configured references for valid averaging periods. " + cs.get("summary", "")
    parts = [f"{f['label']} ({f['primary']['period_label']} {f['primary']['period_value']} {f['unit']}, +{f['primary']['percentage_difference']} %)" for f in exc]
    return f"Configured references exceeded for: {', '.join(parts)}. " + cs.get("summary", "")
