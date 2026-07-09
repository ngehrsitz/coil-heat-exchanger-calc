"""Tests for the sweep engine."""

import math

import pytest

from physics.calculator import FixedInputs, PhysicsError
from physics.fluid_air import W_from_RH
from physics.geometry import RegisterGeometry
from physics.units import KELVIN_OFFSET, to_kelvin, to_m3s
from sweep.sweep import (
    AxisSpec,
    AxisVariable,
    axis_midpoint_si,
    default_steps,
    resolve_humidity,
    run_sweep,
)


def _base_inputs():
    return FixedInputs(
        air_flow=to_m3s(500.0, "m³/h"),
        air_temp_in=to_kelvin(20.0, "°C"),
        water_temp_in=to_kelvin(60.0, "°C"),
        water_flow=to_m3s(2.0, "L/min"),
    )


def test_correct_point_count():
    axis = AxisSpec(
        AxisVariable.WATER_TEMP_IN,
        min_si=to_kelvin(40.0, "°C"),
        max_si=to_kelvin(80.0, "°C"),
        steps=10,
    )
    points = run_sweep(_base_inputs(), RegisterGeometry(), axis)
    assert len(points) == 10


def test_no_nan_in_valid_range():
    axis = AxisSpec(
        AxisVariable.WATER_TEMP_IN,
        min_si=to_kelvin(30.0, "°C"),
        max_si=to_kelvin(80.0, "°C"),
        steps=50,
    )
    points = run_sweep(_base_inputs(), RegisterGeometry(), axis)
    for p in points:
        assert not math.isnan(p.power_kw), f"NaN at x={p.x_si}"
        assert not math.isnan(p.air_temp_out_c)
        assert not math.isnan(p.water_temp_out_c)
        # Heating sweep (air in 20 °C, water in 30–80 °C): the water gives up heat,
        # so it must leave cooler than it entered but no colder than the inlet air.
        water_in_c = p.x_si - KELVIN_OFFSET
        assert 20.0 <= p.water_temp_out_c <= water_in_c


def test_power_monotonic_with_water_temp():
    """Higher water inlet temperature → more heating power (all points in heating mode)."""
    axis = AxisSpec(
        AxisVariable.WATER_TEMP_IN,
        min_si=to_kelvin(30.0, "°C"),
        max_si=to_kelvin(80.0, "°C"),
        steps=20,
    )
    points = run_sweep(_base_inputs(), RegisterGeometry(), axis)
    powers = [p.power_kw for p in points if not math.isnan(p.power_kw)]
    # Air inlet is 20°C; water ranges 30–80°C, so all points are in heating mode
    # Power increases monotonically with water inlet temperature
    assert all(powers[i] <= powers[i + 1] for i in range(len(powers) - 1)), (
        "Power should increase monotonically with water temp"
    )


def test_sweep_air_flow():
    axis = AxisSpec(
        AxisVariable.AIR_FLOW, min_si=to_m3s(100.0, "m³/h"), max_si=to_m3s(800.0, "m³/h"), steps=20
    )
    points = run_sweep(_base_inputs(), RegisterGeometry(), axis)
    assert len(points) == 20
    valid = [p for p in points if not math.isnan(p.power_kw)]
    assert len(valid) > 0


def test_invalid_points_have_error_message():
    """Zero air flow should produce a NaN point with an error message."""
    axis = AxisSpec(AxisVariable.AIR_FLOW, min_si=0.0, max_si=to_m3s(100.0, "m³/h"), steps=5)
    points = run_sweep(_base_inputs(), RegisterGeometry(), axis)
    # First point has air_flow=0 — should be NaN with an error
    first = points[0]
    assert math.isnan(first.power_kw)
    assert first.error != ""


def test_sweep_carries_outlet_rh():
    """A cooling sweep with humid air yields finite outlet RH in [0,100]."""
    T_air = to_kelvin(30.0, "°C")
    fixed = FixedInputs(
        air_flow=to_m3s(500.0, "m³/h"),
        air_temp_in=T_air,
        water_temp_in=to_kelvin(7.0, "°C"),
        water_flow=to_m3s(5.0, "L/min"),
        humidity_ratio=W_from_RH(T_air, 0.70),
    )
    axis = AxisSpec(
        AxisVariable.WATER_TEMP_IN,
        min_si=to_kelvin(5.0, "°C"),
        max_si=to_kelvin(25.0, "°C"),
        steps=30,
    )
    points = run_sweep(fixed, RegisterGeometry(), axis)
    valid = [p for p in points if p.error == ""]
    assert len(valid) > 0
    for p in valid:
        assert not math.isnan(p.air_rh_out_pct)
        assert 0.0 <= p.air_rh_out_pct <= 100.0
    # Cold-water end should be condensing.
    assert any(p.is_wet for p in valid)


