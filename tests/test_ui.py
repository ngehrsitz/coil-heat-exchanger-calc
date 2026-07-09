"""Headless UI-logic tests.

These run under Qt's ``offscreen`` platform plugin (no display needed) and
exercise the widgets' getters, validation, and pure conversion helpers — not
their pixels. The platform is set programmatically so a plain ``uv run pytest``
works without the caller exporting ``QT_QPA_PLATFORM``.
"""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication, QDoubleSpinBox

from physics.calculator import PhysicsError
from physics.units import from_kelvin, from_m3s, to_kelvin, to_m3s
from sweep.sweep import DataPoint
from ui.chart_widget import ChartWidget
from ui.geometry_panel import _FIN_MATERIALS, _TUBE_MATERIALS, GeometryPanel
from ui.input_form import InputForm
from ui.main_window import MainWindow
from ui.spinbox import AcceleratingDoubleSpinBox, AcceleratingSpinBox
from ui.validation import clear_invalid, mark_invalid


@pytest.fixture(scope="session")
def qapp():
    """One shared QApplication for the whole test session."""
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# ui/validation.py
# ---------------------------------------------------------------------------


def test_mark_and_clear_invalid(qapp):
    box = QDoubleSpinBox()
    assert not box.property("invalid")

    mark_invalid(box)
    assert box.property("invalid") is True

    clear_invalid(box)
    assert box.property("invalid") is False


def test_mark_invalid_is_idempotent(qapp):
    # Second call with the same state hits the early-return no-op branch.
    box = QDoubleSpinBox()
    mark_invalid(box)
    mark_invalid(box)  # no-op — property already True
    assert box.property("invalid") is True


# ---------------------------------------------------------------------------
# ui/input_form.py
# ---------------------------------------------------------------------------


def test_input_form_getters(qapp):
    form = InputForm()
    assert form.axis_variable() == "water_temp_in"
    assert form.inlet_rh_percent() == 50.0
    assert form.axis_display_unit() == "°C"

    fixed = form.fixed_values()
    # The swept axis variable is excluded from the fixed values.
    assert "water_temp_in" not in fixed
    assert set(fixed) == {"air_flow", "air_temp_in", "water_flow"}
    for _var, (value, unit) in fixed.items():
        assert isinstance(value, float)
        assert isinstance(unit, str)

    lo_val, lo_unit, hi_val, hi_unit = form.axis_range()
    assert lo_val == 20.0 and hi_val == 90.0
    assert lo_unit == "°C" and hi_unit == "°C"


def test_unit_spinbox_set_unit(qapp):
    form = InputForm()
    box = form._fixed_widgets["air_flow"]
    assert box.unit == "m³/h"
    box.set_unit("L/s")  # re-applies bounds for the new unit
    assert box.unit == "L/s"
    box.set_unit("nonexistent")  # findText < 0 → no change
    assert box.unit == "L/s"
    box._on_unit_changed()  # no-op when the combo's unit has not changed
    assert box.unit == "L/s"


def test_unit_spinbox_set_unit_preserves_physical_flow(qapp):
    form = InputForm()
    box = form._fixed_widgets["air_flow"]
    initial_si = to_m3s(box.value, box.unit)
    box.set_unit("m³/s")
    assert abs(to_m3s(box.value, box.unit) - initial_si) < 1e-6
    assert abs(box.value - initial_si) < 1e-6


def test_unit_spinbox_set_unit_preserves_physical_temperature(qapp):
    form = InputForm()
    box = form._fixed_widgets["air_temp_in"]
    initial_si = to_kelvin(box.value, box.unit)
    box.set_unit("K")
    assert abs(to_kelvin(box.value, box.unit) - initial_si) < 1e-9
    assert abs(box.value - initial_si) < 1e-6


def test_range_sync_unit_preserves_physical_range(qapp):
    form = InputForm()
    rw = form._range_widgets["water_temp_in"]
    min_si = to_kelvin(rw.min_box.value, rw.min_box.unit)
    max_si = to_kelvin(rw.max_box.value, rw.max_box.unit)
    rw.sync_unit("K")
    assert abs(to_kelvin(rw.min_box.value, rw.min_box.unit) - min_si) < 1e-9
    assert abs(to_kelvin(rw.max_box.value, rw.max_box.unit) - max_si) < 1e-9


def test_input_form_axis_change_to_flow(qapp):
    form = InputForm()
    idx = form._axis_combo.findData("air_flow")
    form._axis_combo.setCurrentIndex(idx)
    assert form.axis_variable() == "air_flow"
    # Switching to the axis seeds Min == Max from the fixed value, so the range
    # is now zero-width (validation flags it until the user widens it).
    assert any("zero-width" in e for e in form.validate())
    # The flow range widget is now the active one (not explicitly hidden).
    # isVisible() would need a shown top-level window; isHidden() reflects the
    # widget's own requested state offscreen.
    assert not form._range_widgets["air_flow"].isHidden()


