import sys
import logging
from PySide6.QtWidgets import QApplication
from constants import HAS_CV2, HAS_NUMBA, HAS_CUPY, find_ffmpeg
from gui import PGNtoMP4Window

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-7s] %(name)s — %(message)s", datefmt="%H:%M:%S")

def main():
    if not find_ffmpeg() and not HAS_CV2:
        print("ERROR: FFmpeg or opencv-python is required.")
        print("Install FFmpeg for H.264 support, or run: pip install opencv-python numpy")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("PGN → MP4 Converter")
    
    window = PGNtoMP4Window()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()