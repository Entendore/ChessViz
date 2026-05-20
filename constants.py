"""Chess Video Maker Pro — Constants, Themes, and Configuration"""

import chess
from PySide6.QtGui import QColor

# ─── Optional Dependencies ──────────────────────────────────────────

try:
    import cv2  # noqa: F401
    import numpy as np  # noqa: F401
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# ─── Piece Symbols ──────────────────────────────────────────────────

PIECE_SYM = {
    (chess.PAWN,   chess.WHITE): "♙", (chess.PAWN,   chess.BLACK): "♟",
    (chess.KNIGHT, chess.WHITE): "♘", (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.WHITE): "♗", (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK,   chess.WHITE): "♖", (chess.ROOK,   chess.BLACK): "♜",
    (chess.QUEEN,  chess.WHITE): "♕", (chess.QUEEN,  chess.BLACK): "♛",
    (chess.KING,   chess.WHITE): "♔", (chess.KING,   chess.BLACK): "♚",
}

# ─── AI Engine Mapping ──────────────────────────────────────────────

AI_MAP = {
    0: "Minimax (Alpha-Beta)",
    1: "MCTS (Monte Carlo)",
    2: "Stockfish (UCI)",
}

# ─── Sample PGN ─────────────────────────────────────────────────────

SAMPLE_PGN = """\
[Event "World Championship 2023"]
[Site "London ENG"]
[Date "2023.04.09"]
[White "Carlsen, Magnus"]
[Black "Nepomniachtchi, Ian"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5
7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 11. Nbd2 Bb7 12. Bc2 Re8
13. Nf1 Bf8 14. Ng3 g6 15. a4 Bg7 16. Bd3 c6 17. Bg5 Qc7 18. Qd2 Nh5
19. Nxh5 gxh5 20. Bh6 Bxh6 21. Qxh6 Qd8 22. Rab1 Qe7 23. b4 a5 1-0"""

# ─── Board Themes ───────────────────────────────────────────────────


class BoardTheme:
    """Chess board visual theme with configurable colors."""

    def __init__(self, name="Classic", light=(240, 217, 181), dark=(181, 136, 99),
                 border=(48, 26, 7), highlight=(255, 255, 0, 100),
                 last_move=(155, 199, 0, 100), arrow=(220, 50, 47, 200)):
        self.name = name
        self.light_sq = QColor(*light)
        self.dark_sq = QColor(*dark)
        self.border = QColor(*border)
        self.highlight = QColor(*highlight)
        self.last_move = QColor(*last_move)
        self.arrow_clr = QColor(*arrow)
        self.bg = QColor(32, 32, 36)
        self.coord = QColor(180, 160, 130)


THEMES = {
    "Classic": BoardTheme(),
    "Blue": BoardTheme("Blue", (208, 224, 243), (116, 150, 194), (40, 50, 70)),
    "Green": BoardTheme("Green", (238, 238, 210), (118, 150, 86), (50, 60, 40)),
    "Brown": BoardTheme("Brown", (222, 197, 165), (170, 120, 70), (60, 35, 15)),
}