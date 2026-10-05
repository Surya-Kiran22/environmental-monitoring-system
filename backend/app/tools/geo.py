"""Geospatial helpers: distances, bearings, cross-station comparison and source-investigation support."""
from __future__ import annotations

import math


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def angle_diff(a, b) -> float:
    return abs((a - b + 180) % 360 - 180)


def compass(deg: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int((deg % 360) / 22.5 + 0.5) % 16]


def classify_spatial(elevated: int, total: int, self_elevated: bool) -> tuple[str, str]:
    if total <= 1:
        return "insufficient_stations", "No comparable nearby station; spatial extent cannot be assessed."
    if not self_elevated and elevated == 0:
        return "not_elevated", "No station in the comparison group is elevated."
    share = elevated / total
    if self_elevated and elevated == 1:
        return "localized", "Only this station is elevated; nearby stations are within normal range. Pattern appears localized."
    if share >= 0.6:
        return "distributed", f"{elevated} of {total} nearby stations are elevated. Pattern appears geographically distributed (area-wide)."
    return "partially_distributed", f"{elevated} of {total} nearby stations are elevated. Pattern is partially distributed."


def upwind_sources(station: dict, sources: list[dict], wind_from_deg: float | None, radius_km: float, tolerance: float = 45) -> list[dict]:
    """Registered sources within radius whose bearing from the station is within ±tolerance of the wind-from direction."""
    out = []
    for s in sources:
        d = haversine_km(station["latitude"], station["longitude"], s["latitude"], s["longitude"])
        if d > radius_km:
            continue
        b = bearing_deg(station["latitude"], station["longitude"], s["latitude"], s["longitude"])
        upwind = wind_from_deg is not None and angle_diff(b, wind_from_deg) <= tolerance
        out.append({**s, "distance_km": round(d, 2), "bearing_deg": round(b), "bearing": compass(b), "upwind": upwind,
                    "label": "Source requiring investigation" if upwind else "Nearby registered source (not upwind)"})
    return sorted(out, key=lambda x: (not x["upwind"], x["distance_km"]))
