#!/usr/bin/env python3
"""Constants, themes, presets, and configuration classes."""

import hashlib
import os
import shutil
import threading

import chess
from PySide6.QtGui import QColor

# ── File Paths ──────────────────────────────────────────────────────────────

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
EXPORT_DIR = os.path.join(APP_DIR, "exports")
LICHESS_PARQUET_NAME = "lichess_db_puzzle.parquet"
LICHESS_DB_PATH = os.path.join(DATA_DIR, LICHESS_PARQUET_NAME)
EXPORT_MANIFEST_PATH = os.path.join(DATA_DIR, "export_manifest.duckdb")

# ── External Dependency Checks ──────────────────────────────────────────────

HAS_FFMPEG = shutil.which("ffmpeg") is not None

# ── Board / Rendering Constants ─────────────────────────────────────────────

SQ_SIZE = 68
BOARD_PX = SQ_SIZE * 8

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

# ── Layout Modes ────────────────────────────────────────────────────────────

class LayoutMode:
    BOARD_ONLY          = "board_only"
    BOARD_MOVES_RIGHT   = "board_moves_right"
    BOARD_MOVES_BOTTOM  = "board_moves_bottom"

LAYOUT_MODES = {
    LayoutMode.BOARD_ONLY:         "Board Only",
    LayoutMode.BOARD_MOVES_RIGHT:  "Board + Moves (Right)",
    LayoutMode.BOARD_MOVES_BOTTOM: "Board + Moves (Bottom)",
}

# ── Move Panel Size Constraints ─────────────────────────────────────────────

MIN_MOVE_PANEL_W = 200
MAX_MOVE_PANEL_W = 400
MIN_MOVE_PANEL_H = 140
MAX_MOVE_PANEL_H = 300

# ── Minimalist Color Palette (Tokyo Night inspired) ────────────────────────

class MiniColors:
    bg           = "#1a1b26"
    surface      = "#24283b"
    surface2     = "#2f3349"
    border       = "#3b4261"
    border_subtle= "#292e42"
    text         = "#c0caf5"
    text_dim     = "#565f89"
    text_subtle  = "#a9b1d6"
    accent       = "#7aa2f7"
    accent_dim   = "#3d59a1"
    green        = "#9ece6a"
    red          = "#f7768e"
    yellow       = "#e0af68"
    cyan         = "#7dcfff"
    purple       = "#bb9af7"

# ── Board Themes ────────────────────────────────────────────────────────────

class BoardTheme:
    def __init__(self, name="Classic",
                 light=(240, 217, 181), dark=(181, 136, 99),
                 border=(48, 26, 7), highlight=(255, 255, 0, 100),
                 last_move=(155, 199, 0, 100), arrow=(220, 50, 47, 200)):
        self.name = name
        self.light_sq = QColor(*light)
        self.dark_sq = QColor(*dark)
        self.border = QColor(*border)
        self.highlight = QColor(*highlight)
        self.last_move = QColor(*last_move)
        self.arrow_clr = QColor(*arrow)
        self.bg = QColor(32, 32, 36)
        self.coord = QColor(180, 160, 130)


THEMES = {
    "Classic": BoardTheme(),
    "Blue":    BoardTheme("Blue", (208, 224, 243), (116, 150, 194), (40, 50, 70)),
    "Green":   BoardTheme("Green", (238, 238, 210), (118, 150, 86), (50, 60, 40)),
    "Brown":   BoardTheme("Brown", (222, 197, 165), (170, 120, 70), (60, 35, 15)),
    "Purple":  BoardTheme("Purple", (220, 210, 230), (150, 130, 170), (50, 40, 60)),
    "Ice":     BoardTheme("Ice", (230, 240, 250), (160, 190, 220), (50, 60, 80)),
    "Midnight": BoardTheme("Midnight", (35, 40, 58), (22, 27, 44), (15, 18, 30),
                           highlight=(122, 162, 247, 80), last_move=(158, 206, 106, 80),
                           arrow=(122, 162, 247, 200)),
}

# ── Move List Panel Colors ─────────────────────────────────────────────────

