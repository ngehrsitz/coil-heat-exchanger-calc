# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A PyQt6 desktop application that calculates and plots the thermal performance of a fin-and-tube heating/cooling register. The user selects one input variable as the X-axis, sets a min/max range, fixes all other inputs (including inlet relative humidity), and the app plots thermal power [kW], air outlet temperature [°C], water return temperature [°C], and outlet relative humidity [%] over at least 100 computed points. When a cooling coil drops below the inlet-air dew point, condensation (latent heat + moisture removal) is modelled.

## Commands

This project is managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`); there is no `requirements.txt`.

```bash
# Install dependencies (create the venv + install locked deps)
uv sync

# Run the app
uv run python main.py

# Run all tests. Coverage rides along automatically (config in pyproject.toml
# addopts): prints a per-file table and fails if total coverage < 100%.
uv run pytest

# Run a single test file
uv run pytest tests/test_calculator.py -v

# Run a single test by name
uv run pytest tests/test_correlations.py::test_crossflow_ntu1_cr05 -v

# Lint / format-check / type-check (the same gates CI runs)
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## Architecture

### Data flow (physics layer — no Qt dependency)

```
User inputs (float + unit string)
  → physics/axis_model.py to_si() / from_si()  (dispatch by axis variable; axis labels + display bounds)
  → physics/units.py     to_kelvin() / to_m3s()                  → plain float in SI
  → physics/geometry.py  derive_geometry(RegisterGeometry)        → DerivedGeometry
                         (geometry mm↔m via units.py to_meter() / from_meter(), in the geometry panel)
  → physics/fluid_air.py / fluid_water.py  (CoolProp)             → ρ, cp, μ, k, Pr
                         W_from_RH() / RH_from_W() / air_enthalpy() (moist-air psychrometrics)
  → physics/correlations.py  air_heat_transfer_coeff()            → h_air, Re_air
                             water_heat_transfer_coeff()           → h_water, Re_water
                             fin_efficiency()                      → η_surface
  → physics/entu.py      solve_ua()                               → UA [W/K]
                         solve_crossflow(NTU, Cr)                  → ε
  → physics/calculator.py  calculate(FixedInputs, RegisterGeometry) → CalcResult
                           _solve_wet(...)                          → wet-coil branch
  → sweep/sweep.py       run_sweep(fixed, geom, AxisSpec)          → list[DataPoint]
```

Support modules used throughout but omitted from the flow above for clarity:
`physics/axis_model.py` sits above the pure unit conversions in `units.py` — it maps each sweep-axis
variable to its SI unit, display units, label, and input bounds, and its `to_si()`/`from_si()`
dispatch on the variable to the right `units.py` converter. `physics/_constants.py` supplies the
shared `P_ATM` (101 325 Pa) that the fluid wrappers evaluate properties at. `physics/_exceptions.py`
holds `PropertyRangeError` (raised by the fluid wrappers when CoolProp is asked for an out-of-range
state) and `_is_range_error`, kept dependency-free so the wrappers and `errors.py` can share it
without a circular import; `physics/errors.py` re-exports `PropertyRangeError` and its
`humanize_error()` formats the message on each failed (NaN) `DataPoint` in the sweep.

`calculate()` is the single entry point for physics — the sweep engine calls it once per X-axis point (`AxisSpec.steps`, which defaults to 100 but the UI sets it via `default_steps()` (≥100) in `_run_calculation()`). Failed points (`PhysicsError`, `ValueError`, `ZeroDivisionError`) are returned as NaN `DataPoint`s rather than raising, so the chart always receives a full array.

### Dry vs. wet coil (condensation)

