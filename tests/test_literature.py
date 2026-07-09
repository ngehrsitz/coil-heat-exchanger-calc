"""Literature-validation tests — recompute published Incropera examples.

The simulator can model arbitrary register geometries (``RegisterGeometry`` has
every field defaulted). This module turns that into a validation strategy: take a
published worked example's *own* conditions, run them through the app's physics,
and assert the app reproduces the published answer within a cited tolerance.

Each result is checked at the layer the app actually computes it: the ε-NTU
relation (``entu.solve_crossflow``), the UA resistance network (``entu.solve_ua``),
or the water-side Nusselt correlation (``correlations.gnielinski_nusselt``).
End-to-end ``calculate()`` is not asserted tightly because the app derives
``h_air`` from its own Colburn fit rather than a textbook's tabulated j-factor.

Reference work (in the repo: Solutions-Incropera-7th-[www.konkur.in].pdf):
  Incropera, DeWitt, Bergman & Lavine, Fundamentals of Heat and Mass Transfer,
  7th ed. — Problem 8.67 (Gnielinski internal flow), Problem 11.25 (crossflow
  heat exchanger, both fluids unmixed, Eq. 11.32), Table 11.4 / Fig. 11.14.

The app's crossflow relation (entu.solve_crossflow) IS Incropera Eq. 11.32
verbatim, and its water-side Nusselt IS the Gnielinski correlation Eq. 8.21, so
these are direct like-for-like checks against the solutions manual, not analogues.

Two exact crossflow points (NTU=1,Cr=0.5 and NTU=2,Cr=1) already live with the
other ``solve_crossflow`` unit tests in tests/test_correlations.py; this module
does not duplicate them.
"""

import math

from physics.correlations import colburn_j_factor, fin_efficiency, gnielinski_nusselt
from physics.entu import solve_crossflow, solve_ua
from physics.fluid_water import water_props
from physics.geometry import DerivedGeometry, RegisterGeometry, derive_geometry

# ---------------------------------------------------------------------------
# Layer A — crossflow ε-NTU, both fluids unmixed. Incropera Eq. 11.32, which is
# exactly entu.solve_crossflow. The Cr → 0 case reduces to the exact analytic
# limit ε = 1 − e^(−NTU) (Incropera Eq. 11.35a).
# ---------------------------------------------------------------------------


def test_crossflow_cr_zero_analytic_limit():
    """Cr → 0 (one fluid condensing/evaporating, infinite capacity rate): the
    effectiveness is exactly ε = 1 − e^(−NTU) (Incropera Eq. 11.35a). No
    approximation involved, so this is pinned tight."""
    for ntu in (0.5, 1.0, 2.0, 3.0):
        expected = 1.0 - math.exp(-ntu)
        assert abs(solve_crossflow(ntu, 0.0) - expected) < 1e-6


# ---------------------------------------------------------------------------
# Incropera 7th ed., Problem 11.25 — automobile radiator as a single-pass
# cross-flow heat exchanger, BOTH FLUIDS UNMIXED (the app's exact configuration).
# Hot fluid water m=0.05 kg/s, cp=4209 J/kg·K → C_h = 210.45 W/K (= C_min);
# cold fluid air m=0.75 kg/s, cp=1007 J/kg·K → C_c = 755.25 W/K (= C_max).
# T_h,i = 400 K, T_c,i = 300 K. Published solution (via IHT, Eq. 11.32):
#   Cr = C_min/C_max = 0.279, ε = q/q_max = 0.700, NTU = 1.441, T_c,o = 319.5 K.
# The solutions manual lists the model equation as
#   eps = 1 - exp((1/Cr)*(NTU^0.22)*(exp(-Cr*NTU^0.78) - 1))   // Eq 11.32
# which is byte-for-byte entu.solve_crossflow — so this is a direct check, tight.
# ---------------------------------------------------------------------------


