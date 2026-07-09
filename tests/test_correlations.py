"""Tests for heat transfer correlations."""

import math

from physics.correlations import (
    air_re_in_range,
    colburn_j_factor,
    fin_efficiency,
    gnielinski_nusselt,
    water_re_in_range,
)
from physics.entu import solve_crossflow, solve_ua
from physics.geometry import RegisterGeometry, derive_geometry

# ---------------------------------------------------------------------------
# Gnielinski
# ---------------------------------------------------------------------------


def test_gnielinski_turbulent_reference():
    # Re=10000, Pr=7, L/D=50 — verify against manual formula
    re, pr, l_over_d = 10000.0, 7.0, 50.0
    f = (0.790 * math.log(re) - 1.64) ** -2
    nu_expected = (
        (f / 8.0)
        * (re - 1000.0)
        * pr
        / (1.0 + 12.7 * math.sqrt(f / 8.0) * (pr ** (2.0 / 3.0) - 1.0))
    )
    nu_calc = gnielinski_nusselt(re, pr, l_over_d)
    # Allow entrance correction to shift result slightly
    assert abs(nu_calc - nu_expected) / nu_expected < 0.15


def test_gnielinski_laminar_limit():
    # Re → 0, should return fully-developed laminar Nu ≈ 3.66
    nu = gnielinski_nusselt(0.0, 7.0, 50.0)
    assert abs(nu - 3.66) < 0.1


def test_gnielinski_positive():
    for re in [100, 1000, 5000, 20000]:
        assert gnielinski_nusselt(re, 5.0, 30.0) > 0


# ---------------------------------------------------------------------------
# ε-NTU crossflow
# ---------------------------------------------------------------------------


def test_crossflow_zero_ntu():
    assert solve_crossflow(0.0, 0.5) == 0.0


def test_crossflow_cr_zero():
    # Cr → 0: ε = 1 - exp(-NTU)
    ntu = 2.0
    expected = 1.0 - math.exp(-ntu)
    assert abs(solve_crossflow(ntu, 0.0) - expected) < 1e-6


def test_crossflow_ntu1_cr05():
    # Reference: Incropera Table 11.4, crossflow unmixed/unmixed, exact ε ≈ 0.558.
    # The Kays-London approximation this model uses has a known ~2-3 % offset vs.
    # the exact value, so pin to the model's own output (0.545) tightly rather
    # than to 0.558 with a loose band that would hide a regression.
    eps = solve_crossflow(1.0, 0.5)
    assert abs(eps - 0.545) < 0.005


def test_crossflow_ntu2_cr1():
    # NTU=2, Cr=1.0 → ε ≈ 0.615 (Kays & London both-unmixed; exact ≈ 0.617).
    eps = solve_crossflow(2.0, 1.0)
    assert abs(eps - 0.615) < 0.005


def test_crossflow_bounded():
    for ntu in [0.5, 1.0, 2.0, 5.0]:
        for cr in [0.1, 0.5, 1.0]:
            eps = solve_crossflow(ntu, cr)
            assert 0.0 < eps < 1.0


# ---------------------------------------------------------------------------
# Fin efficiency
# ---------------------------------------------------------------------------


def test_fin_efficiency_bounded():
    geom = RegisterGeometry()
    derived = derive_geometry(geom)
    eta = fin_efficiency(50.0, geom, derived)  # h_air = 50 W/m²K (typical)
    assert 0.0 < eta <= 1.0


def test_fin_efficiency_decreases_with_h():
    geom = RegisterGeometry()
    derived = derive_geometry(geom)
    eta_low = fin_efficiency(20.0, geom, derived)
    eta_high = fin_efficiency(200.0, geom, derived)
    assert eta_low > eta_high


def test_fin_efficiency_zero_h():
    geom = RegisterGeometry()
    derived = derive_geometry(geom)
    assert fin_efficiency(0.0, geom, derived) == 1.0


def test_fin_efficiency_negligible_fin_parameter():
    """When the fin parameter m·r1·φ is negligibly small the tanh(x)/x form
    degenerates numerically, so the correlation short-circuits to η = 1.0. A
    (physically absurd but real) enormous fin conductivity drives m → 0, which
    is the only real input that can make m·r1·φ < 1e-10 — h_air ≤ 0 is caught
    by the earlier guard. This exercises the real arithmetic, not a mock."""
    import dataclasses

    geom = dataclasses.replace(RegisterGeometry(), fin_conductivity=1e25)
    derived = derive_geometry(geom)
    assert fin_efficiency(50.0, geom, derived) == 1.0


# ---------------------------------------------------------------------------
# Reynolds-number range checks
# ---------------------------------------------------------------------------


def test_air_re_in_range():
    assert air_re_in_range(5000.0)
    assert air_re_in_range(300.0)
    assert air_re_in_range(20_000.0)
    assert not air_re_in_range(100.0)
    assert not air_re_in_range(50_000.0)


def test_water_re_in_range():
    assert water_re_in_range(5000.0)
    assert water_re_in_range(3000.0)
    assert not water_re_in_range(1000.0)


# ---------------------------------------------------------------------------
# Colburn j-factor edge case
# ---------------------------------------------------------------------------


def test_colburn_j_factor_zero_re():
    geom = RegisterGeometry()
    assert colburn_j_factor(0.0, geom) == 0.0
    assert colburn_j_factor(-100.0, geom) == 0.0


def test_colburn_j_factor_positive():
    geom = RegisterGeometry()
    assert colburn_j_factor(5000.0, geom) > 0.0


# ---------------------------------------------------------------------------
# Gnielinski entrance correction (short tube, L/D < 60)
# ---------------------------------------------------------------------------


def test_gnielinski_entrance_correction_short_tube():
    # L/D < 60 applies an entrance boost, so a short tube's Nu exceeds a long one's.
    nu_short = gnielinski_nusselt(10000.0, 7.0, 20.0)
    nu_long = gnielinski_nusselt(10000.0, 7.0, 200.0)
    assert nu_short > nu_long


# ---------------------------------------------------------------------------
# solve_ua degenerate (zero-coefficient) short circuits
# ---------------------------------------------------------------------------


def test_solve_ua_zero_air_coeff():
    geom = RegisterGeometry()
    derived = derive_geometry(geom)
    assert solve_ua(0.0, 500.0, 0.9, geom, derived) == 0.0
    assert solve_ua(50.0, 500.0, 0.0, geom, derived) == 0.0


def test_solve_ua_zero_water_coeff():
    geom = RegisterGeometry()
    derived = derive_geometry(geom)
    assert solve_ua(50.0, 0.0, 0.9, geom, derived) == 0.0


def test_solve_ua_positive():
    geom = RegisterGeometry()
    derived = derive_geometry(geom)
    assert solve_ua(50.0, 5000.0, 0.9, geom, derived) > 0.0
