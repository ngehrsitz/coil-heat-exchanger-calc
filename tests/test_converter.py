"""Tests for unit conversion helpers."""

import pytest

from physics.axis_model import (
    display_bounds,
    from_si,
    kind_of,
    temp_in_range,
    temp_range,
    to_si,
)
from physics.fluid_air import AIR_T_MAX, AIR_T_MIN
from physics.fluid_water import WATER_T_MAX, WATER_T_MIN
from physics.units import (
    from_kelvin,
    from_m3s,
    from_meter,
    to_kelvin,
    to_m3s,
    to_meter,
)

# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------


def test_celsius_to_kelvin():
    assert abs(to_kelvin(20.0, "°C") - 293.15) < 1e-9


def test_kelvin_roundtrip():
    assert abs(to_kelvin(300.0, "K") - 300.0) < 1e-9


def test_fahrenheit_to_kelvin():
    # 32°F = 0°C = 273.15 K
    assert abs(to_kelvin(32.0, "°F") - 273.15) < 1e-9
    # 212°F = 100°C = 373.15 K
    assert abs(to_kelvin(212.0, "°F") - 373.15) < 1e-9


def test_kelvin_to_celsius():
    assert abs(from_kelvin(293.15, "°C") - 20.0) < 1e-9


def test_from_kelvin_unknown_unit():
    with pytest.raises(ValueError):
        from_kelvin(300.0, "R")


def test_temperature_roundtrip():
    for unit in ("°C", "K", "°F"):
        v = 50.0
        assert abs(from_kelvin(to_kelvin(v, unit), unit) - v) < 1e-9


def test_unknown_temperature_unit():
    with pytest.raises(ValueError):
        to_kelvin(20.0, "R")


# ---------------------------------------------------------------------------
# Volume flow
# ---------------------------------------------------------------------------


def test_m3h_to_m3s():
    assert abs(to_m3s(3600.0, "m³/h") - 1.0) < 1e-9


def test_lmin_to_m3s():
    assert abs(to_m3s(60_000.0, "L/min") - 1.0) < 1e-9


def test_ls_to_m3s():
    assert abs(to_m3s(1000.0, "L/s") - 1.0) < 1e-9


def test_500_m3h():
    assert abs(to_m3s(500.0, "m³/h") - 500.0 / 3600.0) < 1e-10


def test_flow_roundtrip():
    for unit in ("m³/s", "m³/h", "L/s", "L/min", "CFM"):
        v = 1.5
        assert abs(from_m3s(to_m3s(v, unit), unit) - v) < 1e-9


def test_unknown_flow_unit():
    with pytest.raises(ValueError):
        to_m3s(1.0, "gal/min")


def test_from_m3s_unknown_unit():
    with pytest.raises(ValueError):
        from_m3s(1.0, "gal/min")


# ---------------------------------------------------------------------------
# Length
# ---------------------------------------------------------------------------


def test_mm_to_m():
    assert abs(to_meter(1000.0, "mm") - 1.0) < 1e-12


def test_length_roundtrip():
    for unit in ("m", "mm"):
        v = 25.4
        assert abs(from_meter(to_meter(v, unit), unit) - v) < 1e-9


def test_to_meter_unknown_unit():
    with pytest.raises(ValueError):
        to_meter(1.0, "cm")


def test_from_meter_unknown_unit():
    with pytest.raises(ValueError):
        from_meter(1.0, "km")


# ---------------------------------------------------------------------------
# Axis-variable dispatch: to_si / from_si
# ---------------------------------------------------------------------------


def test_to_si_temperature():
    assert abs(to_si("air_temp_in", 20.0, "°C") - 293.15) < 1e-9
    assert abs(to_si("water_temp_in", 60.0, "°C") - 333.15) < 1e-9


def test_to_si_air_flow():
    assert abs(to_si("air_flow", 3600.0, "m³/h") - 1.0) < 1e-9


def test_to_si_water_flow():
    assert abs(to_si("water_flow", 60_000.0, "L/min") - 1.0) < 1e-9


def test_to_si_unknown_variable():
    with pytest.raises(ValueError):
        to_si("humidity_ratio", 50.0, "%")


def test_from_si_temperature():
    assert abs(from_si("water_temp_in", 293.15, "°C") - 20.0) < 1e-9
    assert abs(from_si("air_temp_in", 293.15, "K") - 293.15) < 1e-9


def test_from_si_air_flow():
    assert abs(from_si("air_flow", 1.0, "m³/h") - 3600.0) < 1e-6


def test_from_si_water_flow():
    assert abs(from_si("water_flow", 1.0, "L/min") - 60_000.0) < 1e-3


def test_from_si_unknown_variable():
    with pytest.raises(ValueError):
        from_si("humidity_ratio", 1.0, "%")


def test_si_roundtrip():
    for var, unit in (
        ("air_temp_in", "°F"),
        ("water_temp_in", "°C"),
        ("air_flow", "CFM"),
        ("water_flow", "L/s"),
    ):
        v = 42.0
        assert abs(from_si(var, to_si(var, v, unit), unit) - v) < 1e-6


# ---------------------------------------------------------------------------
# Input bounds — kind_of / display_bounds / temp envelope
# ---------------------------------------------------------------------------


def test_kind_of_temperature():
    assert kind_of("air_temp_in") == "temperature"
    assert kind_of("water_temp_in") == "temperature"


def test_kind_of_flow():
    assert kind_of("air_flow") == "flow"
    assert kind_of("water_flow") == "flow"


def test_kind_of_unknown():
    with pytest.raises(ValueError):
        kind_of("humidity_ratio")


def test_temperature_display_bounds_floor_at_absolute_zero_no_max():
    # Widget hard limit for temperatures: just above absolute zero, unbounded
    # above. The narrower property envelope is validated, not clamped.
    lo, hi = display_bounds("air_temp_in", "K")
    assert 0.0 < lo < 1.0
    assert hi is None
    lo_c, hi_c = display_bounds("air_temp_in", "°C")
    assert -273.15 < lo_c < -273.0
    assert hi_c is None


def test_flow_bounds_positive_floor_unbounded_above():
    # Floor is 0.001 in the display unit (smallest 3-decimal value)
    for unit in ("m³/h", "m³/s", "L/s", "L/min", "CFM"):
        lo, hi = display_bounds("air_flow", unit)
        assert lo == 0.001
        assert hi is None
    assert display_bounds("water_flow", "L/min")[0] == 0.001


def test_display_bounds_unknown_variable():
    with pytest.raises(ValueError):
        display_bounds("humidity_ratio", "%")


def test_temp_range_matches_fluid_envelope():
    # Envelope tracks the CoolProp-backed modules, converted to the display unit.
    assert temp_range("air_temp_in", "K") == (AIR_T_MIN, AIR_T_MAX)
    assert temp_range("water_temp_in", "K") == (WATER_T_MIN, WATER_T_MAX)
    lo_c, hi_c = temp_range("air_temp_in", "°C")
    assert abs(lo_c - (AIR_T_MIN - 273.15)) < 1e-9
    assert abs(hi_c - (AIR_T_MAX - 273.15)) < 1e-9


def test_temp_in_range():
    assert temp_in_range("air_temp_in", 300.0)
    assert temp_in_range("air_temp_in", AIR_T_MIN)
    assert temp_in_range("air_temp_in", AIR_T_MAX)
    assert not temp_in_range("air_temp_in", AIR_T_MIN - 1.0)
    assert not temp_in_range("air_temp_in", AIR_T_MAX + 1.0)
    # Water envelope is distinct: 250 K is fine for air, too cold for water.
    assert not temp_in_range("water_temp_in", 250.0)
