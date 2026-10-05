"""Configurable environmental-standard knowledge base (structured part).

Limits are NEVER produced by an LLM. They are loaded from data/standards/standards.json into the
`standards` table and can be added/edited through the /api/standards endpoints.
"""
from __future__ import annotations

import json

from ..config import STANDARDS_FILE
from ..database import SessionLocal, StandardRecord


def seed_standards(db) -> int:
    data = json.loads(STANDARDS_FILE.read_text(encoding="utf-8"))["standards"]
    n = 0
    for s in data:
        if not db.get(StandardRecord, s["id"]):
            db.add(StandardRecord(id=s["id"], data=s, active=True))
            n += 1
    db.commit()
    return n


def all_standards(db=None, include_inactive: bool = False) -> list[dict]:
    own = db is None
    db = db or SessionLocal()
    try:
        q = db.query(StandardRecord)
        if not include_inactive:
            q = q.filter(StandardRecord.active.is_(True))
        return [{**r.data, "id": r.id, "active": r.active} for r in q.all()]
    finally:
        if own:
            db.close()


def get_standard(std_id: str, db=None) -> dict | None:
    for s in all_standards(db, include_inactive=True):
        if s["id"] == std_id:
            return s
    return None


def applicable(station: dict, parameter: str, db=None) -> list[dict]:
    """Return standards applicable to this station + parameter (jurisdiction, zone, water class filters)."""
    out = []
    for s in all_standards(db):
        if s.get("parameter") != parameter or s.get("jurisdiction", "IN") != station.get("jurisdiction", "IN"):
            continue
        if s.get("zones") and station.get("zone_category") not in s["zones"]:
            continue
        if s.get("water_classes") and station.get("water_class") not in s["water_classes"]:
            continue
        if s.get("stations") and station["id"] not in s["stations"]:
            continue
        out.append(s)
    order = {"1h": 0, "instantaneous": 0, "day": 1, "night": 2, "8h": 3, "24h": 4, "annual": 9}
    return sorted(out, key=lambda s: order.get(s.get("averaging_period"), 5))
