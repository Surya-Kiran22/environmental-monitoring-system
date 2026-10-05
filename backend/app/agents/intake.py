"""Agent 1 — Environmental Data Intake & Validation Agent."""
from __future__ import annotations

from datetime import timedelta

from ..config import ANALYSIS_LOOKBACK_DAYS
from ..database import Measurement, SessionLocal
from ..tools import data_access as da
from ..tools.validation import CANONICAL_UNITS, validate_long
from .base import Step, event


def intake_agent(state: dict) -> dict:
    st = state["station"]
    now = state["now"]
    with Step("Environmental Data Intake & Validation Agent", "intake", {"station_id": st["id"], "lookback_days": ANALYSIS_LOOKBACK_DAYS}) as step:
        db = SessionLocal()
        try:
            long = step.tool("db.load_measurements", {"station_id": st["id"], "days": ANALYSIS_LOOKBACK_DAYS},
                             None) or da.load_long(db, [st["id"]], start=now - timedelta(days=ANALYSIS_LOOKBACK_DAYS))
            step.tool_calls[-1]["result"] = {"rows": len(long)}
            checked, issues = validate_long(long, now=now)
            step.tool("validation.validate_long", {"rows": len(long)}, {"issues": len(issues)})
            # persist algorithmic flags (suspicious values are marked, never deleted)
            changed = 0
            orig = long.set_index("id")[["quality_flag", "flag_reason"]]
            for r in checked.itertuples():
                o = orig.loc[r.id]
                if (o.quality_flag, o.flag_reason) != (r.quality_flag, r.flag_reason) and o.quality_flag not in ("invalid", "verified"):
                    db.query(Measurement).filter(Measurement.id == int(r.id)).update({"quality_flag": r.quality_flag, "flag_reason": r.flag_reason})
                    changed += 1
            db.commit()
        finally:
            db.close()
        wide = da.to_wide(checked, usable_only=True)
        wide_all = da.to_wide(checked, usable_only=False)
        latest = {}
        if not wide_all.empty:
            last_ts = checked[checked.value.notna()].timestamp.max()
            row = wide_all.loc[last_ts] if last_ts in wide_all.index else wide_all.iloc[-1]
            latest = {p: (None if row.get(p) != row.get(p) else round(float(row.get(p)), 3)) for p in wide_all.columns}
        suspects = checked[checked.quality_flag == "suspect"]
        recent_suspects = suspects[suspects.timestamp > now - timedelta(hours=48)]
        severe = [i for i in issues if i["severity"] == "high" and (i.get("timestamp") is None or i["timestamp"] > now - timedelta(hours=48))]
        status = "valid" if not severe else ("stale" if any(i["type"] == "stale_sensor" for i in severe) else "needs_verification")
        observation = {"station_id": st["id"], "timestamp": last_ts.isoformat() if latest else None,
                       "monitoring_type": st["monitoring_type"], "measurements": latest,
                       "units": {p: CANONICAL_UNITS.get(p) for p in latest}, "validation_status": status}
        validation = {"status": status, "issues": issues, "issue_counts": {}, "flags_updated": changed,
                      "recent_suspects": [{"timestamp": r.timestamp, "parameter": r.parameter, "value": r.value, "reason": r.flag_reason}
                                          for r in recent_suspects.itertuples()],
                      "rows_checked": len(checked)}
        for i in issues:
            validation["issue_counts"][i["type"]] = validation["issue_counts"].get(i["type"], 0) + 1
        step.output = {"observation": observation, "validation_status": status, "issue_counts": validation["issue_counts"],
                       "recent_suspects": validation["recent_suspects"][:10]}
    return {"long": checked, "wide": wide, "wide_all": wide_all, "observation": observation, "validation": validation,
            "trace": [step.record()], "events": [event("DATA_VALIDATED", {"station_id": st["id"], "validation_status": status,
                                                                          "issues": validation["issue_counts"]})]}
