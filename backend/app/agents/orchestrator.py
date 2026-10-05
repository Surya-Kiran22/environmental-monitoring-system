"""Multi-agent orchestration with LangGraph (StateGraph) and persistent workflow state.

Graph:
  intake ──► route ──► air | water | noise ──► weather ──► anomaly ──► alert ──► reviewer ──┐
                                                                         ▲                   │
                                                                         └── reassess (≤1) ◄─┤
                                                                                             ▼
                                                                                        human_gate ──► END
State is a typed dict; list fields (trace, events) use additive reducers so every agent appends.
Each run is persisted in `pipeline_runs` (status, trace, events, risk, human decision).
If LangGraph is unavailable, an equivalent sequential executor with the same nodes/edges is used.
"""
from __future__ import annotations

import operator
import traceback
from typing import Annotated, Any, TypedDict

from ..config import NETWORK_ID
from ..database import PipelineRun, SessionLocal, Station
from ..tools import data_access as da
from ..utils import clean, new_id, now
from .air import air_agent
from .alert import RANK, alert_agent, risk_category
from .anomaly import anomaly_agent
from .base import event
from .intake import intake_agent
from .noise import noise_agent
from .reviewer import human_gate, reviewer_agent
from .water import water_agent
from .weather import weather_agent


class PipelineState(TypedDict, total=False):
    run_id: str
    trigger: str
    now: Any
    station: dict
    long: Any
    wide: Any
    wide_all: Any
    observation: dict
    validation: dict
    findings: list
    domain_summary: str
    cross_station: dict
    water_changes: list
    noise_periods: list
    weather_context: dict
    anomaly: dict
    draft: dict
    review: dict
    review_feedback: list
    reassess_count: int
    persisted: list
    incidents: list
    status: str
    trace: Annotated[list, operator.add]
    events: Annotated[list, operator.add]


def route_domain(state: dict) -> str:
    return {"air_quality": "air_quality", "water_quality": "water_quality", "noise": "noise"}[state["station"]["monitoring_type"]]


def after_review(state: dict) -> str:
    return "alert" if state.get("review", {}).get("verdict") == "reassess" else "human_gate"


NODES = {"intake": intake_agent, "air_quality": air_agent, "water_quality": water_agent, "noise": noise_agent,
         "weather": weather_agent, "anomaly": anomaly_agent, "alert": alert_agent,
         "reviewer": reviewer_agent, "human_gate": human_gate}
EDGES = [("intake", "route"), ("air_quality", "weather"), ("water_quality", "weather"), ("noise", "weather"),
         ("weather", "anomaly"), ("anomaly", "alert"), ("alert", "reviewer"), ("reviewer", "alert|human_gate"), ("human_gate", "END")]

try:
    from langgraph.graph import END, START, StateGraph

    def _build():
        g = StateGraph(PipelineState)
        for name, fn in NODES.items():
            g.add_node(name, fn)
        g.add_edge(START, "intake")
        g.add_conditional_edges("intake", route_domain, {"air_quality": "air_quality", "water_quality": "water_quality", "noise": "noise"})
        for d in ("air_quality", "water_quality", "noise"):
            g.add_edge(d, "weather")
        g.add_edge("weather", "anomaly")
        g.add_edge("anomaly", "alert")
        g.add_edge("alert", "reviewer")
        g.add_conditional_edges("reviewer", after_review, {"alert": "alert", "human_gate": "human_gate"})
        g.add_edge("human_gate", END)
        return g.compile()

    GRAPH = _build()
    ENGINE = "langgraph"
except Exception:  # pragma: no cover
    GRAPH, ENGINE = None, "sequential-fallback"


def _invoke(state: dict) -> dict:
    if GRAPH is not None:
        return GRAPH.invoke(state, {"recursion_limit": 25})
    order = ["intake", route_domain(state), "weather", "anomaly"]
    for n in order:
        state = _merge(state, NODES[n](state))
    while True:
        state = _merge(state, NODES["alert"](state))
        state = _merge(state, NODES["reviewer"](state))
        if after_review(state) == "human_gate":
            break
    return _merge(state, NODES["human_gate"](state))


def _merge(state, upd):
    for k, v in upd.items():
        state[k] = state.get(k, []) + v if k in ("trace", "events") else v
    return state


def _version(events: list) -> list:
    return [{**e, "version": i + 1} for i, e in enumerate(events)]


def serialize_result(s: dict) -> dict:
    keep = ("observation", "validation", "findings", "domain_summary", "cross_station", "water_changes", "noise_periods",
            "weather_context", "anomaly", "draft", "review", "persisted", "incidents", "status", "station")
    out = {k: s.get(k) for k in keep}
    if out.get("draft"):
        out["draft"] = {k: v for k, v in out["draft"].items() if k != "llm_facts"}
    return clean(out)