def test_input_form_axis_switch_seeds_range_from_fixed_value(qapp):
    """Switching a variable to the graph axis carries its fixed value into both
    Min and Max, so the value set while it was fixed is not lost. The initial
    axis keeps its default range (construction does not reseed)."""
    form = InputForm()
    # Startup axis (water_temp_in) retains its default 20–90 range, not 60/60.
    lo_val, _lo_unit, hi_val, _hi_unit = form.axis_range()
    assert lo_val == 20.0 and hi_val == 90.0

    # Set a distinctive fixed value, then make that variable the axis.
    form._fixed_widgets["air_temp_in"].spin.setValue(33.0)
    idx = form._axis_combo.findData("air_temp_in")
    form._axis_combo.setCurrentIndex(idx)

    rw = form._range_widgets["air_temp_in"]
    assert rw.min_box.value == 33.0
    assert rw.max_box.value == 33.0
    # Switching away leaves the fixed field untouched.
    form._axis_combo.setCurrentIndex(form._axis_combo.findData("water_flow"))
    assert form._fixed_widgets["air_temp_in"].value == 33.0


def test_input_form_validate_default_ok(qapp):
    form = InputForm()
    assert form.validate() == []


def test_input_form_validate_flags_out_of_envelope_temp(qapp):
    form = InputForm()
    # air_temp_in is a fixed field (the axis is water_temp_in), so it is checked.
    # Push it far above the fluid envelope.
    form._fixed_widgets["air_temp_in"].spin.setValue(500.0)
    errors = form.validate()
    assert any("Air Inlet Temperature" in e for e in errors)
    assert form._fixed_widgets["air_temp_in"].spin.property("invalid") is True


def test_input_form_validate_zero_width_range(qapp):
    form = InputForm()
    rw = form._range_widgets["water_temp_in"]
    rw.min_box.spin.setValue(50.0)
    rw.max_box.spin.setValue(50.0)
    errors = form.validate()
    assert any("zero-width" in e for e in errors)


# ---------------------------------------------------------------------------
# ui/geometry_panel.py
# ---------------------------------------------------------------------------


def test_geometry_panel_geometry_conversion(qapp):
    panel = GeometryPanel()
    geom = panel.geometry()
    # Spinboxes hold mm; geometry() converts to metres. Default coil is 300 mm.
    assert abs(geom.coil_length - 0.300) < 1e-6
    assert geom.rows == 6
    assert geom.tubes_per_row == 10


def test_geometry_panel_toggle(qapp):
    panel = GeometryPanel()
    panel._on_toggle(True)
    assert not panel._content.isHidden()
    panel._on_toggle(False)
    assert panel._content.isHidden()


def test_geometry_panel_tube_material_custom(qapp):
    panel = GeometryPanel()
    custom_idx = len(_TUBE_MATERIALS) - 1  # "Custom…" is last
    panel._tube_mat.setCurrentIndex(custom_idx)
    assert not panel._tube_cond.isHidden()

    # Switch back to a named material → hidden and its conductivity applied.
    panel._tube_mat.setCurrentIndex(0)
    assert panel._tube_cond.isHidden()
    assert panel._tube_cond.value() == _TUBE_MATERIALS[0][1]


def test_geometry_panel_fin_material_custom(qapp):
    panel = GeometryPanel()
    custom_idx = len(_FIN_MATERIALS) - 1
    panel._fin_mat.setCurrentIndex(custom_idx)
    assert not panel._fin_cond.isHidden()

    panel._fin_mat.setCurrentIndex(0)
    assert panel._fin_cond.isHidden()
    assert panel._fin_cond.value() == _FIN_MATERIALS[0][1]


def test_geometry_panel_validate_default_ok(qapp):
    panel = GeometryPanel()
    assert panel.validate() == []


def test_geometry_panel_validate_flags_bad_tube_wall(qapp):
    panel = GeometryPanel()
    # tube_wall ≥ tube_od / 2 makes the bore ≤ 0 — a reported inconsistency.
    od_mm = panel._tube_od.value()
    panel._tube_wall.setValue(od_mm)  # wall == OD, well over half
    errors = panel.validate()
    assert any("Tube wall" in e for e in errors)
    assert panel._tube_wall.property("invalid") is True


# ---------------------------------------------------------------------------
# ui/chart_widget.py
# ---------------------------------------------------------------------------


