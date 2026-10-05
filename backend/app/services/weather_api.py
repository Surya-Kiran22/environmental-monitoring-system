"""External weather integration (Open-Meteo, no API key required).

Every record is stored with its source and retrieval timestamp. If the API is unreachable the agent
falls back to the most recent dataset observation and labels the source accordingly.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from .. import config
from ..database import WeatherObservation
from ..utils import now


def fetch_current(lat: float, lon: float) -> dict | None:
    if not config.ENABLE_LIVE_WEATHER:
        return None
    try:
        r = httpx.get(config.WEATHER_API_URL, timeout=config.WEATHER_TIMEOUT_S, params={
            "latitude": lat, "longitude": lon, "timezone": config.TIMEZONE, "wind_speed_unit": "ms", "forecast_days": 2,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,precipitation",
            "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,precipitation"})
        r.raise_for_status()
        j = r.json()
        c = j["current"]
        h = j.get("hourly", {})
        return {"source": "open-meteo", "url": config.WEATHER_API_URL, "observed_at": c["time"], "retrieved_at": now().isoformat(),
                "temperature": c["temperature_2m"], "humidity": c["relative_humidity_2m"], "wind_speed": c["wind_speed_10m"],
                "wind_direction": c["wind_direction_10m"], "rainfall": c.get("precipitation", 0.0),
                "hourly_forecast": [{"time": t, "temperature": h["temperature_2m"][i], "humidity": h["relative_humidity_2m"][i],
                                     "wind_speed": h["wind_speed_10m"][i], "wind_direction": h["wind_direction_10m"][i],
                                     "rainfall": h["precipitation"][i]} for i, t in enumerate(h.get("time", []))]}
    except Exception:  # noqa: BLE001
        return None


def current_with_fallback(db, lat: float, lon: float, location: str) -> dict:
    live = fetch_current(lat, lon)
    if live:
        db.add(WeatherObservation(timestamp=datetime.fromisoformat(live["observed_at"]), location=location, latitude=lat, longitude=lon,
                                  temperature=live["temperature"], humidity=live["humidity"], wind_speed=live["wind_speed"],
                                  wind_direction=live["wind_direction"], rainfall=live["rainfall"], source="open-meteo",
                                  retrieved_at=now()))
        db.commit()
        return live
    w = (db.query(WeatherObservation).filter(WeatherObservation.source == "synthetic-dataset")
         .order_by(WeatherObservation.timestamp.desc()).first())
    if not w:
        return {"source": "unavailable"}
    return {"source": "dataset-fallback (Open-Meteo unreachable)", "observed_at": w.timestamp.isoformat(), "retrieved_at": now().isoformat(),
            "temperature": w.temperature, "humidity": w.humidity, "wind_speed": w.wind_speed, "wind_direction": w.wind_direction,
            "rainfall": w.rainfall, "hourly_forecast": []}
