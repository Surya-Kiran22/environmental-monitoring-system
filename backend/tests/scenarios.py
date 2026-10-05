"""TC-01 … TC-08 scenario definitions shared by pytest (tests/test_scenarios.py) and the
documentation generator (scripts/run_test_scenarios.py). Each returns a fully documented record."""
from __future__ import annotations

import re
from datetime import timedelta

import numpy as np
import pandas as pd

from app.utils import now

AGENTS_AIR = ["Intake & Validation", "Air Quality", "Weather & Context", "Anomaly & Trend", "Alert & Investigation", "Standards Reviewer"]
CAUSAL = re.compile(r"\b(caused by|caused|due to|because of|responsible for)\b", re.I)


def _station(c, sid, mtype, zone, lat, lon, params, water_class=None):
    c.post("/api/stations", json={"id": sid, "name": f"Test {sid}", "monitoring_type": mtype, "location": f"Test site {sid}",
                                   "latitude": lat, "longitude": lon, "zone_category": zone, "water_class": water_class, "parameters": params})


def _ingest(c, sid, frame: pd.DataFrame, units: dict):
    rows = [{"station_id": sid, "timestamp": t.isoformat(), "parameter": p, "value": None if pd.isna(v) else float(v), "unit": units[p]}
            for t, r in frame.iterrows() for p, v in r.items()]
    for i in range(0, len(rows), 4000):
        res = c.post("/api/ingest/measurements", json=rows[i:i + 4000])
        assert res.status_code == 200, res.text


AIR_UNITS = {"pm2_5": "µg/m³", "pm10": "µg/m³", "no2": "µg/m³", "so2": "µg/m³", "co": "mg/m³", "o3": "µg/m³"}


def air_frame(seed: int, days: int = 10, last24_pm: float | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=pd.Timestamp(now()).floor("h"), periods=days * 24, freq="h")
    h = idx.hour.values
    di = 1 + 0.2 * np.cos(2 * np.pi * (h - 8) / 24)
    pm = 30 * di * rng.lognormal(0, 0.06, len(idx))
    if last24_pm:
        pm[-24:] = last24_pm * rng.lognormal(0, 0.04, 24)
    return pd.DataFrame({"pm2_5": pm, "pm10": pm * 1.6, "no2": 25 * di * rng.lognormal(0, 0.06, len(idx)),
                         "so2": 10 * rng.lognormal(0, 0.06, len(idx)), "co": 0.6 * di * rng.lognormal(0, 0.05, len(idx)),
                         "o3": 35 + 20 * np.clip(np.sin(2 * np.pi * (h - 7) / 24), 0, None) + rng.normal(0, 2, len(idx))}, index=idx).round(3)


def _run(c, sid):
    r = c.post("/api/pipeline/run", json={"station_id": sid, "trigger": "test"}).json()
    return r, c.get(f"/api/pipeline/runs/{r['run_id']}").json()


def _agents(run):
    return [t["agent"] for t in run["trace"]]


def tc01(c):
    _station(c, "TST-AIR-N", "air_quality", "residential", 17.70, 83.30, list(AIR_UNITS))
    _ingest(c, "TST-AIR-N", air_frame(1), AIR_UNITS)
    r, run = _run(c, "TST-AIR-N")
    alerts = run["result"]["draft"]["alerts"]
    persisted = run["result"]["persisted"]
    ok = r["status"] == "completed_no_alert" and not persisted and all(a["priority_rank"] < 2 for a in alerts)
    return {"id": "TC-01", "scenario": "Normal environmental readings", "expected": "No unnecessary pollution alert",
            "input": "10 days hourly air data, PM2.5 ≈ 30 µg/m³ with diurnal cycle (TST-AIR-N, residential)",
            "initial_state": "New station, no alerts/incidents", "agents": _agents(run),
            "actual": f"status={r['status']}, overall={r['overall_category']}, persisted alerts={len(persisted)}",
            "model_output": {"anomaly_latest_score": run["result"]["anomaly"].get("latest_score"),
                             "anomalous_hours_24h": run["result"]["anomaly"].get("anomalous_hours_24h"), "risk": r["risk"].get("score")},
            "evidence": run["result"]["draft"]["summary"], "passed": ok}


def tc02(c):
    _station(c, "TST-AIR-E", "air_quality", "industrial", 17.72, 83.32, list(AIR_UNITS))
    _ingest(c, "TST-AIR-E", air_frame(2, last24_pm=95), AIR_UNITS)
    r, run = _run(c, "TST-AIR-E")
    f = next(x for x in run["result"]["findings"] if x["parameter"] == "pm2_5")
    pr = f["primary"]
    a = next((x for x in run["result"]["draft"]["alerts"] if x["parameter"] == "pm2_5"), None)
    exp_d = round(pr["period_value"] - 60, 3)
    ok = (a is not None and a["alert_type"].startswith("threshold_exceedance") and a["standard_ref"]["id"] == "IN-NAAQS-PM25-24H"
          and abs(pr["difference"] - exp_d) < 0.01 and abs(pr["percentage_difference"] - round(exp_d / 60 * 100, 1)) < 0.11
          and pr["comparison_valid"] and len(run["result"]["persisted"]) > 0)
    return {"id": "TC-02", "scenario": "Pollutant exceeds configured reference", "expected": "Environmental alert generated",
            "input": "9 normal days + last 24 h PM2.5 ≈ 95 µg/m³ (TST-AIR-E, industrial)", "initial_state": "New station, no alerts",
            "agents": _agents(run), "actual": f"{a and a['category']}: {a and a['title']}",
            "model_output": {"period_value": pr["period_value"], "limit": pr["limit_text"], "difference": pr["difference"],
                             "pct": pr["percentage_difference"], "coverage": pr["coverage"], "standard": pr["standard"]["id"]},
            "evidence": a and a["why"], "passed": ok}