def test_chart_display_conversion_temperature(qapp):
    # update_chart converts the SI X values to the display unit; verify via the
    # public API (the stored _x_values) rather than a private helper.
    chart = ChartWidget()
    points = [
        DataPoint(x_si=293.15, power_kw=1.0, air_temp_out_c=25.0, air_rh_out_pct=40.0),
        DataPoint(x_si=333.15, power_kw=2.0, air_temp_out_c=30.0, air_rh_out_pct=35.0),
    ]
    chart.update_chart(points, "water_temp_in", "°C")
    assert abs(chart._x_values[0] - from_kelvin(293.15, "°C")) < 1e-9
    assert abs(chart._x_values[1] - from_kelvin(333.15, "°C")) < 1e-9


def test_chart_display_conversion_flow(qapp):
    chart = ChartWidget()
    points = [
        DataPoint(x_si=1.0, power_kw=1.0, air_temp_out_c=25.0, air_rh_out_pct=40.0),
        DataPoint(x_si=0.5, power_kw=2.0, air_temp_out_c=30.0, air_rh_out_pct=35.0),
    ]
    chart.update_chart(points, "air_flow", "m³/h")
    assert abs(chart._x_values[0] - from_m3s(1.0, "m³/h")) < 1e-6


def test_chart_update_chart_with_nan_point(qapp):
    chart = ChartWidget()
    points = [
        DataPoint(x_si=293.15, power_kw=1.0, air_temp_out_c=25.0, air_rh_out_pct=40.0),
        DataPoint(x_si=303.15, power_kw=2.0, air_temp_out_c=30.0, air_rh_out_pct=35.0),
        # A failed point comes through as NaN — the chart must tolerate it.
        DataPoint(
            x_si=313.15,
            power_kw=math.nan,
            air_temp_out_c=math.nan,
            error="boom",
        ),
    ]
    chart.update_chart(points, "water_temp_in", "°C")
    assert chart._x_values.size == 3


# ---------------------------------------------------------------------------
# ui/main_window.py — construction + full calculation path
# ---------------------------------------------------------------------------


def test_main_window_construction_and_calculation(qapp):
    win = MainWindow()
    # Defaults are valid, so Calculate is enabled after wiring.
    assert win._calc_btn.isEnabled()

    # Drive the full sweep → chart → status-line orchestration.
    win._on_calculate()
    text = win._status_label.text()
    assert "points calculated" in text
    assert "T_air_out" in text and "T_water_out" in text  # air/water named separately
    assert win._chart._x_values.size > 0


def test_main_window_input_changed_shows_errors_and_keeps_button_while_running(qapp):
    """The error branch of _on_input_changed shows red text; while a calculation
    is running the Calculate button state is left untouched (the running guard)."""
    win = MainWindow()
    # Push a fixed input out of the fluid envelope so validate() reports an error.
    win._input_form._fixed_widgets["air_temp_in"].spin.setValue(500.0)

    # Simulate "calculation in progress" so the button-enable line is skipped.
    win._calc_running = True
    win._calc_btn.setEnabled(False)
    win._on_input_changed()
    assert "color:red" in win._status_label.text()
    # The running guard means the button was not re-enabled by the invalid input.
    assert not win._calc_btn.isEnabled()
    win._calc_running = False


def test_main_window_input_changed_clears_stale_errors(qapp):
    win = MainWindow()
    field = win._input_form._fixed_widgets["air_temp_in"].spin

    field.setValue(500.0)
    win._on_input_changed()
    assert "color:red" in win._status_label.text()

    field.setValue(20.0)
    win._on_input_changed()
    assert win._status_label.text() == ""


def test_main_window_auto_recalculate(qapp):
    """With Auto-recalculate checked and valid inputs, an input change kicks off
    a calculation directly from _on_input_changed."""
    win = MainWindow()
    win._chart._x_values = win._chart._x_values[:0]  # ensure it starts empty-ish
    win._auto_calc_cb.setChecked(True)
    win._on_input_changed()  # valid defaults → auto branch runs _on_calculate
    assert "points calculated" in win._status_label.text()
    assert win._chart._x_values.size > 0


def test_main_window_calculate_guard_rejects_invalid(qapp):
    """_on_calculate bails out (red status, no chart update) when validation fails,
    guarding the Enter-key / auto-recalc paths that bypass the disabled button."""
    win = MainWindow()
    # Zero-width sweep range is a reported validation error.
    rw = win._input_form._range_widgets["water_temp_in"]
    rw.min_box.spin.setValue(50.0)
    rw.max_box.spin.setValue(50.0)
    win._on_calculate()
    assert "color:red" in win._status_label.text()
    assert "zero-width" in win._status_label.text()
    assert win._chart._x_values.size == 0  # chart never updated


