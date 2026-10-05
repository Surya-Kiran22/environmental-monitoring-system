"""Unit tests for the deterministic tools."""
import pandas as pd

from app.tools.compliance import difference, evaluate, leq
from app.tools.geo import classify_spatial
from app.tools.validation import normalize_unit, validate_long

STD = {"id": "X", "parameter": "pm2_5", "limit_type": "max", "limit": 60, "averaging_period": "24h", "unit": "µg/m³"}


def test_difference_formula_is_deterministic():
    d, pct, exc = difference(92, STD)
    assert (d, pct, exc) == (32, 53.3, True)


def test_min_and_range_limits():
    assert difference(3.5, {"limit_type": "min", "limit": 4})[0] == 0.5
    assert difference(9.5, {"limit_type": "range", "min": 6, "max": 9})[2] is True
    assert difference(7.5, {"limit_type": "range", "min": 6, "max": 9})[2] is False


def test_hourly_value_not_compared_with_24h_limit():
    idx = pd.date_range("2026-01-01", periods=48, freq="h")
    s = pd.Series(30.0, index=idx)
    s.iloc[-1] = 92  # one high hour, 24-h mean stays far below 60
    r = evaluate(s, STD)
    assert r["status"] == "indicative_hourly_above" and r["exceeded"] is False


def test_low_completeness_is_indicative_only():
    idx = pd.date_range("2026-01-01", periods=48, freq="h")
    s = pd.Series(90.0, index=idx)
    s.iloc[-24:-8] = float("nan")  # only 8 of 24 h available
    r = evaluate(s, STD)
    assert r["status"] == "indicative_exceedance" and r["exceeded"] is False


def test_annual_standard_not_assessable_with_30_days():
    idx = pd.date_range("2026-01-01", periods=720, freq="h")
    r = evaluate(pd.Series(50.0, index=idx), {**STD, "averaging_period": "annual", "limit": 40})
    assert r["status"] == "not_assessable"


def test_unit_conversion():
    assert normalize_unit("co", 1.0, "ppm")[0:2] == (1.145, "mg/m³")
    assert normalize_unit("no2", 10, "ppb")[1] == "µg/m³"
    assert normalize_unit("pm2_5", 10, "furlongs")[2] is not None


def test_validation_flags_but_keeps_spike():
    idx = pd.date_range("2026-01-01", periods=10, freq="h")
    vals = [0.6] * 10
    vals[5] = 45
    df = pd.DataFrame({"station_id": "S", "timestamp": idx, "parameter": "co", "value": vals, "unit": "mg/m³"})
    out, issues = validate_long(df)
    assert len(out) == 10 and out.iloc[5].quality_flag == "suspect" and (out.quality_flag == "suspect").sum() == 1
    assert any(i["type"] == "unrealistic_change" for i in issues)


def test_leq_energy_average():
    assert round(leq([50, 50]), 1) == 50.0 and round(leq([40, 60]), 1) == 57.0


def test_spatial_classification():
    assert classify_spatial(1, 3, True)[0] == "localized"
    assert classify_spatial(2, 3, True)[0] == "distributed"
    assert classify_spatial(0, 3, False)[0] == "not_elevated"
