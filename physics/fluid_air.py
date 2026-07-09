"""Moist air thermophysical properties via CoolProp HumidAir backend.

All inputs and outputs in SI base units.
W = humidity ratio [kg_water / kg_dry_air]; use 0.0 for dry air.
Valid range: 250 K – 350 K at atmospheric pressure.
"""

from __future__ import annotations

from typing import NamedTuple

import CoolProp.CoolProp as CP

from ._constants import P_ATM as _P_ATM
from ._exceptions import PropertyRangeError, _is_range_error

# Supported moist-air temperature envelope [K]. CoolProp's HumidAir backend
# raises a cryptic range error outside this; callers use air_temp_in_range() to
# reject such inputs up front with a clear message.
AIR_T_MIN = 250.0
AIR_T_MAX = 350.0


def air_temp_in_range(T: float) -> bool:
    """True if air temperature T [K] is within the supported property range."""
    return AIR_T_MIN <= T <= AIR_T_MAX


class AirProps(NamedTuple):
    """Moist-air properties at a state, in SI base units."""

    rho: float  # kg/m³   density of the humid-air mixture
    cp: float  # J/kg·K   specific heat (per kg humid air)
    mu: float  # Pa·s     dynamic viscosity
    k: float  # W/m·K    thermal conductivity
    Pr: float  # —        Prandtl number


def air_density(T: float, W: float = 0.0) -> float:
    """kg/m³ of moist air mixture."""
    # HAPropsSI 'Vha' returns specific volume [m³/kg_humid_air]; invert for density
    v_ha = CP.HAPropsSI("Vha", "T", T, "P", _P_ATM, "W", W)
    return 1.0 / v_ha


def air_specific_heat(T: float, W: float = 0.0) -> float:
    """J/kg·K  (per kg of humid air)."""
    return CP.HAPropsSI("cp_ha", "T", T, "P", _P_ATM, "W", W)


def air_dynamic_viscosity(T: float, W: float = 0.0) -> float:
    """Dynamic viscosity of moist air [Pa·s]."""
    return CP.HAPropsSI("mu", "T", T, "P", _P_ATM, "W", W)


def air_thermal_conductivity(T: float, W: float = 0.0) -> float:
    """Thermal conductivity of moist air [W/m·K]."""
    return CP.HAPropsSI("k", "T", T, "P", _P_ATM, "W", W)


def _prandtl(cp: float, mu: float, k: float) -> float:
    """Prandtl number from cp, dynamic viscosity, and thermal conductivity."""
    return cp * mu / k


def air_prandtl(T: float, W: float = 0.0) -> float:
    """Prandtl number [—] of moist air:  Pr = cp × mu / k."""
    cp = air_specific_heat(T, W)
    mu = air_dynamic_viscosity(T, W)
    k = air_thermal_conductivity(T, W)
    return _prandtl(cp, mu, k)


def air_props(T: float, W: float = 0.0) -> AirProps:
    """Return :class:`AirProps` for moist air at T [K], humidity ratio W.

    If CoolProp rejects the state as out of range, re-raise as
    :class:`PropertyRangeError` so callers get a typed signal instead of
    CoolProp's cryptic wording. The supported envelope (``AIR_T_MIN``/``MAX``) is
    a conservative advisory band, not CoolProp's hard limit, so the translation
    keys off CoolProp actually failing rather than off the envelope.
    """
    try:
        rho = air_density(T, W)
        cp = air_specific_heat(T, W)
        mu = air_dynamic_viscosity(T, W)
        k = air_thermal_conductivity(T, W)
        # Reuse the shared Pr formula without re-querying cp/mu/k from CoolProp.
        Pr = _prandtl(cp, mu, k)
        return AirProps(rho, cp, mu, k, Pr)
    except ValueError as exc:
        if _is_range_error(exc):
            raise PropertyRangeError(
                f"Air temperature {T:.1f} K outside the valid property range."
            ) from exc
        raise  # pragma: no cover - defensive: any ValueError CoolProp raises for
        # an out-of-domain state is a range error (matched above); a non-range
        # ValueError is not reachable with the (T, W) inputs this wrapper accepts.


# ---------------------------------------------------------------------------
# Psychrometric helpers for the wet-coil (condensation) model
#
# Enthalpy is expressed PER KG DRY AIR (HAPropsSI 'H'), because condensation
# removes water while dry-air mass is conserved through the coil. Pairing 'H'
# with the dry-air mass flow keeps the enthalpy energy balance closed.
# ---------------------------------------------------------------------------


def air_enthalpy(T: float, W: float = 0.0) -> float:
    """Moist-air enthalpy [J / kg dry air] at T [K], humidity ratio W."""
    return CP.HAPropsSI("H", "T", T, "P", _P_ATM, "W", W)


def W_from_RH(T: float, rh_fraction: float) -> float:
    """Humidity ratio [kg_w/kg_da] from T [K] and RH as a FRACTION 0..1.

    HAPropsSI 'R' expects a fraction (0.5 = 50 %), not a percentage.
    """
    rh = min(max(rh_fraction, 0.0), 1.0)
    return CP.HAPropsSI("W", "T", T, "P", _P_ATM, "R", rh)


def RH_from_W(T: float, W: float) -> float:
    """Relative humidity as a FRACTION 0..1 from T [K] and humidity ratio W.

    Clamped to [0, 1]. If W exceeds saturation at T, CoolProp raises a
    range error rather than returning RH > 1, so a supersaturated state is
    reported as fully saturated (RH = 1).
    """
    if W >= W_sat_at_T(T):
        return 1.0
    rh = CP.HAPropsSI("R", "T", T, "P", _P_ATM, "W", W)
    return min(max(rh, 0.0), 1.0)


def dew_point(T: float, W: float) -> float:
    """Dew-point temperature [K] of moist air at T [K], humidity ratio W."""
    return CP.HAPropsSI("D", "T", T, "P", _P_ATM, "W", W)


def sat_enthalpy_at_T(T: float) -> float:
    """Enthalpy of SATURATED moist air (RH = 1) at T [K], J / kg dry air.

    This is the saturated-air enthalpy used as the driving-potential
    reference in the enthalpy-potential (Threlkeld) wet-coil method.
    """
    return CP.HAPropsSI("H", "T", T, "P", _P_ATM, "R", 1.0)


def W_sat_at_T(T: float) -> float:
    """Saturation humidity ratio [kg_w/kg_da] at T [K] (RH = 1)."""
    return CP.HAPropsSI("W", "T", T, "P", _P_ATM, "R", 1.0)


def T_from_H_W(H: float, W: float) -> float:
    """Dry-bulb temperature [K] from enthalpy H [J/kg_da] and humidity ratio W.

    Inverts air_enthalpy() to recover the outlet air temperature once the
    outlet enthalpy and humidity ratio are known.
    """
    return CP.HAPropsSI("T", "H", H, "P", _P_ATM, "W", W)
