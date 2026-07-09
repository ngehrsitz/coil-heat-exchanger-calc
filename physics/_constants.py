"""Shared physical constants for the physics layer (SI units)."""

from __future__ import annotations

# Standard atmospheric pressure [Pa]. Fluid properties are all evaluated at this
# fixed pressure; the moist-air and water CoolProp wrappers share this value.
P_ATM = 101_325.0  # Pa
