"""
Chess Learning App — Shared constants, logging, and optional-dependency detection.
"""

import csv, re, ast, base64

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
    """Print a timestamped log message to the terminal."""
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{level}] {msg}", flush=True)

# ── Board / rendering constants ───────────────────────────────────────────────
SQ_SIZE = 68
LIGHT_SQ  = "#F0D9B5"
DARK_SQ   = "#B58863"
SEL_COL   = (106, 175, 228, 160)
MOVE_DOT  = (0, 0, 0, 60)
CAP_RING  = (0, 0, 0, 50)
LAST_COL  = (205, 210, 106, 130)
CHECK_COL = (235, 97, 80, 170)

UNICODE_PIECES = {
    'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
    'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟'
}

FILES_STR = 'abcdefgh'
RANKS_STR = '87654321'

# ── Piece-square tables and values ────────────────────────────────────────────
PIECE_VAL = {'P': 100, 'N': 320, 'B': 330, 'R': 500, 'Q': 900, 'K': 20000}

PST = {
    'P': [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [50, 50, 50, 50, 50, 50, 50, 50],
        [10, 10, 20, 30, 30, 20, 10, 10],
        [5, 5, 10, 25, 25, 10, 5, 5],
        [0, 0, 0, 20, 20, 0, 0, 0],
        [5, -5, -10, 0, 0, -10, -5, 5],
        [5, 10, 10, -20, -20, 10, 10, 5],
        [0, 0, 0, 0, 0, 0, 0, 0],
    ],
    'N': [
        [-50, -40, -30, -30, -30, -30, -40, -50],
        [-40, -20, 0, 0, 0, 0, -20, -40],
        [-30, 0, 10, 15, 15, 10, 0, -30],
        [-30, 5, 15, 20, 20, 15, 5, -30],
        [-30, 0, 15, 20, 20, 15, 0, -30],
        [-30, 5, 10, 15, 15, 10, 5, -30],
        [-40, -20, 0, 5, 5, 0, -20, -40],
        [-50, -40, -30, -30, -30, -30, -40, -50],
    ],
    'B': [
        [-20, -10, -10, -10, -10, -10, -10, -20],
        [-10, 0, 0, 0, 0, 0, 0, -10],
        [-10, 0, 10, 10, 10, 10, 0, -10],
        [-10, 5, 5, 10, 10, 5, 5, -10],
        [-10, 0, 5, 10, 10, 5, 0, -10],
        [-10, 10, 5, 10, 10, 5, 10, -10],
        [-10, 5, 0, 0, 0, 0, 5, -10],
        [-20, -10, -10, -10, -10, -10, -10, -20],
    ],
    'R': [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [5, 10, 10, 10, 10, 10, 10, 5],
        [-5, 0, 0, 0, 0, 0, 0, -5],
        [-5, 0, 0, 0, 0, 0, 0, -5],
        [-5, 0, 0, 0, 0, 0, 0, -5],
        [-5, 0, 0, 0, 0, 0, 0, -5],
        [-5, 0, 0, 0, 0, 0, 0, -5],
        [0, 0, 0, 5, 5, 0, 0, 0],
    ],
    'Q': [
        [-20, -10, -10, -5, -5, -10, -10, -20],
        [-10, 0, 0, 0, 0, 0, 0, -10],
        [-10, 0, 5, 5, 5, 5, 0, -10],
        [-5, 0, 5, 5, 5, 5, 0, -5],
        [0, 0, 5, 5, 5, 5, 0, -5],
        [-10, 5, 5, 5, 5, 5, 0, -10],
        [-10, 0, 5, 0, 0, 0, 0, -10],
        [-20, -10, -10, -5, -5, -10, -10, -20],
    ],
    'K': [
        [-30, -40, -40, -50, -50, -40, -40, -30],
        [-30, -40, -40, -50, -50, -40, -40, -30],
        [-30, -40, -40, -50, -50, -40, -40, -30],
        [-30, -40, -40, -50, -50, -40, -40, -30],
        [-20, -30, -30, -40, -40, -30, -30, -20],
        [-10, -20, -20, -20, -20, -20, -20, -10],
        [20, 20, 0, 0, 0, 0, 20, 20],
        [20, 30, 10, 0, 0, 10, 30, 20],
    ],
}

# ── Opening-image parsing helper ──────────────────────────────────────────────
def parse_opening_image(img_val):
    """Try to extract a QPixmap from the various 'img' formats found in opening files."""
    from PySide6.QtGui import QPixmap

    pixmap = None
    img_dict = None

    if isinstance(img_val, dict):
        img_dict = img_val
    elif isinstance(img_val, str) and img_val.strip().startswith("{"):
        try:
            safe_str = img_val
            safe_str = re.sub(r'\bnull\b', 'None', safe_str)
            safe_str = re.sub(r'\btrue\b', 'True', safe_str)
            safe_str = re.sub(r'\bfalse\b', 'False', safe_str)
            safe_str = re.sub(r'\bNaN\b', 'None', safe_str)
            safe_str = re.sub(r'\bundefined\b', 'None', safe_str)
            img_dict = ast.literal_eval(safe_str)
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