"""Agent 6 — Pollution Anomaly & Trend Detection Agent."""
from __future__ import annotations

import json
from datetime import timedelta

import numpy as np

from ..database import SessionLocal, Station
from ..ml import anomaly_model as am
from ..tools import data_access as da
from ..tools import llm
from ..utils import clean
from .base import Step, event, fmt
from .prompts import PROMPTS

DOMAIN = {"air_quality": "air", "water_quality": "water", "noise": "noise"}
_BUNDLES: dict = {}


def get_bundle(domain: str, now) -> dict:
    key = (domain, now.strftime("%Y-%m-%d"))
    if key in _BUNDLES:
        return _BUNDLES[key]
    db = SessionLocal()
    try:
        mt = {v: k for k, v in DOMAIN.items()}[domain]
        sids = [s.id for s in db.query(Station).filter(Station.monitoring_type == mt).all()]
        cutoff = now - timedelta(hours=48)
        series = {}
        for sid in sids:
            w = da.to_wide(da.load_long(db, [sid], start=now - timedelta(days=30), end=cutoff))
            if len(w) > 72:
                series[sid] = w
        wx = da.weather_frame(db, start=now - timedelta(days=31), end=now)
    finally:
        db.close()
    bundle = am.fit_domain(series, domain, wx)
    bundle["weather"] = wx
    bundle["trained_until"] = cutoff.isoformat()
    _BUNDLES.clear()
    _BUNDLES[key] = bundle
    return bundle


def classify_change(change: dict, validation: dict, wide, weather_ctx: dict) -> dict:
    p = change["parameter"]
    t0 = change["previous_time"]
    sus = [s for s in validation.get("recent_suspects", []) if s["parameter"] == p and s["timestamp"] >= t0]
    missing = wide[p][wide.index >= t0].isna().sum() if p in wide else 0
    co = []
    for other, sign in (("dissolved_oxygen", -1), ("conductivity", 1), ("tds", 1)):
        if other != p and other in wide:
            w = wide[other][wide.index >= t0].dropna()
            if len(w) >= 3 and np.sign(w.iloc[-1] - w.iloc[0]) == sign:
                co.append(other)
    rain = weather_ctx.get("rain_48h_mm", 0) or 0
    if sus:
        cls, why = "sensor_anomaly", f"{len(sus)} value(s) in the change window were flagged as unrealistic by validation."
    elif missing >= 3:
        cls, why = "data_quality_issue", f"{int(missing)} missing hour(s) inside the change window."
    elif change["consecutive_direction_hours"] >= 4 and co:
        cls = "valid_environmental_change"
        why = (f"Sustained change over {change['consecutive_direction_hours']} consecutive hours with co-movement in {', '.join(co)}"
               + (f"; {fmt(rain)} mm rainfall in 48 h." if rain > 1 else "; no rainfall recorded, so runoff is not indicated.")
               + " Laboratory confirmation recommended.")
    else:
        cls, why = "undetermined", "Change is not sustained or lacks supporting signals; sensor verification recommended."
    return {**change, "classification": cls, "classification_reason": why}


def anomaly_agent(state: dict) -> dict:
    st, wide, now = state["station"], state["wide"], state["now"]
    domain = DOMAIN[st["monitoring_type"]]
    with Step("Pollution Anomaly & Trend Detection Agent", "anomaly", {"station_id": st["id"], "domain": domain}) as step:
        bundle = get_bundle(domain, now)
        step.tool("ml.isolation_forest.fit_or_cache", {"domain": domain, "trained_until": bundle["trained_until"]},
                  {"n_train": bundle["n_train"], "threshold": bundle["threshold"], "features": bundle["columns"]})
        recent = wide[wide.index > wide.index.max() - timedelta(hours=72)] if not wide.empty else wide
        sc = am.score(bundle, recent, domain, st["id"], bundle["weather"]) if len(recent) else None
        result = {"model": "IsolationForest + robust z-score + Theil-Sen", "domain": domain}
        if sc is not None and len(sc):
            last24 = sc[sc.index > sc.index.max() - timedelta(hours=24)]
            latest = sc.iloc[-1]
            result.update({
                "latest_score": round(float(latest.score), 3), "latest_is_anomaly": bool(latest.is_anomaly),
                "latest_top_contributors": [{"parameter": p, "robust_z": z} for p, z in latest.top],
                "max_score_24h": round(float(last24.score.max()), 3), "anomalous_hours_24h": int(last24.is_anomaly.sum()),
                "first_anomalous_hour_24h": last24[last24.is_anomaly].index.min() if last24.is_anomaly.any() else None,
                "series": [{"timestamp": t, "score": round(float(r.score), 3), "is_anomaly": bool(r.is_anomaly)} for t, r in sc.iterrows()]})
            step.tool("ml.isolation_forest.score", {"station_id": st["id"], "hours": len(recent)},
                      {k: result[k] for k in ("latest_score", "latest_is_anomaly", "max_score_24h", "anomalous_hours_24h")})
            tops = [p for p, z in latest.top if abs(z) >= 2.5]
            result["unusual_combination"] = bool(latest.is_anomaly and len(tops) >= 2)
            result["combination_parameters"] = tops
        # robust z-scores of latest values
        zs = {}
        for p in [c for c in am.FEATURES[domain] if c in wide]:
            s = wide[p].dropna()
            if len(s) > 48:
                zs[p] = round(float(am.robust_z(s[s.index <= s.index.max() - timedelta(hours=48)], float(s.iloc[-1]))), 2)
        result["latest_robust_z"] = zs
        # sensor-level anomalies from validation
        val = state.get("validation", {})
        result["sensor_flags"] = val.get("recent_suspects", [])
        result["stale"] = any(i["type"] == "stale_sensor" for i in val.get("issues", []))
        # trend / gradual deterioration
        trends = {f["parameter"]: f.get("trend", {}) for f in state.get("findings", [])}
        bad_dir = {"dissolved_oxygen": "decreasing"}
        result["gradual_deterioration"] = [p for p, t in trends.items() if t.get("direction") == bad_dir.get(p, "increasing")]
        # water change classification
        changes = [classify_change(c, val, wide, state.get("weather_context", {})) for c in state.get("water_changes", [])]
        result["classified_changes"] = changes
        needs = []
        if result.get("anomalous_hours_24h", 0) >= 3:
            needs.append(f"{result['anomalous_hours_24h']} anomalous hour(s) in the last 24 h (max score {result['max_score_24h']}).")
        if result.get("unusual_combination"):
            needs.append(f"Unusual multi-parameter pattern: {', '.join(result['combination_parameters'])}.")
        for c in changes:
            needs.append(f"{c['parameter']} change classified as {c['classification'].replace('_', ' ')}.")
        if result["sensor_flags"]:
            needs.append(f"{len(result['sensor_flags'])} reading(s) flagged for sensor verification.")
        result["events_requiring_investigation"] = needs
        gen = llm.generate(PROMPTS["anomaly"], json.dumps(clean({k: v for k, v in result.items() if k != "series"}), default=str))
        step.llm_used = bool(gen)
        result["interpretation"] = gen or (" ".join(needs) if needs else "Readings are consistent with the station's historical baseline.")
        step.output = {k: v for k, v in result.items() if k != "series"}
    return {"anomaly": result, "trace": [step.record()],
            "events": [event("ANOMALY_SCORED", {"latest_score": result.get("latest_score"), "anomalous_hours_24h": result.get("anomalous_hours_24h"),
                                                 "sensor_flags": len(result["sensor_flags"])})]}