def run_station(station_id: str, trigger: str = "manual", parent: str | None = None) -> dict:
    db = SessionLocal()
    try:
        st = db.get(Station, station_id)
        if not st:
            raise ValueError(f"unknown station {station_id}")
        station = da.station_dict(st)
        run = PipelineRun(id=new_id("RUN"), scope=station_id, trigger=trigger, status="running", started_at=now(), parent_run=parent)
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()
    state: dict = {"run_id": run_id, "trigger": trigger, "now": now(), "station": station, "reassess_count": 0,
                   "trace": [], "events": [event("PIPELINE_EXECUTED", {"location": station["location"], "station_id": station_id, "trigger": trigger,
                                                                       "engine": ENGINE})]}
    try:
        final = _invoke(state)
        status, err = final.get("status", "completed"), None
    except Exception as e:  # noqa: BLE001
        final, status, err = state, "failed", f"{e}\n{traceback.format_exc()[-1500:]}"
    result = serialize_result(final)
    if err:
        result["error"] = err
    risk = (final.get("draft") or {}).get("risk") or {}
    db = SessionLocal()
    try:
        r = db.get(PipelineRun, run_id)
        r.status, r.finished_at = status, now()
        r.result, r.trace, r.events = result, clean(final.get("trace", [])), _version(clean(final.get("events", [])))
        r.risk = clean({**risk, "alert_category": (final.get("draft") or {}).get("overall_category")})
        db.commit()
    finally:
        db.close()
    return {"run_id": run_id, "station_id": station_id, "status": status, "risk": risk,
            "overall_category": (final.get("draft") or {}).get("overall_category"), "error": err}


def run_network(trigger: str = "manual_override") -> dict:
    db = SessionLocal()
    try:
        stations = [da.station_dict(s) for s in db.query(Station).filter(Station.operational_status != "offline").all()]
        net = PipelineRun(id=new_id("RUN"), scope="NETWORK", trigger=trigger, status="running", started_at=now())
        db.add(net)
        db.commit()
        net_id = net.id
    finally:
        db.close()
    events = [event("PIPELINE_EXECUTED", {"location": NETWORK_ID, "trigger": trigger, "stations": len(stations), "engine": ENGINE})]
    children = [run_station(s["id"], trigger, parent=net_id) | {"monitoring_type": s["monitoring_type"], "name": s["name"]} for s in stations]
    dom = {"air_quality": "AIR", "water_quality": "WATER", "noise": "NOISE"}
    dscores: dict = {}
    for c in children:
        d = dom[c["monitoring_type"]]
        dscores[d] = max(dscores.get(d, 0), (c.get("risk") or {}).get("score", 0))
    mx = max(dscores.values()) if dscores else 0
    overall = round(0.6 * mx + 0.4 * (sum(dscores.values()) / len(dscores) if dscores else 0), 1)
    highest = max(dscores, key=dscores.get) if dscores else None
    top_child = max(children, key=lambda c: (RANK.get(c.get("overall_category") or "Normal", 0), (c.get("risk") or {}).get("score", 0)), default=None)
    events.append(event("STATIONS_ANALYZED", {"runs": [{"station": c["station_id"], "category": c.get("overall_category"),
                                                        "risk": (c.get("risk") or {}).get("score")} for c in children]}))
    events.append(event("RISK_EVALUATED", {"overall_risk_score": overall, "category": risk_category(overall), "highest_factor": highest,
                                           "domain_scores": dscores}))
    rec = None
    db = SessionLocal()
    try:
        if top_child:
            child = db.get(PipelineRun, top_child["run_id"])
            rec = ((child.result or {}).get("draft") or {}).get("recommendation")
            if rec:
                events.append(event("BANDIT_RECOMMENDATION", {"station": top_child["station_id"], "action": rec["recommended_action"],
                                                              "mode": rec["mode"], "epsilon": rec["epsilon"], "context": rec["context"]}))
        needs_review = any(RANK.get(c.get("overall_category") or "Normal", 0) >= 2 for c in children)
        lifecycle = "INTERVENTION_REQUIRED" if any(RANK.get(c.get("overall_category") or "Normal", 0) >= 3 for c in children) else (
            "ELEVATED_MONITORING" if needs_review else "NORMAL_OPERATION")
        events.append(event("HUMAN_REVIEW_PENDING" if needs_review else "NO_ACTION_REQUIRED", {"lifecycle_status": lifecycle}))
        r = db.get(PipelineRun, net_id)
        r.status = "awaiting_human_review" if needs_review else "completed_no_alert"
        r.finished_at = now()
        r.events = _version(clean(events))
        r.risk = {"overall_risk_score": overall, "category": risk_category(overall), "highest_factor": highest, "domain_scores": dscores,
                  "lifecycle_status": lifecycle}
        r.result = clean({"children": children, "recommendation": rec, "top_station": top_child and top_child["station_id"]})
        r.trace = []
        db.commit()
    finally:
        db.close()
    return {"run_id": net_id, "risk": {"overall_risk_score": overall, "category": risk_category(overall), "highest_factor": highest,
                                        "domain_scores": dscores, "lifecycle_status": lifecycle}, "children": children}


GRAPH_SPEC = {"engine": ENGINE, "nodes": list(NODES.keys()), "edges": EDGES,
              "conditional": {"intake": "route by station.monitoring_type", "reviewer": "reassess → alert (max 1) else human_gate"}}
