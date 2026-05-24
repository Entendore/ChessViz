#!/usr/bin/env python3
"""Chess Video Maker Pro — Application Entry Point"""
import sys
import logging
from PySide6.QtWidgets import QApplication
from main_window import MainWindow

def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)-7s] %(name)s — %(message)s",
        datefmt="%H:%M:%S")
    logger = logging.getLogger("ChessVideoMaker")
    logger.info("═══════════════════════════════════════════════")
    logger.info("  Chess Video Maker Pro — starting up")
    logger.info("═══════════════════════════════════════════════")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    ret = app.exec()
    window._cleanup()
    sys.exit(ret)

if __name__ == "__main__":
    main()