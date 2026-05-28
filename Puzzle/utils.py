#!/usr/bin/env python3
"""Logging, helper utilities, and render-asset caching."""

import re
import ast
import base64
import threading

from PySide6.QtGui import QFont, QPen, QColor
from PySide6.QtCore import Qt

from config import SQ_SIZE


# ── Logging ─────────────────────────────────────────────────────────────────

def log(msg, level="INFO"):
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{level}] {msg}", flush=True)


# ── Filename Sanitiser ──────────────────────────────────────────────────────

_SAFE_FS = re.compile(r'[\\/*?:"<>|]')

def sanitize_filename(name, max_len=120):
    s = _SAFE_FS.sub('_', name).strip('. ')
    return s[:max_len] if s else "untitled"


# ── Opening Image Parser ────────────────────────────────────────────────────

def parse_opening_image(img_val):
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
                try:
                    actual_bytes = base64.b64decode(bytes_val)
                except Exception:
                    pass
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

def get_render_assets(sz):
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

def ease_out_cubic(t):
    return 1.0 - (1.0 - t) ** 3