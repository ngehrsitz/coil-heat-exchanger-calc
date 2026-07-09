"""Water thermophysical properties via CoolProp.

All inputs and outputs in SI base units.
Valid range: 280 K – 370 K at atmospheric pressure.
"""

from __future__ import annotations

from typing import NamedTuple

import CoolProp.CoolProp as CP

from ._constants import P_ATM as _P_ATM
from ._exceptions import PropertyRangeError, _is_range_error

_FLUID = "Water"

# Supported liquid-water temperature envelope [K] at atmospheric pressure.
# Outside this CoolProp raises a cryptic range error; callers use
# water_temp_in_range() to reject such inputs up front with a clear message.
WATER_T_MIN = 280.0
WATER_T_MAX = 370.0


def water_temp_in_range(T: float) -> bool:
    """True if water temperature T [K] is within the supported property range."""
    return WATER_T_MIN <= T <= WATER_T_MAX


class WaterProps(NamedTuple):
    """Liquid-water properties at a temperature, in SI base units."""

    rho: float  # kg/m³   density
    cp: float  # J/kg·K   specific heat
    mu: float  # Pa·s     dynamic viscosity
    k: float  # W/m·K    thermal conductivity
    Pr: float  # —        Prandtl number


def water_density(T: float) -> float:
    """Density of liquid water [kg/m³]."""
    return CP.PropsSI("D", "T", T, "P", _P_ATM, _FLUID)


def water_specific_heat(T: float) -> float:
    """Specific heat of liquid water [J/kg·K]."""
    return CP.PropsSI("C", "T", T, "P", _P_ATM, _FLUID)


def water_dynamic_viscosity(T: float) -> float:
    """Dynamic viscosity of liquid water [Pa·s]."""
    return CP.PropsSI("V", "T", T, "P", _P_ATM, _FLUID)


def water_thermal_conductivity(T: float) -> float:
    """Thermal conductivity of liquid water [W/m·K]."""
    return CP.PropsSI("L", "T", T, "P", _P_ATM, _FLUID)


def water_prandtl(T: float) -> float:
    """Prandtl number [—] of liquid water."""
    return CP.PropsSI("Prandtl", "T", T, "P", _P_ATM, _FLUID)


def water_props(T: float) -> WaterProps:
    """Return :class:`WaterProps` for water at temperature T [K].

    If CoolProp rejects T as out of range, re-raise as :class:`PropertyRangeError`
    so callers get a typed signal instead of CoolProp's cryptic wording. Note the
    supported envelope (``WATER_T_MIN``/``MAX``) is a conservative advisory band,
    not CoolProp's hard limit — properties just outside it may still evaluate, so
    the translation keys off CoolProp actually failing, not off the envelope.
    """
    try:
        return WaterProps(
            water_density(T),
            water_specific_heat(T),
            water_dynamic_viscosity(T),
            water_thermal_conductivity(T),
            water_prandtl(T),
        )
    except ValueError as exc:
        if _is_range_error(exc):
            raise PropertyRangeError(
                f"Water temperature {T:.1f} K outside the valid property range."
            ) from exc
        raise  # pragma: no cover - defensive: any ValueError CoolProp raises for
        # an out-of-domain temperature is a range error (matched above); a
        # non-range ValueError is not reachable with the T inputs this accepts.
