"""Chess Learning App — Shared constants, configuration, logging, and optional-dependency detection."""

import csv, re, ast, base64, os, threading
from PySide6.QtGui import QColor, QFont, QPen
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

UNICODE_PIECES = {
    'K': '♚', 'Q': '♛', 'R': '♜', 'B': '♝', 'N': '♞', 'P': '♟',
    'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
}

FILES_STR = 'abcdefgh'
RANKS_STR = '87654321'

# ── Animation defaults ────────────────────────────────────────────────────────
ANIM_SPEED_SLOW    = 500
ANIM_SPEED_DEFAULT = 250
ANIM_SPEED_FAST    = 100
ANIM_FPS           = 60

# ── Move Quality Badges ──────────────────────────────────────────────────────
MQ_GOOD      = "good"
MQ_BEST      = "best"
MQ_BRILLIANT = "brilliant"
MQ_BLUNDER   = "blunder"
MQ_BOOK      = "book"

MQ_SHOW_BADGE = {MQ_BRILLIANT, MQ_BLUNDER, MQ_BEST, MQ_GOOD}

MQ_COLORS = {
    MQ_GOOD:      QColor(120, 190, 120),
    MQ_BEST:      QColor(100, 180, 255),
    MQ_BRILLIANT: QColor(0, 210, 175),
    MQ_BLUNDER:   QColor(220, 45, 45),
    MQ_BOOK:      QColor(170, 160, 140),
}

MQ_ICONS = {
    MQ_GOOD:      "!",
    MQ_BEST:      "!!",
    MQ_BRILLIANT: "★",
    MQ_BLUNDER:   "✕",
    MQ_BOOK:      "B",
}

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

# ── Piece-square tables and values ────────────────────────────────────────────
PIECE_VAL = {'P': 100, 'N': 320, 'B': 330, 'R': 500, 'Q': 900, 'K': 20000}

PST = {
    'P': [[0,0,0,0,0,0,0,0],[50,50,50,50,50,50,50,50],[10,10,20,30,30,20,10,10],[5,5,10,25,25,10,5,5],[0,0,0,20,20,0,0,0],[5,-5,-10,0,0,-10,-5,5],[5,10,10,-20,-20,10,10,5],[0,0,0,0,0,0,0,0]],
    'N': [[-50,-40,-30,-30,-30,-30,-40,-50],[-40,-20,0,0,0,0,-20,-40],[-30,0,10,15,15,10,0,-30],[-30,5,15,20,20,15,5,-30],[-30,0,15,20,20,15,0,-30],[-30,5,10,15,15,10,5,-30],[-40,-20,0,5,5,0,-20,-40],[-50,-40,-30,-30,-30,-30,-40,-50]],
    'B': [[-20,-10,-10,-10,-10,-10,-10,-20],[-10,0,0,0,0,0,0,-10],[-10,0,10,10,10,10,0,-10],[-10,5,5,10,10,5,5,-10],[-10,0,5,10,10,5,0,-10],[-10,10,5,10,10,5,10,-10],[-10,5,0,0,0,0,5,-10],[-20,-10,-10,-10,-10,-10,-10,-20]],
    'R': [[0,0,0,0,0,0,0,0],[5,10,10,10,10,10,10,5],[-5,0,0,0,0,0,0,-5],[-5,0,0,0,0,0,0,-5],[-5,0,0,0,0,0,0,-5],[-5,0,0,0,0,0,0,-5],[-5,0,0,0,0,0,0,-5],[0,0,0,5,5,0,0,0]],
    'Q': [[-20,-10,-10,-5,-5,-10,-10,-20],[-10,0,0,0,0,0,0,-10],[-10,0,5,5,5,5,0,-10],[-5,0,5,5,5,5,0,-5],[0,0,5,5,5,5,0,-5],[-10,5,5,5,5,5,0,-10],[-10,0,5,0,0,0,0,-10],[-20,-10,-10,-5,-5,-10,-10,-20]],
    'K': [[-30,-40,-40,-50,-50,-40,-40,-30],[-30,-40,-40,-50,-50,-40,-40,-30],[-30,-40,-40,-50,-50,-40,-40,-30],[-30,-40,-40,-50,-50,-40,-40,-30],[-20,-30,-30,-40,-40,-30,-30,-20],[-10,-20,-20,-20,-20,-20,-20,-10],[20,20,0,0,0,0,20,20],[20,30,10,0,0,10,30,20]],
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
        self.move_quality        = MQ_GOOD  # Default export badge

# ── Opening-image parsing helper ──────────────────────────────────────────────
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
                try: actual_bytes = base64.b64decode(bytes_val)
                except Exception: pass
                if actual_bytes is None:
                    try: actual_bytes = bytes(bytes_val, "utf-8").decode("unicode_escape").encode("latin1")
                    except Exception: pass
            if actual_bytes:
                pixmap = QPixmap()
                pixmap.loadFromData(actual_bytes)
        except Exception as e:
            log(f"Image byte extraction error: {e}", "OPENINGS")
    return pixmap

# ── Render Cache Helper ───────────────────────────────────────────────────────
_render_cache = {}

def get_render_assets(sz):
    tid = threading.get_ident()
    isz = int(sz * 100)
    key = (tid, isz)
    if key in _render_cache:
        return _render_cache[key]
        
    font_piece = QFont("Segoe UI Emoji", sz * 0.72)
    font_piece.setStyleStrategy(QFont.PreferAntialias)
    font_coord = QFont("Sans", max(7, int(sz * 0.13)), QFont.Bold)
    font_badge_normal = QFont("Sans", max(6, int(sz * 0.19 * 0.95)), QFont.Bold)
    font_badge_symbol = QFont("Segoe UI Emoji", max(7, int(sz * 0.19 * 1.15)), QFont.Bold)
    
    pen_white_shadow  = QPen(QColor(0, 0, 0, 50), max(1, sz * 0.03))
    pen_white_outline = QPen(QColor(0, 0, 0, 200), max(1, sz * 0.04))
    pen_black_shadow  = QPen(QColor(0, 0, 0, 60), max(1, sz * 0.03))
    pen_badge_outline = QPen(QColor(255, 255, 255, 120), max(0.8, sz * 0.008))
    
    assets = (font_piece, font_coord, font_badge_normal, font_badge_symbol,
              pen_white_shadow, pen_white_outline, pen_black_shadow, pen_badge_outline)
    _render_cache[key] = assets
    return assets