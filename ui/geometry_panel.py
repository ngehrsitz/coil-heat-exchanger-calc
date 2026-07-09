"""Collapsible register geometry editor with spec defaults."""

from __future__ import annotations

from functools import partial
from typing import NamedTuple

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

from physics.geometry import RegisterGeometry
from physics.units import from_meter, to_meter
from ui.spinbox import AcceleratingDoubleSpinBox, AcceleratingSpinBox
from ui.validation import clear_invalid, mark_invalid

# (name, conductivity [W/m·K] or None for a custom entry). The display label is
# generated from the value so the number lives in exactly one place.
_TUBE_MATERIALS: list[tuple[str, float | None]] = [
    ("Copper", 385.0),
    ("Stainless steel 304", 16.0),
    ("Aluminium", 205.0),
    ("Custom…", None),
]

_FIN_MATERIALS: list[tuple[str, float | None]] = [
    ("Aluminium", 205.0),
    ("Copper", 385.0),
    ("Stainless steel 304", 16.0),
    ("Custom…", None),
]


def _material_label(name: str, cond: float | None) -> str:
    """Combo-box label for a material, e.g. ``"Copper (385 W/m·K)"``."""
    return name if cond is None else f"{name} ({cond:g} W/m·K)"


# Entry-widget display ranges for each geometry field. ``mm`` marks a length
# stored in metres but shown/edited in millimetres; ``dec`` is the spinbox
# precision. Integer-valued fields (rows, tubes) carry dec=None. Keeping the
# limits here (rather than inline at construction) puts every anonymous bound in
# one table and lets geometry() iterate the same field set.
class _Range(NamedTuple):
    lo: float
    hi: float
    dec: int | None  # None → integer spinbox
    mm: bool  # True → value is a length displayed in mm


_GEOM_RANGES: dict[str, _Range] = {
    "rows": _Range(1, 20, None, False),
    "tubes_per_row": _Range(1, 50, None, False),
    "coil_length": _Range(50, 2000, 1, True),
    "tube_od": _Range(3, 50, 2, True),
    "tube_wall": _Range(0.1, 5, 2, True),
    "fin_pitch": _Range(1, 10, 2, True),
    "fin_thickness": _Range(0.05, 0.5, 3, True),
    "fin_conductivity": _Range(1, 1000, 1, False),
    "row_pitch": _Range(5, 100, 2, True),
    "hole_pitch": _Range(5, 100, 2, True),
    "tube_conductivity": _Range(1, 1000, 1, False),
}


