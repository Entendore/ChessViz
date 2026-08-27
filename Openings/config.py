"""
config.py — Constants, optional-dependency flags, logging, themes, presets, export config.
"""

import os, shutil
import numpy as np

# ═══════════════════════════════════════════════════════════════════════════════
#  OPTIONAL DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════════

HAS_NUMPY = True
HAS_IMAGEIO = False
try:
    import imageio.v3 as iio; HAS_IMAGEIO = True
except Exception: pass
HAS_PANDAS = False; HAS_PYARROW = False; HAS_DUCKDB = False
try:
    import pandas as pd; HAS_PANDAS = True
except ImportError: pass
if not HAS_PANDAS:
    try:
        import pyarrow.parquet as pq; HAS_PYARROW = True
    except ImportError: pass
try:
    import duckdb; HAS_DUCKDB = True
except ImportError: pass
HAS_NUMBA = False
try:
    import numba; HAS_NUMBA = True
except ImportError: pass
HAS_CUPY = False
try:
    import cupy as cp; HAS_CUPY = True
except Exception: pass
HAS_FFMPEG = shutil.which('ffmpeg') is not None
HAS_MOVIEPY = False
try:
    import moviepy; HAS_MOVIEPY = True
except ImportError: pass

# ═══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

def log(msg, level="INFO"):
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{level}] {msg}", flush=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  FILE PATHS
# ═══════════════════════════════════════════════════════════════════════════════

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
DB_OPENINGS_PATH = os.path.join(DATA_DIR, "cache_openings.parquet")
LICHESS_DB_PATH = os.path.join(DATA_DIR, "lichess_db_openings.parquet")

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD / RENDERING CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

import chess

SQ_SIZE   = 68
BOARD_PX  = SQ_SIZE * 8

PIECE_SYM = {
    (chess.PAWN, chess.WHITE): "♟", (chess.PAWN, chess.BLACK): "♟",
    (chess.KNIGHT, chess.WHITE): "♞", (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.WHITE): "♝", (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK, chess.WHITE): "♜", (chess.ROOK, chess.BLACK): "♜",
    (chess.QUEEN, chess.WHITE): "♛", (chess.QUEEN, chess.BLACK): "♛",
    (chess.KING, chess.WHITE): "♚", (chess.KING, chess.BLACK): "♚",
}

FILES_STR = 'abcdefgh'
RANKS_STR = '87654321'

ANIM_SPEED_SLOW    = 500
ANIM_SPEED_DEFAULT = 250
ANIM_SPEED_FAST    = 100
ANIM_FPS           = 60

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD THEMES
# ═══════════════════════════════════════════════════════════════════════════════

from PySide6.QtGui import QColor

class BoardTheme:
    def __init__(self, name="Classic",
                 light=(240, 217, 181), dark=(181, 136, 99),
                 border=(48, 26, 7), highlight=(255, 255, 0, 100),
                 last_move=(155, 199, 0, 100), arrow=(220, 50, 47, 200)):
        self.name = name; self.light_sq = QColor(*light)
        self.dark_sq = QColor(*dark); self.border = QColor(*border)
        self.highlight = QColor(*highlight); self.last_move = QColor(*last_move)
        self.arrow_clr = QColor(*arrow)
        self.bg = QColor(32, 32, 36); self.coord = QColor(180, 160, 130)

THEMES = {
    "Classic": BoardTheme(),
    "Blue":    BoardTheme("Blue", (208, 224, 243), (116, 150, 194), (40, 50, 70)),
    "Green":   BoardTheme("Green", (238, 238, 210), (118, 150, 86), (50, 60, 40)),
    "Brown":   BoardTheme("Brown", (222, 197, 165), (170, 120, 70), (60, 35, 15)),
    "Purple":  BoardTheme("Purple", (220, 210, 230), (150, 130, 170), (50, 40, 60)),
    "Ice":     BoardTheme("Ice", (230, 240, 250), (160, 190, 220), (50, 60, 80)),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT PRESETS
# ═══════════════════════════════════════════════════════════════════════════════

class ExportPreset:
    def __init__(self, name, width, height, fps=30, board_frac=0.82,
                 bg=(26, 26, 46), description=""):
        self.name = name; self.width = width; self.height = height
        self.fps = fps; self.board_frac = board_frac
        self.bg = bg; self.description = description
    @property
    def is_vertical(self): return self.height > self.width
    @property
    def is_square(self): return self.width == self.height
    def calc_sq_size(self):
        if self.is_vertical:
            board_px = int(self.width * self.board_frac)
        else:
            board_px = int(self.height * 0.78 * self.board_frac / 0.82)
        board_px = (board_px // 8) * 8
        return max(8, board_px // 8)

EXPORT_PRESETS = {
    "YouTube 1080p":    ExportPreset("YouTube 1080p",    1920, 1080, 30, 0.60, (26, 26, 46), "16:9 Full HD"),
    "YouTube 720p":     ExportPreset("YouTube 720p",     1280,  720, 30, 0.60, (26, 26, 46), "16:9 HD"),
    "YouTube 4K":       ExportPreset("YouTube 4K",       3840, 2160, 30, 0.60, (26, 26, 46), "16:9 4K"),
    "YouTube Shorts":   ExportPreset("YouTube Shorts",   1080, 1920, 30, 0.70, (26, 26, 46), "9:16 vertical"),
    "TikTok":           ExportPreset("TikTok",           1080, 1920, 30, 0.70, (26, 26, 46), "9:16 vertical"),
    "Instagram Reels":  ExportPreset("Instagram Reels",  1080, 1920, 30, 0.70, (26, 26, 46), "9:16 vertical"),
    "Instagram Square": ExportPreset("Instagram Square", 1080, 1080, 30, 0.65, (26, 26, 46), "1:1 square"),
    "Board Only":       ExportPreset("Board Only",        544,  544, 30, 1.00, (26, 26, 46), "Square board-only"),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ExportConfig:
    def __init__(self):
        self.fps = 30
        self.title_enabled = True; self.title_duration = 3.0
        self.end_hold_enabled = True; self.end_hold_duration = 3.0
        self.move_anim_duration = 0.5; self.pause_after_move = 0.8
        self.preset_name = "YouTube 1080p"
        self.theme_name = "Classic"
        self.ffmpeg_crf = 20; self.ffmpeg_preset = "medium"
    def apply_preset(self, name):
        if name in EXPORT_PRESETS:
            p = EXPORT_PRESETS[name]; self.preset_name = name
            self.fps = p.fps
    @property
    def preset(self):
        return EXPORT_PRESETS.get(self.preset_name, EXPORT_PRESETS["YouTube 1080p"])
    @property
    def target_width(self): return self.preset.width
    @property
    def target_height(self): return self.preset.height
    @property
    def bg_color(self): return self.preset.bg
    @property
    def is_vertical(self): return self.preset.is_vertical
    @property
    def sq_size(self): return self.preset.calc_sq_size()