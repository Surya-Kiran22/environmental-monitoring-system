"""REST API. Interactive docs at /docs (OpenAPI)."""
from __future__ import annotations

import io
from datetime import timedelta
from typing import Literal

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..agents.orchestrator import GRAPH_SPEC, run_network, run_station
from ..config import NETWORK_ID
from ..database import (Alert, Incident, IncidentAction, Measurement, PipelineRun, Report, SessionLocal, StandardRecord,
                        Station)
from ..ml.anomaly_model import get_metrics
from ..reports.pdf_report import render
from ..services import analysis, reports
from ..services.weather_api import current_with_fallback
from ..tools import bandit, rag
from ..tools import data_access as da
from ..tools import llm
from ..tools import standards as stdtool
from ..utils import clean, now

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ schemas
class StationIn(BaseModel):
    id: str = Field(..., examples=["ENV-ST-009"])
    name: str
    monitoring_type: Literal["air_quality", "water_quality", "noise"]
    location: str
    latitude: float
    longitude: float
    zone_category: Literal["industrial", "residential", "commercial", "silence", "rural", "water_body"]
    water_class: str | None = None
    jurisdiction: str = "IN"
    parameters: list[str]
    sensors: list[dict] = []
    operational_status: Literal["active", "maintenance", "offline"] = "active"
    notes: str = ""


class StationPatch(BaseModel):
    name: str | None = None
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    zone_category: str | None = None
    water_class: str | None = None
    parameters: list[str] | None = None
    sensors: list[dict] | None = None
    operational_status: str | None = None
    notes: str | None = None


class MeasurementIn(BaseModel):
    station_id: str
    timestamp: str
    parameter: str
    value: float | None
    unit: str


class SimulateIn(BaseModel):
    station_id: str
    scenario: Literal["normal", "exceedance", "spike", "turbidity_rise", "night_noise", "missing"] = "normal"
    analyze: bool = False


class FlagIn(BaseModel):
    quality_flag: Literal["valid", "verified", "invalid", "suspect"]
    reason: str = ""
    actor: str = "Environmental Officer"


class RunIn(BaseModel):
    station_id: str | None = None
    trigger: str = "manual_override"


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "request_reassessment"]
    actor: str = "Environmental Officer"
    note: str = ""


class AlertActionIn(BaseModel):
    action: Literal["acknowledge", "confirm", "reject", "close", "reopen"]
    actor: str = "Environmental Officer"
    note: str = ""


class IncidentActionIn(BaseModel):
    action: Literal["review", "verify_sensor", "request_field_inspection", "add_observation", "assign", "add_lab_result",
                    "confirm_anomaly", "reject_anomaly", "correct_regulatory_comparison", "start_investigation", "escalate", "close", "reopen"]
    actor: str = "Environmental Officer"
    note: str = ""
    assigned_to: str | None = None
    lab_result: dict | None = None


class FeedbackIn(BaseModel):
    useful: bool
    actor: str = "Environmental Officer"


class AskIn(BaseModel):
    question: str
    alert_id: str | None = None


class StandardIn(BaseModel):
    id: str
    standard_name: str
    issuer: str = ""
    jurisdiction: str = "IN"
    parameter: str
    limit_type: Literal["max", "min", "range"] = "max"
    limit: float | None = None
    min: float | None = None
    max: float | None = None
    averaging_period: Literal["1h", "8h", "24h", "annual", "day", "night", "instantaneous"]
    unit: str
    zones: list[str] | None = None
    water_classes: list[str] | None = None
    source_doc: str
    section: str
    version: str = ""
    basis: Literal["regulatory", "screening_benchmark", "site_baseline"] = "regulatory"
    note: str = ""


class ReportIn(BaseModel):
    station_ids: list[str] | None = None
    hours: int = 168


class ApproveIn(BaseModel):
    actor: str = "Environmental Officer"
    note: str = ""


# ------------------------------------------------------------------ health
@router.get("/health")
def health():
    return {"status": "ok", "time": now().isoformat(), "network": NETWORK_ID, "orchestration": GRAPH_SPEC["engine"],
            "llm": llm.enabled(), "llm_provider": llm.config.LLM_PROVIDER}


