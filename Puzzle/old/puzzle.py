#!/usr/bin/env python3
"""
Chess Puzzle Studio — Professional Chess Puzzle Creator & YouTube Video Generator

A complete desktop application for creating chess puzzles and producing
YouTube videos and Shorts with animated board play, title cards, and overlays.

Architecture:
  DATA       → Puzzle, FilterCriteria, MoveInfo, PuzzleIndex, PuzzleCollection
  ALGORITHM  → Trie, binary search, inverted index, filter pipeline
  DOMAIN     → ChessEngine, BoardRenderer, SoundManager, PuzzleLoader
  VIDEO      → VideoExporter, FrameGenerator, TitleCardRenderer
  UI         → ChessBoardWidget, PuzzleCreatorPanel, VideoEditorPanel,
               FilterPanel, PuzzleBrowserPanel, MainWindow

Install:  pip install PySide6 numpy imageio[ffmpeg] chess
Optional: pip install pandas pyarrow duckdb
"""

from __future__ import annotations

import sys, os, math, time, csv, re, json, shutil
import tempfile, wave, threading, copy
from abc import ABC, abstractmethod
from bisect import bisect_left, bisect_right
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import lru_cache
from pathlib import Path
from typing import (
    Any, Callable, Dict, FrozenSet, Iterator, List, Optional, Sequence,
    Set, Tuple, TypeVar, Union,
)

import chess
import numpy as np
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QTextEdit, QFrame, QListWidget,
    QListWidgetItem, QSlider, QSpinBox, QLineEdit, QFormLayout, QComboBox,
    QProgressBar, QCheckBox, QFileDialog, QDialog, QMessageBox,
    QSizePolicy, QGridLayout, QGroupBox, QScrollArea, QSplitter,
    QToolButton, QMenu, QStatusBar, QDockWidget, QToolBar,
    QDialogButtonBox, QRadioButton, QButtonGroup,
)
from PySide6.QtCore import (
    Qt, QRect, QRectF, Signal, QTimer, QPointF, QUrl, QSize, QObject,
    QThread, Signal as QSignal, QSettings, QMutex, QWaitCondition,
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QRadialGradient,
    QImage, QPixmap, QPolygonF, QPainterPath, QTransform, QPalette,
    QAction, QIcon, QFontMetrics, QLinearGradient,
)
from PySide6.QtMultimedia import QSoundEffect

csv.field_size_limit(2**31 - 1)

# ═══════════════════════════════════════════════════════════════════════════════
#  OPTIONAL DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════════

HAS_IMAGEIO = False
try:
    import imageio.v3 as iio
    HAS_IMAGEIO = True
except Exception:
    pass

HAS_PANDAS = False
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pass

HAS_PYARROW = False
try:
    import pyarrow.parquet as pq
    HAS_PYARROW = True
except ImportError:
    pass

HAS_DUCKDB = False
try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    pass

HAS_FFMPEG = shutil.which('ffmpeg') is not None

# ═══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

def log(msg: str, level: str = "INFO") -> None:
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{level}] {msg}", flush=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS & PATHS
# ═══════════════════════════════════════════════════════════════════════════════

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
SETTINGS_PATH = os.path.join(APP_DIR, "puzzle_studio_settings.json")
os.makedirs(DATA_DIR, exist_ok=True)

SQ_SIZE = 68
BOARD_PX = SQ_SIZE * 8
ANIM_FPS = 60
ANIM_SPEED_DEFAULT = 300

PIECE_SYM = {
    (chess.PAWN, chess.WHITE): "♟", (chess.PAWN, chess.BLACK): "♟",
    (chess.KNIGHT, chess.WHITE): "♞", (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.WHITE): "♝", (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK, chess.WHITE): "♜", (chess.ROOK, chess.BLACK): "♜",
    (chess.QUEEN, chess.WHITE): "♛", (chess.QUEEN, chess.BLACK): "♛",
    (chess.KING, chess.WHITE): "♚", (chess.KING, chess.BLACK): "♚",
}

PIECE_LETTERS = "KQRBNPkqrbnp"
FILES_STR = 'abcdefgh'
RANKS_STR = '87654321'
UCI_RE = re.compile(r'^[a-h][1-8][a-h][1-8][qrbn]?$')
SAFE_FS_RE = re.compile(r'[\\/*?:"<>|]')

# ═══════════════════════════════════════════════════════════════════════════════
#  ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class SortMode(Enum):
    DEFAULT = auto(); NAME_ASC = auto(); NAME_DESC = auto()
    DIFFICULTY_ASC = auto(); DIFFICULTY_DESC = auto()
    RATING_ASC = auto(); RATING_DESC = auto()
    MOVES_ASC = auto(); MOVES_DESC = auto()

class DifficultyTier(Enum):
    BEGINNER = (0.0, 0.2, "Beginner", "#66BB6A")
    EASY = (0.2, 0.4, "Easy", "#AED581")
    MEDIUM = (0.4, 0.6, "Medium", "#FFD54F")
    HARD = (0.6, 0.8, "Hard", "#FF8A65")
    EXPERT = (0.8, 1.01, "Expert", "#EF5350")

    def __init__(self, lo, hi, label, color):
        self.lo = lo; self.hi = hi; self.label = label; self.color = color

    @classmethod
    def from_score(cls, score: float) -> "DifficultyTier":
        for tier in cls:
            if tier.lo <= score < tier.hi:
                return tier
        return cls.EXPERT

    @classmethod
    def from_rating(cls, rating: int) -> "DifficultyTier":
        if rating < 800: return cls.BEGINNER
        if rating < 1200: return cls.EASY
        if rating < 1600: return cls.MEDIUM
        if rating < 2000: return cls.HARD
        return cls.EXPERT

class VideoStyle(Enum):
    CINEMATIC = "Cinematic"
    MINIMAL = "Minimal"
    NEON = "Neon"
    CLASSIC = "Classic"
    DARK = "Dark"

class ExportFormat(Enum):
    MP4 = "mp4"
    GIF = "gif"
    PNG_SEQ = "png_sequence"

# ═══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class Puzzle:
    id: int
    name: str
    fen: str
    moves: Tuple[str, ...]
    desc: str
    difficulty: float
    themes: FrozenSet[str]
    rating: Optional[int]
    move_count: int
    opening: str = ""
    eco: str = ""
    raw_row: Optional[Dict[str, Any]] = field(default=None, repr=False, hash=False)

    @property
    def tier(self) -> DifficultyTier:
        return DifficultyTier.from_score(self.difficulty)

    @property
    def tier_color(self) -> str:
        return self.tier.color

    @property
    def tier_label(self) -> str:
        return self.tier.label

    @property
    def search_text(self) -> str:
        parts = [self.name, self.desc, self.opening, ' '.join(self.themes)]
        return ' '.join(parts).lower()

    @property
    def search_tokens(self) -> Tuple[str, ...]:
        return tuple(re.findall(r'[a-z0-9]+', self.search_text))

    def safe_filename(self) -> str:
        name = SAFE_FS_RE.sub('_', self.name)
        return name[:80] if name else f"puzzle_{self.id}"


@dataclass(frozen=True, slots=True)
class FilterCriteria:
    text_query: str = ""
    difficulty_range: Tuple[float, float] = (0.0, 1.0)
    rating_range: Tuple[int, int] = (0, 3500)
    move_count_range: Tuple[int, int] = (1, 50)
    theme_tags: FrozenSet[str] = frozenset()
    sort_mode: SortMode = SortMode.DEFAULT
    require_rating: bool = False

    @property
    def is_trivial(self) -> bool:
        return (not self.text_query
                and self.difficulty_range == (0.0, 1.0)
                and self.rating_range == (0, 3500)
                and self.move_count_range == (1, 50)
                and not self.theme_tags
                and self.sort_mode == SortMode.DEFAULT
                and not self.require_rating)

    @property
    def active_count(self) -> int:
        c = 0
        if self.text_query: c += 1
        if self.difficulty_range != (0.0, 1.0): c += 1
        if self.rating_range != (0, 3500): c += 1
        if self.move_count_range != (1, 50): c += 1
        if self.theme_tags: c += 1
        if self.sort_mode != SortMode.DEFAULT: c += 1
        if self.require_rating: c += 1
        return c


@dataclass(frozen=True, slots=True)
class MoveInfo:
    from_rc: Tuple[int, int]
    to_rc: Tuple[int, int]
    piece_symbol: str
    piece_obj: chess.Piece
    captured: str
    is_castle: bool
    is_ep: bool
    promo: Optional[int]
    is_check: bool
    is_mate: bool
    notation: str


