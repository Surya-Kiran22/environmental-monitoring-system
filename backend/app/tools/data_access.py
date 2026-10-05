"""Read helpers that turn DB rows into pandas frames for the agents."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from ..database import Measurement, RegisteredSource, Station, WeatherObservation


def station_dict(s: Station) -> dict:
    return {"id": s.id, "name": s.name, "monitoring_type": s.monitoring_type, "location": s.location,
            "latitude": s.latitude, "longitude": s.longitude, "zone_category": s.zone_category,
            "water_class": s.water_class, "jurisdiction": s.jurisdiction or "IN", "parameters": s.parameters or [],
            "sensors": s.sensors or [], "operational_status": s.operational_status,
            "last_communication": s.last_communication.isoformat() if s.last_communication else None, "notes": s.notes}


def load_long(db, station_ids: list[str], start: datetime | None = None, end: datetime | None = None,
              parameters: list[str] | None = None) -> pd.DataFrame:
    q = db.query(Measurement.id, Measurement.station_id, Measurement.timestamp, Measurement.parameter, Measurement.value,
                 Measurement.unit, Measurement.quality_flag, Measurement.flag_reason).filter(Measurement.station_id.in_(station_ids))
    if start:
        q = q.filter(Measurement.timestamp >= start)
    if end:
        q = q.filter(Measurement.timestamp <= end)
    if parameters:
        q = q.filter(Measurement.parameter.in_(parameters))
    df = pd.DataFrame(q.all(), columns=["id", "station_id", "timestamp", "parameter", "value", "unit", "quality_flag", "flag_reason"])
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values(["station_id", "parameter", "timestamp", "id"])
    return df


def to_wide(long: pd.DataFrame, usable_only: bool = True) -> pd.DataFrame:
    """Hourly wide frame (index=timestamp, columns=parameters). Suspect/invalid values become NaN when usable_only."""
    if long.empty:
        return pd.DataFrame()
    d = long.drop_duplicates(["timestamp", "parameter"], keep="first").copy()
    if usable_only:
        d.loc[~d["quality_flag"].isin(["valid", "verified"]), "value"] = float("nan")
    w = d.pivot(index="timestamp", columns="parameter", values="value").sort_index()
    full = pd.date_range(w.index.min().floor("h"), w.index.max().floor("h"), freq="h")
    return w.reindex(full)


def latest_time(db, station_id: str):
    r = (db.query(Measurement.timestamp).filter(Measurement.station_id == station_id, Measurement.value.isnot(None))
         .order_by(Measurement.timestamp.desc()).first())
    return r[0] if r else None


def weather_frame(db, start: datetime | None = None, end: datetime | None = None, dataset_only: bool = True) -> pd.DataFrame:
    q = db.query(WeatherObservation)
    if dataset_only:
        q = q.filter(WeatherObservation.source == "synthetic-dataset")
    if start:
        q = q.filter(WeatherObservation.timestamp >= start)
    if end:
        q = q.filter(WeatherObservation.timestamp <= end)
    rows = [(w.timestamp, w.temperature, w.humidity, w.wind_speed, w.wind_direction, w.rainfall, w.source) for w in q.all()]
    df = pd.DataFrame(rows, columns=["timestamp", "temperature", "humidity", "wind_speed", "wind_direction", "rainfall", "source"])
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.floor("h")
    return df.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()


def sources(db) -> list[dict]:
    return [{"id": s.id, "name": s.name, "category": s.category, "latitude": s.latitude, "longitude": s.longitude}
            for s in db.query(RegisteredSource).all()]


def window_start(end: datetime, days: int) -> datetime:
    return end - timedelta(days=days)