def test_incropera_11_25_crossflow_radiator():
    c_hot = 0.05 * 4209.0  # water, W/K  → C_min
    c_cold = 0.75 * 1007.0  # air,   W/K  → C_max
    c_min, c_max = min(c_hot, c_cold), max(c_hot, c_cold)
    cr = c_min / c_max
    assert abs(cr - 0.279) < 0.005  # published Cr

    # Published NTU (IHT precise value) reproduces the published effectiveness.
    ntu = 1.441
    eps = solve_crossflow(ntu, cr)
    assert abs(eps - 0.700) < 0.005  # published ε = 0.700

    # Close the loop: from ε recover the air (cold, C_max) outlet temperature.
    t_hot_in, t_cold_in = 400.0, 300.0
    q = eps * c_min * (t_hot_in - t_cold_in)
    t_cold_out = t_cold_in + q / c_cold
    assert abs(t_cold_out - 319.5) < 0.5  # published T_c,o = 319.5 K


# ---------------------------------------------------------------------------
# Incropera 7th ed., Problem 8.67 — turbulent internal flow of pure water in a
# circular tube. D = 2 mm, m = 10 g/s, water at 300 K (Pr = 5.83).
# Published: Re_D = 7450 (turbulent), L/D = 50, "fully-developed at the tube
# exit". Gnielinski correlation (Eq. 8.21) → f = 0.0342, Nu_D = 56.24.
# The app's gnielinski_nusselt IS Eq. 8.21; it additionally applies an entrance
# correction for L/D < 60, so we compare against the fully-developed value at
# L/D ≥ 60 (Incropera used the fully-developed Nu here) and separately document
# the app's <60 entrance boost.
# ---------------------------------------------------------------------------


def test_incropera_8_67_gnielinski_water():
    re, pr = 7450.0, 5.83

    # Fully-developed regime (L/D ≥ 60): bare Gnielinski, must match Nu = 56.24.
    nu_fd = gnielinski_nusselt(re, pr, 60.0)
    assert abs(nu_fd - 56.24) / 56.24 < 0.02  # 0.05% in practice; ±2% band

    # No entrance boost once fully developed: L/D = 60 and L/D = 1000 agree.
    assert gnielinski_nusselt(re, pr, 60.0) == gnielinski_nusselt(re, pr, 1000.0)

    # At Incropera's stated L/D = 50 the app deliberately adds an entrance boost,
    # so its Nu sits a few % above the fully-developed reference (by design).
    nu_entrance = gnielinski_nusselt(re, pr, 50.0)
    assert nu_entrance > nu_fd
    assert abs(nu_entrance - nu_fd) / nu_fd < 0.10


# ---------------------------------------------------------------------------
# Layer B — compact finned circular-tube coil, air over fins / water in tubes
# (the app's construction). The app cannot ingest a tabulated j-factor, so rather
# than expect calculate() to reproduce a published h_air, we inject side
# coefficients into solve_ua (as test_calculator.py's Mitchell-Braun test injects
# UA) on a REAL coil geometry and check the resulting UA is physically bracketed
# by the two single-side conductances. This validates the resistance-network math
# and the derived-geometry areas, independent of the air-side correlation.
#
# Geometry: the app default register — the real 6×10×300 mm coil of vendor drawing
# HX20260709 (Ø9.52 mm Cu tube, 2.5 mm fin pitch, 22 mm row / 25.4 mm hole pitch).
# ---------------------------------------------------------------------------


def test_finned_coil_ua_between_resistance_limits():
    geom = RegisterGeometry()
    derived = derive_geometry(geom)

    h_air = 60.0  # W/m²·K — air-side coefficient (controlling resistance)
    h_water = 6000.0  # W/m²·K — water-side coefficient
    eta_surface = 0.85

    ua = solve_ua(h_air, h_water, eta_surface, geom, derived)

    ua_air_side = eta_surface * h_air * derived.total_ext_area
    ua_water_side = h_water * derived.tube_int_area
    # Series resistances: overall UA below both single-side conductances.
    assert 0.0 < ua < min(ua_air_side, ua_water_side)
    # Air side controls, so UA is within a factor of the air-side conductance.
    assert 0.5 * ua_air_side < ua < ua_air_side


