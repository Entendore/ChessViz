#!/usr/bin/env python3
"""
main.py — Entry point for Chess Openings App.

Install:  pip install PySide6 numpy imageio[ffmpeg] chess
Optional: pip install pandas pyarrow duckdb
GPU/Accel: pip install numba cupy-cuda121
"""

import sys
from PySide6.QtWidgets import QApplication
from config import log
from main_window import MainWindow


def main():
    log("Chess Openings App starting…")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette
    from PySide6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(45, 45, 48))
    palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
    palette.setColor(QPalette.ToolTipBase, QColor(25, 25, 25))
    palette.setColor(QPalette.ToolTipText, QColor(220, 220, 220))
    palette.setColor(QPalette.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.Button, QColor(55, 55, 58))
    palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.BrightText, QColor(255, 50, 50))
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)

    window = MainWindow()
    window.show()

    log("Window shown — event loop starting")
    ret = app.exec()
    log("Application exiting")
    return ret


if __name__ == "__main__":
    sys.exit(main())