def test_main_window_rejects_unresolvable_humidity(qapp, monkeypatch):
    """If the pre-sweep RH→W resolution fails (a moist-air property edge), the
    calculation surfaces a clean error and never reaches the sweep/chart — this is
    the path that used to escape run_sweep's NaN net and abort the whole run."""
    win = MainWindow()

    def _boom(_air_temp_in, _rh_frac):
        raise PhysicsError("simulated moist-air property failure")

    monkeypatch.setattr("ui.main_window.resolve_humidity", _boom)
    win._on_calculate()
    assert "color:red" in win._status_label.text()
    assert win._chart._x_values.size == 0  # chart never updated


def test_main_window_extrapolation_warning(qapp):
    """A very wide air-flow sweep pushes the air- and water-side Reynolds numbers
    outside the documented correlation ranges, so the status line carries the
    orange 'correlation extrapolated' warning (both Re branches)."""
    win = MainWindow()
    form = win._input_form
    idx = form._axis_combo.findData("air_flow")
    form._axis_combo.setCurrentIndex(idx)
    rw = form._range_widgets["air_flow"]
    rw.min_box.spin.setValue(rw.min_box.spin.minimum())
    rw.max_box.spin.setValue(rw.max_box.spin.maximum())
    win._on_calculate()
    text = win._status_label.text()
    assert "correlation extrapolated" in text
    assert "air-side Re" in text


def test_main_window_no_extrapolation_warning_in_range(qapp):
    """With a high fixed water flow every point's Reynolds number stays inside the
    documented ranges, so no extrapolation note is appended (the in-range arrows
    of both `any(...)` checks and the empty-`extrap` branch)."""
    win = MainWindow()
    fw = win._input_form._fixed_widgets["water_flow"]
    fw.spin.setValue(fw.spin.maximum())  # huge water flow → water Re well above 3000
    win._on_calculate()
    text = win._status_label.text()
    assert "points calculated" in text
    assert "correlation extrapolated" not in text


def test_main_window_mixed_range_units_use_display_span_for_steps(qapp):
    win = MainWindow()
    rw = win._input_form._range_widgets["water_temp_in"]
    rw.min_box.set_unit("°C")
    rw.min_box.spin.setValue(20.0)
    rw.max_box.set_unit("°F")
    rw.max_box.spin.setValue(122.0)
    win._on_calculate()
    # 20 °C to 122 °F is a 30 °C display span, so the 100-point floor wins.
    # The old raw-value path saw abs(122 - 20) and produced 103 points.
    assert win._chart._x_values.size == 100


# ---------------------------------------------------------------------------
# ui/chart_widget.py — resize + hover slots (driven directly, no live events)
# ---------------------------------------------------------------------------


def _chart_with_data(rh_present=True, water_present=True):
    chart = ChartWidget()
    chart.resize(600, 400)
    points = [
        DataPoint(
            x_si=293.15,
            power_kw=1.0,
            air_temp_out_c=25.0,
            water_temp_out_c=(45.0 if water_present else math.nan),
            air_rh_out_pct=(40.0 if rh_present else math.nan),
        ),
        DataPoint(
            x_si=303.15,
            power_kw=2.0,
            air_temp_out_c=30.0,
            water_temp_out_c=(50.0 if water_present else math.nan),
            air_rh_out_pct=(35.0 if rh_present else math.nan),
        ),
    ]
    chart.update_chart(points, "water_temp_in", "°C")
    return chart


def test_chart_update_views_runs(qapp):
    """The resize slot re-aligns the two auxiliary ViewBoxes; call it directly
    (the real sigResized only fires on a shown, resized window)."""
    chart = _chart_with_data()
    chart._update_views()  # must not raise; syncs _vb2/_vb3 geometry
    # The auxiliary viewboxes exist and were repositioned to a non-empty rect.
    assert chart._vb2.sceneBoundingRect().width() > 0
    assert chart._vb3.sceneBoundingRect().width() > 0


def test_chart_hover_empty_data_early_return(qapp):
    chart = ChartWidget()  # no data loaded → _x_values is empty
    chart._on_mouse_moved(QPointF(100.0, 100.0))
    assert chart._hover_label.text() == ""


def test_chart_hover_outside_plot_clears_label(qapp):
    chart = _chart_with_data()
    chart._on_mouse_moved(QPointF(-1e6, -1e6))  # far outside the scene rect
    assert chart._hover_label.text() == ""


