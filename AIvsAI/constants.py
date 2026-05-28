"""Chess Learning App — Shared constants, configuration, logging, and optional-dependency detection."""

import os
import sys
import csv
import re
import ast
import base64
import threading
import shutil

from PySide6.QtGui import QColor, QFont, QPen

csv.field_size_limit(2**31 - 1)

# ════════════════════════════════════════════════════════════════════
#  Optional dependencies
# ════════════════════════════════════════════════════════════════════

HAS_NUMPY = False
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    pass

HAS_IMAGEIO = False
try:
    import imageio.v3 as iio
    HAS_IMAGEIO = True
except Exception:
    pass

HAS_PANDAS = False
HAS_PYARROW = False
HAS_DUCKDB = False
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pass
if not HAS_PANDAS:
    try:
        import pyarrow.parquet as pq
        HAS_PYARROW = True
    except ImportError:
        pass
try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    pass

# ════════════════════════════════════════════════════════════════════
#  Logging helper
# ════════════════════════════════════════════════════════════════════

def log(msg, level="INFO"):
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{level}] {msg}", flush=True)

# ════════════════════════════════════════════════════════════════════
#  File Paths
# ════════════════════════════════════════════════════════════════════

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")

# ════════════════════════════════════════════════════════════════════
#  Board / rendering constants
# ════════════════════════════════════════════════════════════════════

SQ_SIZE  = 68
BOARD_PX = SQ_SIZE * 8

UNICODE_PIECES = {
    'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
    'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
}

FILES_STR = 'abcdefgh'
RANKS_STR = '87654321'

# ── Piece symbol map for board_renderer (piece_type, color) → unicode ──

import chess as _chess

PIECE_SYM = {
    (_chess.PAWN,   _chess.WHITE): '♙',
    (_chess.KNIGHT, _chess.WHITE): '♘',
    (_chess.BISHOP, _chess.WHITE): '♗',
    (_chess.ROOK,   _chess.WHITE): '♖',
    (_chess.QUEEN,  _chess.WHITE): '♕',
    (_chess.KING,   _chess.WHITE): '♔',
    (_chess.PAWN,   _chess.BLACK): '♟',
    (_chess.KNIGHT, _chess.BLACK): '♞',
    (_chess.BISHOP, _chess.BLACK): '♝',
    (_chess.ROOK,   _chess.BLACK): '♜',
    (_chess.QUEEN,  _chess.BLACK): '♛',
    (_chess.KING,   _chess.BLACK): '♚',
}

# ════════════════════════════════════════════════════════════════════
#  Animation defaults
# ════════════════════════════════════════════════════════════════════

ANIM_SPEED_SLOW    = 500
ANIM_SPEED_DEFAULT = 250
ANIM_SPEED_FAST    = 100
ANIM_FPS           = 60

# ════════════════════════════════════════════════════════════════════
#  Game States
# ════════════════════════════════════════════════════════════════════

GAME_NORMAL       = "normal"
GAME_CHECKMATE    = "checkmate"
GAME_STALEMATE    = "stalemate"
GAME_DRAW         = "draw"
GAME_INSUFFICIENT = "insufficient"

# ════════════════════════════════════════════════════════════════════
#  Move Quality Badges
# ════════════════════════════════════════════════════════════════════

MQ_GOOD       = "good"
MQ_BEST       = "best"
MQ_GREAT      = "great"
MQ_BRILLIANT  = "brilliant"
MQ_INACCURACY = "inaccuracy"
MQ_MISTAKE    = "mistake"
MQ_BLUNDER    = "blunder"
MQ_BOOK       = "book"

# Board badges: only truly exceptional moves get a circle on the board
MQ_SHOW_BADGE = {MQ_BRILLIANT, MQ_BLUNDER}

# Move-list pill badges: slightly more permissive
MQ_SHOW_MOVES_BADGE = {MQ_BRILLIANT, MQ_BLUNDER, MQ_MISTAKE, MQ_GREAT}

# Square border glow: highlights the destination square dramatically
MQ_SHOW_SQUARE_GLOW = {MQ_BRILLIANT, MQ_BLUNDER, MQ_MISTAKE}

# ── Badge colours — more vivid for the rare badges ──────────────────

MQ_COLORS = {
    MQ_GOOD:       QColor(120, 190, 120),
    MQ_BEST:       QColor(100, 180, 255),
    MQ_GREAT:      QColor(50, 170, 80),
    MQ_BRILLIANT:  QColor(0, 225, 180),
    MQ_INACCURACY: QColor(220, 190, 60),
    MQ_MISTAKE:    QColor(230, 140, 30),
    MQ_BLUNDER:    QColor(230, 40, 40),
    MQ_BOOK:       QColor(170, 160, 140),
}

