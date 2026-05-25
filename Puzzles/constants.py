"""Chess Learning App — Shared constants, configuration, logging, and thread-safe helpers.
Numba JIT and CuPy GPU acceleration detected at import time.
"""

import csv, re, ast, base64, os, threading
import chess
from PySide6.QtGui import QColor, QFont, QPen, QImage
csv.field_size_limit(2**31 - 1)

# ── Optional dependencies ─────────────────────────────────────────────────────
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

HAS_NUMBA = False
try:
    import numba
    HAS_NUMBA = True
except ImportError:
    pass

HAS_CUPY = False
try:
    import cupy as cp
    HAS_CUPY = True
except Exception:
    cp = None

# ── Logging helper ────────────────────────────────────────────────────────────
def log(msg, level="INFO"):
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{level}] {msg}", flush=True)

# ── File Paths ────────────────────────────────────────────────────────────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")

# ── Board / rendering constants ───────────────────────────────────────────────
SQ_SIZE   = 68
BOARD_PX  = SQ_SIZE * 8

PIECE_SYM = {
    (chess.PAWN, chess.WHITE):   "♟", (chess.PAWN, chess.BLACK):   "♟",
    (chess.KNIGHT, chess.WHITE): "♞", (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.WHITE): "♝", (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK, chess.WHITE):   "♜", (chess.ROOK, chess.BLACK):   "♜",
    (chess.QUEEN, chess.WHITE):  "♛", (chess.QUEEN, chess.BLACK):  "♛",
    (chess.KING, chess.WHITE):   "♚", (chess.KING, chess.BLACK):   "♚",
}

FILES_STR = 'abcdefgh'
RANKS_STR = '87654321'

# ── Animation defaults ────────────────────────────────────────────────────────
ANIM_SPEED_SLOW    = 500
ANIM_SPEED_DEFAULT = 250
ANIM_SPEED_FAST    = 100
ANIM_FPS           = 60


# ── Board Themes ──────────────────────────────────────────────────────────────
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

# ── Export configuration ─────────────────────────────────────────────────────
class ExportConfig:
    def __init__(self):
        self.fps                 = 30
        self.title_enabled       = True
        self.title_text          = ""
        self.title_duration      = 3.0
        self.title_bg            = "#1a1a2e"
        self.title_fg            = "#e0e0e0"
        self.title_font_size     = 36
        self.end_enabled         = True
        self.end_text            = "Solved!"
        self.end_duration        = 3.0
        self.end_bg              = "#1a1a2e"
        self.end_fg              = "#e0e0e0"
        self.end_font_size       = 42
        self.move_anim_duration  = 0.4
        self.pause_after_move    = 1.0
        self.highlight_duration  = 0.3
        self.max_workers         = 4
        self.sq_size             = SQ_SIZE
        self.theme_name          = "Classic"
        self.gpu_post_process    = True
        self.gpu_vignette        = 0.25
        self.gpu_contrast        = 1.02
        self.gpu_saturation      = 1.05
        self.output_dir          = ""
        self.batch_combine       = False

# ── Filename sanitiser ───────────────────────────────────────────────────────
_SAFE_FS = re.compile(r'[\\/*?:"<>|]')

def sanitize_filename(name, max_len=120):
    s = _SAFE_FS.sub('_', name).strip('. ')
    return s[:max_len] if s else "untitled"

# ── Thread-safe Opening-image parsing ────────────────────────────────────────
def parse_opening_image(img_val):
    img_dict = None
    if isinstance(img_val, dict): img_dict = img_val
    elif isinstance(img_val, str) and img_val.strip().startswith("{"):
        try:
            safe = img_val; safe = re.sub(r'\bnull\b', 'None', safe); safe = re.sub(r'\btrue\b', 'True', safe)
            safe = re.sub(r'\bfalse\b', 'False', safe); safe = re.sub(r'\bNaN\b', 'None', safe)
            safe = re.sub(r'\bundefined\b', 'None', safe); img_dict = ast.literal_eval(safe)
        except Exception: pass
    if img_dict:
        try:
            bytes_val = img_dict.get('bytes'); actual_bytes = None
            if isinstance(bytes_val, bytes): actual_bytes = bytes_val
            elif isinstance(bytes_val, str):
                try: actual_bytes = base64.b64decode(bytes_val)
                except Exception: pass
                if actual_bytes is None:
                    try: actual_bytes = bytes(bytes_val, "utf-8").decode("unicode_escape").encode("latin1")
                    except Exception: pass
            if actual_bytes:
                img = QImage(); img.loadFromData(actual_bytes); return img
        except Exception: pass
    return None

# ── Thread-Local Render Cache Helper ─────────────────────────────────────────
_thread_local = threading.local()

def get_render_assets(sz):
    isz = int(sz * 100)
    if getattr(_thread_local, 'cache_sz', -1) == isz: return _thread_local.assets
    font_piece = QFont("Segoe UI Emoji", sz * 0.9)
    font_piece.setStyleStrategy(QFont.PreferAntialias)
    font_coord = QFont("Sans", max(7, int(sz * 0.13)), QFont.Bold)
    font_badge_normal = QFont("Sans", max(6, int(sz * 0.19 * 0.95)), QFont.Bold)
    font_badge_symbol = QFont("Segoe UI Emoji", max(7, int(sz * 0.19 * 1.15)), QFont.Bold)
    pen_badge_outline = QPen(QColor(255, 255, 255, 120), max(0.8, sz * 0.008))
    assets = (font_piece, font_coord, font_badge_normal, font_badge_symbol, pen_badge_outline)
    _thread_local.cache_sz = isz; _thread_local.assets = assets; return assets