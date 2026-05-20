#!/usr/bin/env python3
"""
Chess Video Maker Pro — Database, Assets, AI Battle & Eval Graph
Create chess YouTube videos with external PGN databases, Image overlays, AI vs AI, and Eval Bars.

Requirements:
    pip install PySide6 python-chess opencv-python numpy
"""

import sys
from PySide6.QtWidgets import QApplication

from main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()