MOVE_LIST_COLORS = {
    'bg':           (26, 27, 46),
    'text':         (192, 202, 245),
    'dim':          (86, 95, 137),
    'accent':       (122, 162, 247),
    'highlight_bg': (122, 162, 247, 30),
    'border':       (59, 66, 97),
}

# ── Pagination ──────────────────────────────────────────────────────────────

PUZZLES_PER_PAGE = 200
PAGE_SIZE_OPTIONS = [50, 100, 200, 500]

# ── Lichess Database Exact Mapping ─────────────────────────────────────────

LICHESS_COLUMNS = {
    'id': 'PuzzleId',
    'fen': 'FEN',
    'moves': 'Moves',
    'rating': 'Rating',
    'rating_deviation': 'RatingDeviation',
    'popularity': 'Popularity',
    'nb_plays': 'NbPlays',
    'themes': 'Themes',
    'game_url': 'GameUrl',
    'opening': 'OpeningTags'
}

# ── Export Presets & Bitrate Targets ────────────────────────────────────────

RESOLUTION_BITRATES = {
    (3840, 2160): 56000, (2160, 3840): 56000,
    (2560, 1440): 20000, (1440, 2560): 20000,
    (1920, 1080): 10000, (1080, 1920): 10000,
    (1280, 720):  6000,  (720, 1280):  6000,
}

