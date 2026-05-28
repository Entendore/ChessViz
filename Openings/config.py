"""
config.py — Constants, optional-dependency flags, logging, themes, presets, export config.
"""

import os, math, re, shutil
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
HAS_CUPY = False; _cp = None
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
DB_OPENINGS_PATH = os.path.join(DATA_DIR, "cache_openings.parquet")

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

class BoardTheme:
    def __init__(self, name="Classic",
                 light=(240, 217, 181), dark=(181, 136, 99),
                 border=(48, 26, 7), highlight=(255, 255, 0, 100),
                 last_move=(155, 199, 0, 100), arrow=(220, 50, 47, 200)):
        self.name = name; self.light_sq = QColor(*light); self.dark_sq = QColor(*dark)
        self.border = QColor(*border); self.highlight = QColor(*highlight)
        self.last_move = QColor(*last_move); self.arrow_clr = QColor(*arrow)
        self.bg = QColor(32, 32, 36); self.coord = QColor(180, 160, 130)

# Deferred QColor import — BoardTheme needs it
from PySide6.QtGui import QColor

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
    def aspect_ratio(self):
        from math import gcd; g = gcd(self.width, self.height)
        return self.width // g, self.height // g
    @property
    def is_vertical(self): return self.height > self.width
    @property
    def is_square(self): return self.width == self.height
    def calc_sq_size(self):
        shorter = min(self.width, self.height)
        board_px = int(shorter * self.board_frac); board_px = (board_px // 8) * 8
        return max(8, board_px // 8)
    def calc_board_rect(self):
        sq = self.calc_sq_size(); bw = sq * 8; bh = sq * 8
        return (self.width - bw) // 2, (self.height - bh) // 2, bw, bh

EXPORT_PRESETS = {
    "Board Only (544×544)": ExportPreset("Board Only", 544, 544, 30, 1.0, (26, 26, 46), "Square board-only"),
    "YouTube 720p (1280×720)": ExportPreset("YouTube 720p", 1280, 720, 30, 0.82, (18, 18, 32), "16:9 HD"),
    "YouTube 1080p (1920×1080)": ExportPreset("YouTube 1080p", 1920, 1080, 30, 0.78, (18, 18, 32), "16:9 Full HD"),
    "YouTube 4K (3840×2160)": ExportPreset("YouTube 4K", 3840, 2160, 30, 0.75, (18, 18, 32), "16:9 4K"),
    "YouTube Shorts (1080×1920)": ExportPreset("YouTube Shorts", 1080, 1920, 30, 0.50, (18, 18, 32), "9:16 vertical"),
    "TikTok (1080×1920)": ExportPreset("TikTok", 1080, 1920, 30, 0.50, (18, 18, 32), "9:16 vertical"),
    "Instagram Reels (1080×1920)": ExportPreset("Instagram Reels", 1080, 1920, 30, 0.50, (18, 18, 32), "9:16 vertical"),
    "Instagram Square (1080×1080)": ExportPreset("Instagram Square", 1080, 1080, 30, 0.82, (18, 18, 32), "1:1 square"),
    "Twitter/X (1280×720)": ExportPreset("Twitter/X", 1280, 720, 30, 0.80, (18, 18, 32), "16:9"),
    "Custom": ExportPreset("Custom", 544, 544, 30, 0.82, (26, 26, 46), "User-defined"),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ExportConfig:
    def __init__(self):
        self.fps = 30; self.title_enabled = True; self.title_text = ""
        self.title_duration = 3.0; self.title_bg = "#1a1a2e"
        self.title_fg = "#e0e0e0"; self.title_font_size = 36
        self.end_enabled = True; self.end_text = "Solved!"
        self.end_duration = 3.0; self.end_bg = "#1a1a2e"
        self.end_fg = "#e0e0e0"; self.end_font_size = 42
        self.move_anim_duration = 0.4; self.pause_after_move = 1.0
        self.highlight_duration = 0.3; self.max_workers = 4
        self.sq_size = SQ_SIZE; self.theme_name = "Classic"
        self.gpu_post_process = True; self.gpu_vignette = 0.25
        self.gpu_contrast = 1.02; self.gpu_saturation = 1.05
        self.output_dir = ""; self.batch_combine = False
        self.preset_name = "Board Only (544×544)"
        self.target_width = 544; self.target_height = 544
        self.background_color = (26, 26, 46); self.board_frac = 0.82
        self.audio_path = ""; self.audio_volume = 0.25
        self.export_gif = False; self.gif_fps = 12
        self.show_title_overlay = True; self.title_overlay_text = ""
        self.subtitle_text = ""; self.use_ffmpeg = True
        self.ffmpeg_crf = 20; self.ffmpeg_preset = "medium"
    def apply_preset(self, preset_name):
        if preset_name in EXPORT_PRESETS:
            p = EXPORT_PRESETS[preset_name]
            self.preset_name = preset_name; self.target_width = p.width
            self.target_height = p.height; self.fps = p.fps
            self.background_color = p.bg; self.board_frac = p.board_frac
            if preset_name != "Custom": self.sq_size = p.calc_sq_size()
    @property
    def effective_sq_size(self):
        if self.preset_name and self.preset_name not in ("Board Only (544×544)", "Custom"):
            p = EXPORT_PRESETS.get(self.preset_name)
            if p: return p.calc_sq_size()
        return self.sq_size
    @property
    def is_vertical(self): return self.target_height > self.target_width