"""Read-side analytics used by the API (dashboard, domain pages, map, forecasts, simulation)."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from ..agents.alert import RANK
from ..agents.domain_common import analyze_parameter, template_interpretation
from ..config import NETWORK_ID
from ..database import Alert, Incident, Measurement, PipelineRun, SessionLocal, Station
from ..ml.forecast_model import train_and_forecast
from ..tools import data_access as da
from ..tools.compliance import noise_periods
from ..tools.validation import CANONICAL_UNITS, LABELS, validate_long
from ..utils import clean, now
from .weather_api import fetch_current

DOMAIN_TYPES = {"air": "air_quality", "water": "water_quality", "noise": "noise"}
_FC_CACHE: dict = {}


class _NullStep:
    def tool(self, name, args, result):
        return result

    tool_calls: list = [{}]


def station_status(db, s: Station) -> dict:
    alerts = db.query(Alert).filter(Alert.station_id == s.id, Alert.status.in_(["open", "acknowledged", "confirmed"])).all()
    top = max(alerts, key=lambda a: a.priority_rank, default=None)
    last = da.latest_time(db, s.id)
    stale = last is None or (now() - last) > timedelta(hours=3)
    status = "offline" if s.operational_status == "offline" else ("stale" if stale else (top.category if top else "Normal"))
    return {"alert_category": top.category if top else "Normal", "open_alerts": len(alerts), "last_measurement": last.isoformat() if last else None,
            "stale": stale, "status": status}


def latest_readings(db, station_id: str) -> dict:
    long = da.load_long(db, [station_id], start=now() - timedelta(hours=6) - timedelta(days=2))
    if long.empty:
        return {}
    long = long[long.value.notna()]
    out = {}
    for p, g in long.groupby("parameter"):
        r = g.iloc[-1]
        out[p] = {"value": round(float(r.value), 3), "unit": r.unit, "timestamp": r.timestamp.isoformat(), "quality_flag": r.quality_flag,
                  "label": LABELS.get(p, p)}
    return out


def domain_summary(domain: str) -> dict:
    mt = DOMAIN_TYPES[domain]
    db = SessionLocal()
    try:
        stations = db.query(Station).filter(Station.monitoring_type == mt).all()
        out = []
        for s in stations:
            sd = da.station_dict(s)
            long = da.load_long(db, [s.id], start=now() - timedelta(days=30))
            checked, _ = validate_long(long) if not long.empty else (long, [])
            wide = da.to_wide(checked) if not checked.empty else pd.DataFrame()
            params = []
            for p in sd["parameters"]:
                f = analyze_parameter(_NullStep(), sd, wide, p)
                f["ai_interpretation"] = template_interpretation(f)
                params.append(f)
            out.append({"station": sd, **station_status(db, s), "parameters": params})
        return clean({"domain": domain, "stations": out, "generated_at": now()})
    finally:
        db.close()


def series(station_id: str, hours: int = 168, parameters: list[str] | None = None) -> dict:
    db = SessionLocal()
    try:
        long = da.load_long(db, [station_id], start=now() - timedelta(hours=hours), parameters=parameters)
        if long.empty:
            return {"station_id": station_id, "points": [], "flags": []}
        wide = da.to_wide(long, usable_only=False)
        pts = [{"timestamp": t.isoformat(), **{c: (None if pd.isna(v) else round(float(v), 3)) for c, v in row.items()}} for t, row in wide.iterrows()]
        flags = [{"timestamp": r.timestamp.isoformat(), "parameter": r.parameter, "value": r.value, "flag": r.quality_flag, "reason": r.flag_reason, "id": int(r.id)}
                 for r in long[~long.quality_flag.isin(["valid"])].itertuples()]
        return clean({"station_id": station_id, "units": {p: CANONICAL_UNITS.get(p) for p in wide.columns}, "points": pts, "flags": flags})
    finally:
        db.close()


def noise_analysis(station_id: str) -> dict:
    db = SessionLocal()
    try:
        s = db.get(Station, station_id)
        sd = da.station_dict(s)
        long = da.load_long(db, [station_id], start=now() - timedelta(days=30), parameters=["noise_laeq"])
        wide = da.to_wide(long)
        ser = wide["noise_laeq"] if "noise_laeq" in wide else pd.Series(dtype=float)
        f = analyze_parameter(_NullStep(), sd, wide, "noise_laeq")
        periods = noise_periods(ser, days=14)
        recent = ser[ser.index > ser.index.max() - timedelta(days=14)]
        heat = [{"date": str(t.date()), "hour": int(t.hour), "value": None if pd.isna(v) else round(float(v), 1)} for t, v in recent.items()]
        lim = {c["standard"]["averaging_period"]: c["standard"]["limit"] for c in f["comparisons"]}
        for p in periods:
            L = lim.get(p["period"])
            p["limit"] = L
            p["exceeded"] = bool(L is not None and p["leq"] is not None and p["leq"] > L and p["coverage"] >= 0.75)
        return clean({"station": sd, "limits": lim, "periods": periods, "heatmap": heat,
                      "standards": [c["standard"] for c in f["comparisons"]],
                      "repeated_night_periods": sum(1 for p in periods if p["period"] == "night" and p["exceeded"])})
    finally:
        db.close()


def forecast(station_id: str, parameter: str = "pm2_5", horizon: int = 24) -> dict:
    key = (station_id, parameter, horizon, now().strftime("%Y%m%d%H"))
    if key in _FC_CACHE:
        return _FC_CACHE[key]
    db = SessionLocal()
    try:
        s = db.get(Station, station_id)
        long = da.load_long(db, [station_id], start=now() - timedelta(days=30), parameters=[parameter])
        wide = da.to_wide(long)
        wx = da.weather_frame(db, start=now() - timedelta(days=31))
    finally:
        db.close()
    if parameter not in wide or wide[parameter].notna().sum() < 24 * 10:
        return {"error": "not enough history for forecasting (need ≥10 days)"}
    live = fetch_current(s.latitude, s.longitude)
    fw = None
    if live and live.get("hourly_forecast"):
        fw = pd.DataFrame(live["hourly_forecast"]).assign(timestamp=lambda d: pd.to_datetime(d.time)).set_index("timestamp")
    res = train_and_forecast(wide[parameter], wx, horizon, fw)
    hist = wide[parameter].dropna()
    hist = hist[hist.index > hist.index.max() - timedelta(hours=72)]
    out = clean({"station_id": station_id, "parameter": parameter, "unit": CANONICAL_UNITS.get(parameter),
                 "history": [{"timestamp": t, "value": round(float(v), 2)} for t, v in hist.items()], **res})
    _FC_CACHE.clear()
    _FC_CACHE[key] = out
    return out


def map_data() -> dict:
    db = SessionLocal()
    try:
        out = []
        for s in db.query(Station).all():
            st = station_status(db, s)
            lr = latest_readings(db, s.id)
            key = {"air_quality": "pm2_5", "water_quality": "turbidity", "noise": "noise_laeq"}[s.monitoring_type]
            out.append({**da.station_dict(s), **st, "key_parameter": key, "key_reading": lr.get(key)})
        return clean({"stations": out, "sources": da.sources(db), "network_id": NETWORK_ID})
    finally:
        db.close()


def dashboard() -> dict:
    db = SessionLocal()
    try:
        stations = db.query(Station).all()
        st_rows = []
        for s in stations:
            st_rows.append({"id": s.id, "name": s.name, "monitoring_type": s.monitoring_type, **station_status(db, s),
                            "latest": latest_readings(db, s.id)})
        net = db.query(PipelineRun).filter(PipelineRun.scope == "NETWORK").order_by(PipelineRun.started_at.desc()).first()
        open_inc = db.query(Incident).filter(Incident.status != "closed").all()
        alerts = db.query(Alert).filter(Alert.status.in_(["open", "acknowledged", "confirmed"])).all()

        def worst(mt):
            rows = [r for r in st_rows if r["monitoring_type"] == mt]
            r = max(rows, key=lambda r: RANK.get(r["alert_category"], 0), default=None)
            return {"category": r["alert_category"] if r else "Normal", "station": r["id"] if r else None,
                    "stations": len(rows), "stale": sum(x["stale"] for x in rows)}

        def pick(mt, p):
            rows = [(r["id"], r["latest"].get(p)) for r in st_rows if r["monitoring_type"] == mt and r["latest"].get(p)]
            if not rows:
                return None
            sid, v = max(rows, key=lambda x: x[1]["value"] if p != "ph" else abs(x[1]["value"] - 7.5))
            return {**v, "station_id": sid}
        child_risk = {}
        if net and net.result:
            for c in net.result.get("children", []):
                child_risk[c["station_id"]] = (c.get("risk") or {})
        # air series for chart (48 h PM2.5 per air station)
        air_ids = [s.id for s in stations if s.monitoring_type == "air_quality"]
        long = da.load_long(db, air_ids, start=now() - timedelta(hours=48), parameters=["pm2_5"])
        air_series = []
        if not long.empty:
            pv = long[long.quality_flag.isin(["valid", "verified"])].drop_duplicates(["station_id", "timestamp"]).pivot(index="timestamp", columns="station_id", values="value")
            air_series = [{"timestamp": t.isoformat(), **{c: (None if pd.isna(v) else round(float(v), 1)) for c, v in r.items()}} for t, r in pv.iterrows()]
        long14 = da.load_long(db, air_ids, start=now() - timedelta(days=14), parameters=["pm2_5"])
        trend = []
        if not long14.empty:
            d = long14[long14.quality_flag.isin(["valid", "verified"])].set_index("timestamp")["value"].resample("D").mean()
            trend = [{"date": str(t.date()), "pm2_5": round(float(v), 1)} for t, v in d.items() if not np.isnan(v)]
        return clean({
            "network_id": NETWORK_ID, "generated_at": now(),
            "last_run": {"id": net.id, "status": net.status, "started_at": net.started_at, "finished_at": net.finished_at,
                         "events": net.events, "risk": net.risk, "human_decision": net.human_decision} if net else None,
            "parameters": {"pm2_5": pick("air_quality", "pm2_5"), "pm10": pick("air_quality", "pm10"), "ph": pick("water_quality", "ph"),
                           "turbidity": pick("water_quality", "turbidity"), "noise": pick("noise", "noise_laeq")},
            "domain_status": {"air": worst("air_quality"), "water": worst("water_quality"), "noise": worst("noise")},
            "counts": {"stations": len(stations), "active": sum(not r["stale"] for r in st_rows), "sensor_failures": sum(r["stale"] for r in st_rows)
                       + sum(1 for a in alerts if a.category == "Sensor Verification Required" and a.parameter != "*"),
                       "open_incidents": len(open_inc), "critical_alerts": sum(a.category == "Critical Review Required" for a in alerts),
                       "open_alerts": len(alerts), "open_investigations": sum(i.status in ("investigating", "field_inspection_requested", "under_review", "escalated") for i in open_inc)},
            "stations": [{k: v for k, v in r.items() if k != "latest"} | {"risk": child_risk.get(r["id"], {}).get("score")} for r in st_rows],
            "critical_alerts": [{"id": a.id, "title": a.title, "station_id": a.station_id, "category": a.category, "last_seen": a.last_seen}
                                for a in sorted(alerts, key=lambda a: -a.priority_rank)[:6]],
            "air_series": air_series, "pm25_daily_trend": trend})
    finally:
        db.close()


def simulate(station_id: str, scenario: str = "normal") -> dict:
    """Simulated IoT stream: append one hourly reading per parameter after the station's latest timestamp."""
    rng = np.random.default_rng()
    db = SessionLocal()
    try:
        s = db.get(Station, station_id)
        long = da.load_long(db, [station_id], start=now() - timedelta(days=3))
        last = long.timestamp.max() if not long.empty else pd.Timestamp(now()).floor("h")
        ts = (last + pd.Timedelta(hours=1)).to_pydatetime()
        med = long[long.value.notna()].groupby("parameter").value.apply(lambda v: v.tail(24).median()).to_dict()
        rows = []
        for p in s.parameters:
            v = float(med.get(p, 1.0)) * float(rng.normal(1, 0.06))
            if p == "noise_laeq":
                v = float(med.get(p, 50)) + float(rng.normal(0, 1.5))
            if scenario == "exceedance" and p in ("pm2_5", "pm10", "no2"):
                v *= 2.2
            if scenario == "spike" and p == "co":
                v = 45.0
            if scenario == "turbidity_rise" and p == "turbidity":
                v *= 3.5
            if scenario == "turbidity_rise" and p == "dissolved_oxygen":
                v *= 0.75
            if scenario == "night_noise" and p == "noise_laeq":
                v = 58 + float(rng.normal(0, 1))
            if scenario == "missing" and p == rng.choice(s.parameters):
                v = None
            rows.append({"station_id": station_id, "timestamp": ts, "parameter": p, "value": None if v is None else round(v, 3), "unit": CANONICAL_UNITS[p]})
        res = ingest_rows(db, rows, source=f"simulated-iot:{scenario}")
        return {"timestamp": ts.isoformat(), "scenario": scenario, "readings": rows, **res}
    finally:
        db.close()