def test_finned_coil_epsilon_from_injected_ua():
    """Once UA and the capacity rates are fixed, ε follows from the crossflow
    relation. Uses real water properties for the capacity rate so the whole
    ε-NTU chain is exercised on a real coil geometry, and checks the result is a
    bounded, physically valid effectiveness."""
    geom = RegisterGeometry()
    derived = derive_geometry(geom)

    ua = solve_ua(60.0, 6000.0, 0.85, geom, derived)

    rho_w, cp_w, *_ = water_props(333.15)  # 60 °C water
    c_water = 0.05 * rho_w * cp_w  # 0.05 m³/s equivalent
    c_air = 1500.0  # W/K, representative air-side capacity rate

    c_min = min(c_air, c_water)
    cr = c_min / max(c_air, c_water)
    ntu = ua / c_min
    eps = solve_crossflow(ntu, cr)

    assert 0.0 < eps < 1.0


# ---------------------------------------------------------------------------
# Air-side cross-check — Wang, Chi & Chang (2000), "Heat transfer and friction
# characteristics of plain fin-and-tube heat exchangers, part II: Correlation,"
# Int. J. Heat Mass Transfer 43(15):2693-2700 (repo: s0017-9310_2899_2900333-6.pdf).
#
# This is an INDEPENDENT plain-fin j-factor correlation from a 74-sample database
# (different lineage from the app's McQuiston/Rich fit), used to sanity-check the
# app's colburn_j_factor. The app's coil is inside Wang's stated applicability
# range (plain fin; N 1-6; Do 6.35-12.7 mm; Fp 1.19-8.7 mm; Pt 17.7-31.75 mm;
# Pl 12.4-27.5 mm) — the default 6-row / 9.52 mm / 2.5 mm / 25.4 / 22 mm coil fits
# every bound.
#
# Wang's correlation (Eqs. 6-10), Re based on the fin-COLLAR diameter Dc = Do+2·df:
#   j = 0.086·Re_Dc^P3·N^P4·(Fp/Dc)^P5·(Fp/Dh)^P6·(Fp/Pt)^-0.93
#   P3 = -0.361 - 0.042·N/ln(Re_Dc) + 0.158·ln(N·(Fp/Dc)^0.41)
#   P4 = -1.224 - 0.076·(Pl/Dh)^1.42/ln(Re_Dc)
#   P5 = -0.083 + 0.058·N/ln(Re_Dc)
#   P6 = -5.735 + 1.21·ln(Re_Dc/N)
#
# The app's Re is on the air-side hydraulic diameter dh_ext, not Dc, so a fair
# comparison fixes one physical operating point (a mass flux G_c) and maps
# Re_Dc = Re_Dh·(Dc/dh_ext) — at fixed G_c/μ, Reynolds scales linearly with the
# characteristic length. Both are the same dimensionless Colburn factor
# j = Nu/(Re·Pr^1/3), so the j values are directly comparable.
#
# Tolerance ±25%: Wang's own correlation reproduces only 88.6% of its database
# within ±15% (7.53% mean deviation), and the app's fit is a different correlation
# family; in practice the app runs 6-13% below Wang across Re, comfortably inside.
# ---------------------------------------------------------------------------


def _wang2000_j(re_dc: float, geom: RegisterGeometry, derived: DerivedGeometry) -> float:
    """Wang, Chi & Chang (2000) plain-fin Colburn j-factor, Eqs. (6)-(10)."""
    n = geom.rows
    dc = geom.tube_od + 2.0 * geom.fin_thickness  # fin collar diameter
    fp = geom.fin_pitch
    pt = geom.hole_pitch  # transverse tube pitch
    pl = geom.row_pitch  # longitudinal tube pitch
    dh = derived.dh_ext
    ln_re = math.log(re_dc)

    p3 = -0.361 - 0.042 * n / ln_re + 0.158 * math.log(n * (fp / dc) ** 0.41)
    p4 = -1.224 - 0.076 * (pl / dh) ** 1.42 / ln_re
    p5 = -0.083 + 0.058 * n / ln_re
    p6 = -5.735 + 1.21 * math.log(re_dc / n)

    return 0.086 * re_dc**p3 * n**p4 * (fp / dc) ** p5 * (fp / dh) ** p6 * (fp / pt) ** -0.93


