"""Cross-station analysis tool: is an elevated reading localized or geographically distributed?"""
from __future__ import annotations

from datetime import timedelta

from ..config import CROSS_STATION_RADIUS_KM
from ..database import SessionLocal, Station
from . import data_access as da
from . import standards as stdtool
from .geo import classify_spatial, haversine_km

PERIOD = {"pm2_5": "24h", "pm10": "24h", "no2": "24h", "so2": "24h", "co": "8h", "o3": "8h"}


def cross_station(station_id: str, parameter: str, now, radius_km: float = CROSS_STATION_RADIUS_KM) -> dict:
    db = SessionLocal()
    try:
        me = db.get(Station, station_id)
        cands = [s for s in db.query(Station).all() if parameter in (s.parameters or [])]
        rows = []
        for s in cands:
            d = 0.0 if s.id == station_id else haversine_km(me.latitude, me.longitude, s.latitude, s.longitude)
            if d > radius_km:
                continue
            long = da.load_long(db, [s.id], start=now - timedelta(days=30), parameters=[parameter])
            w = da.to_wide(long)
            if w.empty or parameter not in w:
                continue
            ser = w[parameter].dropna()
            if ser.empty:
                continue
            hours = int(PERIOD.get(parameter, "24h").rstrip("h"))
            recent = ser[ser.index > ser.index.max() - timedelta(hours=hours)]
            mean_recent = float(recent.mean())
            base = float(ser[ser.index <= ser.index.max() - timedelta(hours=48)].median())
            stds = [x for x in stdtool.applicable(da.station_dict(s), parameter, db)
                    if x.get("averaging_period") == PERIOD.get(parameter) and x.get("limit_type") == "max"]
            ref = stds[0]["limit"] if stds else None
            elevated = (mean_recent > ref) if ref is not None else (mean_recent > 1.5 * base)
            rows.append({"station_id": s.id, "name": s.name, "distance_km": round(d, 2), "latitude": s.latitude, "longitude": s.longitude,
                         "recent_mean": round(mean_recent, 2), "window_h": hours, "baseline_median": round(base, 2), "reference_limit": ref,
                         "basis": "configured reference" if ref is not None else "1.5 × station baseline", "elevated": bool(elevated),
                         "last_reading": ser.index.max().isoformat()})
        me_row = next((r for r in rows if r["station_id"] == station_id), None)
        n_el = sum(r["elevated"] for r in rows)
        cls, summary = classify_spatial(n_el, len(rows), bool(me_row and me_row["elevated"]))
        return {"parameter": parameter, "radius_km": radius_km, "stations": sorted(rows, key=lambda r: r["distance_km"]),
                "elevated_count": n_el, "station_count": len(rows), "classification": cls,
                "summary": summary + " Spatial pattern alone does not identify a pollution source."}
    finally:
        db.close()
