"""Sweep engine — varies one input parameter and returns a performance curve."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from physics.calculator import CalcResult, FixedInputs, PhysicsError, calculate
from physics.correlations import air_re_in_range, water_re_in_range
from physics.errors import humanize_error
from physics.fluid_air import W_from_RH
from physics.geometry import RegisterGeometry
from physics.units import KELVIN_OFFSET

logger = logging.getLogger(__name__)

# Minimum number of sweep points; also the floor in default_steps().
_MIN_SWEEP_STEPS = 100

# Watts per kilowatt — thermal power is reported to the chart in kW.
_W_PER_KW = 1000.0


def resolve_humidity(air_temp_in: float, rh_frac: float) -> float:
    """Inlet humidity ratio W [kg_w/kg_da] from inlet air temp [K] and RH fraction.

    Holding absolute humidity W constant across the sweep (rather than RH) is the
    physically correct choice: RH then varies along an air-temperature sweep. This
    conversion is a modelling decision, so it lives here in the sweep layer rather
    than in the UI, where it would only be reachable through Qt.

    Raises ``PhysicsError`` if the underlying moist-air property call fails (e.g. a
    CoolProp saturation/convergence edge). This is resolved once, before the sweep
    loop, so a raw exception here would otherwise abort the whole run instead of
    being handled like the per-point failures inside ``run_sweep``.
    """
    try:
        return W_from_RH(air_temp_in, rh_frac)
    except (ValueError, ZeroDivisionError) as exc:
        raise PhysicsError(f"Could not resolve inlet humidity: {exc}") from exc


def axis_midpoint_si(min_si: float, max_si: float) -> float:
    """Placeholder value for the swept variable when building ``FixedInputs``.

    The swept variable still needs *a* value in ``FixedInputs`` before the sweep
    overrides it per point; seeding it at the range midpoint is a modelling
    choice (it also sets the inlet air temperature at which RH→W is evaluated when
    air temp is the axis), so it lives here beside the other sweep-modelling
    decisions rather than in the UI.
    """
    return (min_si + max_si) / 2.0


def default_steps(min_display: float, max_display: float) -> int:
    """Number of sweep points: at least 100, and at least one per integer display unit.

    Wider ranges get proportionally more points so a long axis is not undersampled.
    ``min_display`` / ``max_display`` are the raw range endpoints in the user's
    display unit (the span, not the SI value, is what matters for sampling density).

    ``np.linspace(a, b, n)`` yields ``n`` points spanning ``n - 1`` intervals, so a
    span of ``S`` display units needs ``ceil(S) + 1`` points to place at least one
    point per unit (``ceil(S)`` intervals).
    """
    return max(_MIN_SWEEP_STEPS, math.ceil(abs(max_display - min_display)) + 1)


class AxisVariable(StrEnum):
    """The four sweepable input variables.

    A ``StrEnum`` so each member *is* its canonical string key (e.g.
    ``AxisVariable.AIR_FLOW == "air_flow"``); this lets it index the string-keyed
    metadata dicts in ``physics.units`` directly, without a separate conversion.
    """

    AIR_FLOW = "air_flow"
    AIR_TEMP_IN = "air_temp_in"
    WATER_TEMP_IN = "water_temp_in"
    WATER_FLOW = "water_flow"


@dataclass(frozen=True)
class AxisSpec:
    variable: AxisVariable
    min_si: float
    max_si: float
    steps: int = _MIN_SWEEP_STEPS


@dataclass(frozen=True)
class DataPoint:
    x_si: float  # swept variable value in SI
    power_kw: float  # thermal power in kW  (NaN on error)
    air_temp_out_c: float  # outlet air temperature in °C  (NaN on error)
    water_temp_out_c: float = math.nan  # water outlet (return) temperature in °C (NaN on error)
    air_rh_out_pct: float = math.nan  # outlet relative humidity in %
    humidity_ratio_out: float = math.nan  # outlet humidity ratio kg_w/kg_da
    is_wet: bool = False  # True if condensation occurred at this point
    re_air: float = math.nan  # air-side Reynolds number (for extrapolation checks)
    re_water: float = math.nan  # water-side Reynolds number
    air_extrapolated: bool = False  # True if air-side Re is outside the correlation range
    water_extrapolated: bool = False  # True if water-side Re is outside the correlation range
    error: str = ""  # non-empty if this point failed


def _make_inputs(fixed: FixedInputs, axis: AxisVariable, x: float) -> FixedInputs:
    """Return a copy of fixed inputs with the swept variable replaced by x."""
    return FixedInputs(
        air_flow=x if axis == AxisVariable.AIR_FLOW else fixed.air_flow,
        air_temp_in=x if axis == AxisVariable.AIR_TEMP_IN else fixed.air_temp_in,
        water_temp_in=x if axis == AxisVariable.WATER_TEMP_IN else fixed.water_temp_in,
        water_flow=x if axis == AxisVariable.WATER_FLOW else fixed.water_flow,
        humidity_ratio=fixed.humidity_ratio,
    )


def run_sweep(
    fixed: FixedInputs,
    geom: RegisterGeometry,
    axis: AxisSpec,
) -> list[DataPoint]:
    """Generate a performance curve by sweeping one input variable.

    Individual points that raise PhysicsError are returned as NaN — the sweep
    never raises on partial failures so the chart always receives a full array.
    """
    x_values = np.linspace(axis.min_si, axis.max_si, axis.steps)
    points: list[DataPoint] = []

    for x in x_values:
        inputs = _make_inputs(fixed, axis.variable, float(x))
        try:
            result: CalcResult = calculate(inputs, geom)
            points.append(
                DataPoint(
                    x_si=float(x),
                    power_kw=result.thermal_power / _W_PER_KW,
                    air_temp_out_c=result.air_temp_out - KELVIN_OFFSET,
                    water_temp_out_c=result.water_temp_out - KELVIN_OFFSET,
                    air_rh_out_pct=result.air_rh_out,
                    humidity_ratio_out=result.humidity_ratio_out,
                    is_wet=result.is_wet,
                    re_air=result.re_air,
                    re_water=result.re_water,
                    air_extrapolated=not air_re_in_range(result.re_air),
                    water_extrapolated=not water_re_in_range(result.re_water),
                )
            )
        except (PhysicsError, ValueError, ZeroDivisionError) as exc:
            logger.debug("Sweep point x=%.4g failed: %s", x, exc)
            points.append(
                DataPoint(
                    x_si=float(x),
                    power_kw=math.nan,
                    air_temp_out_c=math.nan,
                    water_temp_out_c=math.nan,
                    air_rh_out_pct=math.nan,
                    humidity_ratio_out=math.nan,
                    error=humanize_error(exc),
                )
            )

    return points
