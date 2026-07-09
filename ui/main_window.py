"""Main window — wires the input form, geometry panel, and chart together."""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from physics.axis_model import from_si, to_si
from physics.calculator import FixedInputs, PhysicsError
from physics.errors import humanize_error
from physics.geometry import RegisterGeometry
from sweep.sweep import (
    AxisSpec,
    AxisVariable,
    axis_midpoint_si,
    default_steps,
    resolve_humidity,
    run_sweep,
)
from ui import palette
from ui.chart_widget import ChartWidget
from ui.geometry_panel import GeometryPanel
from ui.input_form import InputForm

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level window: input form + geometry panel on the left, chart on the right."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("coil-heat-exchanger-calc — Thermal Performance Calculator")
        self.resize(1100, 700)
        self._setup_ui()

    def _setup_ui(self):
        # Red outline for widgets flagged invalid via the "invalid" dynamic property.
        self.setStyleSheet(
            'QDoubleSpinBox[invalid="true"], QSpinBox[invalid="true"] { border: 1px solid red; }'
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # --- Left panel ---
        left = QWidget()
        left.setMinimumWidth(260)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)

        self._input_form = InputForm()
        left_layout.addWidget(self._input_form)

        self._geom_panel = GeometryPanel()
        left_layout.addWidget(self._geom_panel)

        self._calc_btn = QPushButton("Calculate")
        self._calc_btn.setMinimumHeight(36)
        self._calc_btn.clicked.connect(self._on_calculate)
        left_layout.addWidget(self._calc_btn)

        self._auto_calc_cb = QCheckBox("Auto-recalculate")
        left_layout.addWidget(self._auto_calc_cb)

        self._calc_running = False
        self._input_form.inputChanged.connect(self._on_input_changed)
        self._geom_panel.inputChanged.connect(self._on_input_changed)

        left_layout.addStretch()

        # Status line showing last result summary
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        left_layout.addWidget(self._status_label)

        splitter.addWidget(left)

        # --- Right panel: chart ---
        self._chart = ChartWidget()
        splitter.addWidget(self._chart)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 780])

        self.setStatusBar(QStatusBar())

        # Reflect the initial (valid) defaults in the button state.
        self._on_input_changed()

    def _show_errors(self, errors: list[str]) -> None:
        """Render validation/error messages in the status label (red)."""
        self._status_label.setText(
            f"<span style='color:{palette.ERROR}'>" + "<br>".join(errors) + "</span>"
        )

    def _on_input_changed(self):
        """Validate all inputs; disable Calculate and show errors while invalid."""
        errors = self._input_form.validate() + self._geom_panel.validate()
        valid = not errors

        if not self._calc_running:
            self._calc_btn.setEnabled(valid)

        if errors:
            self._show_errors(errors)
        elif self._auto_calc_cb.isChecked() and not self._calc_running:
            self._on_calculate()
        else:
            self._status_label.setText("")

    def _on_calculate(self):
        """Run the sweep, disabling the button and reporting errors to the status line."""
        # Guard against Enter-key / auto-recalc paths that bypass the disabled button.
        errors = self._input_form.validate() + self._geom_panel.validate()
        if errors:
            self._show_errors(errors)
            return

        self._calc_running = True
        self._calc_btn.setEnabled(False)
        self.statusBar().showMessage("Calculating…")
        # Paint the "Calculating…" message and disabled-button state before the
        # (synchronous) sweep blocks the event loop; otherwise neither renders.
        QApplication.processEvents()
        try:
            self._run_calculation()
        except Exception as exc:  # pragma: no cover - defensive UI net; no achievable
            # form/geometry state makes the physics layer raise (spinbox minimums
            # clamp inputs and the sweep degrades gracefully to NaN points), so this
            # handler cannot be reached without mocking. Kept to keep the UI alive if
            # a future input path ever does raise.
            logger.exception("Calculation failed")
            message = humanize_error(exc)
            self.statusBar().showMessage(f"Error: {message}")
            self._status_label.setText(f"<span style='color:{palette.ERROR}'>{message}</span>")
            self._calc_btn.setEnabled(True)
        finally:
            self._calc_running = False

    def _run_calculation(self):
        """Convert the form inputs to SI (the input boundary), build an
        ``AxisSpec`` with at least one step per integer display unit, run the
        sweep, and push the result to the chart + status line."""
        form = self._input_form
        # AxisVariable is a str-enum, so `axis_var` doubles as the canonical
        # string key for the physics.units metadata dicts — no separate string.
        axis_var = AxisVariable(form.axis_variable())

        # Build fixed inputs — convert each value to SI
        fixed_values = form.fixed_values()
        kwargs: dict = {}
        for var, (val, unit) in fixed_values.items():
            kwargs[var] = to_si(var, val, unit)

        # Set axis variable to a placeholder (will be overridden by sweep)
        axis_min_val, axis_min_unit, axis_max_val, axis_max_unit = form.axis_range()
        axis_min_si = to_si(axis_var, axis_min_val, axis_min_unit)
        axis_max_si = to_si(axis_var, axis_max_val, axis_max_unit)
        display_unit = form.axis_display_unit()
        axis_min_display = from_si(axis_var, axis_min_si, display_unit)
        axis_max_display = from_si(axis_var, axis_max_si, display_unit)

        # Provide a placeholder value for the swept variable in FixedInputs (the
        # sweep overrides it per point). The seeding rule lives in the sweep layer.
        kwargs[axis_var.value] = axis_midpoint_si(axis_min_si, axis_max_si)

        # Inlet RH% → humidity ratio W, evaluated at the (fixed or midpoint)
        # inlet air temperature. The sweep layer owns this modelling choice
        # (hold W constant, so RH varies along the sweep). This is resolved once,
        # up front; unlike the per-point sweep calls it is not inside run_sweep's
        # NaN net, so a moist-air property failure is surfaced as a clean error.
        rh_frac = form.inlet_rh_percent() / 100.0
        try:
            kwargs["humidity_ratio"] = resolve_humidity(kwargs["air_temp_in"], rh_frac)
        except PhysicsError as exc:
            self._show_errors([humanize_error(exc)])
            self.statusBar().showMessage("Error: invalid inlet humidity.")
            return

        fixed = FixedInputs(**kwargs)
        geom: RegisterGeometry = self._geom_panel.geometry()

        axis = AxisSpec(
            variable=axis_var,
            min_si=min(axis_min_si, axis_max_si),
            max_si=max(axis_min_si, axis_max_si),
            steps=default_steps(axis_min_display, axis_max_display),
        )

        points = run_sweep(fixed, geom, axis)

        valid = [p for p in points if p.error == ""]
        n_err = len(points) - len(valid)

        if not valid:  # pragma: no cover - unreachable: the sweep returns graceful
            # NaN points rather than raising, and no achievable input makes all 100
            # points fail, so `valid` is never empty. Defensive against a future
            # regime where every point errors.
            raise PhysicsError("No valid calculation points in the given range.")

        self._chart.update_chart(points, axis_var, display_unit)

        # Summary of midpoint result
        mid = valid[len(valid) // 2]
        wet_note = f" <span style='color:{palette.RH}'>(condensing)</span>" if mid.is_wet else ""

        # Correlation-extrapolation warning: flag if any point strayed outside
        # the documented validity range of the air- or water-side correlation.
        # The range decision is made in the sweep layer (per-point flags); the UI
        # only presents it.
        extrap: list[str] = []
        if any(p.air_extrapolated for p in valid):
            extrap.append("air-side Re out of range")
        if any(p.water_extrapolated for p in valid):
            extrap.append("water-side Re out of range")
        extrap_note = (
            f"<br><span style='color:{palette.WARNING}'>⚠ {'; '.join(extrap)} "
            "(correlation extrapolated)</span>"
            if extrap
            else ""
        )

        msg = (
            f"<b>{len(valid)}</b> points calculated"
            + (f" (<span style='color:{palette.WARNING}'>{n_err} failed</span>)" if n_err else "")
            + f"<br>Midpoint: <b>{mid.power_kw:.2f} kW</b>"
            + f"<br>T_air_out = <b>{mid.air_temp_out_c:.1f} °C</b>"
            + f"<br>T_water_out = <b>{mid.water_temp_out_c:.1f} °C</b>"
            + f"<br>RH_out = <b>{mid.air_rh_out_pct:.0f} %</b>{wet_note}"
            + extrap_note
        )
        self._status_label.setText(msg)
        self.statusBar().showMessage("Done.")