`calculate()` first runs the dry sensible ε-NTU as a predictor, then decides the regime. The coil is **wet** when it is cooling, humidity is present, and either the estimated mean surface temperature is below the inlet-air dew point **or** the dry-predicted outlet air is supersaturated. The wet branch (`_solve_wet()`) uses the **enthalpy-potential (Threlkeld) method**: the driving potential is the enthalpy difference between the bulk air and saturated air at the water temperature, reusing `solve_crossflow` in enthalpy space (`UA* = 1 / (cp_a/UA_air + c_s/UA_rest)`, where `c_s` is the saturation-enthalpy slope). Enthalpy is per **kg dry air** — condensation conserves dry-air mass, not humid-air mass, so `m_dot_da = m_dot_air / (1 + W)`. The outlet state is recovered with an apparatus-dew-point / bypass-factor model, and a **partial-wet blend** (weighting the dry and fully-wet solutions by how far the surface is below the dew point) keeps the dry→wet transition continuous. If the wet solve degenerates it falls back to the dry result. RH is a **fixed** operating condition, never a sweep axis.

### SI unit discipline

All values inside the physics packages are plain `float` in SI base units. Conversion happens **only** at two boundaries:
- **Input boundary**: `physics/axis_model.py` `to_si()` — called in `ui/main_window.py` before building `FixedInputs` — dispatches on the variable to `to_kelvin()` / `to_m3s()` in `physics/units.py` (the four sweep-axis variables are temperatures and flows only). Geometry length inputs are a separate boundary: `ui/geometry_panel.py` converts them mm↔m directly via `units.py` `to_meter()` / `from_meter()`. Inlet RH% is converted to humidity ratio `W` by `sweep.sweep.resolve_humidity()` (which wraps `fluid_air.W_from_RH()`) at the inlet air temperature; when air temp is the X-axis, that temperature is seeded to the range midpoint via `sweep.sweep.axis_midpoint_si()`. Holding absolute humidity `W` constant along the sweep is the physically correct choice, so RH then varies along it.
- **Output boundary**: `physics/axis_model.py` `from_si()` — called in `ui/chart_widget.py` to convert X-axis values for display (it dispatches to `from_kelvin()` / `from_m3s()` in `physics/units.py`)

Temperature conversions use offset functions (not scale factors). Never pass a Celsius value where Kelvin is expected.

### Geometry: independent vs. derived

`RegisterGeometry` holds only the 11 independent parameters (rows, pitches, diameters, conductivities). All computed quantities (areas, hydraulic diameters, tube count, depth) live in `DerivedGeometry` produced by `derive_geometry()`. The UI geometry panel passes mm to the user but stores metres internally.

### Chart (pyqtgraph three Y-axes, four curves)

`ChartWidget` uses two additional `pg.ViewBox` objects. `_vb2` is linked to the built-in right axis (col 2 in the layout) and carries the air outlet temperature curve (blue, solid) plus the water return temperature curve (purple, dashed) on the shared °C scale. `_vb3` is linked to a manually-added `pg.AxisItem("right")` inserted at col 3, and carries the air outlet relative humidity curve (green, dashed). The thermal power curve is on `plotItem.vb` (left axis, red). The four metric colors (`POWER`/`TEMP`/`WATER`/`RH`) are defined once in `ui/palette.py`; the chart curves use all four, and the `main_window` status line reuses `palette.RH` for the `(condensing)` note (its metric numbers are plain bold text, not color-coded). `_update_views()` must be connected to `pi.vb.sigResized` to keep all three ViewBoxes geometrically in sync on resize — each gets `setGeometry(rect)` and `linkedViewChanged(pi.vb, XAxis)` for the same `rect`. Hover uses `pi.scene().sigMouseMoved` — `mapSceneToView` converts scene coords, then `np.argmin(abs(x_values - x))` finds the nearest point and reports power, `T_air_out`, `T_water_out`, and `RH_out` when available.

### Key correlations

- **Air side**: Colburn j-factor (Rich 1975 / McQuiston 1978 for corrugated fins): `j = 0.158 × Re⁻⁰·⁴ × (s/D)⁰·¹⁵ × N_rows⁻⁰·⁰²`; valid Re 300–20 000
- **Water side**: Gnielinski (1976) for turbulent flow, Hausen for Re < 3000; entrance correction applied when L/D < 60
- **Fin efficiency**: Schmidt (1945-46) equivalent-radius approximation for staggered arrays (X_L = half the diagonal pitch to the nearest adjacent-row tube, ½·√(row_pitch² + (hole_pitch/2)²))
- **ε-NTU**: Kays & London crossflow unmixed/unmixed: `ε = 1 − exp{(1/Cr) × NTU⁰·²² × [exp(−Cr × NTU⁰·⁷⁸) − 1]}`; degenerates to `1 − exp(−NTU)` when Cr → 0
- **Wet coil**: enthalpy-potential (Threlkeld) method with `solve_crossflow` in enthalpy space; outlet recovered via apparatus-dew-point / bypass-factor model. See "Dry vs. wet coil" above.