# ------------------------------------------------------------------ stations
@router.get("/stations")
def list_stations():
    db = SessionLocal()
    try:
        return [{**da.station_dict(s), **analysis.station_status(db, s)} for s in db.query(Station).all()]
    finally:
        db.close()


@router.post("/stations", status_code=201)
def create_station(body: StationIn):
    db = SessionLocal()
    try:
        if db.get(Station, body.id):
            raise HTTPException(409, "station id already exists")
        db.add(Station(**body.model_dump()))
        db.commit()
        return da.station_dict(db.get(Station, body.id))
    finally:
        db.close()


@router.get("/stations/{sid}")
def get_station(sid: str):
    db = SessionLocal()
    try:
        s = db.get(Station, sid) or _404("station")
        return {**da.station_dict(s), **analysis.station_status(db, s), "latest": analysis.latest_readings(db, sid)}
    finally:
        db.close()


@router.put("/stations/{sid}")
def update_station(sid: str, body: StationPatch):
    db = SessionLocal()
    try:
        s = db.get(Station, sid) or _404("station")
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(s, k, v)
        db.commit()
        return da.station_dict(s)
    finally:
        db.close()


@router.delete("/stations/{sid}")
def delete_station(sid: str):
    db = SessionLocal()
    try:
        s = db.get(Station, sid) or _404("station")
        s.operational_status = "offline"
        db.commit()
        return {"id": sid, "operational_status": "offline", "note": "stations are decommissioned (offline), not deleted, to preserve history"}
    finally:
        db.close()


# ------------------------------------------------------------------ data
@router.get("/live")
def live():
    db = SessionLocal()
    try:
        return clean([{**da.station_dict(s), **analysis.station_status(db, s), "latest": analysis.latest_readings(db, s.id)} for s in db.query(Station).all()])
    finally:
        db.close()


@router.get("/stations/{sid}/series")
def station_series(sid: str, hours: int = 168, parameters: str | None = None):
    return analysis.series(sid, hours, parameters.split(",") if parameters else None)


@router.post("/measurements/{mid}/flag")
def flag_measurement(mid: int, body: FlagIn):
    db = SessionLocal()
    try:
        m = db.get(Measurement, mid) or _404("measurement")
        m.quality_flag, m.flag_reason = body.quality_flag, f"{body.reason} (by {body.actor}, {now():%Y-%m-%d %H:%M})"
        db.commit()
        return {"id": mid, "quality_flag": m.quality_flag, "flag_reason": m.flag_reason}
    finally:
        db.close()


@router.post("/ingest/measurements")
def ingest_json(rows: list[MeasurementIn]):
    db = SessionLocal()
    try:
        return analysis.ingest_rows(db, [r.model_dump() for r in rows], source="rest-api")
    finally:
        db.close()


@router.post("/ingest/file")
async def ingest_file(file: UploadFile = File(...), station_id: str | None = Query(None)):
    raw = await file.read()
    name = (file.filename or "").lower()
    try:
        df = pd.read_excel(io.BytesIO(raw)) if name.endswith((".xlsx", ".xls")) else pd.read_csv(io.BytesIO(raw))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"could not parse file: {e}") from e
    df.columns = [c.strip().lower() for c in df.columns]
    if station_id and "station_id" not in df:
        df["station_id"] = station_id
    if {"parameter", "value"}.issubset(df.columns):
        rows = df.to_dict("records")
    else:  # wide format: station_id, timestamp, <param columns>
        from ..tools.validation import CANONICAL_UNITS, canonical_parameter
        pcols = [c for c in df.columns if canonical_parameter(c.split("(")[0].strip())]
        rows = []
        for r in df.to_dict("records"):
            for c in pcols:
                p = canonical_parameter(c.split("(")[0].strip())
                unit = c.split("(")[1].rstrip(")") if "(" in c else CANONICAL_UNITS[p]
                rows.append({"station_id": r.get("station_id"), "timestamp": r.get("timestamp"), "parameter": p, "value": r.get(c), "unit": unit})
    db = SessionLocal()
    try:
        res = analysis.ingest_rows(db, rows, source=f"file:{file.filename}")
        return {"file": file.filename, "rows_in_file": len(df), "measurements_parsed": len(rows), **res}
    finally:
        db.close()


