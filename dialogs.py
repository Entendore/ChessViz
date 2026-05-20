"""Chess Video Maker Pro — Inline Widgets (Promotion, no popups)"""

import chess
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont


class PromotionWidget(QWidget):
    """Inline widget for selecting pawn promotion piece (no popup)."""

    piece_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        self._label = QLabel("Promote to:")
        self._label.setStyleSheet("font-weight: bold;")
        lay.addWidget(self._label)
        self._buttons = []
        syms = {
            chess.QUEEN: "♕",
            chess.ROOK: "♖",
            chess.BISHOP: "♗",
            chess.KNIGHT: "♘",
        }
        for pt, sym in syms.items():
            b = QPushButton(sym)
            b.setFont(QFont("Segoe UI Symbol", 20))
            b.setFixedSize(48, 40)
            b.clicked.connect(lambda _, p=pt: self._pick(p))
            lay.addWidget(b)
            self._buttons.append((pt, b))
        self.hide()

    def show_for_color(self, color):
        black_syms = {
            chess.QUEEN: "♛",
            chess.ROOK: "♜",
            chess.BISHOP: "♝",
            chess.KNIGHT: "♞",
        }
        syms = black_syms if color == chess.BLACK else {
            chess.QUEEN: "♕",
            chess.ROOK: "♖",
            chess.BISHOP: "♗",
            chess.KNIGHT: "♘",
        }
        for pt, b in self._buttons:
            b.setText(syms[pt])
        self.show()

    def _pick(self, pt):
        self.piece_selected.emit(pt)
        self.hide()