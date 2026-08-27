#!/usr/bin/env python3
"""
Chess Puzzle App — Single-file PySide6 Application
Install:  pip install PySide6 numpy imageio[ffmpeg] chess
Optional: pip install pandas pyarrow duckdb
GPU/Accel: pip install numba cupy-cuda121
"""

import sys, os, math, time, csv, re, ast, base64, threading, shutil, tempfile, gc, wave, subprocess
import chess
import json
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QTextEdit, QFrame, QListWidget,
    QListWidgetItem, QSlider, QSpinBox, QLineEdit, QFormLayout, QComboBox,
    QProgressBar, QGroupBox, QCheckBox, QScrollArea
)
from PySide6.QtCore import Qt, QRect, QRectF, Signal, QTimer, QPointF, QUrl
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QRadialGradient,
    QImage, QPixmap, QPolygonF, QPainterPath, QTransform
)
from PySide6.QtMultimedia import QSoundEffect

csv.field_size_limit(2**31 - 1)

# ═══════════════════════════════════════════════════════════════════════════════
#  OPTIONAL DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════════

HAS_NUMPY = True
HAS_IMAGEIO = False
try:
    import imageio.v3 as iio
    HAS_IMAGEIO = True
except Exception:
    pass
HAS_PANDAS = False; HAS_PYARROW = False; HAS_DUCKDB = False
try:
    import pandas as pd; HAS_PANDAS = True
except ImportError:
    pass
if not HAS_PANDAS:
    try:
        import pyarrow.parquet as pq; HAS_PYARROW = True
    except ImportError:
        pass
try:
    import duckdb; HAS_DUCKDB = True
except ImportError:
    pass
HAS_NUMBA = False
try:
    import numba; HAS_NUMBA = True
except ImportError:
    pass
HAS_CUPY = False; _cp = None
try:
    import cupy as cp; HAS_CUPY = True
except Exception:
    pass
HAS_FFMPEG = shutil.which('ffmpeg') is not None
HAS_MOVIEPY = False
try:
    import moviepy; HAS_MOVIEPY = True
