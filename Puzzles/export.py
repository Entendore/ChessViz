"""MP4 export worker — renders a puzzle as a video file in a background thread."""

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from constants import log, HAS_NUMPY, HAS_IMAGEIO
from engine import ChessEngine
from board_widget import ChessBoardWidget


class ExportWorker(QThread):
    progress = Signal(int)
    finished = Signal(str)

    def __init__(self, puzzle, file_path):
        super().__init__()
        self.puzzle = puzzle
        self.file_path = file_path

    def run(self):
        if not HAS_NUMPY or not HAS_IMAGEIO:
            msg = ("ERROR: Missing numpy or imageio. Install via:\n"
                   "pip install numpy imageio[ffmpeg]")
            log(msg, "EXPORT"); self.finished.emit(msg)
            return

        import numpy as np
        import imageio.v3 as iio

        log(f"Starting MP4 export for puzzle '{self.puzzle['name']}' "
            f"-> {self.file_path}", "EXPORT")

        eng = ChessEngine()
        eng.load_fen(self.puzzle["fen"])
        fps = 30
        frames = []

        # Intro
        log("Rendering intro frames...", "EXPORT")
        for i in range(fps * 3):
            pix = ChessBoardWidget.render_image(
                eng.board,
                text_overlay=f"Puzzle: {self.puzzle['name']}")
            frames.append(self._pix_to_np(pix))
        self.progress.emit(30)

        # Each move
        for idx, move in enumerate(self.puzzle["moves"]):
            (fr, fc), (tr, tc) = move
            log(f"Rendering move {idx+1}/{len(self.puzzle['moves'])}: "
                f"({fr},{fc})->({tr},{tc})...", "EXPORT")
            for i in range(int(fps * 1.5)):
                pix = ChessBoardWidget.render_image(
                    eng.board, selected=(fr, fc))
                frames.append(self._pix_to_np(pix))
            eng.make_move(fr, fc, tr, tc)
            for i in range(fps * 2):
                pix = ChessBoardWidget.render_image(
                    eng.board, last_move=((fr, fc), (tr, tc)))
                frames.append(self._pix_to_np(pix))
            pct = 30 + (40 * (idx + 1) // len(self.puzzle["moves"]))
            self.progress.emit(pct)
            log(f"Move {idx+1} rendered — progress {pct}%", "EXPORT")

        # Outro
        log("Rendering outro frames...", "EXPORT")
        for i in range(fps * 2):
            pix = ChessBoardWidget.render_image(
                eng.board, text_overlay="Solved!")
            frames.append(self._pix_to_np(pix))
        self.progress.emit(85)

        # Write
        log(f"Writing {len(frames)} frames to {self.file_path}...", "EXPORT")
        try:
            iio.write(self.file_path, fps, frames)
        except Exception as e:
            msg = f"Error writing MP4: {e}"
            log(msg, "EXPORT"); self.finished.emit(msg)
            return

        self.progress.emit(100)
        msg = f"MP4 successfully saved to: {self.file_path}"
        log(msg, "EXPORT"); self.finished.emit(msg)

    @staticmethod
    def _pix_to_np(pix):
        import numpy as np
        img = pix.toImage().convertToFormat(QImage.Format_RGB888)
        ptr = img.bits(); ptr.setsize(img.sizeInBytes())
        return np.frombuffer(ptr, dtype=np.uint8).reshape(
            (img.height(), img.width(), 3)).copy()