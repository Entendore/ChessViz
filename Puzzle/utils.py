#!/usr/bin/env python3
"""Logging, helper utilities, render-asset caching, and centralized dependency checks."""

import re
import ast
import base64
import shutil
import threading

from PySide6.QtGui import QFont, QPen, QColor
from PySide6.QtCore import Qt

# ── Centralized Dependency Checks ───────────────────────────────────────────
# (single source of truth — all other modules import from here)

HAS_NUMBA = False
try:
    import numba  # noqa: F401
    HAS_NUMBA = True
except ImportError:
    pass

HAS_CUPY = False
try:
    import cupy as _cp  # noqa: F401
    HAS_CUPY = True
except Exception:
    pass

HAS_PANDAS = False
try:
    import pandas as _pd  # noqa: F401
    HAS_PANDAS = True
except ImportError:
    pass

HAS_PYARROW = False
try:
    import pyarrow as _pa  # noqa: F401
    HAS_PYARROW = True
except ImportError:
    pass

HAS_DUCKDB = False
try:
    import duckdb as _ddb  # noqa: F401
    HAS_DUCKDB = True
except ImportError:
    pass

HAS_FFMPEG = shutil.which("ffmpeg") is not None

# ── Logging ─────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO") -> None:
    """Print a timestamped log message to stdout."""
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{level}] {msg}", flush=True)


# ── Filename Sanitiser ──────────────────────────────────────────────────────

_SAFE_FS = re.compile(r'[\\/*?:"<>|]')

def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Strip unsafe filesystem characters and truncate."""
    s = _SAFE_FS.sub('_', name).strip('. ')
    return s[:max_len] if s else "untitled"


# ── Opening Image Parser ────────────────────────────────────────────────────

def parse_opening_image(img_val):
    """Attempt to parse an opening image from various encoded formats.

    Accepts a dict with 'bytes' key (raw bytes or base64 string),
    or a JSON-like string representation of such a dict.
    Returns a QImage on success, or None.
    """
    from PySide6.QtGui import QImage
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
        except Exception:
            pass
    if img_dict:
        try:
            bytes_val = img_dict.get('bytes')
            actual_bytes = None
            if isinstance(bytes_val, bytes):
                actual_bytes = bytes_val
            elif isinstance(bytes_val, str):
                # Try base64 first
                try:
                    actual_bytes = base64.b64decode(bytes_val)
                except Exception:
                    pass
                # Fallback: unicode-escape → latin1
                if actual_bytes is None:
                    try:
                        actual_bytes = bytes(bytes_val, "utf-8").decode(
                            "unicode_escape").encode("latin1")
                    except Exception:
                        pass
            if actual_bytes:
                img = QImage()
                img.loadFromData(actual_bytes)
                return img
        except Exception:
            pass
    return None


# ── Render-Asset Cache (thread-local) ───────────────────────────────────────

_thread_local = threading.local()

def get_render_assets(sz: int):
    """Return cached (font_piece, font_coord, font_badge_normal,
    font_badge_symbol, pen_badge_outline) for the given square size.

    Uses a thread-local cache keyed by integer size * 100 so that
    repeated calls with the same size are O(1).
    """
    isz = int(sz * 100)
    if getattr(_thread_local, 'cache_sz', -1) == isz:
        return _thread_local.assets

    font_piece = QFont("Segoe UI Emoji", sz * 0.9)
    font_piece.setStyleStrategy(QFont.PreferAntialias)

    font_coord = QFont("Sans", max(7, int(sz * 0.13)), QFont.Bold)

    font_badge_normal = QFont("Sans", max(6, int(sz * 0.19 * 0.95)), QFont.Bold)
    font_badge_symbol = QFont("Segoe UI Emoji", max(7, int(sz * 0.19 * 1.15)), QFont.Bold)

    pen_badge_outline = QPen(QColor(255, 255, 255, 120), max(0.8, sz * 0.008))

    assets = (font_piece, font_coord, font_badge_normal,
              font_badge_symbol, pen_badge_outline)
    _thread_local.cache_sz = isz
    _thread_local.assets = assets
    return assets


# ── Easing ──────────────────────────────────────────────────────────────────

def ease_out_cubic(t: float) -> float:
    """Cubic ease-out: fast start, slow end."""
    return 1.0 - (1.0 - t) ** 3


# ── Stride Fixer (Numba-optional) ──────────────────────────────────────────
# Shared by board_widget and any other module that converts QImage → numpy.
# When QImage has padding bytes per line (bpl > w*3), we must de-stride.

import numpy as np

if HAS_NUMBA:
    from numba import njit as _njit

    @_njit(cache=True, nogil=True)
    def fix_stride(raw, w, h, bpl):
        """De-stride a raw image buffer: copy row-by-row removing padding."""
        out = np.empty((h, w, 3), dtype=np.uint8)
        w3 = w * 3
        for i in range(h):
            src = i * bpl
            dst = i * w3
            for j in range(w3):
                out.flat[dst + j] = raw.flat[src + j]
        return out

    log("Numba JIT stride-fixer loaded", "UTILS")
else:
    def fix_stride(raw, w, h, bpl):
        """De-stride a raw image buffer (NumPy fallback)."""
        return raw[:, :w * 3].reshape(h, w, 3)


# ── Unified Difficulty Computation ──────────────────────────────────────────
# Replaces duplicated logic that was previously in puzzle_utils.py

def compute_difficulty(move_count: int, has_fen: bool,
                       has_rating: bool, rating_val: float) -> float:
    """Compute a normalized difficulty score in [0, 1].

    The formula weights three factors:
      - Move count (40%): longer puzzles are harder
      - FEN presence (20%): custom positions add complexity
      - Rating (40%): higher rated puzzles are harder

    Args:
        move_count: Number of half-moves in the puzzle.
        has_fen: Whether the puzzle starts from a custom position.
        has_rating: Whether a human-assigned rating exists.
        rating_val: The numeric rating (0 if unavailable).

    Returns:
        Float in [0, 1] representing normalized difficulty.
    """
    base = min(1.0, max(0.0, move_count / 8.0))
    fen_b = 0.15 if has_fen else 0.0
    rating = (min(1.0, max(0.0, rating_val / 3000.0)) if has_rating else 0.5)
    return 0.4 * base + 0.2 * fen_b + 0.4 * rating