except ImportError:
    pass

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

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD / RENDERING CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

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
        self.name = name
        self.light_sq = QColor(*light); self.dark_sq = QColor(*dark)
        self.border = QColor(*border); self.highlight = QColor(*highlight)
        self.last_move = QColor(*last_move); self.arrow_clr = QColor(*arrow)
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
    def aspect_ratio(self):
        from math import gcd; g = gcd(self.width, self.height)
        return self.width // g, self.height // g

    @property
    def is_vertical(self):
        return self.height > self.width

    @property
    def is_square(self):
        return self.width == self.height

    def calc_sq_size(self):
        shorter = min(self.width, self.height)
        board_px = int(shorter * self.board_frac)
        board_px = (board_px // 8) * 8
        return max(8, board_px // 8)

    def calc_board_rect(self):
        sq = self.calc_sq_size(); bw = sq * 8; bh = sq * 8
        x = (self.width - bw) // 2; y = (self.height - bh) // 2
        return x, y, bw, bh

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
            if preset_name != "Custom":
                self.sq_size = p.calc_sq_size()

    @property
    def effective_sq_size(self):
        if self.preset_name and self.preset_name not in ("Board Only (544×544)", "Custom"):
            p = EXPORT_PRESETS.get(self.preset_name)
            if p: return p.calc_sq_size()
        return self.sq_size

    @property
    def is_vertical(self):
        return self.target_height > self.target_width

# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

_SAFE_FS = re.compile(r'[\\/*?:"<>|]')

def sanitize_filename(name, max_len=120):
    s = _SAFE_FS.sub('_', name).strip('. ')
    return s[:max_len] if s else "untitled"

def parse_opening_image(img_val):
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
            bytes_val = img_dict.get('bytes'); actual_bytes = None
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
                img = QImage(); img.loadFromData(actual_bytes); return img
        except Exception:
            pass
    return None

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
    assets = (font_piece, font_coord, font_badge_normal, font_badge_symbol, pen_badge_outline)
    _thread_local.cache_sz = isz; _thread_local.assets = assets
    return assets

# ═══════════════════════════════════════════════════════════════════════════════
#  CHESS ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class ChessEngine:
    def __init__(self):
        self.board = chess.Board(); self.game_over = False
        self.result = ""; self.last_move = None

    def reset(self):
        self.board.reset(); self.game_over = False
        self.result = ""; self.last_move = None

    @staticmethod
    def sq_to_rc(sq):
        return 7 - chess.square_rank(sq), chess.square_file(sq)

    @staticmethod
    def rc_to_sq(r, c):
        return chess.square(c, 7 - r)

    @property
    def turn(self):
        return 'w' if self.board.turn == chess.WHITE else 'b'

    def color_of(self, piece):
        return 'w' if piece.color == chess.WHITE else 'b'

    def check_squares(self):
        if self.board.is_check():
            return [self.sq_to_rc(self.board.king(self.board.turn))]
        return []

    def legal_moves(self, r, c):
        sq = self.rc_to_sq(r, c)
        return [self.sq_to_rc(m.to_square) for m in self.board.legal_moves
                if m.from_square == sq]

    def make_move(self, fr, fc, tr, tc, promo=None):
        from_sq = self.rc_to_sq(fr, fc); to_sq = self.rc_to_sq(tr, tc)
        piece = self.board.piece_at(from_sq)
        if not piece:
            return None
        promotion = None
        if piece.piece_type == chess.PAWN:
            if (piece.color == chess.WHITE and tr == 0) or \
               (piece.color == chess.BLACK and tr == 7):
                if promo:
                    promotion = chess.PIECE_SYMBOLS.index(promo.lower()) + 1
                else:
                    promotion = chess.QUEEN
        move = chess.Move(from_sq, to_sq, promotion=promotion)
        if move not in self.board.legal_moves:
            return None
        is_castle = self.board.is_castling(move)
        is_ep = self.board.is_en_passant(move)
        if is_ep:
            ep_cap_sq = chess.square(chess.square_file(to_sq), chess.square_rank(from_sq))
            cap = self.board.piece_at(ep_cap_sq)
        else:
            cap = self.board.piece_at(to_sq)
        captured = cap.symbol() if cap else '.'
        notation = self.board.san(move)
        piece_obj = chess.Piece(piece.piece_type, piece.color)
        self.board.push(move)
        self.last_move = ((fr, fc), (tr, tc))
        self.game_over = self.board.is_game_over()
        self.result = self.board.result() if self.game_over else ""
        return {
            'from': (fr, fc), 'to': (tr, tc), 'piece': piece.symbol(),
            'piece_obj': piece_obj, 'captured': captured,
            'castle': is_castle, 'ep': is_ep, 'promo': promo,
            'check': self.board.is_check(), 'mate': self.board.is_checkmate(),
            'notation': notation,
        }

    def make_move_uci(self, uci_str):
        move = chess.Move.from_uci(uci_str)
        if move in self.board.legal_moves:
            fr, fc = self.sq_to_rc(move.from_square)
            tr, tc = self.sq_to_rc(move.to_square)
            promo = chess.piece_symbol(move.promotion) if move.promotion else None
            return self.make_move(fr, fc, tr, tc, promo)
        return None

    def undo(self):
        if len(self.board.move_stack) > 0:
            self.board.pop()
            self.game_over = self.board.is_game_over()
            self.result = self.board.result() if self.game_over else ""
            if self.board.move_stack:
                last = self.board.peek()
                self.last_move = (self.sq_to_rc(last.from_square),
                                  self.sq_to_rc(last.to_square))
            else:
                self.last_move = None
            return True
        return False

    def load_fen(self, fen):
        self.board.set_fen(fen)
        self.game_over = self.board.is_game_over()
        self.result = self.board.result() if self.game_over else ""
        self.last_move = None

# ═══════════════════════════════════════════════════════════════════════════════
#  SOUND MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

if HAS_NUMBA:
    from numba import njit
    @njit(cache=True, nogil=True)
    def _nb_sin(freq, n_samples, volume, sr):
        out = np.empty(n_samples, dtype=np.float64)
        two_pi = 2.0 * math.pi
        for i in range(n_samples):
            out[i] = 32767.0 * volume * math.sin(two_pi * freq * i / sr)
        return out
    @njit(cache=True, nogil=True)
    def _nb_sweep(start_freq, end_freq, n_samples, volume, sr):
        out = np.empty(n_samples, dtype=np.float64)
        two_pi = 2.0 * math.pi
        for i in range(n_samples):
            f = start_freq + (end_freq - start_freq) * float(i) / n_samples
            out[i] = 32767.0 * volume * math.sin(two_pi * f * i / sr)
        return out
    @njit(cache=True, nogil=True)
    def _nb_env(samples, attack_s, release_s, sr):
        out = samples.copy(); n = len(out)
        ai = min(int(sr * attack_s), n); ri = min(int(sr * release_s), n)
        for i in range(ai): out[i] *= float(i) / float(ai)
        for i in range(ri): out[-(i + 1)] *= float(i) / float(ri)
        return out
    @njit(cache=True, nogil=True)
    def _nb_mix(a, b):
        na, nb = len(a), len(b); n = max(na, nb)
        out = np.zeros(n, dtype=np.float64)
        for i in range(na): out[i] += a[i]
        for i in range(nb): out[i] += b[i]
        return out
    @njit(cache=True, nogil=True)
    def _nb_clip_i16(samples):
        n = len(samples); out = np.empty(n, dtype=np.int16)
        for i in range(n):
            v = samples[i]
            if v > 32767.0: v = 32767.0
            elif v < -32768.0: v = -32768.0
            out[i] = np.int16(v)
        return out
    log("Numba JIT audio primitives loaded", "SOUND")
else:
    def _nb_sin(freq, n_samples, volume, sr):
        t = np.arange(n_samples, dtype=np.float64)
        return 32767.0 * volume * np.sin(2.0 * np.pi * freq * t / sr)
    def _nb_sweep(start_freq, end_freq, n_samples, volume, sr):
        i = np.arange(n_samples, dtype=np.float64)
        f = start_freq + (end_freq - start_freq) * i / n_samples
        return 32767.0 * volume * np.sin(2.0 * np.pi * f * i / sr)
    def _nb_env(samples, attack_s, release_s, sr):
        out = samples.copy(); n = len(out)
        ai = min(int(sr * attack_s), n); ri = min(int(sr * release_s), n)
        if ai > 1: out[:ai] *= np.linspace(0, 1, ai)
        if ri > 1: out[-ri:] *= np.linspace(0, 1, ri)[::-1]
        return out
    def _nb_mix(a, b):
        na, nb = len(a), len(b); n = max(na, nb)
        out = np.zeros(n, dtype=np.float64); out[:na] += a; out[:nb] += b
        return out
    def _nb_clip_i16(samples):
        return np.clip(samples, -32768, 32767).astype(np.int16)

def _sin(freq, duration, volume=0.5, sr=44100):
    return _nb_sin(freq, int(sr * duration), volume, sr)
def _sweep(start_freq, end_freq, duration, volume=0.5, sr=44100):
    return _nb_sweep(start_freq, end_freq, int(sr * duration), volume, sr)
def _env(samples, attack=0.01, release=0.02, sr=44100):
    return _nb_env(samples, attack, release, sr)
def _mix(a, b): return _nb_mix(a, b)
def _to_i16(samples): return _nb_clip_i16(samples)

class SoundManager:
    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="chess_sfx_")
        self.sounds = {}; self._enabled = True; self._volume = 0.7
        self._gen_all(); self._load_all()

    @staticmethod
    def _wav(path, samples, sr=44100):
        int_samples = _to_i16(samples)
        with wave.open(path, 'w') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(int_samples.tobytes())

    def _gen_all(self):
        sr = 44100; d = self.tmpdir
        self._wav(os.path.join(d, "move.wav"), _env(_sin(800, 0.06, 0.4), 0.005, 0.03))
        self._wav(os.path.join(d, "capture.wav"), _env(_mix(_sin(300, 0.10, 0.5), _sin(600, 0.08, 0.3)), 0.005, 0.04))
        self._wav(os.path.join(d, "check.wav"), _env(_mix(_sin(1000, 0.12, 0.5), _sin(1250, 0.10, 0.3)), 0.005, 0.04))
        cm = np.concatenate([_sin(800, 0.15, 0.5), _sin(600, 0.15, 0.5), _sin(400, 0.25, 0.5)])
        self._wav(os.path.join(d, "checkmate.wav"), _env(cm, 0.01, 0.08))
        self._wav(os.path.join(d, "castle.wav"), _env(_sweep(400, 800, 0.15, 0.4), 0.005, 0.03))
        self._wav(os.path.join(d, "error.wav"), _env(_sin(200, 0.10, 0.4), 0.005, 0.03))
        self._wav(os.path.join(d, "promote.wav"), _env(_sweep(400, 800, 0.2, 0.4), 0.01, 0.05))
        start_tone = np.concatenate([_sin(523, 0.12, 0.4), np.zeros(int(sr * 0.03), dtype=np.float64), _sin(659, 0.18, 0.4)])
        self._wav(os.path.join(d, "start.wav"), _env(start_tone, 0.005, 0.04))

    def _load_all(self):
        for n in ("move", "capture", "check", "checkmate", "castle", "error", "promote", "start"):
            e = QSoundEffect()
            e.setSource(QUrl.fromLocalFile(os.path.join(self.tmpdir, f"{n}.wav")))
            e.setVolume(self._volume); self.sounds[n] = e

    def set_volume(self, vol):
        self._volume = max(0.0, min(1.0, vol))
        for s in self.sounds.values(): s.setVolume(self._volume)

    def set_enabled(self, enabled): self._enabled = enabled

    def play(self, name):
        if not self._enabled: return
        s = self.sounds.get(name)
        if s: s.stop(); s.play()

    def cleanup(self):
        try:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            log("Sound temp directory cleaned up", "SOUND")
        except Exception as e:
            log(f"Sound cleanup error: {e}", "SOUND")

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD WIDGET
# ═══════════════════════════════════════════════════════════════════════════════

if HAS_NUMBA:
    from numba import njit as _njit2
    @_njit2(cache=True, nogil=True)
    def _fix_stride_nb(raw, w, h, bpl):
        out = np.empty((h, w, 3), dtype=np.uint8); w3 = w * 3
        for i in range(h):
            src = i * bpl; dst = i * w3
            for j in range(w3): out.flat[dst + j] = raw.flat[src + j]
        return out
    log("Numba JIT stride-fixer loaded", "BOARD")
else:
    def _fix_stride_nb(raw, w, h, bpl):
        return raw[:, :w * 3].reshape(h, w, 3)

def _ease_out_cubic(t):
    return 1.0 - (1.0 - t) ** 3

class ChessBoardWidget(QWidget):
    move_made = Signal(str)

    def __init__(self, engine, sound_mgr, parent=None):
        super().__init__(parent)
        self.engine = engine; self.snd = sound_mgr
        self.selected = None; self.legal_targets = []
        self.setFixedSize(SQ_SIZE * 8, SQ_SIZE * 8); self.setMouseTracking(True)
        self.animating = False; self.anim_from = None; self.anim_to = None
        self.anim_piece_obj = None; self.anim_captured = '.'
        self.anim_progress = 0.0; self.anim_speed = ANIM_SPEED_DEFAULT
        self.anim_start_time = 0.0; self.pending_notation = None
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(1000 // ANIM_FPS)
        self._anim_timer.timeout.connect(self._anim_tick)
        self.current_theme = THEMES["Classic"]

    def start_animation(self, fr, fc, tr, tc, piece_obj, captured='.', notation=''):
        self.animating = True; self.anim_from = (fr, fc); self.anim_to = (tr, tc)
        self.anim_piece_obj = piece_obj; self.anim_captured = captured
        self.anim_progress = 0.0; self.anim_start_time = time.perf_counter()
        self.pending_notation = notation; self._anim_timer.start()

    def _anim_tick(self):
        elapsed = time.perf_counter() - self.anim_start_time
        duration = self.anim_speed / 1000.0
        self.anim_progress = min(1.0, elapsed / duration) if duration > 0 else 1.0
        self.update()
        if self.anim_progress >= 1.0:
            self._anim_timer.stop(); self.animating = False
            self.anim_piece_obj = None; self.update()
            if self.pending_notation:
                self.move_made.emit(self.pending_notation)
                self.pending_notation = None

    def _get_anim_state(self):
        if not self.animating: return None
        t_eased = _ease_out_cubic(self.anim_progress)
        return {'from': self.anim_from, 'to': self.anim_to,
                'piece_obj': self.anim_piece_obj, 'progress': t_eased}

    def paintEvent(self, e):
        chk = self.engine.check_squares()
        img = self.render_frame(self.engine.board, self.engine.last_move,
                                self.selected, self.legal_targets,
                                check_squares=chk, anim_state=self._get_anim_state(),
                                theme=self.current_theme)
        pix = QPixmap.fromImage(img)
        painter = QPainter(self)
        painter.drawPixmap(0, 0, pix)
        painter.end()

    @staticmethod
    def render_frame(board, last_move=None, selected=None, legal_targets=None,
                     text_overlay="", check_squares=None, anim_state=None,
                     sq_size=SQ_SIZE, show_arrow=True, theme=None):
        if theme is None: theme = THEMES["Classic"]
        sz = sq_size
        img = QImage(sz * 8, sz * 8, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        (font_piece, font_coord, font_badge_normal, font_badge_symbol,
         pen_badge_outline) = get_render_assets(sz)
        check_set = set(check_squares or []); skip_sq = set()
        if anim_state:
            skip_sq.add(anim_state['from']); skip_sq.add(anim_state['to'])

        for sq in chess.SQUARES:
            r, c = 7 - chess.square_rank(sq), chess.square_file(sq)
            x, y = c * sz, r * sz
            is_light = (r + c) % 2 == 0
            color = theme.light_sq if is_light else theme.dark_sq
            p.fillRect(x, y, sz, sz, color)
            if last_move and (r, c) in last_move:
                p.fillRect(x, y, sz, sz, theme.last_move)
            if selected and (r, c) == selected:
                p.fillRect(x, y, sz, sz, theme.highlight)
            if (r, c) in check_set:
                grad = QRadialGradient(x + sz / 2, y + sz / 2, sz * 0.7)
                grad.setColorAt(0, QColor(255, 30, 30, 180))
                grad.setColorAt(1, QColor(255, 0, 0, 0))
                p.setBrush(QBrush(grad)); p.setPen(Qt.NoPen)
                p.drawRect(x, y, sz, sz)
            if legal_targets and (r, c) in legal_targets:
                cx, cy = x + sz // 2, y + sz // 2
                if board.piece_at(sq) is not None:
                    p.setPen(QPen(QColor(0, 0, 0, 90), max(3, sz // 14)))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(cx - sz * 5 // 12, cy - sz * 5 // 12,
                                  sz * 10 // 12, sz * 10 // 12)
                else:
                    p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 90))
                    p.drawEllipse(cx - sz // 6, cy - sz // 6, sz // 3, sz // 3)

        if show_arrow and last_move:
            (fr, fc), (tr, tc) = last_move
            ChessBoardWidget._draw_arrow(p, fc * sz + sz // 2, fr * sz + sz // 2,
                                         tc * sz + sz // 2, tr * sz + sz // 2,
                                         theme.arrow_clr, sz)

        for sq in chess.SQUARES:
            r, c = 7 - chess.square_rank(sq), chess.square_file(sq)
            if (r, c) in skip_sq: continue
            piece = board.piece_at(sq)
            if piece: ChessBoardWidget._draw_piece(p, piece, r, c, sz, font_piece)

        if anim_state and anim_state.get('captured', '.') != '.':
            fr, fc_ = anim_state['from']; tr, tc_ = anim_state['to']
            cap_piece = board.piece_at(chess.square(tc_, 7 - tr))
            if cap_piece is None:
                sym = anim_state['captured']; is_w = sym.isupper()
                pt_map = {'K': chess.KING, 'Q': chess.QUEEN, 'R': chess.ROOK,
                          'B': chess.BISHOP, 'N': chess.KNIGHT, 'P': chess.PAWN}
                pt = pt_map.get(sym.upper())
                if pt:
                    cap_piece = chess.Piece(pt, chess.WHITE if is_w else chess.BLACK)
                    fade = max(0, int(200 * (1.0 - anim_state['progress'])))
                    p.setOpacity(fade / 255.0)
                    ChessBoardWidget._draw_piece(p, cap_piece, tr, tc_, sz, font_piece)
                    p.setOpacity(1.0)

        if anim_state:
            fr, fc_ = anim_state['from']; tr, tc_ = anim_state['to']
            t = anim_state['progress']
            anim_piece_obj = anim_state.get('piece_obj')
            if anim_piece_obj:
                lift = 4.0 * t * (1.0 - t) * 0.15
                scale = 1.0 + 4.0 * t * (1.0 - t) * 0.08
                ir = fr + (tr - fr) * t; ic = fc_ + (tc_ - fc_) * t
                shadow_alpha = 30 + int(70 * (lift / 0.15))
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, shadow_alpha))
                sy = ir * sz + sz * 0.82
                p.drawEllipse(QRectF(ic * sz + (sz * scale - sz * 0.65) / 2,
                                     sy, sz * 0.65, sz * 0.12))
                w, h = sz * scale, sz * scale
                y_lift = ir * sz - (sz * lift)
                ChessBoardWidget._draw_piece_at(p, anim_piece_obj, y_lift / sz, ic, sz, w, h, font_piece)

        p.setFont(font_coord)
        coord_margin = max(3, int(sz * 0.04)); coord_sz = max(12, sz // 5)
        for c in range(8):
            is_light = (7 + c) % 2 == 0
            col = theme.dark_sq if is_light else theme.light_sq
            p.setPen(col)
            p.drawText(QRect(c * sz + sz - coord_sz - coord_margin,
                             7 * sz + coord_margin, coord_sz, coord_sz),
                       Qt.AlignCenter, FILES_STR[c])
        for r in range(8):
            is_light = r % 2 == 0
            col = theme.dark_sq if is_light else theme.light_sq
            p.setPen(col)
            p.drawText(QRect(coord_margin, r * sz + coord_margin,
                             coord_sz, coord_sz), Qt.AlignCenter, RANKS_STR[r])

        if text_overlay:
            p.fillRect(0, sz * 4 - 28, sz * 8, 56, QColor(0, 0, 0, 200))
            p.setPen(Qt.white); p.setFont(QFont("Sans", max(12, sz // 4), QFont.Bold))
            p.drawText(QRect(0, sz * 4 - 28, sz * 8, 56), Qt.AlignCenter, text_overlay)
        p.end(); return img

    @staticmethod
    def render_card(text, bg="#1a1a2e", fg="#e0e0e0", w=544, h=544,
                    width=None, height=None, font_size=36, sub_text="",
                    bg_color=None, fg_color=None):
        bg_val = bg if bg != "#1a1a2e" else (bg_color or bg)
        fg_val = fg if fg != "#e0e0e0" else (fg_color or fg)
        w_val = width if width is not None else w
        h_val = height if height is not None else h
        img = QImage(w_val, h_val, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(bg_val))
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(fg_val)); p.setFont(QFont("Sans", font_size, QFont.Bold))
        p.drawText(QRect(0, 0, w_val, h_val), Qt.AlignCenter, text)
        if sub_text:
            p.setFont(QFont("Sans", max(10, font_size // 2)))
            p.setPen(QColor(fg_val).lighter(140))
            p.drawText(QRect(0, h_val * 3 // 5, w_val, h_val // 4),
                       Qt.AlignCenter, sub_text)
        p.end(); return img

    @staticmethod
    def _draw_piece(p, piece_obj, row, col, sz, font):
        ChessBoardWidget._draw_piece_at(p, piece_obj, float(row), float(col), sz, sz, sz, font)

    @staticmethod
    def _draw_piece_at(p, piece_obj, row_f, col_f, sz, w, h, font):
        FIT_FRAC = 0.85
        is_w = piece_obj.color == chess.WHITE
        glyph = PIECE_SYM[(piece_obj.piece_type, piece_obj.color)]
        px = col_f * sz; py = row_f * sz
        rect = QRectF(px + (sz - w) / 2, py + (sz - h) / 2, w, h)
        center = rect.center(); p.setFont(font)
        path = QPainterPath(); path.addText(QPointF(0, 0), font, glyph)
        br = path.boundingRect(); path.translate(-br.center().x(), -br.center().y())
        if br.width() > 0 and br.height() > 0:
            sx = (w * FIT_FRAC) / br.width(); sy = (h * FIT_FRAC) / br.height()
            s = min(sx, sy); path = QTransform.fromScale(s, s).map(path)
        path.translate(center.x(), center.y())
        if is_w:
            shadow = QPainterPath(path); shadow.translate(1.5, 2.0)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 50)); p.drawPath(shadow)
            olw = max(1.2, sz * 0.028)
            p.setPen(QPen(QColor(30, 30, 30), olw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QColor(255, 255, 255)); p.drawPath(path)
        else:
            shadow = QPainterPath(path); shadow.translate(1.5, 2.0)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 60)); p.drawPath(shadow)
            olw = max(0.8, sz * 0.018)
            p.setPen(QPen(QColor(10, 10, 10), olw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QColor(40, 40, 40)); p.drawPath(path)

    @staticmethod
    def _draw_arrow(painter, fx, fy, tx, ty, color, sz):
        dx = tx - fx; dy = ty - fy; dist = max(1, math.hypot(dx, dy))
        margin = sz * 0.22
        fx2 = fx + dx * margin / dist; fy2 = fy + dy * margin / dist
        tx2 = tx - dx * margin / dist; ty2 = ty - dy * margin / dist
        painter.setPen(QPen(color, max(2, sz // 20), Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(int(fx2), int(fy2), int(tx2), int(ty2))
        angle = math.atan2(dy, dx); a_sz = sz * 0.22
        p1x = tx2 - a_sz * math.cos(angle - 0.45)
        p1y = ty2 - a_sz * math.sin(angle - 0.45)
        p2x = tx2 - a_sz * math.cos(angle + 0.45)
        p2y = ty2 - a_sz * math.sin(angle + 0.45)
        tri = QPolygonF([QPointF(tx2, ty2), QPointF(p1x, p1y), QPointF(p2x, p2y)])
        painter.setBrush(color); painter.setPen(Qt.NoPen); painter.drawPolygon(tri)

    @staticmethod
    def qimage_to_np(img):
        img2 = img.convertToFormat(QImage.Format_RGB888)
        ptr = img2.constBits()
        if hasattr(ptr, 'setsize'): ptr.setsize(img2.sizeInBytes())
        w = img2.width(); h = img2.height(); bpl = img2.bytesPerLine()
        raw = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl)).copy()
        if bpl == w * 3: return raw.reshape((h, w, 3))
        return _fix_stride_nb(raw, w, h, bpl)

    @staticmethod
    def qimage_to_np_batch(images, use_gpu=False):
        if not images: return np.empty((0, 0, 0, 3), dtype=np.uint8)
        arrays = [ChessBoardWidget.qimage_to_np(im) for im in images]
        stack = np.stack(arrays)
        if use_gpu and HAS_CUPY:
            import cupy as _cp; return _cp.asarray(stack)
        return stack

    def mousePressEvent(self, e):
        if self.animating or self.engine.game_over: return
        c = int(e.position().x()) // SQ_SIZE
        r = int(e.position().y()) // SQ_SIZE
        if not (0 <= r < 8 and 0 <= c < 8): return
        sq = self.engine.rc_to_sq(r, c)
        piece = self.engine.board.piece_at(sq)
        if self.selected:
            sr, sc = self.selected
            if (r, c) in self.legal_targets:
                info = self.engine.make_move(sr, sc, r, c)
                if info:
                    is_capture = info['captured'] != '.'
                    sfx = ("capture" if is_capture
                           else "castle" if info['castle'] else "move")
                    if info['mate']: sfx = "checkmate"
                    elif info['check']: sfx = "check"
                    self.snd.play(sfx)
                    if self.anim_speed > 0:
                        self.start_animation(sr, sc, r, c, info['piece_obj'],
                                             info['captured'], info['notation'])
                    else:
                        self.move_made.emit(info['notation'])
            self.selected = None; self.legal_targets = []
        else:
            if piece and piece.color == self.engine.board.turn:
                self.selected = (r, c)
                self.legal_targets = self.engine.legal_moves(r, c)
                if not self.legal_targets:
                    self.snd.play("error"); self.selected = None
        self.update()

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE LOADER
# ═══════════════════════════════════════════════════════════════════════════════

_CHUNK = 4096
_CSV_PROCESS_CHUNK = 50_000
_PARQUET_BATCH = 50_000

_UCI_RE = re.compile(r'^[a-h][1-8][a-h][1-8][qrbn]?$')
_MVNUM_RE = re.compile(r'^\d+\.+$')
_RESULT_RE = frozenset({'1-0', '0-1', '1/2-1/2', '*'})

def _clean_move_tokens(tokens):
    out = []
    for t in tokens:
        t = t.strip()
        if not t or _MVNUM_RE.match(t) or t in _RESULT_RE: continue
        t = t.rstrip('.')
        if not t: continue
        out.append(t)
    return out

def _detect_move_format(tokens):
    for t in tokens:
        if _UCI_RE.match(t): return 'uci'
        return 'san'
    return 'uci'

def _san_to_uci(tokens, fen=''):
    board = chess.Board(fen) if fen else chess.Board()
    result = []
    for t in tokens:
        try:
            m = board.parse_san(t); result.append(m.uci()); board.push(m); continue
        except Exception: pass
        try:
            m = chess.Move.from_uci(t)
            if m in board.legal_moves: result.append(t); board.push(m); continue
        except Exception: pass
        break
    return result

def _extract_uci_moves(row):
    raw_val = ''
    for col in ('uci', 'moves', 'pgn'):
        v = row.get(col, '')
        if v and str(v).strip(): raw_val = v; break
    tokens = _parse_uci_value(raw_val)
    tokens = _clean_move_tokens(tokens)
    if not tokens: return []
    fen = str(row.get('fen', row.get('epd', ''))).strip()
    if fen and len(fen.split()) < 6: fen += " 0 1"
    fmt = _detect_move_format(tokens)
    if fmt == 'san':
        uci_moves = _san_to_uci(tokens, fen)
        if uci_moves: return uci_moves
    return tokens

if HAS_NUMBA:
    from numba import njit as _njit3, prange as _prange
    @_njit3(cache=True, nogil=True)
    def _count_moves_nb(data, offsets, lengths):
        n = len(offsets); out = np.empty(n, dtype=np.int64); comma = np.uint8(44)
        for i in range(n):
            ln = lengths[i]
            if ln == 0: out[i] = 0; continue
            c = 1; s = offsets[i]; e = s + ln
            for j in range(s, e):
                if data[j] == comma: c += 1
            out[i] = c
        return out
    @_njit3(cache=True, nogil=True)
    def _validate_uci_first_nb(data, offsets, lengths):
        n = len(offsets); valid = np.ones(n, dtype=np.bool_)
        for i in range(n):
            s = offsets[i]; ln = lengths[i]
            if ln == 0 or ln < 4: valid[i] = False; continue
            for j in range(4):
                b = int(data[s + j])
                if not ((48 <= b <= 57) or (97 <= b <= 122)): valid[i] = False; break
        return valid
    @_njit3(cache=True, nogil=True)
    def _compute_difficulty_nb(move_counts, has_fen, has_rating, rating_vals):
        n = len(move_counts); out = np.empty(n, dtype=np.float64)
        for i in range(n):
            base = min(1.0, max(0.0, float(move_counts[i]) / 8.0))
            fen_b = 0.15 if has_fen[i] else 0.0
            if has_rating[i]: rating = min(1.0, max(0.0, rating_vals[i] / 3000.0))
            else: rating = 0.5
            out[i] = 0.4 * base + 0.2 * fen_b + 0.4 * rating
        return out
    log("Numba JIT puzzle helpers ready", "PUZZLE")
else:
    def _count_moves_nb(data, offsets, lengths):
        out = np.empty(len(offsets), dtype=np.int64)
        for i in range(len(offsets)):
            if lengths[i] == 0: out[i] = 0
            else:
                seg = data[offsets[i]:offsets[i] + lengths[i]].tobytes()
                out[i] = seg.count(b',') + 1
        return out
    def _validate_uci_first_nb(data, offsets, lengths):
        valid = np.ones(len(offsets), dtype=np.bool_)
        for i in range(len(offsets)):
            if lengths[i] < 4: valid[i] = lengths[i] > 0
        return valid
    def _compute_difficulty_nb(move_counts, has_fen, has_rating, rating_vals):
        n = len(move_counts); out = np.empty(n, dtype=np.float64)
        for i in range(n):
            base = min(1.0, max(0.0, float(move_counts[i]) / 8.0))
            fen_b = 0.15 if has_fen[i] else 0.0
            rating = (min(1.0, max(0.0, rating_vals[i] / 3000.0)) if has_rating[i] else 0.5)
            out[i] = 0.4 * base + 0.2 * fen_b + 0.4 * rating
        return out

def _pack_strings(strings):
    encoded = [s.encode('utf-8') if s else b'' for s in strings]
    lengths = np.array([len(e) for e in encoded], dtype=np.int64)
    offsets = np.empty(len(encoded), dtype=np.int64); total = 0
    for i in range(len(encoded)): offsets[i] = total; total += lengths[i]
    buf = b''.join(encoded)
    data = (np.frombuffer(buf, dtype=np.uint8).copy() if buf else np.empty(0, dtype=np.uint8))
    return data, offsets, lengths

def batch_count_moves(move_strings):
    if not move_strings: return np.array([], dtype=np.int64)
    data, offsets, lengths = _pack_strings(move_strings)
    return _count_moves_nb(data, offsets, lengths)

def batch_validate_uci(move_strings):
    if not move_strings: return np.array([], dtype=np.bool_)
    data, offsets, lengths = _pack_strings(move_strings)
    return _validate_uci_first_nb(data, offsets, lengths)

if HAS_CUPY:
    import cupy as _cp_gpu
    def gpu_difficulty_scores(move_counts, has_fen, has_rating, rating_vals):
        mc_gpu = _cp_gpu.asarray(move_counts.astype(np.float64))
        hf_gpu = _cp_gpu.asarray(has_fen.astype(np.float64))
        hr_gpu = _cp_gpu.asarray(has_rating.astype(np.float64))
        rv_gpu = _cp_gpu.asarray(rating_vals.astype(np.float64))
        base = _cp_gpu.clip(mc_gpu / 8.0, 0.0, 1.0)
        fen_b = 0.15 * hf_gpu
        rating = _cp_gpu.where(hr_gpu > 0, _cp_gpu.clip(rv_gpu / 3000.0, 0.0, 1.0), 0.5)
        return _cp_gpu.asnumpy(0.4 * base + 0.2 * fen_b + 0.4 * rating)
    log("CuPy GPU puzzle helpers ready", "PUZZLE")
else:
    _cp_gpu = None
    def gpu_difficulty_scores(move_counts, has_fen, has_rating, rating_vals):
        return _compute_difficulty_nb(move_counts, has_fen, has_rating, rating_vals)

def _parse_uci_value(val):
    if isinstance(val, list):
        flat = []
        for item in val:
            if isinstance(item, str): flat.extend(item.replace(',', ' ').split())
            elif item is not None:
                s = str(item).strip().replace(',', ' ')
                if s: flat.extend(s.split())
        return flat
    s = str(val).strip().replace(',', ' ')
    return s.split() if s else []

def _rating_category(rating):
    if rating < 800: return "Beginner"
    if rating < 1200: return "Easy"
    if rating < 1600: return "Medium"
    if rating < 2000: return "Hard"
    return "Expert"

def _generate_name(row, uci_moves, idx):
    number = idx + 1; attrs = []
    name = str(row.get('name', '')).strip()
    if name and name.lower() not in ('nan', 'none', ''): attrs.append(name)
    themes = str(row.get('themes', row.get('theme', ''))).strip()
    if themes and themes.lower() not in ('nan', 'none', ''): attrs.append(themes)
    opening = str(row.get('opening', row.get('opening_tags', row.get('openingtags', '')))).strip()
    if opening and opening.lower() not in ('nan', 'none', ''): attrs.append(opening)
    for rkey in ('rating', 'elo', 'difficulty', 'score'):
        rval = str(row.get(rkey, '')).strip()
        if rval and rval.lower() not in ('nan', 'none', ''):
            try:
                rv = float(rval); attrs.append(f"{_rating_category(rv)} ({int(rv)})"); break
            except ValueError: pass
    if not name:
        white = str(row.get('white', '')).strip(); black = str(row.get('black', '')).strip()
        if white and black: attrs.append(f"{white} vs {black}")
    if not name:
        event = str(row.get('event', '')).strip()
        if event and event.lower() not in ('nan', 'none', ''): attrs.append(event)
    eco = str(row.get('eco', '')).strip()
    if eco and eco.lower() not in ('nan', 'none', ''): attrs.append(f"ECO {eco}")
    if attrs: return f"Puzzle #{number} — {' | '.join(attrs)}"
    return _generate_name_fallback(row, uci_moves, idx)

def _generate_name_fallback(row, uci_moves, idx):
    number = idx + 1
    ignore = frozenset({'fen', 'moves', 'uci', 'pgn', 'id', 'name', 'img',
                        'desc', 'description', 'white', 'black', 'event',
                        'rating', 'difficulty', 'score', 'elo', 'themes',
                        'theme', 'opening', 'opening_tags', 'openingtags', 'eco'})
    parts = []
    for k, v in row.items():
        val = str(v).strip() if v is not None else ''
        if k not in ignore and val and val.lower() not in ('nan', 'none', ''):
            parts.append(f"{k.title()}: {val}")
            if len(parts) == 2: break
    if parts: return f"Puzzle #{number} — {' | '.join(parts)}"
    if uci_moves: return f"Puzzle #{number} — {uci_moves[0]}…"
    return f"Puzzle #{number}"

def _compute_iterative_difficulty(row, uci_moves):
    move_count = len(uci_moves)
    base = min(1.0, max(0.0, move_count / 8.0))
    fen = str(row.get('fen', '')).strip()
    fen_b = 0.15 if fen else 0.0
    rating = 0.5
    for rkey in ('rating', 'elo', 'difficulty', 'score'):
        rval = str(row.get(rkey, '')).strip()
        if rval and rval.lower() not in ('nan', 'none', ''):
            try:
                rv = float(rval); rating = min(1.0, max(0.0, rv / 3000.0)); break
            except ValueError: pass
    return 0.4 * base + 0.2 * fen_b + 0.4 * rating

def _process_rows_iterative(rows):
    puzzles = []
    for idx, row in enumerate(rows):
        row = {str(k).lower(): (v if v is not None else '') for k, v in row.items()}
        uci_moves = _extract_uci_moves(row)
        name = _generate_name(row, uci_moves, idx)
        difficulty = _compute_iterative_difficulty(row, uci_moves)
        puzzles.append({'name': name, 'fen': str(row.get('fen', '')),
                        'moves': uci_moves, 'desc': str(row.get('desc', row.get('description', ''))),
                        'difficulty': difficulty})
    return puzzles

def _process_rows_vectorized(rows):
    import pandas as pd
    df = pd.DataFrame(rows); df.columns = df.columns.str.lower().str.strip()
    str_cols = df.select_dtypes(include=['object']).columns
    df[str_cols] = df[str_cols].fillna(''); n = len(df)
    moves_col = None
    for candidate in ('uci', 'moves', 'pgn'):
        if candidate in df.columns: moves_col = candidate; break
    moves_series = (df[moves_col] if moves_col else pd.Series([''] * n, index=df.index))
    uci_moves_list = moves_series.apply(_parse_uci_value)
    move_strs = moves_series.astype(str).tolist()
    move_counts = batch_count_moves(move_strs)
    uci_valid = batch_validate_uci(move_strs)
    invalid_n = int((~uci_valid).sum())
    if invalid_n:
        log(f"Note: {invalid_n}/{n} rows have non-UCI first token", "PUZZLE")
    has_fen = np.array([bool(str(v).strip()) for v in df.get('fen', pd.Series('', index=df.index))], dtype=np.bool_)
    rating_col = None
    for candidate in ('rating', 'difficulty', 'score', 'elo'):
        if candidate in df.columns: rating_col = candidate; break
    if rating_col:
        rating_vals = pd.to_numeric(df[rating_col], errors='coerce').fillna(0).values.astype(np.float64)
        has_rating = rating_vals > 0
    else:
        rating_vals = np.zeros(n, dtype=np.float64); has_rating = np.zeros(n, dtype=np.bool_)
    difficulty = gpu_difficulty_scores(move_counts, has_fen, has_rating, rating_vals)
    fen_col = ('fen' if 'fen' in df.columns else None)
    desc_col = ('desc' if 'desc' in df.columns else 'description' if 'description' in df.columns else None)
    fens = (df[fen_col].astype(str) if fen_col else pd.Series([''] * n, index=df.index))
    descs = (df[desc_col].astype(str) if desc_col else pd.Series([''] * n, index=df.index))

    # Generate names
    names = np.empty(n, dtype=object)
    def _str_col(col_name):
        s = df.get(col_name, pd.Series('', index=df.index))
        return s.fillna('').astype(str).str.strip() if isinstance(s, pd.Series) else pd.Series('', index=df.index)
    name_col = _str_col('name'); themes_col = _str_col('themes')
    if (themes_col == '').all(): themes_col = _str_col('theme')
    opening_col = _str_col('opening')
    if (opening_col == '').all(): opening_col = _str_col('opening_tags')
    if (opening_col == '').all(): opening_col = _str_col('openingtags')
    rating_col_s = _str_col('rating'); eco_col = _str_col('eco')
    white_col = _str_col('white'); black_col = _str_col('black')
    event_col = _str_col('event')
    for i in range(n):
        number = i + 1; attrs = []
        nm = name_col.iloc[i]
        if nm and nm.lower() not in ('nan', 'none', ''): attrs.append(nm)
        th = themes_col.iloc[i]
        if th and th.lower() not in ('nan', 'none', ''): attrs.append(th)
        op = opening_col.iloc[i]
        if op and op.lower() not in ('nan', 'none', ''): attrs.append(op)
        rv = rating_col_s.iloc[i]
        if rv and rv.lower() not in ('nan', 'none', ''):
            try:
                rvf = float(rv); attrs.append(f"{_rating_category(rvf)} ({int(rvf)})")
            except ValueError: pass
        if not nm:
            w, b = white_col.iloc[i], black_col.iloc[i]
            if w and b: attrs.append(f"{w} vs {b}")
        if not nm:
            ev = event_col.iloc[i]
            if ev and ev.lower() not in ('nan', 'none', ''): attrs.append(ev)
        eco = eco_col.iloc[i]
        if eco and eco.lower() not in ('nan', 'none', ''): attrs.append(f"ECO {eco}")
        if attrs: names[i] = f"Puzzle #{number} — {' | '.join(attrs)}"
        else:
            row_dict = df.iloc[i].to_dict()
            uci_moves = uci_moves_list.iloc[i]
            names[i] = _generate_name_fallback(row_dict, uci_moves, i)

    puzzles = []
    for i in range(n):
        raw_tokens = _clean_move_tokens(uci_moves_list.iloc[i])
        fmt = _detect_move_format(raw_tokens)
        if fmt == 'san':
            fen_str = str(fens.iloc[i]).strip()
            if fen_str and len(fen_str.split()) < 6: fen_str += " 0 1"
            uci_moves = _san_to_uci(raw_tokens, fen_str)
            if not uci_moves: uci_moves = raw_tokens
        else:
            uci_moves = raw_tokens
        puzzles.append({'name': names[i], 'fen': fens.iloc[i], 'moves': uci_moves,
                        'desc': descs.iloc[i], 'difficulty': float(difficulty[i])})
    return puzzles

def _process_rows(rows):
    if not rows: return []
    n = len(rows)
    if HAS_PANDAS and n > 100:
        try: return _process_rows_vectorized(rows)
        except Exception as exc:
            log(f"Vectorized path failed ({exc}); falling back to iterative", "PUZZLE")
    return _process_rows_iterative(rows)

def load_puzzles(filepath):
    ext = Path(filepath).suffix.lower()
    log(f"Loading puzzles from {Path(filepath).name} ({ext})…", "PUZZLE")
    if ext == '.csv': yield from _load_csv_chunked(filepath)
    elif ext in ('.parquet', '.pq'): yield from _load_parquet_chunked(filepath)
    elif ext == '.duckdb': yield from _load_duckdb_chunked(filepath)
    elif ext in ('.db', '.sqlite'): yield from _load_sqlite_chunked(filepath)
    else: raise ValueError(f"Unsupported file format: {ext}")
    gc.collect()

def _load_csv_chunked(filepath):
    if HAS_PANDAS:
        import pandas as pd
        for chunk_df in pd.read_csv(filepath, dtype=str, chunksize=_CSV_PROCESS_CHUNK, encoding='utf-8', on_bad_lines='skip'):
            chunk_df = chunk_df.fillna(''); rows = chunk_df.to_dict('records')
            yield _process_rows(rows); del rows, chunk_df
        gc.collect()
    else:
        rows = []
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            for row in csv.DictReader(f): rows.append(row)
        log(f"Parsed {len(rows)} CSV rows (stdlib)", "PUZZLE")
        for i in range(0, len(rows), _CSV_PROCESS_CHUNK):
            yield _process_rows(rows[i:i + _CSV_PROCESS_CHUNK])
        del rows; gc.collect()

def _load_parquet_chunked(filepath):
    if HAS_PYARROW:
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(filepath); total = 0
        for batch in pf.iter_batches(batch_size=_PARQUET_BATCH):
            df = batch.to_pandas(); df = df.where(df.notna(), None)
            rows = df.to_dict('records'); yield _process_rows(rows)
            total += len(rows); del rows, df, batch
        log(f"Chunked-parquet: {total} rows from {Path(filepath).name}", "PUZZLE")
    elif HAS_PANDAS:
        import pandas as pd
        df = pd.read_parquet(filepath); df = df.where(df.notna(), None)
        rows = df.to_dict('records')
        for i in range(0, len(rows), _CSV_PROCESS_CHUNK):
            yield _process_rows(rows[i:i + _CSV_PROCESS_CHUNK])
        del rows, df; gc.collect()
    else:
        raise ImportError("Parquet requires 'pandas' or 'pyarrow'")

def _load_duckdb_chunked(filepath):
    if not HAS_DUCKDB: raise ImportError("DuckDB requires 'duckdb'")
    import duckdb
    con = duckdb.connect(filepath, read_only=True)
    try:
        tables = con.execute("SHOW TABLES").fetchall()
        if not tables: raise ValueError("No tables found in DuckDB database")
        table_name = tables[0][0]
        count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        offset = 0
        while offset < count:
            df = con.execute(f'SELECT * FROM "{table_name}" LIMIT {_CSV_PROCESS_CHUNK} OFFSET {offset}').fetchdf()
            df = df.where(df.notna(), None); rows = df.to_dict('records')
            yield _process_rows(rows); offset += _CSV_PROCESS_CHUNK; del rows, df
    finally:
        con.close()

def _load_sqlite_chunked(filepath):
    import sqlite3
    conn = sqlite3.connect(filepath)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        if not tables: raise ValueError("No tables found in SQLite database")
        table_name = tables[0][0]
        cursor = conn.execute(f'SELECT * FROM "{table_name}"')
        col_names = [desc[0] for desc in cursor.description]
        while True:
            rows_raw = cursor.fetchmany(_CSV_PROCESS_CHUNK)
            if not rows_raw: break
            rows = [dict(zip(col_names, r)) for r in rows_raw]
            yield _process_rows(rows); del rows, rows_raw
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════════
#  DATA MANAGER (Puzzles only)
# ═══════════════════════════════════════════════════════════════════════════════

DB_PUZZLES_PATH = os.path.join(DATA_DIR, "cache_puzzles.parquet")

def _sanitize_for_json(obj):
    if isinstance(obj, dict): return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list): return [_sanitize_for_json(v) for v in obj]
    elif isinstance(obj, bytes): return base64.b64encode(obj).decode('ascii')
    elif isinstance(obj, (str, int, float, bool)) or obj is None: return obj
    else: return str(obj)

class DataProvider:
    _PUZZLE_COLS = ['id', 'name', 'fen', 'moves', 'desc', 'difficulty', 'display_title']
    _SLIM_PUZZLE_COLS = ['id', 'name', 'difficulty', 'display_title']
    _LIST_COLS = {'moves'}

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._slim = {}; self._next_id = {}; self._dirty = {}
        self._load_slim('puzzles'); self._dirty['puzzles'] = False

    def _columns(self, db_type): return self._PUZZLE_COLS
    def _slim_columns(self, db_type): return self._SLIM_PUZZLE_COLS
    def _cache_path(self, db_type): return DB_PUZZLES_PATH

    @staticmethod
    def _parquet_columns(path):
        try:
            if HAS_PYARROW:
                import pyarrow.parquet as pq
                return [f.name for f in pq.read_schema(path)]
        except Exception: pass
        try:
            if HAS_PANDAS:
                import pandas as pd
                return list(pd.read_parquet(path, columns=None).head(0).columns)
        except Exception: pass
        return []

    def _empty_slim(self, db_type):
        if HAS_PANDAS:
            import pandas as pd; return pd.DataFrame(columns=self._slim_columns(db_type))
        return []

    def _load_slim(self, db_type):
        path = self._cache_path(db_type); slim_cols = self._slim_columns(db_type)
        if not os.path.exists(path):
            self._slim[db_type] = self._empty_slim(db_type); self._next_id[db_type] = 1; return
        if not HAS_PANDAS and not HAS_PYARROW:
            self._slim[db_type] = self._empty_slim(db_type); self._next_id[db_type] = 1; return
        try:
            available = self._parquet_columns(path)
            read_cols = [c for c in slim_cols if c in available] if available else slim_cols
            if not read_cols:
                self._slim[db_type] = self._empty_slim(db_type); self._next_id[db_type] = 1; return
            df = None
            try:
                if HAS_PANDAS:
                    import pandas as pd; df = pd.read_parquet(path, columns=read_cols)
                elif HAS_PYARROW:
                    import pyarrow.parquet as pq; df = pq.read_table(path, columns=read_cols).to_pandas()
            except Exception: df = None
            if df is None:
                try:
                    if HAS_PANDAS:
                        import pandas as pd; df = pd.read_parquet(path)
                    elif HAS_PYARROW:
                        import pyarrow.parquet as pq; df = pq.read_table(path).to_pandas()
                except Exception as e2:
                    self._slim[db_type] = self._empty_slim(db_type); self._next_id[db_type] = 1; return
            for c in slim_cols:
                if c not in df.columns:
                    if c == 'id': df[c] = 0
                    elif c == 'difficulty': df[c] = 0.5
                    else: df[c] = ''
            df = df[slim_cols]
            if 'id' in df.columns: df['id'] = df['id'].astype(int)
            if 'difficulty' in df.columns:
                df['difficulty'] = pd.to_numeric(df['difficulty'], errors='coerce').fillna(0.5)
            self._slim[db_type] = df
            self._next_id[db_type] = (int(df['id'].max()) + 1 if len(df) > 0 else 1)
            mem_mb = df.memory_usage(deep=True).sum() / 1e6
            log(f"Loaded slim {len(df):,} {db_type} ({mem_mb:.1f} MB)", "DATA")
        except Exception as e:
            log(f"Error loading {db_type} slim: {e}", "DATA")
            import traceback; traceback.print_exc()
            self._slim[db_type] = self._empty_slim(db_type); self._next_id[db_type] = 1

    def _deserialize_record(self, rec):
        for col in self._LIST_COLS:
            if col in rec and isinstance(rec[col], str):
                try: rec[col] = json.loads(rec[col])
                except Exception: pass
        if 'id' in rec: rec['id'] = int(rec['id'])
        if 'difficulty' in rec and rec.get('difficulty') is None: rec['difficulty'] = 0.5
        for key in list(rec.keys()):
            if rec[key] is None:
                if key == 'id': rec[key] = 0
                elif key == 'difficulty': rec[key] = 0.5
                else: rec[key] = ''
        return rec

    def _records_from_parquet(self, db_type, ids=None):
        path = self._cache_path(db_type)
        if not os.path.exists(path): return []
        id_set = set(ids) if ids is not None else None; results = []; scan_batch = 100_000
        try:
            if HAS_PYARROW:
                import pyarrow.parquet as pq
                pf = pq.ParquetFile(path)
                for batch in pf.iter_batches(batch_size=scan_batch):
                    df = batch.to_pandas()
                    if id_set is not None:
                        df = df[df['id'].isin(id_set)]; id_set -= set(df['id'].tolist())
                    for rec in df.to_dict('records'): results.append(self._deserialize_record(rec))
                    del df, batch
                    if id_set is not None and not id_set: break
            elif HAS_PANDAS:
                import pandas as pd
                df = pd.read_parquet(path)
                if id_set is not None: df = df[df['id'].isin(id_set)]
                for rec in df.to_dict('records'): results.append(self._deserialize_record(rec))
                del df
        except Exception as e:
            log(f"Error reading {db_type} records: {e}", "DATA")
        return results

    def _chunks_from_parquet(self, db_type, ids=None, chunk_size=500):
        path = self._cache_path(db_type)
        if not os.path.exists(path): return
        id_set = set(ids) if ids is not None else None; buf = []; scan_batch = 100_000
        try:
            if HAS_PYARROW:
                import pyarrow.parquet as pq
                pf = pq.ParquetFile(path)
                for batch in pf.iter_batches(batch_size=scan_batch):
                    df = batch.to_pandas()
                    if id_set is not None:
                        df = df[df['id'].isin(id_set)]; id_set -= set(df['id'].tolist())
                    for rec in df.to_dict('records'):
                        buf.append(self._deserialize_record(rec))
                        if len(buf) >= chunk_size: yield buf; buf = []
                    del df
                    if id_set is not None and not id_set: break
            elif HAS_PANDAS:
                import pandas as pd
                df = pd.read_parquet(path)
                if id_set is not None: df = df[df['id'].isin(id_set)]
                for rec in df.to_dict('records'):
                    buf.append(self._deserialize_record(rec))
                    if len(buf) >= chunk_size: yield buf; buf = []
                del df
        except Exception as e:
            log(f"Error scanning {db_type}: {e}", "DATA")
        if buf: yield buf

    def _make_record(self, db_type, item, next_id):
        return {'id': next_id, 'name': str(item.get('name', '')),
                'fen': str(item.get('fen', '')), 'moves': item.get('moves', []),
                'desc': str(item.get('desc', '')),
                'difficulty': float(item.get('difficulty', 0.5)),
                'display_title': str(item.get('display_title', item.get('name', '')))}

    def _serialize_record_for_parquet(self, rec, cols):
        sr = dict(rec)
        for col in self._LIST_COLS:
            if col in sr and isinstance(sr[col], list): sr[col] = json.dumps(sr[col], default=str)
        if 'difficulty' in sr:
            try: sr['difficulty'] = float(sr.get('difficulty', 0.5))
            except (ValueError, TypeError): sr['difficulty'] = 0.5
        if 'id' in sr: sr['id'] = int(sr['id'])
        for col in cols:
            if col not in sr:
                if col == 'id': sr[col] = 0
                elif col == 'difficulty': sr[col] = 0.5
                else: sr[col] = ''
        return sr

    def _records_to_dataframe(self, records, cols):
        import pandas as pd
        if not records: return pd.DataFrame(columns=cols)
        df = pd.DataFrame(records, columns=cols)
        if 'id' in df.columns: df['id'] = df['id'].astype(int)
        if 'difficulty' in df.columns:
            df['difficulty'] = pd.to_numeric(df['difficulty'], errors='coerce').fillna(0.5)
        return df

    def stream_import(self, db_type, chunk_generator):
        cols = self._columns(db_type); path = self._cache_path(db_type)
        if HAS_PYARROW:
            yield from self._stream_import_pyarrow(db_type, chunk_generator, cols, path, self._next_id[db_type])
        elif HAS_PANDAS:
            yield from self._stream_import_pandas(db_type, chunk_generator, cols, path, self._next_id[db_type])
        else:
            raise ImportError("Need pandas or pyarrow for parquet I/O")
        self._load_slim(db_type); self._dirty[db_type] = False

    def _stream_import_pyarrow(self, db_type, chunk_generator, cols, path, next_id):
        import pyarrow as pa; import pyarrow.parquet as pq
        writer = None; total_count = 0; schema = None
        try:
            for chunk in chunk_generator:
                if not chunk: continue
                records = []
                for item in chunk:
                    rec = self._make_record(db_type, item, next_id)
                    records.append(self._serialize_record_for_parquet(rec, cols)); next_id += 1
                chunk_df = self._records_to_dataframe(records, cols)
                table = pa.Table.from_pandas(chunk_df, preserve_index=False)
                if writer is None: schema = table.schema; writer = pq.ParquetWriter(path, schema)
                else:
                    if table.schema != schema: table = table.cast(schema)
                writer.write_table(table); total_count += len(chunk)
                del records, chunk_df, table; yield len(chunk), total_count
        finally:
            if writer is not None: writer.close()
        self._next_id[db_type] = next_id

    def _stream_import_pandas(self, db_type, chunk_generator, cols, path, next_id):
        import pandas as pd
        temp_dir = path + '.parts'; os.makedirs(temp_dir, exist_ok=True)
        temp_files = []; total_count = 0
        try:
            for chunk_idx, chunk in enumerate(chunk_generator):
                if not chunk: continue
                records = []
                for item in chunk:
                    rec = self._make_record(db_type, item, next_id)
                    records.append(self._serialize_record_for_parquet(rec, cols)); next_id += 1
                chunk_df = self._records_to_dataframe(records, cols)
                temp_path = os.path.join(temp_dir, f'part_{chunk_idx:06d}.parquet')
                chunk_df.to_parquet(temp_path, index=False); temp_files.append(temp_path)
                total_count += len(chunk); del records, chunk_df; yield len(chunk), total_count
            if temp_files:
                dfs = [pd.read_parquet(tf) for tf in temp_files]
                combined = pd.concat(dfs, ignore_index=True); combined.to_parquet(path, index=False)
                del dfs, combined
            else:
                pd.DataFrame(columns=cols).to_parquet(path, index=False)
        finally:
            for f in temp_files:
                try: os.remove(f)
                except OSError: pass
            try: shutil.rmtree(temp_dir, ignore_errors=True)
            except OSError: pass
        self._next_id[db_type] = next_id

    def _append_records_to_parquet(self, db_type, records, cols):
        import pandas as pd
        save_records = [self._serialize_record_for_parquet(rec, cols) for rec in records]
        new_df = self._records_to_dataframe(save_records, cols)
        path = self._cache_path(db_type)
        if not os.path.exists(path): new_df.to_parquet(path, index=False)
        else:
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined.to_parquet(path, index=False); del existing, combined

    def _save_cache(self, db_type): self._dirty[db_type] = False

    def clear_table(self, db_type):
        path = self._cache_path(db_type)
        if os.path.exists(path):
            try: os.remove(path)
            except OSError: pass
        self._slim[db_type] = self._empty_slim(db_type)
        self._next_id[db_type] = 1; self._dirty[db_type] = False

    def insert_batch(self, db_type, items):
        if not items: return
        cols = self._columns(db_type); slim_cols = self._slim_columns(db_type); next_id = self._next_id[db_type]
        records = []; slim_rows = []
        for item in items:
            rec = self._make_record(db_type, item, next_id)
            records.append(rec); slim_rows.append({c: rec.get(c, '') for c in slim_cols}); next_id += 1
        self._append_records_to_parquet(db_type, records, cols)
        if HAS_PANDAS:
            import pandas as pd
            new_slim = pd.DataFrame(slim_rows, columns=slim_cols)
            if 'id' in new_slim.columns: new_slim['id'] = new_slim['id'].astype(int)
            existing = self._slim.get(db_type)
            if existing is not None and len(existing) > 0:
                self._slim[db_type] = pd.concat([existing, new_slim], ignore_index=True)
            else:
                self._slim[db_type] = new_slim
        self._next_id[db_type] = next_id; self._dirty[db_type] = True

    def flush(self, db_type=None):
        if db_type:
            if self._dirty.get(db_type, False): self._save_cache(db_type)
        else:
            for dt in list(self._dirty.keys()):
                if self._dirty[dt]: self._save_cache(dt)

    def reload(self, db_type):
        self._load_slim(db_type); self._dirty[db_type] = False

    def get_count(self, db_type, filter_text=""):
        df = self._slim.get(db_type)
        if df is None or not HAS_PANDAS or len(df) == 0: return 0
        if filter_text:
            ft = filter_text.lower()
            mask = df['name'].str.lower().str.contains(ft, na=False)
            if 'display_title' in df.columns:
                mask |= df['display_title'].str.lower().str.contains(ft, na=False)
            return int(mask.sum())
        return len(df)

    def get_page(self, db_type, page, page_size, filter_text=""):
        df = self._slim.get(db_type)
        if df is None or not HAS_PANDAS or len(df) == 0: return []
        if filter_text:
            ft = filter_text.lower()
            mask = df['name'].str.lower().str.contains(ft, na=False)
            if 'display_title' in df.columns:
                mask |= df['display_title'].str.lower().str.contains(ft, na=False)
            filtered = df[mask]
        else:
            filtered = df
        start = page * page_size; end = start + page_size
        page_df = filtered.iloc[start:end]
        results = []
        for rec in page_df.to_dict('records'):
            r = dict(rec)
            if 'id' in r: r['id'] = int(r['id'])
            if 'difficulty' in r and r.get('difficulty') is not None:
                try: r['difficulty'] = float(r['difficulty'])
                except (ValueError, TypeError): r['difficulty'] = 0.5
            results.append(r)
        return results

    def get_ids_by_filter(self, db_type, filter_text=""):
        df = self._slim.get(db_type)
        if df is None or not HAS_PANDAS or len(df) == 0: return []
        if filter_text:
            ft = filter_text.lower()
            mask = df['name'].str.lower().str.contains(ft, na=False)
            if 'display_title' in df.columns:
                mask |= df['display_title'].str.lower().str.contains(ft, na=False)
            filtered = df[mask]
        else:
            filtered = df
        return filtered['id'].astype(int).tolist()

    def get_items_by_ids(self, db_type, ids):
        if not ids: return []
        return self._records_from_parquet(db_type, ids)

    def get_chunks_by_ids(self, db_type, ids, chunk_size=500):
        if not ids: return
        yield from self._chunks_from_parquet(db_type, ids, chunk_size)

class DataLoadWorker(QThread):
    data_ready = Signal(str, int)
    load_error = Signal(str, str)

    def __init__(self, db_type, directory=None, single_file=None):
        super().__init__()
        self.db_type = db_type; self.directory = directory
        self.single_file = single_file; self._abort = False

    def abort(self): self._abort = True

    def run(self):
        try:
            db = DataProvider(); db.clear_table(self.db_type); total_count = 0
            files = self._get_files()
            for f in files:
                if self._abort: break
                try:
                    chunk_gen = load_puzzles(str(f))
                    for chunk_count, running_total in db.stream_import(self.db_type, chunk_gen):
                        if self._abort: break
                        total_count = running_total
                        if chunk_count % 100_000 < 60_000:
                            log(f"  {self.db_type}: {total_count:,} rows (+{chunk_count})", "DATA")
                except Exception as e:
                    log(f"Error loading {f.name}: {e}", "DATA")
                    import traceback; traceback.print_exc()
                    self.load_error.emit(self.db_type, f"{f.name}: {e}")
            db.flush(self.db_type)
            log(f"Load complete: {total_count:,} {self.db_type}", "DATA")
            self.data_ready.emit(self.db_type, total_count)
        except Exception as e:
            log(f"Fatal load error ({self.db_type}): {e}", "DATA")
            import traceback; traceback.print_exc()
            self.load_error.emit(self.db_type, str(e))
            self.data_ready.emit(self.db_type, 0)

    def _get_files(self):
        valid_exts = {'.csv', '.parquet', '.pq', '.duckdb', '.db', '.sqlite'}
        if self.single_file: return [Path(self.single_file)]
        directory = self.directory
        if not directory or not os.path.exists(directory):
            if directory: os.makedirs(directory, exist_ok=True)
            return []
        return sorted(f for f in Path(directory).iterdir() if f.suffix.lower() in valid_exts)

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════════════════════════════

if HAS_NUMBA:
    from numba import njit as _njit4, prange as _prange2
    @_njit4(cache=True, parallel=True, nogil=True)
    def _normalize_frames_nb(frame_ptrs, target_h, target_w):
        n = frame_ptrs.shape[0]
        out = np.empty((n, target_h, target_w, 3), dtype=np.uint8)
        for idx in _prange2(n):
            src = frame_ptrs[idx]; sh, sw = src.shape[0], src.shape[1]
            for y in range(target_h):
                sy = min(int(y * sh / target_h), sh - 1)
                for x in range(target_w):
                    sx = min(int(x * sw / target_w), sw - 1)
                    for c in range(3): out[idx, y, x, c] = src[sy, sx, c]
        return out
    log("Numba JIT frame normaliser loaded", "EXPORT")
else:
    def _normalize_frames_nb(frame_ptrs, target_h, target_w):
        out = np.empty((len(frame_ptrs), target_h, target_w, 3), dtype=np.uint8)
        for idx, src in enumerate(frame_ptrs):
            sh, sw = src.shape[0], src.shape[1]
            iy = (np.arange(target_h) * sh // target_h).clip(0, sh - 1)
            ix = (np.arange(target_w) * sw // target_w).clip(0, sw - 1)
            out[idx] = src[np.ix_(iy, ix)]
        return out

if HAS_CUPY:
    import cupy as _cp_export
    def _gpu_vignette(frames_gpu, strength=0.25):
        _n, h, w, _c = frames_gpu.shape
        yy, xx = _cp_export.meshgrid(_cp_export.linspace(-1, 1, h, dtype=_cp_export.float32),
                                      _cp_export.linspace(-1, 1, w, dtype=_cp_export.float32), indexing='ij')
        dist = _cp_export.sqrt(xx ** 2 + yy ** 2)
        vignette = 1.0 - strength * _cp_export.clip(dist / 1.414, 0, 1)
        vignette = vignette[_cp_export.newaxis, :, :, _cp_export.newaxis]
        out = frames_gpu.astype(_cp_export.float32) * vignette
        return _cp_export.clip(out, 0, 255).astype(_cp_export.uint8)
    def _gpu_color_grade(frames_gpu, contrast=1.02, brightness=0.0, saturation=1.05):
        f = frames_gpu.astype(_cp_export.float32)
        f = _cp_export.clip(f * contrast + brightness, 0, 255)
        if saturation != 1.0:
            gray = _cp_export.mean(f, axis=3, keepdims=True)
            f = _cp_export.clip(gray + saturation * (f - gray), 0, 255)
        return f.astype(_cp_export.uint8)
    log("CuPy GPU post-processing helpers loaded", "EXPORT")
else:
    _cp_export = None

def _render_puzzle_frames(puzzle, cfg, abort_check=None):
    sz = cfg.effective_sq_size; bpx = sz * 8; fps = cfg.fps
    theme = THEMES.get(cfg.theme_name, THEMES["Classic"])
    tasks = []; tw, th = cfg.target_width, cfg.target_height
    needs_composite = (tw != bpx or th != bpx); bg = cfg.background_color
    title_text = cfg.title_text
    if not title_text: title_text = puzzle.get('display_title', puzzle.get('name', ''))
    if cfg.title_enabled and title_text:
        n_frames = int(fps * cfg.title_duration)
        card_font_size = max(24, int(sz * 0.55))
        if needs_composite: card_font_size = max(28, int(min(tw, th) * 0.05))
        for _ in range(n_frames):
            tasks.append(('card', {'text': title_text, 'bg': cfg.title_bg,
                                   'fg': cfg.title_fg, 'w': tw if needs_composite else bpx,
                                   'h': th if needs_composite else bpx,
                                   'font_size': card_font_size, 'sub_text': cfg.subtitle_text}))
    eng = ChessEngine()
    fen = puzzle.get("fen")
    if fen: eng.load_fen(fen)
    else: eng.reset()
    for move_str in puzzle["moves"]:
        if abort_check and abort_check(): return None
        move_str = move_str.strip()
        if not move_str: continue
        board_before_move = eng.board.copy()
        move = None
        try:
            m = chess.Move.from_uci(move_str)
            if m in eng.board.legal_moves: move = m
        except ValueError: pass
        if move is None:
            try: move = eng.board.parse_san(move_str)
            except Exception: pass
        if move is None:
            log(f"Skipping illegal move {move_str} in export", "EXPORT"); continue
        from_sq = move.from_square; to_sq = move.to_square
        fr = 7 - chess.square_rank(from_sq); fc = chess.square_file(from_sq)
        tr = 7 - chess.square_rank(to_sq); tc = chess.square_file(to_sq)
        piece_obj = board_before_move.piece_at(from_sq)
        if piece_obj is None: continue
        n_highlight = max(1, int(fps * cfg.highlight_duration))
        for _ in range(n_highlight):
            tasks.append(('board', {'board': board_before_move, 'sz': sz, 'selected': (fr, fc), 'last_move': None, 'theme': theme}))
        n_anim = max(1, int(fps * cfg.move_anim_duration))
        for i in range(n_anim):
            prog = i / n_anim
            tasks.append(('board', {'board': board_before_move, 'sz': sz,
                                    'anim_state': {'from': (fr, fc), 'to': (tr, tc), 'piece_obj': piece_obj, 'progress': prog}, 'theme': theme}))
        info = eng.make_move_uci(move.uci())
        last_move = ((fr, fc), (tr, tc)) if info else None
        n_pause = max(1, int(fps * cfg.pause_after_move))
        for _ in range(n_pause):
            tasks.append(('board', {'board': eng.board.copy(), 'sz': sz, 'last_move': last_move, 'theme': theme}))
    if cfg.end_enabled and cfg.end_text:
        n_frames = int(fps * cfg.end_duration)
        end_font_size = max(28, int(sz * 0.65))
        if needs_composite: end_font_size = max(32, int(min(tw, th) * 0.058))
        for _ in range(n_frames):
            tasks.append(('card', {'text': cfg.end_text, 'bg': cfg.end_bg,
                                   'fg': cfg.end_fg, 'w': tw if needs_composite else bpx,
                                   'h': th if needs_composite else bpx,
                                   'font_size': end_font_size}))
    total = len(tasks)
    if total == 0: return []
    frames = [None] * total

    def render_task(idx_task):
        idx, (t_type, t_kwargs) = idx_task
        if t_type == 'card':
            img = ChessBoardWidget.render_card(**t_kwargs)
            np_arr = ChessBoardWidget.qimage_to_np(img)
            if needs_composite: np_arr = composite_card_frame(np_arr, tw, th, bg)
        else:
            img = ChessBoardWidget.render_frame(t_kwargs['board'], last_move=t_kwargs.get('last_move'),
                                                selected=t_kwargs.get('selected'), anim_state=t_kwargs.get('anim_state'),
                                                sq_size=t_kwargs['sz'], show_arrow=True, theme=t_kwargs['theme'])
            np_arr = ChessBoardWidget.qimage_to_np(img)
            if needs_composite:
                np_arr = composite_frame(np_arr, tw, th, bg,
                                         title_overlay=cfg.title_overlay_text if cfg.show_title_overlay else "",
                                         subtitle_overlay=cfg.subtitle_text if cfg.show_title_overlay else "")
        return idx, np_arr

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
        futures = {executor.submit(render_task, (i, t)): i for i, t in enumerate(tasks)}
        for future in as_completed(futures):
            if abort_check and abort_check():
                executor.shutdown(wait=False, cancel_futures=True); return None
            try:
                idx, np_arr = future.result(); frames[idx] = np_arr
            except Exception as e:
                log(f"Frame render error: {e}", "EXPORT")
    frames = [f for f in frames if f is not None]
    if not frames: return None
    return frames

def _post_process_frames(frames, cfg, abort_check=None):
    if not frames: return frames
    target_h, target_w = cfg.target_height, cfg.target_width
    needs_resize = any(f.shape[0] != target_h or f.shape[1] != target_w for f in frames if f is not None)
    if needs_resize:
        frame_ptrs = np.empty(len(frames), dtype=object)
        for i, f in enumerate(frames): frame_ptrs[i] = f
        frames_np = _normalize_frames_nb(frame_ptrs, target_h, target_w)
        frames = [frames_np[i] for i in range(len(frames))]
    use_gpu = (HAS_CUPY and cfg.gpu_post_process and
               (cfg.gpu_vignette > 0 or cfg.gpu_contrast != 1.0 or cfg.gpu_saturation != 1.0))
    if use_gpu:
        try: frames = _gpu_post_process(frames, cfg)
        except Exception as e:
            log(f"CuPy GPU post-processing failed ({e}), skipping", "EXPORT")
    return frames

def _gpu_post_process(frames, cfg):
    n = len(frames)
    if n == 0: return frames
    h, w, c = frames[0].shape; frame_bytes = h * w * c
    chunk = max(1, min(200, (1 << 30) // frame_bytes)); result = [None] * n
    for start in range(0, n, chunk):
        end = min(start + chunk, n); stack_np = np.stack(frames[start:end])
        gpu = _cp_export.asarray(stack_np)
        if cfg.gpu_contrast != 1.0 or cfg.gpu_saturation != 1.0:
            gpu = _gpu_color_grade(gpu, contrast=cfg.gpu_contrast, saturation=cfg.gpu_saturation)
        if cfg.gpu_vignette > 0.0: gpu = _gpu_vignette(gpu, strength=cfg.gpu_vignette)
        cpu = _cp_export.asnumpy(gpu)
        for i in range(end - start): result[start + i] = cpu[i]
        del gpu, stack_np, cpu
        _cp_export.get_default_memory_pool().free_all_blocks()
    return result

def _write_mp4(filepath, frames, fps, cfg=None):
    if not HAS_NUMPY or not HAS_IMAGEIO:
        return False, "ERROR: Missing numpy or imageio"
    use_ffmpeg = HAS_FFMPEG and (cfg.use_ffmpeg if cfg else True)
    if use_ffmpeg and cfg and len(frames) > 0:
        h, w = frames[0].shape[:2]
        try:
            tmp_dir = tempfile.mkdtemp(prefix="chess_frames_")
            write_frames_to_disk(frames, tmp_dir)
            crf = cfg.ffmpeg_crf if cfg else 20
            preset = cfg.ffmpeg_preset if cfg else "medium"
            ok, msg = write_mp4_ffmpeg(tmp_dir, filepath, fps, w, h, crf, preset)
            try: shutil.rmtree(tmp_dir)
            except OSError: pass
            if ok: return True, msg
            log(f"FFmpeg encode failed ({msg}), falling back to imageio", "EXPORT")
        except Exception as e:
            log(f"FFmpeg encode error ({e}), falling back to imageio", "EXPORT")
    try:
        import imageio.v3 as iio; iio.imwrite(filepath, frames, fps=fps)
        return True, f"Saved: {filepath}"
    except AttributeError:
        try:
            import imageio; imageio.mimwrite(filepath, frames, fps=fps)
            return True, f"Saved: {filepath}"
        except Exception as e2: return False, f"Error writing {filepath}: {e2}"
    except Exception as e: return False, f"Error writing {filepath}: {e}"

def _write_gif(filepath, frames, fps, cfg=None):
    if HAS_FFMPEG and len(frames) > 0:
        h, w = frames[0].shape[:2]
        try:
            tmp_dir = tempfile.mkdtemp(prefix="chess_gif_")
            write_frames_to_disk(frames, tmp_dir)
            ok, msg = write_gif_ffmpeg(tmp_dir, filepath, fps, w, h)
            try: shutil.rmtree(tmp_dir)
            except OSError: pass
            if ok: return True, msg
        except Exception as e:
            log(f"FFmpeg GIF failed ({e}), trying imageio", "EXPORT")
    try:
        import imageio.v3 as iio; iio.imwrite(filepath, frames, fps=fps, loop=0)
        return True, f"Saved GIF: {filepath}"
    except Exception as e: return False, f"GIF error: {e}"

def _add_audio(video_path, cfg):
    audio_path = cfg.audio_path
    if not audio_path or not os.path.exists(audio_path): return video_path, ""
    base, ext = os.path.splitext(video_path); audio_out = base + "_audio" + ext
    ok, msg = mix_audio_ffmpeg(video_path, audio_path, audio_out, volume=cfg.audio_volume)
    if ok:
        try: os.replace(audio_out, video_path); return video_path, msg
        except OSError: return audio_out, msg
    else:
        log(f"Audio mixing failed: {msg}", "EXPORT"); return video_path, msg

def composite_frame(board_np, target_w, target_h, bg, title_overlay="", subtitle_overlay=""):
    canvas = np.full((target_h, target_w, 3), bg, dtype=np.uint8)
    bh, bw = board_np.shape[:2]
    x = (target_w - bw) // 2; y = (target_h - bh) // 2
    y1, y2 = max(0, y), min(target_h, y + bh); x1, x2 = max(0, x), min(target_w, x + bw)
    by1, by2 = y1 - y, y2 - y; bx1, bx2 = x1 - x, x2 - x
    canvas[y1:y2, x1:x2] = board_np[by1:by2, bx1:bx2]
    if title_overlay or subtitle_overlay:
        canvas = _render_overlays(canvas, title_overlay, subtitle_overlay)
    return canvas

def composite_card_frame(card_np, target_w, target_h, bg):
    canvas = np.full((target_h, target_w, 3), bg, dtype=np.uint8)
    ch, cw = card_np.shape[:2]
    x = (target_w - cw) // 2; y = (target_h - ch) // 2
    y1, y2 = max(0, y), min(target_h, y + ch); x1, x2 = max(0, x), min(target_w, x + cw)
    by1, by2 = y1 - y, y2 - y; bx1, bx2 = x1 - x, x2 - x
    canvas[y1:y2, x1:x2] = card_np[by1:by2, bx1:bx2]
    return canvas

def _render_overlays(canvas, title_text, subtitle_text):
    h, w = canvas.shape[:2]
    img = QImage(canvas.data, w, h, w * 3, QImage.Format_RGB888).copy()
    p = QPainter(img); p.setRenderHint(QPainter.TextAntialiasing)
    if title_text:
        font_size = max(16, int(min(w, h) * 0.04))
        p.setFont(QFont("Sans", font_size, QFont.Bold)); p.setPen(QColor(220, 220, 220, 200))
        margin = int(h * 0.02)
        p.drawText(QRect(margin, margin, w - 2 * margin, font_size + 10), Qt.AlignLeft | Qt.AlignTop, title_text)
    if subtitle_text:
        font_size = max(12, int(min(w, h) * 0.025))
        p.setFont(QFont("Sans", font_size)); p.setPen(QColor(180, 180, 180, 180))
        margin = int(h * 0.02); top = h - font_size - margin - 10
        p.drawText(QRect(margin, top, w - 2 * margin, font_size + 10), Qt.AlignLeft | Qt.AlignBottom, subtitle_text)
    p.end()
    ptr = img.constBits()
    if hasattr(ptr, 'setsize'): ptr.setsize(img.sizeInBytes())
    raw = np.frombuffer(ptr, dtype=np.uint8).reshape(h, w * 3).copy()
    return raw.reshape(h, w, 3)

def write_frames_to_disk(frames, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    if HAS_IMAGEIO:
        import imageio.v3 as iio
        for i, frame in enumerate(frames):
            iio.imwrite(os.path.join(output_dir, f"frame_{i:06d}.png"), frame)
    else:
        for i, frame in enumerate(frames):
            h, w = frame.shape[:2]
            img = QImage(frame.copy().data, w, h, w * 3, QImage.Format_RGB888).copy()
            img.save(os.path.join(output_dir, f"frame_{i:06d}.png"))
    log(f"Wrote {len(frames)} frames to {output_dir}", "VIDEO")

def write_mp4_ffmpeg(frame_dir, output_path, fps, width, height, crf=20, preset="medium"):
    if not HAS_FFMPEG: return False, "FFmpeg not found on PATH"
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", os.path.join(frame_dir, "frame_%06d.png"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(crf), "-preset", preset,
           "-movflags", "+faststart", output_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0: return True, f"Saved MP4: {output_path}"
        return False, f"FFmpeg error: {result.stderr[:300]}"
    except FileNotFoundError: return False, "FFmpeg binary not found"
    except subprocess.TimeoutExpired: return False, "FFmpeg encode timed out"

def write_gif_ffmpeg(frame_dir, output_path, fps, width, height):
    if not HAS_FFMPEG: return False, "FFmpeg not found on PATH"
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", os.path.join(frame_dir, "frame_%06d.png"),
           "-filter_complex", f"[0:v] fps={fps},split [a][b];[a] palettegen [p];[b][p] paletteuse",
           output_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0: return True, f"Saved GIF: {output_path}"
        return False, f"FFmpeg GIF error: {result.stderr[:300]}"
    except FileNotFoundError: return False, "FFmpeg binary not found"
    except subprocess.TimeoutExpired: return False, "FFmpeg GIF encode timed out"

def mix_audio_ffmpeg(video_path, audio_path, output_path, volume=0.25):
    if not HAS_FFMPEG: return False, "FFmpeg not found on PATH"
    cmd = ["ffmpeg", "-y", "-i", video_path, "-i", audio_path,
           "-filter_complex", f"[1:a]volume={volume}[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", output_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0: return True, "Audio mixed successfully"
        return False, f"FFmpeg audio error: {result.stderr[:300]}"
    except FileNotFoundError: return False, "FFmpeg binary not found"
    except subprocess.TimeoutExpired: return False, "FFmpeg audio mix timed out"

class ExportWorker(QThread):
    progress = Signal(int); finished = Signal(str)
    def __init__(self, puzzle, file_path, config=None):
        super().__init__()
        self.puzzle = puzzle; self.file_path = file_path
        self.config = config or ExportConfig(); self._abort = False
    def abort(self): self._abort = True
    def run(self):
        if not HAS_NUMPY or not HAS_IMAGEIO:
            self.finished.emit("ERROR: Missing numpy or imageio"); return
        log(f"Exporting '{self.puzzle['name']}' -> {self.file_path}", "EXPORT")
        self.progress.emit(5)
        frames = _render_puzzle_frames(self.puzzle, self.config, abort_check=lambda: self._abort)
        if frames is None: self.finished.emit("Export cancelled."); return
        self.progress.emit(50)
        frames = _post_process_frames(frames, self.config, abort_check=lambda: self._abort)
        if frames is None: self.finished.emit("Export cancelled."); return
        self.progress.emit(70)
        if self.config.export_gif:
            ok, msg = _write_gif(self.file_path, frames, self.config.gif_fps, self.config)
        else:
            ok, msg = _write_mp4(self.file_path, frames, self.config.fps, self.config)
        self.progress.emit(85)
        if ok and self.config.audio_path:
            final_path, audio_msg = _add_audio(self.file_path, self.config)
            if audio_msg: msg = msg + " | " + audio_msg
        self.progress.emit(100 if ok else 0); self.finished.emit(msg)

class BatchExportWorker(QThread):
    batch_progress = Signal(int, int, str); puzzle_progress = Signal(int, int)
    puzzle_done = Signal(int, str); puzzle_error = Signal(int, str)
    all_done = Signal(int, int, str)
    def __init__(self, puzzles, output_dir, config=None):
        super().__init__()
        self.puzzles = puzzles; self.output_dir = output_dir
        self.config = config or ExportConfig(); self._abort = False
    def abort(self): self._abort = True
    def _unique_path(self, base_name, ext=None):
        if ext is None: ext = ".gif" if self.config.export_gif else ".mp4"
        safe = sanitize_filename(base_name)
        path = os.path.join(self.output_dir, safe + ext)
        if not os.path.exists(path): return path
        i = 2
        while True:
            path = os.path.join(self.output_dir, f"{safe}_{i}{ext}")
            if not os.path.exists(path): return path
            i += 1
    def run(self):
        if not HAS_NUMPY or not HAS_IMAGEIO:
            self.all_done.emit(0, len(self.puzzles), self.output_dir); return
        os.makedirs(self.output_dir, exist_ok=True)
        total = len(self.puzzles); exported = 0; errors = 0
        for i, puzzle in enumerate(self.puzzles):
            if self._abort: break
            name = puzzle.get('name', f'puzzle_{i+1}')
            self.batch_progress.emit(i, total, name); self.puzzle_progress.emit(i, 0)
            filepath = self._unique_path(name)
            try:
                frames = _render_puzzle_frames(puzzle, self.config, abort_check=lambda: self._abort)
                if frames is None: self.puzzle_error.emit(i, "Cancelled"); errors += 1; continue
                self.puzzle_progress.emit(i, 40)
                frames = _post_process_frames(frames, self.config, abort_check=lambda: self._abort)
                if frames is None: self.puzzle_error.emit(i, "Cancelled"); errors += 1; continue
                self.puzzle_progress.emit(i, 70)
                if self.config.export_gif:
                    ok, msg = _write_gif(filepath, frames, self.config.gif_fps, self.config)
                else:
                    ok, msg = _write_mp4(filepath, frames, self.config.fps, self.config)
                if ok:
                    if self.config.audio_path and not self.config.export_gif:
                        final_path, audio_msg = _add_audio(filepath, self.config)
                        if audio_msg: msg = msg + " | " + audio_msg
                    exported += 1; self.puzzle_done.emit(i, filepath); self.puzzle_progress.emit(i, 100)
                else:
                    errors += 1; self.puzzle_error.emit(i, msg)
            except Exception as e:
                errors += 1; self.puzzle_error.emit(i, f"Error: {e}")
        self.all_done.emit(exported, errors, self.output_dir)

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW (Puzzle App)
# ═══════════════════════════════════════════════════════════════════════════════

class CheckableListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.setItemAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    def add_checkable_item(self, text, data=None, checked=False):
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        if data is not None: item.setData(Qt.UserRole, data)
        self.addItem(item); return item

class MainWindow(QWidget):
    _PAGE_SIZE = 100

    def __init__(self):
        super().__init__()
        self.setWindowTitle("♚ Chess Puzzle App")
        log("Initializing Chess Puzzle App...", "APP")
        self._apply_professional_style()
        self.engine = ChessEngine(); self.snd = SoundManager()
        self.db = DataProvider()
        self.board_widget = ChessBoardWidget(self.engine, self.snd)
        self.board_widget.move_made.connect(self.on_move)
        self.export_worker = None; self.batch_worker = None
        self.puzzles_loaded = False; self._active_workers = []
        self._pz_page = 0; self._pz_checked = set()
        layout = QHBoxLayout(self); layout.setContentsMargins(12, 12, 12, 12); layout.setSpacing(12)
        self.tabs = QTabWidget(); self.tabs.setFixedWidth(460); layout.addWidget(self.tabs)
        board_frame = QFrame(); board_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        board_frame.setStyleSheet("QFrame { border: 1px solid #4a4a4f; border-radius: 6px; background: #25252a; }")
        bl = QVBoxLayout(board_frame); bl.setContentsMargins(8, 8, 8, 8); bl.setSpacing(8)
        top_ctrl = QHBoxLayout(); top_ctrl.addWidget(QLabel("Theme:"))
        self.theme_cb = QComboBox(); self.theme_cb.addItems(THEMES.keys())
        self.theme_cb.currentTextChanged.connect(self._change_theme); top_ctrl.addWidget(self.theme_cb)
        top_ctrl.addStretch(); top_ctrl.addWidget(QLabel("Speed:"))
        self.anim_slider = QSlider(Qt.Horizontal); self.anim_slider.setRange(0, 600)
        self.anim_slider.setValue(600 - ANIM_SPEED_DEFAULT); self.anim_slider.setInvertedAppearance(True)
        self.anim_slider.setFixedWidth(120)
        self.anim_lbl = QLabel(self._fmt_anim(ANIM_SPEED_DEFAULT))
        self.anim_slider.valueChanged.connect(self._update_anim_speed)
        top_ctrl.addWidget(self.anim_slider); top_ctrl.addWidget(self.anim_lbl); bl.addLayout(top_ctrl)
        bl.addWidget(self.board_widget, alignment=Qt.AlignCenter); layout.addWidget(board_frame, alignment=Qt.AlignCenter)
        self._build_puzzle_tab(); self._build_settings_tab()
        self.snd.play("start"); log("App initialization complete", "APP")
        QTimer.singleShot(50, lambda: self._start_data_load("puzzles"))

    def closeEvent(self, event):
        log("Closing application...", "APP")
        for worker in self._active_workers[:]:
            if worker.isRunning(): worker.abort(); worker.wait(2000)
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.abort(); self.export_worker.wait(2000)
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.abort(); self.batch_worker.wait(2000)
        self.db.flush(); self.snd.cleanup(); event.accept()

    def on_move(self, notation):
        if self.engine.game_over:
            if self.engine.board.is_checkmate(): self.puzzle_status.setText("♔ Checkmate!")
            elif self.engine.board.is_stalemate(): self.puzzle_status.setText("½ Stalemate — Draw")
            elif self.engine.board.is_insufficient_material(): self.puzzle_status.setText("½ Insufficient material — Draw")
            else: self.puzzle_status.setText(f"Game over: {self.engine.result}")
        self.board_widget.update()

    def _apply_professional_style(self):
        self.setStyleSheet("""
            QWidget { font-family: 'Segoe UI', Arial, sans-serif; color: #d0d0d0; }
            QGroupBox { font-weight: bold; border: 1px solid #4a4a4f; border-radius: 6px;
                margin-top: 14px; padding: 12px 8px 8px 8px; background-color: #2e2e32; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #a0a0a8; }
            QPushButton { padding: 6px 14px; border-radius: 4px; background-color: #3c3f41;
                border: 1px solid #4a4a4f; color: #d0d0d0; }
            QPushButton:hover { background-color: #4e5254; border-color: #606068; }
            QPushButton:pressed { background-color: #2d2f30; }
            QPushButton:disabled { background-color: #2a2a2e; color: #606068; border-color: #333338; }
            QTabWidget::pane { border: 1px solid #4a4a4f; border-radius: 4px; background-color: #25252a; }
            QTabBar::tab { padding: 8px 18px; border: 1px solid #4a4a4f; border-bottom: none;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
                background: #2e2e32; color: #a0a0a8; font-weight: bold; }
            QTabBar::tab:selected { background: #3c3f41; color: #ffffff; }
            QListWidget { border: 1px solid #4a4a4f; border-radius: 4px; background-color: #25252a; padding: 2px; }
            QListWidget::item { padding: 4px; border-bottom: 1px solid #333338; }
            QListWidget::item:hover { background-color: #3c3f41; }
            QListWidget::item:selected { background-color: #4e5254; color: white; }
            QLineEdit, QSpinBox, QComboBox { padding: 4px 8px; border: 1px solid #4a4a4f;
                border-radius: 4px; background-color: #25252a; color: #d0d0d0; }
            QComboBox::drop-down { border: none; }
            QSlider::groove:horizontal { border: 1px solid #4a4a4f; height: 6px;
                background: #25252a; border-radius: 3px; }
            QSlider::handle:horizontal { background: #a0a0a8; border: 1px solid #4a4a4f;
                width: 14px; margin: -5px 0; border-radius: 7px; }
            QTextEdit { border: 1px solid #4a4a4f; border-radius: 4px;
                background-color: #25252a; color: #d0d0d0; }
            QProgressBar { border: 1px solid #4a4a4f; border-radius: 4px; text-align: center;
                background-color: #25252a; color: white; height: 20px; font-weight: bold; }
            QProgressBar::chunk { background-color: #5c9fd6; border-radius: 3px; }
        """)

    # ── Theme / animation helpers ────────────────────────────────────────

    def _change_theme(self, name):
        if name in THEMES:
            self.board_widget.current_theme = THEMES[name]; self.board_widget.update()
            self.theme_cb.blockSignals(True); self.theme_cb.setCurrentText(name); self.theme_cb.blockSignals(False)
            if hasattr(self, 'settings_theme_cb'):
                self.settings_theme_cb.blockSignals(True)
                self.settings_theme_cb.setCurrentText(name)
                self.settings_theme_cb.blockSignals(False)

    def _fmt_anim(self, ms):
        if ms == 0: return "Instant"
        if ms <= 100: return f"Fast ({ms}ms)"
        if ms <= 350: return f"Normal ({ms}ms)"
        return f"Slow ({ms}ms)"

    def _update_anim_speed(self, raw_val):
        val = 600 - raw_val; self.board_widget.anim_speed = val
        self.anim_lbl.setText(self._fmt_anim(val))
        self.anim_slider.blockSignals(True); self.anim_slider.setValue(raw_val); self.anim_slider.blockSignals(False)
        if hasattr(self, 'settings_anim_slider'):
            self.settings_anim_lbl.setText(self._fmt_anim(val))
            self.settings_anim_slider.blockSignals(True)
            self.settings_anim_slider.setValue(raw_val); self.settings_anim_slider.blockSignals(False)

    # ── Thread-safe data loading ─────────────────────────────────────────

    def _start_data_load(self, db_type, single_file=None):
        self.puzzle_list.clear()
        self.puzzle_list.add_checkable_item("Loading puzzles…", checked=False)
        self.puzzles_loaded = False
        if single_file:
            worker = DataLoadWorker(db_type, single_file=single_file)
        else:
            directory = str(Path(DATA_DIR) / db_type)
            worker = DataLoadWorker(db_type, directory=directory)
        worker.setObjectName(f"DataLoadWorker_{db_type}")
        worker.data_ready.connect(self._on_data_ready)
        worker.load_error.connect(self._on_load_error)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._active_workers.append(worker); worker.start()

    def _on_data_ready(self, db_type, total_count):
        self.db.reload(db_type); self.puzzles_loaded = True
        self._pz_checked.clear(); self._pz_page = 0
        self._populate_puzzle_page()
        self.puzzle_db_status.setText(f"Loaded {total_count:,} puzzles")

    def _on_load_error(self, db_type, error_msg):
        log(f"Load error ({db_type}): {error_msg}", "DATA")
        self.puzzle_db_status.setText(f"Error: {error_msg}")

    def _cleanup_worker(self, worker):
        if worker in self._active_workers: self._active_workers.remove(worker)
        if not worker.isRunning(): worker.deleteLater()
        else: worker.finished.connect(worker.deleteLater)

    # ════════════════════════════════════════════════════════════════════════
    #  PUZZLE TAB
    # ════════════════════════════════════════════════════════════════════════

    def _build_puzzle_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget(); l = QVBoxLayout(container); l.setSpacing(12)

        # ── 1. Database ──────────────────────────────────────────────────
        db_group = QGroupBox("📂 Puzzle Database"); db_layout = QVBoxLayout(db_group)
        path_row = QHBoxLayout()
        self.puzzle_db_path = QLineEdit()
        self.puzzle_db_path.setPlaceholderText("Database file path (.csv .parquet .pq .duckdb .db .sqlite)…")
        path_row.addWidget(self.puzzle_db_path, 1)
        btn_load_db = QPushButton("Load"); btn_load_db.clicked.connect(self.load_puzzle_db)
        path_row.addWidget(btn_load_db); db_layout.addLayout(path_row)
        self.puzzle_db_status = QLabel("No database loaded")
        self.puzzle_db_status.setAlignment(Qt.AlignCenter)
        db_layout.addWidget(self.puzzle_db_status); l.addWidget(db_group)

        # ── 2. Filter & Selection ────────────────────────────────────────
        filter_group = QGroupBox("🔍 Filter & Selection"); fl = QVBoxLayout(filter_group)
        filter_row = QHBoxLayout()
        self.puzzle_filter = QLineEdit(); self.puzzle_filter.setPlaceholderText("Filter puzzles…")
        filter_row.addWidget(self.puzzle_filter, 1); fl.addLayout(filter_row)
        self._pz_filter_timer = QTimer(); self._pz_filter_timer.setSingleShot(True)
        self._pz_filter_timer.setInterval(300); self._pz_filter_timer.timeout.connect(self._apply_puzzle_filter)
        self.puzzle_filter.textChanged.connect(lambda: self._pz_filter_timer.start())
        sel_row = QHBoxLayout()
        btn_all = QPushButton("All"); btn_all.setFixedWidth(55); btn_all.clicked.connect(self._puzzle_select_all)
        btn_none = QPushButton("None"); btn_none.setFixedWidth(55); btn_none.clicked.connect(self._puzzle_select_none)
        btn_inv = QPushButton("Invert"); btn_inv.setFixedWidth(60); btn_inv.clicked.connect(self._puzzle_select_invert)
        sel_row.addWidget(btn_all); sel_row.addWidget(btn_none)
        sel_row.addWidget(btn_inv); sel_row.addStretch(); fl.addLayout(sel_row)
        range_row = QHBoxLayout()
        self.puzzle_range_from = QSpinBox(); self.puzzle_range_from.setRange(1, 999999); self.puzzle_range_from.setPrefix("#")
        self.puzzle_range_to = QSpinBox(); self.puzzle_range_to.setRange(1, 999999); self.puzzle_range_to.setPrefix("#")
        btn_range = QPushButton("Apply Range"); btn_range.clicked.connect(self._puzzle_select_range)
        range_row.addWidget(QLabel("From:")); range_row.addWidget(self.puzzle_range_from)
        range_row.addWidget(QLabel("To:")); range_row.addWidget(self.puzzle_range_to)
        range_row.addWidget(btn_range); fl.addLayout(range_row)
        self.puzzle_sel_label = QLabel("Selected: 0")
        self.puzzle_sel_label.setAlignment(Qt.AlignRight); fl.addWidget(self.puzzle_sel_label)
        l.addWidget(filter_group)

        # ── 3. Puzzle List ───────────────────────────────────────────────
        list_group = QGroupBox("📋 Puzzles"); ll = QVBoxLayout(list_group)
        self.puzzle_list = CheckableListWidget(); self.puzzle_list.setMaximumHeight(160)
        self.puzzle_list.itemChanged.connect(self._on_puzzle_item_changed)
        ll.addWidget(self.puzzle_list)
        nav = QHBoxLayout()
        self.btn_pz_prev = QPushButton("◀"); self.btn_pz_prev.clicked.connect(self._pz_prev_page)
        self.pz_page_lbl = QLabel("Page 0 / 0"); self.pz_page_lbl.setAlignment(Qt.AlignCenter)
        self.btn_pz_next = QPushButton("▶"); self.btn_pz_next.clicked.connect(self._pz_next_page)
        nav.addWidget(self.btn_pz_prev); nav.addWidget(self.pz_page_lbl, 1); nav.addWidget(self.btn_pz_next)
        nav.addWidget(QLabel("Jump:"))
        self.pz_jump_spin = QSpinBox(); self.pz_jump_spin.setRange(1, 999999); self.pz_jump_spin.setFixedWidth(65)
        btn_jump = QPushButton("Go"); btn_jump.setFixedWidth(35); btn_jump.clicked.connect(self._pz_jump_page)
        nav.addWidget(self.pz_jump_spin); nav.addWidget(btn_jump); ll.addLayout(nav)
        btn_load = QPushButton("📋 Load Selected Puzzle to Board")
        btn_load.clicked.connect(self.load_puzzle); ll.addWidget(btn_load); l.addWidget(list_group)

        # ── 4. Export Settings ───────────────────────────────────────────
        export_group = QGroupBox("🎬 Export Configuration"); eform = QFormLayout(export_group); eform.setSpacing(8)
        self.exp_preset = QComboBox(); self.exp_preset.addItems(EXPORT_PRESETS.keys())
        self.exp_preset.setCurrentText("Board Only (544×544)"); eform.addRow("Preset:", self.exp_preset)
        self.exp_title = QLineEdit(); self.exp_title.setPlaceholderText("Leave blank for puzzle name")
        eform.addRow("Title:", self.exp_title)
        self.exp_end = QLineEdit("Solved!"); eform.addRow("End text:", self.exp_end)
        row_fps = QHBoxLayout()
        self.exp_fps = QSpinBox(); self.exp_fps.setRange(10, 120); self.exp_fps.setValue(30)
        self.exp_workers = QSpinBox(); self.exp_workers.setRange(1, 16); self.exp_workers.setValue(4)
        row_fps.addWidget(self.exp_fps); row_fps.addWidget(QLabel("Workers:")); row_fps.addWidget(self.exp_workers)
        eform.addRow("FPS:", row_fps)
        row_theme = QHBoxLayout()
        self.exp_theme = QComboBox(); self.exp_theme.addItems(THEMES.keys())
        self.exp_theme.setCurrentText(self.theme_cb.currentText()); row_theme.addWidget(self.exp_theme)
        eform.addRow("Theme:", row_theme)
        self.exp_outdir = QLineEdit(); self.exp_outdir.setPlaceholderText("Output directory…")
        eform.addRow("Output:", self.exp_outdir)
        row_format = QHBoxLayout()
        self.exp_gif = QCheckBox("Export as GIF"); row_format.addWidget(self.exp_gif)
        self.exp_gif_fps = QSpinBox(); self.exp_gif_fps.setRange(5, 30); self.exp_gif_fps.setValue(12)
        self.exp_gif_fps.setEnabled(False); self.exp_gif.toggled.connect(self.exp_gif_fps.setEnabled)
        row_format.addWidget(QLabel("GIF FPS:")); row_format.addWidget(self.exp_gif_fps)
        eform.addRow("Format:", row_format)
        self.exp_gpu = QCheckBox("GPU post-process")
        self.exp_gpu.setChecked(HAS_CUPY); self.exp_gpu.setEnabled(HAS_CUPY); eform.addRow(self.exp_gpu)
        row_gpu1 = QHBoxLayout()
        self.exp_vignette = QSlider(Qt.Horizontal); self.exp_vignette.setRange(0, 100); self.exp_vignette.setValue(25)
        self.exp_vignette_lbl = QLabel("0.25")
        self.exp_vignette.valueChanged.connect(lambda v: self.exp_vignette_lbl.setText(f"{v/100:.2f}"))
        row_gpu1.addWidget(self.exp_vignette, 1); row_gpu1.addWidget(self.exp_vignette_lbl)
        eform.addRow("Vignette:", row_gpu1)
        row_gpu2 = QHBoxLayout()
        self.exp_contrast = QSlider(Qt.Horizontal); self.exp_contrast.setRange(80, 150); self.exp_contrast.setValue(102)
        self.exp_contrast_lbl = QLabel("1.02")
        self.exp_contrast.valueChanged.connect(lambda v: self.exp_contrast_lbl.setText(f"{v/100:.2f}"))
        row_gpu2.addWidget(self.exp_contrast, 1); row_gpu2.addWidget(self.exp_contrast_lbl)
        eform.addRow("Contrast:", row_gpu2)
        row_gpu3 = QHBoxLayout()
        self.exp_saturation = QSlider(Qt.Horizontal); self.exp_saturation.setRange(80, 150); self.exp_saturation.setValue(105)
        self.exp_saturation_lbl = QLabel("1.05")
        self.exp_saturation.valueChanged.connect(lambda v: self.exp_saturation_lbl.setText(f"{v/100:.2f}"))
        row_gpu3.addWidget(self.exp_saturation, 1); row_gpu3.addWidget(self.exp_saturation_lbl)
        eform.addRow("Saturation:", row_gpu3); l.addWidget(export_group)

        # ── 5. Export Actions ────────────────────────────────────────────
        action_group = QGroupBox("🚀 Export Actions"); al = QVBoxLayout(action_group)
        exp_btns = QHBoxLayout()
        self.btn_export_current = QPushButton("Current"); self.btn_export_current.clicked.connect(self._export_current_puzzle)
        self.btn_export_selected = QPushButton("Selected"); self.btn_export_selected.clicked.connect(self._export_selected_batch)
        self.btn_export_all = QPushButton("All"); self.btn_export_all.clicked.connect(self._export_all_batch)
        exp_btns.addWidget(self.btn_export_current); exp_btns.addWidget(self.btn_export_selected)
        exp_btns.addWidget(self.btn_export_all); al.addLayout(exp_btns)
        self.puzzle_progress = QProgressBar(); self.puzzle_progress.setRange(0, 100); self.puzzle_progress.setValue(0)
        al.addWidget(self.puzzle_progress)
        self.puzzle_status = QLabel(""); self.puzzle_status.setWordWrap(True); al.addWidget(self.puzzle_status)
        self.btn_cancel_export = QPushButton("✕ Cancel Export")
        self.btn_cancel_export.clicked.connect(self._cancel_export); self.btn_cancel_export.setEnabled(False)
        al.addWidget(self.btn_cancel_export); l.addWidget(action_group)
        self.puzzle_info = QTextEdit(); self.puzzle_info.setReadOnly(True); self.puzzle_info.setMaximumHeight(50)
        l.addWidget(self.puzzle_info); l.addStretch(); scroll.setWidget(container)
        self.tabs.addTab(scroll, "🧩 Puzzles")

    # ── Puzzle pagination helpers ────────────────────────────────────────

    def _pz_total_items(self):
        return self.db.get_count('puzzles', self.puzzle_filter.text().strip())

    def _pz_page_count(self):
        return max(1, math.ceil(self._pz_total_items() / self._PAGE_SIZE))

    def _populate_puzzle_page(self):
        self.puzzle_list.blockSignals(True); self.puzzle_list.clear()
        filter_text = self.puzzle_filter.text().strip()
        items = self.db.get_page('puzzles', self._pz_page, self._PAGE_SIZE, filter_text)
        for item in items:
            di = item['id']; checked = di in self._pz_checked
            list_item = self.puzzle_list.add_checkable_item(item["name"], data=item, checked=checked)
            list_item.setData(Qt.UserRole + 1, di)
        self.puzzle_list.blockSignals(False)
        self._update_puzzle_nav(); self._update_puzzle_sel_label()

    def _update_puzzle_nav(self):
        total = self._pz_total_items(); pc = max(1, math.ceil(total / self._PAGE_SIZE))
        self.pz_page_lbl.setText(f"Page {self._pz_page + 1} / {pc}  ({total:,} items)")
        self.btn_pz_prev.setEnabled(self._pz_page > 0)
        self.btn_pz_next.setEnabled(self._pz_page < pc - 1)
        self.pz_jump_spin.setRange(1, pc); self.pz_jump_spin.setValue(self._pz_page + 1)
        count = self.db.get_count('puzzles')
        self.puzzle_range_from.setRange(1, max(1, count)); self.puzzle_range_to.setRange(1, max(1, count))

    def _update_puzzle_sel_label(self, _item=None):
        cnt = len(self._pz_checked); total = self.db.get_count('puzzles')
        self.puzzle_sel_label.setText(f"Selected: {cnt:,} / {total:,}")

    def _on_puzzle_item_changed(self, item):
        di = item.data(Qt.UserRole + 1)
        if di is None: return
        if item.checkState() == Qt.Checked: self._pz_checked.add(di)
        else: self._pz_checked.discard(di)
        self._update_puzzle_sel_label()

    def _apply_puzzle_filter(self):
        self._pz_page = 0; self._populate_puzzle_page()

    def _puzzle_select_all(self):
        self._pz_checked = set(self.db.get_ids_by_filter('puzzles', self.puzzle_filter.text().strip()))
        self._populate_puzzle_page()

    def _puzzle_select_none(self):
        self._pz_checked.clear(); self._populate_puzzle_page()

    def _puzzle_select_invert(self):
        all_ids = set(self.db.get_ids_by_filter('puzzles', self.puzzle_filter.text().strip()))
        self._pz_checked = all_ids - self._pz_checked; self._populate_puzzle_page()

    def _puzzle_select_range(self):
        start = self.puzzle_range_from.value(); end = self.puzzle_range_to.value()
        if start > end: start, end = end, start
        all_ids = self.db.get_ids_by_filter('puzzles')
        for i in range(start - 1, min(end, len(all_ids))):
            self._pz_checked.add(all_ids[i])
        self._populate_puzzle_page()

    def _pz_prev_page(self):
        if self._pz_page > 0: self._pz_page -= 1; self._populate_puzzle_page()

    def _pz_next_page(self):
        if self._pz_page < self._pz_page_count() - 1: self._pz_page += 1; self._populate_puzzle_page()

    def _pz_jump_page(self):
        page = self.pz_jump_spin.value() - 1
        if 0 <= page < self._pz_page_count(): self._pz_page = page; self._populate_puzzle_page()

    # ── Build export config ──────────────────────────────────────────────

    def _build_export_config(self, puzzle_name=""):
        cfg = ExportConfig()
        title_text = self.exp_title.text().strip()
        cfg.title_text = title_text if title_text else puzzle_name
        cfg.end_text = self.exp_end.text(); cfg.fps = self.exp_fps.value()
        cfg.max_workers = self.exp_workers.value(); cfg.theme_name = self.exp_theme.currentText()
        cfg.output_dir = self.exp_outdir.text().strip()
        cfg.gpu_post_process = self.exp_gpu.isChecked()
        cfg.gpu_vignette = self.exp_vignette.value() / 100.0
        cfg.gpu_contrast = self.exp_contrast.value() / 100.0
        cfg.gpu_saturation = self.exp_saturation.value() / 100.0
        cfg.apply_preset(self.exp_preset.currentText())
        cfg.export_gif = self.exp_gif.isChecked(); cfg.gif_fps = self.exp_gif_fps.value()
        return cfg

    def _ensure_output_dir(self):
        d = self.exp_outdir.text().strip()
        if not d: d = (self.settings_outdir.text().strip() if hasattr(self, 'settings_outdir') else "")
        if not d:
            d = str(Path(DATA_DIR) / "exports"); self.exp_outdir.setText(d)
            if hasattr(self, 'settings_outdir'): self.settings_outdir.setText(d)
        os.makedirs(d, exist_ok=True); return d

    # ── Export: current puzzle ────────────────────────────────────────────

    def _export_current_puzzle(self):
        item = self.puzzle_list.currentItem()
        if not item: self.puzzle_status.setText("No puzzle selected."); return
        pz_slim = item.data(Qt.UserRole)
        if not pz_slim: self.puzzle_status.setText("No puzzle data."); return
        full = self.db.get_items_by_ids('puzzles', [pz_slim['id']])
        if not full: self.puzzle_status.setText("Failed to load puzzle data."); return
        pz_copy = dict(full[0]); pz_copy['display_title'] = f"Puzzle #{pz_copy['id']}"
        out_dir = self._ensure_output_dir(); cfg = self._build_export_config(pz_copy.get('display_title', pz_copy['name']))
        ext = ".gif" if cfg.export_gif else ".mp4"
        filename = sanitize_filename(pz_copy['name']) + ext
        filepath = os.path.join(out_dir, filename)
        if os.path.exists(filepath):
            base = sanitize_filename(pz_copy['name']); i = 2
            while os.path.exists(os.path.join(out_dir, f"{base}_{i}{ext}")): i += 1
            filepath = os.path.join(out_dir, f"{base}_{i}{ext}")
        log(f"Exporting current puzzle: {pz_copy['name']} -> {filepath}", "EXPORT")
        self._set_exporting(True)
        self.export_worker = ExportWorker(pz_copy, filepath, cfg)
        self.export_worker.progress.connect(self._on_single_progress)
        self.export_worker.finished.connect(self._on_single_finished)
        self.export_worker.start()

    def _export_selected_batch(self):
        if not self._pz_checked: self.puzzle_status.setText("No puzzles checked."); return
        puzzles = self.db.get_items_by_ids('puzzles', list(self._pz_checked))
        for p in puzzles: p['display_title'] = f"Puzzle #{p['id']}"
        self._start_batch_export(puzzles)

    def _export_all_batch(self):
        total = self.db.get_count('puzzles')
        if total == 0: self.puzzle_status.setText("No puzzles loaded."); return
        all_ids = self.db.get_ids_by_filter('puzzles')
        puzzles = self.db.get_items_by_ids('puzzles', all_ids)
        for p in puzzles: p['display_title'] = f"Puzzle #{p['id']}"
        self._start_batch_export(puzzles)

    def _on_single_progress(self, pct):
        self.puzzle_progress.setValue(pct); self.puzzle_status.setText(f"Rendering… {pct}%")

    def _on_single_finished(self, msg):
        self.puzzle_status.setText(msg); self.puzzle_progress.setValue(100 if "Saved" in msg else 0)
        self._set_exporting(False)
        if self.export_worker: self.export_worker.deleteLater(); self.export_worker = None

    # ── Export: batch ─────────────────────────────────────────────────────

    def _start_batch_export(self, puzzles):
        out_dir = self._ensure_output_dir(); cfg = self._build_export_config()
        total = len(puzzles); log(f"Starting batch export: {total} puzzles -> {out_dir}", "EXPORT")
        self._set_exporting(True, batch=True)
        self.puzzle_progress.setValue(0); self.puzzle_status.setText(f"Batch: 0 / {total}")
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.abort(); self.batch_worker.wait(3000)
        self.batch_worker = BatchExportWorker(puzzles, out_dir, cfg)
        self.batch_worker.batch_progress.connect(self._on_batch_progress)
        self.batch_worker.puzzle_done.connect(self._on_batch_puzzle_done)
        self.batch_worker.puzzle_error.connect(self._on_batch_puzzle_error)
        self.batch_worker.all_done.connect(self._on_batch_all_done)
        self.batch_worker.start()

    def _on_batch_progress(self, idx, total, name):
        pct = int(100 * (idx + 1) / total) if total > 0 else 0
        self.puzzle_progress.setValue(pct); self.puzzle_status.setText(f"Batch [{idx+1}/{total}]: {name}")

    def _on_batch_puzzle_done(self, idx, filepath):
        log(f"Batch puzzle done: {filepath}", "EXPORT")

    def _on_batch_puzzle_error(self, idx, msg):
        log(f"Batch puzzle error: {msg}", "EXPORT")

    def _on_batch_all_done(self, exported, errors, out_dir):
        self.puzzle_progress.setValue(100)
        self.puzzle_status.setText(f"Batch done: {exported} exported, {errors} errors → {out_dir}")
        self._set_exporting(False, batch=True)
        if self.batch_worker: self.batch_worker.deleteLater(); self.batch_worker = None

    # ── Cancel / UI state ────────────────────────────────────────────────

    def _cancel_export(self):
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.abort(); self.puzzle_status.setText("Cancelling…")
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.abort(); self.puzzle_status.setText("Cancelling batch…")

    def _set_exporting(self, busy, batch=False):
        self.btn_export_current.setEnabled(not busy)
        self.btn_export_selected.setEnabled(not busy)
        self.btn_export_all.setEnabled(not busy)
        self.btn_cancel_export.setEnabled(busy)

    # ── Load puzzle DB ───────────────────────────────────────────────────

    def load_puzzle_db(self):
        path = self.puzzle_db_path.text().strip()
        if not path: self.puzzle_db_status.setText("Enter a database path above first."); return
        if not os.path.exists(path): self.puzzle_db_status.setText(f"File not found: {path}"); return
        self.puzzle_db_status.setText("Loading…"); self._start_data_load("puzzles", single_file=path)

    # ── Load puzzle to board ─────────────────────────────────────────────

    def load_puzzle(self):
        item = self.puzzle_list.currentItem()
        if not item: return
        pz_slim = item.data(Qt.UserRole)
        if not pz_slim: return
        full = self.db.get_items_by_ids('puzzles', [pz_slim['id']])
        if not full: return
        pz = full[0]
        if pz.get("fen"): self.engine.load_fen(pz["fen"])
        else: self.engine.reset()
        self.puzzle_info.setText(pz.get("desc", ""))
        self.board_widget.selected = None; self.board_widget.legal_targets = []
        self.board_widget.update(); self.snd.play("start")

    # ════════════════════════════════════════════════════════════════════════
    #  SETTINGS TAB
    # ════════════════════════════════════════════════════════════════════════

    def _build_settings_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget(); l = QVBoxLayout(container); l.setSpacing(12)
        appear_group = QGroupBox("🎨 Appearance"); aform = QFormLayout(appear_group)
        self.settings_theme_cb = QComboBox(); self.settings_theme_cb.addItems(THEMES.keys())
        self.settings_theme_cb.currentTextChanged.connect(self._change_theme)
        aform.addRow("Theme:", self.settings_theme_cb)
        row_anim = QHBoxLayout()
        self.settings_anim_slider = QSlider(Qt.Horizontal)
        self.settings_anim_slider.setRange(0, 600); self.settings_anim_slider.setValue(600 - ANIM_SPEED_DEFAULT)
        self.settings_anim_slider.setInvertedAppearance(True)
        self.settings_anim_lbl = QLabel(self._fmt_anim(ANIM_SPEED_DEFAULT))
        self.settings_anim_slider.valueChanged.connect(self._update_anim_speed)
        row_anim.addWidget(self.settings_anim_slider, 1); row_anim.addWidget(self.settings_anim_lbl)
        aform.addRow("Anim Speed:", row_anim); l.addWidget(appear_group)
        path_group = QGroupBox("📁 Default Export Path"); pl = QHBoxLayout(path_group)
        self.settings_outdir = QLineEdit(str(Path(DATA_DIR) / "exports"))
        pl.addWidget(self.settings_outdir, 1); l.addWidget(path_group)
        db_info_group = QGroupBox("💾 Database Info"); db_info_layout = QVBoxLayout(db_info_group)
        db_info_layout.addWidget(QLabel("Cache format: Parquet (.parquet / .pq)"))
        db_info_layout.addWidget(QLabel(f"Puzzles cache: {self.db._cache_path('puzzles')}"))
        l.addWidget(db_info_group); l.addStretch(); scroll.setWidget(container)
        self.tabs.addTab(scroll, "⚙️ Settings")


def main():
    log("Launching Chess Puzzle App…", "APP")
    app = QApplication(sys.argv); app.setStyle("Fusion")
    shell = QMainWindow(); shell.setWindowTitle("♚ Chess Puzzle App")
    shell.setCentralWidget(MainWindow()); shell.resize(1020, 640); shell.show()
    log("Event loop started", "APP"); sys.exit(app.exec())


if __name__ == "__main__":
    main()