@router.post("/ingest/simulate")
def simulate(body: SimulateIn):
    res = analysis.simulate(body.station_id, body.scenario)
    if body.analyze:
        res["pipeline"] = run_station(body.station_id, trigger=f"iot-stream:{body.scenario}")
    return res


# ------------------------------------------------------------------ analytics
@router.get("/dashboard")
def dashboard():
    return analysis.dashboard()


@router.get("/domain/{domain}")
def domain(domain: Literal["air", "water", "noise"]):
    return analysis.domain_summary(domain)


@router.get("/noise/{sid}")
def noise(sid: str):
    return analysis.noise_analysis(sid)


@router.get("/map")
def map_data():
    return analysis.map_data()


@router.get("/cross-station")
def cross(station_id: str, parameter: str = "pm2_5"):
    from ..tools.cross_station import cross_station
    return clean(cross_station(station_id, parameter, now()))


@router.get("/forecast/{sid}")
def forecast(sid: str, parameter: str = "pm2_5", horizon: int = Query(24, ge=1, le=72)):
    return analysis.forecast(sid, parameter, horizon)


@router.get("/models/anomaly")
def anomaly_metrics():
    return get_metrics()


@router.get("/weather/current")
def weather_current(station_id: str | None = None):
    db = SessionLocal()
    try:
        s = db.get(Station, station_id) if station_id else None
        lat, lon, loc = (s.latitude, s.longitude, s.location) if s else (16.5062, 80.6480, "Vijayawada")
        return clean(current_with_fallback(db, lat, lon, loc))
    finally:
        db.close()


@router.get("/weather/history")
def weather_history(hours: int = 168):
    db = SessionLocal()
    try:
        df = da.weather_frame(db, start=now() - timedelta(hours=hours), dataset_only=False)
        return clean([{"timestamp": t, **r} for t, r in df.to_dict("index").items()])
    finally:
        db.close()


# ------------------------------------------------------------------ pipeline / workflow state
@router.post("/pipeline/run")
def pipeline_run(body: RunIn):
    if body.station_id:
        return run_station(body.station_id, body.trigger)
    return run_network(body.trigger)


@router.post("/pipeline/run-network")
def pipeline_run_network(body: RunIn | None = None):
    return run_network((body.trigger if body else "manual_override"))


@router.get("/pipeline/graph")
def pipeline_graph():
    return GRAPH_SPEC


@router.get("/pipeline/runs")
def pipeline_runs(limit: int = 30, scope: str | None = None):
    db = SessionLocal()
    try:
        q = db.query(PipelineRun)
        if scope:
            q = q.filter(PipelineRun.scope == scope)
        return clean([{"id": r.id, "scope": r.scope, "trigger": r.trigger, "status": r.status, "started_at": r.started_at,
                       "finished_at": r.finished_at, "risk": r.risk, "parent_run": r.parent_run, "human_decision": r.human_decision}
                      for r in q.order_by(PipelineRun.started_at.desc()).limit(limit).all()])
    finally:
        db.close()


@router.get("/pipeline/runs/{rid}")
def pipeline_run_get(rid: str):
    db = SessionLocal()
    try:
        r = db.get(PipelineRun, rid) or _404("run")
        return clean({"id": r.id, "scope": r.scope, "trigger": r.trigger, "status": r.status, "started_at": r.started_at,
                      "finished_at": r.finished_at, "risk": r.risk, "result": r.result, "trace": r.trace, "events": r.events,
                      "human_decision": r.human_decision, "parent_run": r.parent_run})
    finally:
        db.close()


@router.post("/pipeline/runs/{rid}/decision")
def pipeline_decision(rid: str, body: DecisionIn):
    db = SessionLocal()
    try:
        r = db.get(PipelineRun, rid) or _404("run")
        dec = {"decision": body.decision, "actor": body.actor, "note": body.note, "timestamp": now().isoformat()}
        targets = [r] + db.query(PipelineRun).filter(PipelineRun.parent_run == rid).all()
        for t in targets:
            t.human_decision = dec
            t.status = {"approve": "approved", "reject": "rejected", "request_reassessment": "reassessment_requested"}[body.decision]
            ids = [p.get("alert_id") for p in ((t.result or {}).get("persisted") or [])]
            for a in db.query(Alert).filter(Alert.id.in_(ids)).all():
                if body.decision == "approve" and a.status == "open":
                    a.status = "acknowledged"
                if body.decision == "reject":
                    a.status = "rejected"
        db.commit()
        out = {"run_id": rid, **dec}
    finally:
        db.close()
    if body.decision == "request_reassessment":
        out["reassessment"] = run_network("reassessment") if r.scope == "NETWORK" else run_station(r.scope, "reassessment", parent=rid)
    return out


