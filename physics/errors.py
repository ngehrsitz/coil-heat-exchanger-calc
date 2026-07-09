"""Translate low-level property-library exceptions into user-facing messages.

CoolProp raises range errors whose text exposes internal parameter indices,
e.g. "The input for key (12) with value (13) is outside the range of
validity: ...". That is meaningless to a user. The fluid wrappers guard their
inputs and raise :class:`PropertyRangeError` before calling CoolProp, so
``humanize_error`` can recognise the condition by type; the legacy text match
remains as a fallback for any range error raised from deeper in CoolProp.
"""

from __future__ import annotations

from ._exceptions import PropertyRangeError, _is_range_error
from .fluid_air import AIR_T_MAX, AIR_T_MIN
from .fluid_water import WATER_T_MAX, WATER_T_MIN

__all__ = ["PropertyRangeError", "humanize_error"]


def _range_message() -> str:
    return (
        "Inlet temperature is outside the supported property range "
        f"(air {AIR_T_MIN:.0f}–{AIR_T_MAX:.0f} K, "
        f"water {WATER_T_MIN:.0f}–{WATER_T_MAX:.0f} K). "
        "Adjust the air or water inlet temperature."
    )


def humanize_error(exc: BaseException) -> str:
    """Return a clear message for ``exc``, rewriting cryptic CoolProp errors.

    Non-CoolProp errors (and already-clear PhysicsError messages) are returned
    unchanged.
    """
    if isinstance(exc, PropertyRangeError):
        return _range_message()
    # Legacy fallback for a raw CoolProp range error that bypassed the wrappers'
    # translation (recognised by the same text heuristic used at the raise site).
    if _is_range_error(exc):
        return _range_message()
    return str(exc)
