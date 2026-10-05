"""
Synthetic environmental dataset generator for the Vijayawada demo network.

Produces 30 days of hourly data for 8 monitoring stations (4 air, 2 water, 2 noise)
plus regional weather, fictional registered sources and ground-truth event labels
(used only to evaluate the anomaly model, never shown to the agents).

Injected scenarios (all relative to the final hour of the dataset):
  * Air: area-wide PM episode during the last ~24 h under low wind at ENV-ST-001/002/004,
         ENV-ST-003 stays normal. The final ENV-ST-004 reading equals the problem-statement
         example (PM2.5 92, PM10 148, NO2 62, SO2 28, CO 1.4; 31 C, 68 %, 4.5 m/s).
  * Sensor fault: single unrealistic CO spike (46 mg/m3) at ENV-ST-003, 30 h before end.
  * Data quality: missing PM2.5 hours at ENV-ST-003, a duplicated timestamp at ENV-ST-001.
  * Water: rain-driven turbidity rise ~18 days before end (valid environmental change);
           turbidity 3.2 -> 12.8 NTU over the final 6 h at ENV-WQ-001 with a DO decline.
  * Stale sensor: ENV-WQ-002 stops reporting 9 h before the end.
  * Noise: repeated night-time exceedances (22:00-02:00) for the last 5 nights at ENV-NS-002.

Run:  python data/generate_data.py            (writes CSVs next to this file)
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
RNG = np.random.default_rng(42)
DAYS = 30

STATIONS = [
    # id, name, type, location, lat, lon, zone, water_class, parameters
    ("ENV-ST-001", "Benz Circle AQ Station", "air_quality", "Benz Circle, Vijayawada", 16.4990, 80.6560, "commercial", "", "pm2_5;pm10;no2;so2;co;o3"),
    ("ENV-ST-002", "Auto Nagar AQ Station", "air_quality", "Auto Nagar, Vijayawada", 16.4955, 80.6745, "industrial", "", "pm2_5;pm10;no2;so2;co;o3"),
    ("ENV-ST-003", "Gunadala AQ Station", "air_quality", "Gunadala, Vijayawada", 16.5195, 80.6530, "residential", "", "pm2_5;pm10;no2;so2;co;o3"),
    ("ENV-ST-004", "Industrial Zone A AQ Station", "air_quality", "Industrial Zone A, Kondapalli", 16.6180, 80.5420, "industrial", "", "pm2_5;pm10;no2;so2;co;o3"),
    ("ENV-WQ-001", "Krishna River - Prakasam Barrage", "water_quality", "Prakasam Barrage, Vijayawada", 16.5065, 80.6040, "water_body", "C", "ph;dissolved_oxygen;turbidity;conductivity;tds;water_temperature"),
    ("ENV-WQ-002", "Budameru Canal Outfall", "water_quality", "Budameru Canal, Vijayawada", 16.5310, 80.6290, "water_body", "C", "ph;dissolved_oxygen;turbidity;conductivity;tds;water_temperature"),
    ("ENV-NS-001", "Governorpet Noise Station", "noise", "Governorpet, Vijayawada", 16.5135, 80.6295, "commercial", "", "noise_laeq"),
    ("ENV-NS-002", "Patamata Noise Station", "noise", "Patamata, Vijayawada", 16.4985, 80.6655, "residential", "", "noise_laeq"),
]

UNITS = {
    "pm2_5": "µg/m³", "pm10": "µg/m³", "no2": "µg/m³", "so2": "µg/m³", "o3": "µg/m³", "co": "mg/m³",
    "ph": "pH", "dissolved_oxygen": "mg/L", "turbidity": "NTU", "conductivity": "µS/cm", "tds": "mg/L",
    "water_temperature": "°C", "noise_laeq": "dB(A)",
}

# Fictional registered units — deliberately anonymised so no real organisation is implicated.
SOURCES = [
    ("SRC-101", "Registered Unit R-101 (cement grinding)", "industrial", 16.6265, 80.5335),
    ("SRC-102", "Registered Unit R-102 (stone crushing)", "industrial", 16.6090, 80.5560),
    ("SRC-103", "Registered Unit R-103 (foundry)", "industrial", 16.4925, 80.6810),
    ("SRC-104", "Bus depot & fuel station", "transport", 16.5040, 80.6500),
    ("SRC-105", "Municipal STP outfall", "wastewater", 16.5120, 80.6000),
    ("SRC-106", "Function hall cluster", "commercial", 16.4995, 80.6690),
]


def main(end: datetime | None = None) -> None:
    end = (end or datetime.now()).replace(minute=0, second=0, microsecond=0)
    hours = DAYS * 24
    idx = pd.date_range(end=end, periods=hours, freq="h")
    t = np.arange(hours)
    hod = idx.hour.values
    from_end = hours - 1 - t  # hours before the final timestamp

    # ---------------- regional weather ----------------
    temp = 28 + 4 * np.sin(2 * np.pi * (hod - 9) / 24) + RNG.normal(0, 0.7, hours)
    hum = 72 - 12 * np.sin(2 * np.pi * (hod - 9) / 24) + RNG.normal(0, 3, hours)
    wind = np.clip(3.4 + 1.2 * np.sin(2 * np.pi * (hod - 14) / 24) + RNG.normal(0, 0.5, hours), 0.3, None)
    wdir = (220 + 25 * np.sin(2 * np.pi * t / 96) + RNG.normal(0, 12, hours)) % 360
    rain = np.zeros(hours)
    rain_window = (from_end >= 18 * 24 - 10) & (from_end <= 18 * 24)  # rain ~18 days before end
    rain[rain_window] = RNG.uniform(2, 9, rain_window.sum())
    rain[(from_end >= 9 * 24) & (from_end <= 9 * 24 + 3)] = 1.5
    # episode: low wind for 26 h before the last 3 h, then wind picks up (changing weather)
    episode = (from_end >= 3) & (from_end <= 28)
    wind[episode] = np.clip(RNG.normal(1.3, 0.25, episode.sum()), 0.4, None)
    wdir[episode] = (300 + RNG.normal(0, 10, episode.sum())) % 360  # north-westerly
    recovery = from_end < 3
    wind[recovery] = [3.6, 4.1, 4.5][: recovery.sum()]
    temp[-1], hum[-1], wind[-1] = 31.0, 68.0, 4.5
    weather = pd.DataFrame({
        "timestamp": idx, "location": "Vijayawada", "temperature": temp.round(1), "humidity": np.clip(hum, 20, 100).round(0),
        "wind_speed": wind.round(2), "wind_direction": wdir.round(0), "rainfall": rain.round(1), "source": "synthetic-dataset",
    })

    rows: list[tuple] = []
    labels: list[tuple] = []

    def add(sid: str, p: str, values: np.ndarray) -> None:
        for ts, v in zip(idx, values):
            rows.append((sid, ts, p, None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 3), UNITS[p]))

    # ---------------- air ----------------
    diurnal = 1 + 0.22 * np.cos(2 * np.pi * (hod - 8) / 24) + 0.18 * np.cos(2 * np.pi * (hod - 21) / 12)
    stagnation = 1 + 0.45 * np.clip((3.0 - wind) / 3.0, -0.4, 1)
    washout = np.where(rain > 1, 0.7, 1.0)
    air_base = {"ENV-ST-001": (44, 28, 11, 0.85), "ENV-ST-002": (50, 33, 15, 0.95), "ENV-ST-003": (34, 22, 9, 0.7), "ENV-ST-004": (47, 36, 19, 0.9)}
    episode_gain = {"ENV-ST-001": 1.55, "ENV-ST-002": 1.6, "ENV-ST-003": 1.0, "ENV-ST-004": 1.75}
    for sid, (pm, no2, so2, co) in air_base.items():
        gain = np.where(episode | recovery, episode_gain[sid], 1.0)
        if sid == "ENV-ST-003":
            st = np.ones(hours)  # Gunadala sits outside the stagnant plume in this scenario
            st[~(episode | recovery)] = stagnation[~(episode | recovery)]
        else:
            st = stagnation
        noise = RNG.lognormal(0, 0.09, hours)
        pm25 = pm * diurnal * st * washout * gain * noise
        pm10 = pm25 * RNG.normal(1.62, 0.06, hours)
        n2 = no2 * (0.8 + 0.4 * diurnal) * st * gain * RNG.lognormal(0, 0.08, hours) * np.where(gain > 1, 1.05, 1)
        s2 = so2 * st * gain * RNG.lognormal(0, 0.1, hours)
        c = co * diurnal * st * np.where(gain > 1, 1.25, 1) * RNG.lognormal(0, 0.07, hours)
        o3 = 30 + 35 * np.clip(np.sin(2 * np.pi * (hod - 7) / 24), 0, None) + RNG.normal(0, 4, hours)
        if sid == "ENV-ST-004":
            pm25[-1], pm10[-1], n2[-1], s2[-1], c[-1] = 92, 148, 62, 28, 1.4
        if sid == "ENV-ST-003":
            c[hours - 1 - 30] = 46.0  # unrealistic single-hour spike -> sensor verification
            labels.append((sid, idx[hours - 1 - 30], "co", "sensor_spike"))
            pm25 = pm25.astype(float)
            for h in (40, 41, 42, 77):
                pm25[hours - 1 - h] = np.nan
                pm10[hours - 1 - h] = np.nan
        for i in np.where((episode | recovery) & (episode_gain[sid] > 1))[0]:
            labels.append((sid, idx[i], "pm2_5", "pollution_episode"))
        for p, arr in (("pm2_5", pm25), ("pm10", pm10), ("no2", n2), ("so2", s2), ("co", c), ("o3", o3)):
            add(sid, p, arr)
    # duplicate timestamp (data-quality test)
    dup_ts = idx[hours - 1 - 12]
    rows.append(("ENV-ST-001", dup_ts, "pm2_5", 61.0, UNITS["pm2_5"]))

    # ---------------- water ----------------
    for sid, ph0, do0, tb0, ec0 in (("ENV-WQ-001", 7.6, 6.9, 3.0, 420), ("ENV-WQ-002", 7.3, 5.6, 4.2, 610)):
        ph = ph0 + 0.08 * np.sin(2 * np.pi * (hod - 14) / 24) + RNG.normal(0, 0.05, hours)
        do = do0 + 0.5 * np.sin(2 * np.pi * (hod - 15) / 24) + RNG.normal(0, 0.12, hours)
        tb = tb0 + RNG.normal(0, 0.25, hours)
        # rain-driven runoff: turbidity rises and decays after the rain event
        rain_idx = np.where(rain_window)[0]
        if len(rain_idx):
            r0 = rain_idx[0]
            k = np.arange(hours) - r0
            pulse = np.where(k >= 0, 5.5 * np.exp(-np.clip(k, 0, None) / 14.0), 0)
            tb = tb + pulse
            for i in np.where(pulse > 1.5)[0]:
                labels.append((sid, idx[i], "turbidity", "rain_runoff"))
        ec = ec0 + RNG.normal(0, 12, hours)
        wt = 27 + 0.8 * np.sin(2 * np.pi * (hod - 15) / 24) + RNG.normal(0, 0.15, hours)
        if sid == "ENV-WQ-001":
            ramp = np.array([3.2, 4.1, 5.6, 7.4, 9.3, 11.2, 12.8])
            tb[-7:] = ramp
            do[-7:] = np.linspace(do[-8], 5.2, 7)
            ec[-7:] = ec[-7:] + np.linspace(0, 140, 7)
            for i in range(hours - 6, hours):
                labels.append((sid, idx[i], "turbidity", "water_deterioration"))
        tds = ec * 0.64 + RNG.normal(0, 5, hours)
        vals = {"ph": ph, "dissolved_oxygen": do, "turbidity": tb, "conductivity": ec, "tds": tds, "water_temperature": wt}
        if sid == "ENV-WQ-002":  # stale sensor: stops reporting 9 h before the end
            for p in vals:
                vals[p] = vals[p].astype(float)
                vals[p][-9:] = np.nan
        for p, arr in vals.items():
            if sid == "ENV-WQ-002":
                for ts, v in zip(idx[:-9], arr[:-9]):
                    rows.append((sid, ts, p, round(float(v), 3), UNITS[p]))
            else:
                add(sid, p, arr)

    # ---------------- noise ----------------
    night = (hod >= 22) | (hod < 6)
    for sid, day0, night0 in (("ENV-NS-001", 61.5, 51.0), ("ENV-NS-002", 51.5, 41.5)):
        lv = np.where(night, night0, day0) + 2.5 * np.sin(2 * np.pi * (hod - 13) / 24) * (~night) + RNG.normal(0, 1.6, hours)
        if sid == "ENV-NS-002":
            late = ((hod >= 22) | (hod <= 1)) & (from_end <= 5 * 24 + 6)
            lv[late] = RNG.normal(56.5, 1.2, late.sum())
            for i in np.where(late)[0]:
                labels.append((sid, idx[i], "noise_laeq", "night_noise_event"))
        add(sid, "noise_laeq", lv)

    meas = pd.DataFrame(rows, columns=["station_id", "timestamp", "parameter", "value", "unit"])
    meas.to_csv(OUT / "measurements.csv", index=False)
    weather.to_csv(OUT / "weather.csv", index=False)
    pd.DataFrame(labels, columns=["station_id", "timestamp", "parameter", "label"]).to_csv(OUT / "event_labels.csv", index=False)
    pd.DataFrame(STATIONS, columns=["station_id", "name", "monitoring_type", "location", "latitude", "longitude", "zone_category", "water_class", "parameters"]).to_csv(OUT / "stations.csv", index=False)
    pd.DataFrame(SOURCES, columns=["source_id", "name", "category", "latitude", "longitude"]).to_csv(OUT / "registered_sources.csv", index=False)
    print(f"wrote {len(meas)} measurements, {len(weather)} weather rows, {len(labels)} labels ending {end}")


if __name__ == "__main__":
    main()