@dataclass
class VideoConfig:
    """Configuration for video export."""
    width: int = 1920
    height: int = 1080
    fps: int = 30
    board_theme_name: str = "Classic"
    style: VideoStyle = VideoStyle.CINEMATIC
    flip_board: bool = False
    show_title_card: bool = True
    show_solution: bool = True
    title_duration: float = 3.0
    pause_duration: float = 2.0
    move_duration: float = 0.8
    think_duration: float = 3.0
    end_duration: float = 2.5
    show_arrows: bool = True
    show_coordinates: bool = True
    show_move_list: bool = True
    show_difficulty: bool = True
    bg_color: Tuple[int, int, int] = (32, 32, 36)
    accent_color: Tuple[int, int, int] = (45, 125, 154)
    title_text: str = ""
    subtitle_text: str = ""
    channel_name: str = ""
    logo_path: str = ""
    watermark: bool = False
    format: ExportFormat = ExportFormat.MP4
    quality: int = 85  # 0-100

    @property
    def is_portrait(self) -> bool:
        return self.height > self.width

    @property
    def is_shorts(self) -> bool:
        return self.height > self.width and self.height >= 1920

    @property
    def calc_sq_size(self) -> int:
        if self.is_portrait:
            bw = int(self.width * 0.92)
        else:
            bw = int(min(self.width * 0.55, self.height * 0.85))
        return max(8, (bw // 8) * 8 // 8)

    @property
    def board_pixel_size(self) -> int:
        return self.calc_sq_size * 8

    @property
    def board_origin(self) -> Tuple[int, int]:
        bw = self.board_pixel_size
        if self.is_portrait:
            x = (self.width - bw) // 2
            y = int(self.height * 0.22)
        else:
            x = int(self.width * 0.04)
            y = (self.height - bw) // 2
        return x, y

    @property
    def info_rect(self) -> Tuple[int, int, int, int]:
        """x, y, w, h for info panel (landscape only)."""
        bw = self.board_pixel_size
        _, by = self.board_origin
        x = int(self.width * 0.04) + bw + int(self.width * 0.04)
        y = by
        w = self.width - x - int(self.width * 0.04)
        h = bw
        return x, y, w, h


# ═══════════════════════════════════════════════════════════════════════════════
#  TRIE — Prefix search for autocomplete
# ═══════════════════════════════════════════════════════════════════════════════

class TrieNode:
    __slots__ = ('children', 'is_end', 'count')
    def __init__(self):
        self.children: Dict[str, "TrieNode"] = {}
        self.is_end: bool = False
        self.count: int = 0

class Trie:
    def __init__(self) -> None:
        self.root = TrieNode()
        self._size = 0

    def insert(self, word: str) -> None:
        node = self.root
        for ch in word.lower():
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
            node.count += 1
        node.is_end = True
        self._size += 1

    def search(self, prefix: str, limit: int = 20) -> List[str]:
        node = self.root
        for ch in prefix.lower():
            if ch not in node.children:
                return []
            node = node.children[ch]
        results: List[str] = []
        self._collect(node, prefix.lower(), results, limit)
        return results

    def _collect(self, node, prefix, results, limit):
        if len(results) >= limit: return
        if node.is_end: results.append(prefix)
        for ch, child in sorted(node.children.items()):
            self._collect(child, prefix + ch, results, limit)
            if len(results) >= limit: return

    def has_prefix(self, prefix: str) -> bool:
        node = self.root
        for ch in prefix.lower():
            if ch not in node.children: return False
            node = node.children[ch]
        return True

    @property
    def size(self) -> int:
        return self._size

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE INDEX
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleIndex:
    def __init__(self, puzzles: Sequence[Puzzle]) -> None:
        self._puzzles: Dict[int, Puzzle] = {}
        self._tag_index: Dict[str, Set[int]] = defaultdict(set)
        self._token_index: Dict[str, Set[int]] = defaultdict(set)
        self._diff_sorted: List[Tuple[float, int]] = []
        self._rating_sorted: List[Tuple[float, int]] = []
        self._moves_sorted: List[Tuple[int, int]] = []
        self._name_sorted: List[Tuple[str, int]] = []
        self._theme_trie = Trie()
        self._build(puzzles)

    def _build(self, puzzles):
        for p in puzzles:
            pid = p.id
            self._puzzles[pid] = p
            for tag in p.themes:
                self._tag_index[tag].add(pid)
            for token in p.search_tokens:
                self._token_index[token].add(pid)
            self._diff_sorted.append((p.difficulty, pid))
            if p.rating is not None:
                self._rating_sorted.append((float(p.rating), pid))
            self._moves_sorted.append((p.move_count, pid))
            self._name_sorted.append((p.name.lower(), pid))
        self._diff_sorted.sort()
        self._rating_sorted.sort()
        self._moves_sorted.sort()
        self._name_sorted.sort()
        for tag in self._tag_index:
            self._theme_trie.insert(tag)

    def get(self, pid) -> Optional[Puzzle]:
        return self._puzzles.get(pid)

    def __len__(self): return len(self._puzzles)
    def __contains__(self, pid): return pid in self._puzzles

    @property
    def all_ids(self) -> Set[int]:
        return set(self._puzzles.keys())

    @property
    def all_themes(self) -> List[str]:
        return sorted(self._tag_index.keys())

    @property
    def theme_trie(self) -> Trie:
        return self._theme_trie

    def ids_in_difficulty_range(self, lo, hi) -> Set[int]:
        arr = self._diff_sorted
        left = bisect_left(arr, (lo, -1))
        right = bisect_right(arr, (hi, float('inf')))
        return {arr[i][1] for i in range(left, right)}

    def ids_in_rating_range(self, lo, hi) -> Set[int]:
        arr = self._rating_sorted
        left = bisect_left(arr, (float(lo), -1))
        right = bisect_right(arr, (float(hi), float('inf')))
        return {arr[i][1] for i in range(left, right)}

    def ids_in_move_range(self, lo, hi) -> Set[int]:
        arr = self._moves_sorted
        left = bisect_left(arr, (lo, -1))
        right = bisect_right(arr, (hi, 0x7FFFFFFF))
        return {arr[i][1] for i in range(left, right)}

    def ids_with_tag(self, tag) -> Set[int]:
        return self._tag_index.get(tag.lower(), set())

    def ids_with_any_tag(self, tags) -> Set[int]:
        result: Set[int] = set()
        for tag in tags:
            result |= self.ids_with_tag(tag)
        return result

    def ids_matching_text(self, query) -> Set[int]:
        tokens = re.findall(r'[a-z0-9]+', query.lower())
        if not tokens: return self.all_ids
        token_sets = []
        for t in tokens:
            s = self._token_index.get(t, set())
            if not s: return set()
            token_sets.append(s)
        token_sets.sort(key=len)
        result = token_sets[0].copy()
        for s in token_sets[1:]:
            result &= s
            if not result: return set()
        return result

    def filter(self, criteria: FilterCriteria) -> List[int]:
        if criteria.is_trivial:
            return sorted(self._puzzles.keys())
        candidates: List[Set[int]] = []
        if criteria.text_query:
            candidates.append(self.ids_matching_text(criteria.text_query))
        if criteria.difficulty_range != (0.0, 1.0):
            candidates.append(self.ids_in_difficulty_range(*criteria.difficulty_range))
        if criteria.rating_range != (0, 3500) or criteria.require_rating:
            lo, hi = criteria.rating_range
            rated = self.ids_in_rating_range(lo, hi)
            if criteria.require_rating:
                rated &= {pid for pid, p in self._puzzles.items() if p.rating is not None}
            candidates.append(rated)
        if criteria.move_count_range != (1, 50):
            candidates.append(self.ids_in_move_range(*criteria.move_count_range))
        if criteria.theme_tags:
            candidates.append(self.ids_with_any_tag(criteria.theme_tags))
        if not candidates:
            result = self.all_ids
        else:
            candidates.sort(key=len)
            result = candidates[0]
            for s in candidates[1:]:
                result = result & s
                if not result: return []
        return self._sort(result, criteria.sort_mode)

    def _sort(self, ids, mode):
        if mode == SortMode.DEFAULT: return sorted(ids)
        key_fn = {
            SortMode.NAME_ASC: lambda pid: self._puzzles[pid].name.lower(),
            SortMode.NAME_DESC: lambda pid: self._puzzles[pid].name.lower(),
            SortMode.DIFFICULTY_ASC: lambda pid: self._puzzles[pid].difficulty,
            SortMode.DIFFICULTY_DESC: lambda pid: self._puzzles[pid].difficulty,
            SortMode.RATING_ASC: lambda pid: self._puzzles[pid].rating or 0,
            SortMode.RATING_DESC: lambda pid: self._puzzles[pid].rating or 0,
            SortMode.MOVES_ASC: lambda pid: self._puzzles[pid].move_count,
            SortMode.MOVES_DESC: lambda pid: self._puzzles[pid].move_count,
        }.get(mode, lambda pid: pid)
        reverse = mode.value % 2 == 0
        return sorted(ids, key=key_fn, reverse=reverse)

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE COLLECTION
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleCollection:
    def __init__(self):
        self._puzzles: List[Puzzle] = []
        self._index: Optional[PuzzleIndex] = None
        self._next_id: int = 0

    @property
    def index(self): return self._index
    @property
    def puzzles(self): return self._puzzles
    @property
    def count(self): return len(self._puzzles)

    def add(self, puzzle: Puzzle):
        self._puzzles.append(puzzle)
        self._next_id = max(self._next_id, puzzle.id + 1)

    def add_many(self, puzzles):
        for p in puzzles:
            self._puzzles.append(p)
            self._next_id = max(self._next_id, p.id + 1)

    def build_index(self):
        self._index = PuzzleIndex(self._puzzles)
        log(f"Index built: {len(self._puzzles)} puzzles, {len(self._index.all_themes)} themes")

    def filter(self, criteria: FilterCriteria) -> List[int]:
        if self._index is None: self.build_index()
        return self._index.filter(criteria)

    def get(self, pid) -> Optional[Puzzle]:
        if self._index: return self._index.get(pid)
        for p in self._puzzles:
            if p.id == pid: return p
        return None

    def clear(self):
        self._puzzles.clear()
        self._index = None
        self._next_id = 0

    def next_id(self) -> int:
        nid = self._next_id; self._next_id += 1; return nid

    def remove(self, pid: int):
        self._puzzles = [p for p in self._puzzles if p.id != pid]
        self._index = None  # Rebuild needed

    def save_json(self, path: str):
        data = []
        for p in self._puzzles:
            d = {
                'id': p.id, 'name': p.name, 'fen': p.fen,
                'moves': list(p.moves), 'desc': p.desc,
                'difficulty': p.difficulty, 'themes': list(p.themes),
                'rating': p.rating, 'move_count': p.move_count,
                'opening': p.opening, 'eco': p.eco,
            }
            data.append(d)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log(f"Saved {len(data)} puzzles to {path}")

    def load_json(self, path: str) -> int:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        count = 0
        for d in data:
            p = Puzzle(
                id=d.get('id', self.next_id()),
                name=d.get('name', ''),
                fen=d['fen'],
                moves=tuple(d['moves']),
                desc=d.get('desc', ''),
                difficulty=d.get('difficulty', 0.5),
                themes=frozenset(d.get('themes', [])),
                rating=d.get('rating'),
                move_count=d.get('move_count', len(d['moves'])),
                opening=d.get('opening', ''),
                eco=d.get('eco', ''),
            )
            self.add(p)
            count += 1
        log(f"Loaded {count} puzzles from {path}")
        return count

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD THEME
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class BoardTheme:
    name: str
    light_sq: Tuple[int, int, int]
    dark_sq: Tuple[int, int, int]
    border: Tuple[int, int, int] = (180, 180, 180)
    highlight: Tuple[int, int, int, int] = (45, 125, 154, 70)
    last_move: Tuple[int, int, int, int] = (45, 125, 154, 50)
    arrow: Tuple[int, int, int, int] = (45, 125, 154, 180)
    bg: Tuple[int, int, int] = (250, 250, 250)
    coord: Tuple[int, int, int] = (160, 160, 160)

    def qcolor(self, attr: str) -> QColor:
        val = getattr(self, attr)
        return QColor(*val)

THEMES: Dict[str, BoardTheme] = {
    "Minimal": BoardTheme("Minimal", (240, 240, 240), (213, 213, 213)),
    "Classic": BoardTheme("Classic", (240, 217, 181), (181, 136, 99),
                          border=(48, 26, 7), highlight=(255, 255, 0, 100),
                          last_move=(155, 199, 0, 100), arrow=(220, 50, 47, 200),
                          bg=(32, 32, 36), coord=(180, 160, 130)),
    "Blue": BoardTheme("Blue", (208, 224, 243), (116, 150, 194), border=(40, 50, 70)),
    "Green": BoardTheme("Green", (238, 238, 210), (118, 150, 86), border=(50, 60, 40)),
    "Brown": BoardTheme("Brown", (222, 197, 165), (170, 120, 70), border=(60, 35, 15)),
    "Ice": BoardTheme("Ice", (230, 240, 250), (160, 190, 220), border=(50, 60, 80)),
    "Neon": BoardTheme("Neon", (20, 20, 30), (10, 10, 20),
                       border=(0, 255, 136), highlight=(0, 255, 136, 80),
                       last_move=(0, 200, 255, 80), arrow=(0, 255, 136, 200),
                       bg=(10, 10, 18), coord=(0, 255, 136)),
    "Dark": BoardTheme("Dark", (54, 54, 54), (38, 38, 38),
                       border=(30, 30, 30), highlight=(100, 180, 200, 80),
                       last_move=(80, 140, 160, 60), arrow=(100, 180, 200, 200),
                       bg=(24, 24, 28), coord=(100, 100, 100)),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT PRESETS
# ═══════════════════════════════════════════════════════════════════════════════

EXPORT_PRESETS = {
    "YouTube 1080p": VideoConfig(width=1920, height=1080, fps=30),
    "YouTube 4K": VideoConfig(width=3840, height=2160, fps=30),
    "YouTube Shorts": VideoConfig(width=1080, height=1920, fps=30,
                                  think_duration=2.5, move_duration=0.7),
    "TikTok": VideoConfig(width=1080, height=1920, fps=30,
                           think_duration=2.5, move_duration=0.7),
    "Instagram Reel": VideoConfig(width=1080, height=1920, fps=30),
    "Instagram Square": VideoConfig(width=1080, height=1080, fps=30),
    "Board Only (544×544)": VideoConfig(width=544, height=544, fps=30,
                                        show_title_card=False, show_move_list=False,
                                        show_difficulty=False),
    "Custom": VideoConfig(),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  STYLESHEET
# ═══════════════════════════════════════════════════════════════════════════════

class Palette:
    BG = "#FAFAFA"; BG2 = "#F5F5F5"; BG3 = "#EEEEEE"; CARD = "#FFFFFF"
    TEXT = "#1A1A1A"; TEXT2 = "#757575"; TEXT3 = "#BDBDBD"; INV = "#FFFFFF"
    ACCENT = "#2D7D9A"; ACCENT_H = "#23697F"; ACCENT_L = "#E0F0F5"
    BORDER = "#E0E0E0"; BORDER_L = "#F0F0F0"
    ERROR = "#E53935"; SUCCESS = "#4CAF50"; WARN = "#FF9800"

    @classmethod
    def apply(cls, app):
        p = QPalette()
        p.setColor(QPalette.Window, QColor(cls.BG))
        p.setColor(QPalette.WindowText, QColor(cls.TEXT))
        p.setColor(QPalette.Base, QColor(cls.CARD))
        p.setColor(QPalette.AlternateBase, QColor(cls.BG2))
        p.setColor(QPalette.Text, QColor(cls.TEXT))
        p.setColor(QPalette.Button, QColor(cls.BG2))
        p.setColor(QPalette.ButtonText, QColor(cls.TEXT))
        p.setColor(QPalette.Highlight, QColor(cls.ACCENT))
        p.setColor(QPalette.HighlightedText, QColor(cls.INV))
        p.setColor(QPalette.Link, QColor(cls.ACCENT))
        app.setPalette(p)

STYLESHEET = """
QMainWindow, QWidget { background:#FAFAFA; color:#1A1A1A;
    font-family:"Inter","Segoe UI","SF Pro",sans-serif; font-size:13px; }
QLabel { color:#1A1A1A; background:transparent; }
QPushButton { background:#FFF; border:1px solid #E0E0E0; border-radius:6px;
    padding:7px 16px; color:#1A1A1A; font-weight:500; min-height:18px; }
QPushButton:hover { background:#F5F5F5; border-color:#BDBDBD; }
QPushButton:pressed { background:#EEE; }
QPushButton[accent="true"] { background:#2D7D9A; color:#FFF; border:1px solid #23697F; }
QPushButton[accent="true"]:hover { background:#23697F; }
QPushButton[danger="true"] { background:#E53935; color:#FFF; border:1px solid #C62828; }
QPushButton[danger="true"]:hover { background:#C62828; }
QPushButton[outline="true"] { background:transparent; border:1px solid #2D7D9A; color:#2D7D9A; }
QPushButton[outline="true"]:hover { background:#E0F0F5; }
QLineEdit { background:#FFF; border:1px solid #E0E0E0; border-radius:6px;
    padding:7px 10px; selection-background-color:#2D7D9A; selection-color:#FFF; }
QLineEdit:focus { border-color:#2D7D9A; }
QComboBox { background:#FFF; border:1px solid #E0E0E0; border-radius:6px;
    padding:6px 10px; min-height:20px; }
QComboBox::drop-down { border:none; width:24px; }
QComboBox::down-arrow { image:none; border-left:4px solid transparent;
    border-right:4px solid transparent; border-top:5px solid #757575; }
QSpinBox { background:#FFF; border:1px solid #E0E0E0; border-radius:6px; padding:5px 8px; }
QSlider::groove:horizontal { height:4px; background:#E0E0E0; border-radius:2px; }
QSlider::handle:horizontal { background:#2D7D9A; width:14px; height:14px;
    margin:-5px 0; border-radius:7px; }
QSlider::sub-page:horizontal { background:#2D7D9A; border-radius:2px; }
QListWidget { background:#FFF; border:1px solid #E0E0E0; border-radius:6px;
    outline:none; padding:2px; }
QListWidget::item { padding:8px 10px; border-bottom:1px solid #F5F5F5; border-radius:3px; }
QListWidget::item:selected { background:#E0F0F5; color:#1A1A1A; }
QListWidget::item:hover { background:#F5F5F5; }
QTextEdit { background:#FFF; border:1px solid #E0E0E0; border-radius:6px; padding:6px; }
QTabWidget::pane { border:1px solid #E0E0E0; border-radius:6px; background:#FFF; top:-1px; }
QTabBar::tab { background:#F5F5F5; border:1px solid #E0E0E0; border-bottom:none;
    border-top-left-radius:6px; border-top-right-radius:6px;
    padding:8px 18px; margin-right:2px; color:#757575; font-weight:500; }
QTabBar::tab:selected { background:#FFF; color:#2D7D9A; border-bottom:2px solid #2D7D9A; }
QProgressBar { border:1px solid #E0E0E0; border-radius:4px; text-align:center;
    background:#F5F5F5; height:20px; color:#757575; font-size:11px; }
QProgressBar::chunk { background:#2D7D9A; border-radius:3px; }
QCheckBox { spacing:8px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #BDBDBD;
    border-radius:4px; background:#FFF; }
QCheckBox::indicator:checked { background:#2D7D9A; border-color:#2D7D9A; }
QGroupBox { border:1px solid #E0E0E0; border-radius:6px; margin-top:14px;
    padding-top:18px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; color:#2D7D9A; }
QScrollArea { border:none; background:transparent; }
QStatusBar { background:#FFF; border-top:1px solid #E0E0E0; color:#757575;
    font-size:12px; padding:4px 8px; }
QToolTip { background:#1A1A1A; color:#FFF; border:none; border-radius:4px;
    padding:6px 10px; font-size:12px; }
QSplitter::handle { background:#E0E0E0; width:1px; }
QToolBar { background:#FFF; border-bottom:1px solid #E0E0E0; spacing:6px; padding:4px; }
QToolBar QToolButton { background:transparent; border:1px solid transparent;
    border-radius:4px; padding:5px 8px; }
QToolBar QToolButton:hover { background:#F5F5F5; border-color:#E0E0E0; }
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  CHESS ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class ChessEngine:
    def __init__(self):
        self.board = chess.Board()
        self.game_over = False
        self.result = ""
        self.last_move = None
        self.initial_fen = None
        self.move_history: List[MoveInfo] = []
        self.san_history: List[str] = []

    def reset(self):
        self.board.reset(); self.game_over = False
        self.result = ""; self.last_move = None
        self.initial_fen = None
        self.move_history.clear(); self.san_history.clear()

    def reset_to_initial(self):
        if self.initial_fen:
            self.load_fen(self.initial_fen)
        else:
            self.reset()

    @staticmethod
    def sq_to_rc(sq) -> Tuple[int, int]:
        return 7 - chess.square_rank(sq), chess.square_file(sq)

    @staticmethod
    def rc_to_sq(r, c) -> int:
        return chess.square(c, 7 - r)

    @property
    def turn(self) -> str:
        return 'w' if self.board.turn == chess.WHITE else 'b'

    @property
    def turn_name(self) -> str:
        return "White" if self.board.turn == chess.WHITE else "Black"

    def check_squares(self) -> List[Tuple[int, int]]:
        if self.board.is_check():
            return [self.sq_to_rc(self.board.king(self.board.turn))]
        return []

    def legal_targets(self, r, c) -> List[Tuple[int, int]]:
        sq = self.rc_to_sq(r, c)
        return [self.sq_to_rc(m.to_square) for m in self.board.legal_moves
                if m.from_square == sq]

    def is_promotion(self, fr, fc, tr, tc) -> bool:
        from_sq = self.rc_to_sq(fr, fc)
        piece = self.board.piece_at(from_sq)
        if piece and piece.piece_type == chess.PAWN:
            if (piece.color == chess.WHITE and tr == 0) or \
               (piece.color == chess.BLACK and tr == 7):
                return True
        return False

    def make_move(self, fr, fc, tr, tc, promo=None) -> Optional[MoveInfo]:
        from_sq = self.rc_to_sq(fr, fc)
        to_sq = self.rc_to_sq(tr, tc)
        piece = self.board.piece_at(from_sq)
        if not piece: return None
        promotion = None
        if piece.piece_type == chess.PAWN:
            if (piece.color == chess.WHITE and tr == 0) or \
               (piece.color == chess.BLACK and tr == 7):
                promotion = promo if promo else chess.QUEEN
        move = chess.Move(from_sq, to_sq, promotion=promotion)
        if move not in self.board.legal_moves: return None
        is_castle = self.board.is_castling(move)
        is_ep = self.board.is_en_passant(move)
        if is_ep:
            ep_sq = chess.square(chess.square_file(to_sq), chess.square_rank(from_sq))
            cap = self.board.piece_at(ep_sq)
        else:
            cap = self.board.piece_at(to_sq)
        captured = cap.symbol() if cap else '.'
        notation = self.board.san(move)
        piece_obj = chess.Piece(piece.piece_type, piece.color)
        self.board.push(move)
        self.last_move = ((fr, fc), (tr, tc))
        self.game_over = self.board.is_game_over()
        self.result = self.board.result() if self.game_over else ""
        info = MoveInfo(
            from_rc=(fr, fc), to_rc=(tr, tc), piece_symbol=piece.symbol(),
            piece_obj=piece_obj, captured=captured, is_castle=is_castle,
            is_ep=is_ep, promo=promo, is_check=self.board.is_check(),
            is_mate=self.board.is_checkmate(), notation=notation,
        )
        self.move_history.append(info)
        self.san_history.append(notation)
        return info

    def make_move_uci(self, uci_str) -> Optional[MoveInfo]:
        try:
            move = chess.Move.from_uci(uci_str)
        except ValueError:
            return None
        if move in self.board.legal_moves:
            fr, fc = self.sq_to_rc(move.from_square)
            tr, tc = self.sq_to_rc(move.to_square)
            return self.make_move(fr, fc, tr, tc, move.promotion)
        return None

    def undo(self) -> bool:
        if self.board.move_stack:
            self.board.pop()
            self.move_history.pop()
            self.san_history.pop()
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

    def load_fen(self, fen) -> bool:
        try:
            self.board.set_fen(fen)
        except ValueError:
            log(f"Invalid FEN: {fen}", "ERROR"); return False
        self.game_over = self.board.is_game_over()
        self.result = self.board.result() if self.game_over else ""
        self.last_move = None; self.initial_fen = fen
        self.move_history.clear(); self.san_history.clear()
        return True

    def san_move_list(self) -> str:
        """Generate PGN-like move list string."""
        if not self.san_history:
            return ""
        lines = []
        temp_board = chess.Board()
        if self.initial_fen:
            temp_board.set_fen(self.initial_fen)
        for i, san in enumerate(self.san_history):
            if temp_board.turn == chess.WHITE:
                lines.append(f"{temp_board.fullmove_number}. {san}")
            else:
                lines.append(san)
            try:
                move = temp_board.parse_san(san)
                temp_board.push(move)
            except Exception:
                break
        return " ".join(lines)

# ═══════════════════════════════════════════════════════════════════════════════
#  SOUND MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class SoundManager:
    """Generates and plays procedural chess sound effects."""

    def __init__(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="chess_sfx_")
        self._sounds: Dict[str, QSoundEffect] = {}
        self._enabled = True
        self._volume = 0.7
        self._generate()
        self._load()

    @staticmethod
    def _to_wav(path: str, samples: np.ndarray, sr: int = 44100) -> None:
        int_data = np.clip(samples, -32768, 32767).astype(np.int16)
        with wave.open(path, 'w') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(int_data.tobytes())

    @staticmethod
    def _tone(freq: float, dur: float, vol: float = 0.4,
              sr: int = 44100) -> np.ndarray:
        t = np.arange(int(sr * dur), dtype=np.float64)
        return 32767.0 * vol * np.sin(2.0 * np.pi * freq * t / sr)

    @staticmethod
    def _envelope(samples: np.ndarray, attack: float = 0.005,
                  release: float = 0.03, sr: int = 44100) -> np.ndarray:
        out = samples.copy(); n = len(out)
        ai = min(int(sr * attack), n)
        ri = min(int(sr * release), n)
        if ai > 1: out[:ai] *= np.linspace(0, 1, ai)
        if ri > 1: out[-ri:] *= np.linspace(1, 0, ri)
        return out

    @staticmethod
    def _mix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Add two tone arrays of different lengths, zero-padding the shorter one."""
        if len(a) == len(b):
            return a + b
        if len(a) < len(b):
            a = np.pad(a, (0, len(b) - len(a)))
        else:
            b = np.pad(b, (0, len(a) - len(b)))
        return a + b

    def _generate(self) -> None:
        sr = 44100; d = self._tmpdir
        self._to_wav(os.path.join(d, "move.wav"),
                     self._envelope(self._tone(800, 0.06)))
        self._to_wav(os.path.join(d, "capture.wav"),
                     self._envelope(self._mix(
                         self._tone(300, 0.10, 0.5),
                         self._tone(600, 0.08, 0.3))))
        self._to_wav(os.path.join(d, "check.wav"),
                     self._envelope(self._mix(
                         self._tone(1000, 0.12, 0.5),
                         self._tone(1250, 0.10, 0.3))))
        self._to_wav(os.path.join(d, "checkmate.wav"),
                     self._envelope(np.concatenate([
                         self._tone(800, 0.15, 0.5),
                         self._tone(600, 0.15, 0.5),
                         self._tone(400, 0.25, 0.5)]), 0.01, 0.08))
        self._to_wav(os.path.join(d, "castle.wav"),
                     self._envelope(self._mix(
                         self._tone(400, 0.15) * 0.4,
                         self._tone(800, 0.15, 0.3))))
        self._to_wav(os.path.join(d, "error.wav"),
                     self._envelope(self._tone(200, 0.10, 0.4)))
        self._to_wav(os.path.join(d, "promote.wav"),
                     self._envelope(np.concatenate([
                         self._tone(400, 0.10, 0.4),
                         self._tone(600, 0.10, 0.4),
                         self._tone(800, 0.12, 0.4)]), 0.01, 0.05))
        self._to_wav(os.path.join(d, "start.wav"),
                     self._envelope(np.concatenate([
                         self._tone(523, 0.12, 0.4),
                         np.zeros(int(sr * 0.03)),
                         self._tone(659, 0.18, 0.4)])))

    def _load(self) -> None:
        for name in ("move", "capture", "check", "checkmate",
                     "castle", "error", "promote", "start"):
            fx = QSoundEffect()
            fx.setSource(QUrl.fromLocalFile(
                os.path.join(self._tmpdir, f"{name}.wav")))
            fx.setVolume(self._volume)
            self._sounds[name] = fx

    def set_volume(self, vol: float) -> None:
        self._volume = max(0.0, min(1.0, vol))
        for s in self._sounds.values():
            s.setVolume(self._volume)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def play(self, name: str) -> None:
        if not self._enabled:
            return
        s = self._sounds.get(name)
        if s:
            s.stop(); s.play()

    def cleanup(self) -> None:
        for s in self._sounds.values():
            s.stop()
        self._sounds.clear()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD RENDERER
# ═══════════════════════════════════════════════════════════════════════════════

class BoardRenderer:
    _thread_local = threading.local()

    @staticmethod
    def _assets(sz):
        isz = int(sz * 100)
        if getattr(BoardRenderer._thread_local, 'cache_sz', -1) == isz:
            return BoardRenderer._thread_local.assets
        font_piece = QFont("Segoe UI Emoji", sz * 0.9)
        font_piece.setStyleStrategy(QFont.PreferAntialias)
        font_coord = QFont("Sans", max(7, int(sz * 0.13)), QFont.Bold)
        assets = (font_piece, font_coord)
        BoardRenderer._thread_local.cache_sz = isz
        BoardRenderer._thread_local.assets = assets
        return assets

    @staticmethod
    def render(board, last_move=None, selected=None, legal_targets=None,
               check_squares=None, anim_state=None, sq_size=SQ_SIZE,
               theme=THEMES["Minimal"], flipped=False, text_overlay="") -> QImage:
        sz = sq_size
        img = QImage(sz * 8, sz * 8, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        font_piece, font_coord = BoardRenderer._assets(sz)
        check_set = set(check_squares or [])
        skip_sq: Set[Tuple[int, int]] = set()
        if anim_state:
            skip_sq.add(anim_state['from']); skip_sq.add(anim_state['to'])

        def src(r, c):
            return (7 - r, 7 - c) if flipped else (r, c)

        for sq in chess.SQUARES:
            r, c = 7 - chess.square_rank(sq), chess.square_file(sq)
            sr, sc = src(r, c); x, y = sc * sz, sr * sz
            is_light = (r + c) % 2 == 0
            p.fillRect(x, y, sz, sz, theme.qcolor('light_sq' if is_light else 'dark_sq'))
            if last_move and (r, c) in last_move:
                p.fillRect(x, y, sz, sz, theme.qcolor('last_move'))
            if selected and (r, c) == selected:
                p.fillRect(x, y, sz, sz, theme.qcolor('highlight'))
            if (r, c) in check_set:
                grad = QRadialGradient(x + sz / 2, y + sz / 2, sz * 0.7)
                grad.setColorAt(0, QColor(255, 30, 30, 180))
                grad.setColorAt(1, QColor(255, 0, 0, 0))
                p.setBrush(QBrush(grad)); p.setPen(Qt.NoPen)
                p.drawRect(x, y, sz, sz)
            if legal_targets and (r, c) in legal_targets:
                cx, cy = x + sz // 2, y + sz // 2
                if board.piece_at(sq):
                    p.setPen(QPen(QColor(0, 0, 0, 50), max(3, sz // 14)))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(cx - sz * 5 // 12, cy - sz * 5 // 12,
                                  sz * 10 // 12, sz * 10 // 12)
                else:
                    p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 60))
                    p.drawEllipse(cx - sz // 6, cy - sz // 6, sz // 3, sz // 3)

        if last_move:
            (fr, fc), (tr, tc) = last_move
            sfr, sfc = src(fr, fc); str_, stc = src(tr, tc)
            BoardRenderer._draw_arrow(p, sfc * sz + sz // 2, sfr * sz + sz // 2,
                                      stc * sz + sz // 2, str_ * sz + sz // 2,
                                      theme.qcolor('arrow'), sz)

        for sq in chess.SQUARES:
            r, c = 7 - chess.square_rank(sq), chess.square_file(sq)
            if (r, c) in skip_sq: continue
            piece = board.piece_at(sq)
            if piece:
                sr, sc = src(r, c)
                BoardRenderer._draw_piece(p, piece, sr, sc, sz, font_piece)

        if anim_state and anim_state.get('captured', '.') != '.':
            tr, tc_ = anim_state['to']; sr, sc = src(tr, tc_)
            sym = anim_state['captured']; is_w = sym.isupper()
            pt_map = {'K': chess.KING, 'Q': chess.QUEEN, 'R': chess.ROOK,
                      'B': chess.BISHOP, 'N': chess.KNIGHT, 'P': chess.PAWN}
            pt = pt_map.get(sym.upper())
            if pt:
                cap = chess.Piece(pt, chess.WHITE if is_w else chess.BLACK)
                fade = max(0, int(200 * (1.0 - anim_state['progress'])))
                p.setOpacity(fade / 255.0)
                BoardRenderer._draw_piece(p, cap, sr, sc, sz, font_piece)
                p.setOpacity(1.0)

        if anim_state and anim_state.get('piece_obj'):
            fr, fc_ = anim_state['from']; tr, tc_ = anim_state['to']
            t = anim_state['progress']; obj = anim_state['piece_obj']
            ir = fr + (tr - fr) * t; ic = fc_ + (tc_ - fc_) * t
            if flipped: scr_ir_f = 7 - ir; scr_ic_f = 7 - ic
            else: scr_ir_f = ir; scr_ic_f = ic
            lift = 4.0 * t * (1.0 - t) * 0.15
            scale = 1.0 + 4.0 * t * (1.0 - t) * 0.08
            shadow_alpha = 30 + int(70 * max(0, lift / 0.15))
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, shadow_alpha))
            sy = scr_ir_f * sz + sz * 0.82
            p.drawEllipse(QRectF(scr_ic_f * sz + (sz * scale - sz * 0.65) / 2,
                                 sy, sz * 0.65, sz * 0.12))
            y_lift = scr_ir_f * sz - (sz * lift)
            BoardRenderer._draw_piece_at(p, obj, y_lift / sz, scr_ic_f, sz,
                                         sz * scale, sz * scale, font_piece)

        p.setFont(font_coord)
        cm = max(3, int(sz * 0.04)); csz = max(12, sz // 5)
        for ci in range(8):
            fc = FILES_STR[7 - ci] if flipped else FILES_STR[ci]
            is_light = (7 + ci) % 2 == 0
            p.setPen(theme.qcolor('dark_sq' if is_light else 'light_sq'))
            p.drawText(QRect(ci * sz + sz - csz - cm, 7 * sz + cm, csz, csz),
                       Qt.AlignCenter, fc)
        for ri in range(8):
            rc = RANKS_STR[7 - ri] if flipped else RANKS_STR[ri]
            is_light = ri % 2 == 0
            p.setPen(theme.qcolor('dark_sq' if is_light else 'light_sq'))
            p.drawText(QRect(cm, ri * sz + cm, csz, csz), Qt.AlignCenter, rc)

        if text_overlay:
            p.fillRect(0, sz * 4 - 28, sz * 8, 56, QColor(0, 0, 0, 160))
            p.setPen(Qt.white)
            p.setFont(QFont("Sans", max(12, sz // 4), QFont.Bold))
            p.drawText(QRect(0, sz * 4 - 28, sz * 8, 56), Qt.AlignCenter, text_overlay)
        p.end()
        return img

    @staticmethod
    def render_full_frame(board, config: VideoConfig, last_move=None,
                          move_list_text: str = "", puzzle_title: str = "",
                          difficulty_label: str = "", difficulty_color: str = "#FFD54F",
                          turn_text: str = "", phase_text: str = "",
                          theme_name: str = "Classic") -> QImage:
        """Render a complete video frame with board + info panel."""
        theme = THEMES.get(theme_name, THEMES["Classic"])
        w, h = config.width, config.height
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        bg = QColor(*config.bg_color)
        img.fill(bg)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        sq = config.calc_sq_size
        bx, by = config.board_origin
        bw = config.board_pixel_size

        # Board shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 30))
        p.drawRoundedRect(bx + 4, by + 4, bw, bw, 4, 4)

        # Render board
        board_img = BoardRenderer.render(board, last_move=last_move,
                                         sq_size=sq, theme=theme,
                                         flipped=config.flip_board)
        scaled = board_img.scaled(bw, bw, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawImage(bx, by, scaled)

        # Board border
        p.setPen(QPen(QColor(*theme.border), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(bx - 1, by - 1, bw + 2, bw + 2)

        accent = QColor(*config.accent_color)

        if config.is_portrait:
            # Portrait: info above and below board
            # Title above board
            if puzzle_title:
                p.setPen(Qt.white)
                title_font = QFont("Sans", max(14, w // 28), QFont.Bold)
                p.setFont(title_font)
                fm = QFontMetrics(title_font)
                max_w = w - 40
                title = fm.elidedText(puzzle_title, Qt.ElideRight, max_w)
                ty = by - max(50, h // 18)
                p.drawText(QRect(20, ty, w - 40, max(40, h // 20)),
                           Qt.AlignCenter, title)

            # Difficulty badge above board
            if difficulty_label and config.show_difficulty:
                badge_font = QFont("Sans", max(10, w // 45), QFont.Bold)
                p.setFont(badge_font)
                p.setPen(Qt.white)
                dc = QColor(difficulty_color)
                badge_w = max(80, w // 6)
                badge_h = max(22, w // 35)
                badge_x = (w - badge_w) // 2
                badge_y = by - max(25, h // 30)
                p.setBrush(dc)
                p.drawRoundedRect(badge_x, badge_y, badge_w, badge_h, badge_h // 2, badge_h // 2)
                p.drawText(QRect(badge_x, badge_y, badge_w, badge_h),
                           Qt.AlignCenter, difficulty_label)

            # Move list below board
            if move_list_text and config.show_move_list:
                ml_font = QFont("Courier", max(11, w // 40), QFont.Bold)
                p.setFont(ml_font)
                p.setPen(QColor(200, 200, 200))
                ml_y = by + bw + max(12, h // 40)
                p.drawText(QRect(20, ml_y, w - 40, max(30, h // 20)),
                           Qt.AlignCenter, move_list_text)

            # Turn indicator below
            if turn_text:
                turn_font = QFont("Sans", max(10, w // 48))
                p.setFont(turn_font)
                p.setPen(accent)
                turn_y = by + bw + max(45, h // 18)
                p.drawText(QRect(20, turn_y, w - 40, max(24, h // 30)),
                           Qt.AlignCenter, turn_text)

            # Phase text
            if phase_text:
                phase_font = QFont("Sans", max(12, w // 35), QFont.Bold)
                p.setFont(phase_font)
                p.setPen(accent)
                phase_y = by + bw + max(75, h // 12)
                p.drawText(QRect(20, phase_y, w - 40, max(30, h // 22)),
                           Qt.AlignCenter, phase_text)
        else:
            # Landscape: info panel to the right
            ix, iy, iw, ih = config.info_rect

            # Puzzle title
            if puzzle_title:
                title_font = QFont("Sans", max(14, iw // 18), QFont.Bold)
                p.setFont(title_font)
                p.setPen(Qt.white)
                fm = QFontMetrics(title_font)
                title = fm.elidedText(puzzle_title, Qt.ElideRight, iw - 20)
                p.drawText(QRect(ix, iy, iw, max(28, ih // 16)),
                           Qt.AlignLeft | Qt.AlignVCenter, title)

            # Difficulty badge
            y_offset = max(40, ih // 12)
            if difficulty_label and config.show_difficulty:
                badge_font = QFont("Sans", max(10, iw // 28), QFont.Bold)
                p.setFont(badge_font)
                p.setPen(Qt.white)
                dc = QColor(difficulty_color)
                badge_w = max(80, iw // 4)
                badge_h = max(22, iw // 20)
                p.setBrush(dc)
                p.drawRoundedRect(ix, iy + y_offset, badge_w, badge_h,
                                  badge_h // 2, badge_h // 2)
                p.drawText(QRect(ix, iy + y_offset, badge_w, badge_h),
                           Qt.AlignCenter, difficulty_label)
                y_offset += badge_h + 12

            # Divider
            p.setPen(QPen(QColor(80, 80, 80), 1))
            p.drawLine(ix, iy + y_offset, ix + iw, iy + y_offset)
            y_offset += 16

            # Move list
            if move_list_text and config.show_move_list:
                ml_font = QFont("Courier", max(11, iw // 26), QFont.Bold)
                p.setFont(ml_font)
                p.setPen(QColor(200, 200, 200))
                remaining_h = ih - y_offset - 80
                p.drawText(QRect(ix, iy + y_offset, iw, remaining_h),
                           Qt.AlignLeft | Qt.AlignTop, move_list_text)

            # Turn indicator at bottom
            if turn_text:
                turn_font = QFont("Sans", max(11, iw // 24))
                p.setFont(turn_font)
                p.setPen(accent)
                p.drawText(QRect(ix, iy + ih - 60, iw, 24),
                           Qt.AlignLeft, turn_text)

            # Phase overlay
            if phase_text:
                # Semi-transparent phase indicator at top
                phase_font = QFont("Sans", max(16, iw // 14), QFont.Bold)
                p.setFont(phase_font)
                p.setPen(Qt.white)
                pw = max(200, iw)
                ph = max(40, ih // 12)
                px = ix + (iw - pw) // 2
                py = iy + ih // 2 - ph // 2
                p.setBrush(QColor(0, 0, 0, 140))
                p.drawRoundedRect(px, py, pw, ph, 8, 8)
                p.drawText(QRect(px, py, pw, ph), Qt.AlignCenter, phase_text)

        # Watermark
        if config.watermark and config.channel_name:
            wm_font = QFont("Sans", max(9, w // 100))
            p.setFont(wm_font)
            p.setPen(QColor(255, 255, 255, 80))
            p.drawText(QRect(w - 200, h - 24, 190, 20),
                       Qt.AlignRight | Qt.AlignVCenter, config.channel_name)

        p.end()
        return img

    @staticmethod
    def render_title_card(config: VideoConfig, title: str, subtitle: str = "",
                          difficulty: str = "", diff_color: str = "#FFD54F",
                          channel: str = "") -> QImage:
        """Render an animated-style title card frame."""
        w, h = config.width, config.height
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        bg = QColor(*config.bg_color)
        img.fill(bg)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        accent = QColor(*config.accent_color)

        # Decorative chess pattern (subtle)
        p.setPen(Qt.NoPen)
        mini = max(8, min(w, h) // 40)
        for ri in range(h // mini + 1):
            for ci in range(w // mini + 1):
                if (ri + ci) % 2 == 0:
                    p.setBrush(QColor(255, 255, 255, 8))
                    p.drawRect(ci * mini, ri * mini, mini, mini)

        # Center accent line
        lw = min(w, h) // 3
        p.setPen(QPen(accent, 3))
        p.drawLine((w - lw) // 2, h // 2 - min(60, h // 10),
                   (w + lw) // 2, h // 2 - min(60, h // 10))

        # Title
        title_size = max(20, min(w, h) // 18)
        p.setFont(QFont("Sans", title_size, QFont.Bold))
        p.setPen(Qt.white)
        p.drawText(QRect(40, h // 2 - min(50, h // 10), w - 80, title_size * 2),
                   Qt.AlignCenter, title)

        # Subtitle
        if subtitle:
            sub_size = max(12, title_size // 2)
            p.setFont(QFont("Sans", sub_size))
            p.setPen(QColor(200, 200, 200))
            p.drawText(QRect(40, h // 2 + title_size, w - 80, sub_size * 2),
                       Qt.AlignCenter, subtitle)

        # Difficulty badge
        if difficulty:
            badge_size = max(10, title_size // 3)
            p.setFont(QFont("Sans", badge_size, QFont.Bold))
            p.setPen(Qt.white)
            dc = QColor(diff_color)
            bw_ = max(100, w // 5); bh_ = max(28, h // 25)
            bx_ = (w - bw_) // 2
            by_ = h // 2 + title_size + badge_size * 2 + 10
            p.setBrush(dc)
            p.drawRoundedRect(bx_, by_, bw_, bh_, bh_ // 2, bh_ // 2)
            p.drawText(QRect(bx_, by_, bw_, bh_), Qt.AlignCenter, difficulty)

        # Channel name
        if channel:
            p.setFont(QFont("Sans", max(10, title_size // 4)))
            p.setPen(QColor(160, 160, 160))
            p.drawText(QRect(40, h - max(50, h // 12), w - 80, max(24, h // 30)),
                       Qt.AlignCenter, channel)

        # Bottom accent line
        p.setPen(QPen(accent, 3))
        p.drawLine((w - lw) // 2, h // 2 + min(60, h // 10),
                   (w + lw) // 2, h // 2 + min(60, h // 10))

        p.end()
        return img

    @staticmethod
    def render_end_card(config: VideoConfig, result_text: str,
                        move_list: str = "", channel: str = "") -> QImage:
        w, h = config.width, config.height
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        bg = QColor(*config.bg_color)
        img.fill(bg)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        accent = QColor(*config.accent_color)

        # Result text large
        res_size = max(24, min(w, h) // 14)
        p.setFont(QFont("Sans", res_size, QFont.Bold))
        p.setPen(Qt.white)
        p.drawText(QRect(40, h // 3 - res_size, w - 80, res_size * 2),
                   Qt.AlignCenter, result_text)

        # Accent line
        lw = min(w, h) // 4
        p.setPen(QPen(accent, 3))
        p.drawLine((w - lw) // 2, h // 2, (w + lw) // 2, h // 2)

        # Move list small
        if move_list:
            ml_size = max(10, res_size // 3)
            p.setFont(QFont("Courier", ml_size))
            p.setPen(QColor(180, 180, 180))
            p.drawText(QRect(40, h // 2 + 20, w - 80, h // 4),
                       Qt.AlignCenter, move_list)

        # Channel
        if channel:
            p.setFont(QFont("Sans", max(10, res_size // 4)))
            p.setPen(QColor(140, 140, 140))
            p.drawText(QRect(40, h - max(50, h // 10), w - 80, 30),
                       Qt.AlignCenter, channel)

        p.end()
        return img

    @staticmethod
    def _draw_piece(p, piece, row, col, sz, font):
        BoardRenderer._draw_piece_at(p, piece, float(row), float(col), sz, sz, sz, font)

    @staticmethod
    def _draw_piece_at(p, piece, row_f, col_f, sz, w, h, font):
        glyph = PIECE_SYM[(piece.piece_type, piece.color)]
        is_w = piece.color == chess.WHITE
        px = col_f * sz; py = row_f * sz
        rect = QRectF(px + (sz - w) / 2, py + (sz - h) / 2, w, h)
        center = rect.center(); p.setFont(font)
        path = QPainterPath(); path.addText(QPointF(0, 0), font, glyph)
        br = path.boundingRect()
        path.translate(-br.center().x(), -br.center().y())
        if br.width() > 0 and br.height() > 0:
            s = min((w * 0.85) / br.width(), (h * 0.85) / br.height())
            path = QTransform.fromScale(s, s).map(path)
        path.translate(center.x(), center.y())
        shadow = QPainterPath(path); shadow.translate(1.5, 2.0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40 if is_w else 50))
        p.drawPath(shadow)
        olw = max(1.0, sz * (0.022 if is_w else 0.014))
        p.setPen(QPen(QColor(60 if is_w else 20, 60 if is_w else 20,
                             60 if is_w else 20), olw,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QColor(255, 255, 255) if is_w else QColor(50, 50, 50))
        p.drawPath(path)

    @staticmethod
    def _draw_arrow(p, fx, fy, tx, ty, color, sz):
        dx = tx - fx; dy = ty - fy; dist = max(1, math.hypot(dx, dy))
        m = sz * 0.22
        fx2 = fx + dx * m / dist; fy2 = fy + dy * m / dist
        tx2 = tx - dx * m / dist; ty2 = ty - dy * m / dist
        p.setPen(QPen(color, max(2, sz // 20), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(int(fx2), int(fy2), int(tx2), int(ty2))
        angle = math.atan2(dy, dx); a = sz * 0.22
        tri = QPolygonF([
            QPointF(tx2, ty2),
            QPointF(tx2 - a * math.cos(angle - 0.45), ty2 - a * math.sin(angle - 0.45)),
            QPointF(tx2 - a * math.cos(angle + 0.45), ty2 - a * math.sin(angle + 0.45))])
        p.setBrush(color); p.setPen(Qt.NoPen); p.drawPolygon(tri)

    @staticmethod
    def to_numpy(img) -> np.ndarray:
        if img.isNull():
            return np.zeros((1, 1, 3), dtype=np.uint8)
        img2 = img.convertToFormat(QImage.Format_RGB888)
        ptr = img2.constBits()
        if hasattr(ptr, 'setsize'):
            ptr.setsize(img2.sizeInBytes())
        w, h, bpl = img2.width(), img2.height(), img2.bytesPerLine()
        raw = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl)).copy()
        needed = w * 3
        if bpl == needed: return raw.reshape((h, w, 3))
        if bpl > needed: return raw[:, :needed].reshape((h, w, 3))
        out = np.zeros((h, needed), dtype=np.uint8)
        for i in range(h):
            out[i, :min(bpl, needed)] = raw[i, :min(bpl, needed)]
        return out.reshape((h, w, 3))

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE LOADER
# ═══════════════════════════════════════════════════════════════════════════════

class BaseLoader(ABC):
    @abstractmethod
    def can_load(self, path) -> bool: ...
    @abstractmethod
    def load(self, path) -> List[Dict[str, Any]]: ...

class CsvLoader(BaseLoader):
    def can_load(self, path): return path.lower().endswith('.csv')
    def load(self, path):
        rows = []
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                for row in csv.DictReader(f):
                    rows.append(row)
        except Exception as e:
            log(f"CSV error: {e}", "ERROR")
        return rows

class ParquetLoader(BaseLoader):
    def can_load(self, path): return path.lower().endswith(('.parquet', '.pq'))
    def load(self, path):
        if HAS_PANDAS: return pd.read_parquet(path).to_dict('records')
        if HAS_PYARROW: return pq.read_table(path).to_pandas().to_dict('records')
        if HAS_DUCKDB:
            r = duckdb.query(f"SELECT * FROM '{path}'")
            cols = [c[0] for c in r.description]
            return [dict(zip(cols, row)) for row in r.fetchall()]
        log("No Parquet reader available", "ERROR")
        return []

class JsonLoader(BaseLoader):
    def can_load(self, path): return path.lower().endswith(('.json', '.jsonl'))
    def load(self, path):
        if path.lower().endswith('.jsonl'):
            rows = []
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try: rows.append(json.loads(line))
                        except json.JSONDecodeError: pass
            return rows
        else:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else [data]

LOADERS = [CsvLoader(), JsonLoader()]
if HAS_PANDAS or HAS_PYARROW or HAS_DUCKDB:
    LOADERS.append(ParquetLoader())

def normalize_puzzle_row(row: Dict[str, Any], id_counter: int) -> Optional[Puzzle]:
    """Normalize a raw row from any format into a Puzzle object."""
    try:
        fen = row.get('FEN', row.get('fen', row.get('position', '')))
        moves_str = row.get('Moves', row.get('moves', ''))
        if not fen:
            return None
        if isinstance(moves_str, str):
            moves = tuple(moves_str.strip().split())
        elif isinstance(moves_str, (list, tuple)):
            moves = tuple(str(m) for m in moves_str)
        else:
            moves = ()

        themes_str = row.get('Themes', row.get('themes', row.get('tags', '')))
        if isinstance(themes_str, str):
            themes = frozenset(t.strip() for t in themes_str.split() if t.strip())
        elif isinstance(themes_str, (list, tuple, set)):
            themes = frozenset(str(t).strip() for t in themes_str)
        else:
            themes = frozenset()

        rating_raw = row.get('Rating', row.get('rating', row.get('elo', None)))
        rating = int(rating_raw) if rating_raw is not None else None
        diff_raw = row.get('difficulty', None)
        if diff_raw is not None:
            difficulty = float(diff_raw)
        elif rating:
            difficulty = min(1.0, max(0.0, rating / 2500.0))
        else:
            difficulty = 0.5

        name = row.get('Name', row.get('name', row.get('title', f"Puzzle #{id_counter}")))
        desc = row.get('Description', row.get('desc', row.get('description', '')))
        opening = row.get('Opening', row.get('opening', ''))
        eco = row.get('ECO', row.get('eco', ''))

        return Puzzle(
            id=id_counter, name=str(name), fen=str(fen), moves=moves,
            desc=str(desc), difficulty=difficulty, themes=themes,
            rating=rating, move_count=len(moves) // 2 + 1,
            opening=str(opening), eco=str(eco), raw_row=row,
        )
    except Exception as e:
        log(f"Row parse error: {e}", "WARN")
        return None

# ═══════════════════════════════════════════════════════════════════════════════
#  VIDEO EXPORTER — Generates video frames and encodes
# ═══════════════════════════════════════════════════════════════════════════════

class VideoExportWorker(QObject):
    """Worker that generates video frames in a background thread."""
    progress = QSignal(int, int)   # current, total
    finished = QSignal(str)         # output path
    error = QSignal(str)
    frame_ready = QSignal(QImage)   # preview

    def __init__(self, puzzle: Puzzle, config: VideoConfig):
        super().__init__()
        self.puzzle = puzzle
        self.config = config
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self._export()
        except Exception as e:
            self.error.emit(str(e))

    def _export(self):
        cfg = self.config
        puzzle = self.puzzle

        # Build move sequence
        engine = ChessEngine()
        if not engine.load_fen(puzzle.fen):
            self.error.emit("Invalid FEN")
            return

        # Calculate total frames
        title_frames = int(cfg.title_duration * cfg.fps) if cfg.show_title_card else 0
        think_frames = int(cfg.think_duration * cfg.fps)
        move_frames_per = int(cfg.move_duration * cfg.fps)
        pause_frames = int(cfg.pause_duration * cfg.fps)
        end_frames = int(cfg.end_duration * cfg.fps)

        total_move_frames = len(puzzle.moves) * (move_frames_per + pause_frames)
        total_frames = title_frames + think_frames + total_move_frames + end_frames

        frames_list = []
        frame_idx = 0

        # Title card
        for i in range(title_frames):
            if self._cancel: return
            img = BoardRenderer.render_title_card(
                cfg, puzzle.name,
                subtitle=puzzle.desc[:80] if puzzle.desc else "",
                difficulty=puzzle.tier_label,
                diff_color=puzzle.tier_color,
                channel=cfg.channel_name)
            frames_list.append(BoardRenderer.to_numpy(img))
            frame_idx += 1
            if frame_idx % cfg.fps == 0:
                self.progress.emit(frame_idx, total_frames)

        # Think phase
        for i in range(think_frames):
            if self._cancel: return
            phase = "Find the best move!" if i < think_frames // 2 else ""
            ml = engine.san_move_list()
            img = BoardRenderer.render_full_frame(
                engine.board, cfg, last_move=engine.last_move,
                move_list_text=ml, puzzle_title=puzzle.name,
                difficulty_label=puzzle.tier_label,
                difficulty_color=puzzle.tier_color,
                turn_text=f"{engine.turn_name} to move",
                phase_text=phase,
                theme_name=cfg.board_theme_name)
            frames_list.append(BoardRenderer.to_numpy(img))
            frame_idx += 1
            if frame_idx % cfg.fps == 0:
                self.progress.emit(frame_idx, total_frames)

        # Play each move
        for mi, uci in enumerate(puzzle.moves):
            if self._cancel: return
            info = engine.make_move_uci(uci)
            if not info:
                log(f"Invalid move {uci} at index {mi}", "WARN")
                continue

            # Animate move
            for fi in range(move_frames_per):
                if self._cancel: return
                t = fi / max(1, move_frames_per - 1)
                # Smooth easing
                t = t * t * (3 - 2 * t)
                anim = {
                    'from': info.from_rc, 'to': info.to_rc,
                    'piece_obj': info.piece_obj,
                    'captured': info.captured,
                    'progress': t,
                }
                # For animation we need to undo the move, render with anim, then redo
                engine.undo()
                phase = ""
                if info.is_check: phase = "Check!"
                if info.is_mate: phase = "Checkmate!"
                ml = engine.san_move_list()
                board_img = BoardRenderer.render(
                    engine.board, last_move=engine.last_move,
                    anim_state=anim, sq_size=cfg.calc_sq_size,
                    theme=THEMES.get(cfg.board_theme_name, THEMES["Classic"]),
                    flipped=cfg.flip_board)
                engine.make_move_uci(uci)  # redo move

                # Compose full frame
                full = QImage(cfg.width, cfg.height, QImage.Format_ARGB32_Premultiplied)
                full.fill(QColor(*cfg.bg_color))
                painter = QPainter(full)
                painter.setRenderHint(QPainter.Antialiasing)
                bx, by = cfg.board_origin
                bw = cfg.board_pixel_size
                scaled = board_img.scaled(bw, bw, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                painter.drawImage(bx, by, scaled)
                painter.end()

                # Re-render with info
                ml_full = engine.san_move_list()
                # Use render_full_frame but with custom board
                # Simpler: just re-render full frame without animation for pause
                if fi == move_frames_per - 1:
                    # Last frame: full render
                    pass

                frames_list.append(BoardRenderer.to_numpy(full))
                frame_idx += 1

            # Pause after move
            for pi in range(pause_frames):
                if self._cancel: return
                phase = ""
                if info.is_check and not info.is_mate: phase = "Check!"
                if info.is_mate: phase = "Checkmate!"
                ml = engine.san_move_list()
                img = BoardRenderer.render_full_frame(
                    engine.board, cfg, last_move=engine.last_move,
                    move_list_text=ml, puzzle_title=puzzle.name,
                    difficulty_label=puzzle.tier_label,
                    difficulty_color=puzzle.tier_color,
                    turn_text=f"{engine.turn_name} to move" if not engine.game_over else engine.result,
                    phase_text=phase,
                    theme_name=cfg.board_theme_name)
                frames_list.append(BoardRenderer.to_numpy(img))
                frame_idx += 1

        # End card
        for i in range(end_frames):
            if self._cancel: return
            result = "Checkmate!" if engine.board.is_checkmate() else \
                     "Stalemate!" if engine.board.is_stalemate() else \
                     engine.result or "Puzzle Complete"
            img = BoardRenderer.render_end_card(
                cfg, result,
                move_list=engine.san_move_list(),
                channel=cfg.channel_name)
            frames_list.append(BoardRenderer.to_numpy(img))
            frame_idx += 1
            if frame_idx % cfg.fps == 0:
                self.progress.emit(frame_idx, total_frames)

        self.progress.emit(total_frames, total_frames)

        # Write video
        if not frames_list:
            self.error.emit("No frames generated")
            return

        out_dir = os.path.join(DATA_DIR, "exports")
        os.makedirs(out_dir, exist_ok=True)
        safe_name = puzzle.safe_filename()
        out_path = os.path.join(out_dir, f"{safe_name}.mp4")

        if HAS_IMAGEIO:
            try:
                iio.imwrite(out_path, frames_list, fps=cfg.fps,
                            codec='libx264', quality=cfg.quality)
                log(f"Video exported: {out_path}")
                self.finished.emit(out_path)
            except Exception as e:
                # Try without codec specification
                try:
                    iio.imwrite(out_path, frames_list, fps=cfg.fps)
                    self.finished.emit(out_path)
                except Exception as e2:
                    self.error.emit(f"Video write error: {e2}")
        elif HAS_FFMPEG:
            # Fallback: write PNGs and use ffmpeg
            tmp_dir = tempfile.mkdtemp(prefix="chess_frames_")
            for i, frame in enumerate(frames_list):
                from PIL import Image
                Image.fromarray(frame).save(os.path.join(tmp_dir, f"frame_{i:06d}.png"))
            cmd = [
                'ffmpeg', '-y', '-framerate', str(cfg.fps),
                '-i', os.path.join(tmp_dir, 'frame_%06d.png'),
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-crf', str(max(0, 51 - cfg.quality * 51 // 100)),
                out_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            self.finished.emit(out_path)
        else:
            # Save as PNG sequence
            seq_dir = os.path.join(out_dir, f"{safe_name}_frames")
            os.makedirs(seq_dir, exist_ok=True)
            for i, frame in enumerate(frames_list):
                qi = QImage(frame.data, frame.shape[1], frame.shape[0],
                           frame.shape[1] * 3, QImage.Format_RGB888)
                qi.save(os.path.join(seq_dir, f"frame_{i:06d}.png"))
            self.finished.emit(seq_dir)

# ═══════════════════════════════════════════════════════════════════════════════
#  CHESS BOARD WIDGET
# ═══════════════════════════════════════════════════════════════════════════════

class ChessBoardWidget(QWidget):
    """Interactive chess board widget with animation and interaction."""
    move_made = Signal(str)  # UCI string
    move_info = Signal(MoveInfo)
    position_changed = Signal()
    clicked_square = Signal(int, int)  # row, col

    def __init__(self, engine: ChessEngine, sound: SoundManager,
                 parent=None, sq_size=SQ_SIZE):
        super().__init__(parent)
        self.engine = engine
        self.sound = sound
        self.sq_size = sq_size
        self.theme_name = "Classic"
        self.flipped = False
        self._selected: Optional[Tuple[int, int]] = None
        self._legal_targets: List[Tuple[int, int]] = []
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(1000 // ANIM_FPS)
        self._anim_timer.timeout.connect(self._anim_tick)
        self._anim_state: Optional[Dict] = None
        self._anim_info: Optional[MoveInfo] = None
        self._anim_progress = 0.0
        self._anim_speed = ANIM_SPEED_DEFAULT
        self._interactive = True
        self._text_overlay = ""
        self.setFixedSize(sq_size * 8, sq_size * 8)
        self.setCursor(Qt.PointingHandCursor)

    @property
    def theme(self) -> BoardTheme:
        return THEMES.get(self.theme_name, THEMES["Classic"])

    def set_theme(self, name: str):
        self.theme_name = name; self.update()

    def set_flipped(self, flipped: bool):
        self.flipped = flipped; self.update()

    def set_interactive(self, interactive: bool):
        self._interactive = interactive
        self.setCursor(Qt.PointingHandCursor if interactive else Qt.ArrowCursor)

    def set_text_overlay(self, text: str):
        self._text_overlay = text; self.update()

    def refresh(self):
        self._selected = None; self._legal_targets = []
        self.update()

    def _rc_from_pos(self, pos) -> Optional[Tuple[int, int]]:
        c = pos.x() // self.sq_size
        r = pos.y() // self.sq_size
        if self.flipped:
            c = 7 - c; r = 7 - r
        if 0 <= r < 8 and 0 <= c < 8:
            return r, c
        return None

    def mousePressEvent(self, event):
        if not self._interactive or event.button() != Qt.LeftButton:
            return
        rc = self._rc_from_pos(event.position().toPoint())
        if not rc: return
        r, c = rc

        if self._selected:
            sr, sc = self._selected
            if (r, c) in self._legal_targets:
                self._try_move(sr, sc, r, c)
                return
            # Re-select if clicking own piece
            sq = self.engine.rc_to_sq(r, c)
            piece = self.engine.board.piece_at(sq)
            if piece and piece.color == self.engine.board.turn:
                self._selected = (r, c)
                self._legal_targets = self.engine.legal_targets(r, c)
                self.update()
                return
            self._selected = None; self._legal_targets = []
            self.update()
        else:
            sq = self.engine.rc_to_sq(r, c)
            piece = self.engine.board.piece_at(sq)
            if piece and piece.color == self.engine.board.turn:
                self._selected = (r, c)
                self._legal_targets = self.engine.legal_targets(r, c)
                self.clicked_square.emit(r, c)
        self.update()

    def _try_move(self, fr, fc, tr, tc):
        promo = None
        if self.engine.is_promotion(fr, fc, tr, tc):
            promo = self._show_promotion_dialog()
            if promo is None: return

        info = self.engine.make_move(fr, fc, tr, tc, promo)
        if info:
            self._start_animation(info)
            if info.is_mate:
                self.sound.play("checkmate")
            elif info.is_check:
                self.sound.play("check")
            elif info.is_castle:
                self.sound.play("castle")
            elif info.captured != '.':
                self.sound.play("capture")
            elif info.promo:
                self.sound.play("promote")
            else:
                self.sound.play("move")
            self.move_made.emit(
                chess.Move(self.engine.rc_to_sq(fr, fc),
                           self.engine.rc_to_sq(tr, tc),
                           promotion=promo).uci())
            self.move_info.emit(info)
            self.position_changed.emit()
        else:
            self.sound.play("error")
        self._selected = None; self._legal_targets = []

    def _show_promotion_dialog(self) -> Optional[int]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Promote pawn")
        dialog.setModal(True)
        layout = QHBoxLayout(dialog)
        group = QButtonGroup(dialog)
        pieces = [(chess.QUEEN, "♛ Queen"), (chess.ROOK, "♜ Rook"),
                  (chess.BISHOP, "♝ Bishop"), (chess.KNIGHT, "♞ Knight")]
        result = [chess.QUEEN]
        for pt, label in pieces:
            btn = QRadioButton(label)
            if pt == chess.QUEEN: btn.setChecked(True)
            group.addButton(btn, pt)
            layout.addWidget(btn)
        group.idClicked.connect(lambda id_: result.__setitem__(0, id_))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dialog.accept)
        btns.rejected.connect(dialog.reject)
        layout.addWidget(btns)
        if dialog.exec() == QDialog.Accepted:
            return result[0]
        return None

    def _start_animation(self, info: MoveInfo):
        self._anim_info = info
        self._anim_progress = 0.0
        self._anim_state = {
            'from': info.from_rc, 'to': info.to_rc,
            'piece_obj': info.piece_obj,
            'captured': info.captured,
            'progress': 0.0,
        }
        # Undo move for animation (will redo after animation completes)
        self.engine.undo()
        self._anim_timer.start()

    def _anim_tick(self):
        dt = (1000 / ANIM_FPS) / self._anim_speed
        self._anim_progress = min(1.0, self._anim_progress + dt)
        # Smooth easing
        t = self._anim_progress
        t = t * t * (3 - 2 * t)
        if self._anim_state:
            self._anim_state['progress'] = t
        self.update()
        if self._anim_progress >= 1.0:
            self._anim_timer.stop()
            # Redo the move
            if self._anim_info:
                fr, fc = self._anim_info.from_rc
                tr, tc = self._anim_info.to_rc
                self.engine.make_move(fr, fc, tr, tc, self._anim_info.promo)
            self._anim_state = None
            self._anim_info = None
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        img = BoardRenderer.render(
            self.engine.board,
            last_move=self.engine.last_move,
            selected=self._selected,
            legal_targets=self._legal_targets,
            check_squares=self.engine.check_squares(),
            anim_state=self._anim_state,
            sq_size=self.sq_size,
            theme=self.theme,
            flipped=self.flipped,
            text_overlay=self._text_overlay)

        painter.drawImage(0, 0, img)
        painter.end()

    def to_pixmap(self) -> QPixmap:
        img = BoardRenderer.render(
            self.engine.board, last_move=self.engine.last_move,
            sq_size=self.sq_size, theme=self.theme, flipped=self.flipped)
        return QPixmap.fromImage(img)

    def save_screenshot(self, path: str):
        self.to_pixmap().save(path)

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE CREATOR PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleCreatorPanel(QWidget):
    puzzle_saved = Signal(object)  # Puzzle

    def __init__(self, engine: ChessEngine, board: ChessBoardWidget,
                 collection: PuzzleCollection, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.board = board
        self.collection = collection
        self._edit_mode = False
        self._edit_puzzle_id = None
        self._setup_ui()

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("Puzzle Creator")
        title.setStyleSheet("font-size:18px; font-weight:700; color:#2D7D9A;")
        hdr.addWidget(title)
        hdr.addStretch()
        self.mode_label = QLabel("New Puzzle")
        self.mode_label.setStyleSheet("color:#757575; font-style:italic;")
        hdr.addWidget(self.mode_label)
        main.addLayout(hdr)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(14)

        # FEN Input Group
        fen_group = QGroupBox("Position (FEN)")
        fen_lay = QVBoxLayout()
        self.fen_edit = QLineEdit()
        self.fen_edit.setPlaceholderText("Paste FEN string or set up position on the board...")
        self.fen_edit.returnPressed.connect(self._apply_fen)
        fen_lay.addWidget(self.fen_edit)
        fen_btns = QHBoxLayout()
        self.apply_fen_btn = QPushButton("Apply FEN")
        self.apply_fen_btn.setProperty("accent", True)
        self.apply_fen_btn.clicked.connect(self._apply_fen)
        fen_btns.addWidget(self.apply_fen_btn)
        self.start_pos_btn = QPushButton("Starting Position")
        self.start_pos_btn.clicked.connect(self._set_starting_pos)
        fen_btns.addWidget(self.start_pos_btn)
        self.clear_btn = QPushButton("Empty Board")
        self.clear_btn.clicked.connect(self._clear_board)
        fen_btns.addWidget(self.clear_btn)
        self.paste_btn = QPushButton("Paste from Clipboard")
        self.paste_btn.clicked.connect(self._paste_fen)
        fen_btns.addWidget(self.paste_btn)
        fen_lay.addLayout(fen_btns)
        fen_group.setLayout(fen_lay)
        layout.addWidget(fen_group)

        # Current FEN display
        self.current_fen_label = QLabel("")
        self.current_fen_label.setStyleSheet(
            "font-family:monospace; font-size:11px; color:#757575; padding:4px 8px;"
            "background:#F5F5F5; border-radius:4px;")
        self.current_fen_label.setWordWrap(True)
        layout.addWidget(self.current_fen_label)

        # Puzzle Details Group
        details_group = QGroupBox("Puzzle Details")
        details_lay = QFormLayout()
        details_lay.setSpacing(8)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., Mating Net in the Corner")
        details_lay.addRow("Name:", self.name_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(70)
        self.desc_edit.setPlaceholderText("Describe the puzzle idea, what makes it special...")
        details_lay.addRow("Description:", self.desc_edit)

        # Difficulty + Rating row
        dr_row = QHBoxLayout()
        self.difficulty_slider = QSlider(Qt.Horizontal)
        self.difficulty_slider.setRange(0, 100)
        self.difficulty_slider.setValue(50)
        self.difficulty_label = QLabel("Medium")
        self.difficulty_label.setMinimumWidth(70)
        self.difficulty_slider.valueChanged.connect(self._update_difficulty_label)
        dr_row.addWidget(self.difficulty_slider)
        dr_row.addWidget(self.difficulty_label)
        details_lay.addRow("Difficulty:", dr_row)

        self.rating_spin = QSpinBox()
        self.rating_spin.setRange(0, 3500)
        self.rating_spin.setSingleStep(50)
        self.rating_spin.setSpecialValueText("No rating")
        self.rating_spin.setValue(0)
        details_lay.addRow("Rating:", self.rating_spin)

        self.opening_edit = QLineEdit()
        self.opening_edit.setPlaceholderText("e.g., Sicilian Defense, Najdorf")
        details_lay.addRow("Opening:", self.opening_edit)

        self.eco_edit = QLineEdit()
        self.eco_edit.setPlaceholderText("e.g., B90")
        self.eco_edit.setMaximumWidth(100)
        details_lay.addRow("ECO:", self.eco_edit)

        details_group.setLayout(details_lay)
        layout.addWidget(details_group)

        # Themes Group
        themes_group = QGroupBox("Theme Tags")
        themes_lay = QVBoxLayout()
        self.themes_edit = QLineEdit()
        self.themes_edit.setPlaceholderText("Type themes separated by spaces: fork pin skewer mate combo...")
        themes_lay.addWidget(self.themes_edit)
        # Quick-add theme buttons
        quick_themes = QHBoxLayout()
        for tag in ["fork", "pin", "skewer", "mate in 1", "mate in 2",
                     "sacrifice", "combo", "endgame", "tactics", "defense",
                     "discovered attack", "deflection", "decoy", "zugzwang"]:
            btn = QPushButton(tag)
            btn.setProperty("outline", "true")
            btn.setStyleSheet("font-size:11px; padding:3px 8px;")
            btn.clicked.connect(lambda checked, t=tag: self._add_theme(t))
            quick_themes.addWidget(btn)
        themes_lay.addLayout(quick_themes)
        themes_group.setLayout(themes_lay)
        layout.addWidget(themes_group)

        # Move Builder Group
        moves_group = QGroupBox("Solution Moves")
        moves_lay = QVBoxLayout()
        self.moves_label = QLabel("Play the solution moves on the board:")
        self.moves_label.setStyleSheet("color:#757575;")
        moves_lay.addWidget(self.moves_label)

        self.moves_display = QTextEdit()
        self.moves_display.setReadOnly(True)
        self.moves_display.setMaximumHeight(60)
        self.moves_display.setStyleSheet(
            "font-family:'Courier New',monospace; font-size:12px; "
            "background:#FAFAFA; padding:6px;")
        moves_lay.addWidget(self.moves_display)

        move_btns = QHBoxLayout()
        self.record_btn = QPushButton("Record Mode")
        self.record_btn.setProperty("accent", True)
        self.record_btn.setCheckable(True)
        self.record_btn.setChecked(True)
        self.record_btn.toggled.connect(self._toggle_record)
        move_btns.addWidget(self.record_btn)

        self.add_move_btn = QPushButton("Add UCI Move")
        self.add_move_btn.clicked.connect(self._add_uci_move)
        move_btns.addWidget(self.add_move_btn)

        self.undo_move_btn = QPushButton("Undo Move")
        self.undo_move_btn.clicked.connect(self._undo_move)
        move_btns.addWidget(self.undo_move_btn)

        self.clear_moves_btn = QPushButton("Clear All")
        self.clear_moves_btn.clicked.connect(self._clear_moves)
        move_btns.addWidget(self.clear_moves_btn)

        self.reset_pos_btn = QPushButton("Reset Position")
        self.reset_pos_btn.clicked.connect(self._reset_position)
        move_btns.addWidget(self.reset_pos_btn)

        moves_lay.addLayout(move_btns)

        # UCI input
        uci_row = QHBoxLayout()
        self.uci_input = QLineEdit()
        self.uci_input.setPlaceholderText("e.g., e2e4 or e7e8q")
        self.uci_input.returnPressed.connect(self._add_uci_move)
        uci_row.addWidget(self.uci_input)
        moves_lay.addLayout(uci_row)

        moves_group.setLayout(moves_lay)
        layout.addWidget(moves_group)

        # Validation status
        self.validation_label = QLabel("")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)

        # Action buttons
        action_lay = QHBoxLayout()
        self.save_btn = QPushButton("Save Puzzle")
        self.save_btn.setProperty("accent", True)
        self.save_btn.setStyleSheet("font-size:14px; padding:10px 24px;")
        self.save_btn.clicked.connect(self._save_puzzle)
        action_lay.addWidget(self.save_btn)

        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setProperty("outline", "true")
        self.preview_btn.clicked.connect(self._preview_puzzle)
        action_lay.addWidget(self.preview_btn)

        self.new_btn = QPushButton("New Puzzle")
        self.new_btn.clicked.connect(self._new_puzzle)
        action_lay.addWidget(self.new_btn)

        layout.addStretch()
        scroll.setWidget(content)
        main.addWidget(scroll)

        # Connect board signals
        self.board.move_made.connect(self._on_board_move)
        self.board.position_changed.connect(self._update_fen_display)
        self._update_fen_display()

    def _apply_fen(self):
        fen = self.fen_edit.text().strip()
        if fen and self.engine.load_fen(fen):
            self.board.refresh()
            self._update_fen_display()
            self.sound_effect("start")
            self.validation_label.setText("")
            self.validation_label.setStyleSheet("color:#4CAF50;")
        else:
            self.validation_label.setText("Invalid FEN string")
            self.validation_label.setStyleSheet("color:#E53935;")

    def _set_starting_pos(self):
        self.engine.reset()
        self.fen_edit.setText(chess.STARTING_FEN)
        self.board.refresh()
        self._update_fen_display()
        self._clear_moves()

    def _clear_board(self):
        empty_fen = "8/8/8/8/8/8/8/8 w - - 0 1"
        self.engine.load_fen(empty_fen)
        self.fen_edit.setText(empty_fen)
        self.board.refresh()
        self._update_fen_display()
        self._clear_moves()

    def _paste_fen(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self.fen_edit.setText(text)
            self._apply_fen()

    def _update_fen_display(self):
        fen = self.engine.board.fen()
        self.current_fen_label.setText(f"FEN: {fen}")
        if self.engine.initial_fen:
            self.fen_edit.setText(self.engine.initial_fen)

    def _update_difficulty_label(self, val):
        score = val / 100.0
        tier = DifficultyTier.from_score(score)
        self.difficulty_label.setText(tier.label)
        self.difficulty_label.setStyleSheet(f"color:{tier.color}; font-weight:bold;")

    def _add_theme(self, tag):
        current = self.themes_edit.text().strip()
        if tag not in current.split():
            self.themes_edit.setText((current + " " + tag).strip())

    def _toggle_record(self, checked):
        self.board.set_interactive(checked)
        if checked:
            self.record_btn.setText("Recording...")
            self.record_btn.setProperty("accent", True)
        else:
            self.record_btn.setText("Record Mode")
            self.record_btn.setProperty("outline", True)
        self.record_btn.style().unpolish(self.record_btn)
        self.record_btn.style().polish(self.record_btn)

    def _on_board_move(self, uci):
        if self.record_btn.isChecked():
            self._update_moves_display()

    def _add_uci_move(self):
        uci = self.uci_input.text().strip()
        if not uci: return
        info = self.engine.make_move_uci(uci)
        if info:
            self.board.refresh()
            self._update_moves_display()
            self.uci_input.clear()
            self.sound_effect("move")
        else:
            self.validation_label.setText(f"Invalid move: {uci}")
            self.validation_label.setStyleSheet("color:#E53935;")

    def _undo_move(self):
        if self.engine.undo():
            self.board.refresh()
            self._update_moves_display()

    def _clear_moves(self):
        self.engine.reset_to_initial()
        self.board.refresh()
        self._update_moves_display()

    def _reset_position(self):
        self.engine.reset_to_initial()
        self.board.refresh()
        self._update_moves_display()
        self._update_fen_display()

    def _update_moves_display(self):
        if self.engine.san_history:
            self.moves_display.setText(" ".join(self.engine.san_history))
        else:
            self.moves_display.setText("No moves recorded")

    def sound_effect(self, name):
        # Access sound manager from parent
        pass

    def _validate(self) -> Tuple[bool, str]:
        if not self.engine.initial_fen:
            return False, "No position set. Apply a FEN first."
        if not self.name_edit.text().strip():
            return False, "Puzzle needs a name."
        if not self.engine.san_history:
            return False, "Record at least one move for the solution."
        # Verify solution is valid from initial position
        test_board = chess.Board(self.engine.initial_fen)
        for san in self.engine.san_history:
            try:
                move = test_board.parse_san(san)
                test_board.push(move)
            except Exception as e:
                return False, f"Invalid solution move '{san}': {e}"
        return True, "Valid"

    def _save_puzzle(self):
        valid, msg = self._validate()
        if not valid:
            self.validation_label.setText(msg)
            self.validation_label.setStyleSheet("color:#E53935;")
            QMessageBox.warning(self, "Validation Error", msg)
            return

        fen = self.engine.initial_fen or self.engine.board.fen()
        # Get UCI moves from initial position
        test_board = chess.Board(fen)
        uci_moves = []
        for san in self.engine.san_history:
            move = test_board.parse_san(san)
            uci_moves.append(move.uci())
            test_board.push(move)

        themes_text = self.themes_edit.text().strip()
        themes = frozenset(t.strip() for t in themes_text.split() if t.strip()) if themes_text else frozenset()
        rating_val = self.rating_spin.value() if self.rating_spin.value() > 0 else None

        if self._edit_mode and self._edit_puzzle_id is not None:
            pid = self._edit_puzzle_id
        else:
            pid = self.collection.next_id()

        puzzle = Puzzle(
            id=pid,
            name=self.name_edit.text().strip(),
            fen=fen,
            moves=tuple(uci_moves),
            desc=self.desc_edit.toPlainText().strip(),
            difficulty=self.difficulty_slider.value() / 100.0,
            themes=themes,
            rating=rating_val,
            move_count=len(uci_moves),
            opening=self.opening_edit.text().strip(),
            eco=self.eco_edit.text().strip(),
        )

        if self._edit_mode:
            self.collection.remove(pid)

        self.collection.add(puzzle)
        self.collection.build_index()

        self.validation_label.setText("Puzzle saved successfully!")
        self.validation_label.setStyleSheet("color:#4CAF50;")
        self.puzzle_saved.emit(puzzle)
        log(f"Puzzle saved: {puzzle.name} (id={puzzle.id})")

    def _preview_puzzle(self):
        """Reset and replay the puzzle from the beginning."""
        self.engine.reset_to_initial()
        self.board.refresh()
        self._update_moves_display()
        # Auto-play moves with delay
        if self.engine.san_history:
            self._preview_index = 0
            self._preview_moves = list(self.engine.san_history)
            self.engine.reset_to_initial()
            self.board.refresh()
            self._preview_next()

    def _preview_next(self):
        if self._preview_index < len(self._preview_moves):
            san = self._preview_moves[self._preview_index]
            info = self.engine.make_move_uci(
                chess.Move.from_uci(self._get_uci_for_san(san)).uci()
                if False else "")
            # Simpler: just use the UCI moves stored
            self._preview_index += 1
            self.board.refresh()
            QTimer.singleShot(800, self._preview_next)

    def _new_puzzle(self):
        self._edit_mode = False
        self._edit_puzzle_id = None
        self.mode_label.setText("New Puzzle")
        self.name_edit.clear()
        self.desc_edit.clear()
        self.difficulty_slider.setValue(50)
        self.rating_spin.setValue(0)
        self.opening_edit.clear()
        self.eco_edit.clear()
        self.themes_edit.clear()
        self.fen_edit.clear()
        self.engine.reset()
        self.board.refresh()
        self._update_fen_display()
        self._clear_moves()
        self.validation_label.setText("")

    def edit_puzzle(self, puzzle: Puzzle):
        """Load an existing puzzle for editing."""
        self._edit_mode = True
        self._edit_puzzle_id = puzzle.id
        self.mode_label.setText(f"Editing Puzzle #{puzzle.id}")
        self.name_edit.setText(puzzle.name)
        self.desc_edit.setPlainText(puzzle.desc)
        self.difficulty_slider.setValue(int(puzzle.difficulty * 100))
        self.rating_spin.setValue(puzzle.rating or 0)
        self.opening_edit.setText(puzzle.opening)
        self.eco_edit.setText(puzzle.eco)
        self.themes_edit.setText(" ".join(sorted(puzzle.themes)))
        self.fen_edit.setText(puzzle.fen)
        self.engine.load_fen(puzzle.fen)
        # Replay moves
        for uci in puzzle.moves:
            self.engine.make_move_uci(uci)
        self.board.refresh()
        self._update_fen_display()
        self._update_moves_display()
        self.validation_label.setText(f"Editing: {puzzle.name}")
        self.validation_label.setStyleSheet("color:#2D7D9A;")

# ═══════════════════════════════════════════════════════════════════════════════
#  VIDEO EDITOR PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class VideoEditorPanel(QWidget):
    export_started = Signal()
    export_finished = Signal(str)

    def __init__(self, engine: ChessEngine, board: ChessBoardWidget,
                 collection: PuzzleCollection, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.board = board
        self.collection = collection
        self._current_puzzle: Optional[Puzzle] = None
        self._worker: Optional[VideoExportWorker] = None
        self._thread: Optional[QThread] = None
        self._setup_ui()

    def _setup_ui(self):
        main = QVBoxLayout(self)
        main.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("Video Generator")
        title.setStyleSheet("font-size:18px; font-weight:700; color:#2D7D9A;")
        hdr.addWidget(title)
        hdr.addStretch()
        main.addLayout(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(14)

        # Preset selection
        preset_group = QGroupBox("Export Preset")
        preset_lay = QVBoxLayout()
        self.preset_combo = QComboBox()
        for name in EXPORT_PRESETS:
            self.preset_combo.addItem(name)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        preset_lay.addWidget(self.preset_combo)
        preset_group.setLayout(preset_lay)
        layout.addWidget(preset_group)

        # Video Config
        config_group = QGroupBox("Video Configuration")
        config_lay = QFormLayout()
        config_lay.setSpacing(8)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(200, 7680); self.width_spin.setValue(1920)
        self.width_spin.setSingleStep(2)
        config_lay.addRow("Width:", self.width_spin)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(200, 4320); self.height_spin.setValue(1080)
        self.height_spin.setSingleStep(2)
        config_lay.addRow("Height:", self.height_spin)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(10, 60); self.fps_spin.setValue(30)
        config_lay.addRow("FPS:", self.fps_spin)

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(10, 100); self.quality_spin.setValue(85)
        config_lay.addRow("Quality:", self.quality_spin)

        config_group.setLayout(config_lay)
        layout.addWidget(config_group)

        # Board Settings
        board_group = QGroupBox("Board Settings")
        board_lay = QFormLayout()

        self.theme_combo = QComboBox()
        for name in THEMES:
            self.theme_combo.addItem(name)
        self.theme_combo.setCurrentText("Classic")
        board_lay.addRow("Board Theme:", self.theme_combo)

        self.flip_check = QCheckBox("Flip Board")
        self.flip_check.toggled.connect(
            lambda c: self.board.set_flipped(c) if self.board else None)
        board_lay.addRow(self.flip_check)

        self.show_coords_check = QCheckBox("Show Coordinates")
        self.show_coords_check.setChecked(True)
        board_lay.addRow(self.show_coords_check)

        self.show_arrows_check = QCheckBox("Show Arrows")
        self.show_arrows_check.setChecked(True)
        board_lay.addRow(self.show_arrows_check)

        board_group.setLayout(board_lay)
        layout.addWidget(board_group)

        # Timing
        timing_group = QGroupBox("Timing")
        timing_lay = QFormLayout()

        self.title_dur_spin = QSpinBox()
        self.title_dur_spin.setRange(0, 10); self.title_dur_spin.setValue(3)
        self.title_dur_spin.setSuffix(" sec")
        timing_lay.addRow("Title Card:", self.title_dur_spin)

        self.think_dur_spin = QSpinBox()
        self.think_dur_spin.setRange(1, 15); self.think_dur_spin.setValue(3)
        self.think_dur_spin.setSuffix(" sec")
        timing_lay.addRow("Think Time:", self.think_dur_spin)

        self.move_dur_spin = QSpinBox()
        self.move_dur_spin.setRange(200, 3000); self.move_dur_spin.setValue(800)
        self.move_dur_spin.setSuffix(" ms")
        self.move_dur_spin.setSingleStep(100)
        timing_lay.addRow("Move Duration:", self.move_dur_spin)

        self.pause_dur_spin = QSpinBox()
        self.pause_dur_spin.setRange(0, 5000); self.pause_dur_spin.setValue(2000)
        self.pause_dur_spin.setSuffix(" ms")
        self.pause_dur_spin.setSingleStep(250)
        timing_lay.addRow("Pause After Move:", self.pause_dur_spin)

        self.end_dur_spin = QSpinBox()
        self.end_dur_spin.setRange(1, 15); self.end_dur_spin.setValue(3)
        self.end_dur_spin.setSuffix(" sec")
        timing_lay.addRow("End Card:", self.end_dur_spin)

        timing_group.setLayout(timing_lay)
        layout.addWidget(timing_group)

        # Overlays
        overlay_group = QGroupBox("Overlays & Branding")
        overlay_lay = QFormLayout()

        self.show_title_check = QCheckBox("Show Title Card")
        self.show_title_check.setChecked(True)
        overlay_lay.addRow(self.show_title_check)

        self.show_moves_check = QCheckBox("Show Move List")
        self.show_moves_check.setChecked(True)
        overlay_lay.addRow(self.show_moves_check)

        self.show_difficulty_check = QCheckBox("Show Difficulty Badge")
        self.show_difficulty_check.setChecked(True)
        overlay_lay.addRow(self.show_difficulty_check)

        self.show_solution_check = QCheckBox("Show Solution (auto-play)")
        self.show_solution_check.setChecked(True)
        overlay_lay.addRow(self.show_solution_check)

        self.channel_edit = QLineEdit()
        self.channel_edit.setPlaceholderText("Your channel name...")
        overlay_lay.addRow("Channel Name:", self.channel_edit)

        self.watermark_check = QCheckBox("Watermark")
        overlay_lay.addRow(self.watermark_check)

        self.title_override = QLineEdit()
        self.title_override.setPlaceholderText("Leave blank to use puzzle name")
        overlay_lay.addRow("Title Override:", self.title_override)

        overlay_group.setLayout(overlay_lay)
        layout.addWidget(overlay_group)

        # Preview
        preview_group = QGroupBox("Preview")
        preview_lay = QVBoxLayout()
        self.preview_label = QLabel("Select a puzzle and click Preview Frame")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(200)
        self.preview_label.setStyleSheet(
            "background:#1A1A1A; border-radius:6px; color:#757575;")
        preview_lay.addWidget(self.preview_label)

        preview_btns = QHBoxLayout()
        self.preview_title_btn = QPushButton("Preview Title")
        self.preview_title_btn.clicked.connect(self._preview_title)
        preview_btns.addWidget(self.preview_title_btn)

        self.preview_board_btn = QPushButton("Preview Board")
        self.preview_board_btn.clicked.connect(self._preview_board)
        preview_btns.addWidget(self.preview_board_btn)

        self.preview_end_btn = QPushButton("Preview End")
        self.preview_end_btn.clicked.connect(self._preview_end)
        preview_btns.addWidget(self.preview_end_btn)

        self.save_thumb_btn = QPushButton("Save Thumbnail")
        self.save_thumb_btn.clicked.connect(self._save_thumbnail)
        preview_btns.addWidget(self.save_thumb_btn)

        preview_lay.addLayout(preview_btns)
        preview_group.setLayout(preview_lay)
        layout.addWidget(preview_group)

        # Export
        export_group = QGroupBox("Export")
        export_lay = QVBoxLayout()

        self.puzzle_info_label = QLabel("No puzzle selected")
        self.puzzle_info_label.setStyleSheet("color:#757575;")
        export_lay.addWidget(self.puzzle_info_label)

        self.export_btn = QPushButton("Export Video")
        self.export_btn.setProperty("accent", True)
        self.export_btn.setStyleSheet("font-size:14px; padding:10px 24px;")
        self.export_btn.clicked.connect(self._start_export)
        export_lay.addWidget(self.export_btn)

        self.cancel_btn = QPushButton("Cancel Export")
        self.cancel_btn.setProperty("danger", True)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_export)
        export_lay.addWidget(self.cancel_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        export_lay.addWidget(self.progress_bar)

        self.export_status = QLabel("")
        self.export_status.setStyleSheet("color:#757575; font-size:11px;")
        export_lay.addWidget(self.export_status)

        export_group.setLayout(export_lay)
        layout.addWidget(export_group)

        layout.addStretch()
        scroll.setWidget(content)
        main.addWidget(scroll)

    def _get_config(self) -> VideoConfig:
        return VideoConfig(
            width=self.width_spin.value(),
            height=self.height_spin.value(),
            fps=self.fps_spin.value(),
            quality=self.quality_spin.value(),
            board_theme_name=self.theme_combo.currentText(),
            flip_board=self.flip_check.isChecked(),
            show_title_card=self.show_title_check.isChecked(),
            show_solution=self.show_solution_check.isChecked(),
            title_duration=float(self.title_dur_spin.value()),
            pause_duration=self.pause_dur_spin.value() / 1000.0,
            move_duration=self.move_dur_spin.value() / 1000.0,
            think_duration=float(self.think_dur_spin.value()),
            end_duration=float(self.end_dur_spin.value()),
            show_arrows=self.show_arrows_check.isChecked(),
            show_coordinates=self.show_coords_check.isChecked(),
            show_move_list=self.show_moves_check.isChecked(),
            show_difficulty=self.show_difficulty_check.isChecked(),
            channel_name=self.channel_edit.text().strip(),
            watermark=self.watermark_check.isChecked(),
            title_text=self.title_override.text().strip(),
        )

    def _on_preset_changed(self, name):
        preset = EXPORT_PRESETS.get(name)
        if preset and name != "Custom":
            self.width_spin.setValue(preset.width)
            self.height_spin.setValue(preset.height)
            self.fps_spin.setValue(preset.fps)
            self.think_dur_spin.setValue(int(preset.think_duration))
            self.move_dur_spin.setValue(int(preset.move_duration * 1000))

    def set_puzzle(self, puzzle: Puzzle):
        self._current_puzzle = puzzle
        title = puzzle.title_text if hasattr(puzzle, 'title_text') else puzzle.name
        self.puzzle_info_label.setText(
            f"<b>{puzzle.name}</b><br>"
            f"Rating: {puzzle.rating or 'N/A'} | "
            f"Difficulty: {puzzle.tier_label} | "
            f"Moves: {len(puzzle.moves)}")

    def _preview_title(self):
        cfg = self._get_config()
        puzzle = self._current_puzzle
        if not puzzle: return
        img = BoardRenderer.render_title_card(
            cfg, puzzle.name,
            subtitle=puzzle.desc[:80] if puzzle.desc else "",
            difficulty=puzzle.tier_label,
            diff_color=puzzle.tier_color,
            channel=cfg.channel_name)
        self._show_preview(img, cfg)

    def _preview_board(self):
        cfg = self._get_config()
        puzzle = self._current_puzzle
        if not puzzle: return
        temp_engine = ChessEngine()
        temp_engine.load_fen(puzzle.fen)
        img = BoardRenderer.render_full_frame(
            temp_engine.board, cfg,
            puzzle_title=puzzle.name,
            difficulty_label=puzzle.tier_label,
            difficulty_color=puzzle.tier_color,
            turn_text=f"{temp_engine.turn_name} to move",
            phase_text="Find the best move!",
            theme_name=cfg.board_theme_name)
        self._show_preview(img, cfg)

    def _preview_end(self):
        cfg = self._get_config()
        puzzle = self._current_puzzle
        if not puzzle: return
        temp_engine = ChessEngine()
        temp_engine.load_fen(puzzle.fen)
        for uci in puzzle.moves:
            temp_engine.make_move_uci(uci)
        result = "Checkmate!" if temp_engine.board.is_checkmate() else \
                 "Puzzle Complete"
        img = BoardRenderer.render_end_card(
            cfg, result,
            move_list=temp_engine.san_move_list(),
            channel=cfg.channel_name)
        self._show_preview(img, cfg)

    def _show_preview(self, img: QImage, cfg: VideoConfig):
        # Scale to fit preview area
        max_h = 300
        scale = max_h / max(img.height(), 1)
        scaled = img.scaled(int(img.width() * scale), max_h,
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm = QPixmap.fromImage(scaled)
        self.preview_label.setPixmap(pm)

    def _save_thumbnail(self):
        cfg = self._get_config()
        puzzle = self._current_puzzle
        if not puzzle: return
        temp_engine = ChessEngine()
        temp_engine.load_fen(puzzle.fen)
        img = BoardRenderer.render_full_frame(
            temp_engine.board, cfg,
            puzzle_title=puzzle.name,
            difficulty_label=puzzle.tier_label,
            difficulty_color=puzzle.tier_color,
            turn_text=f"{temp_engine.turn_name} to move",
            phase_text="Can you find the best move?",
            theme_name=cfg.board_theme_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Thumbnail", f"{puzzle.safe_filename()}_thumb.png",
            "PNG Files (*.png);;All Files (*)")
        if path:
            img.save(path)
            self.export_status.setText(f"Thumbnail saved: {path}")

    def _start_export(self):
        puzzle = self._current_puzzle
        if not puzzle:
            QMessageBox.warning(self, "No Puzzle", "Select a puzzle first.")
            return

        if not HAS_IMAGEIO and not HAS_FFMPEG:
            QMessageBox.warning(
                self, "Missing Dependencies",
                "Video export requires imageio or ffmpeg.\n\n"
                "Install with: pip install imageio[ffmpeg]")
            return

        cfg = self._get_config()
        self._worker = VideoExportWorker(puzzle, cfg)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_export_progress)
        self._worker.finished.connect(self._on_export_finished)
        self._worker.error.connect(self._on_export_error)
        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.export_status.setText("Exporting...")
        self._thread.start()
        self.export_started.emit()

    def _cancel_export(self):
        if self._worker:
            self._worker.cancel()
        self.export_status.setText("Cancelling...")

    def _on_export_progress(self, current, total):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
            pct = current * 100 // total
            self.export_status.setText(f"Exporting... {pct}%")

    def _on_export_finished(self, path):
        self._cleanup_export()
        self.export_status.setText(f"Export complete: {path}")
        self.export_finished.emit(path)
        QMessageBox.information(self, "Export Complete",
                               f"Video saved to:\n{path}")

    def _on_export_error(self, msg):
        self._cleanup_export()
        self.export_status.setText(f"Export failed: {msg}")
        QMessageBox.critical(self, "Export Error", msg)

    def _cleanup_export(self):
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        self._worker = None
        self._thread = None

# ═══════════════════════════════════════════════════════════════════════════════
#  FILTER PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class FilterPanel(QWidget):
    filter_changed = Signal(FilterCriteria)

    def __init__(self, collection: PuzzleCollection, parent=None):
        super().__init__(parent)
        self.collection = collection
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Search
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search puzzles...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._emit_filter)
        layout.addWidget(self.search_edit)

        # Difficulty range
        diff_label = QLabel("Difficulty:")
        diff_label.setStyleSheet("font-weight:600; font-size:11px;")
        layout.addWidget(diff_label)
        diff_row = QHBoxLayout()
        self.diff_min = QSlider(Qt.Horizontal)
        self.diff_min.setRange(0, 100); self.diff_min.setValue(0)
        self.diff_max = QSlider(Qt.Horizontal)
        self.diff_max.setRange(0, 100); self.diff_max.setValue(100)
        self.diff_min.valueChanged.connect(self._emit_filter)
        self.diff_max.valueChanged.connect(self._emit_filter)
        diff_row.addWidget(QLabel("Min")); diff_row.addWidget(self.diff_min)
        diff_row.addWidget(QLabel("Max")); diff_row.addWidget(self.diff_max)
        layout.addLayout(diff_row)

        # Rating range
        rating_label = QLabel("Rating:")
        rating_label.setStyleSheet("font-weight:600; font-size:11px;")
        layout.addWidget(rating_label)
        rating_row = QHBoxLayout()
        self.rating_min = QSpinBox()
        self.rating_min.setRange(0, 3500); self.rating_min.setValue(0)
        self.rating_min.setSingleStep(100)
        self.rating_max = QSpinBox()
        self.rating_max.setRange(0, 3500); self.rating_max.setValue(3500)
        self.rating_max.setSingleStep(100)
        self.rating_min.valueChanged.connect(self._emit_filter)
        self.rating_max.valueChanged.connect(self._emit_filter)
        rating_row.addWidget(QLabel("Min")); rating_row.addWidget(self.rating_min)
        rating_row.addWidget(QLabel("Max")); rating_row.addWidget(self.rating_max)
        layout.addLayout(rating_row)

        # Move count range
        moves_label = QLabel("Move Count:")
        moves_label.setStyleSheet("font-weight:600; font-size:11px;")
        layout.addWidget(moves_label)
        moves_row = QHBoxLayout()
        self.moves_min = QSpinBox()
        self.moves_min.setRange(1, 50); self.moves_min.setValue(1)
        self.moves_max = QSpinBox()
        self.moves_max.setRange(1, 50); self.moves_max.setValue(50)
        self.moves_min.valueChanged.connect(self._emit_filter)
        self.moves_max.valueChanged.connect(self._emit_filter)
        moves_row.addWidget(QLabel("Min")); moves_row.addWidget(self.moves_min)
        moves_row.addWidget(QLabel("Max")); moves_row.addWidget(self.moves_max)
        layout.addLayout(moves_row)

        # Themes
        theme_label = QLabel("Themes:")
        theme_label.setStyleSheet("font-weight:600; font-size:11px;")
        layout.addWidget(theme_label)
        self.theme_combo = QComboBox()
        self.theme_combo.setEditable(True)
        self.theme_combo.setPlaceholderText("Filter by theme...")
        self.theme_combo.currentTextChanged.connect(self._emit_filter)
        layout.addWidget(self.theme_combo)

        # Sort
        sort_label = QLabel("Sort:")
        sort_label.setStyleSheet("font-weight:600; font-size:11px;")
        layout.addWidget(sort_label)
        self.sort_combo = QComboBox()
        for mode in SortMode:
            self.sort_combo.addItem(mode.name.replace('_', ' ').title(), mode)
        self.sort_combo.currentIndexChanged.connect(self._emit_filter)
        layout.addWidget(self.sort_combo)

        # Require rating
        self.require_rating_check = QCheckBox("Has Rating")
        self.require_rating_check.toggled.connect(self._emit_filter)
        layout.addWidget(self.require_rating_check)

        # Reset button
        self.reset_btn = QPushButton("Reset Filters")
        self.reset_btn.setProperty("outline", "true")
        self.reset_btn.clicked.connect(self._reset_filters)
        layout.addWidget(self.reset_btn)

        layout.addStretch()

    def refresh_themes(self):
        if self.collection.index:
            current = self.theme_combo.currentText()
            self.theme_combo.clear()
            self.theme_combo.addItem("")
            for theme in self.collection.index.all_themes:
                self.theme_combo.addItem(theme)
            idx = self.theme_combo.findText(current)
            if idx >= 0:
                self.theme_combo.setCurrentIndex(idx)

    def _emit_filter(self, *_):
        theme_tags = frozenset()
        theme_text = self.theme_combo.currentText().strip()
        if theme_text:
            theme_tags = frozenset([theme_text])

        sort_data = self.sort_combo.currentData()
        sort_mode = sort_data if sort_data else SortMode.DEFAULT

        criteria = FilterCriteria(
            text_query=self.search_edit.text().strip(),
            difficulty_range=(self.diff_min.value() / 100.0,
                            self.diff_max.value() / 100.0),
            rating_range=(self.rating_min.value(), self.rating_max.value()),
            move_count_range=(self.moves_min.value(), self.moves_max.value()),
            theme_tags=theme_tags,
            sort_mode=sort_mode,
            require_rating=self.require_rating_check.isChecked(),
        )
        self.filter_changed.emit(criteria)

    def _reset_filters(self):
        self.search_edit.clear()
        self.diff_min.setValue(0); self.diff_max.setValue(100)
        self.rating_min.setValue(0); self.rating_max.setValue(3500)
        self.moves_min.setValue(1); self.moves_max.setValue(50)
        self.theme_combo.setCurrentIndex(0)
        self.sort_combo.setCurrentIndex(0)
        self.require_rating_check.setChecked(False)

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE BROWSER PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleBrowserPanel(QWidget):
    puzzle_selected = Signal(object)  # Puzzle
    puzzle_edit_requested = Signal(object)

    def __init__(self, collection: PuzzleCollection, parent=None):
        super().__init__(parent)
        self.collection = collection
        self._filtered_ids: List[int] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Stats bar
        self.stats_label = QLabel("0 puzzles")
        self.stats_label.setStyleSheet("font-weight:600; color:#2D7D9A;")
        layout.addWidget(self.stats_label)

        # Puzzle list
        self.puzzle_list = QListWidget()
        self.puzzle_list.setAlternatingRowColors(True)
        self.puzzle_list.currentRowChanged.connect(self._on_selection)
        self.puzzle_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.puzzle_list.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.puzzle_list)

        # Action buttons
        btn_row = QHBoxLayout()
        self.load_btn = QPushButton("Load Puzzles")
        self.load_btn.setProperty("accent", True)
        self.load_btn.clicked.connect(self._load_puzzles)
        btn_row.addWidget(self.load_btn)

        self.save_btn = QPushButton("Save Collection")
        self.save_btn.clicked.connect(self._save_puzzles)
        btn_row.addWidget(self.save_btn)

        self.sample_btn = QPushButton("Load Samples")
        self.sample_btn.setProperty("outline", "true")
        self.sample_btn.clicked.connect(self._load_samples)
        btn_row.addWidget(self.sample_btn)

        layout.addLayout(btn_row)

    def refresh(self, filtered_ids: List[int] = None):
        if filtered_ids is not None:
            self._filtered_ids = filtered_ids
        else:
            if self.collection.index:
                self._filtered_ids = sorted(self.collection.index.all_ids)
            else:
                self._filtered_ids = []

        self.puzzle_list.clear()
        for pid in self._filtered_ids:
            puzzle = self.collection.get(pid)
            if puzzle:
                item = QListWidgetItem()
                # Colored difficulty indicator
                tier_char = "●"
                item.setText(f" {tier_char} {puzzle.name}  "
                            f"[{puzzle.tier_label}]  "
                            f"{'⭐' + str(puzzle.rating) if puzzle.rating else ''}  "
                            f"{'🎬' + str(len(puzzle.moves)) + ' moves' if puzzle.moves else ''}")
                item.setData(Qt.UserRole, pid)
                # Color the tier indicator
                item.setForeground(QColor(puzzle.tier_color))
                self.puzzle_list.addItem(item)

        self.stats_label.setText(
            f"{len(self._filtered_ids)} of {self.collection.count} puzzles")

    def _on_selection(self, row):
        if 0 <= row < len(self._filtered_ids):
            pid = self._filtered_ids[row]
            puzzle = self.collection.get(pid)
            if puzzle:
                self.puzzle_selected.emit(puzzle)

    def _context_menu(self, pos):
        item = self.puzzle_list.itemAt(pos)
        if not item: return
        pid = item.data(Qt.UserRole)
        puzzle = self.collection.get(pid)
        if not puzzle: return

        menu = QMenu(self)
        load_action = menu.addAction("Load on Board")
        edit_action = menu.addAction("Edit Puzzle")
        delete_action = menu.addAction("Delete Puzzle")
        export_action = menu.addAction("Export Video")

        action = menu.exec(self.puzzle_list.mapToGlobal(pos))
        if action == load_action:
            self.puzzle_selected.emit(puzzle)
        elif action == edit_action:
            self.puzzle_edit_requested.emit(puzzle)
        elif action == delete_action:
            reply = QMessageBox.question(
                self, "Delete Puzzle",
                f"Delete '{puzzle.name}'?",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.collection.remove(pid)
                self.collection.build_index()
                self.refresh()
        elif action == export_action:
            self.puzzle_selected.emit(puzzle)

    def _load_puzzles(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Puzzles", DATA_DIR,
            "All Supported (*.csv *.json *.jsonl *.parquet);;"
            "CSV Files (*.csv);;JSON Files (*.json *.jsonl);;"
            "Parquet Files (*.parquet);;All Files (*)")
        if not path: return

        loaded = 0
        for loader in LOADERS:
            if loader.can_load(path):
                rows = loader.load(path)
                id_start = self.collection.next_id()
                for row in rows:
                    puzzle = normalize_puzzle_row(row, id_start + loaded)
                    if puzzle:
                        self.collection.add(puzzle)
                        loaded += 1
                break

        if loaded > 0:
            self.collection.build_index()
            self.refresh()
            QMessageBox.information(
                self, "Loaded", f"Imported {loaded} puzzles from {os.path.basename(path)}")
        else:
            QMessageBox.warning(self, "No Puzzles", "No valid puzzles found in file.")

    def _save_puzzles(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Puzzles", os.path.join(DATA_DIR, "puzzles.json"),
            "JSON Files (*.json);;All Files (*)")
        if path:
            self.collection.save_json(path)
            QMessageBox.information(self, "Saved",
                                   f"Saved {self.collection.count} puzzles.")

    def _load_samples(self):
        """Load built-in sample puzzles for demonstration."""
        samples = self._generate_sample_puzzles()
        for p in samples:
            self.collection.add(p)
        self.collection.build_index()
        self.refresh()
        QMessageBox.information(self, "Samples Loaded",
                               f"Loaded {len(samples)} sample puzzles.")

    def _generate_sample_puzzles(self) -> List[Puzzle]:
        """Generate a set of sample puzzles covering various themes."""
        samples_data = [
            ("Back Rank Mate", "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1",
             ["a1a8"], "Classic back rank weakness", 0.3,
             frozenset(["mate in 1", "back rank", "beginner"]), 800),
            ("Smothered Mate", "r5k1/5ppp/8/8/1N6/8/5PPP/6K1 w - - 0 1",
             ["b4c2", "a8a1", "c2a1"], "Knight delivers smothered mate", 0.6,
             frozenset(["mate in 2", "smothered mate", "knight"]), 1500),
            ("Rook Sacrifice", "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
             ["e4e5"], "Break open the center", 0.2,
             frozenset(["pawn", "center", "beginner"]), 600),
            ("Fork Tactic", "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 3",
             ["d2d3"], "Develop with a tactical threat", 0.3,
             frozenset(["development", "tactics"]), 900),
            ("Queen Trap", "r1b1kb1r/ppppqppp/2n2n2/4p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 0 1",
             ["d2d4"], "Opening the position to trap the queen", 0.5,
             frozenset(["queen trap", "tactics", "intermediate"]), 1300),
            ("Pin and Win", "r2qk2r/ppp2ppp/2n1bn2/3pp3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R w KQkq - 0 1",
             ["c4f7"], "Bishop pins the knight to the king", 0.4,
             frozenset(["pin", "sacrifice", "intermediate"]), 1200),
            ("Endgame Technique", "8/8/4k3/8/8/4K3/4R3/8 w - - 0 1",
             ["e2e6"], "Rook endgame technique", 0.5,
             frozenset(["endgame", "rook", "technique"]), 1100),
            ("Discovered Attack", "rnbqkb1r/pppppppp/5n2/8/4P3/2N5/PPPP1PPP/R1BQKBNR w KQkq - 1 2",
             ["c3e4"], "Discovered attack on the knight", 0.35,
             frozenset(["discovered attack", "tactics"]), 1000),
            ("Zugzwang", "8/8/1p1k4/p1p5/P1P5/1P1K4/8/8 w - - 0 1",
             [], "Side to move loses — pure zugzwang", 0.85,
             frozenset(["zugzwang", "endgame", "pawn"]), 2200),
            ("Mating Attack", "r1b1k2r/ppppqppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R w KQkq - 0 1",
             ["f3e5"], "Knight fork wins material", 0.45,
             frozenset(["fork", "knight", "tactics"]), 1250),
        ]

        puzzles = []
        base_id = self.collection.next_id()
        for i, (name, fen, moves, desc, diff, themes, rating) in enumerate(samples_data):
            p = Puzzle(
                id=base_id + i, name=name, fen=fen,
                moves=tuple(moves), desc=desc,
                difficulty=diff, themes=themes,
                rating=rating, move_count=max(1, len(moves)))
            puzzles.append(p)
        return puzzles

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE PLAY PANEL — Interactive puzzle solving
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzlePlayPanel(QWidget):
    puzzle_completed = Signal(bool)  # solved correctly

    def __init__(self, engine: ChessEngine, board: ChessBoardWidget,
                 sound: SoundManager, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.board = board
        self.sound = sound
        self._current_puzzle: Optional[Puzzle] = None
        self._move_index = 0
        self._solving = False
        self._auto_play_timer = QTimer(self)
        self._auto_play_timer.setSingleShot(True)
        self._auto_play_timer.timeout.connect(self._auto_play_response)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Puzzle info
        info_frame = QFrame()
        info_frame.setStyleSheet(
            "QFrame{background:#FFF; border:1px solid #E0E0E0; border-radius:6px; padding:8px;}")
        info_lay = QVBoxLayout(info_frame)
        info_lay.setSpacing(4)

        self.puzzle_name_label = QLabel("No puzzle loaded")
        self.puzzle_name_label.setStyleSheet("font-size:15px; font-weight:700;")
        info_lay.addWidget(self.puzzle_name_label)

        self.puzzle_desc_label = QLabel("")
        self.puzzle_desc_label.setWordWrap(True)
        self.puzzle_desc_label.setStyleSheet("color:#757575; font-size:12px;")
        info_lay.addWidget(self.puzzle_desc_label)

        meta_row = QHBoxLayout()
        self.difficulty_badge = QLabel("")
        self.difficulty_badge.setStyleSheet(
            "padding:2px 10px; border-radius:10px; color:white; font-weight:bold; font-size:11px;")
        meta_row.addWidget(self.difficulty_badge)
        self.rating_label = QLabel("")
        self.rating_label.setStyleSheet("color:#757575; font-size:12px;")
        meta_row.addWidget(self.rating_label)
        self.turn_label = QLabel("")
        self.turn_label.setStyleSheet("font-weight:600; font-size:12px;")
        meta_row.addWidget(self.turn_label)
        meta_row.addStretch()
        info_lay.addLayout(meta_row)

        layout.addWidget(info_frame)

        # Move progress
        self.progress_label = QLabel("")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setStyleSheet(
            "font-size:12px; color:#757575; padding:4px;")
        layout.addWidget(self.progress_label)

        # Feedback
        self.feedback_label = QLabel("")
        self.feedback_label.setAlignment(Qt.AlignCenter)
        self.feedback_label.setStyleSheet(
            "font-size:14px; font-weight:600; padding:8px; border-radius:6px;")
        layout.addWidget(self.feedback_label)

        # Control buttons
        ctrl_row = QHBoxLayout()

        self.hint_btn = QPushButton("💡 Hint")
        self.hint_btn.clicked.connect(self._show_hint)
        ctrl_row.addWidget(self.hint_btn)

        self.reset_btn = QPushButton("🔄 Reset")
        self.reset_btn.clicked.connect(self._reset_puzzle)
        ctrl_row.addWidget(self.reset_btn)

        self.solution_btn = QPushButton("📖 Show Solution")
        self.solution_btn.clicked.connect(self._show_solution)
        ctrl_row.addWidget(self.solution_btn)

        self.next_move_btn = QPushButton("▶ Next Move")
        self.next_move_btn.clicked.connect(self._play_next_move)
        ctrl_row.addWidget(self.next_move_btn)

        layout.addLayout(ctrl_row)

        # Move history display
        self.moves_display = QTextEdit()
        self.moves_display.setReadOnly(True)
        self.moves_display.setMaximumHeight(50)
        self.moves_display.setStyleSheet(
            "font-family:'Courier New',monospace; font-size:12px; "
            "background:#F5F5F5; border:1px solid #E0E0E0; border-radius:4px; padding:4px;")
        layout.addWidget(self.moves_display)

        layout.addStretch()

        # Connect board
        self.board.move_info.connect(self._on_player_move)

    def load_puzzle(self, puzzle: Puzzle):
        self._current_puzzle = puzzle
        self._move_index = 0
        self._solving = True

        self.engine.load_fen(puzzle.fen)
        self.board.refresh()
        self.board.set_interactive(True)

        self.puzzle_name_label.setText(puzzle.name)
        self.puzzle_desc_label.setText(puzzle.desc)
        tier = puzzle.tier
        self.difficulty_badge.setText(tier.label)
        self.difficulty_badge.setStyleSheet(
            f"padding:2px 10px; border-radius:10px; color:white; "
            f"font-weight:bold; font-size:11px; background:{tier.color};")
        self.rating_label.setText(f"⭐ {puzzle.rating}" if puzzle.rating else "")
        self.turn_label.setText(f"{self.engine.turn_name} to move")
        self.progress_label.setText(f"Move 1 of {len(puzzle.moves)}")
        self.feedback_label.setText("Your turn! Find the best move.")
        self.feedback_label.setStyleSheet(
            "font-size:14px; font-weight:600; padding:8px; border-radius:6px; "
            "background:#E0F0F5; color:#2D7D9A;")
        self.moves_display.clear()

        self.sound.play("start")

    def _on_player_move(self, info: MoveInfo):
        if not self._current_puzzle or not self._solving:
            return

        puzzle = self._current_puzzle
        if self._move_index >= len(puzzle.moves):
            return

        expected_uci = puzzle.moves[self._move_index]
        actual_move = self.engine.board.peek() if self.engine.board.move_stack else None

        if actual_move:
            actual_uci = actual_move.uci()
            if actual_uci == expected_uci:
                # Correct move
                self._move_index += 1
                self._update_progress()

                if self._move_index < len(puzzle.moves):
                    self.feedback_label.setText("✓ Correct! Opponent is responding...")
                    self.feedback_label.setStyleSheet(
                        "font-size:14px; font-weight:600; padding:8px; "
                        "border-radius:6px; background:#E8F5E9; color:#4CAF50;")
                    # Auto-play opponent response
                    self._auto_play_timer.start(800)
                else:
                    self._on_puzzle_solved()
            else:
                # Wrong move
                self.feedback_label.setText("✗ Not the best move. Try again!")
                self.feedback_label.setStyleSheet(
                    "font-size:14px; font-weight:600; padding:8px; "
                    "border-radius:6px; background:#FFEBEE; color:#E53935;")
                self.sound.play("error")
                # Undo
                QTimer.singleShot(600, self._undo_last)

        self._update_moves_display()

    def _auto_play_response(self):
        """Play the opponent's response move."""
        if not self._current_puzzle or self._move_index >= len(self._current_puzzle.moves):
            return
        uci = self._current_puzzle.moves[self._move_index]
        info = self.engine.make_move_uci(uci)
        if info:
            self._move_index += 1
            self.board.refresh()
            self._update_progress()
            self._update_moves_display()

            if self._move_index >= len(self._current_puzzle.moves):
                self._on_puzzle_solved()
            else:
                self.feedback_label.setText("Your turn! Find the best move.")
                self.feedback_label.setStyleSheet(
                    "font-size:14px; font-weight:600; padding:8px; "
                    "border-radius:6px; background:#E0F0F5; color:#2D7D9A;")

            if info.is_check:
                self.sound.play("check")
            elif info.is_mate:
                self.sound.play("checkmate")
            elif info.captured != '.':
                self.sound.play("capture")
            else:
                self.sound.play("move")

    def _undo_last(self):
        if self.engine.undo():
            self.board.refresh()
            self._update_moves_display()

    def _on_puzzle_solved(self):
        self._solving = False
        self.feedback_label.setText("🎉 Puzzle Solved! Excellent!")
        self.feedback_label.setStyleSheet(
            "font-size:16px; font-weight:700; padding:12px; border-radius:6px; "
            "background:#E8F5E9; color:#2E7D32;")
        self.sound.play("checkmate")
        self.puzzle_completed.emit(True)

    def _update_progress(self):
        if self._current_puzzle:
            total = len(self._current_puzzle.moves)
            self.progress_label.setText(f"Move {self._move_index + 1} of {total}")
            pct = (self._move_index / max(1, total)) * 100
            self.progress_label.setText(
                f"Progress: {self._move_index}/{total} moves ({int(pct)}%)")

    def _update_moves_display(self):
        self.moves_display.setText(" ".join(self.engine.san_history))

    def _show_hint(self):
        if not self._current_puzzle or self._move_index >= len(self._current_puzzle.moves):
            return
        uci = self._current_puzzle.moves[self._move_index]
        try:
            move = chess.Move.from_uci(uci)
            board = self.engine.board
            san = board.san(move)
            self.feedback_label.setText(f"💡 Hint: Look at {san}")
            self.feedback_label.setStyleSheet(
                "font-size:14px; font-weight:600; padding:8px; "
                "border-radius:6px; background:#FFF8E1; color:#F57F17;")
        except Exception:
            self.feedback_label.setText("💡 Hint: Look for a strong move!")

    def _reset_puzzle(self):
        if self._current_puzzle:
            self.load_puzzle(self._current_puzzle)

    def _show_solution(self):
        if not self._current_puzzle:
            return
        self._solving = False
        self.engine.reset_to_initial()
        self.board.set_interactive(False)
        self.board.refresh()

        # Animate solution moves
        self._solution_moves = list(self._current_puzzle.moves)
        self._solution_index = 0
        self._play_solution_step()

    def _play_solution_step(self):
        if self._solution_index < len(self._solution_moves):
            uci = self._solution_moves[self._solution_index]
            info = self.engine.make_move_uci(uci)
            if info:
                self.board.refresh()
                self._update_moves_display()
                if info.is_mate:
                    self.sound.play("checkmate")
                elif info.is_check:
                    self.sound.play("check")
                elif info.captured != '.':
                    self.sound.play("capture")
                else:
                    self.sound.play("move")
            self._solution_index += 1
            QTimer.singleShot(600, self._play_solution_step)
        else:
            self.feedback_label.setText("Solution complete.")
            self.feedback_label.setStyleSheet(
                "font-size:14px; font-weight:600; padding:8px; "
                "border-radius:6px; background:#E0F0F5; color:#2D7D9A;")
            self.board.set_interactive(True)

    def _play_next_move(self):
        """Play the next move in the solution (for step-by-step viewing)."""
        if not self._current_puzzle:
            return
        if self._move_index < len(self._current_puzzle.moves):
            uci = self._current_puzzle.moves[self._move_index]
            info = self.engine.make_move_uci(uci)
            if info:
                self._move_index += 1
                self.board.refresh()
                self._update_moves_display()
                self._update_progress()
                if info.is_mate:
                    self.sound.play("checkmate")
                elif info.is_check:
                    self.sound.play("check")
                elif info.captured != '.':
                    self.sound.play("capture")
                else:
                    self.sound.play("move")

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chess Puzzle Studio — Create & Share Chess Puzzles")
        self.setMinimumSize(1200, 750)
        self.resize(1400, 850)

        # Core objects
        self.engine = ChessEngine()
        self.sound = SoundManager()
        self.collection = PuzzleCollection()

        # Load saved collection
        saved_path = os.path.join(DATA_DIR, "puzzles.json")
        if os.path.exists(saved_path):
            try:
                self.collection.load_json(saved_path)
                self.collection.build_index()
            except Exception as e:
                log(f"Failed to load saved puzzles: {e}")

        # Build UI
        self._setup_ui()
        self._setup_toolbar()
        self._setup_statusbar()
        self._connect_signals()
        self._apply_settings()

        # Auto-load samples if collection is empty
        if self.collection.count == 0:
            self.browser._load_samples()

        self.statusBar().showMessage("Ready — Create, solve, and share chess puzzles!")

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # --- FIX: Create the board FIRST so we can pass it to other panels ---
        self.board = ChessBoardWidget(self.engine, self.sound, sq_size=SQ_SIZE)

        # Left panel: tabs for Creator, Play, Browser
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(8, 8, 4, 8)
        left_widget.setFixedWidth(340)

        self.left_tabs = QTabWidget()
        self.left_tabs.setStyleSheet(
            "QTabBar::tab { font-size:11px; padding:6px 12px; }")

        # Browser panel
        self.browser = PuzzleBrowserPanel(self.collection)
        self.left_tabs.addTab(self.browser, "📚 Browse")

        # Play panel (now receives self.board instead of None)
        self.play_panel = PuzzlePlayPanel(self.engine, self.board, self.sound)
        self.left_tabs.addTab(self.play_panel, "♟ Play")

        # Creator panel (now receives self.board instead of None)
        self.creator = PuzzleCreatorPanel(self.engine, self.board, self.collection)
        self.left_tabs.addTab(self.creator, "✏️ Create")

        # Video panel (now receives self.board instead of None)
        self.video_panel = VideoEditorPanel(self.engine, self.board, self.collection)
        self.left_tabs.addTab(self.video_panel, "🎬 Video")

        left_layout.addWidget(self.left_tabs)
        main_layout.addWidget(left_widget)

        # Center: Chess board layout
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(4, 8, 4, 8)

        # Board controls
        controls = QHBoxLayout()
        controls.setSpacing(6)

        self.flip_btn = QPushButton("🔄 Flip")
        self.flip_btn.setFixedWidth(70)
        self.flip_btn.setToolTip("Flip the board")
        controls.addWidget(self.flip_btn)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES.keys())
        self.theme_combo.setCurrentText("Classic")
        self.theme_combo.setFixedWidth(100)
        self.theme_combo.setToolTip("Board theme")
        controls.addWidget(self.theme_combo)

        self.undo_btn = QPushButton("↩ Undo")
        self.undo_btn.setFixedWidth(70)
        controls.addWidget(self.undo_btn)

        self.reset_btn = QPushButton("⟲ Reset")
        self.reset_btn.setFixedWidth(70)
        controls.addWidget(self.reset_btn)

        controls.addStretch()

        self.sound_btn = QPushButton("🔊")
        self.sound_btn.setFixedWidth(40)
        self.sound_btn.setCheckable(True)
        self.sound_btn.setChecked(True)
        self.sound_btn.setToolTip("Toggle sound")
        controls.addWidget(self.sound_btn)

        self.anim_slider = QSlider(Qt.Horizontal)
        self.anim_slider.setRange(50, 800)
        self.anim_slider.setValue(ANIM_SPEED_DEFAULT)
        self.anim_slider.setFixedWidth(100)
        self.anim_slider.setToolTip("Animation speed")
        controls.addWidget(self.anim_slider)

        speed_label = QLabel("Speed")
        speed_label.setStyleSheet("font-size:11px; color:#757575;")
        controls.addWidget(speed_label)

        center_layout.addLayout(controls)

        # Add the already-created board to the layout
        center_layout.addWidget(self.board, alignment=Qt.AlignCenter)

        # FEN display
        self.fen_display = QLabel("")
        self.fen_display.setStyleSheet(
            "font-family:monospace; font-size:10px; color:#BDBDBD; padding:2px;")
        self.fen_display.setAlignment(Qt.AlignCenter)
        center_layout.addWidget(self.fen_display)

        # Engine info
        self.engine_info = QLabel("")
        self.engine_info.setStyleSheet("font-size:11px; color:#757575; padding:2px;")
        self.engine_info.setAlignment(Qt.AlignCenter)
        center_layout.addWidget(self.engine_info)

        center_layout.addStretch()
        main_layout.addWidget(center_widget, stretch=1)

        # Right panel: filter
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 8, 8, 8)
        right_widget.setFixedWidth(240)

        self.filter_panel = FilterPanel(self.collection)
        right_layout.addWidget(self.filter_panel)

        main_layout.addWidget(right_widget)

    def _setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        # File actions
        load_action = QAction("📂 Import", self)
        load_action.setToolTip("Import puzzles from file")
        load_action.triggered.connect(lambda: self.browser._load_puzzles())
        toolbar.addAction(load_action)

        save_action = QAction("💾 Save", self)
        save_action.setToolTip("Save puzzle collection")
        save_action.triggered.connect(lambda: self.browser._save_puzzles())
        toolbar.addAction(save_action)

        toolbar.addSeparator()

        # Quick export
        export_video_action = QAction("🎬 Export Video", self)
        export_video_action.setToolTip("Export current puzzle as video")
        export_video_action.triggered.connect(self._quick_export)
        toolbar.addAction(export_video_action)

        export_shorts_action = QAction("📱 Export Shorts", self)
        export_shorts_action.setToolTip("Export as YouTube Shorts")
        export_shorts_action.triggered.connect(self._quick_export_shorts)
        toolbar.addAction(export_shorts_action)

        toolbar.addSeparator()

        # Screenshot
        screenshot_action = QAction("📸 Screenshot", self)
        screenshot_action.setToolTip("Save board screenshot")
        screenshot_action.triggered.connect(self._screenshot)
        toolbar.addAction(screenshot_action)

        toolbar.addSeparator()

        # Batch export
        batch_action = QAction("📦 Batch Export", self)
        batch_action.setToolTip("Export multiple puzzles as videos")
        batch_action.triggered.connect(self._batch_export)
        toolbar.addAction(batch_action)

    def _setup_statusbar(self):
        self.statusBar().addPermanentWidget(
            QLabel(f"  imageio: {'✓' if HAS_IMAGEIO else '✗'}  |  "
                   f"ffmpeg: {'✓' if HAS_FFMPEG else '✗'}  |  "
                   f"pandas: {'✓' if HAS_PANDAS else '✗'}  "))

    def _connect_signals(self):
        # Board
        self.flip_btn.clicked.connect(lambda: self.board.set_flipped(not self.board.flipped))
        self.theme_combo.currentTextChanged.connect(self.board.set_theme)
        self.theme_combo.currentTextChanged.connect(
            lambda t: self.board.update())
        self.undo_btn.clicked.connect(self._undo_move)
        self.reset_btn.clicked.connect(self._reset_board)
        self.sound_btn.toggled.connect(self.sound.set_enabled)
        self.anim_slider.valueChanged.connect(
            lambda v: setattr(self.board, '_anim_speed', v))

        # Board position updates
        self.board.position_changed.connect(self._update_position_info)

        # Browser
        self.browser.puzzle_selected.connect(self._on_puzzle_selected)
        self.browser.puzzle_edit_requested.connect(self._on_puzzle_edit)

        # Filter
        self.filter_panel.filter_changed.connect(self._on_filter_changed)

        # Creator
        self.creator.puzzle_saved.connect(self._on_puzzle_saved)

        # Play
        self.play_panel.puzzle_completed.connect(self._on_puzzle_completed)

        # Video
        self.video_panel.export_finished.connect(self._on_export_finished)

    def _update_position_info(self):
        fen = self.engine.board.fen()
        self.fen_display.setText(fen)
        move_num = self.engine.board.fullmove_number
        turn = "White" if self.engine.board.turn == chess.WHITE else "Black"
        info_parts = [f"{turn} to move", f"Move {move_num}"]
        if self.engine.board.is_check():
            info_parts.append("⚠ Check!")
        if self.engine.board.is_checkmate():
            info_parts.append("♚ Checkmate!")
        if self.engine.board.is_stalemate():
            info_parts.append("½ Stalemate")
        if self.engine.board.is_insufficient_material():
            info_parts.append("½ Insufficient material")
        self.engine_info.setText(" | ".join(info_parts))

    def _on_puzzle_selected(self, puzzle: Puzzle):
        # Switch to play tab and load puzzle
        self.left_tabs.setCurrentIndex(1)  # Play tab
        self.play_panel.load_puzzle(puzzle)
        self.video_panel.set_puzzle(puzzle)
        self.statusBar().showMessage(
            f"Loaded: {puzzle.name} ({puzzle.tier_label}, "
            f"{'Rating ' + str(puzzle.rating) if puzzle.rating else 'Unrated'})")

    def _on_puzzle_edit(self, puzzle: Puzzle):
        self.left_tabs.setCurrentIndex(2)  # Create tab
        self.creator.edit_puzzle(puzzle)
        self.statusBar().showMessage(f"Editing: {puzzle.name}")

    def _on_puzzle_saved(self, puzzle: Puzzle):
        self.browser.refresh()
        self.filter_panel.refresh_themes()
        self.statusBar().showMessage(f"Puzzle saved: {puzzle.name}")
        # Auto-save collection
        self._auto_save()

    def _on_puzzle_completed(self, solved: bool):
        if solved:
            self.statusBar().showMessage("🎉 Puzzle solved! Great job!")

    def _on_filter_changed(self, criteria: FilterCriteria):
        ids = self.collection.filter(criteria)
        self.browser.refresh(ids)

    def _on_export_finished(self, path: str):
        self.statusBar().showMessage(f"Video exported: {path}")

    def _undo_move(self):
        if self.engine.undo():
            self.board.refresh()
            self._update_position_info()

    def _reset_board(self):
        self.engine.reset_to_initial()
        self.board.refresh()
        self._update_position_info()

    def _screenshot(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot", "chess_board.png",
            "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)")
        if path:
            self.board.save_screenshot(path)
            self.statusBar().showMessage(f"Screenshot saved: {path}")

    def _quick_export(self):
        """Quick export current puzzle as YouTube video."""
        if self.collection.count == 0:
            QMessageBox.warning(self, "No Puzzles", "Load or create puzzles first.")
            return
        # Get the most recently selected/created puzzle
        self.left_tabs.setCurrentIndex(3)  # Video tab
        self.statusBar().showMessage("Configure and export video from the Video tab.")

    def _quick_export_shorts(self):
        """Quick export as YouTube Shorts."""
        self.left_tabs.setCurrentIndex(3)
        self.video_panel.preset_combo.setCurrentText("YouTube Shorts")
        self.statusBar().showMessage("YouTube Shorts preset selected. Click Export Video.")

    def _batch_export(self):
        """Export multiple puzzles as videos."""
        if self.collection.count == 0:
            QMessageBox.warning(self, "No Puzzles", "Load or create puzzles first.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Batch Export Videos")
        dialog.setMinimumSize(400, 300)
        lay = QVBoxLayout(dialog)

        lay.addWidget(QLabel("Select puzzles to export:"))

        puzzle_list = QListWidget()
        puzzle_list.setAlternatingRowColors(True)
        for p in self.collection.puzzles:
            item = QListWidgetItem(f"{p.name} [{p.tier_label}]")
            item.setData(Qt.UserRole, p.id)
            item.setCheckState(Qt.Checked)
            puzzle_list.addItem(item)
        lay.addWidget(puzzle_list)

        # Preset
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        preset_combo = QComboBox()
        preset_combo.addItems(EXPORT_PRESETS.keys())
        preset_combo.setCurrentText("YouTube Shorts")
        preset_row.addWidget(preset_combo)
        lay.addLayout(preset_row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dialog.accept)
        btns.rejected.connect(dialog.reject)
        lay.addWidget(btns)

        if dialog.exec() == QDialog.Accepted:
            selected = []
            for i in range(puzzle_list.count()):
                item = puzzle_list.item(i)
                if item.checkState() == Qt.Checked:
                    selected.append(item.data(Qt.UserRole))

            if not selected:
                QMessageBox.warning(self, "None Selected", "Select at least one puzzle.")
                return

            preset_name = preset_combo.currentText()
            self._do_batch_export(selected, preset_name)

    def _do_batch_export(self, puzzle_ids: List[int], preset_name: str):
        """Perform batch export of selected puzzles."""
        preset = EXPORT_PRESETS.get(preset_name, VideoConfig())
        out_dir = os.path.join(DATA_DIR, "exports", "batch")
        os.makedirs(out_dir, exist_ok=True)

        progress = QProgressDialog("Exporting videos...", "Cancel", 0, len(puzzle_ids), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        exported = 0
        for i, pid in enumerate(puzzle_ids):
            if progress.wasCanceled():
                break

            puzzle = self.collection.get(pid)
            if not puzzle:
                continue

            progress.setLabelText(f"Exporting: {puzzle.name}")
            progress.setValue(i)

            cfg = copy.deepcopy(preset)
            worker = VideoExportWorker(puzzle, cfg)
            # Run synchronously in a simple way
            try:
                worker._export()
                exported += 1
            except Exception as e:
                log(f"Batch export error for {puzzle.name}: {e}", "ERROR")

            QApplication.processEvents()

        progress.setValue(len(puzzle_ids))
        QMessageBox.information(
            self, "Batch Export Complete",
            f"Exported {exported} of {len(puzzle_ids)} puzzles.\n"
            f"Saved to: {out_dir}")

    def _auto_save(self):
        """Auto-save the puzzle collection."""
        saved_path = os.path.join(DATA_DIR, "puzzles.json")
        try:
            self.collection.save_json(saved_path)
        except Exception as e:
            log(f"Auto-save failed: {e}", "ERROR")

    def _apply_settings(self):
        """Load and apply saved settings."""
        if os.path.exists(SETTINGS_PATH):
            try:
                with open(SETTINGS_PATH, 'r') as f:
                    settings = json.load(f)
                # Apply theme
                theme = settings.get('board_theme', 'Classic')
                idx = self.theme_combo.findText(theme)
                if idx >= 0:
                    self.theme_combo.setCurrentIndex(idx)
                # Apply channel name
                channel = settings.get('channel_name', '')
                if channel:
                    self.video_panel.channel_edit.setText(channel)
            except Exception:
                pass

    def _save_settings(self):
        """Save current settings."""
        settings = {
            'board_theme': self.theme_combo.currentText(),
            'channel_name': self.video_panel.channel_edit.text().strip(),
        }
        try:
            with open(SETTINGS_PATH, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception:
            pass

    def closeEvent(self, event):
        """Save state on close."""
        self._save_settings()
        self._auto_save()
        self.sound.cleanup()
        event.accept()

# ═══════════════════════════════════════════════════════════════════════════════
#  APPLICATION ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    # High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("Chess Puzzle Studio")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("ChessPuzzleStudio")

    # Apply style
    Palette.apply(app)
    app.setStyleSheet(STYLESHEET)

    # Create main window
    window = MainWindow()
    window.show()

    # Check dependencies and show info
    deps = []
    if not HAS_IMAGEIO and not HAS_FFMPEG:
        deps.append("imageio[ffmpeg] (for video export)")
    if not HAS_PANDAS:
        deps.append("pandas (for Parquet support)")

    if deps:
        QTimer.singleShot(1500, lambda: window.statusBar().showMessage(
            f"💡 Optional: pip install {' '.join(deps)}", 10000))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()