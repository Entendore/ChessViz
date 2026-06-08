#!/usr/bin/env python3
"""
Chess Puzzle Studio — Entry Point

Install:  pip install PySide6 numpy chess duckdb
Optional: pip install pandas pyarrow numba cupy-cuda121
GPU/Accel: Ensure FFmpeg is installed and in system PATH.
"""

import sys
from PySide6.QtWidgets import QApplication
from main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Chess Puzzle Studio")
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()