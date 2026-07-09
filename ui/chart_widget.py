"""Three Y-axis pyqtgraph chart with crosshair hover tooltip."""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from physics.axis_model import AXIS_LABEL, from_si
from sweep.sweep import DataPoint
from ui import palette

# Watts per kilowatt — power is stored in kW but plotted in base-SI watts so the
# left axis auto-prefixes correctly (W/kW/…).
_W_PER_KW = 1000.0


class ChartWidget(QWidget):
    """Plots power (left axis), outlet temperatures (inner right axis, ``_vb2`` —
    both air outlet and water return share this °C scale), and outlet RH (outer right
    axis, ``_vb3``) against the swept variable, with a hover readout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._x_values: np.ndarray = np.array([])
        self._power_kw: np.ndarray = np.array([])
        self._temp_out_c: np.ndarray = np.array([])
        self._water_temp_out_c: np.ndarray = np.array([])
        self._rh_out: np.ndarray = np.array([])
        self._x_unit: str = ""
        self._x_variable: str = ""

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")

        self.plot_widget = pg.PlotWidget()
        layout.addWidget(self.plot_widget)

        pi = self.plot_widget.plotItem
        pi.showAxis("right")
        pi.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # --- Second Y-axis: Air Outlet Temperature (right, col 2) ---
        self._vb2 = pg.ViewBox()
        pi.scene().addItem(self._vb2)
        pi.getAxis("right").linkToView(self._vb2)
        self._vb2.setXLink(pi)

        # --- Third Y-axis: Air Outlet RH % (far right, col 3) ---
        self._axis_rh = pg.AxisItem("right")
        pi.layout.addItem(self._axis_rh, 2, 3)
        self._vb3 = pg.ViewBox()
        pi.scene().addItem(self._vb3)
        self._axis_rh.linkToView(self._vb3)
        self._vb3.setXLink(pi)

        pi.vb.sigResized.connect(self._update_views)

        # --- Curve objects ---
        self._curve_power = pi.plot(
            pen=pg.mkPen(color=palette.POWER, width=2), name="Thermal Power"
        )
        self._curve_temp = pg.PlotCurveItem(
            pen=pg.mkPen(color=palette.TEMP, width=2), name="Air Outlet Temp [°C]"
        )
        self._vb2.addItem(self._curve_temp)

        # Water return temperature shares the temperature axis (_vb2); dashed so it
        # reads distinctly from the solid air-outlet curve on the same scale.
        self._curve_water = pg.PlotCurveItem(
            pen=pg.mkPen(color=palette.WATER, width=2, style=Qt.PenStyle.DashLine),
            name="Water Return Temp [°C]",
        )
        self._vb2.addItem(self._curve_water)

        self._curve_rh = pg.PlotCurveItem(
            pen=pg.mkPen(color=palette.RH, width=2, style=Qt.PenStyle.DashLine),
            name="Air Outlet RH [%]",
        )
        self._vb3.addItem(self._curve_rh)

        # --- Axis labels ---
        # Power is plotted in base SI watts so pyqtgraph applies a single correct SI
        # prefix (W/kW/…). The other axes carry non-prefixable units (°C, %, L/s), so
        # SI-prefixing is disabled with siPrefixEnableRanges=() to avoid "m°C"/"kL/s".
        pi.getAxis("left").setLabel("Thermal Power", units="W", color=palette.POWER)
        pi.getAxis("right").setLabel(
            "Outlet Temp", units="°C", siPrefixEnableRanges=(), color=palette.TEMP
        )
        self._axis_rh.setLabel(
            "Air Outlet RH", units="%", siPrefixEnableRanges=(), color=palette.RH
        )

        # --- Crosshair ---
        self._vline = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen(palette.MUTED, width=1, style=Qt.PenStyle.DashLine),
        )
        pi.addItem(self._vline, ignoreBounds=True)

        # --- Hover label ---
        self._hover_label = QLabel("")
        self._hover_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._hover_label.setMinimumHeight(20)
        layout.addWidget(self._hover_label)

        # Align the extra ViewBoxes to the plot rect once up front. Otherwise they
        # keep their default geometry until the first sigResized fires, so the temp
        # and RH curves can render mis-positioned before the initial resize.
        self._update_views()

    def _update_views(self):
        """Keep the two extra ViewBoxes aligned with the main plot on resize."""
        rect = self.plot_widget.plotItem.vb.sceneBoundingRect()
        pi = self.plot_widget.plotItem
        self._vb2.setGeometry(rect)
        self._vb2.linkedViewChanged(pi.vb, self._vb2.XAxis)
        self._vb3.setGeometry(rect)
        self._vb3.linkedViewChanged(pi.vb, self._vb3.XAxis)

    def update_chart(
        self,
        points: list[DataPoint],
        x_variable: str,
        x_display_unit: str,
    ):
        """Redraw all curves for a fresh sweep result and auto-range the axes."""
        self._x_variable = x_variable
        self._x_unit = x_display_unit

        x_si = np.array([p.x_si for p in points])
        power = np.array([p.power_kw for p in points])
        temp_c = np.array([p.air_temp_out_c for p in points])
        water_c = np.array([p.water_temp_out_c for p in points])
        rh_out = np.array([p.air_rh_out_pct for p in points])

        # Convert the SI X values to the user's chosen display unit (the output
        # boundary), reusing the physics-layer dispatch rather than duplicating it.
        x_display = np.array([from_si(x_variable, v, x_display_unit) for v in x_si])

        self._x_values = x_display
        self._power_kw = power
        self._temp_out_c = temp_c
        self._water_temp_out_c = water_c
        self._rh_out = rh_out

        # Curve is in watts (base SI) so the left axis auto-prefixes correctly; the
        # stored self._power_kw stays in kW for the hover readout.
        self._curve_power.setData(x=x_display, y=power * _W_PER_KW)
        self._curve_temp.setData(x=x_display, y=temp_c)
        self._curve_water.setData(x=x_display, y=water_c)
        self._curve_rh.setData(x=x_display, y=rh_out)

        self.plot_widget.plotItem.enableAutoRange()
        self._vb2.enableAutoRange()
        self._vb3.enableAutoRange()

        label = AXIS_LABEL.get(x_variable, x_variable)
        self.plot_widget.plotItem.getAxis("bottom").setLabel(
            label, units=x_display_unit, siPrefixEnableRanges=()
        )

    def _on_mouse_moved(self, pos: QPointF):
        """Snap the crosshair to the nearest point and update the hover readout."""
        if self._x_values.size == 0:
            return
        pi = self.plot_widget.plotItem
        if not pi.sceneBoundingRect().contains(pos):
            self._hover_label.setText("")
            return

        mouse_point = pi.vb.mapSceneToView(pos)
        x = mouse_point.x()

        idx = int(np.argmin(np.abs(self._x_values - x)))
        if idx < 0 or idx >= len(self._x_values):  # pragma: no cover - unreachable:
            # argmin over a non-empty array (guaranteed by the size check above)
            # always yields a valid in-bounds index. Defensive guard only.
            return

        xv = self._x_values[idx]
        pv = self._power_kw[idx]
        tv = self._temp_out_c[idx]
        wv = self._water_temp_out_c[idx] if idx < len(self._water_temp_out_c) else math.nan
        rv = self._rh_out[idx] if idx < len(self._rh_out) else math.nan

        self._vline.setPos(xv)

        if math.isnan(pv) or math.isnan(tv):
            self._hover_label.setText(
                f'<span style="color:{palette.MUTED}">{self._x_unit}: {xv:.3g} — no data</span>'
            )
        else:
            water_seg = (
                f'&nbsp;&nbsp;<span style="color:{palette.WATER}">'
                f"T_water_out: <b>{wv:.1f} °C</b></span>"
                if not math.isnan(wv)
                else ""
            )
            rh_seg = (
                f'&nbsp;&nbsp;<span style="color:{palette.RH}">RH_out: <b>{rv:.0f} %</b></span>'
                if not math.isnan(rv)
                else ""
            )
            self._hover_label.setText(
                f'<span style="color:{palette.HOVER_LABEL}">{self._x_unit}: <b>{xv:.3g}</b></span>'
                f"&nbsp;&nbsp;"
                f'<span style="color:{palette.POWER}">Power: <b>{pv:.3f} kW</b></span>'
                f"&nbsp;&nbsp;"
                f'<span style="color:{palette.TEMP}">T_air_out: <b>{tv:.1f} °C</b></span>'
                f"{water_seg}"
                f"{rh_seg}"
            )
