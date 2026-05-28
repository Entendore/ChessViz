#!/usr/bin/env python3
"""Constants, themes, presets, and configuration classes."""

import os
import chess
from PySide6.QtGui import QColor

# ── File Paths ──────────────────────────────────────────────────────────────

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
LICHESS_PARQUET_NAME = "lichess_db_puzzle.parquet"

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
            shorter = self.height
            board_px = int(shorter * self.board_frac)
        elif self.layout == LayoutMode.BOARD_MOVES_BOTTOM:
            board_frac = min(self.board_frac, 0.70)
            shorter = self.width
            board_px = int(shorter * board_frac)
        else:
            shorter = min(self.width, self.height)
            board_px = int(shorter * self.board_frac)
        board_px = (board_px // 8) * 8
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

# ── Sound Design Presets ────────────────────────────────────────────────────

SOUND_PRESETS = {
    "None": {
        "name": "None",
        "description": "No background audio",
    },
    "Soft Ambient": {
        "name": "Soft Ambient",
        "description": "Gentle layered sine pads",
        "base_freq": 174,
        "harmonics": [1.0, 0.5, 0.25, 0.125],
        "beat_period": 2.5,
        "volume": 0.15,
    },
    "Cinematic": {
        "name": "Cinematic",
        "description": "Deep dramatic atmosphere",
        "base_freq": 110,
        "harmonics": [1.0, 0.6, 0.3],
        "beat_period": 3.0,
        "volume": 0.2,
    },
    "Retro 8-bit": {
        "name": "Retro 8-bit",
        "description": "Chip-tune square-wave melody",
        "base_freq": 330,
        "harmonics": [1.0],
        "beat_period": 0.4,
        "volume": 0.12,
        "square_wave": True,
    },
    "Focus": {
        "name": "Focus",
        "description": "Minimal concentration drone",
        "base_freq": 136,
        "harmonics": [1.0, 0.3],
        "beat_period": 4.0,
        "volume": 0.1,
    },
}

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
        self.audio_path = ""
        self.audio_volume = 0.25
        self.export_gif = False
        self.gif_fps = 12
        self.ffmpeg_crf = 20
        self.ffmpeg_preset = "medium"
        self.layout_mode = LayoutMode.BOARD_MOVES_RIGHT

        self.move_list_visible = True
        self.coordinate_visible = True
        self.batch_size = 16
        self.show_arrow = True
        self.sound_preset = "None"

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
            return self.target_width - sq * 8
        return 0

    @property
    def move_panel_height(self):
        if self.layout_mode == LayoutMode.BOARD_MOVES_BOTTOM:
            sq = self.effective_sq_size
            return self.target_height - sq * 8
        return 0

    def estimate_duration(self, n_moves):
        """Estimate total video duration in seconds for audio generation."""
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