MQ_VIDEO_COLORS = dict(MQ_COLORS)

MQ_BG_COLORS = {
    MQ_BRILLIANT:  QColor(0, 225, 180, 50),
    MQ_GREAT:      QColor(50, 170, 80, 35),
    MQ_MISTAKE:    QColor(230, 140, 30, 40),
    MQ_BLUNDER:    QColor(230, 40, 40, 55),
}

# Glow colours for the destination square border
MQ_SQUARE_GLOW_COLORS = {
    MQ_BRILLIANT: QColor(0, 225, 180),
    MQ_BLUNDER:   QColor(230, 40, 40),
    MQ_MISTAKE:   QColor(230, 140, 30),
}

MQ_SYMBOLS = {
    MQ_GOOD:       "",
    MQ_BEST:       "!!",
    MQ_GREAT:      "!",
    MQ_BRILLIANT:  "★",
    MQ_INACCURACY: "?!",
    MQ_MISTAKE:    "!?",
    MQ_BLUNDER:    "✕",
    MQ_BOOK:       "♗",
}

MQ_ICONS = {
    MQ_GOOD:       "",
    MQ_BEST:       "!!",
    MQ_GREAT:      "!",
    MQ_BRILLIANT:  "★",
    MQ_INACCURACY: "?!",
    MQ_MISTAKE:    "!?",
    MQ_BLUNDER:    "✕",
    MQ_BOOK:       "♗",
}

MQ_LABELS = {
    MQ_GOOD:       "Good",
    MQ_BEST:       "Best",
    MQ_GREAT:      "Great",
    MQ_BRILLIANT:  "Brilliant",
    MQ_INACCURACY: "Inaccuracy",
    MQ_MISTAKE:    "Mistake",
    MQ_BLUNDER:    "Blunder",
    MQ_BOOK:       "Book",
}

# ════════════════════════════════════════════════════════════════════
#  Piece values (centipawns) — for legacy ChessEngine
# ════════════════════════════════════════════════════════════════════

PIECE_VAL = {'P': 100, 'N': 320, 'B': 330, 'R': 500, 'Q': 900, 'K': 20000}

# Piece values with enum keys — for move_analyzer sacrifice detection
PIECE_VALUES = {
    _chess.PAWN:   1,
    _chess.KNIGHT: 3,
    _chess.BISHOP: 3,
    _chess.ROOK:   5,
    _chess.QUEEN:  9,
    _chess.KING:   0,
}

# ════════════════════════════════════════════════════════════════════
#  Board Themes
# ════════════════════════════════════════════════════════════════════

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

# ════════════════════════════════════════════════════════════════════
#  Piece-square tables
# ════════════════════════════════════════════════════════════════════

PST = {
    'P': [[0,0,0,0,0,0,0,0],[50,50,50,50,50,50,50,50],[10,10,20,30,30,20,10,10],[5,5,10,25,25,10,5,5],[0,0,0,20,20,0,0,0],[5,-5,-10,0,0,-10,-5,5],[5,10,10,-20,-20,10,10,5],[0,0,0,0,0,0,0,0]],
    'N': [[-50,-40,-30,-30,-30,-30,-40,-50],[-40,-20,0,0,0,0,-20,-40],[-30,0,10,15,15,10,0,-30],[-30,5,15,20,20,15,5,-30],[-30,0,15,20,20,15,0,-30],[-30,5,10,15,15,10,5,-30],[-40,-20,0,5,5,0,-20,-40],[-50,-40,-30,-30,-30,-30,-40,-50]],
    'B': [[-20,-10,-10,-10,-10,-10,-10,-20],[-10,0,0,0,0,0,0,-10],[-10,0,10,10,10,10,0,-10],[-10,5,5,10,10,5,5,-10],[-10,0,5,10,10,5,0,-10],[-10,10,5,10,10,5,10,-10],[-10,5,0,0,0,0,5,-10],[-20,-10,-10,-10,-10,-10,-10,-20]],
    'R': [[0,0,0,0,0,0,0,0],[5,10,10,10,10,10,10,5],[-5,0,0,0,0,0,0,-5],[-5,0,0,0,0,0,0,-5],[-5,0,0,0,0,0,0,-5],[-5,0,0,0,0,0,0,-5],[-5,0,0,0,0,0,0,-5],[0,0,0,5,5,0,0,0]],
    'Q': [[-20,-10,-10,-5,-5,-10,-10,-20],[-10,0,0,0,0,0,0,-10],[-10,0,5,5,5,5,0,-10],[-5,0,5,5,5,5,0,-5],[0,0,5,5,5,5,0,-5],[-10,5,5,5,5,5,0,-10],[-10,0,5,0,0,0,0,-10],[-20,-10,-10,-5,-5,-10,-10,-20]],
    'K': [[-30,-40,-40,-50,-50,-40,-40,-30],[-30,-40,-40,-50,-50,-40,-40,-30],[-30,-40,-40,-50,-50,-40,-40,-30],[-30,-40,-40,-50,-50,-40,-40,-30],[-20,-30,-30,-40,-40,-30,-30,-20],[-10,-20,-20,-20,-20,-20,-20,-10],[20,20,0,0,0,0,20,20],[20,30,10,0,0,10,30,20]],
}

