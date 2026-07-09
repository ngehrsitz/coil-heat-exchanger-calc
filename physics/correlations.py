"""Heat transfer correlations for a fin-and-tube coil.

Air-side:  Colburn j-factor for staggered tube banks (Rich 1975 / McQuiston 1978,
           corrugated fins)
Water-side: Gnielinski correlation for turbulent internal tube flow
Fin:        Schmidt approximation for fin efficiency (rectangular/corrugated fins)
"""

from __future__ import annotations

import math
from typing import NamedTuple

from .geometry import DerivedGeometry, RegisterGeometry


class HTransfer(NamedTuple):
    """A convective heat-transfer coefficient and its Reynolds number."""

    h: float  # W/m²·K   convective coefficient
    re: float  # —        Reynolds number


# ---------------------------------------------------------------------------
# Air-side: Colburn j-factor
# ---------------------------------------------------------------------------

# Documented validity range of the Colburn j-factor correlation (Re based on
# the air-side hydraulic diameter). Outside this the fit is an extrapolation.
RE_AIR_MIN = 300.0
RE_AIR_MAX = 20_000.0

# Rich (1975) / McQuiston (1978) Colburn j-factor coefficients for corrugated
# fins (slightly higher than plain fins):
#     j = COLBURN_C1 * Re^COLBURN_RE_EXP * (s/D)^COLBURN_SD_EXP * N_rows^COLBURN_NROWS_EXP
COLBURN_C1 = 0.158
COLBURN_RE_EXP = -0.4
COLBURN_SD_EXP = 0.15
COLBURN_NROWS_EXP = -0.02


def air_re_in_range(re_air: float) -> bool:
    """True if the air-side Reynolds number is within the correlation's range."""
    return RE_AIR_MIN <= re_air <= RE_AIR_MAX


def colburn_j_factor(re_air: float, geom: RegisterGeometry) -> float:
    """Colburn j-factor for a staggered fin-and-tube bank.

    Uses the Rich (1975) / McQuiston (1978) correlation for corrugated fins:
        j = C1 * Re_Dh^(-0.4) * (s/D)^0.15 * (N_rows)^(-0.02)

    where s = fin pitch, D = tube OD.

    For Re in [300, 20000] — the typical operating range for HVAC coils.
    """
    if re_air <= 0:
        return 0.0

    s_over_D = geom.fin_pitch / geom.tube_od
    j = (
        COLBURN_C1
        * (re_air**COLBURN_RE_EXP)
        * (s_over_D**COLBURN_SD_EXP)
        * (geom.rows**COLBURN_NROWS_EXP)
    )
    return float(max(j, 0.0))


def air_heat_transfer_coeff(
    m_dot_air: float,
    cp_air: float,
    mu_air: float,
    pr_air: float,
    geom: RegisterGeometry,
    derived: DerivedGeometry,
) -> HTransfer:
    """Return (h_air [W/m²K], Re_air) using Colburn analogy.

    G_c = mass flux based on minimum free-flow area.
    h   = j × G_c × cp / Pr^(2/3)
    """
    G_c = m_dot_air / derived.min_free_flow_area  # kg/m²s
    re_air = G_c * derived.dh_ext / mu_air
    j = colburn_j_factor(re_air, geom)
    h_air = j * G_c * cp_air / (pr_air ** (2.0 / 3.0))
    return HTransfer(h_air, re_air)


# ---------------------------------------------------------------------------
# Water-side: Gnielinski correlation
# ---------------------------------------------------------------------------

# Gnielinski is valid for turbulent flow (Re ≥ 3000); below this the code falls
# back to the Hausen laminar correlation, so results in that regime are a
# regime change rather than a strict extrapolation, but still worth flagging.
RE_WATER_MIN = 3000.0

# Nusselt number for fully developed laminar flow in a round tube (constant
# wall temperature); also the floor the turbulent correlation is clamped to.
LAMINAR_NU_LIMIT = 3.66

# Hausen laminar entrance-correction coefficients:
#     Nu = 3.66 + 0.0668·Gz / (1 + 0.04·Gz^(2/3)),  Gz = Re·Pr / (L/D)
HAUSEN_C1 = 0.0668
HAUSEN_C2 = 0.04

# Petukhov friction factor  f = (PETUKHOV_A·ln Re − PETUKHOV_B)^−2
PETUKHOV_A = 0.790
PETUKHOV_B = 1.64
# Gnielinski denominator coefficient (1 + GNIELINSKI_C·√(f/8)·(Pr^(2/3) − 1)).
GNIELINSKI_C = 12.7
# Reynolds offset in the Gnielinski numerator, (Re − GNIELINSKI_RE_OFFSET)·Pr.
GNIELINSKI_RE_OFFSET = 1000.0

# L/D below which the tube-entrance correction is applied.
ENTRANCE_LD_THRESHOLD = 60
# Exponent in the simplified (D/L)^ENTRANCE_LD_EXP entrance-correction factor.
ENTRANCE_LD_EXP = 0.7


def water_re_in_range(re_water: float) -> bool:
    """True if the water-side Reynolds number is within Gnielinski's range."""
    return re_water >= RE_WATER_MIN