class GeometryPanel(QGroupBox):
    """Editable register geometry for a fin-and-tube coil."""

    inputChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Register Geometry", parent)
        self.setCheckable(True)
        self.setChecked(False)  # collapsed by default
        self._setup_ui()
        self.toggled.connect(self._on_toggle)
        self._content.setVisible(False)

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        self._content = QWidget()
        form = QFormLayout(self._content)

        def ispin(val: int, lo: int, hi: int) -> AcceleratingSpinBox:
            s = AcceleratingSpinBox()
            s.setRange(lo, hi)
            s.setValue(val)
            return s

        def dspin(val: float, lo: float, hi: float, dec: int = 3) -> AcceleratingDoubleSpinBox:
            s = AcceleratingDoubleSpinBox()
            s.setDecimals(dec)
            s.setRange(lo, hi)
            s.setValue(val)
            return s

        def spin_for(field: str) -> AcceleratingSpinBox | AcceleratingDoubleSpinBox:
            """Build the entry widget for a geometry field from ``_GEOM_RANGES``.

            Length fields (``mm``) are stored in metres on ``RegisterGeometry``
            but shown in millimetres; integer fields (``dec is None``) use an
            integer spinbox. Each widget is registered in ``self._geom_spins`` so
            ``geometry()`` can read every field back without hand-listing them.
            """
            r = _GEOM_RANGES[field]
            raw = getattr(g, field)
            value = from_meter(raw, "mm") if r.mm else raw
            if r.dec is None:
                spin: AcceleratingSpinBox | AcceleratingDoubleSpinBox = ispin(
                    int(value), int(r.lo), int(r.hi)
                )
            else:
                spin = dspin(value, r.lo, r.hi, r.dec)
            self._geom_spins[field] = spin
            return spin

        g = RegisterGeometry()
        self._geom_spins: dict[str, AcceleratingSpinBox | AcceleratingDoubleSpinBox] = {}
        self._rows = spin_for("rows")
        self._tubes_per_row = spin_for("tubes_per_row")
        self._coil_length = spin_for("coil_length")
        self._tube_od = spin_for("tube_od")
        self._tube_wall = spin_for("tube_wall")
        self._fin_pitch = spin_for("fin_pitch")
        self._fin_thickness = spin_for("fin_thickness")
        self._fin_mat = QComboBox()
        for name, cond in _FIN_MATERIALS:
            self._fin_mat.addItem(_material_label(name, cond))
        self._fin_cond = spin_for("fin_conductivity")
        self._row_pitch = spin_for("row_pitch")
        self._hole_pitch = spin_for("hole_pitch")

        self._tube_mat = QComboBox()
        for name, cond in _TUBE_MATERIALS:
            self._tube_mat.addItem(_material_label(name, cond))
        self._tube_cond = spin_for("tube_conductivity")

        form.addRow("Rows:", self._rows)
        form.addRow("Tubes per row:", self._tubes_per_row)
        form.addRow("Coil length [mm]:", self._coil_length)
        form.addRow("Tube OD [mm]:", self._tube_od)
        form.addRow("Tube wall [mm]:", self._tube_wall)
        form.addRow("Fin pitch [mm]:", self._fin_pitch)
        form.addRow("Fin thickness [mm]:", self._fin_thickness)
        form.addRow("Fin material:", self._fin_mat)
        form.addRow("  conductivity [W/m·K]:", self._fin_cond)
        form.addRow("Row pitch [mm]:", self._row_pitch)
        form.addRow("Hole pitch [mm]:", self._hole_pitch)
        form.addRow("Tube material:", self._tube_mat)
        form.addRow("  conductivity [W/m·K]:", self._tube_cond)

        # Connect after both widgets are in the layout; index 0 (Copper) is already
        # selected so manually hide the spinbox for the initial named-material state.
        self._tube_mat.currentIndexChanged.connect(
            partial(self._on_mat_changed, materials=_TUBE_MATERIALS, cond_spin=self._tube_cond)
        )
        self._tube_cond.setVisible(False)
        form.labelForField(self._tube_cond).setVisible(False)

        self._fin_mat.currentIndexChanged.connect(
            partial(self._on_mat_changed, materials=_FIN_MATERIALS, cond_spin=self._fin_cond)
        )
        self._fin_cond.setVisible(False)
        form.labelForField(self._fin_cond).setVisible(False)

        outer.addWidget(self._content)

        for widget in (
            self._rows,
            self._tubes_per_row,
            self._coil_length,
            self._tube_od,
            self._tube_wall,
            self._fin_pitch,
            self._fin_thickness,
            self._fin_cond,
            self._row_pitch,
            self._hole_pitch,
            self._tube_cond,
        ):
            widget.valueChanged.connect(self.inputChanged)
        self._fin_mat.currentIndexChanged.connect(self.inputChanged)
        self._tube_mat.currentIndexChanged.connect(self.inputChanged)

    def _on_toggle(self, checked: bool):
        self._content.setVisible(checked)

    def _on_mat_changed(
        self,
        idx: int,
        materials: list[tuple[str, float | None]],
        cond_spin: AcceleratingDoubleSpinBox,
    ) -> None:
        """Show the conductivity spinbox for "Custom…", else set it from the material."""
        _, value = materials[idx]
        is_custom = value is None
        cond_spin.setVisible(is_custom)
        label_widget = cond_spin.parentWidget().layout().labelForField(cond_spin)
        if label_widget:  # pragma: no cover - labelForField always returns the paired label here
            label_widget.setVisible(is_custom)
        if not is_custom:
            cond_spin.setValue(value)
        else:
            cond_spin.setFocus()

    def geometry(self) -> RegisterGeometry:
        # Read each field from its registered spinbox, converting length fields
        # (marked ``mm`` in _GEOM_RANGES) from millimetres back to metres. Driving
        # this from the same table as construction keeps the 11 fields in one place.
        values: dict[str, float] = {}
        for field, spin in self._geom_spins.items():
            raw = spin.value()
            values[field] = to_meter(raw, "mm") if _GEOM_RANGES[field].mm else raw
        return RegisterGeometry(**values)

    def validate(self) -> list[str]:
        """Flag inconsistent geometry with a red outline and return the messages.

        The rules themselves live on ``RegisterGeometry.validate`` (physics);
        this method only maps the reported fields back to their entry widgets
        and applies the outline.
        """
        # Fields RegisterGeometry.validate may report → their entry widgets.
        field_widgets = {
            "tube_wall": self._tube_wall,
            "tube_od": self._tube_od,
            "fin_thickness": self._fin_thickness,
            "row_pitch": self._row_pitch,
            "hole_pitch": self._hole_pitch,
        }
        for w in field_widgets.values():
            clear_invalid(w)

        errors: list[str] = []
        for field, message in self.geometry().validate():
            widget = field_widgets.get(field)
            if widget is not None:  # pragma: no cover - validate() only reports mapped fields
                mark_invalid(widget)
            errors.append(message)
        return errors
