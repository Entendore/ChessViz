#!/usr/bin/env python3
"""
Chess Learning App — PySide6
Install:  pip install PySide6 numpy imageio[ffmpeg] chess
Optional: pip install pandas pyarrow duckdb
GPU/Accel: pip install numba cupy-cuda121
"""

import sys
from PySide6.QtWidgets import QApplication, QMainWindow
from constants import log
from main_window import MainWindow


def main():
    log("Launching Chess Learning App…", "APP")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    shell = QMainWindow()
    shell.setWindowTitle("♚ Chess Learning App")
    shell.setCentralWidget(MainWindow())
    shell.resize(1020, 640)
    shell.show()
    log("Event loop started", "APP")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()