def gnielinski_nusselt(re: float, pr: float, l_over_d: float) -> float:
    """Nusselt number for turbulent internal flow (Gnielinski 1976).

    Valid for: 0.5 ≤ Pr ≤ 2000, 3000 ≤ Re ≤ 5×10⁶.
    Falls back to the Hausen laminar correlation for Re < 3000 (laminar/transition).

    Nu = (f/8)(Re − 1000)Pr / [1 + 12.7√(f/8)(Pr^(2/3) − 1)]
    f  = (0.790 ln Re − 1.64)^−2   (Petukhov friction factor)
    """
    if re <= 0:
        return LAMINAR_NU_LIMIT  # fully developed laminar limit
    if re < RE_WATER_MIN:
        # Laminar — Hausen approximation with entrance correction
        nu_lam = LAMINAR_NU_LIMIT + (HAUSEN_C1 * (re * pr / l_over_d)) / (
            1.0 + HAUSEN_C2 * (re * pr / l_over_d) ** (2.0 / 3.0)
        )
        return float(nu_lam)

    f = (PETUKHOV_A * math.log(re) - PETUKHOV_B) ** -2
    numerator = (f / 8.0) * (re - GNIELINSKI_RE_OFFSET) * pr
    denominator = 1.0 + GNIELINSKI_C * math.sqrt(f / 8.0) * (pr ** (2.0 / 3.0) - 1.0)
    nu = numerator / denominator

    # Entrance correction: multiply by [1 + (D/L)^0.7]. This is a simplified
    # single-term (D/L)^0.7 factor at full weight, not the coefficient-weighted
    # Nusselt form; only applied when l_over_d < ENTRANCE_LD_THRESHOLD.
    if l_over_d < ENTRANCE_LD_THRESHOLD:
        nu *= 1.0 + derived_entrance_factor(l_over_d)

    return float(max(nu, LAMINAR_NU_LIMIT))


def derived_entrance_factor(l_over_d: float) -> float:
    """Hydrodynamic entrance correction factor (approximate)."""
    return (1.0 / l_over_d) ** ENTRANCE_LD_EXP if l_over_d > 0 else 0.0


def water_heat_transfer_coeff(
    m_dot_water: float,
    rho_water: float,
    mu_water: float,
    k_water: float,
    pr_water: float,
    geom: RegisterGeometry,
    derived: DerivedGeometry,
) -> HTransfer:
    """Return (h_water [W/m²K], Re_water).

    Flow is distributed equally across all tubes.
    """
    n_tubes = derived.total_tubes
    m_dot_per_tube = m_dot_water / n_tubes
    area_per_tube = math.pi / 4.0 * derived.dh_int**2
    u = m_dot_per_tube / (rho_water * area_per_tube)
    re_water = rho_water * u * derived.dh_int / mu_water

    # Tube length = coil_length (each tube runs along the coil-length axis, not
    # the airflow-direction depth). Matches solve_ua() and tube_int_area.
    l_over_d = geom.coil_length / derived.dh_int
    nu = gnielinski_nusselt(re_water, pr_water, l_over_d)
    h_water = nu * k_water / derived.dh_int
    return HTransfer(h_water, re_water)


# ---------------------------------------------------------------------------
# Fin efficiency — Schmidt approximation for rectangular/corrugated fins
# ---------------------------------------------------------------------------


def fin_efficiency(h_air: float, geom: RegisterGeometry, derived: DerivedGeometry) -> float:
    """Overall surface efficiency using Schmidt (1945-46) approximation.

    For a circular fin on a round tube:
        m  = sqrt(2 h / (k_fin × t_fin))
        r2c = r2 + t_fin/2   (corrected outer radius)
        phi = (r2c/r1 - 1)(1 + 0.35 ln(r2c/r1))
        eta_fin = tanh(m r1 phi) / (m r1 phi)

    For fin-and-tube with non-circular fins, an equivalent radius is used:
        r_eq = 1.27 × X_M × sqrt(X_L/X_M - 0.3)
    where, for a staggered array, X_M = ½ × transverse pitch (hole_pitch/2) and
    X_L = half the diagonal distance to the nearest tube in the adjacent row,
    X_L = ½ × sqrt(row_pitch² + (hole_pitch/2)²)  (Schmidt; see ASHRAE / McQuiston).
    The (1.27, 0.3) constants are the staggered-layout pair from Wang, Chi & Chang
    (Int. J. Heat Mass Transfer, 1998, Eq. 4); the inline layout uses (1.28, 0.2).

    Reference: T.E. Schmidt, "La production calorifique des surfaces munies
    d'ailettes," Bulletin de l'Institut International du Froid, Annexe G-5,
    1945-46. Agrees with the exact annular-fin (Bessel) efficiency to ~1-2%.
    """
    if h_air <= 0:
        return 1.0

    r1 = geom.tube_od / 2.0
    k_fin = geom.fin_conductivity
    t_fin = geom.fin_thickness

    # Equivalent circular fin radius for staggered tube array (Schmidt).
    # X_L is HALF the diagonal pitch to the nearest adjacent-row tube, not the
    # full row pitch — using the row pitch overstates r_eq and understates η.
    X_M = geom.hole_pitch / 2.0
    X_L = 0.5 * math.sqrt(geom.row_pitch**2 + (geom.hole_pitch / 2.0) ** 2)
    r_eq = 1.27 * X_M * math.sqrt(X_L / X_M - 0.3)

    r2c = r_eq + t_fin / 2.0
    m = math.sqrt(2.0 * h_air / (k_fin * t_fin))
    phi = (r2c / r1 - 1.0) * (1.0 + 0.35 * math.log(r2c / r1))

    mr1phi = m * r1 * phi
    if mr1phi < 1e-10:
        return 1.0
    eta_fin = math.tanh(mr1phi) / mr1phi

    # Overall surface efficiency
    A_fin = derived.fin_area
    A_total = derived.total_ext_area
    eta_surface = 1.0 - (A_fin / A_total) * (1.0 - eta_fin)
    return eta_surface