# ════════════════════════════════════════════════════════════════════
#  AI Engine Types
# ════════════════════════════════════════════════════════════════════

AI_MINIMAX   = 0
AI_MCTS      = 1
AI_STOCKFISH = 2

AI_MAP = {
    AI_MINIMAX:   "Minimax (α-β)",
    AI_MCTS:      "MCTS",
    AI_STOCKFISH: "Stockfish",
}

AI_SHORT_NAMES = {
    AI_MINIMAX:   "Minimax",
    AI_MCTS:      "MCTS",
    AI_STOCKFISH: "Stockfish",
}

# ════════════════════════════════════════════════════════════════════
#  Sound Events
# ════════════════════════════════════════════════════════════════════

SND_MOVE       = "move"
SND_CAPTURE    = "capture"
SND_CHECK      = "check"
SND_CASTLE     = "castle"
SND_CHECKMATE  = "checkmate"
SND_STALEMATE  = "stalemate"
SND_DRAW       = "draw"
SND_GAME_START = "game_start"
SND_UI_CLICK   = "ui_click"

SOUND_THEME_LIST = ["Classic", "Digital", "Cinematic", "Retro", "Ambient"]

# ════════════════════════════════════════════════════════════════════
#  Export configuration
# ════════════════════════════════════════════════════════════════════

RESOLUTION_LIST = ["1920×1080", "1280×720", "3840×2160", "1080×1920", "720×1280"]
RESOLUTION_SIZES = {
    "1920×1080": (1920, 1080),
    "1280×720":  (1280, 720),
    "3840×2160": (3840, 2160),
    "1080×1920": (1080, 1920),
    "720×1280":  (720, 1280),
}

DEFAULT_VIDEO_FPS       = 30
DEFAULT_MOVE_DURATION   = 2.0
DEFAULT_ANIM_DURATION   = 0.4
DEFAULT_TITLE_DURATION  = 3.0
DEFAULT_RESULT_DURATION = 3.0
DEFAULT_OUTPUT_DIR      = os.path.join(os.path.expanduser("~"), "Videos", "chess_battles")


class ExportConfig:
    def __init__(self):
        self.fps                 = DEFAULT_VIDEO_FPS
        self.title_enabled       = True
        self.title_text          = ""
        self.title_duration      = DEFAULT_TITLE_DURATION
        self.title_bg            = "#1a1a2e"
        self.title_fg            = "#e0e0e0"
        self.title_font_size     = 36
        self.end_enabled         = True
        self.end_text            = "Solved!"
        self.end_duration        = DEFAULT_RESULT_DURATION
        self.end_bg              = "#1a1a2e"
        self.end_fg              = "#e0e0e0"
        self.end_font_size       = 42
        self.move_anim_duration  = DEFAULT_ANIM_DURATION
        self.pause_after_move    = DEFAULT_MOVE_DURATION
        self.highlight_duration  = 0.3
        self.max_workers         = 4
        self.sq_size             = SQ_SIZE
        self.theme_name          = "Classic"
        self.move_quality        = MQ_GOOD

# ════════════════════════════════════════════════════════════════════
#  Stockfish finder
# ════════════════════════════════════════════════════════════════════

