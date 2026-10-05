"""Seed the database from the CSV dataset.

Replay alignment: timestamps in the CSVs are shifted so the newest record equals the current hour.
This keeps the demo "live" (stale-sensor logic, day/night noise windows) whenever the app is deployed.
"""
from __future__ import annotations

import pandas as pd

from .config import DATA_DIR
from .database import Measurement, RegisteredSource, SessionLocal, Station, WeatherObservation
from .tools.standards import seed_standards
from .tools.validation import validate_long
from .utils import now

SENSORS = {
    "air_quality": [{"sensor_id": "BAM-1020", "measures": "pm2_5,pm10"}, {"sensor_id": "CLD-NOx", "measures": "no2"},
                    {"sensor_id": "UVF-SO2", "measures": "so2"}, {"sensor_id": "NDIR-CO", "measures": "co"},
                    {"sensor_id": "UVP-O3", "measures": "o3"}],
    "water_quality": [{"sensor_id": "MP-SONDE-6", "measures": "ph,dissolved_oxygen,turbidity,conductivity,tds,water_temperature"}],
    "noise": [{"sensor_id": "SLM-CL1", "measures": "noise_laeq"}],
}


def ensure_dataset() -> None:
    if not (DATA_DIR / "measurements.csv").exists():
        from data.generate_data import main as gen  # type: ignore
        gen()


def seed(force: bool = False) -> dict:
    db = SessionLocal()
    try:
        seed_standards(db)
        if db.query(Station).count() and not force:
            return {"seeded": False}
        ensure_dataset()
        st = pd.read_csv(DATA_DIR / "stations.csv").fillna("")
        meas = pd.read_csv(DATA_DIR / "measurements.csv", parse_dates=["timestamp"])
        wx = pd.read_csv(DATA_DIR / "weather.csv", parse_dates=["timestamp"])
        src = pd.read_csv(DATA_DIR / "registered_sources.csv")
        shift = pd.Timestamp(now()).floor("h") - max(meas.timestamp.max(), wx.timestamp.max())
        meas["timestamp"] += shift
        wx["timestamp"] += shift
        for _, r in st.iterrows():
            db.merge(Station(id=r.station_id, name=r["name"], monitoring_type=r.monitoring_type, location=r.location,
                             latitude=float(r.latitude), longitude=float(r.longitude), zone_category=r.zone_category,
                             water_class=r.water_class or None, jurisdiction="IN", parameters=r.parameters.split(";"),
                             sensors=SENSORS[r.monitoring_type], operational_status="active"))
        for _, r in src.iterrows():
            db.merge(RegisteredSource(id=r.source_id, name=r["name"], category=r.category, latitude=r.latitude, longitude=r.longitude))
        db.commit()
        # validate at ingest so suspicious values are flagged (not dropped) in storage
        meas["quality_flag"], meas["flag_reason"] = "valid", ""
        checked, _ = validate_long(meas.reset_index(drop=True))
        dup_mask = meas.duplicated(subset=["station_id", "timestamp", "parameter"], keep="first")
        meas.loc[checked.index, ["quality_flag", "flag_reason"]] = checked[["quality_flag", "flag_reason"]]
        meas.loc[dup_mask, ["quality_flag", "flag_reason"]] = ["suspect", "duplicate timestamp"]
        meas["value"] = meas["value"].astype(object).where(meas["value"].notna(), None)
        db.bulk_insert_mappings(Measurement, [
            {"station_id": r.station_id, "timestamp": r.timestamp.to_pydatetime(), "parameter": r.parameter, "value": r.value,
             "unit": r.unit, "quality_flag": r.quality_flag, "flag_reason": r.flag_reason, "source": "dataset"}
            for r in meas.itertuples()])
        db.bulk_insert_mappings(WeatherObservation, [
            {"timestamp": r.timestamp.to_pydatetime(), "location": r.location, "temperature": r.temperature, "humidity": r.humidity,
             "wind_speed": r.wind_speed, "wind_direction": r.wind_direction, "rainfall": r.rainfall, "source": r.source,
             "retrieved_at": r.timestamp.to_pydatetime()} for r in wx.itertuples()])
        db.commit()
        for s in db.query(Station).all():
            last = meas[(meas.station_id == s.id) & meas.value.notna()].timestamp.max()
            s.last_communication = last.to_pydatetime() if pd.notna(last) else None
        db.commit()
        return {"seeded": True, "measurements": len(meas), "shift_hours": shift.total_seconds() / 3600}
    finally:
        db.close()
