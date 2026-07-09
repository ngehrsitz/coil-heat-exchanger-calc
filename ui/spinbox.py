"""Spin box subclasses with hold-to-accelerate step multiplier."""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDoubleSpinBox, QSpinBox

# Milliseconds of key-repeat silence after which the hold counter resets.
_HOLD_RESET_MS = 300

# Hold-to-accelerate ladder: (min hold_count, step multiplier), highest first.
# The first band whose threshold the hold count has reached wins.
_ACCEL_BANDS: tuple[tuple[int, int], ...] = (
    (15, 50),
    (7, 10),
    (3, 5),
)


class _AccelMixin:
    """Mixin that multiplies the step size when the arrow key is held down."""

    def __init__(self) -> None:
        self._hold_count: int = 0
        self._hold_timer: QTimer = QTimer(self)  # type: ignore[call-arg]
        self._hold_timer.setInterval(_HOLD_RESET_MS)
        self._hold_timer.timeout.connect(self._reset_hold)

    def _multiplier(self) -> int:
        for threshold, mult in _ACCEL_BANDS:
            if self._hold_count >= threshold:
                return mult
        return 1

    def _reset_hold(self) -> None:
        self._hold_count = 0
        self._hold_timer.stop()

    def stepBy(self, steps: int) -> None:
        self._hold_count += 1
        self._hold_timer.start()
        super().stepBy(steps * self._multiplier())  # type: ignore[misc]


class AcceleratingDoubleSpinBox(_AccelMixin, QDoubleSpinBox):
    def __init__(self, parent=None) -> None:
        QDoubleSpinBox.__init__(self, parent)
        _AccelMixin.__init__(self)


class AcceleratingSpinBox(_AccelMixin, QSpinBox):
    def __init__(self, parent=None) -> None:
        QSpinBox.__init__(self, parent)
        _AccelMixin.__init__(self)