class ExportPreset:
    def __init__(self, name, width, height, fps=30, board_frac=0.82,
                 bg=(26, 27, 46), description="", layout=LayoutMode.BOARD_ONLY):
        self.name = name
        self.width = width
        self.height = height
        self.fps = fps
        self.board_frac = board_frac
        self.bg = bg
        self.description = description
        self.layout = layout

    @property
    def bitrate(self):
        return RESOLUTION_BITRATES.get((self.width, self.height), 8000)

    @property
    def aspect_ratio(self):
        from math import gcd
        g = gcd(self.width, self.height)
        return self.width // g, self.height // g

    @property
    def is_vertical(self):
        return self.height > self.width

    @property
    def is_square(self):
        return self.width == self.height

    def calc_sq_size(self):
        if self.layout == LayoutMode.BOARD_MOVES_RIGHT:
            max_board_px = min(self.width - MIN_MOVE_PANEL_W, self.height)
        elif self.layout == LayoutMode.BOARD_MOVES_BOTTOM:
            max_board_px = min(self.width, self.height - MIN_MOVE_PANEL_H)
        else:
            max_board_px = min(self.width, self.height) * self.board_frac
        board_px = (max(1, int(max_board_px)) // 8) * 8
        return max(8, board_px // 8)


EXPORT_PRESETS = {
    "YouTube 4K (3840×2160)": ExportPreset("YouTube 4K", 3840, 2160, 30, 0.70, (26, 27, 46), "16:9 4K", LayoutMode.BOARD_MOVES_RIGHT),
    "YouTube 1440p (2560×1440)": ExportPreset("YouTube 1440p", 2560, 1440, 30, 0.72, (26, 27, 46), "16:9 1440p", LayoutMode.BOARD_MOVES_RIGHT),
    "YouTube 1080p (1920×1080)": ExportPreset("YouTube 1080p", 1920, 1080, 30, 0.75, (26, 27, 46), "16:9 Full HD", LayoutMode.BOARD_MOVES_RIGHT),
    "YouTube 720p (1280×720)": ExportPreset("YouTube 720p", 1280, 720, 30, 0.78, (26, 27, 46), "16:9 HD", LayoutMode.BOARD_MOVES_RIGHT),
    "Shorts 4K (2160×3840)": ExportPreset("Shorts 4K", 2160, 3840, 30, 0.48, (26, 27, 46), "9:16 4K", LayoutMode.BOARD_MOVES_BOTTOM),
    "Shorts 1440p (1440×2560)": ExportPreset("Shorts 1440p", 1440, 2560, 30, 0.48, (26, 27, 46), "9:16 1440p", LayoutMode.BOARD_MOVES_BOTTOM),
    "Shorts 1080p (1080×1920)": ExportPreset("Shorts 1080p", 1080, 1920, 30, 0.48, (26, 27, 46), "9:16 vertical", LayoutMode.BOARD_MOVES_BOTTOM),
    "Shorts 720p (720×1280)": ExportPreset("Shorts 720p", 720, 1280, 30, 0.48, (26, 27, 46), "9:16 vertical", LayoutMode.BOARD_MOVES_BOTTOM),
    "Board Only (544×544)": ExportPreset("Board Only", 544, 544, 30, 1.0, (26, 27, 46), "Square board-only"),
    "Custom": ExportPreset("Custom", 544, 544, 30, 0.82, (26, 27, 46), "User-defined"),
}

# ── Sound Effect Packs ──────────────────────────────────────────────────────

SOUND_PACKS = ["Classic", "Digital", "Wooden", "Arcade"]

SOUND_EFFECTS = [
    "move", "capture", "check", "checkmate",
    "castle", "error", "promote", "start", "solved",
]

# ── YouTube Quality Constants (hardcoded) ───────────────────────────────────

YOUTUBE_FFMPEG_PRESET = "slow"
YOUTUBE_AUDIO_BITRATE = "192k"

# ── Export Configuration ─────────────────────────────────────────────────────

class ExportConfig:
    def __init__(self):
        self.fps = 30
        self.title_enabled = True
        self.title_text = ""
        self.title_duration = 3.0
        self.title_bg = "#1a1b26"
        self.title_fg = "#c0caf5"
        self.title_font_size = 36

        self.position_hold_enabled = True
        self.position_hold_duration = 3.0
        self.position_overlay_text = "White to play"

        self.end_enabled = True
        self.end_text = "Solved!"
        self.end_duration = 3.0
        self.end_bg = "#1a1b26"
        self.end_fg = "#c0caf5"
        self.end_font_size = 42

        self.move_speed = 1.0
        self.pause_after_move = 0.5
        self.pause_on_key_moves = True
        self.key_move_pause_multiplier = 2.0
        self.highlight_last_move = True
        self.highlight_key_squares = False

        self.loop_count = 1
        self.easing_curve = "ease_out"

        self.max_workers = 4
        self.sq_size = SQ_SIZE
        self.theme_name = "Midnight"
        self.gpu_post_process = True
        self.gpu_vignette = 0.25
        self.gpu_contrast = 1.02
        self.gpu_saturation = 1.05

        self.output_dir = ""
        self.batch_combine = False
        self.preset_name = "YouTube 1080p (1920×1080)"
        self.target_width = 1920
        self.target_height = 1080
        self.background_color = (26, 27, 46)
        self.board_frac = 0.75
        self.export_gif = False
        self.gif_fps = 12
        self.layout_mode = LayoutMode.BOARD_MOVES_RIGHT

        self.move_list_visible = True
        self.coordinate_visible = True
        self.batch_size = 16
        self.show_arrow = True
        self.sound_pack = "Classic"

    def apply_preset(self, preset_name):
        if preset_name in EXPORT_PRESETS:
            p = EXPORT_PRESETS[preset_name]
            self.preset_name = preset_name
            self.target_width = p.width
            self.target_height = p.height
            self.fps = p.fps
            self.background_color = p.bg
            self.board_frac = p.board_frac
            self.layout_mode = p.layout
            if preset_name != "Custom":
                self.sq_size = p.calc_sq_size()

    @property
    def effective_sq_size(self):
        if self.preset_name and self.preset_name not in ("Board Only (544×544)", "Custom"):
            p = EXPORT_PRESETS.get(self.preset_name)
            if p:
                return p.calc_sq_size()
        return self.sq_size

    @property
    def is_vertical(self):
        return self.target_height > self.target_width

    @property
    def effective_bitrate(self):
        p = EXPORT_PRESETS.get(self.preset_name)
        if p: return p.bitrate
        return RESOLUTION_BITRATES.get((self.target_width, self.target_height), 8000)

    @property
    def move_anim_duration(self):
        return self.move_speed

    @property
    def move_panel_width(self):
        if self.layout_mode == LayoutMode.BOARD_MOVES_RIGHT:
            sq = self.effective_sq_size
            bw = sq * 8
            remaining = self.target_width - bw
            panel_w = max(MIN_MOVE_PANEL_W, min(MAX_MOVE_PANEL_W, int(bw * 0.38)))
            return min(panel_w, remaining)
        return 0

    @property
    def move_panel_height(self):
        if self.layout_mode == LayoutMode.BOARD_MOVES_BOTTOM:
            sq = self.effective_sq_size
            bh = sq * 8
            remaining = self.target_height - bh
            panel_h = max(MIN_MOVE_PANEL_H, min(MAX_MOVE_PANEL_H, int(bh * 0.28)))
            return min(panel_h, remaining)
        return 0

    def estimate_duration(self, n_moves):
        total = 0.0
        if self.title_enabled and self.title_text:
            total += self.title_duration
        if self.position_hold_enabled:
            total += self.position_hold_duration
        loops = max(1, self.loop_count)
        total += loops * n_moves * (self.move_anim_duration + self.pause_after_move)
        if self.end_enabled and self.end_text:
            total += self.end_duration
        return max(1.0, total)

    # ── Serialization ───────────────────────────────────────────────────

    def to_dict(self):
        return {
            'fps': self.fps,
            'title_enabled': self.title_enabled,
            'title_text': self.title_text,
            'title_duration': self.title_duration,
            'title_bg': self.title_bg,
            'title_fg': self.title_fg,
            'title_font_size': self.title_font_size,
            'position_hold_enabled': self.position_hold_enabled,
            'position_hold_duration': self.position_hold_duration,
            'position_overlay_text': self.position_overlay_text,
            'end_enabled': self.end_enabled,
            'end_text': self.end_text,
            'end_duration': self.end_duration,
            'end_bg': self.end_bg,
            'end_fg': self.end_fg,
            'end_font_size': self.end_font_size,
            'move_speed': self.move_speed,
            'pause_after_move': self.pause_after_move,
            'pause_on_key_moves': self.pause_on_key_moves,
            'key_move_pause_multiplier': self.key_move_pause_multiplier,
            'highlight_last_move': self.highlight_last_move,
            'highlight_key_squares': self.highlight_key_squares,
            'loop_count': self.loop_count,
            'easing_curve': self.easing_curve,
            'theme_name': self.theme_name,
            'gpu_post_process': self.gpu_post_process,
            'gpu_vignette': self.gpu_vignette,
            'gpu_contrast': self.gpu_contrast,
            'gpu_saturation': self.gpu_saturation,
            'preset_name': self.preset_name,
            'target_width': self.target_width,
            'target_height': self.target_height,
            'background_color': list(self.background_color),
            'board_frac': self.board_frac,
            'export_gif': self.export_gif,
            'gif_fps': self.gif_fps,
            'layout_mode': self.layout_mode,
            'move_list_visible': self.move_list_visible,
            'coordinate_visible': self.coordinate_visible,
            'show_arrow': self.show_arrow,
            'sound_pack': self.sound_pack,
        }

    def from_dict(self, d):
        if not d or not isinstance(d, dict):
            return
        _simple = {
            'fps', 'title_enabled', 'title_text', 'title_duration',
            'title_bg', 'title_fg', 'title_font_size',
            'position_hold_enabled', 'position_hold_duration',
            'position_overlay_text', 'end_enabled', 'end_text',
            'end_duration', 'end_bg', 'end_fg', 'end_font_size',
            'move_speed', 'pause_after_move', 'pause_on_key_moves',
            'key_move_pause_multiplier', 'highlight_last_move',
            'highlight_key_squares', 'loop_count', 'easing_curve',
            'theme_name', 'gpu_post_process', 'gpu_vignette',
            'gpu_contrast', 'gpu_saturation', 'preset_name',
            'export_gif', 'gif_fps',
            'layout_mode', 'move_list_visible', 'coordinate_visible',
            'show_arrow', 'sound_pack',
        }
        for key in _simple:
            if key in d:
                setattr(self, key, d[key])
        if 'target_width' in d:
            self.target_width = int(d['target_width'])
        if 'target_height' in d:
            self.target_height = int(d['target_height'])
        if 'background_color' in d:
            bc = d['background_color']
            if isinstance(bc, (list, tuple)) and len(bc) >= 3:
                self.background_color = tuple(bc[:3])
        if 'board_frac' in d:
            self.board_frac = float(d['board_frac'])

# ── Puzzle ID & Export Manifest ─────────────────────────────────────────────

def _get_puzzle_id(puzzle):
    """Get or generate a consistent, unique puzzle ID."""
    pid = puzzle.get('id', '')
    if pid and str(pid).strip() and str(pid).strip().lower() not in ('nan', 'none', ''):
        return str(pid).strip()
    fen = puzzle.get('fen', '')
    moves = ' '.join(puzzle.get('moves', []))
    hash_input = f"{fen}|{moves}"
    return hashlib.md5(hash_input.encode()).hexdigest()[:16]


class ExportManifest:
    """Tracks exported puzzles in a local DuckDB (or JSON fallback) database."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = None
        self._json_data = {}
        self._json_path = os.path.splitext(db_path)[0] + '.json'
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            import duckdb
            self._conn = duckdb.connect(self.db_path)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS export_manifest (
                    puzzle_id VARCHAR PRIMARY KEY,
                    export_time TIMESTAMP DEFAULT current_timestamp,
                    output_path VARCHAR,
                    preset_name VARCHAR,
                    puzzle_name VARCHAR
                )
            """)
            log("Export manifest database initialized (DuckDB)", "MANIFEST")
            return
        except Exception as e:
            log(f"DuckDB manifest init failed ({e}), using JSON fallback", "MANIFEST")
            self._conn = None

        import json
        try:
            if os.path.exists(self._json_path):
                with open(self._json_path, 'r') as f:
                    self._json_data = json.load(f)
                log(f"Export manifest loaded from JSON ({len(self._json_data)} records)", "MANIFEST")
        except Exception:
            self._json_data = {}

    def mark_exported(self, puzzle_id, output_path='', preset_name='', puzzle_name=''):
        with self._lock:
            pid = str(puzzle_id)
            if self._conn:
                try:
                    self._conn.execute("""
                        INSERT OR REPLACE INTO export_manifest
                        (puzzle_id, output_path, preset_name, puzzle_name)
                        VALUES (?, ?, ?, ?)
                    """, [pid, output_path, preset_name, puzzle_name])
                    return
                except Exception:
                    pass
            import json
            from datetime import datetime
            self._json_data[pid] = {
                'export_time': datetime.now().isoformat(),
                'output_path': output_path,
                'preset_name': preset_name,
                'puzzle_name': puzzle_name,
            }
            try:
                with open(self._json_path, 'w') as f:
                    json.dump(self._json_data, f, indent=2)
            except Exception:
                pass

    def is_exported(self, puzzle_id):
        pid = str(puzzle_id)
        with self._lock:
            if self._conn:
                try:
                    result = self._conn.execute(
                        "SELECT 1 FROM export_manifest WHERE puzzle_id = ?", [pid]).fetchone()
                    return result is not None
                except Exception:
                    pass
            return pid in self._json_data

    def get_exported_ids(self, puzzle_ids):
        if not puzzle_ids:
            return set()
        str_ids = [str(pid) for pid in puzzle_ids]
        with self._lock:
            if self._conn:
                try:
                    placeholders = ','.join(['?'] * len(str_ids))
                    rows = self._conn.execute(
                        f"SELECT puzzle_id FROM export_manifest WHERE puzzle_id IN ({placeholders})",
                        str_ids).fetchall()
                    return {r[0] for r in rows}
                except Exception:
                    pass
            return {pid for pid in str_ids if pid in self._json_data}

    def get_info(self, puzzle_id):
        """Return export metadata dict for a puzzle, or None."""
        pid = str(puzzle_id)
        with self._lock:
            if self._conn:
                try:
                    row = self._conn.execute(
                        "SELECT export_time, output_path, preset_name, puzzle_name "
                        "FROM export_manifest WHERE puzzle_id = ?", [pid]).fetchone()
                    if row:
                        return {
                            'timestamp': str(row[0]),
                            'path': row[1] or '',
                            'preset_name': row[2] or '',
                            'puzzle_name': row[3] or '',
                        }
                except Exception:
                    pass
            if pid in self._json_data:
                info = dict(self._json_data[pid])
                info.setdefault('timestamp', info.get('export_time', ''))
                info.setdefault('path', info.get('output_path', ''))
                return info
            return None

    def close(self):
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None


def log(msg, level="INFO"):
    """Convenience logger for config module (avoids circular import from utils)."""
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{level}] {msg}", flush=True)