def find_stockfish():
    """Attempt to locate the Stockfish binary on the system."""
    # 1. Check STOCKFISH_PATH env var
    env_path = os.environ.get("STOCKFISH_PATH")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path

    # 2. Check common names on PATH
    candidates = [
        "stockfish",
        "stockfish-windows-x86-64-avx2",
        "stockfish-windows-x86-64-modern",
        "stockfish-windows-x86-64",
        "stockfish_17", "stockfish_16",
    ]
    if sys.platform == "win32":
        candidates = [c + ".exe" for c in candidates]
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found

    # 3. Check common install locations
    if sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local_app_data = os.environ.get("LocalAppData", "")

        search_dirs = [
            program_files,
            program_files_x86,
            r"C:\Stockfish",
            r"D:\Stockfish",
        ]
        if local_app_data:
            search_dirs.append(os.path.join(local_app_data, "Programs"))

        subfolder_names = ["stockfish", "Stockfish", "Stockfish Engine", ""]

        exe_names = [
            # Modern distribution naming (most common)
            "stockfish-windows-x86-64-avx2.exe",
            "stockfish-windows-x86-64-modern.exe",
            "stockfish-windows-x86-64-sse41-popcnt.exe",
            "stockfish-windows-x86-64.exe",
            # Generic naming
            "stockfish.exe",
            "Stockfish.exe",
            # Versioned
            "stockfish_17.exe", "stockfish_16.exe",
            "stockfish_15.exe", "stockfish_14.exe",
        ]

        for base_dir in search_dirs:
            if not os.path.isdir(base_dir):
                continue
            # Check directly in base_dir
            for exe in exe_names:
                p = os.path.join(base_dir, exe)
                if os.path.isfile(p):
                    return p
            # Check in common subfolders
            for sub in subfolder_names:
                for exe in exe_names:
                    p = os.path.join(base_dir, sub, exe)
                    if os.path.isfile(p):
                        return p
            # Fallback: scan for any *stockfish*.exe
            try:
                for entry in os.listdir(base_dir):
                    entry_lower = entry.lower()
                    if "stockfish" in entry_lower:
                        full = os.path.join(base_dir, entry)
                        if os.path.isfile(full) and full.lower().endswith(".exe"):
                            return full
                        if os.path.isdir(full):
                            try:
                                for inner in os.listdir(full):
                                    if inner.lower().endswith(".exe") and "stockfish" in inner.lower():
                                        return os.path.join(full, inner)
                            except OSError:
                                pass
            except OSError:
                pass

    elif sys.platform == "darwin":
        for p in ["/usr/local/bin/stockfish",
                  "/opt/homebrew/bin/stockfish",
                  "/Applications/Stockfish.app/Contents/MacOS/stockfish"]:
            if os.path.isfile(p):
                return p
        # Also check macOS-specific naming
        for name in ["stockfish-macos-x86-64", "stockfish-macos-arm64"]:
            found = shutil.which(name)
            if found:
                return found
    else:
        for p in ["/usr/bin/stockfish",
                  "/usr/local/bin/stockfish",
                  "/usr/games/stockfish",
                  "/snap/bin/stockfish"]:
            if os.path.isfile(p):
                return p
        for name in ["stockfish-linux-x86-64-avx2",
                      "stockfish-linux-x86-64-modern",
                      "stockfish-linux-x86-64"]:
            found = shutil.which(name)
            if found:
                return found

    return None

# ════════════════════════════════════════════════════════════════════
#  Opening-image parsing helper
# ════════════════════════════════════════════════════════════════════

def parse_opening_image(img_val):
    from PySide6.QtGui import QPixmap
    pixmap = None
    img_dict = None
    if isinstance(img_val, dict):
        img_dict = img_val
    elif isinstance(img_val, str) and img_val.strip().startswith("{"):
        try:
            safe = img_val
            safe = re.sub(r'\bnull\b', 'None', safe)
            safe = re.sub(r'\btrue\b', 'True', safe)
            safe = re.sub(r'\bfalse\b', 'False', safe)
            safe = re.sub(r'\bNaN\b', 'None', safe)
            safe = re.sub(r'\bundefined\b', 'None', safe)
            img_dict = ast.literal_eval(safe)
        except Exception as e:
            log(f"Image parse error: {e}", "OPENINGS")
    if img_dict:
        try:
            bytes_val = img_dict.get('bytes')
            actual_bytes = None
            if isinstance(bytes_val, bytes):
                actual_bytes = bytes_val
            elif isinstance(bytes_val, str):
                try:
                    actual_bytes = base64.b64decode(bytes_val)
                except Exception:
                    pass
                if actual_bytes is None:
                    try:
                        actual_bytes = bytes(bytes_val, "utf-8").decode("unicode_escape").encode("latin1")
                    except Exception:
                        pass
            if actual_bytes:
                pixmap = QPixmap()
                pixmap.loadFromData(actual_bytes)
        except Exception as e:
            log(f"Image byte extraction error: {e}", "OPENINGS")
    return pixmap