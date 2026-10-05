"""Agent 8 — Environmental Standards & Reviewer (critic) Agent, plus the human-review gate node."""
from __future__ import annotations

import re
from datetime import timedelta

from ..config import ALERT_DEDUP_HOURS
from ..database import Alert, Incident, IncidentAction, SessionLocal
from ..tools import rag
from ..tools import standards as stdtool
from ..tools.compliance import difference
from ..utils import clean, new_id
from .alert import RANK
from .base import Step, event

CAUSAL = re.compile(r"\b(caused by|causes|caused|due to|because of|responsible for|the source of|is the source|resulted from|result of)\b", re.I)
LEGAL = re.compile(r"\b(violat\w*|illegal|penalt\w*|fine[ds]?|prosecut\w*|guilty|liable|non-compliance with law)\b", re.I)
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _texts(draft: dict, state: dict) -> list[tuple[str, str]]:
    out = [("summary", draft.get("summary", ""))]
    for a in draft["alerts"]:
        out.append((f"alert:{a['title'][:40]}", a.get("ai_interpretation", "")))
    out.append(("weather", state.get("weather_context", {}).get("interpretation", "")))
    out.append(("anomaly", state.get("anomaly", {}).get("interpretation", "")))
    return out


def reviewer_agent(state: dict) -> dict:
    draft = state["draft"]
    count = state.get("reassess_count", 0)
    checks, issues, corrections = [], [], []
    with Step("Environmental Standards & Reviewer Agent", "reviewer", {"alerts": len(draft["alerts"]), "reassess_count": count}) as step:
        for a in draft["alerts"]:
            std = a.get("standard_ref")
            if not std or not a.get("calculated_exceedance"):
                continue
            kb = stdtool.get_standard(std["id"])
            ok_kb = bool(kb) and all(kb.get(k) == std.get(k) for k in ("limit", "min", "max", "unit", "averaging_period"))
            checks.append({"check": "standard exists in configured KB and matches", "alert": a["title"], "passed": ok_kb})
            unit_ok = a["measured_value"]["unit"] == std["unit"]
            checks.append({"check": "measurement unit equals standard unit", "alert": a["title"], "passed": unit_ok,
                           "detail": f"{a['measured_value']['unit']} vs {std['unit']}"})
            ce = a["calculated_exceedance"]
            avg_ok = bool(ce.get("comparison_valid"))
            checks.append({"check": "averaging period & data completeness valid", "alert": a["title"], "passed": avg_ok, "detail": ce.get("averaging_note")})
            pv = a["measured_value"].get("period_value")
            d, pct, _ = difference(pv, std) if pv is not None else (None, None, False)
            calc_ok = d is not None and abs(d - (ce.get("difference") or 0)) < 0.01 and abs((pct or 0) - (ce.get("percentage_difference") or 0)) < 0.2
            checks.append({"check": "deterministic difference recomputed", "alert": a["title"], "passed": calc_ok, "detail": f"difference={d}, pct={pct}"})
            sup = rag.supporting_text(std)
            step.tool("rag.supporting_text", {"standard_id": std["id"]}, {"doc": sup and sup["doc"], "section": sup and sup["section"]})
            checks.append({"check": "source document & section retrievable", "alert": a["title"], "passed": bool(sup),
                           "detail": f"{std.get('source_doc')} — {std.get('section')}"})
            if a["alert_type"].startswith("threshold_exceedance") and not (avg_ok and unit_ok and ok_kb and calc_ok):
                corrections.append(f"Downgraded '{a['title']}' to Elevated (comparison could not be verified).")
                a["category"], a["priority_rank"], a["alert_type"] = "Elevated", RANK["Elevated"], "indicative_exceedance"
            if std.get("basis") != "regulatory" and a["category"] == "Critical Review Required":
                corrections.append(f"Capped '{a['title']}' at Investigation Required (reference is a {std.get('basis')}).")
                a["category"], a["priority_rank"] = "Investigation Required", RANK["Investigation Required"]
        # unsupported claims
        for where, text in _texts(draft, state):
            for m in CAUSAL.finditer(text or ""):
                issues.append({"type": "unsupported_causal_claim", "where": where, "phrase": m.group(0)})
            for m in LEGAL.finditer(text or ""):
                issues.append({"type": "legal_determination_language", "where": where, "phrase": m.group(0)})
            if "source" in (text or "").lower() and "potential sources" not in where:
                for sent in re.split(r"(?<=[.!?])\s", text or ""):
                    if re.search(r"\bsource\b", sent, re.I) and not re.search(r"potential contributing|requiring investigation|source document|data source|source:|weather source|not confirmed|does not identify", sent, re.I):
                        issues.append({"type": "source_attribution_wording", "where": where, "phrase": sent[:120]})
        if draft.get("summary_source") == "llm" and draft.get("llm_facts"):
            allowed = set(NUM.findall(str(draft["llm_facts"])))
            extra = [n for n in NUM.findall(draft["summary"]) if n not in allowed and n.rstrip("0").rstrip(".") not in allowed]
            if extra:
                issues.append({"type": "number_not_in_evidence", "where": "summary", "phrase": ", ".join(extra[:5])})
        checks.append({"check": "no unsupported causal / legal / attribution claims", "passed": not issues,
                       "detail": f"{len(issues)} issue(s)" if issues else "clean"})
        if draft["alerts"]:
            draft["alerts"].sort(key=lambda a: -a["priority_rank"])
            draft["overall_category"] = draft["alerts"][0]["category"]
        verdict = "reassess" if issues and count < 1 else ("approved_with_corrections" if corrections or issues else "approved")
        review = {"verdict": verdict, "checks": checks, "issues": issues, "corrections": corrections,
                  "checks_passed": sum(c["passed"] for c in checks), "checks_total": len(checks)}
        step.output = review
    out = {"review": review, "draft": draft, "trace": [step.record()],
           "events": [event("REVIEW_COMPLETED", {"verdict": verdict, "checks": f"{review['checks_passed']}/{review['checks_total']}",
                                                  "issues": len(issues), "corrections": len(corrections)})]}
    if verdict == "reassess":
        out["review_feedback"] = issues
        out["reassess_count"] = count + 1
    return out