# ------------------------------------------------------------------ alerts
def _alert(a: Alert) -> dict:
    return clean({c.name: getattr(a, c.name) for c in Alert.__table__.columns})


@router.get("/alerts")
def alerts(status: str | None = None, station_id: str | None = None):
    db = SessionLocal()
    try:
        q = db.query(Alert)
        if status:
            q = q.filter(Alert.status.in_(status.split(",")))
        if station_id:
            q = q.filter(Alert.station_id == station_id)
        return [_alert(a) for a in q.order_by(Alert.priority_rank.desc(), Alert.last_seen.desc()).all()]
    finally:
        db.close()


@router.get("/alerts/{aid}")
def alert_get(aid: str):
    db = SessionLocal()
    try:
        return _alert(db.get(Alert, aid) or _404("alert"))
    finally:
        db.close()


@router.post("/alerts/{aid}/action")
def alert_action(aid: str, body: AlertActionIn):
    db = SessionLocal()
    try:
        a = db.get(Alert, aid) or _404("alert")
        a.status = {"acknowledge": "acknowledged", "confirm": "confirmed", "reject": "rejected", "close": "closed", "reopen": "open"}[body.action]
        if a.incident_id:
            db.add(IncidentAction(incident_id=a.incident_id, action=f"alert_{body.action}", actor=body.actor, note=f"{a.id}: {body.note}", timestamp=now()))
        db.commit()
        return _alert(a)
    finally:
        db.close()


# ------------------------------------------------------------------ incidents / investigation
def _incident(i: Incident, db, full=False) -> dict:
    d = {c.name: getattr(i, c.name) for c in Incident.__table__.columns}
    if full:
        d["actions"] = [{"action": a.action, "actor": a.actor, "note": a.note, "data": a.data, "timestamp": a.timestamp}
                        for a in db.query(IncidentAction).filter(IncidentAction.incident_id == i.id).order_by(IncidentAction.timestamp).all()]
        d["alerts"] = [_alert(a) for a in db.query(Alert).filter(Alert.incident_id == i.id).all()]
    return clean(d)


@router.get("/incidents")
def incidents(status: str | None = None):
    db = SessionLocal()
    try:
        q = db.query(Incident)
        if status:
            q = q.filter(Incident.status.in_(status.split(",")))
        return [_incident(i, db) for i in q.order_by(Incident.updated_at.desc()).all()]
    finally:
        db.close()


@router.get("/incidents/{iid}")
def incident_get(iid: str):
    db = SessionLocal()
    try:
        return _incident(db.get(Incident, iid) or _404("incident"), db, full=True)
    finally:
        db.close()


TRANSITIONS = {"review": ("under_review", "under_review"), "verify_sensor": (None, "sensor_verification"),
               "request_field_inspection": ("field_inspection_requested", "field_inspection_requested"),
               "start_investigation": ("investigating", "in_progress"), "assign": (None, None), "add_observation": (None, None),
               "add_lab_result": (None, "lab_results_received"), "confirm_anomaly": (None, "anomaly_confirmed"),
               "reject_anomaly": (None, "anomaly_rejected"), "correct_regulatory_comparison": (None, None),
               "escalate": ("escalated", "escalated"), "close": ("closed", "closed"), "reopen": ("open", "reopened")}


@router.post("/incidents/{iid}/actions")
def incident_action(iid: str, body: IncidentActionIn):
    db = SessionLocal()
    try:
        i = db.get(Incident, iid) or _404("incident")
        st, inv = TRANSITIONS[body.action]
        if st:
            i.status = st
        if inv:
            i.investigation_status = inv
        if body.action == "assign":
            i.assigned_to = body.assigned_to or body.actor
        if body.action == "close":
            i.closed_at = now()
            for a in db.query(Alert).filter(Alert.incident_id == iid, Alert.status != "rejected").all():
                a.status = "closed"
        if body.action == "reject_anomaly":
            for a in db.query(Alert).filter(Alert.incident_id == iid).all():
                a.status = "rejected"
        i.updated_at = now()
        db.add(IncidentAction(incident_id=iid, action=body.action, actor=body.actor, note=body.note,
                              data=clean({"assigned_to": body.assigned_to, "lab_result": body.lab_result}), timestamp=now()))
        db.commit()
        return _incident(i, db, full=True)
    finally:
        db.close()


