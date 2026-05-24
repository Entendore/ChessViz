import sys, os, shutil
import chess
from PySide6.QtGui import QColor

# ── Piece Symbols ──────────────────────────────────────────────
PIECE_SYM = {
    (chess.PAWN,   chess.WHITE): "♙", (chess.PAWN,   chess.BLACK): "♟",
    (chess.KNIGHT, chess.WHITE): "♘", (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.WHITE): "♗", (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK,   chess.WHITE): "♖", (chess.ROOK,   chess.BLACK): "♜",
    (chess.QUEEN,  chess.WHITE): "♕", (chess.QUEEN,  chess.BLACK): "♛",
    (chess.KING,   chess.WHITE): "♔", (chess.KING,   chess.BLACK): "♚",
}

# ── Resolution Presets ─────────────────────────────────────────
RESOLUTION_SIZES = {
    "1920×1080":        (1920, 1080),
    "1280×720":         (1280, 720),
    "1080×1920 (Short)": (1080, 1920),
    "720×1280 (Short)":  (720, 1280),
}
RESOLUTION_LIST = list(RESOLUTION_SIZES.keys())

# ── Game State Constants ──────────────────────────────────────
GAME_NORMAL       = "normal"
GAME_CHECKMATE    = "checkmate"
GAME_STALEMATE    = "stalemate"
GAME_DRAW         = "draw"
GAME_INSUFFICIENT = "insufficient"

# ── AI Map ────────────────────────────────────────────────────
AI_MAP         = {0: "Minimax (Alpha-Beta)", 1: "MCTS (Monte Carlo)", 2: "Stockfish (UCI)"}
AI_SHORT_NAMES = {0: "Minimax", 1: "MCTS", 2: "Stockfish"}

DEFAULT_OUTPUT_DIR = "output"

# ── Sound Events ──────────────────────────────────────────────
SND_MOVE = "move";  SND_CAPTURE = "capture"; SND_CHECK = "check"
SND_CASTLE = "castle"; SND_CHECKMATE = "checkmate"
SND_STALEMATE = "stalemate"; SND_DRAW = "draw"
SND_GAME_START = "game_start"; SND_UI_CLICK = "ui_click"
SOUND_THEME_LIST = ["Classic", "Digital", "Cinematic", "Retro", "Ambient"]

# ── Move Quality ──────────────────────────────────────────────
MQ_BRILLIANT    = "brilliant"
MQ_GREAT        = "great"
MQ_BEST         = "best"
MQ_GOOD         = "good"
MQ_INACCURACY   = "inaccuracy"
MQ_MISTAKE      = "mistake"
MQ_BLUNDER      = "blunder"
MQ_BOOK         = "book"

MQ_LABELS = {
    MQ_BRILLIANT: "Brilliant",  MQ_GREAT: "Great",
    MQ_BEST: "Best",            MQ_GOOD: "Good",
    MQ_INACCURACY: "Inaccuracy",MQ_MISTAKE: "Mistake",
    MQ_BLUNDER: "Blunder",      MQ_BOOK: "Book",
}

MQ_SYMBOLS = {
    MQ_BRILLIANT: "★",  MQ_GREAT: "!",  MQ_BEST: "",
    MQ_GOOD: "",        MQ_INACCURACY: "!?", MQ_MISTAKE: "?",
    MQ_BLUNDER: "✕",    MQ_BOOK: "",
}

MQ_ICONS = {
    MQ_BRILLIANT: "★",  MQ_GREAT: "!",  MQ_BEST: "",
    MQ_GOOD: "",        MQ_INACCURACY: "!?", MQ_MISTAKE: "?",
    MQ_BLUNDER: "✕",    MQ_BOOK: "",
}

MQ_SHOW_BADGE = {MQ_BRILLIANT, MQ_GREAT, MQ_INACCURACY, MQ_MISTAKE, MQ_BLUNDER}

