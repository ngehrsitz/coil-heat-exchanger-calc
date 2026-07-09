# coil-heat-exchanger-calc — Thermal Performance Calculator

A desktop application for calculating and visualizing the heating and cooling performance of a fin-and-tube water-to-air heat exchanger (register). Given operating conditions, it plots **thermal power [kW]**, **air outlet temperature [°C]**, **water return temperature [°C]**, and **outlet relative humidity [%]** as a function of any one input variable you choose. In cooling mode it models condensation (dehumidification) when the coil surface falls below the air's dew point.

---

## Downloads

Prebuilt standalone executables for **Windows** and **Linux** are produced
automatically on every push and pull request — no Python or `uv` installation
required to run them.

- **Latest builds**: go to the [**Actions** tab](../../actions/workflows/build.yml),
  open the most recent *Build* run, and download the
  `coil-heat-exchanger-calc-Windows` or `coil-heat-exchanger-calc-Linux`
  artifact. (Artifacts are retained for 30 days.)
- **Tagged releases**: pushing a version tag (`vX.Y.Z`) publishes the same
  executables as assets on the corresponding [GitHub Release](../../releases).

The executables are built with PyInstaller (`--onefile`), so each is a single
self-contained binary.

---

## Installation

Requires Python 3.13 or later and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                  # create the virtual environment and install locked dependencies
uv run python main.py    # launch the app
```

### Development

```bash
uv run pytest                        # run the test suite
uv run ruff check .                  # lint
uv run ruff format .                 # auto-format (use --check in CI)
uv run mypy                          # type-check the physics + sweep core
```

Dependencies, tool configuration, and the pinned dependency graph live in
`pyproject.toml` and `uv.lock`. CI (`.github/workflows/ci.yml`) runs the lint,
format, type-check, and test gates on every push and pull request, while
`.github/workflows/build.yml` packages the standalone Windows and Linux
executables (see [Downloads](#downloads) above).

---

## Quick start

1. The app opens with **Water Inlet Temperature** on the X-axis and sensible defaults pre-filled.
2. Click **Calculate** to generate the performance curves immediately.
3. Hover over the chart to read exact values at any point.

---

## The interface

The window is divided into a **left panel** (inputs) and a **right panel** (chart).

### Operating Conditions

| Field | Default | Available units |
|---|---|---|
| X-axis variable | Water Inlet Temperature | — (dropdown) |
| Air Volume Flow | 500 m³/h | m³/h, m³/s, L/s, CFM |
| Air Inlet Temperature | 20 °C | °C, K, °F |
| Water Inlet Temperature | 60 °C | °C, K, °F |
| Water Volume Flow | 2 L/min | L/min, L/s, m³/h, m³/s |
| Inlet Relative Humidity | 50 % | % |

**Inlet Relative Humidity** is a fixed operating condition (it cannot be chosen as the X-axis variable). It sets the moisture content of the incoming air, which determines both the dew point (and therefore whether condensation occurs during cooling) and the outlet relative humidity shown on the chart. When *Air Inlet Temperature* is the swept X-axis variable, the absolute humidity is held constant across the sweep (the physically correct choice), so the effective relative humidity varies along it.

**Choosing the X-axis variable**

Select any of the four operating conditions from the *X-axis variable* dropdown. That field's fixed input is replaced by **Min** and **Max** range inputs. The three remaining sweepable parameters, plus inlet relative humidity, stay as fixed values. Click **Calculate** to sweep the chosen variable across at least 100 evenly-spaced points (more for a wide range) and update the chart.

Example — to see how power varies with water flow:
- Set *X-axis variable* → **Water Volume Flow**
- Set *Min* = 0.5 L/min, *Max* = 20 L/min
- Set fixed *Water Inlet Temperature* = 60 °C, *Air Inlet Temperature* = 20 °C, *Air Volume Flow* = 500 m³/h
- Click **Calculate**

### Register Geometry

Click the **Register Geometry** checkbox to expand the geometry panel. Modify these to evaluate a different coil geometry.

| Parameter | Default | Notes |
|---|---|---|
| Rows | 6 | Number of tube rows in the airflow direction |
| Tubes per row | 10 | Tubes across the face (transverse) |
| Coil length | 300 mm | Fin height / coil width |
| Tube OD | 9.52 mm | Outer diameter, copper |
| Tube wall | 0.60 mm | Wall thickness |
| Fin pitch | 2.50 mm | Centre-to-centre fin spacing |
| Fin thickness | 0.10 mm | Aluminium fin material thickness |
| Fin conductivity | 205 W/m·K | Aluminium |
| Row pitch | 22.0 mm | Centre-to-centre spacing in depth direction |
| Hole pitch | 25.4 mm | Centre-to-centre spacing transverse |
| Tube conductivity | 385 W/m·K | Copper |

### Calculate button

Runs the sweep and updates the chart. Disabled during calculation. If any individual points in the sweep fail (e.g. flow rate too low for the correlation range), those points are shown as gaps in the curve rather than aborting the whole calculation. A summary below the button shows the number of valid points and the midpoint result (power, air outlet temperature, water return temperature, and outlet relative humidity), flagged **(condensing)** when the midpoint is dehumidifying.

Enable **Auto-recalculate** to rerun the sweep automatically whenever a valid input changes.

---

## The chart

- **Left Y-axis (red)** — Thermal power in kW. Positive values mean the register heats the air; negative values mean it cools the air.
- **Inner right Y-axis (blue/purple)** — Outlet air temperature in °C (blue solid line) and water return temperature in °C (purple dashed line). Both temperatures share this scale.
- **Outer right Y-axis (green)** — Outlet relative humidity in % (dashed line). It has its own scale, separate from the temperature axis, so the two curves never share a range.
- **X-axis** — The swept variable, in whichever unit you selected.
- **Hover** — Move the mouse over the chart to see a crosshair and a tooltip showing the exact X value, power, air outlet temperature, water return temperature, and outlet relative humidity at the nearest point.
- The chart auto-scales all axes after each calculation. Use the mouse scroll wheel to zoom and drag to pan (standard pyqtgraph interactions).

---

## Interpreting results

**Heating mode** (water hotter than air): thermal power is positive, outlet air temperature is above inlet. No condensation — the outlet relative humidity falls because the same moisture is carried by warmer air.

**Cooling mode** (water cooler than air): thermal power is negative (heat removed from air), outlet air temperature is below inlet.

**Dehumidification (wet coil):** when cooling drives the coil surface below the incoming air's dew point, moisture condenses out. The outlet relative humidity rises toward 100%, the outlet air carries less water than the inlet, and the total cooling power now includes a **latent** component (the heat released by condensing water) on top of the **sensible** component (the temperature drop). The dry→wet transition along a sweep is continuous; near onset only the coldest part of the coil condenses.

**Typical nominal result** (500 m³/h air at 20 °C / 50 % RH, 60 °C water at 2 L/min, default geometry):
- ~2.3 kW heating power
- Air outlet ~34 °C, water return ~43 °C, outlet relative humidity ~22 % (dry coil — heating)
- Effectiveness ~0.42

**Effect of each variable:**
- *Higher water inlet temperature* → more power, higher air outlet temperature (linear relationship)
- *Higher water flow rate* → more power, but with diminishing returns (water-side resistance decreases but air-side becomes limiting)
- *Higher air flow rate* → more power (higher mass flow), but lower air outlet temperature (less time in the coil)
- *Higher air inlet temperature* → less heating power (smaller driving temperature difference)
- *Higher inlet relative humidity* → higher dew point, so condensation begins at a warmer coil surface; once wet, more latent load and greater total cooling power

---

## Calculation method

The app uses the **ε-NTU method** for a crossflow heat exchanger with both fluids unmixed, which is the standard approach for fin-and-tube coils:

- **Air-side heat transfer**: Colburn j-factor correlation (Rich / McQuiston for corrugated fins)
- **Water-side heat transfer**: Gnielinski correlation for turbulent internal tube flow
- **Fin efficiency**: Schmidt (1945-46) equivalent-radius approximation
- **Fluid properties**: CoolProp (water); CoolProp HumidAir backend (moist air)
- **Condensation (wet coil)**: enthalpy-potential (Threlkeld) method — when the coil surface falls below the inlet-air dew point, the driving potential switches from a temperature difference to an enthalpy difference (bulk air vs. saturated air at the water temperature), capturing combined sensible + latent transfer and moisture removal. The wet-coil results are validated against published worked examples (Purdue ME 418; Mitchell & Braun, *HVAC in Buildings* 2013, Example 13.3).

All calculations are performed at the inlet temperature of each fluid. Property variation along the coil depth is not modelled.

---

## Limitations

- **The results have not been validated against another simulation software; calculated outputs should be treated as indicative engineering estimates.**
- Valid air-side Reynolds number range: ~300–20 000 (face velocities ~0.3–4 m/s for this coil). Points outside this range may be inaccurate or return errors.
- Water-side correlation is most accurate for turbulent flow (Re > 3 000, i.e. water flow > ~0.3 L/min for this tube diameter). At very low water flows the laminar approximation is used.
- The wet-coil (condensation) model is an effectiveness-based approximation: the total cooling power and outlet temperatures are reliable, but the **condensate rate and outlet humidity are indicative rather than certified** — they depend on the apparatus-dew-point recovery, which differs somewhat from a detailed row-by-row coil integration. Treat outlet-RH magnitudes in cooling mode as approximate.
- Atmospheric pressure is assumed (101 325 Pa) for all moist-air properties.
