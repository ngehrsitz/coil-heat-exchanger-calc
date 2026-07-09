"""Shared exception types for the physics layer.

Kept dependency-free so both the fluid-property wrappers (which raise these) and
``errors.py`` (which humanizes them) can import them without a circular import.
"""

from __future__ import annotations


class PropertyRangeError(ValueError):
    """A fluid property was requested outside its supported temperature range.

    Raised by the fluid wrappers (guarding CoolProp) so callers can detect the
    condition by type rather than by matching CoolProp's error wording.
    """


def _is_range_error(exc: BaseException) -> bool:
    """True if ``exc`` looks like a CoolProp out-of-range / unsupported-state error.

    CoolProp signals an out-of-range temperature with several distinct wordings,
    e.g. "... is outside the range of validity ..." (the moist-air backend, which
    also mentions a numeric "key") and "we don't support T [..] below Tmelt(p) ..."
    (liquid water below its melting point). This text match is confined here (and
    applied only at the raise site in the fluid wrappers, where we already hold a
    CoolProp exception) so the rest of the codebase can rely on the typed
    :class:`PropertyRangeError` instead of sniffing strings.
    """
    lowered = str(exc).lower()
    return (
        ("outside the range" in lowered and "key" in lowered)
        or "range of validity" in lowered
        or "below tmelt" in lowered
        or "above tmax" in lowered
    )