MQ_COLORS = {
    MQ_BRILLIANT:  QColor(0, 210, 175),
    MQ_GREAT:      QColor(90, 195, 90),
    MQ_BEST:       QColor(100, 155, 225),
    MQ_GOOD:       QColor(150, 155, 165),
    MQ_INACCURACY: QColor(225, 185, 50),
    MQ_MISTAKE:    QColor(225, 125, 50),
    MQ_BLUNDER:    QColor(220, 45, 45),
    MQ_BOOK:       QColor(130, 130, 160),
}
MQ_BG_COLORS = {
    MQ_BRILLIANT:  QColor(0, 210, 175, 50),
    MQ_GREAT:      QColor(90, 195, 90, 45),
    MQ_BEST:       QColor(100, 155, 225, 30),
    MQ_GOOD:       QColor(150, 155, 165, 0),
    MQ_INACCURACY: QColor(225, 185, 50, 45),
    MQ_MISTAKE:    QColor(225, 125, 50, 55),
    MQ_BLUNDER:    QColor(220, 45, 45, 60),
    MQ_BOOK:       QColor(130, 130, 160, 25),
}
MQ_VIDEO_COLORS = {
    MQ_BRILLIANT:  (0, 210, 175),  MQ_GREAT:  (90, 195, 90),
    MQ_BEST:       (100, 155, 225), MQ_GOOD:   (150, 155, 165),
    MQ_INACCURACY: (225, 185, 50), MQ_MISTAKE:(225, 125, 50),
    MQ_BLUNDER:    (220, 45, 45),  MQ_BOOK:   (130, 130, 160),
}

PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}

# ── Video Export Defaults ─────────────────────────────────────
DEFAULT_VIDEO_FPS        = 30
DEFAULT_MOVE_DURATION    = 2.0   # seconds per move (pause + anim + settle)
DEFAULT_ANIM_DURATION    = 0.4   # seconds for piece sliding animation
DEFAULT_TITLE_DURATION   = 3.0   # seconds for title card
DEFAULT_RESULT_DURATION  = 4.0   # seconds for result card

# ── Board Theme ───────────────────────────────────────────────
class BoardTheme:
    def __init__(self, name="Classic",
                 light=(240, 217, 181), dark=(181, 136, 99),
                 border=(48, 26, 7), highlight=(255, 255, 0, 100),
                 last_move=(155, 199, 0, 100), arrow=(220, 50, 47, 200)):
        self.name = name
        self.light_sq = QColor(*light)
        self.dark_sq  = QColor(*dark)
        self.border   = QColor(*border)
        self.highlight = QColor(*highlight)
        self.last_move = QColor(*last_move)
        self.arrow_clr = QColor(*arrow)
        self.bg   = QColor(32, 32, 36)
        self.coord = QColor(180, 160, 130)

THEMES = {
    "Classic": BoardTheme(),
    "Blue":    BoardTheme("Blue", (208, 224, 243), (116, 150, 194), (40, 50, 70)),
    "Green":   BoardTheme("Green", (238, 238, 210), (118, 150, 86), (50, 60, 40)),
    "Brown":   BoardTheme("Brown", (222, 197, 165), (170, 120, 70), (60, 35, 15)),
    "Purple":  BoardTheme("Purple", (220, 210, 230), (150, 130, 170), (50, 40, 60)),
    "Ice":     BoardTheme("Ice", (230, 240, 250), (160, 190, 220), (50, 60, 80)),
}

# ── Stockfish Discovery ──────────────────────────────────────
def find_stockfish():
    for name in ("stockfish", "stockfish.exe"):
        p = shutil.which(name)
        if p:
            return p
    candidates = [
        "/usr/games/stockfish", "/usr/local/bin/stockfish",
        "/opt/homebrew/bin/stockfish", "/usr/bin/stockfish", "/snap/bin/stockfish",
    ]
    if sys.platform == "win32":
        pf  = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pfx = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        lad = os.environ.get("LOCALAPPDATA", r"C:\Users")
        candidates += [r"C:\Stockfish", os.path.join(pf, "Stockfish"),
                       os.path.join(pfx, "Stockfish"),
                       os.path.join(lad, "Programs", "Stockfish")]
    for d in candidates:
        if os.path.isfile(d):
            return d
        if os.path.isdir(d):
            try:
                for f in os.listdir(d):
                    if f.lower().startswith("stockfish") and f.lower().endswith(".exe"):
                        return os.path.join(d, f)
            except OSError:
                pass
    return None