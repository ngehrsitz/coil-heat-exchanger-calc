"""Input form: operating condition fields with unit dropdowns and axis selector."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from physics.axis_model import (
    AXIS_DISPLAY_UNITS,
    AXIS_LABEL,
    display_bounds,
    from_si,
    kind_of,
    temp_in_range,
    temp_range,
    to_si,
)
from ui.spinbox import AcceleratingDoubleSpinBox
from ui.validation import clear_invalid, mark_invalid

# Spinbox maximum used when physics reports no upper bound (display_bounds
# returns None). Large enough to never constrain a realistic input.
_UNBOUNDED_MAX = 99999.0


def _decimals_for_unit(unit: str) -> int:
    """Enough precision to avoid changing SI values when switching units."""
    return 6 if unit == "m³/s" else 3


class UnitSpinBox(QWidget):
    """A QDoubleSpinBox paired with a unit QComboBox.

    ``variable`` names the physical quantity (e.g. "air_temp_in"). The widget's
    hard limits come from ``physics.axis_model.display_bounds`` — a positive floor
    for flows, an absolute-zero floor for temperatures — re-applied when the
    unit changes. The narrower fluid-property envelope for temperatures is NOT
    clamped here; it is validated separately (InputForm.validate) so an
    out-of-envelope value can be entered and then flagged.
    """

    def __init__(
        self,
        units: list[str],
        variable: str,
        default_value: float = 0.0,
        parent=None,
    ):
        super().__init__(parent)
        self._variable = variable
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)

        self.combo = QComboBox()
        self.combo.setMinimumWidth(51)
        for u in units:
            self.combo.addItem(u)

        self.spin = AcceleratingDoubleSpinBox()
        self.spin.setDecimals(_decimals_for_unit(self.combo.currentText()))
        self.spin.setMinimumWidth(100)

        self._unit = self.combo.currentText()
        self._apply_bounds()
        self.spin.setValue(default_value)
        self.combo.currentIndexChanged.connect(self._on_unit_changed)

        row.addWidget(self.spin, 1)
        row.addWidget(self.combo)

    def _apply_bounds(self):
        """Set the spinbox min/max for the currently-selected unit."""
        lo, hi = display_bounds(self._variable, self.combo.currentText())
        self.spin.setMinimum(lo)
        self.spin.setMaximum(hi if hi is not None else _UNBOUNDED_MAX)

    def _on_unit_changed(self):
        """Preserve the physical SI value when the display unit changes."""
        new_unit = self.combo.currentText()
        old_unit = self._unit
        if new_unit == old_unit:
            return

        value_si = to_si(self._variable, self.spin.value(), old_unit)
        self._unit = new_unit
        self.spin.setDecimals(_decimals_for_unit(new_unit))
        self._apply_bounds()
        self.spin.setValue(from_si(self._variable, value_si, new_unit))

    @property
    def value(self) -> float:
        return self.spin.value()

    @property
    def unit(self) -> str:
        return self.combo.currentText()

    def set_unit(self, unit: str):
        idx = self.combo.findText(unit)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)


class RangeWidget(QWidget):
    """Min / Max pair of UnitSpinBoxes for axis sweep range."""

    def __init__(
        self,
        units: list[str],
        variable: str,
        default_min: float,
        default_max: float,
        parent=None,
    ):
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.min_box = UnitSpinBox(units, variable, default_min)
        self.max_box = UnitSpinBox(units, variable, default_max)
        layout.addRow("Min:", self.min_box)
        layout.addRow("Max:", self.max_box)

    def sync_unit(self, unit: str):
        self.min_box.set_unit(unit)
        self.max_box.set_unit(unit)


class InputForm(QGroupBox):
    """Operating condition inputs and axis variable selector."""

    inputChanged = pyqtSignal()

    # Default operating conditions
    _DEFAULTS = {
        "air_flow": (500.0, "m³/h", 50.0, 1000.0),
        "air_temp_in": (20.0, "°C", -10.0, 40.0),
        "water_temp_in": (60.0, "°C", 20.0, 90.0),
        "water_flow": (2.0, "L/min", 0.5, 20.0),
    }

    def __init__(self, parent=None):
        super().__init__("Operating Conditions", parent)
        self._axis_variable: str = "water_temp_in"
        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)

        # Axis variable selector
        axis_row = QHBoxLayout()
        axis_row.addWidget(QLabel("Graph:"))
        self._axis_combo = QComboBox()
        for var, label in AXIS_LABEL.items():
            self._axis_combo.addItem(label, userData=var)
        # Default to water_temp_in
        self._axis_combo.setCurrentIndex(list(AXIS_LABEL.keys()).index("water_temp_in"))
        self._axis_combo.currentIndexChanged.connect(self._on_axis_changed)
        axis_row.addWidget(self._axis_combo, 1)
        outer.addLayout(axis_row)

        # Range inputs (shown for axis variable only, directly below the combo)
        self._range_widgets: dict[str, RangeWidget] = {}
        for var, (_val, unit, lo, hi) in self._DEFAULTS.items():
            units_list = AXIS_DISPLAY_UNITS[var]
            rw = RangeWidget(units_list, var, lo, hi)
            rw.sync_unit(unit)
            rw.setVisible(False)
            self._range_widgets[var] = rw
            outer.addWidget(rw)

        # Fixed-value inputs
        form = QFormLayout()
        self._fixed_widgets: dict[str, UnitSpinBox] = {}
        self._fixed_rows: dict[str, int] = {}
        for var, (val, unit, _lo, _hi) in self._DEFAULTS.items():
            units_list = AXIS_DISPLAY_UNITS[var]
            w = UnitSpinBox(units_list, var, val)
            w.set_unit(unit)
            self._fixed_widgets[var] = w
            self._fixed_rows[var] = form.rowCount()
            form.addRow(AXIS_LABEL[var] + ":", w)

        # Inlet relative humidity — a fixed operating condition, never a sweep
        # axis, so it lives outside _fixed_widgets / the axis selector.
        self._rh_spin = AcceleratingDoubleSpinBox()
        self._rh_spin.setDecimals(1)
        self._rh_spin.setRange(0.0, 100.0)
        self._rh_spin.setValue(50.0)
        self._rh_spin.setSuffix(" %")
        self._rh_spin.setMinimumWidth(100)
        form.addRow("Inlet Relative Humidity:", self._rh_spin)

        self._form = form
        outer.addLayout(form)

        # Reflect the initial axis's row visibility / range unit without seeding
        # the range from the fixed value (that reseed is only for user switches).
        self._apply_axis_selection()

        self._axis_combo.currentIndexChanged.connect(self.inputChanged)
        for w in self._fixed_widgets.values():
            w.spin.valueChanged.connect(self.inputChanged)
            w.combo.currentIndexChanged.connect(self.inputChanged)
        self._rh_spin.valueChanged.connect(self.inputChanged)
        for rw in self._range_widgets.values():
            rw.min_box.spin.valueChanged.connect(self.inputChanged)
            rw.min_box.combo.currentIndexChanged.connect(self.inputChanged)
            rw.max_box.spin.valueChanged.connect(self.inputChanged)
            rw.max_box.combo.currentIndexChanged.connect(self.inputChanged)

    def _apply_axis_selection(self):
        """Show the selected axis variable's range widget (hiding its fixed row
        and the other range widgets) and sync the range unit to the fixed unit.
        Shared by construction and axis switches; does NOT touch range values."""
        var = self._axis_combo.currentData()
        self._axis_variable = var

        for v, _w in self._fixed_widgets.items():
            self._form.setRowVisible(self._fixed_rows[v], v != var)
        for v, rw in self._range_widgets.items():
            rw.setVisible(v == var)

        # Keep range unit in sync with fixed unit
        self._range_widgets[var].sync_unit(self._fixed_widgets[var].unit)

    def _on_axis_changed(self):
        self._apply_axis_selection()

        # Seed the sweep range from the value that was set while this variable was
        # a fixed input, so switching a variable to the axis preserves its value
        # (min == max; the user then widens the range).
        fixed = self._fixed_widgets[self._axis_variable]
        rw = self._range_widgets[self._axis_variable]
        rw.min_box.spin.setValue(fixed.value)
        rw.max_box.spin.setValue(fixed.value)

    def axis_variable(self) -> str:
        return self._axis_variable

    def inlet_rh_percent(self) -> float:
        """Inlet relative humidity in percent (0–100)."""
        return self._rh_spin.value()

    def axis_display_unit(self) -> str:
        return self._range_widgets[self._axis_variable].min_box.unit

    def fixed_values(self) -> dict[str, tuple[float, str]]:
        """Return {variable: (value, unit)} for all non-axis variables."""
        return {
            var: (w.value, w.unit)
            for var, w in self._fixed_widgets.items()
            if var != self._axis_variable
        }

    def axis_range(self) -> tuple[float, str, float, str]:
        """Return (min_value, min_unit, max_value, max_unit)."""
        rw = self._range_widgets[self._axis_variable]
        return (
            rw.min_box.value,
            rw.min_box.unit,
            rw.max_box.value,
            rw.max_box.unit,
        )

    def validate(self) -> list[str]:
        """Flag invalid inputs with a red outline and return the messages.

        Two kinds of check:
          * Temperatures outside the supported fluid-property envelope — these
            are typeable (the widget only floors at absolute zero), so they are
            flagged here rather than clamped. Applies to every visible fixed
            temperature field and, when the swept axis is a temperature, both
            sweep endpoints.
          * Zero-width sweep range (min equals max). An inverted range
            (min > max) is allowed — MainWindow swaps the endpoints.

        Positive-flow floors are enforced by the UnitSpinBox bounds, so no flow
        check is needed here.
        """
        errors: list[str] = []

        # --- Temperature envelope checks ---
        # Visible fixed temperature fields (the axis variable's fixed row is
        # hidden and swept via the range widget instead).
        for var, w in self._fixed_widgets.items():
            if var == self._axis_variable or kind_of(var) != "temperature":
                continue
            errors += self._check_temp_field(var, w)

        # Active sweep-range endpoints, if the axis variable is a temperature.
        rw = self._range_widgets[self._axis_variable]
        clear_invalid(rw.min_box.spin)
        clear_invalid(rw.max_box.spin)
        if kind_of(self._axis_variable) == "temperature":
            errors += self._check_temp_field(self._axis_variable, rw.min_box, "Min ")
            errors += self._check_temp_field(self._axis_variable, rw.max_box, "Max ")

        # --- Zero-width sweep range ---
        var = self._axis_variable
        min_si = to_si(var, rw.min_box.value, rw.min_box.unit)
        max_si = to_si(var, rw.max_box.value, rw.max_box.unit)
        if min_si == max_si:
            mark_invalid(rw.min_box.spin)
            mark_invalid(rw.max_box.spin)
            errors.append(f"{AXIS_LABEL[var]} sweep range is zero-width (min equals max).")
        return errors

    def _check_temp_field(self, var: str, box: UnitSpinBox, prefix: str = "") -> list[str]:
        """Outline ``box`` red and return a message if its temperature is outside
        the fluid-property envelope. ``prefix`` labels a Min/Max sweep endpoint."""
        clear_invalid(box.spin)
        value_si = to_si(var, box.value, box.unit)
        if temp_in_range(var, value_si):
            return []
        mark_invalid(box.spin)
        lo, hi = temp_range(var, box.unit)
        return [f"{prefix}{AXIS_LABEL[var]} must be between {lo:.1f} and {hi:.1f} {box.unit}."]
