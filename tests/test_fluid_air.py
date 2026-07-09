"""Tests for moist air thermophysical properties.
Reference values from NIST / ideal gas law / ASHRAE Fundamentals.
"""

from physics.fluid_air import (
    RH_from_W,
    T_from_H_W,
    W_from_RH,
    W_sat_at_T,
    air_density,
    air_dynamic_viscosity,
    air_enthalpy,
    air_prandtl,
    air_props,
    air_specific_heat,
    air_thermal_conductivity,
    dew_point,
    sat_enthalpy_at_T,
)


def test_density_20c_dry():
    # Ideal gas: rho = P/(R_air * T) = 101325 / (287.058 * 293.15) ≈ 1.204 kg/m³
    expected = 101325.0 / (287.058 * 293.15)
    assert abs(air_density(293.15, 0.0) - expected) < 0.005


def test_density_increases_with_humidity():
    # Moist air is lighter than dry air at same T, P
    rho_dry = air_density(293.15, 0.0)
    rho_moist = air_density(293.15, 0.01)  # 10 g/kg
    assert rho_moist < rho_dry


def test_specific_heat_dry_air():
    # Dry air cp ≈ 1006 J/kg·K at 20°C
    assert abs(air_specific_heat(293.15, 0.0) - 1006.0) < 20.0


def test_prandtl_300k():
    # Pr for dry air at 300 K ≈ 0.707
    assert abs(air_prandtl(300.0, 0.0) - 0.707) < 0.02


def test_dynamic_viscosity_20c():
    # ~1.81e-5 Pa·s at 20°C
    assert abs(air_dynamic_viscosity(293.15, 0.0) - 1.81e-5) < 0.1e-5


def test_thermal_conductivity_20c():
    # ~0.0257 W/m·K at 20°C
    assert abs(air_thermal_conductivity(293.15, 0.0) - 0.0257) < 0.002


def test_props_returns_five_positive_values():
    result = air_props(300.0, 0.0)
    assert len(result) == 5
    assert all(v > 0 for v in result)


# ---------------------------------------------------------------------------
# Psychrometric helpers for the wet-coil model
# ---------------------------------------------------------------------------


def test_W_from_RH_roundtrip():
    W = W_from_RH(293.15, 0.5)
    assert abs(RH_from_W(293.15, W) - 0.5) < 1e-3


def test_W_from_RH_zero_and_saturation():
    assert W_from_RH(293.15, 0.0) < 1e-6
    assert abs(W_from_RH(293.15, 1.0) - W_sat_at_T(293.15)) < 1e-6


def test_dew_point_below_drybulb():
    Td = dew_point(293.15, 0.007)
    assert 273.0 < Td < 293.15


def test_sat_enthalpy_monotonic():
    assert sat_enthalpy_at_T(283.15) < sat_enthalpy_at_T(293.15) < sat_enthalpy_at_T(303.15)


def test_air_enthalpy_increases_with_humidity():
    # At fixed T, more moisture carries more latent enthalpy.
    assert air_enthalpy(295.15, 0.012) > air_enthalpy(295.15, 0.004)


def test_T_from_H_W_inverts_air_enthalpy():
    T, W = 295.0, 0.008
    assert abs(T_from_H_W(air_enthalpy(T, W), W) - T) < 0.05


# ---------------------------------------------------------------------------
# Reference A — Purdue ME 418 cooling-coil psychrometric example
#   Air 85 °F / 50 % RH  →  55 °F / 90 % RH, condensate drains at 45 °F.
#   Pure mass/energy balance (independent of the ε-NTU correlation), so the
#   psychrometric layer is validated to ~2 %. Expected values cross-checked
#   with CoolProp; condensate ≈ 39.8 lb/hr matches the published answer.
#   https://www.purdue.edu/freeform/me418/wp-content/uploads/sites/30/2025/09/Cooling-Coil-Example.pdf
# ---------------------------------------------------------------------------


def _F(f):
    return (f - 32.0) * 5.0 / 9.0 + 273.15


def test_purdue_reference_humidity_ratios():
    W_in = W_from_RH(_F(85.0), 0.50)
    W_out = W_from_RH(_F(55.0), 0.90)
    assert abs(W_in * 1000.0 - 12.94) < 0.3  # g/kg
    assert abs(W_out * 1000.0 - 8.30) < 0.3


def test_purdue_reference_enthalpies():
    h_in = air_enthalpy(_F(85.0), W_from_RH(_F(85.0), 0.50))
    h_out = air_enthalpy(_F(55.0), W_from_RH(_F(55.0), 0.90))
    assert abs(h_in / 1000.0 - 62.69) < 1.5  # kJ/kg dry air
    assert abs(h_out / 1000.0 - 33.79) < 1.5


def test_purdue_reference_condensate_and_shr():
    """2000 cfm inlet → condensate ≈ 39.8 lb/hr and SHR ≈ 0.60."""
    import CoolProp.CoolProp as CP

    P = 101_325.0
    T_in, T_out = _F(85.0), _F(55.0)
    W_in = W_from_RH(T_in, 0.50)
    W_out = W_from_RH(T_out, 0.90)

    # Dry-air mass flow from 2000 cfm at inlet-air density (as the app does).
    q_vol = 2000.0 * 4.719_474_432e-4  # m³/s
    v_ha = CP.HAPropsSI("Vha", "T", T_in, "P", P, "W", W_in)
    m_dot_da = (q_vol / v_ha) / (1.0 + W_in)  # kg dry air / s

    condensate_lb_hr = m_dot_da * (W_in - W_out) * 2.204_62 * 3600.0
    assert abs(condensate_lb_hr - 39.8) < 2.0

    # Sensible / total → sensible heat ratio.
    cp_a = 1006.0 + 1860.0 * W_in
    q_sens = m_dot_da * cp_a * (T_in - T_out)
    h_in = air_enthalpy(T_in, W_in)
    h_out = air_enthalpy(T_out, W_out)
    hf = CP.PropsSI("H", "T", _F(45.0), "Q", 0, "Water")  # condensate leaves at 45 °F
    q_total = m_dot_da * (h_in - h_out) - m_dot_da * (W_in - W_out) * hf
    assert abs(q_sens / q_total - 0.60) < 0.03
