"""Agent 7 — Environmental Alert & Investigation Agent.

Consolidates domain findings, weather context, anomaly results, cross-station analysis and retrieved
standards into explainable draft alerts, a monitoring risk score and a bandit-ranked recommendation.
Drafts go to the Reviewer Agent before anything is persisted.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

from ..config import SOURCE_SEARCH_RADIUS_KM
from ..database import SessionLocal
from ..tools import bandit, llm
from ..tools import data_access as da
from ..tools.geo import haversine_km, upwind_sources
from ..utils import clean
from .base import Step, event, fmt
from .prompts import PROMPTS

RANK = {"Normal": 0, "Observation": 1, "Elevated": 2, "Investigation Required": 3, "Sensor Verification Required": 3,
        "Critical Review Required": 4}
DOMAIN = {"air_quality": "air", "water_quality": "water", "noise": "noise"}


def risk_category(score: float) -> str:
    return "LOW" if score < 25 else "MODERATE" if score < 50 else "HIGH" if score < 75 else "CRITICAL"


def _curve(ratio: float) -> float:
    """Saturating score: ratio 1 (at the limit) -> 50, ratio 2 -> 75, ratio 3 -> 87.5."""
    return 100 * (1 - math.exp(-math.log(2) * max(ratio, 0)))


def param_risk(f: dict) -> float | None:
    if f["parameter"] == "noise_laeq":
        c = (f.get("noise") or {}).get("night") or (f.get("noise") or {}).get("day")
        if not c or c.get("period_value") is None:
            return None
        # +10 dB is perceived as roughly twice as loud -> loudness ratio 2^(ΔL/10)
        return _curve(2 ** ((c["period_value"] - c["standard"]["limit"]) / 10))
    pr = f.get("primary")
    if not pr or pr.get("period_value") is None:
        return None
    std, v = pr["standard"], pr["period_value"]
    lt = std.get("limit_type")
    if lt == "max":
        ratio = v / std["limit"]
    elif lt == "min":
        ratio = std["limit"] / max(v, 0.01)
    else:
        lo, hi = std["min"], std["max"]
        half = (hi - lo) / 2 or 1
        ratio = 0.5 if lo <= v <= hi else 1 + (pr["difference"] or 0) / half
    s = _curve(ratio)
    if std.get("basis") != "regulatory":
        s *= 0.8
    if not pr.get("comparison_valid", True):
        s *= 0.85
    return max(0.0, min(100.0, s))


def compute_risk(findings: list[dict], anomaly: dict) -> dict:
    scores = {f["parameter"]: round(param_risk(f), 1) for f in findings if param_risk(f) is not None}
    if not scores:
        return {"score": 0.0, "category": "LOW", "parameter_scores": {}, "highest_parameter": None, "method": "no assessable parameters"}
    mx, mean = max(scores.values()), sum(scores.values()) / len(scores)
    bonus = 5 * (anomaly.get("max_score_24h") or 0) if (anomaly.get("anomalous_hours_24h") or 0) >= 3 else 0
    score = round(min(100.0, 0.7 * mx + 0.3 * mean + bonus), 1)
    return {"score": score, "category": risk_category(score), "parameter_scores": scores,
            "highest_parameter": max(scores, key=scores.get), "anomaly_bonus": round(bonus, 1),
            "data_confidence": "reduced" if anomaly.get("sensor_flags") or anomaly.get("stale") else "normal",
            "method": "0.7·max(parameter score) + 0.3·mean + 5·anomaly score (if ≥3 anomalous h). Parameter score = 100·(1 − 2^(−value/limit)): 50 at the limit, 75 at twice the limit; noise uses loudness ratio 2^(ΔdB/10). Monitoring priority index, not a regulatory index."}


def _mk(category, alert_type, parameter, title, finding=None, comparison=None, supporting=None):
    std = comparison["standard"] if comparison else None
    a = {"category": category, "alert_type": alert_type, "parameter": parameter, "title": title, "priority_rank": RANK[category],
         "standard_ref": std, "supporting": supporting or [],
         "measured_value": None, "applicable_reference": None, "calculated_exceedance": None}
    if finding and finding.get("measured"):
        a["measured_value"] = {"latest_hourly": finding["measured"]["value"], "latest_time": finding["measured"]["timestamp"], "unit": finding["unit"]}
    if comparison:
        a["measured_value"] = {**(a["measured_value"] or {}), "period_value": comparison.get("period_value"),
                               "period_label": comparison.get("period_label"), "coverage": comparison.get("coverage"),
                               "unit": std["unit"]}
        a["applicable_reference"] = {"limit": comparison.get("limit_text"), "averaging_period": std.get("averaging_period"), "unit": std.get("unit"),
                                     "standard": std.get("standard_name"), "standard_id": std.get("id"), "section": std.get("section"),
                                     "source": std.get("source_doc"), "version": std.get("version"), "basis": std.get("basis")}
        a["calculated_exceedance"] = {"difference": comparison.get("difference"), "percentage_difference": comparison.get("percentage_difference"),
                                      "formula": "Difference = period value − limit; % = Difference / limit × 100 (min/range limits: distance outside the bound)",
                                      "comparison_valid": comparison.get("comparison_valid"), "averaging_note": comparison.get("averaging_note")}
    return a


def build_alerts(state: dict) -> list[dict]:
    st, findings, an = state["station"], state.get("findings", []), state.get("anomaly", {})
    alerts: list[dict] = []
    for f in findings:
        p, lab = f["parameter"], f["label"]
        if p == "noise_laeq":
            for kind in ("night", "day"):
                c = (f.get("noise") or {}).get(kind)
                if c and c.get("repeated"):
                    alerts.append(_mk("Investigation Required", "persistent_elevated", p,
                                      f"Repeated {kind}-time noise above {c['limit_text']} ({c['exceedance_count']} of {c['periods_assessed']} {kind}s)", f, c,
                                      [f"{kind.title()}-time Leq per period: " + ", ".join(f"{x['date']}: {x['leq']} dB(A)" for x in c.get("periods", []) if x.get("leq") is not None)]))
                elif c and c.get("exceeded"):
                    alerts.append(_mk("Elevated", "threshold_exceedance", p, f"{kind.title()}-time noise Leq above {c['limit_text']}", f, c))
            continue
        pr = f.get("primary")
        if not pr:
            continue
        stt = pr.get("status")
        basis_reg = pr["standard"].get("basis") == "regulatory"
        if stt == "exceedance":
            cat = "Critical Review Required" if (pr.get("percentage_difference") or 0) >= 50 and basis_reg else "Investigation Required"
            sup = []
            if f.get("hours_above_limit_24h", 0) >= 12 and pr["standard"].get("limit_type") == "max":
                sup.append(f"Persistent: {f['hours_above_limit_24h']} of the last 24 hourly values are above the numeric limit.")
            alerts.append(_mk(cat, "threshold_exceedance", p, f"{lab} {pr.get('period_label')} above configured {pr['standard']['averaging_period']} reference", f, pr, sup))
        elif stt in ("indicative_exceedance", "indicative_hourly_above"):
            alerts.append(_mk("Elevated", "indicative_exceedance", p, f"{lab} elevated (indicative — averaging/completeness rules not met)", f, pr))
        elif f.get("trend", {}).get("direction") == ("decreasing" if p == "dissolved_oxygen" else "increasing") and (f.get("change_vs_baseline_pct") or 0) >= 25:
            alerts.append(_mk("Observation", "rising_trend", p, f"{lab} rising trend (+{fmt(f['change_vs_baseline_pct'])} % vs. baseline)", f, pr))
    # water change classification (co-moving environmental changes are grouped into one alert)
    env = [c for c in an.get("classified_changes", []) if c["classification"] == "valid_environmental_change"]
    env.sort(key=lambda c: -abs(c.get("change_pct") or 0))
    if env:
        c = env[0]
        f = next((x for x in findings if x["parameter"] == c["parameter"]), None)
        others = [f"{o['parameter']} {fmt(o['previous_value'], 2)} → {fmt(o['current_value'], 2)} ({fmt(o['change_pct'])} %)" for o in env[1:]]
        alerts.append(_mk("Investigation Required", "rapid_deterioration", c["parameter"],
                          f"Possible water-quality deterioration: {f['label'] if f else c['parameter']} {fmt(c['previous_value'], 2)} → {fmt(c['current_value'], 2)} in 6 h",
                          f, None, [c["classification_reason"]] + ([f"Co-moving parameters: {'; '.join(others)}."] if others else [])))
    for c in an.get("classified_changes", []):
        if c["classification"] == "valid_environmental_change":
            continue
        cat, typ = {"sensor_anomaly": ("Sensor Verification Required", "sensor_failure"),
                    "data_quality_issue": ("Sensor Verification Required", "data_quality")}.get(c["classification"], ("Elevated", "abnormal_change"))
        f = next((x for x in findings if x["parameter"] == c["parameter"]), None)
        alerts.append(_mk(cat, typ, c["parameter"],
                          f"{f['label'] if f else c['parameter']} changed {fmt(c['previous_value'], 2)} → {fmt(c['current_value'], 2)} in 6 h ({c['classification'].replace('_', ' ')})",
                          f, None, [c["classification_reason"]]))
    # sensor verification
    by_param = defaultdict(list)
    for s in an.get("sensor_flags", []):
        by_param[s["parameter"]].append(s)
    for p, flags in by_param.items():
        alerts.append(_mk("Sensor Verification Required", "sensor_spike", p,
                          f"Unrealistic {p} reading(s) flagged — sensor verification requested", None, None,
                          [f"{x['timestamp']}: {x['value']} — {x['reason']}" for x in flags[:5]]))
    if an.get("stale"):
        alerts.append(_mk("Sensor Verification Required", "sensor_failure", "*", f"{st['id']} not reporting — stale sensor", None, None,
                          [i["detail"] for i in state.get("validation", {}).get("issues", []) if i["type"] == "stale_sensor"]))
    # anomaly without a stronger alert
    top_rank = max([a["priority_rank"] for a in alerts if a["alert_type"] not in ("sensor_spike", "sensor_failure")], default=0)
    if an.get("anomalous_hours_24h", 0) >= 3 and top_rank < 3:
        key = (an.get("latest_top_contributors") or [{"parameter": "*"}])[0]["parameter"]
        alerts.append(_mk("Elevated", "abnormal_pollution_spike", key,
                          f"Abnormal pattern: {an['anomalous_hours_24h']} anomalous hour(s) in 24 h (max score {an.get('max_score_24h')})"))
    if an.get("unusual_combination"):
        alerts.append(_mk("Elevated", "unusual_multi_pollutant", ",".join(an["combination_parameters"]),
                          f"Unusual multi-parameter pattern ({', '.join(an['combination_parameters'])})"))
    # merge duplicates on the same parameter (avoid alert duplication)
    merged: dict = {}
    for a in alerts:
        k = a["parameter"]
        if k in merged and a["alert_type"] not in ("sensor_spike", "sensor_failure") and merged[k]["alert_type"] not in ("sensor_spike", "sensor_failure"):
            m = merged[k]
            m["supporting"] += [f"Also detected: {a['title']}"] + a["supporting"]
            if a["priority_rank"] > m["priority_rank"]:
                m["category"], m["priority_rank"] = a["category"], a["priority_rank"]
            m["alert_type"] = m["alert_type"] if a["alert_type"] in m["alert_type"] else f"{m['alert_type']}+{a['alert_type']}"
        elif k in merged:
            merged[f"{k}:{a['alert_type']}"] = a
        else:
            merged[k] = a
    return list(merged.values())


def alert_agent(state: dict) -> dict:
    st, now = state["station"], state["now"]
    domain = DOMAIN[st["monitoring_type"]]
    force_template = bool(state.get("review_feedback"))
    wx, cs, an = state.get("weather_context", {}), state.get("cross_station") or {}, state.get("anomaly", {})
    with Step("Environmental Alert & Investigation Agent", "alert",
              {"station_id": st["id"], "findings": len(state.get("findings", [])), "reassessment": force_template,
               "reviewer_feedback": state.get("review_feedback")}) as step:
        alerts = build_alerts(state)
        db = SessionLocal()
        try:
            srcs = da.sources(db)
            # source investigation support (never attribution)
            wind_from = (wx.get("event_window") or {}).get("wind_dir_deg") or wx.get("wind_dir_24h_deg")
            if domain == "air":
                cand = upwind_sources(st, srcs, wind_from, SOURCE_SEARCH_RADIUS_KM)
            else:
                cand = sorted([{**s, "distance_km": round(haversine_km(st["latitude"], st["longitude"], s["latitude"], s["longitude"]), 2),
                                "upwind": None, "label": "Registered source within search radius requiring investigation (flow direction not modelled)"}
                               for s in srcs], key=lambda x: x["distance_km"])
                cand = [c for c in cand if c["distance_km"] <= SOURCE_SEARCH_RADIUS_KM]
            step.tool("geo.source_investigation", {"wind_from_deg": wind_from, "radius_km": SOURCE_SEARCH_RADIUS_KM},
                      [{"id": c["id"], "distance_km": c["distance_km"], "upwind": c["upwind"]} for c in cand])
            for a in alerts:
                if a["priority_rank"] >= 2 and a["alert_type"] not in ("sensor_spike", "sensor_failure"):
                    if domain == "air" and cs:
                        a["cross_station"] = {"classification": cs.get("classification"), "summary": cs.get("summary"),
                                              "elevated": f"{cs.get('elevated_count')} of {cs.get('station_count')}", "parameter": cs.get("parameter")}
                    a["weather_observations"] = wx.get("observations", [])
                    a["anomaly"] = {"latest_score": an.get("latest_score"), "max_score_24h": an.get("max_score_24h"),
                                    "anomalous_hours_24h": an.get("anomalous_hours_24h")}
                    relevant = [c for c in cand if c.get("upwind") or domain != "air"]
                    a["potential_sources"] = [{"id": c["id"], "name": c["name"], "distance_km": c["distance_km"], "bearing": c.get("bearing"),
                                               "label": c["label"]} for c in relevant[:3]]
            alerts.sort(key=lambda a: -a["priority_rank"])
            top = alerts[0] if alerts else None
            overall = top["category"] if top else "Normal"
            risk = compute_risk(state.get("findings", []), an)
            step.tool("risk.compute", {"parameters": list(risk["parameter_scores"].keys())}, {"score": risk["score"], "category": risk["category"]})
            rec = None
            if top and top["priority_rank"] >= 2:
                bdomain = "sensor" if top["category"] == "Sensor Verification Required" else domain
                rec = step.tool("bandit.recommend", {"domain": bdomain, "category": top["category"]},
                                bandit.recommend(db, bdomain, top["category"], seed=state["run_id"]))
        finally:
            db.close()
        # explanations
        for a in alerts:
            f = next((x for x in state.get("findings", []) if x["parameter"] == a["parameter"]), None)
            parts = [f["ai_interpretation"]] if f and f.get("ai_interpretation") else []
            parts += a.get("supporting", [])
            if a.get("cross_station"):
                parts.append(a["cross_station"]["summary"])
            if a.get("weather_observations"):
                parts.append(a["weather_observations"][0])
            if a.get("potential_sources"):
                parts.append("Potential contributing source(s) requiring investigation: " + "; ".join(f"{s['name']} ({s['distance_km']} km)" for s in a["potential_sources"]) + " — not confirmed.")
            a["ai_interpretation"] = " ".join(parts)
            a["why"] = _why(a)
        facts = clean({"station": st["id"], "overall_category": overall, "risk": risk, "alerts": [
            {k: a.get(k) for k in ("title", "category", "measured_value", "applicable_reference", "calculated_exceedance", "cross_station", "weather_observations", "potential_sources")}
            for a in alerts[:4]], "recommendation": rec and rec["recommended_action"]})
        gen = None if force_template else llm.generate(PROMPTS["alert"], json.dumps(facts, default=str))
        step.llm_used = bool(gen)
        summary = gen or _summary(st, overall, alerts, risk, rec)
        draft = {"alerts": alerts, "overall_category": overall, "risk": risk, "recommendation": rec, "summary": summary,
                 "summary_source": "llm" if gen else "template", "llm_facts": facts if gen else None}
        step.output = {"overall_category": overall, "alerts": [{"title": a["title"], "category": a["category"]} for a in alerts],
                       "risk": {"score": risk["score"], "category": risk["category"]}, "recommendation": rec and rec["recommended_action"], "summary": summary}
    evs = [event("RISK_EVALUATED", {"station_id": st["id"], "overall_risk_score": risk["score"], "category": risk["category"],
                                     "highest_factor": risk.get("highest_parameter"), "alert_category": overall})]
    if rec:
        evs.append(event("BANDIT_RECOMMENDATION", {"context": rec["context"], "action": rec["recommended_action"], "mode": rec["mode"], "epsilon": rec["epsilon"]}))
    return {"draft": draft, "trace": [step.record()], "events": evs}


def _why(a: dict) -> str:
    t = a["alert_type"]
    if t.startswith("threshold_exceedance") and a.get("calculated_exceedance"):
        c = a["calculated_exceedance"]
        return (f"Generated because the {a['applicable_reference']['averaging_period']} value {fmt(a['measured_value'].get('period_value'), 2)} "
                f"{a['measured_value']['unit']} differs from the configured reference {a['applicable_reference']['limit']} by "
                f"{fmt(c['difference'], 2)} ({fmt(c['percentage_difference'])} %) with valid data completeness.")
    return {"sensor_spike": "Generated because validation flagged physically unrealistic readings; data is retained but excluded from compliance until verified.",
            "sensor_failure": "Generated because the station stopped reporting or its readings failed validation.",
            "persistent_elevated": "Generated because the configured reference was exceeded in at least 3 of the last 7 assessed periods.",
            "indicative_exceedance": "Generated as an elevated (non-regulatory) signal: values are high but averaging-period or completeness rules prevent declaring an exceedance.",
            "abnormal_pollution_spike": "Generated because the anomaly model scored several recent hours outside the station's normal multivariate pattern.",
            "unusual_multi_pollutant": "Generated because several parameters deviate together in a pattern rarely seen in the station's history.",
            "rapid_deterioration": "Generated because a sustained short-term change was classified as consistent with a real change in water quality.",
            "rising_trend": "Recorded because the 72-h trend test is significant and the 24-h mean is well above the baseline.",
            }.get(t.split("+")[0], "Generated from the combined agent evidence.")


def _summary(st, overall, alerts, risk, rec) -> str:
    if not alerts or overall in ("Normal", "Observation"):
        return f"{st['name']}: no alert required. Monitoring risk index {risk['score']} ({risk['category']})."
    lead = alerts[0]
    t = f"{st['name']}: {overall}. {lead['title']}. Monitoring risk index {risk['score']} ({risk['category']})."
    if rec:
        t += f" Suggested next step for officer review: {rec['recommended_action']}."
    return t + " Findings support investigation and do not constitute a legal determination."
