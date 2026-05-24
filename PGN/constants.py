import os
import shutil
from PySide6.QtGui import QColor
import chess

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import numba
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

try:
    import cupy
    HAS_CUPY = True
except ImportError:
    HAS_CUPY = False

PIECE_SYM = {
    (chess.PAWN, chess.WHITE): "♙", (chess.PAWN, chess.BLACK): "♟",
    (chess.KNIGHT, chess.WHITE): "♘", (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.WHITE): "♗", (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK, chess.WHITE): "♖", (chess.ROOK, chess.BLACK): "♜",
    (chess.QUEEN, chess.WHITE): "♕", (chess.QUEEN, chess.BLACK): "♛",
    (chess.KING, chess.WHITE): "♔", (chess.KING, chess.BLACK): "♚",
}

PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}

RESOLUTION_SIZES = {
    "1920×1080": (1920, 1080),
    "1280×720": (1280, 720),
    "3840×2160": (3840, 2160),
}
RESOLUTION_LIST = list(RESOLUTION_SIZES.keys())

GAME_NORMAL = "normal"
GAME_CHECKMATE = "checkmate"
GAME_STALEMATE = "stalemate"
GAME_DRAW = "draw"
GAME_INSUFFICIENT = "insufficient"

DEFAULT_ANIM_DURATION = 0.3

class BoardTheme:
    def __init__(self, name="Classic", light=(240, 217, 181), dark=(181, 136, 99),
                 border=(48, 26, 7), highlight=(255, 255, 0, 100),
                 last_move=(155, 199, 0, 100), arrow=(220, 50, 47, 200)):
        self.name = name; self.light_sq = QColor(*light); self.dark_sq = QColor(*dark); self.border = QColor(*border)
        self.highlight = QColor(*highlight); self.last_move = QColor(*last_move); self.arrow_clr = QColor(*arrow)
        self.bg = QColor(32, 32, 36); self.coord = QColor(180, 160, 130)

THEMES = {
    "Classic": BoardTheme(),
    "Blue": BoardTheme("Blue", (208, 224, 243), (116, 150, 194), (40, 50, 70)),
    "Green": BoardTheme("Green", (238, 238, 210), (118, 150, 86), (50, 60, 40)),
    "Brown": BoardTheme("Brown", (222, 197, 165), (170, 120, 70), (60, 35, 15)),
}

def find_stockfish():
    p = shutil.which("stockfish")
    if p: return p
    candidates = ["/usr/games/stockfish", "/usr/local/bin/stockfish", r"C:\Stockfish\stockfish.exe", r"C:\Program Files\Stockfish\stockfish.exe", r"C:\Program Files (x86)\Stockfish\stockfish.exe", "/opt/homebrew/bin/stockfish", "/usr/local/Cellar/stockfish"]
    for d in candidates:
        if os.path.isfile(d): return d
        if os.path.isdir(d):
            for root, _, files in os.walk(d):
                for f in files:
                    if "stockfish" in f.lower(): return os.path.join(root, f)
    return None

def find_ffmpeg():
    p = shutil.which("ffmpeg")
    if p: return p
    candidates = ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\FFmpeg\bin\ffmpeg.exe", "/opt/homebrew/bin/ffmpeg"]
    for d in candidates:
        if os.path.isfile(d): return d
    return None