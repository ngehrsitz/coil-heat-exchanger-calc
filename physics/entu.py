"""ε-NTU solver for a crossflow heat exchanger (both fluids unmixed).

References:
  Kays & London, Compact Heat Exchangers, 3rd ed.
  Incropera et al., Fundamentals of Heat and Mass Transfer, Table 11.4
"""

from __future__ import annotations

import math

from .geometry import DerivedGeometry, RegisterGeometry


def solve_crossflow(ntu: float, cr: float) -> float:
    """Crossflow effectiveness — both fluids unmixed (Kays & London).

    ε = 1 − exp{ (1/Cr) × NTU^0.22 × [exp(−Cr × NTU^0.78) − 1] }

    Boundary cases:
      NTU = 0  →  ε = 0
      Cr  = 0  →  ε = 1 − exp(−NTU)   (condensing / evaporating limit)
    """
    if ntu <= 0.0:
        return 0.0
    if cr <= 1e-6:
        # One fluid has effectively infinite capacity rate
        return 1.0 - math.exp(-ntu)
    return 1.0 - math.exp((1.0 / cr) * (ntu**0.22) * (math.exp(-cr * ntu**0.78) - 1.0))


def solve_ua(
    h_air: float,
    h_water: float,
    eta_surface: float,
    geom: RegisterGeometry,
    derived: DerivedGeometry,
) -> float:
    """Overall conductance UA [W/K].

    1/UA = R_air + R_wall + R_water

    R_air   = 1 / (η_surface × h_air   × A_ext)
    R_wall  = ln(D_o/D_i) / (2π × k_Cu × L_tube × N_tubes)
    R_water = 1 / (h_water × A_int)
    """
    # Air-side resistance
    if h_air <= 0 or eta_surface <= 0:
        return 0.0
    R_air = 1.0 / (eta_surface * h_air * derived.total_ext_area)

    # Wall conduction resistance (cylindrical wall).
    # Each tube spans the coil length; there are total_tubes tubes.
    tube_length_each = geom.coil_length
    ln_ratio = math.log(geom.tube_od / derived.tube_id)
    R_wall = ln_ratio / (
        2.0 * math.pi * geom.tube_conductivity * tube_length_each * derived.total_tubes
    )

    # Water-side resistance
    if h_water <= 0:
        return 0.0
    R_water = 1.0 / (h_water * derived.tube_int_area)

    ua = 1.0 / (R_air + R_wall + R_water)
    return ua
