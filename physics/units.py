"""Unit conversion helpers. Conversion happens only at the input/output
boundaries; all internal calculations use plain floats in SI units."""

from __future__ import annotations

UNITS: dict[str, list[str]] = {
    "temperature": ["°C", "K", "°F"],
    "air_flow": ["m³/h", "m³/s", "L/s", "CFM"],
    "water_flow": ["L/min", "L/s", "m³/h", "m³/s"],
    "length": ["mm", "m"],
}

# 0 °C in kelvin — the Celsius↔Kelvin offset.
KELVIN_OFFSET = 273.15

# ---------------------------------------------------------------------------
# Temperature — offset conversion, not a scale factor
# ---------------------------------------------------------------------------


def to_kelvin(value: float, unit: str) -> float:
    if unit == "°C":
        return value + KELVIN_OFFSET
    if unit == "K":
        return value
    if unit == "°F":
        return (value - 32.0) * 5.0 / 9.0 + KELVIN_OFFSET
    raise ValueError(f"Unknown temperature unit: {unit!r}")


def from_kelvin(value: float, unit: str) -> float:
    if unit == "°C":
        return value - KELVIN_OFFSET
    if unit == "K":
        return value
    if unit == "°F":
        return (value - KELVIN_OFFSET) * 9.0 / 5.0 + 32.0
    raise ValueError(f"Unknown temperature unit: {unit!r}")


# ---------------------------------------------------------------------------
# Volume flow — scale factors to m³/s
# ---------------------------------------------------------------------------

_FLOW_TO_M3S: dict[str, float] = {
    "m³/s": 1.0,
    "m³/h": 1.0 / 3600.0,
    "L/s": 1.0 / 1000.0,
    "L/min": 1.0 / 60_000.0,
    "CFM": 4.719_474_432e-4,
}


def to_m3s(value: float, unit: str) -> float:
    try:
        return value * _FLOW_TO_M3S[unit]
    except KeyError:
        raise ValueError(f"Unknown flow unit: {unit!r}") from None


def from_m3s(value: float, unit: str) -> float:
    try:
        return value / _FLOW_TO_M3S[unit]
    except KeyError:
        raise ValueError(f"Unknown flow unit: {unit!r}") from None


# ---------------------------------------------------------------------------
# Length — scale factors to metres
# ---------------------------------------------------------------------------

_LENGTH_TO_M: dict[str, float] = {
    "m": 1.0,
    "mm": 1.0 / 1000.0,
}


def to_meter(value: float, unit: str) -> float:
    try:
        return value * _LENGTH_TO_M[unit]
    except KeyError:
        raise ValueError(f"Unknown length unit: {unit!r}") from None


def from_meter(value: float, unit: str) -> float:
    try:
        return value / _LENGTH_TO_M[unit]
    except KeyError:
        raise ValueError(f"Unknown length unit: {unit!r}") from None