def tc03(c):
    _station(c, "TST-AIR-S", "air_quality", "residential", 17.74, 83.34, list(AIR_UNITS))
    fr = air_frame(3)
    fr.iloc[-5, fr.columns.get_loc("co")] = 45.0
    _ingest(c, "TST-AIR-S", fr, AIR_UNITS)
    r, run = _run(c, "TST-AIR-S")
    alerts = run["result"]["draft"]["alerts"]
    sens = [a for a in alerts if a["category"] == "Sensor Verification Required" and a["parameter"] == "co"]
    co_exc = [a for a in alerts if a["parameter"] == "co" and a["alert_type"].startswith("threshold")]
    ok = bool(sens) and not co_exc
    return {"id": "TC-03", "scenario": "Sudden unrealistic sensor spike", "expected": "Sensor verification requested",
            "input": "Normal air data with a single CO reading of 45 mg/m³ 5 h ago (baseline ≈ 0.6)", "initial_state": "New station",
            "agents": _agents(run), "actual": f"{sens[0]['category']}: {sens[0]['title']}" if sens else "no sensor alert",
            "model_output": {"validation_suspects": run["result"]["validation"]["recent_suspects"][:2], "co_threshold_alert": bool(co_exc)},
            "evidence": sens and sens[0]["supporting"], "passed": ok}


def tc04(c):
    units = {"ph": "pH", "dissolved_oxygen": "mg/L", "turbidity": "NTU", "conductivity": "µS/cm", "tds": "mg/L", "water_temperature": "°C"}
    _station(c, "TST-WQ", "water_quality", "water_body", 17.76, 83.36, list(units), water_class="C")
    rng = np.random.default_rng(4)
    idx = pd.date_range(end=pd.Timestamp(now()).floor("h"), periods=240, freq="h")
    fr = pd.DataFrame({"ph": 7.5 + rng.normal(0, 0.05, 240), "dissolved_oxygen": 6.8 + rng.normal(0, 0.1, 240),
                       "turbidity": 3.2 + rng.normal(0, 0.2, 240), "conductivity": 420 + rng.normal(0, 8, 240),
                       "water_temperature": 27 + rng.normal(0, 0.2, 240)}, index=idx)
    fr.iloc[-7:, fr.columns.get_loc("turbidity")] = [3.2, 4.1, 5.6, 7.4, 9.3, 11.2, 12.8]
    fr.iloc[-7:, fr.columns.get_loc("dissolved_oxygen")] = np.linspace(6.8, 5.3, 7)
    fr.iloc[-7:, fr.columns.get_loc("conductivity")] = np.linspace(420, 560, 7)
    fr["tds"] = fr.conductivity * 0.64
    _ingest(c, "TST-WQ", fr.round(3), units)
    r, run = _run(c, "TST-WQ")
    an = run["result"]["anomaly"]
    ch = next((x for x in an["classified_changes"] if x["parameter"] == "turbidity"), None)
    a = next((x for x in run["result"]["draft"]["alerts"] if x["parameter"] == "turbidity"), None)
    ok = ch is not None and a is not None and a["priority_rank"] >= 3 and ch["classification"] in ("valid_environmental_change", "sensor_anomaly", "undetermined")
    return {"id": "TC-04", "scenario": "Water turbidity rises significantly", "expected": "Water-quality anomaly identified",
            "input": "Turbidity 3.2 → 12.8 NTU over 6 h with DO decline and conductivity rise (TST-WQ, Class C)", "initial_state": "New station",
            "agents": [t["agent"] for t in run["trace"]], "actual": f"{a and a['category']}: {a and a['title']}; change classified as {ch and ch['classification']}",
            "model_output": {"latest_score": an.get("latest_score"), "unusual_combination": an.get("unusual_combination"), "change": ch},
            "evidence": ch and ch["classification_reason"], "passed": ok}