@router.post("/incidents/{iid}/recommendation-feedback")
def incident_feedback(iid: str, body: FeedbackIn):
    db = SessionLocal()
    try:
        i = db.get(Incident, iid) or _404("incident")
        rec = i.recommendation or {}
        if not rec.get("recommended_action"):
            raise HTTPException(400, "incident has no recommendation")
        bandit.feedback(db, rec["context"], rec["recommended_action"], body.useful)
        db.add(IncidentAction(incident_id=iid, action="recommendation_feedback", actor=body.actor,
                              note=f"'{rec['recommended_action']}' marked {'useful' if body.useful else 'not useful'}", timestamp=now()))
        db.commit()
        return {"incident_id": iid, "context": rec["context"], "action": rec["recommended_action"], "useful": body.useful}
    finally:
        db.close()


# ------------------------------------------------------------------ standards / RAG
@router.get("/standards")
def standards(parameter: str | None = None):
    rows = stdtool.all_standards(include_inactive=True)
    return [s for s in rows if not parameter or s["parameter"] == parameter]


@router.post("/standards", status_code=201)
def standard_create(body: StandardIn):
    db = SessionLocal()
    try:
        if db.get(StandardRecord, body.id):
            raise HTTPException(409, "standard id exists — use PUT")
        db.add(StandardRecord(id=body.id, data=body.model_dump(exclude_none=True), active=True, updated_at=now()))
        db.commit()
        rag.build_index(force=True)
        return body.model_dump()
    finally:
        db.close()


@router.put("/standards/{sid}")
def standard_update(sid: str, body: StandardIn):
    db = SessionLocal()
    try:
        r = db.get(StandardRecord, sid) or _404("standard")
        r.data, r.updated_at = body.model_dump(exclude_none=True), now()
        db.commit()
        rag.build_index(force=True)
        return r.data
    finally:
        db.close()


@router.get("/standards/search")
def standards_search(q: str, k: int = 6):
    return clean(rag.search(q, k))


@router.post("/standards/ask")
def standards_ask(body: AskIn):
    alert = None
    if body.alert_id:
        db = SessionLocal()
        try:
            a = db.get(Alert, body.alert_id) or _404("alert")
            alert = _alert(a)
        finally:
            db.close()
    return clean(rag.ask(body.question, alert))


# ------------------------------------------------------------------ reports
@router.post("/reports/generate")
def report_generate(body: ReportIn):
    return reports.generate(body.station_ids, body.hours)


@router.get("/reports")
def report_list():
    db = SessionLocal()
    try:
        return [{k: v for k, v in reports.report_dict(r).items() if k != "content"} for r in db.query(Report).order_by(Report.created_at.desc()).all()]
    finally:
        db.close()


@router.get("/reports/{rid}")
def report_get(rid: str):
    db = SessionLocal()
    try:
        return reports.report_dict(db.get(Report, rid) or _404("report"))
    finally:
        db.close()


@router.post("/reports/{rid}/approve")
def report_approve(rid: str, body: ApproveIn):
    db = SessionLocal()
    try:
        r = db.get(Report, rid) or _404("report")
        r.status, r.approved_by, r.approved_at = "approved", body.actor, now()
        db.commit()
        return reports.report_dict(r)
    finally:
        db.close()


@router.get("/reports/{rid}/pdf")
def report_pdf(rid: str):
    db = SessionLocal()
    try:
        rep = reports.report_dict(db.get(Report, rid) or _404("report"))
    finally:
        db.close()
    return Response(render(rep), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{rid}.pdf"'})


# ------------------------------------------------------------------ admin
@router.post("/admin/reset-demo")
def reset_demo():
    from ..database import Base, engine, init_db
    from ..seed import seed
    Base.metadata.drop_all(bind=engine)
    init_db()
    rag.build_index(force=True)
    return seed(force=True)


def _404(what: str):
    raise HTTPException(404, f"{what} not found")
