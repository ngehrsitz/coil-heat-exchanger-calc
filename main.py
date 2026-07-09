"""Entry point."""

import logging
import sys

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> None:
    # Install a root handler so the modules' logger.debug/exception calls surface
    # (without this only WARNING+ reaches the default handler, muting the sweep
    # and calculation diagnostics the code emits).
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    app.setApplicationName("coil-heat-exchanger-calc")
    app.setFont(QFont("Segoe UI", 9))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