def tc05(c):
    _station(c, "TST-NS", "noise", "residential", 17.78, 83.38, ["noise_laeq"])
    rng = np.random.default_rng(5)
    idx = pd.date_range(end=pd.Timestamp(now()).floor("h"), periods=240, freq="h")
    h = idx.hour.values
    night = (h >= 22) | (h < 6)
    lv = np.where(night, 41.5, 51.5) + rng.normal(0, 1.2, 240)
    late = ((h >= 22) | (h <= 1)) & (idx > idx.max() - pd.Timedelta(days=5, hours=6))
    lv[late] = 57 + rng.normal(0, 1, late.sum())
    _ingest(c, "TST-NS", pd.DataFrame({"noise_laeq": lv}, index=idx).round(2), {"noise_laeq": "dB(A)"})
    r, run = _run(c, "TST-NS")
    a = next((x for x in run["result"]["draft"]["alerts"] if x["alert_type"] == "persistent_elevated"), None)
    inc = run["result"]["incidents"]
    night = run["result"]["findings"][0]["noise"]["night"]
    ok = a is not None and len(inc) == 1
    return {"id": "TC-05", "scenario": "Repeated high nighttime noise", "expected": "Noise incident generated",
            "input": "Residential noise station; 22:00–02:00 at ≈57 dB(A) on the last 5 nights (limit 45 dB(A) night)", "initial_state": "New station",
            "agents": _agents(run), "actual": f"{a and a['category']}: {a and a['title']}; incident {inc}",
            "model_output": {"night_leq_latest": night.get("period_value"), "exceedances": night.get("exceedance_count"),
                             "periods_assessed": night.get("periods_assessed")}, "evidence": a and a["supporting"], "passed": ok}


def tc06(c):
    # isolated cluster (>20 km from the Vijayawada network) so the comparison group is exactly A, B, C
    for sid, lat, lon in (("TST-X-A", 17.400, 78.480), ("TST-X-B", 17.420, 78.500), ("TST-X-C", 17.440, 78.470)):
        _station(c, sid, "air_quality", "commercial", lat, lon, list(AIR_UNITS))
    _ingest(c, "TST-X-A", air_frame(61, last24_pm=90), AIR_UNITS)
    _ingest(c, "TST-X-B", air_frame(62, last24_pm=85), AIR_UNITS)
    _ingest(c, "TST-X-C", air_frame(63), AIR_UNITS)
    r, run = _run(c, "TST-X-A")
    cs = run["result"]["cross_station"]
    ok = cs["station_count"] == 3 and cs["elevated_count"] == 2 and cs["classification"] in ("distributed", "partially_distributed") \
        and "does not identify a pollution source" in cs["summary"]
    return {"id": "TC-06", "scenario": "Multiple stations show elevated pollutant", "expected": "Cross-station analysis performed",
            "input": "Station A PM2.5 ≈ 90, B ≈ 85, C normal (≈30) in the last 24 h, all within 5 km", "initial_state": "Three new stations",
            "agents": _agents(run), "actual": f"{cs['classification']}: {cs['summary']}",
            "model_output": {s["station_id"]: {"mean_24h": s["recent_mean"], "elevated": s["elevated"], "distance_km": s["distance_km"]} for s in cs["stations"]},
            "evidence": cs["summary"], "passed": ok}


def tc07(c):
    r, run = _run(c, "ENV-ST-004")
    wx = run["result"]["weather_context"]
    texts = [wx.get("interpretation", ""), run["result"]["draft"]["summary"]] + [a["ai_interpretation"] for a in run["result"]["draft"]["alerts"]]
    causal = [m.group(0) for t in texts for m in CAUSAL.finditer(t or "")]
    review = run["result"]["review"]
    ok = bool(wx.get("observations")) and wx.get("weather_changing") and not causal and \
        next(ch for ch in review["checks"] if ch["check"].startswith("no unsupported"))["passed"] and wx["current"]["source"]
    return {"id": "TC-07", "scenario": "Pollution rises during changing weather", "expected": "Weather context included without unsupported causation",
            "input": "Dataset station ENV-ST-004: PM episode under low wind (≈1.3 m/s), wind rising to 4.5 m/s in the last 3 h", "initial_state": "Seeded demo network",
            "agents": _agents(run), "actual": " | ".join(wx["observations"]),
            "model_output": {"weather_source": wx["current"]["source"], "association": wx.get("association_wind"), "causal_phrases_found": causal,
                             "reviewer_verdict": review["verdict"]}, "evidence": wx.get("event_window"), "passed": bool(ok)}


def tc08(c):
    f = c.get("/api/forecast/ENV-ST-004", params={"parameter": "pm2_5", "horizon": 24}).json()
    m = f["metrics_one_step"]
    ok = len(f["forecast"]) == 24 and all(k in m for k in ("mae", "rmse", "mape_pct")) and f["backtest_24h"]["windows"] >= 1
    return {"id": "TC-08", "scenario": "Future pollutant values requested", "expected": "Forecast generated with model metrics",
            "input": "GET /api/forecast/ENV-ST-004?parameter=pm2_5&horizon=24", "initial_state": "Seeded demo network (30 days history)",
            "agents": ["Forecasting service (HistGradientBoosting)"], "actual": f"{len(f['forecast'])} hourly predictions, first {f['forecast'][0]}",
            "model_output": {"one_step": m, "persistence_baseline": f["persistence_baseline_one_step"], "backtest_24h": f["backtest_24h"]},
            "evidence": f["future_weather_source"], "passed": ok}


ALL = [tc01, tc02, tc03, tc04, tc05, tc06, tc07, tc08]
