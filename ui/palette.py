"""Shared UI color palette.

Single source of truth for the four metric colors. The chart curves
(``chart_widget``) use all four; the status-line HTML (``main_window``) reuses
``RH`` for the ``(condensing)`` note (plus ``WARNING``/``ERROR``), so any color
it shares with the chart stays in sync.
"""

from __future__ import annotations

# Per-metric colors, matched across the chart and the status summary.
POWER = "#c0392b"  # thermal power (red)
TEMP = "#2980b9"  # air outlet temperature (blue)
WATER = "#8e44ad"  # water return temperature (purple)
RH = "#27ae60"  # air outlet relative humidity / condensing note (green)

# Status-message colors.
ERROR = "red"
WARNING = "orange"

# Neutral greys for chart chrome (crosshair, hover readout, "no data" text).
HOVER_LABEL = "#555"  # hover readout label text
MUTED = "gray"  # crosshair line and "no data" hover text
