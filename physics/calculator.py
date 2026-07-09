"""Full ε-NTU thermal performance calculator for a fin-and-tube register.

Supports both dry (sensible-only) and wet (condensing) coil operation. When the
coil operates in cooling mode and the effective surface temperature falls below
the inlet-air dew point, moisture condenses out of the air stream. The wet
regime is solved with the enthalpy-potential (Threlkeld) method, reusing the
same crossflow effectiveness relation as the dry regime but driven by an
enthalpy difference rather than a temperature difference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .correlations import air_heat_transfer_coeff, fin_efficiency, water_heat_transfer_coeff
from .entu import solve_crossflow, solve_ua
from .fluid_air import (
    AIR_T_MAX,
    RH_from_W,
    T_from_H_W,
    W_sat_at_T,
    air_enthalpy,
    air_props,
    dew_point,
    sat_enthalpy_at_T,
)
from .fluid_water import water_props
from .geometry import DerivedGeometry, RegisterGeometry, derive_geometry


@dataclass(frozen=True)
class FixedInputs:
    air_flow: float  # m³/s  volumetric at inlet conditions
    air_temp_in: float  # K
    water_temp_in: float  # K
    water_flow: float  # m³/s  volumetric
    humidity_ratio: float = 0.0  # kg_w / kg_da


@dataclass(frozen=True)
class CalcResult:
    thermal_power: float  # W   (positive = heating air)
    air_temp_out: float  # K
    water_temp_out: float  # K
    effectiveness: float  # —
    ua: float  # W/K
    ntu: float  # —
    # Intermediates
    re_air: float
    re_water: float
    h_air: float  # W/m²·K
    h_water: float  # W/m²·K
    fin_eff: float  # overall surface efficiency
    c_air: float  # W/K
    c_water: float  # W/K
    # Humidity / wet-coil results
    humidity_ratio_out: float = 0.0  # kg_w / kg_da
    air_rh_out: float = 0.0  # %   relative humidity of outlet air
    q_sensible: float = 0.0  # W   (signed, heating +)
    q_latent: float = 0.0  # W   (signed, heating +)
    condensate_rate: float = 0.0  # kg/s  water removed (≥ 0)
    is_wet: bool = False  # True if condensation occurs
    dew_point_in: float = 0.0  # K   inlet-air dew point


class PhysicsError(ValueError):
    """Raised when inputs are outside the valid range of the correlations."""


# --- Named thresholds (see also the exemplary constants in correlations.py) ---

# Humidity ratio below which the air is treated as effectively dry: no dew
# point, no wet-coil regime, no outlet-RH reporting.
_W_PRESENCE_FLOOR = 1e-6  # kg_w / kg_da

# Span over which the partial-wet weight ramps 0→1 once condensation onset is
# detected, keeping the dry→wet handoff continuous rather than a step.
_WETNESS_RAMP_SPAN_K = 3.0  # K

# _sat_temp_from_enthalpy bisection: absolute clamp to CoolProp's valid moist-air
# range, the half-width of the bracket narrowed around the guess, and the number
# of bisection iterations (2^-60 of the bracket → far below float precision).
_SAT_TEMP_MIN_K = 253.15
_SAT_TEMP_MAX_K = AIR_T_MAX
_SAT_TEMP_BRACKET_HALF_K = 40.0
_SAT_TEMP_ITERS = 60

# Symmetric half-step used for the saturation-enthalpy slope when the water
# temperature span is too small for a stable secant.
_SAT_SLOPE_HALF_STEP_K = 0.5

# Water temperature span below which the saturation-enthalpy secant is unstable
# and the symmetric point slope is used instead.
_DEGENERATE_DT_W_K = 1e-3  # K

# Convert a 0–1 fraction to a percentage for outlet-RH reporting.
_FRACTION_TO_PERCENT = 100.0


@dataclass(frozen=True)
class WetResult:
    """Outputs of the enthalpy-potential (Threlkeld) wet-coil solve.

    All values are in the heating-positive sign convention; ``condensate_rate``
    is ≥ 0 (moisture removed). Returned by ``_solve_wet`` and consumed by the
    partial-wet blend in ``calculate``.
    """

    q: float  # W   total (sensible + latent), heating +
    air_temp_out: float  # K
    water_temp_out: float  # K
    humidity_ratio_out: float  # kg_w / kg_da
    q_sensible: float  # W   (signed, heating +)
    q_latent: float  # W   (signed, heating +)
    condensate_rate: float  # kg/s  water removed (≥ 0)
    effectiveness: float  # —   enthalpy effectiveness
    ntu: float  # —   enthalpy-space NTU


@dataclass(frozen=True)
class _Intermediates:
    """Regime-independent quantities shared by the wet and dry result branches.

    Internal plumbing (not part of the public physics API) — replaces what was
    a stringly-typed dict so a mistyped field is a static error, not a runtime
    KeyError.
    """

    ua: float  # W/K
    re_air: float
    re_water: float
    h_air: float  # W/m²·K
    h_water: float  # W/m²·K
    fin_eff: float  # overall surface efficiency
    c_air: float  # W/K
    c_water: float  # W/K


@dataclass(frozen=True)
class _WetContext:
    """Inputs the wet-coil regime helpers share, bundled to avoid long arg lists.

    Internal plumbing (not part of the public physics API). ``calculate`` builds
    one after the dry ε-NTU predictor; ``_detect_wet_regime``, ``_solve_wet`` and
    ``_blend_wet_dry`` read from it instead of receiving 7–8 positional args each.
    """

    inputs: FixedInputs
    W_in: float  # kg_w / kg_da  inlet humidity ratio
    cp_a: float  # J/kg_da·K   dry-air-basis moist-air specific heat
    m_dot_da: float  # kg/s   dry-air mass flow (conserved through condensation)
    C_water: float  # W/K    water capacity rate
    ua_air: float  # W/K     air-side conductance (η·h_air·A_ext)
    ua_rest: float  # W/K    combined wall + water conductance
    r_air: float  # K/W      air-side resistance
    r_rest: float  # K/W     wall + water resistance
    # Dry ε-NTU predictor outputs (also the regime-detection / blend reference).
    Q_dry: float  # W        heating-positive
    T_air_out_dry: float  # K
    T_water_out_dry: float  # K
    dew_in: float  # K       inlet-air dew point (0 when air is effectively dry)


def _sat_temp_from_enthalpy(h_target: float, T_guess: float) -> float:
    """Temperature [K] of saturated moist air with enthalpy h_target [J/kg_da].

    Inverts sat_enthalpy_at_T() by bisection. Bracketed near T_guess (the coil
    surface / water temperature) and clamped to CoolProp's valid moist-air
    range so a stray call never raises.
    """
    lo, hi = _SAT_TEMP_MIN_K, _SAT_TEMP_MAX_K
    # Narrow the bracket around the guess for faster, well-behaved convergence.
    lo = max(lo, T_guess - _SAT_TEMP_BRACKET_HALF_K)
    hi = min(hi, T_guess + _SAT_TEMP_BRACKET_HALF_K)
    if sat_enthalpy_at_T(lo) >= h_target:
        return lo
    if sat_enthalpy_at_T(hi) <= h_target:
        return hi
    for _ in range(_SAT_TEMP_ITERS):
        mid = 0.5 * (lo + hi)
        if sat_enthalpy_at_T(mid) < h_target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _build_result(
    *,
    thermal_power: float,
    air_temp_out: float,
    water_temp_out: float,
    effectiveness: float,
    ntu: float,
    humidity_ratio_out: float,
    air_rh_out: float,
    q_sensible: float,
    q_latent: float,
    condensate_rate: float,
    is_wet: bool,
    intermediates: _Intermediates,
    dew_point_in: float,
) -> CalcResult:
    """Assemble a :class:`CalcResult` from regime-specific outputs.

    ``intermediates`` carries the shared, regime-independent quantities (``ua``,
    ``re_air``, ``re_water``, ``h_air``, ``h_water``, ``fin_eff``, ``c_air``,
    ``c_water``) so the wet and dry branches don't duplicate them.
    """
    return CalcResult(
        thermal_power=thermal_power,
        air_temp_out=air_temp_out,
        water_temp_out=water_temp_out,
        effectiveness=effectiveness,
        ntu=ntu,
        re_air=intermediates.re_air,
        re_water=intermediates.re_water,
        h_air=intermediates.h_air,
        h_water=intermediates.h_water,
        fin_eff=intermediates.fin_eff,
        c_air=intermediates.c_air,
        c_water=intermediates.c_water,
        ua=intermediates.ua,
        humidity_ratio_out=humidity_ratio_out,
        air_rh_out=air_rh_out,
        q_sensible=q_sensible,
        q_latent=q_latent,
        condensate_rate=condensate_rate,
        is_wet=is_wet,
        dew_point_in=dew_point_in,
    )


def _detect_wet_regime(ctx: _WetContext) -> tuple[bool, float]:
    """Decide whether the coil condenses, and estimate the mean surface temperature.

    Returns ``(wet, T_surface)``. The effective coil surface temperature seen by
    the air partitions the air↔water temperature drop across the air-side
    resistance vs. the rest. Condensation begins when the coil surface the air
    contacts falls below the inlet-air dew point. Detect it two ways: (a) the
    estimated mean surface temperature is below the dew point, or (b) the
    dry-predicted outlet air is already supersaturated (W_in exceeds saturation
    at T_air_out_dry) — a sure sign the surface dipped below the dew point
    somewhere along the coil.
    """
    inputs = ctx.inputs
    W_in = ctx.W_in
    T_air_mean = (inputs.air_temp_in + ctx.T_air_out_dry) / 2.0
    T_water_mean = (inputs.water_temp_in + ctx.T_water_out_dry) / 2.0
    r_air, r_rest = ctx.r_air, ctx.r_rest
    # The wetted surface sits at the air-film / (wall+water) interface. Walking
    # from air to water, the drop *across the air film* is the fraction
    # r_air/(r_air+r_rest) of the total air↔water drop, so that fraction — not
    # r_rest's — carries the surface toward the water side when the air film
    # dominates (the usual case for a finned coil).
    frac_air = r_air / (r_air + r_rest) if (r_air + r_rest) > 0 else 0.0
    T_surface = T_air_mean + frac_air * (T_water_mean - T_air_mean)

    is_cooling = inputs.water_temp_in < inputs.air_temp_in
    surface_below_dew = T_surface < ctx.dew_in
    dry_outlet_supersaturated = (
        is_cooling and W_in > _W_PRESENCE_FLOOR and W_in > W_sat_at_T(ctx.T_air_out_dry)
    )
    wet = (
        is_cooling and W_in > _W_PRESENCE_FLOOR and (surface_below_dew or dry_outlet_supersaturated)
    )
    return wet, T_surface


def _blend_wet_dry(
    ctx: _WetContext,
    result: WetResult,
    *,
    T_surface: float,
    intermediates: _Intermediates,
) -> CalcResult:
    """Interpolate between the dry and fully-wet solutions (partial-wet blend).

    Near onset only the coldest fraction of the coil condenses. Ramp a wetness
    weight 0→1 over a ~3 K span, then interpolate between the dry and fully-wet
    outlet states. At onset (w→0) the result equals the dry solution, so the
    dry→wet handoff is continuous rather than a step.

    Two onset signals matter, and the weight must ramp on EITHER — the same union
    the regime detector uses. Driving the weight off the surface margin alone lets
    it collapse to 0 (falling back to the dry, constant-W solution) at points the
    detector flagged wet via outlet supersaturation, which then leaves
    W_out > W_sat(T_out) — a physically impossible state masked as RH = 100 %. So
    take the larger of:
      • the surface margin  (dew_in − T_surface): the coil surface the air
        contacts has dipped below the inlet dew point, and
      • the outlet-air margin (dew_in − T_air_out_dry): the air itself is being
        cooled below its dew point, so it must be condensing regardless of the
        mean-surface estimate.
    """
    Q_dry = ctx.Q_dry
    T_air_out_dry = ctx.T_air_out_dry
    dew_in = ctx.dew_in
    wetness_surface = (dew_in - T_surface) / _WETNESS_RAMP_SPAN_K
    wetness_outlet = (dew_in - T_air_out_dry) / _WETNESS_RAMP_SPAN_K
    wetness = max(wetness_surface, wetness_outlet)
    wetness = min(max(wetness, 0.0), 1.0)

    Q = (1.0 - wetness) * Q_dry + wetness * result.q
    T_water_out = (1.0 - wetness) * ctx.T_water_out_dry + wetness * result.water_temp_out
    W_out = (1.0 - wetness) * ctx.W_in + wetness * result.humidity_ratio_out
    h_in = air_enthalpy(ctx.inputs.air_temp_in, ctx.W_in)
    h_out = h_in + Q / ctx.m_dot_da
    T_air_out = T_from_H_W(h_out, W_out)
    q_sensible = ctx.m_dot_da * ctx.cp_a * (T_air_out - ctx.inputs.air_temp_in)
    q_latent = Q - q_sensible
    condensate = wetness * result.condensate_rate
    is_wet_flag = condensate > 0.0

    return _build_result(
        thermal_power=Q,
        air_temp_out=T_air_out,
        water_temp_out=T_water_out,
        effectiveness=result.effectiveness,
        ntu=result.ntu,
        humidity_ratio_out=W_out,
        air_rh_out=RH_from_W(T_air_out, W_out) * _FRACTION_TO_PERCENT,
        q_sensible=q_sensible,
        q_latent=q_latent,
        condensate_rate=condensate,
        is_wet=is_wet_flag,
        intermediates=intermediates,
        dew_point_in=dew_in,
    )


def calculate(inputs: FixedInputs, geom: RegisterGeometry) -> CalcResult:
    """Run the full ε-NTU pipeline and return performance results."""

    derived: DerivedGeometry = derive_geometry(geom)

    # --- Fluid properties ---
    W_in = inputs.humidity_ratio
    rho_a, cp_a, mu_a, k_a, pr_a = air_props(inputs.air_temp_in, W_in)
    rho_w, cp_w, mu_w, k_w, pr_w = water_props(inputs.water_temp_in)

    # --- Mass flow rates ---
    m_dot_air = inputs.air_flow * rho_a  # kg/s humid air
    m_dot_water = inputs.water_flow * rho_w  # kg/s

    if m_dot_air <= 0 or m_dot_water <= 0:
        raise PhysicsError("Mass flow rates must be positive.")

    # Dry-air mass flow — conserved through condensation (water is not)
    m_dot_da = m_dot_air / (1.0 + W_in)

    # --- Air-side heat transfer ---
    h_air, re_air = air_heat_transfer_coeff(m_dot_air, cp_a, mu_a, pr_a, geom, derived)

    # --- Water-side heat transfer ---
    h_water, re_water = water_heat_transfer_coeff(
        m_dot_water, rho_w, mu_w, k_w, pr_w, geom, derived
    )

    # --- Fin / surface efficiency ---
    eta_surface = fin_efficiency(h_air, geom, derived)

    # --- Overall conductance ---
    ua = solve_ua(h_air, h_water, eta_surface, geom, derived)
    if ua <= 0:  # pragma: no cover - defensive; solve_ua is > 0 for any valid geometry
        raise PhysicsError("UA ≤ 0: check geometry and flow inputs.")

    # Air-side conductance vs. the rest (wall + water) — needed both for the
    # surface-temperature estimate and for the enthalpy-potential conductance.
    if eta_surface <= 0:  # pragma: no cover - defensive; Schmidt fin efficiency is in (0, 1]
        raise PhysicsError("Surface efficiency ≤ 0.")
    ua_air = eta_surface * h_air * derived.total_ext_area  # W/K
    r_air = 1.0 / ua_air
    r_rest = max(1.0 / ua - r_air, 0.0)  # wall + water resistance
    ua_rest = (1.0 / r_rest) if r_rest > 0 else float("inf")

    # --- Capacity rates ---
    C_air = m_dot_air * cp_a
    C_water = m_dot_water * cp_w
    C_min = min(C_air, C_water)
    C_max = max(C_air, C_water)
    C_r = C_min / C_max

    # --- Dry ε-NTU predictor (also the final answer when the coil stays dry) ---
    ntu = ua / C_min
    epsilon = solve_crossflow(ntu, C_r)

    delta_T = inputs.water_temp_in - inputs.air_temp_in
    Q_dry = math.copysign(epsilon * C_min * abs(delta_T), delta_T)
    T_air_out_dry = inputs.air_temp_in + Q_dry / C_air
    T_water_out_dry = inputs.water_temp_in - Q_dry / C_water

    dew_in = dew_point(inputs.air_temp_in, W_in) if W_in > _W_PRESENCE_FLOOR else 0.0

    # Regime-independent quantities shared by both the wet and dry results.
    intermediates = _Intermediates(
        ua=ua,
        re_air=re_air,
        re_water=re_water,
        h_air=h_air,
        h_water=h_water,
        fin_eff=eta_surface,
        c_air=C_air,
        c_water=C_water,
    )

    # Wet-coil enthalpy and dry-air mass balances are per kg dry air; CoolProp's
    # cp_ha is per kg humid air, so convert the specific heat to the same basis.
    cp_da = cp_a * (1.0 + W_in)

    # Inputs the wet-coil regime helpers share, bundled once after the dry
    # predictor so they take a single context instead of long positional lists.
    wet_ctx = _WetContext(
        inputs=inputs,
        W_in=W_in,
        cp_a=cp_da,
        m_dot_da=m_dot_da,
        C_water=C_water,
        ua_air=ua_air,
        ua_rest=ua_rest,
        r_air=r_air,
        r_rest=r_rest,
        Q_dry=Q_dry,
        T_air_out_dry=T_air_out_dry,
        T_water_out_dry=T_water_out_dry,
        dew_in=dew_in,
    )

    # --- Regime detection ---
    wet, T_surface = _detect_wet_regime(wet_ctx)

    if wet:
        result = _solve_wet(wet_ctx)
        if result is not None:
            return _blend_wet_dry(
                wet_ctx,
                result,
                T_surface=T_surface,
                intermediates=intermediates,
            )
        else:  # pragma: no cover - unreachable: when the regime is detected wet
            # there is always enthalpy potential, so _solve_wet never returns None
            # here. Kept as a defensive fall-through to the dry result.
            pass

    # --- Dry result ---
    return _build_result(
        thermal_power=Q_dry,
        air_temp_out=T_air_out_dry,
        water_temp_out=T_water_out_dry,
        effectiveness=epsilon,
        ntu=ntu,
        humidity_ratio_out=W_in,
        air_rh_out=(
            (RH_from_W(T_air_out_dry, W_in) * _FRACTION_TO_PERCENT)
            if W_in > _W_PRESENCE_FLOOR
            else 0.0
        ),
        q_sensible=Q_dry,
        q_latent=0.0,
        condensate_rate=0.0,
        is_wet=False,
        intermediates=intermediates,
        dew_point_in=dew_in,
    )


def _solve_wet(ctx: _WetContext) -> WetResult | None:
    """Enthalpy-potential (Threlkeld) wet-coil solve.

    Returns a :class:`WetResult`, or None if the solution degenerates (e.g. no
    net sensible cooling), in which case the caller falls back to the dry
    result.

    ``ctx.ua_air`` is the air-side conductance (η·h_air·A_ext) and ``ctx.ua_rest``
    the combined wall + water conductance, both in W/K. All enthalpies are per kg
    dry air; the enthalpy-space conductance follows Mitchell & Braun:

        UA* = 1 / (cp_a/UA_air + c_s/UA_rest)      [kg_da/s]

    and the two capacity rates are the dry-air mass flow and the water capacity
    rate scaled by the saturation-enthalpy slope c_s into the same units.
    """
    inputs = ctx.inputs
    W_in = ctx.W_in
    cp_a = ctx.cp_a
    m_dot_da = ctx.m_dot_da
    C_water = ctx.C_water
    ua_air = ctx.ua_air
    ua_rest = ctx.ua_rest
    T_water_out_dry = ctx.T_water_out_dry

    T_air_in = inputs.air_temp_in
    T_water_in = inputs.water_temp_in

    h_air_in = air_enthalpy(T_air_in, W_in)
    h_s_wi = sat_enthalpy_at_T(T_water_in)

    # Saturation-enthalpy slope c_s = d(h_sat)/dT, secant across the water span.
    dT_w = T_water_out_dry - T_water_in
    if abs(dT_w) < _DEGENERATE_DT_W_K:
        # Degenerate span — use a small symmetric point slope instead.
        c_s = (
            sat_enthalpy_at_T(T_water_in + _SAT_SLOPE_HALF_STEP_K)
            - sat_enthalpy_at_T(T_water_in - _SAT_SLOPE_HALF_STEP_K)
        ) / (2.0 * _SAT_SLOPE_HALF_STEP_K)
    else:
        c_s = (sat_enthalpy_at_T(T_water_out_dry) - h_s_wi) / dT_w
    if c_s <= 0:  # pragma: no cover - unreachable: saturated-air enthalpy is
        # monotonic in T, so the secant slope is always positive.
        return None

    # Enthalpy-space conductance and capacity rates.
    ua_star = 1.0 / (cp_a / ua_air + c_s / ua_rest)  # kg_da/s
    m_star_air = m_dot_da
    m_star_water = C_water / c_s
    m_min = min(m_star_air, m_star_water)
    m_max = max(m_star_air, m_star_water)
    cr_h = m_min / m_max
    ntu_h = ua_star / m_min
    eps_h = solve_crossflow(ntu_h, cr_h)

    # Enthalpy driving potential and total heat removed from the air.
    dh_max = h_air_in - h_s_wi  # > 0 in cooling
    if dh_max <= 0:
        return None
    Q_total = eps_h * m_min * dh_max  # W  (magnitude removed from air)
    Q = -Q_total  # heating-positive convention

    # Recover the outlet state with the apparatus-dew-point (ADP) line while
    # matching the enthalpy change already fixed by eps_h. The leaving air lies
    # on the straight line from inlet to saturated ADP; solve the contact fraction
    # on that line so air_enthalpy(T_out, W_out) equals h_in - Q_total/m_dot_da.
    h_adp = h_air_in - dh_max  # = h_s_wi: saturated enthalpy at the coldest surface
    T_adp = _sat_temp_from_enthalpy(h_adp, T_water_in)
    W_adp = W_sat_at_T(T_adp)

    h_target = h_air_in - Q_total / m_dot_da
    lo, hi = 0.0, 1.0
    for _ in range(_SAT_TEMP_ITERS):
        contact_mid = 0.5 * (lo + hi)
        T_mid = T_air_in - contact_mid * (T_air_in - T_adp)
        W_mid = W_in - contact_mid * (W_in - W_adp)
        if air_enthalpy(T_mid, W_mid) > h_target:
            lo = contact_mid
        else:
            hi = contact_mid
    contact = 0.5 * (lo + hi)
    T_air_out = T_air_in - contact * (T_air_in - T_adp)
    W_out = W_in - contact * (W_in - W_adp)
    W_out = min(max(W_out, 0.0), W_in)  # condensation only removes moisture

    q_sensible = m_dot_da * cp_a * (T_air_out - T_air_in)
    if q_sensible >= 0:  # pragma: no cover - unreachable: contact fraction (1−BF)
        # is strictly positive whenever wet is detected, so the leaving air is
        # always cooler than the inlet. Defensive guard against a numerical edge.
        # No net sensible cooling — defer to dry result.
        return None
    q_latent = Q - q_sensible
    condensate = m_dot_da * (W_in - W_out)

    T_water_out = T_water_in - Q / C_water

    return WetResult(
        q=Q,
        air_temp_out=T_air_out,
        water_temp_out=T_water_out,
        humidity_ratio_out=W_out,
        q_sensible=q_sensible,
        q_latent=q_latent,
        condensate_rate=condensate,
        effectiveness=eps_h,
        ntu=ntu_h,
    )
