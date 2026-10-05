"""Agent 5 — Weather & Environmental Context Agent.

Retrieves live weather (Open-Meteo) for the station and analyses co-occurrence between weather and
pollutant behaviour using the stored hourly weather history. Language is strictly associative.
"""
from __future__ import annotations

import json
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy import stats

from ..database import SessionLocal
from ..services.weather_api import current_with_fallback
from ..tools import data_access as da
from ..tools import llm
from ..tools.geo import compass
from ..utils import clean
from .base import Step, event, fmt
from .prompts import PROMPTS

KEY_PARAM = {"air_quality": "pm2_5", "water_quality": "turbidity", "noise": "noise_laeq"}


def circular_mean(deg: pd.Series) -> float | None:
    d = deg.dropna()
    if d.empty:
        return None
    r = np.radians(d)
    return float((np.degrees(np.arctan2(np.sin(r).mean(), np.cos(r).mean())) + 360) % 360)


def weather_agent(state: dict) -> dict:
    st, now, wide = state["station"], state["now"], state["wide"]
    key = KEY_PARAM.get(st["monitoring_type"], "pm2_5")
    with Step("Weather & Environmental Context Agent", "weather", {"station_id": st["id"], "lat": st["latitude"], "lon": st["longitude"]}) as step:
        db = SessionLocal()
        try:
            live = current_with_fallback(db, st["latitude"], st["longitude"], st["location"])
            step.tool("weather_api.current (Open-Meteo)", {"lat": st["latitude"], "lon": st["longitude"]},
                      {k: live.get(k) for k in ("source", "observed_at", "temperature", "humidity", "wind_speed", "wind_direction", "rainfall")})
            wx = da.weather_frame(db, start=now - timedelta(days=30), end=now)
        finally:
            db.close()
        obs: list[str] = []
        ctx = {"current": {k: live.get(k) for k in ("source", "observed_at", "retrieved_at", "temperature", "humidity", "wind_speed", "wind_direction", "rainfall")}}
        if not wx.empty:
            last24 = wx[wx.index > wx.index.max() - timedelta(hours=24)]
            last3 = wx[wx.index > wx.index.max() - timedelta(hours=3)]
            prior = wx[wx.index <= wx.index.max() - timedelta(hours=24)]
            ctx.update({
                "history_source": "synthetic-dataset (hourly, stored)",
                "wind_mean_24h": round(float(last24.wind_speed.mean()), 2), "wind_mean_30d": round(float(prior.wind_speed.mean()), 2),
                "wind_mean_last3h": round(float(last3.wind_speed.mean()), 2),
                "wind_dir_24h_deg": circular_mean(last24.wind_direction), "rain_24h_mm": round(float(last24.rainfall.sum()), 1),
                "rain_48h_mm": round(float(wx[wx.index > wx.index.max() - timedelta(hours=48)].rainfall.sum()), 1),
                "humidity_mean_24h": round(float(last24.humidity.mean()), 1), "temp_mean_24h": round(float(last24.temperature.mean()), 1)})
            ctx["wind_dir_24h"] = compass(ctx["wind_dir_24h_deg"]) if ctx["wind_dir_24h_deg"] is not None else None
            # event window = hours in last 24 h where the key parameter is above its 30-day 90th percentile
            if key in wide and wide[key].notna().sum() > 48:
                s = wide[key]
                p90 = s.quantile(0.9)
                ev = s[(s.index > s.index.max() - timedelta(hours=24)) & (s > p90)]
                if len(ev) >= 3:
                    ew = wx.reindex(ev.index)
                    ctx["event_window"] = {"hours": len(ev), "start": ev.index.min(), "end": ev.index.max(),
                                           "wind_mean": round(float(ew.wind_speed.mean()), 2), "wind_dir_deg": circular_mean(ew.wind_direction),
                                           "rain_mm": round(float(ew.rainfall.sum()), 1)}
                    if ctx["event_window"]["wind_dir_deg"] is not None:
                        ctx["event_window"]["wind_from"] = compass(ctx["event_window"]["wind_dir_deg"])
                    if ew.wind_speed.mean() < 0.7 * ctx["wind_mean_30d"]:
                        obs.append(f"Elevated {key} values in the last 24 h occurred during low-wind conditions (mean {fmt(ew.wind_speed.mean(), 2)} m/s vs. "
                                   f"30-day mean {fmt(ctx['wind_mean_30d'], 2)} m/s).")
                joined = pd.concat([s, wx.wind_speed], axis=1, keys=["v", "w"], sort=True).dropna()
                if len(joined) > 48 and st["monitoring_type"] == "air_quality":
                    rho, p = stats.spearmanr(joined.v, joined.w)
                    ctx["association_wind"] = {"spearman_rho": round(float(rho), 3), "p_value": round(float(p), 5), "n": len(joined)}
                    if p < 0.05:
                        obs.append(f"Over 30 days, {key} and wind speed show a {'negative' if rho < 0 else 'positive'} association "
                                   f"(Spearman ρ = {fmt(rho, 2)}). Association does not establish causation.")
            # changing weather
            if ctx.get("event_window") and abs(ctx["wind_mean_last3h"] - ctx["event_window"]["wind_mean"]) > 1.5:
                obs.append(f"Weather is changing: wind speed moved from {fmt(ctx['event_window']['wind_mean'], 2)} m/s during the elevated period "
                           f"to {fmt(ctx['wind_mean_last3h'], 2)} m/s in the last 3 h.")
                ctx["weather_changing"] = True
            if ctx["rain_48h_mm"] > 1:
                obs.append(f"Rainfall of {fmt(ctx['rain_48h_mm'])} mm was recorded in the last 48 h; runoff can coincide with turbidity changes.")
            elif st["monitoring_type"] == "water_quality":
                obs.append("No rainfall was recorded in the last 48 h.")
            if ctx["humidity_mean_24h"] > 85 and st["monitoring_type"] == "air_quality":
                obs.append("Mean humidity above 85 % — optical PM sensors can over-read under these conditions (see sensor manual).")
        if not obs:
            obs.append("No notable weather pattern coincided with the readings.")
        ctx["observations"] = obs
        gen = llm.generate(PROMPTS["weather"], json.dumps(clean(ctx), default=str))
        step.llm_used = bool(gen)
        ctx["interpretation"] = gen or " ".join(obs)
        step.output = {"current": ctx["current"], "observations": obs}
    return {"weather_context": ctx, "trace": [step.record()],
            "events": [event("WEATHER_CONTEXT", {"source": live.get("source"), "wind_speed": live.get("wind_speed"), "observations": len(obs)})]}
