"""Environmental report assembly (structured JSON) — rendered to PDF by reports/pdf_report.py."""
from __future__ import annotations

from datetime import timedelta

from ..database import Alert, Incident, IncidentAction, PipelineRun, Report, SessionLocal, Station
from ..ml.anomaly_model import get_metrics
from ..tools import data_access as da
from ..utils import clean, new_id, now
from .analysis import forecast


def generate(station_ids: list[str] | None = None, hours: int = 168, created_by: str = "system") -> dict:
    db = SessionLocal()
    try:
        end = now()
        start = end - timedelta(hours=hours)
        stations = db.query(Station).all()
        if station_ids:
            stations = [s for s in stations if s.id in station_ids]
        ids = [s.id for s in stations]
        sections = {"air": [], "water": [], "noise": []}
        comparisons, anomalies, weather, standards_used = [], [], None, {}
        for s in stations:
            run = (db.query(PipelineRun).filter(PipelineRun.scope == s.id, PipelineRun.status != "failed")
                   .order_by(PipelineRun.started_at.desc()).first())
            if not run or not run.result:
                continue
            res = run.result
            dom = {"air_quality": "air", "water_quality": "water", "noise": "noise"}[s.monitoring_type]
            draft = res.get("draft") or {}
            sections[dom].append({"station_id": s.id, "name": s.name, "location": s.location, "run_id": run.id,
                                  "category": draft.get("overall_category"), "risk": (draft.get("risk") or {}).get("score"),
                                  "summary": res.get("domain_summary"), "alert_summary": draft.get("summary"),
                                  "trends": {f["parameter"]: (f.get("trend") or {}).get("direction") for f in res.get("findings", [])}})
            for f in res.get("findings", []):
                pr = f.get("primary")
                if pr and pr.get("period_value") is not None:
                    std = pr["standard"]
                    comparisons.append({"station_id": s.id, "parameter": f["label"], "measured": pr.get("period_value"), "period": pr.get("period_label"),
                                        "limit": pr.get("limit_text"), "averaging": std.get("averaging_period"), "difference": pr.get("difference"),
                                        "pct": pr.get("percentage_difference"), "status": pr.get("status"), "standard_id": std.get("id")})
                    standards_used[std["id"]] = {k: std.get(k) for k in ("id", "standard_name", "section", "source_doc", "version", "basis")}
            an = res.get("anomaly") or {}
            if an.get("events_requiring_investigation"):
                anomalies.append({"station_id": s.id, "latest_score": an.get("latest_score"), "anomalous_hours_24h": an.get("anomalous_hours_24h"),
                                  "items": an["events_requiring_investigation"]})
            if weather is None and res.get("weather_context"):
                weather = res["weather_context"]
        incs = db.query(Incident).filter(Incident.station_id.in_(ids)).order_by(Incident.created_at.desc()).all()
        incidents = []
        for i in incs:
            acts = db.query(IncidentAction).filter(IncidentAction.incident_id == i.id).order_by(IncidentAction.timestamp).all()
            incidents.append({"id": i.id, "station_id": i.station_id, "parameter": i.parameter, "title": i.title, "priority": i.priority,
                              "status": i.status, "investigation_status": i.investigation_status, "start_time": i.start_time,
                              "actions": [{"action": a.action, "actor": a.actor, "note": a.note, "data": a.data, "timestamp": a.timestamp} for a in acts],
                              "recommendation": (i.recommendation or {}).get("recommended_action")})
        alerts = db.query(Alert).filter(Alert.station_id.in_(ids), Alert.last_seen >= start).all()
        fc_station = next((s.id for s in stations if s.monitoring_type == "air_quality"), None)
        fc = forecast(fc_station, "pm2_5", 24) if fc_station else None
        fc_summary = None
        if fc and not fc.get("error"):
            vals = [p["value"] for p in fc["forecast"]]
            fc_summary = {"station_id": fc_station, "parameter": "PM2.5", "model": fc["model"], "metrics_one_step": fc["metrics_one_step"],
                          "persistence_baseline": fc["persistence_baseline_one_step"], "backtest_24h": fc["backtest_24h"],
                          "next_24h_min": min(vals), "next_24h_max": max(vals), "next_24h_mean": round(sum(vals) / len(vals), 1),
                          "future_weather_source": fc["future_weather_source"]}
        recs = sorted({i["recommendation"] for i in incidents if i["recommendation"] and i["status"] != "closed"})
        content = clean({
            "title": "Environmental Monitoring Report", "monitoring_location": ", ".join(sorted({s.location.split(",")[-1].strip() for s in stations})),
            "stations": [{"id": s.id, "name": s.name, "type": s.monitoring_type, "location": s.location} for s in stations],
            "period": {"start": start, "end": end, "hours": hours}, "air": sections["air"], "water": sections["water"], "noise": sections["noise"],
            "weather": weather and {"current": weather.get("current"), "observations": weather.get("observations")},
            "anomalies": anomalies, "anomaly_model_metrics": get_metrics().get("domains"), "comparisons": comparisons,
            "forecast": fc_summary, "incidents": incidents,
            "alerts": [{"id": a.id, "station_id": a.station_id, "category": a.category, "title": a.title, "status": a.status, "occurrences": a.occurrences} for a in alerts],
            "recommended_actions": recs, "source_references": list(standards_used.values()),
            "disclaimer": "Decision-support output. Comparisons use configured standards; findings do not constitute legal determinations, "
                          "and no organisation is identified as the cause of any event without independent confirmation."})
        rep = Report(id=new_id("RPT"), created_at=end, period_start=start, period_end=end, station_ids=ids, content=content, status="draft")
        db.add(rep)
        db.commit()
        return report_dict(rep)
    finally:
        db.close()


def report_dict(r: Report) -> dict:
    return clean({"id": r.id, "created_at": r.created_at, "period_start": r.period_start, "period_end": r.period_end,
                  "station_ids": r.station_ids, "status": r.status, "approved_by": r.approved_by, "approved_at": r.approved_at, "content": r.content})