def test_chart_hover_over_data_full_readout(qapp):
    chart = _chart_with_data(rh_present=True)
    center = chart.plot_widget.plotItem.sceneBoundingRect().center()
    chart._on_mouse_moved(center)
    text = chart._hover_label.text()
    assert "kW" in text and "°C" in text
    assert "T_air_out" in text and "T_water_out" in text  # air/water named separately
    assert "RH_out" in text  # RH segment present when rh is not NaN


def test_chart_hover_no_water_segment_when_water_nan(qapp):
    chart = _chart_with_data(water_present=False)
    center = chart.plot_widget.plotItem.sceneBoundingRect().center()
    chart._on_mouse_moved(center)
    text = chart._hover_label.text()
    assert "T_air_out" in text
    assert "T_water_out" not in text  # the `else ""` branch of the water segment


def test_chart_hover_no_rh_segment_when_rh_nan(qapp):
    chart = _chart_with_data(rh_present=False)
    center = chart.plot_widget.plotItem.sceneBoundingRect().center()
    chart._on_mouse_moved(center)
    text = chart._hover_label.text()
    assert "kW" in text and "°C" in text
    assert "RH_out" not in text  # the `else ""` branch of the RH segment


def test_chart_hover_nan_point_shows_no_data(qapp):
    """A single failed (NaN) point: hovering anywhere snaps to it and the readout
    shows the 'no data' message rather than a numeric row."""
    chart = ChartWidget()
    chart.resize(600, 400)
    chart.update_chart(
        [DataPoint(x_si=293.15, power_kw=math.nan, air_temp_out_c=math.nan, error="boom")],
        "water_temp_in",
        "°C",
    )
    center = chart.plot_widget.plotItem.sceneBoundingRect().center()
    chart._on_mouse_moved(center)
    assert "no data" in chart._hover_label.text()


# ---------------------------------------------------------------------------
# ui/spinbox.py — hold-to-accelerate step multiplier
# ---------------------------------------------------------------------------


def test_accelerating_double_spin_single_step(qapp):
    box = AcceleratingDoubleSpinBox()
    box.setRange(0.0, 1000.0)
    box.setValue(50.0)
    box.setSingleStep(1.0)
    box.stepBy(1)
    # First step: hold_count == 1 < 3 → multiplier 1×
    assert abs(box.value() - 51.0) < 1e-9


def test_accelerating_double_spin_multiplier_thresholds(qapp):
    # Contract: held stepping accelerates — later steps advance by strictly more
    # than early (unaccelerated) steps. Asserted behaviourally so tuning the
    # multiplier ladder doesn't require editing hard-coded cumulative arithmetic.
    box = AcceleratingDoubleSpinBox()
    box.setRange(0.0, 100000.0)
    box.setValue(0.0)
    box.setSingleStep(1.0)

    # Two early steps are unaccelerated (1× each) → advance by exactly 1 apiece.
    box.stepBy(1)
    first = box.value()
    box.stepBy(1)
    second = box.value()
    assert abs((first - 0.0) - 1.0) < 1e-9
    assert abs((second - first) - 1.0) < 1e-9

    # After enough held steps the multiplier kicks in: a later single step must
    # advance by more than the initial 1× step.
    before = box.value()
    for _ in range(10):
        box.stepBy(1)
    accelerated_span = box.value() - before
    assert accelerated_span > 10.0  # would be exactly 10.0 with no acceleration
    # And the value only ever increases.
    assert box.value() > second


def test_accelerating_double_spin_50x_band(qapp):
    box = AcceleratingDoubleSpinBox()
    box.setRange(0.0, 10000.0)
    box.setValue(0.0)
    box.setSingleStep(1.0)
    # Drive hold_count past 15
    for _ in range(16):
        box.stepBy(1)
    # At hold_count == 16 the multiplier is 50× — value should be well above 16
    assert box.value() > 16.0


def test_accelerating_double_spin_reset_hold(qapp):
    box = AcceleratingDoubleSpinBox()
    box.setRange(0.0, 10000.0)
    box.setValue(0.0)
    box.setSingleStep(1.0)
    # Accumulate some hold
    for _ in range(10):
        box.stepBy(1)
    assert box._hold_count == 10
    # Manually fire the timer callback (simulates key release + timer expiry)
    box._reset_hold()
    assert box._hold_count == 0
    assert not box._hold_timer.isActive()


def test_accelerating_spin_box_steps(qapp):
    box = AcceleratingSpinBox()
    box.setRange(0, 10000)
    box.setValue(0)
    box.setSingleStep(1)
    box.stepBy(1)
    assert box.value() == 1
    # Drive into 5× band
    for _ in range(5):
        box.stepBy(1)
    assert box.value() > 6