def test_wang2000_air_side_j_factor_cross_check():
    geom = RegisterGeometry()
    derived = derive_geometry(geom)
    dc = geom.tube_od + 2.0 * geom.fin_thickness
    dc_over_dh = dc / derived.dh_ext

    # Sweep several operating points across the app's valid air-side Re range
    # (RE_AIR_MIN=300 .. RE_AIR_MAX=20000, Re on dh_ext).
    for re_dh in (400.0, 800.0, 1500.0, 3000.0, 6000.0):
        re_dc = re_dh * dc_over_dh  # same mass flux, collar-diameter Reynolds
        j_app = colburn_j_factor(re_dh, geom)
        j_wang = _wang2000_j(re_dc, geom, derived)
        # Independent-correlation agreement within Wang's scatter band + margin.
        assert abs(j_app - j_wang) / j_wang < 0.25, (
            f"Re_Dh={re_dh}: app j={j_app:.4f} vs Wang j={j_wang:.4f}"
        )


# ---------------------------------------------------------------------------
# Fin-efficiency validation — exact annular-fin (Bessel-function) solution.
#
# The app uses the Schmidt equivalent-radius approximation, which the literature
# states agrees with the exact circular-fin efficiency to ~1-2%. Here we verify
# that directly: for the app's equivalent fin radius, compute the EXACT annular
# (radial) fin efficiency and confirm the app's Schmidt result matches it tightly.
# This needs no external source — the exact solution is standard (Incropera §3.6):
#
#   η_fin = C2 · [K1(m r1)I1(m r2c) − I1(m r1)K1(m r2c)]
#              / [I0(m r1)K1(m r2c) + K0(m r1)I1(m r2c)]
#   C2 = (2 r1/m) / (r2c² − r1²)
#
# Bessel functions I0,I1,K0,K1 are evaluated via the Abramowitz & Stegun 9.8
# polynomial approximations (|error| < 2e-7), so the test is self-contained.
# A poor Schmidt match here (e.g. from a wrong equivalent radius) would surface
# as a large deviation — this test is what pins the X_L definition.
# ---------------------------------------------------------------------------


def _besseli0(x: float) -> float:
    t = x / 3.75
    if x < 3.75:
        t2 = t * t
        return (
            1.0
            + 3.5156229 * t2
            + 3.0899424 * t2**2
            + 1.2067492 * t2**3
            + 0.2659732 * t2**4
            + 0.0360768 * t2**5
            + 0.0045813 * t2**6
        )
    it = 1.0 / t
    poly = (
        0.39894228
        + 0.01328592 * it
        + 0.00225319 * it**2
        - 0.00157565 * it**3
        + 0.00916281 * it**4
        - 0.02057706 * it**5
        + 0.02635537 * it**6
        - 0.01647633 * it**7
        + 0.00392377 * it**8
    )
    return math.exp(x) / math.sqrt(x) * poly


def _besseli1(x: float) -> float:
    t = x / 3.75
    if x < 3.75:
        t2 = t * t
        poly = (
            0.5
            + 0.87890594 * t2
            + 0.51498869 * t2**2
            + 0.15084934 * t2**3
            + 0.02658733 * t2**4
            + 0.00301532 * t2**5
            + 0.00032411 * t2**6
        )
        return x * poly
    it = 1.0 / t
    poly = (
        0.39894228
        - 0.03988024 * it
        - 0.00362018 * it**2
        + 0.00163801 * it**3
        - 0.01031555 * it**4
        + 0.02282967 * it**5
        - 0.02895312 * it**6
        + 0.01787654 * it**7
        - 0.00420059 * it**8
    )
    return math.exp(x) / math.sqrt(x) * poly