def human_gate(state: dict) -> dict:
    """Persist reviewed alerts (with de-duplication) and incidents, then wait for an authorised officer."""
    st, draft, run_id, now = state["station"], state["draft"], state["run_id"], state["now"]
    persisted, incidents = [], []
    with Step("Workflow: human-review gate", "human_gate", {"alerts": len(draft["alerts"])}) as step:
        db = SessionLocal()
        try:
            for a in draft["alerts"]:
                if a["priority_rank"] < 2:  # Normal / Observation stay in the run record only
                    continue
                existing = (db.query(Alert).filter(Alert.station_id == st["id"], Alert.parameter == a["parameter"],
                                                   Alert.alert_type == a["alert_type"], Alert.status.in_(["open", "acknowledged", "confirmed"]),
                                                   Alert.last_seen >= now - timedelta(hours=ALERT_DEDUP_HOURS * 4)).first())
                evidence = clean({k: a.get(k) for k in ("measured_value", "applicable_reference", "calculated_exceedance", "supporting", "cross_station",
                                                         "weather_observations", "anomaly", "potential_sources", "why")})
                if existing:
                    existing.occurrences += 1
                    existing.last_seen = now
                    existing.evidence, existing.ai_interpretation, existing.run_id = evidence, a["ai_interpretation"], run_id
                    if a["priority_rank"] > existing.priority_rank:
                        existing.category, existing.priority_rank = a["category"], a["priority_rank"]
                    al = existing
                    action = "deduplicated"
                else:
                    al = Alert(id=new_id("ALT"), station_id=st["id"], parameter=a["parameter"], category=a["category"], alert_type=a["alert_type"],
                               priority_rank=a["priority_rank"], title=a["title"], evidence=evidence, ai_interpretation=a["ai_interpretation"],
                               standard_ref=clean(a.get("standard_ref")), status="open", first_seen=now, last_seen=now, run_id=run_id)
                    db.add(al)
                    action = "created"
                db.flush()
                if a["priority_rank"] >= 3:
                    # one open incident per station and kind (environmental event vs. sensor issue) — avoids incident duplication
                    kind = "sensor" if a["category"] == "Sensor Verification Required" else "environmental"
                    inc = next((i for i in db.query(Incident).filter(Incident.station_id == st["id"], Incident.status != "closed").all()
                                if (i.evidence or {}).get("kind") == kind), None)
                    if not inc:
                        inc = Incident(id=new_id("INC"), station_id=st["id"], parameter=a["parameter"], title=a["title"],
                                       start_time=now, status="open",
                                       investigation_status="awaiting_review", priority=a["category"],
                                       measurement=clean(a.get("measured_value")), applicable_reference=clean(a.get("applicable_reference")),
                                       evidence=clean({"kind": kind, "alerts": [al.id], "parameters": [a["parameter"]], "why": a["why"], "interpretation": a["ai_interpretation"], **evidence}),
                                       recommendation=clean(draft.get("recommendation")), created_at=now, updated_at=now)
                        db.add(inc)
                        db.add(IncidentAction(incident_id=inc.id, action="created", actor="Alert Agent", note=a["title"], timestamp=now))
                    else:
                        ev = dict(inc.evidence or {})
                        ev["alerts"] = sorted(set(ev.get("alerts", []) + [al.id]))
                        ev["parameters"] = sorted(set(ev.get("parameters", []) + [a["parameter"]]))
                        if a["priority_rank"] >= RANK.get(inc.priority, 0):
                            ev.update({k: v for k, v in evidence.items() if v})
                        inc.parameter = ",".join(ev["parameters"])
                        inc.evidence, inc.updated_at = clean(ev), now
                        if a["priority_rank"] > RANK.get(inc.priority, 0):
                            inc.priority, inc.title = a["category"], a["title"]
                            inc.measurement = clean(a.get("measured_value")) or inc.measurement
                            inc.applicable_reference = clean(a.get("applicable_reference")) or inc.applicable_reference
                        db.add(IncidentAction(incident_id=inc.id, action="evidence_updated", actor="Alert Agent", note=f"Run {run_id}: {a['title']}", timestamp=now))
                    al.incident_id = inc.id
                    incidents.append(inc.id)
                persisted.append({"alert_id": al.id, "action": action, "category": al.category, "incident_id": al.incident_id})
            db.commit()
        finally:
            db.close()
        status = "awaiting_human_review" if persisted else "completed_no_alert"
        step.output = {"persisted": persisted, "incidents": sorted(set(incidents)), "status": status}
    return {"persisted": persisted, "incidents": sorted(set(incidents)), "status": status, "trace": [step.record()],
            "events": [event("HUMAN_REVIEW_PENDING" if persisted else "NO_ACTION_REQUIRED",
                             {"alerts": len(persisted), "incidents": sorted(set(incidents)), "status": status})]}