def test_outlet_rh_varies_along_air_temp_sweep():
    """RH varies along an air-temperature sweep because absolute humidity W is held.

    CLAUDE.md's modelling choice: inlet RH% is resolved to a humidity ratio W
    once, then W (not RH) is held constant across the sweep. Sweeping the air
    inlet temperature at fixed W must therefore make the *outlet* RH change — a
    lower air temperature at fixed moisture sits closer to saturation. This is the
    one axis (AIR_TEMP_IN) that exercises that behavior, and no other sweep test
    uses it. Kept in a mild heating regime so the coil stays dry (W_out == W_in)
    and the outlet RH cleanly reflects the outlet temperature alone.
    """
    T_mid = to_kelvin(20.0, "°C")
    fixed = FixedInputs(
        air_flow=to_m3s(500.0, "m³/h"),
        air_temp_in=T_mid,  # placeholder; overridden per point
        water_temp_in=to_kelvin(45.0, "°C"),
        water_flow=to_m3s(5.0, "L/min"),
        # W resolved at the range midpoint temperature (as the UI does).
        humidity_ratio=W_from_RH(T_mid, 0.40),
    )
    axis = AxisSpec(
        AxisVariable.AIR_TEMP_IN,
        min_si=to_kelvin(10.0, "°C"),
        max_si=to_kelvin(30.0, "°C"),
        steps=30,
    )
    points = run_sweep(fixed, RegisterGeometry(), axis)
    valid = [p for p in points if p.error == ""]
    assert len(valid) == 30
    rhs = [p.air_rh_out_pct for p in valid]
    for rh in rhs:
        assert 0.0 <= rh <= 100.0
    # x ascends (colder → warmer air inlet). At fixed W, warmer air is drier, so
    # outlet RH must fall monotonically — and actually move, not stay flat.
    assert all(rhs[i] >= rhs[i + 1] for i in range(len(rhs) - 1)), (
        "Outlet RH should decrease monotonically as air inlet temperature rises"
    )
    assert rhs[0] - rhs[-1] > 5.0, "Outlet RH should vary appreciably along the sweep"


def test_resolve_humidity_matches_w_from_rh():
    """resolve_humidity is the sweep layer's owner of the RH→W conversion; it
    must agree exactly with the physics primitive it wraps."""
    T = to_kelvin(25.0, "°C")
    for rh in (0.0, 0.3, 0.5, 0.9, 1.0):
        assert resolve_humidity(T, rh) == W_from_RH(T, rh)


def test_resolve_humidity_raises_physics_error_on_property_failure():
    """A moist-air property failure must surface as PhysicsError, not a raw
    CoolProp exception. This call happens once before the sweep loop (outside
    run_sweep's per-point NaN net), so an unwrapped error would abort the run."""
    # 500 K is far outside the moist-air property envelope; CoolProp raises there.
    with pytest.raises(PhysicsError):
        resolve_humidity(500.0, 0.5)


def test_default_steps_floor_and_scaling():
    """At least 100 points; wider ranges get at least one point per integer unit."""
    # Narrow range → floored at 100.
    assert default_steps(20.0, 25.0) == 100
    assert default_steps(0.0, 0.0) == 100
    # Wide range → one point per integer unit. linspace(a, b, n) spans n-1
    # intervals, so a span of S units needs ceil(S)+1 points for ceil(S) intervals.
    assert default_steps(0.0, 250.0) == 251
    # Order-independent (span magnitude is what matters).
    assert default_steps(80.0, 40.0) == 100
    assert default_steps(10.5, 260.0) == math.ceil(260.0 - 10.5) + 1


def test_default_steps_gives_at_least_one_interval_per_unit():
    """The step count must yield at least one *interval* per integer display unit.

    np.linspace(min, max, steps) produces steps-1 intervals; the contract is
    "at least one point per integer unit", so intervals >= ceil(span).
    """
    span = 150.0  # > _MIN_SWEEP_STEPS so the floor does not mask the count
    steps = default_steps(0.0, span)
    intervals = steps - 1
    assert intervals >= math.ceil(span)
    # And the interval width is no coarser than one display unit.
    assert span / intervals <= 1.0


def test_axis_midpoint_si():
    """The swept-variable placeholder is the arithmetic midpoint of the range."""
    assert axis_midpoint_si(10.0, 20.0) == 15.0
    assert axis_midpoint_si(20.0, 10.0) == 15.0  # order-independent
    assert axis_midpoint_si(5.0, 5.0) == 5.0


def test_extrapolation_flags_air_side_in_range():
    """A nominal heating sweep keeps the air-side Reynolds number inside the
    Colburn correlation range, so no point sets air_extrapolated. (The nominal
    2 L/min water flow is laminar, so water_extrapolated is expected there.)"""
    axis = AxisSpec(
        AxisVariable.WATER_TEMP_IN,
        min_si=to_kelvin(40.0, "°C"),
        max_si=to_kelvin(80.0, "°C"),
        steps=20,
    )
    points = run_sweep(_base_inputs(), RegisterGeometry(), axis)
    valid = [p for p in points if p.error == ""]
    assert len(valid) > 0
    assert not any(p.air_extrapolated for p in valid)


def test_extrapolation_flag_air_out_of_range():
    """A very large air flow drives the air-side Reynolds number above the
    correlation's upper bound, setting air_extrapolated on the affected points."""
    axis = AxisSpec(
        AxisVariable.AIR_FLOW,
        min_si=to_m3s(5000.0, "m³/h"),
        max_si=to_m3s(20000.0, "m³/h"),
        steps=10,
    )
    points = run_sweep(_base_inputs(), RegisterGeometry(), axis)
    valid = [p for p in points if p.error == ""]
    assert len(valid) > 0
    assert any(p.air_extrapolated for p in valid)