def _besselk0(x: float) -> float:
    if x <= 2.0:
        t2 = (x / 2.0) ** 2
        return -math.log(x / 2.0) * _besseli0(x) + (
            -0.57721566
            + 0.42278420 * t2
            + 0.23069756 * t2**2
            + 0.03488590 * t2**3
            + 0.00262698 * t2**4
            + 0.00010750 * t2**5
            + 0.00000740 * t2**6
        )
    it = 2.0 / x
    poly = (
        1.25331414
        - 0.07832358 * it
        + 0.02189568 * it**2
        - 0.01062446 * it**3
        + 0.00587872 * it**4
        - 0.00251540 * it**5
        + 0.00053208 * it**6
    )
    return math.exp(-x) / math.sqrt(x) * poly


def _besselk1(x: float) -> float:
    if x <= 2.0:
        t2 = (x / 2.0) ** 2
        return math.log(x / 2.0) * _besseli1(x) + (1.0 / x) * (
            1.0
            + 0.15443144 * t2
            - 0.67278579 * t2**2
            - 0.18156897 * t2**3
            - 0.01919402 * t2**4
            - 0.00110404 * t2**5
            - 0.00004686 * t2**6
        )
    it = 2.0 / x
    poly = (
        1.25331414
        + 0.23498619 * it
        - 0.03655620 * it**2
        + 0.01504268 * it**3
        - 0.00780353 * it**4
        + 0.00325614 * it**5
        - 0.00068245 * it**6
    )
    return math.exp(-x) / math.sqrt(x) * poly


def _exact_annular_fin_efficiency(m: float, r1: float, r2c: float) -> float:
    """Exact radial (annular) fin efficiency, Incropera §3.6 / Eq. 3.91."""
    c2 = (2.0 * r1 / m) / (r2c**2 - r1**2)
    num = _besselk1(m * r1) * _besseli1(m * r2c) - _besseli1(m * r1) * _besselk1(m * r2c)
    den = _besseli0(m * r1) * _besselk1(m * r2c) + _besselk0(m * r1) * _besseli1(m * r2c)
    return c2 * num / den


def test_schmidt_fin_efficiency_matches_exact_bessel():
    geom = RegisterGeometry()
    derived = derive_geometry(geom)

    # The app's equivalent fin radius (Schmidt, staggered, diagonal X_L).
    x_m = geom.hole_pitch / 2.0
    x_l = 0.5 * math.sqrt(geom.row_pitch**2 + (geom.hole_pitch / 2.0) ** 2)
    r_eq = 1.27 * x_m * math.sqrt(x_l / x_m - 0.3)
    r1 = geom.tube_od / 2.0
    r2c = r_eq + geom.fin_thickness / 2.0

    a_fin, a_total = derived.fin_area, derived.total_ext_area

    for h_air in (40.0, 60.0, 80.0):
        m = math.sqrt(2.0 * h_air / (geom.fin_conductivity * geom.fin_thickness))

        # Recover the app's ISOLATED fin efficiency from its overall surface eff.
        # eta_surface = 1 - (A_fin/A_total)(1 - eta_fin)  ⇒  invert for eta_fin.
        eta_surface = fin_efficiency(h_air, geom, derived)
        eta_fin_app = 1.0 - (1.0 - eta_surface) * a_total / a_fin

        eta_fin_exact = _exact_annular_fin_efficiency(m, r1, r2c)

        # Schmidt tracks the exact annular-fin efficiency to ~1-2%.
        assert abs(eta_fin_app - eta_fin_exact) / eta_fin_exact < 0.03, (
            f"h={h_air}: Schmidt η={eta_fin_app:.4f} vs exact η={eta_fin_exact:.4f}"
        )
