"""Axis-variable domain model: labels, SI units, and input bounds.

This sits *above* pure unit conversion (``physics.units``) and the fluid-property
envelopes (``physics.fluid_air`` / ``physics.fluid_water``): it maps the four
sweepable axis variables to their display metadata and validates user input
against physical limits. It legitimately depends on both layers, which is why it
is a separate module rather than living inside ``units`` (pure conversion) or the
fluid wrappers (property lookups).

Two kinds of limit, deliberately handled differently in the UI:
  * Hard limits (``display_bounds``) — values that make no physical sense at all
    (non-positive flow, temperature at/below absolute zero). Entry widgets clamp
    to these so they can never be typed.
  * The fluid-property envelope (``temp_range`` / ``temp_in_range``) —
    temperatures CoolProp cannot evaluate. These ARE typeable, and the UI flags
    them with a red outline + message rather than silently clamping.
"""

from __future__ import annotations

from .units import UNITS, from_kelvin, from_m3s, to_kelvin, to_m3s

# ---------------------------------------------------------------------------
# Axis variable label and SI unit string for chart display
# ---------------------------------------------------------------------------

AXIS_SI_UNIT: dict[str, str] = {
    "air_flow": "m³/s",
    "air_temp_in": "K",
    "water_temp_in": "K",
    "water_flow": "m³/s",
}

AXIS_LABEL: dict[str, str] = {
    "air_flow": "Air Volume Flow",
    "air_temp_in": "Air Inlet Temperature",
    "water_temp_in": "Water Inlet Temperature",
    "water_flow": "Water Volume Flow",
}

AXIS_DISPLAY_UNITS: dict[str, list[str]] = {
    "air_flow": UNITS["air_flow"],
    "air_temp_in": UNITS["temperature"],
    "water_temp_in": UNITS["temperature"],
    "water_flow": UNITS["water_flow"],
}

_TEMPERATURE_VARS = ("air_temp_in", "water_temp_in")
_FLOW_VARS = ("air_flow", "water_flow")


def to_si(variable: str, value: float, unit: str) -> float:
    """Convert a user-facing value to SI for the given axis variable."""
    if variable in _TEMPERATURE_VARS:
        return to_kelvin(value, unit)
    if variable in _FLOW_VARS:
        return to_m3s(value, unit)
    raise ValueError(f"Unknown axis variable: {variable!r}")


def from_si(variable: str, value: float, unit: str) -> float:
    """Convert an SI value back to a user-facing unit for display."""
    if variable in _TEMPERATURE_VARS:
        return from_kelvin(value, unit)
    if variable in _FLOW_VARS:
        return from_m3s(value, unit)
    raise ValueError(f"Unknown axis variable: {variable!r}")


# ---------------------------------------------------------------------------
# Physical input bounds
# ---------------------------------------------------------------------------

# The flow floor must be representable at the entry widget's precision (3
# decimals); a smaller value would round back to zero when clamped.
_FLOW_FLOOR_DISPLAY = 0.001

# Smallest temperature an entry widget accepts (SI kelvin) — just above absolute
# zero. The narrower fluid-property envelope is enforced by validation, not by
# clamping, so out-of-envelope values can be entered and then flagged.
_TEMP_FLOOR_K = 0.001


# Temperature envelope per fluid (SI kelvin), from the CoolProp-backed modules.
# Imported lazily so importing this module does not pull in the CoolProp
# extension unless the envelope is actually queried.
def _temp_range_k(variable: str) -> tuple[float, float]:
    from .fluid_air import AIR_T_MAX, AIR_T_MIN
    from .fluid_water import WATER_T_MAX, WATER_T_MIN

    if variable == "air_temp_in":
        return AIR_T_MIN, AIR_T_MAX
    return WATER_T_MIN, WATER_T_MAX


def kind_of(variable: str) -> str:
    """Return the physical kind of an axis variable: 'temperature' or 'flow'."""
    if variable in _TEMPERATURE_VARS:
        return "temperature"
    if variable in _FLOW_VARS:
        return "flow"
    raise ValueError(f"Unknown axis variable: {variable!r}")


def display_bounds(variable: str, unit: str) -> tuple[float, float | None]:
    """Hard (min, max) an entry widget should allow, in the given display unit.

    Temperatures are floored just above absolute zero (the fluid-property
    envelope is enforced separately by ``temp_in_range`` so it can be flagged
    rather than clamped); flows have a small positive floor. ``max`` is ``None``
    when unbounded.
    """
    if kind_of(variable) == "temperature":
        return from_kelvin(_TEMP_FLOOR_K, unit), None
    return _FLOW_FLOOR_DISPLAY, None


def temp_range(variable: str, unit: str) -> tuple[float, float]:
    """Supported fluid-property temperature envelope, in the given display unit."""
    lo_k, hi_k = _temp_range_k(variable)
    return from_kelvin(lo_k, unit), from_kelvin(hi_k, unit)


def temp_in_range(variable: str, value_si: float) -> bool:
    """True if an SI temperature is within ``variable``'s property envelope."""
    lo_k, hi_k = _temp_range_k(variable)
    return lo_k <= value_si <= hi_k
