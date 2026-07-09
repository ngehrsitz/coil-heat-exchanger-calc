"""Tests for water thermophysical properties.
Reference values from NIST Webbook / Engineering Toolbox at 1 atm.
"""

from physics.fluid_water import (
    water_density,
    water_dynamic_viscosity,
    water_prandtl,
    water_props,
    water_specific_heat,
    water_thermal_conductivity,
)


def test_density_20c():
    assert abs(water_density(293.15) - 998.2) < 1.0  # kg/m³, ±1%


def test_density_60c():
    assert abs(water_density(333.15) - 983.2) < 2.0


def test_specific_heat_20c():
    assert abs(water_specific_heat(293.15) - 4182.0) < 20.0  # J/kg·K


def test_dynamic_viscosity_20c():
    # ~1.002e-3 Pa·s at 20°C
    assert abs(water_dynamic_viscosity(293.15) - 1.002e-3) < 0.05e-3


def test_thermal_conductivity_20c():
    # ~0.598 W/m·K at 20°C
    assert abs(water_thermal_conductivity(293.15) - 0.598) < 0.01


def test_prandtl_20c():
    assert abs(water_prandtl(293.15) - 7.01) < 0.3


def test_prandtl_60c():
    assert abs(water_prandtl(333.15) - 3.15) < 0.2


def test_props_returns_five_values():
    result = water_props(300.0)
    assert len(result) == 5
    rho, cp, mu, k, Pr = result
    assert all(v > 0 for v in (rho, cp, mu, k, Pr))
