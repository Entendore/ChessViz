#!/usr/bin/env python3
"""
Chess Learning App with CSV/Parquet/DuckDB/SQLite Opening Loader — PySide6

Install:  pip install PySide6 numpy imageio[ffmpeg]
Optional: pip install pandas pyarrow duckdb
"""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow

from constants import log
from main_window import MainWindow


def main():
    log("Launching Chess Learning App…", "APP")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Wrap our MainWindow widget in a QMainWindow so it behaves like the
    # original (window title, menu bar, etc. are on the outer shell).
    shell = QMainWindow()
    shell.setWindowTitle("♚ Chess Learning App")
    shell.setCentralWidget(MainWindow())
    shell.show()

    log("Event loop started", "APP")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()