def ingest_rows(db, rows: list[dict], source: str = "api") -> dict:
    """Normalise, validate (in context of the last 48 h) and store measurement rows."""
    from ..tools.validation import canonical_parameter, normalize_unit
    issues, stored, rejected = [], 0, []
    clean_rows = []
    for r in rows:
        p = canonical_parameter(r.get("parameter", ""))
        st = db.get(Station, r.get("station_id"))
        if not p or not st:
            rejected.append({**r, "reason": "unknown station" if not st else f"unknown parameter '{r.get('parameter')}'"})
            continue
        try:
            ts = pd.Timestamp(r["timestamp"]).to_pydatetime().replace(tzinfo=None)
        except Exception:  # noqa: BLE001
            rejected.append({**r, "reason": "invalid timestamp"})
            continue
        val = r.get("value")
        val = None if val in ("", None) or (isinstance(val, float) and np.isnan(val)) else float(val)
        v, unit, issue = normalize_unit(p, val, r.get("unit") or CANONICAL_UNITS[p])
        if issue:
            issues.append({"type": "invalid_unit", "parameter": p, "detail": issue})
        clean_rows.append({"station_id": st.id, "timestamp": ts, "parameter": p, "value": v, "unit": unit,
                           "quality_flag": "suspect" if issue else ("missing" if v is None else "valid"), "flag_reason": issue or ""})
    if clean_rows:
        new = pd.DataFrame(clean_rows)
        for sid, g in new.groupby("station_id"):
            ctx = da.load_long(db, [sid], start=g.timestamp.min() - timedelta(hours=48), end=g.timestamp.max())
            ctx = ctx.drop(columns=["id"]) if not ctx.empty else ctx
            both = pd.concat([ctx.assign(_new=False), g.assign(_new=True)], ignore_index=True)
            checked, iss = validate_long(both.drop(columns=["_new"]))
            checked["_new"] = both.loc[checked.index, "_new"]
            fresh = checked[checked["_new"]]
            dropped = len(g) - len(fresh)
            if dropped:
                issues.append({"type": "duplicate_timestamp", "detail": f"{dropped} row(s) duplicate existing readings and were not stored"})
            issues += [i for i in iss if i.get("timestamp") is None or i["timestamp"] >= g.timestamp.min()]
            for r in fresh.itertuples():
                db.add(Measurement(station_id=sid, timestamp=r.timestamp, parameter=r.parameter, value=None if pd.isna(r.value) else float(r.value),
                                   unit=r.unit, quality_flag=r.quality_flag, flag_reason=r.flag_reason, source=source))
                stored += 1
            st = db.get(Station, sid)
            valid_ts = fresh[fresh.value.notna()].timestamp
            if len(valid_ts) and (st.last_communication is None or valid_ts.max() > st.last_communication):
                st.last_communication = valid_ts.max().to_pydatetime()
        db.commit()
    return clean({"stored": stored, "rejected": rejected, "issues": issues})