### Sign convention

`CalcResult.thermal_power` (W) is positive when water heats air (water hotter), negative when water cools air. `Q = copysign(ε × C_min × |ΔT|, T_water_in − T_air_in)` in the dry regime; in the wet regime `Q` is the total (sensible + latent) enthalpy transfer, `Q = q_sensible + q_latent`, and `condensate_rate ≥ 0` is the moisture removed. `CalcResult` also carries `water_temp_out`, `humidity_ratio_out`, `air_rh_out` (%), and the `is_wet` flag.

## Test reference values

Tests validate correlations against known reference points:
- `solve_crossflow(1.0, 0.5)` ≈ 0.545 ± 0.005 (`tests/test_correlations.py`; pinned tightly to the Kays-London model's own output to catch regressions — Incropera Table 11.4 exact ≈ 0.558, the ~2–3% offset is expected)
- `water_density(293.15)` ≈ 998.2 kg/m³, `water_prandtl(293.15)` ≈ 7.01 (`tests/test_fluid_water.py`; NIST)
- `air_density(293.15, 0.0)` ≈ 1.204 kg/m³ (`tests/test_fluid_air.py`; ideal gas at 101 325 Pa; the second argument is the humidity ratio `W`, not pressure — pressure is fixed internally)

Wet-coil physics is validated against two published references:
- **Purdue ME 418 psychrometric example** (`tests/test_fluid_air.py`) — pure mass/energy balance, independent of the ε-NTU correlation, so the psychrometric layer is checked to ~2% (condensate ±2.0 lb/hr, SHR ±0.03): air 85 °F/50 % RH → 55 °F/90 % RH, condensate ≈ 39.8 lb/hr, SHR ≈ 0.60.
- **Mitchell & Braun, *HVAC in Buildings* (2013), Example 13.3** (`tests/test_calculator.py`, via F-Chart `CoolingCoil1_CL`) — same enthalpy-effectiveness method; end-to-end `_solve_wet` call with injected UA matches Q ≈ 48.5 kW, T_air_out ≈ 11.2 °C, T_water_out ≈ 8.6 °C. Q and T_water_out are checked to ~15% relative tolerance (the reference is counterflow, this model crossflow); T_air_out uses an absolute ±3 °C tolerance. Condensate is the most model-sensitive output and is validated only to order of magnitude.

## Dependencies of note

- **CoolProp** (C++ extension, pre-compiled wheel): fluid properties via `PropsSI` (water) and `HAPropsSI` (moist air `HumidAir` backend). The two backends use overlapping single-letter keys with **different meanings** — notably `'D'`, which is density for water but dew point for moist air — so keep them separate:
  - **`PropsSI` (water)** — `'D'`=density, `'C'`=cp, `'V'`=viscosity, `'L'`=conductivity, `'Prandtl'`.
  - **`HAPropsSI` (moist air)** — `'H'`=enthalpy **per kg dry air**, `'R'`=relative humidity (fraction 0–1), `'W'`=humidity ratio, `'D'`=dew point, `'T'`=dry-bulb temperature (recovered from `H` + `W` in `T_from_H_W`), `'Vha'`=specific volume humid air, `'cp_ha'`=cp humid air, `'mu'`=viscosity, `'k'`=conductivity. Saturation properties use `'R'=1.0`.
- **pyqtgraph**: chart rendering; PyQt6 is the Qt binding (imported directly in `ui/chart_widget.py`; pyqtgraph auto-detects it). `pg.setConfigOption` is used only to set the white background / black foreground, not to select a backend.
- **numpy**: used only in `sweep/sweep.py` (`np.linspace`) and `ui/chart_widget.py` (array ops for hover).
