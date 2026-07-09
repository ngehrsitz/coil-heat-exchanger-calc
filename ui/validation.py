"""Shared helpers for flagging invalid input widgets with a red outline.

Uses a Qt dynamic property (``invalid``) plus a single stylesheet rule so the
outline can be toggled without clobbering other styles. The rule

    QDoubleSpinBox[invalid="true"], QSpinBox[invalid="true"] { border: 1px solid red; }

is installed once on the main window (see ``ui/main_window.py``).
"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget


def mark_invalid(widget: QWidget, invalid: bool = True) -> None:
    """Set (or clear) the ``invalid`` dynamic property and repolish the widget."""
    if widget.property("invalid") == invalid:
        return
    widget.setProperty("invalid", invalid)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def clear_invalid(widget: QWidget) -> None:
    """Clear the invalid outline on a widget."""
    mark_invalid(widget, False)
