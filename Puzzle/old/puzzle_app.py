#!/usr/bin/env python3
"""
Chess Puzzle App — Modular single-file PySide6 Application

Architecture:
  DATA       → Puzzle, FilterCriteria, PuzzleIndex, PuzzleCollection
  ALGORITHM  → Trie, binary search, inverted index, filter pipeline
  DOMAIN     → ChessEngine, BoardRenderer, SoundManager, PuzzleLoader
  UI         → ChessBoardWidget, FilterPanel, MainWindow

Install:  pip install PySide6 numpy imageio[ffmpeg] chess
Optional: pip install pandas pyarrow duckdb numba cupy-cuda121
"""

from __future__ import annotations

import sys, os, math, time, csv, re, ast, base64, threading, shutil
import tempfile, wave, subprocess, json
from abc import ABC, abstractmethod
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import lru_cache, cached_property
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
    QSizePolicy, QGridLayout,
)
from PySide6.QtCore import Qt, QRect, QRectF, Signal, QTimer, QPointF, QUrl
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QRadialGradient,
    QImage, QPixmap, QPolygonF, QPainterPath, QTransform, QPalette,
)
from PySide6.QtMultimedia import QSoundEffect

csv.field_size_limit(2**31 - 1)

# ═══════════════════════════════════════════════════════════════════════════════
#  OPTIONAL DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════════

HAS_IMAGEIO = False
try:
    import imageio.v3 as iio; HAS_IMAGEIO = True
except Exception: pass

HAS_PANDAS = False
try:
    import pandas as pd; HAS_PANDAS = True
except ImportError: pass

HAS_PYARROW = False
try:
    import pyarrow.parquet as pq; HAS_PYARROW = True
except ImportError: pass

HAS_DUCKDB = False
try:
    import duckdb; HAS_DUCKDB = True
except ImportError: pass

HAS_NUMBA = False
try:
    import numba; HAS_NUMBA = True
except ImportError: pass

HAS_CUPY = False
try:
    import cupy as cp; HAS_CUPY = True
except Exception: pass

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
SETTINGS_PATH = os.path.join(APP_DIR, "puzzle_app_settings.json")

SQ_SIZE = 68
BOARD_PX = SQ_SIZE * 8
ANIM_FPS = 60
ANIM_SPEED_DEFAULT = 250

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

UCI_RE = re.compile(r'^[a-h][1-8][a-h][1-8][qrbn]?$')
MVNUM_RE = re.compile(r'^\d+\.+$')
RESULT_RE = frozenset({'1-0', '0-1', '1/2-1/2', '*'})
SAFE_FS_RE = re.compile(r'[\\/*?:"<>|]')


# ═══════════════════════════════════════════════════════════════════════════════
#  ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class SortMode(Enum):
    DEFAULT = auto()
    NAME_ASC = auto()
    NAME_DESC = auto()
    DIFFICULTY_ASC = auto()
    DIFFICULTY_DESC = auto()
    RATING_ASC = auto()
    RATING_DESC = auto()
    MOVES_ASC = auto()
    MOVES_DESC = auto()

class DifficultyTier(Enum):
    BEGINNER = (0.0, 0.2, "Beginner", "#66BB6A")
    EASY = (0.2, 0.4, "Easy", "#AED581")
    MEDIUM = (0.4, 0.6, "Medium", "#FFD54F")
    HARD = (0.6, 0.8, "Hard", "#FF8A65")
    EXPERT = (0.8, 1.01, "Expert", "#EF5350")

    def __init__(self, lo: float, hi: float, label: str, color: str):
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


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class Puzzle:
    """Immutable puzzle record — the core data unit."""
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
        """Pre-computed lowercase text for full-text search."""
        parts = [self.name, self.desc, self.opening, ' '.join(self.themes)]
        return ' '.join(parts).lower()

    @property
    def search_tokens(self) -> Tuple[str, ...]:
        """Tokenized search text for indexing."""
        text = self.search_text
        return tuple(re.findall(r'[a-z0-9]+', text))


@dataclass(frozen=True, slots=True)
class FilterCriteria:
    """Immutable filter specification — describes what to filter."""
    text_query: str = ""
    difficulty_range: Tuple[float, float] = (0.0, 1.0)
    rating_range: Tuple[int, int] = (0, 3500)
    move_count_range: Tuple[int, int] = (1, 50)
    theme_tags: FrozenSet[str] = frozenset()
    sort_mode: SortMode = SortMode.DEFAULT
    require_rating: bool = False

    @property
    def is_trivial(self) -> bool:
        """True if no filters are active (everything passes)."""
        return (
            not self.text_query
            and self.difficulty_range == (0.0, 1.0)
            and self.rating_range == (0, 3500)
            and self.move_count_range == (1, 50)
            and not self.theme_tags
            and self.sort_mode == SortMode.DEFAULT
            and not self.require_rating
        )

    @property
    def active_count(self) -> int:
        """Number of non-default filter dimensions active."""
        count = 0
        if self.text_query: count += 1
        if self.difficulty_range != (0.0, 1.0): count += 1
        if self.rating_range != (0, 3500): count += 1
        if self.move_count_range != (1, 50): count += 1
        if self.theme_tags: count += 1
        if self.sort_mode != SortMode.DEFAULT: count += 1
        if self.require_rating: count += 1
        return count


@dataclass(frozen=True, slots=True)
class MoveInfo:
    """Result of making a move on the board."""
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
    """Compressed trie for prefix-based search and autocomplete."""

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
        """Return all words with the given prefix, up to limit."""
        node = self.root
        for ch in prefix.lower():
            if ch not in node.children:
                return []
            node = node.children[ch]
        results: List[str] = []
        self._collect(node, prefix.lower(), results, limit)
        return results

    def _collect(self, node: TrieNode, prefix: str,
                 results: List[str], limit: int) -> None:
        if len(results) >= limit:
            return
        if node.is_end:
            results.append(prefix)
        for ch, child in sorted(node.children.items()):
            self._collect(child, prefix + ch, results, limit)
            if len(results) >= limit:
                return

    def has_prefix(self, prefix: str) -> bool:
        node = self.root
        for ch in prefix.lower():
            if ch not in node.children:
                return False
            node = node.children[ch]
        return True

    @property
    def size(self) -> int:
        return self._size


# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE INDEX — Inverted index + sorted arrays
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleIndex:
    """
    Pre-built index structures for O(log n) range queries and O(1) tag lookups.

    Structures:
      _tag_index:      tag → set of puzzle ids       (inverted index)
      _token_index:    token → set of puzzle ids      (full-text)
      _diff_sorted:    [(difficulty, id)] sorted       (binary search)
      _rating_sorted:  [(rating, id)] sorted           (binary search)
      _moves_sorted:   [(move_count, id)] sorted       (binary search)
      _name_sorted:    [(name_lower, id)] sorted       (binary search)
      _theme_trie:     Trie for theme autocomplete
    """

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

    def _build(self, puzzles: Sequence[Puzzle]) -> None:
        for p in puzzles:
            pid = p.id
            self._puzzles[pid] = p

            # Tag inverted index
            for tag in p.themes:
                self._tag_index[tag].add(pid)

            # Full-text token index
            for token in p.search_tokens:
                self._token_index[token].add(pid)

            # Sorted arrays for range queries
            self._diff_sorted.append((p.difficulty, pid))
            if p.rating is not None:
                self._rating_sorted.append((float(p.rating), pid))
            self._moves_sorted.append((p.move_count, pid))
            self._name_sorted.append((p.name.lower(), pid))

        # Sort all arrays
        self._diff_sorted.sort()
        self._rating_sorted.sort()
        self._moves_sorted.sort()
        self._name_sorted.sort()

        # Build theme trie
        for tag in self._tag_index:
            self._theme_trie.insert(tag)

    # ── Point lookups ──

    def get(self, pid: int) -> Optional[Puzzle]:
        return self._puzzles.get(pid)

    def __len__(self) -> int:
        return len(self._puzzles)

    def __contains__(self, pid: int) -> bool:
        return pid in self._puzzles

    @property
    def all_ids(self) -> Set[int]:
        return set(self._puzzles.keys())

    @property
    def all_themes(self) -> List[str]:
        return sorted(self._tag_index.keys())

    @property
    def theme_trie(self) -> Trie:
        return self._theme_trie

    # ── Range queries via binary search ──

    def ids_in_difficulty_range(self, lo: float, hi: float) -> Set[int]:
        """O(log n + k) difficulty range query."""
        arr = self._diff_sorted
        left = bisect_left(arr, (lo, -1))
        right = bisect_right(arr, (hi, float('inf')))
        return {arr[i][1] for i in range(left, right)}

    def ids_in_rating_range(self, lo: int, hi: int) -> Set[int]:
        """O(log n + k) rating range query."""
        arr = self._rating_sorted
        left = bisect_left(arr, (float(lo), -1))
        right = bisect_right(arr, (float(hi), float('inf')))
        return {arr[i][1] for i in range(left, right)}

    def ids_in_move_range(self, lo: int, hi: int) -> Set[int]:
        """O(log n + k) move count range query."""
        arr = self._moves_sorted
        left = bisect_left(arr, (lo, -1))
        right = bisect_right(arr, (hi, 0x7FFFFFFF))
        return {arr[i][1] for i in range(left, right)}

    # ── Tag lookup ──

    def ids_with_tag(self, tag: str) -> Set[int]:
        """O(1) tag lookup via inverted index."""
        return self._tag_index.get(tag.lower(), set())

    def ids_with_any_tag(self, tags: Iterable[str]) -> Set[int]:
        """Union of all ids matching any of the given tags."""
        result: Set[int] = set()
        for tag in tags:
            result |= self.ids_with_tag(tag)
        return result

    # ── Full-text search ──

    def ids_matching_text(self, query: str) -> Set[int]:
        """Tokenized full-text search — all tokens must match (AND)."""
        tokens = re.findall(r'[a-z0-9]+', query.lower())
        if not tokens:
            return self.all_ids
        # Start with least common token for efficiency
        token_sets = []
        for t in tokens:
            s = self._token_index.get(t, set())
            if not s:
                return set()  # Early exit if any token matches nothing
            token_sets.append(s)
        token_sets.sort(key=len)  # Process rarest first
        result = token_sets[0].copy()
        for s in token_sets[1:]:
            result &= s
            if not result:
                return set()
        return result

    # ── Combined filter pipeline ──

    def filter(self, criteria: FilterCriteria) -> List[int]:
        """
        Multi-predicate filter using set intersection.
        Applies most selective filters first for early pruning.
        Returns sorted list of puzzle IDs.
        """
        if criteria.is_trivial:
            return sorted(self._puzzles.keys())

        # Build candidate sets for each active filter
        candidates: List[Set[int]] = []

        # Text search — typically most selective
        if criteria.text_query:
            candidates.append(self.ids_matching_text(criteria.text_query))

        # Difficulty range
        if criteria.difficulty_range != (0.0, 1.0):
            candidates.append(
                self.ids_in_difficulty_range(*criteria.difficulty_range))

        # Rating range
        if criteria.rating_range != (0, 3500) or criteria.require_rating:
            lo, hi = criteria.rating_range
            rated = self.ids_in_rating_range(lo, hi)
            if criteria.require_rating:
                # Exclude puzzles without a rating
                rated &= {pid for pid, p in self._puzzles.items()
                          if p.rating is not None}
            candidates.append(rated)

        # Move count range
        if criteria.move_count_range != (1, 50):
            candidates.append(
                self.ids_in_move_range(*criteria.move_count_range))

        # Theme tags (OR semantics — match any)
        if criteria.theme_tags:
            candidates.append(self.ids_with_any_tag(criteria.theme_tags))

        # Intersect all candidate sets, smallest first
        if not candidates:
            result = self.all_ids
        else:
            candidates.sort(key=len)
            result = candidates[0]
            for s in candidates[1:]:
                result = result & s
                if not result:
                    return []

        # Sort results
        return self._sort(result, criteria.sort_mode)

    def _sort(self, ids: Set[int], mode: SortMode) -> List[int]:
        """Sort filtered IDs by the given mode."""
        if mode == SortMode.DEFAULT:
            return sorted(ids)

        key_fn: Callable[[int], Any]
        reverse = False

        if mode == SortMode.NAME_ASC:
            key_fn = lambda pid: self._puzzles[pid].name.lower()
        elif mode == SortMode.NAME_DESC:
            key_fn = lambda pid: self._puzzles[pid].name.lower()
            reverse = True
        elif mode == SortMode.DIFFICULTY_ASC:
            key_fn = lambda pid: self._puzzles[pid].difficulty
        elif mode == SortMode.DIFFICULTY_DESC:
            key_fn = lambda pid: self._puzzles[pid].difficulty
            reverse = True
        elif mode == SortMode.RATING_ASC:
            key_fn = lambda pid: self._puzzles[pid].rating or 0
        elif mode == SortMode.RATING_DESC:
            key_fn = lambda pid: self._puzzles[pid].rating or 0
            reverse = True
        elif mode == SortMode.MOVES_ASC:
            key_fn = lambda pid: self._puzzles[pid].move_count
        elif mode == SortMode.MOVES_DESC:
            key_fn = lambda pid: self._puzzles[pid].move_count
            reverse = True
        else:
            return sorted(ids)

        return sorted(ids, key=key_fn, reverse=reverse)


# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE COLLECTION — High-level data manager
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleCollection:
    """
    Manages a collection of puzzles with an efficient index.
    Provides filtering, sorting, and CRUD operations.
    """

    def __init__(self) -> None:
        self._puzzles: List[Puzzle] = []
        self._index: Optional[PuzzleIndex] = None
        self._next_id: int = 0

    @property
    def index(self) -> Optional[PuzzleIndex]:
        return self._index

    @property
    def puzzles(self) -> List[Puzzle]:
        return self._puzzles

    @property
    def count(self) -> int:
        return len(self._puzzles)

    def add(self, puzzle: Puzzle) -> None:
        self._puzzles.append(puzzle)
        self._next_id = max(self._next_id, puzzle.id + 1)

    def add_many(self, puzzles: Sequence[Puzzle]) -> None:
        for p in puzzles:
            self._puzzles.append(p)
            self._next_id = max(self._next_id, p.id + 1)

    def build_index(self) -> None:
        """Build search index — call after adding all puzzles."""
        self._index = PuzzleIndex(self._puzzles)
        log(f"Index built: {len(self._puzzles)} puzzles, "
            f"{len(self._index.all_themes)} themes", "INDEX")

    def filter(self, criteria: FilterCriteria) -> List[int]:
        """Filter using the index. Returns puzzle IDs."""
        if self._index is None:
            self.build_index()
        return self._index.filter(criteria)

    def get(self, pid: int) -> Optional[Puzzle]:
        if self._index:
            return self._index.get(pid)
        for p in self._puzzles:
            if p.id == pid:
                return p
        return None

    def clear(self) -> None:
        self._puzzles.clear()
        self._index = None
        self._next_id = 0

    def next_id(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid


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
    "Blue": BoardTheme("Blue", (208, 224, 243), (116, 150, 194),
                       border=(40, 50, 70)),
    "Green": BoardTheme("Green", (238, 238, 210), (118, 150, 86),
                        border=(50, 60, 40)),
    "Brown": BoardTheme("Brown", (222, 197, 165), (170, 120, 70),
                        border=(60, 35, 15)),
    "Ice": BoardTheme("Ice", (230, 240, 250), (160, 190, 220),
                      border=(50, 60, 80)),
}


# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT PRESETS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class ExportPreset:
    name: str
    width: int
    height: int
    fps: int = 30
    board_frac: float = 0.82
    bg: Tuple[int, int, int] = (250, 250, 250)
    description: str = ""

    def calc_sq_size(self) -> int:
        shorter = min(self.width, self.height)
        bpx = (int(shorter * self.board_frac) // 8) * 8
        return max(8, bpx // 8)

    def calc_board_rect(self) -> Tuple[int, int, int, int]:
        sq = self.calc_sq_size(); bw = sq * 8; bh = sq * 8
        return (self.width - bw) // 2, (self.height - bh) // 2, bw, bh


EXPORT_PRESETS: Dict[str, ExportPreset] = {
    "Board Only (544×544)": ExportPreset("Board Only", 544, 544, 30, 1.0),
    "YouTube 1080p": ExportPreset("YouTube 1080p", 1920, 1080, 30, 0.78),
    "YouTube Shorts": ExportPreset("YouTube Shorts", 1080, 1920, 30, 0.50),
    "TikTok": ExportPreset("TikTok", 1080, 1920, 30, 0.50),
    "Instagram Square": ExportPreset("Instagram Square", 1080, 1080, 30, 0.82),
    "Custom": ExportPreset("Custom", 544, 544, 30, 0.82),
}


# ═══════════════════════════════════════════════════════════════════════════════
#  MINIMALIST COLOR SCHEME
# ═══════════════════════════════════════════════════════════════════════════════

class Palette:
    BG = "#FAFAFA"; BG2 = "#F5F5F5"; BG3 = "#EEEEEE"; CARD = "#FFFFFF"
    TEXT = "#1A1A1A"; TEXT2 = "#757575"; TEXT3 = "#BDBDBD"; INV = "#FFFFFF"
    ACCENT = "#2D7D9A"; ACCENT_H = "#23697F"; ACCENT_L = "#E0F0F5"
    BORDER = "#E0E0E0"; BORDER_L = "#F0F0F0"
    ERROR = "#E53935"; SUCCESS = "#4CAF50"

    @classmethod
    def apply(cls, app: QApplication) -> None:
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
    padding:6px 14px; color:#1A1A1A; font-weight:500; }
QPushButton:hover { background:#F5F5F5; border-color:#BDBDBD; }
QPushButton:pressed { background:#EEE; }
QPushButton[accent="true"] { background:#2D7D9A; color:#FFF; border:1px solid #23697F; }
QPushButton[accent="true"]:hover { background:#23697F; }
QLineEdit { background:#FFF; border:1px solid #E0E0E0; border-radius:6px;
    padding:6px 10px; selection-background-color:#2D7D9A; selection-color:#FFF; }
QLineEdit:focus { border-color:#2D7D9A; }
QComboBox { background:#FFF; border:1px solid #E0E0E0; border-radius:6px; padding:5px 10px; }
QSpinBox { background:#FFF; border:1px solid #E0E0E0; border-radius:6px; padding:4px 8px; }
QSlider::groove:horizontal { height:4px; background:#E0E0E0; border-radius:2px; }
QSlider::handle:horizontal { background:#2D7D9A; width:14px; height:14px;
    margin:-5px 0; border-radius:7px; }
QSlider::sub-page:horizontal { background:#2D7D9A; border-radius:2px; }
QListWidget { background:#FFF; border:1px solid #E0E0E0; border-radius:6px;
    outline:none; padding:2px; }
QListWidget::item { padding:8px 10px; border-bottom:1px solid #F5F5F5; border-radius:4px; }
QListWidget::item:selected { background:#E0F0F5; color:#1A1A1A; }
QListWidget::item:hover { background:#F5F5F5; }
QTextEdit { background:#FFF; border:1px solid #E0E0E0; border-radius:6px; padding:6px; }
QTabWidget::pane { border:1px solid #E0E0E0; border-radius:6px; background:#FFF; }
QTabBar::tab { background:#F5F5F5; border:1px solid #E0E0E0; border-bottom:none;
    border-top-left-radius:6px; border-top-right-radius:6px;
    padding:7px 16px; margin-right:2px; color:#757575; font-weight:500; }
QTabBar::tab:selected { background:#FFF; color:#2D7D9A; border-bottom:2px solid #2D7D9A; }
QProgressBar { border:1px solid #E0E0E0; border-radius:4px; text-align:center;
    background:#F5F5F5; height:18px; color:#757575; font-size:11px; }
QProgressBar::chunk { background:#2D7D9A; border-radius:3px; }
QCheckBox { spacing:8px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #BDBDBD;
    border-radius:4px; background:#FFF; }
QCheckBox::indicator:checked { background:#2D7D9A; border-color:#2D7D9A; }
QGroupBox { border:1px solid #E0E0E0; border-radius:6px; margin-top:12px;
    padding-top:16px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; color:#2D7D9A; }
QStatusBar { background:#FFF; border-top:1px solid #E0E0E0; color:#757575;
    font-size:12px; padding:4px 8px; }
QToolTip { background:#1A1A1A; color:#FFF; border:none; border-radius:4px;
    padding:6px 10px; font-size:12px; }
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  CHESS ENGINE — Domain logic
# ═══════════════════════════════════════════════════════════════════════════════

class ChessEngine:
    """Wraps python-chess Board with row/col coordinate helpers."""

    def __init__(self) -> None:
        self.board = chess.Board()
        self.game_over = False
        self.result = ""
        self.last_move: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None
        self.initial_fen: Optional[str] = None

    def reset(self) -> None:
        self.board.reset(); self.game_over = False
        self.result = ""; self.last_move = None; self.initial_fen = None

    def reset_to_initial(self) -> None:
        if self.initial_fen:
            self.load_fen(self.initial_fen)
        else:
            self.reset()

    @staticmethod
    def sq_to_rc(sq: int) -> Tuple[int, int]:
        return 7 - chess.square_rank(sq), chess.square_file(sq)

    @staticmethod
    def rc_to_sq(r: int, c: int) -> int:
        return chess.square(c, 7 - r)

    @property
    def turn(self) -> str:
        return 'w' if self.board.turn == chess.WHITE else 'b'

    def check_squares(self) -> List[Tuple[int, int]]:
        if self.board.is_check():
            return [self.sq_to_rc(self.board.king(self.board.turn))]
        return []

    def legal_targets(self, r: int, c: int) -> List[Tuple[int, int]]:
        sq = self.rc_to_sq(r, c)
        return [self.sq_to_rc(m.to_square) for m in self.board.legal_moves
                if m.from_square == sq]

    def is_promotion(self, fr: int, fc: int, tr: int, tc: int) -> bool:
        from_sq = self.rc_to_sq(fr, fc)
        piece = self.board.piece_at(from_sq)
        if piece and piece.piece_type == chess.PAWN:
            if (piece.color == chess.WHITE and tr == 0) or \
               (piece.color == chess.BLACK and tr == 7):
                return True
        return False

    def make_move(self, fr: int, fc: int, tr: int, tc: int,
                  promo: Optional[int] = None) -> Optional[MoveInfo]:
        from_sq = self.rc_to_sq(fr, fc)
        to_sq = self.rc_to_sq(tr, tc)
        piece = self.board.piece_at(from_sq)
        if not piece:
            return None

        promotion = None
        if piece.piece_type == chess.PAWN:
            if (piece.color == chess.WHITE and tr == 0) or \
               (piece.color == chess.BLACK and tr == 7):
                promotion = promo if promo else chess.QUEEN

        move = chess.Move(from_sq, to_sq, promotion=promotion)
        if move not in self.board.legal_moves:
            return None

        is_castle = self.board.is_castling(move)
        is_ep = self.board.is_en_passant(move)
        if is_ep:
            ep_sq = chess.square(chess.square_file(to_sq),
                                 chess.square_rank(from_sq))
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

        return MoveInfo(
            from_rc=(fr, fc), to_rc=(tr, tc), piece_symbol=piece.symbol(),
            piece_obj=piece_obj, captured=captured, is_castle=is_castle,
            is_ep=is_ep, promo=promo, is_check=self.board.is_check(),
            is_mate=self.board.is_checkmate(), notation=notation,
        )

    def make_move_uci(self, uci_str: str) -> Optional[MoveInfo]:
        move = chess.Move.from_uci(uci_str)
        if move in self.board.legal_moves:
            fr, fc = self.sq_to_rc(move.from_square)
            tr, tc = self.sq_to_rc(move.to_square)
            promo = move.promotion
            return self.make_move(fr, fc, tr, tc, promo)
        return None

    def undo(self) -> bool:
        if self.board.move_stack:
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

    def load_fen(self, fen: str) -> bool:
        try:
            self.board.set_fen(fen)
        except ValueError:
            log(f"Invalid FEN: {fen}", "ERROR")
            return False
        self.game_over = self.board.is_game_over()
        self.result = self.board.result() if self.game_over else ""
        self.last_move = None
        self.initial_fen = fen
        return True


# ═══════════════════════════════════════════════════════════════════════════════
#  SOUND MANAGER — Procedural audio
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

    def _generate(self) -> None:
        sr = 44100; d = self._tmpdir
        self._to_wav(os.path.join(d, "move.wav"),
                     self._envelope(self._tone(800, 0.06)))
        self._to_wav(os.path.join(d, "capture.wav"),
                     self._envelope(self._tone(300, 0.10, 0.5) +
                                    self._tone(600, 0.08, 0.3)))
        self._to_wav(os.path.join(d, "check.wav"),
                     self._envelope(self._tone(1000, 0.12, 0.5) +
                                    self._tone(1250, 0.10, 0.3)))
        self._to_wav(os.path.join(d, "checkmate.wav"),
                     self._envelope(np.concatenate([
                         self._tone(800, 0.15, 0.5),
                         self._tone(600, 0.15, 0.5),
                         self._tone(400, 0.25, 0.5)]), 0.01, 0.08))
        self._to_wav(os.path.join(d, "castle.wav"),
                     self._envelope(self._tone(400, 0.15) * 0.4 +
                                    self._tone(800, 0.15, 0.3)))
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
#  BOARD RENDERER — Pure rendering, no widget dependency
# ═══════════════════════════════════════════════════════════════════════════════

class BoardRenderer:
    """Stateless board rendering — produces QImage frames."""

    _thread_local = threading.local()

    @staticmethod
    def _assets(sz: int):
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
    def render(board: chess.Board,
               last_move: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None,
               selected: Optional[Tuple[int, int]] = None,
               legal_targets: Optional[List[Tuple[int, int]]] = None,
               check_squares: Optional[List[Tuple[int, int]]] = None,
               anim_state: Optional[Dict] = None,
               sq_size: int = SQ_SIZE,
               theme: BoardTheme = THEMES["Minimal"],
               flipped: bool = False,
               text_overlay: str = "") -> QImage:
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
            skip_sq.add(anim_state['from'])
            skip_sq.add(anim_state['to'])

        def src(r: int, c: int) -> Tuple[int, int]:
            return (7 - r, 7 - c) if flipped else (r, c)

        # Squares
        for sq in chess.SQUARES:
            r, c = 7 - chess.square_rank(sq), chess.square_file(sq)
            sr, sc = src(r, c)
            x, y = sc * sz, sr * sz
            is_light = (r + c) % 2 == 0
            p.fillRect(x, y, sz, sz,
                       theme.qcolor('light_sq' if is_light else 'dark_sq'))
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
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(0, 0, 0, 60))
                    p.drawEllipse(cx - sz // 6, cy - sz // 6, sz // 3, sz // 3)

        # Arrow
        if last_move:
            (fr, fc), (tr, tc) = last_move
            sfr, sfc = src(fr, fc); str_, stc = src(tr, tc)
            BoardRenderer._draw_arrow(
                p, sfc * sz + sz // 2, sfr * sz + sz // 2,
                stc * sz + sz // 2, str_ * sz + sz // 2,
                theme.qcolor('arrow'), sz)

        # Pieces (skip animated squares)
        for sq in chess.SQUARES:
            r, c = 7 - chess.square_rank(sq), chess.square_file(sq)
            if (r, c) in skip_sq:
                continue
            piece = board.piece_at(sq)
            if piece:
                sr, sc = src(r, c)
                BoardRenderer._draw_piece(p, piece, sr, sc, sz, font_piece)

        # Captured piece fade
        if anim_state and anim_state.get('captured', '.') != '.':
            tr, tc_ = anim_state['to']
            sr, sc = src(tr, tc_)
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

        # Animated piece
        if anim_state and anim_state.get('piece_obj'):
            fr, fc_ = anim_state['from']; tr, tc_ = anim_state['to']
            t = anim_state['progress']
            obj = anim_state['piece_obj']
            ir = fr + (tr - fr) * t; ic = fc_ + (tc_ - fc_) * t
            if flipped:
                scr_ir_f = 7 - ir; scr_ic_f = 7 - ic
            else:
                scr_ir_f = ir; scr_ic_f = ic
            lift = 4.0 * t * (1.0 - t) * 0.15
            scale = 1.0 + 4.0 * t * (1.0 - t) * 0.08
            shadow_alpha = 30 + int(70 * max(0, lift / 0.15))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, shadow_alpha))
            sy = scr_ir_f * sz + sz * 0.82
            p.drawEllipse(QRectF(scr_ic_f * sz + (sz * scale - sz * 0.65) / 2,
                                 sy, sz * 0.65, sz * 0.12))
            y_lift = scr_ir_f * sz - (sz * lift)
            BoardRenderer._draw_piece_at(
                p, obj, y_lift / sz, scr_ic_f, sz,
                sz * scale, sz * scale, font_piece)

        # Coordinates
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

        # Text overlay
        if text_overlay:
            p.fillRect(0, sz * 4 - 28, sz * 8, 56, QColor(0, 0, 0, 160))
            p.setPen(Qt.white)
            p.setFont(QFont("Sans", max(12, sz // 4), QFont.Bold))
            p.drawText(QRect(0, sz * 4 - 28, sz * 8, 56),
                       Qt.AlignCenter, text_overlay)

        p.end()
        return img

    @staticmethod
    def render_card(text: str, w: int = 544, h: int = 544,
                    font_size: int = 36, sub: str = "",
                    bg: str = "#FAFAFA", fg: str = "#1A1A1A") -> QImage:
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(bg))
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(fg)); p.setFont(QFont("Sans", font_size, QFont.Bold))
        p.drawText(QRect(0, 0, w, h), Qt.AlignCenter, text)
        if sub:
            p.setFont(QFont("Sans", max(10, font_size // 2)))
            p.setPen(QColor(fg).lighter(140))
            p.drawText(QRect(0, h * 3 // 5, w, h // 4),
                       Qt.AlignCenter, sub)
        p.end(); return img

    # ── Private helpers ──

    @staticmethod
    def _draw_piece(p: QPainter, piece: chess.Piece,
                    row: int, col: int, sz: int, font: QFont) -> None:
        BoardRenderer._draw_piece_at(
            p, piece, float(row), float(col), sz, sz, sz, font)

    @staticmethod
    def _draw_piece_at(p: QPainter, piece: chess.Piece,
                       row_f: float, col_f: float,
                       sz: int, w: float, h: float,
                       font: QFont) -> None:
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
    def _draw_arrow(p: QPainter, fx: float, fy: float,
                    tx: float, ty: float, color: QColor, sz: int) -> None:
        dx = tx - fx; dy = ty - fy; dist = max(1, math.hypot(dx, dy))
        m = sz * 0.22
        fx2 = fx + dx * m / dist; fy2 = fy + dy * m / dist
        tx2 = tx - dx * m / dist; ty2 = ty - dy * m / dist
        p.setPen(QPen(color, max(2, sz // 20), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(int(fx2), int(fy2), int(tx2), int(ty2))
        angle = math.atan2(dy, dx); a = sz * 0.22
        tri = QPolygonF([
            QPointF(tx2, ty2),
            QPointF(tx2 - a * math.cos(angle - 0.45),
                    ty2 - a * math.sin(angle - 0.45)),
            QPointF(tx2 - a * math.cos(angle + 0.45),
                    ty2 - a * math.sin(angle + 0.45))])
        p.setBrush(color); p.setPen(Qt.NoPen); p.drawPolygon(tri)

    @staticmethod
    def to_numpy(img: QImage) -> np.ndarray:
        if img.isNull():
            return np.zeros((1, 1, 3), dtype=np.uint8)
        img2 = img.convertToFormat(QImage.Format_RGB888)
        ptr = img2.constBits()
        if hasattr(ptr, 'setsize'):
            ptr.setsize(img2.sizeInBytes())
        w, h, bpl = img2.width(), img2.height(), img2.bytesPerLine()
        raw = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl)).copy()
        needed = w * 3
        if bpl == needed:
            return raw.reshape((h, w, 3))
        if bpl > needed:
            return raw[:, :needed].reshape((h, w, 3))
        out = np.zeros((h, needed), dtype=np.uint8)
        for i in range(h):
            out[i, :min(bpl, needed)] = raw[i, :min(bpl, needed)]
        return out.reshape((h, w, 3))


# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE LOADER — Strategy pattern per format
# ═══════════════════════════════════════════════════════════════════════════════

class BaseLoader(ABC):
    """Abstract puzzle file loader."""

    @abstractmethod
    def can_load(self, path: str) -> bool: ...

    @abstractmethod
    def load(self, path: str) -> List[Dict[str, Any]]: ...


class CsvLoader(BaseLoader):
    def can_load(self, path: str) -> bool:
        return path.lower().endswith('.csv')

    def load(self, path: str) -> List[Dict[str, Any]]:
        rows = []
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                for row in csv.DictReader(f):
                    rows.append(row)
        except Exception as e:
            log(f"CSV error: {e}", "ERROR")
        return rows


class ParquetLoader(BaseLoader):
    def can_load(self, path: str) -> bool:
        return path.lower().endswith(('.parquet', '.pq'))

    def load(self, path: str) -> List[Dict[str, Any]]:
        if HAS_PANDAS:
            return pd.read_parquet(path).to_dict('records')
        if HAS_PYARROW:
            return pq.read_table(path).to_pandas().to_dict('records')
        if HAS_DUCKDB:
            r = duckdb.query(f"SELECT * FROM '{path}'")
            cols = [c[0] for c in r.description]
            return [dict(zip(cols, row)) for row in r.fetchall()]
        log("No Parquet reader available", "ERROR")
        return []


class JsonLoader(BaseLoader):
    def can_load(self, path: str) -> bool:
        return path.lower().endswith(('.json', '.jsonl'))

    def load(self, path: str) -> List[Dict[str, Any]]:
        if path.lower().endswith('.jsonl'):
            rows = []
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            return rows
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                if 'puzzles' in data:
                    return data['puzzles']
                return [data]
        except Exception as e:
            log(f"JSON error: {e}", "ERROR")
        return []


class PgnLoader(BaseLoader):
    """Load puzzles from PGN files (one game per puzzle)."""

    def can_load(self, path: str) -> bool:
        return path.lower().endswith('.pgn')

    def load(self, path: str) -> List[Dict[str, Any]]:
        rows = []
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                while True:
                    game = chess.pgn.read_game(f)
                    if game is None:
                        break
                    headers = dict(game.headers)
                    board = game.board()
                    moves_uci = []
                    for move in game.mainline_moves():
                        moves_uci.append(move.uci())
                    fen = board.fen()
                    rows.append({
                        'FEN': fen,
                        'Moves': ' '.join(moves_uci),
                        'Name': headers.get('Event', headers.get('White', 'PGN Game')),
                        'Themes': headers.get('Opening', ''),
                        'Rating': headers.get('WhiteElo', ''),
                    })
        except Exception as e:
            log(f"PGN error: {e}", "ERROR")
        return rows


class PuzzleLoader:
    """
    Factory / dispatcher: picks the right loader and normalizes rows
    into Puzzle objects. Handles various CSV schemas (Lichess, custom, etc.).
    """

    LOADERS: List[BaseLoader] = [CsvLoader(), ParquetLoader(),
                                  JsonLoader(), PgnLoader()]

    # Known column-name mappings for common schemas
    _COL_MAPS: List[Dict[str, str]] = [
        # Lichess puzzle CSV
        {'PuzzleId': 'id', 'FEN': 'fen', 'Moves': 'moves',
         'Rating': 'rating', 'Themes': 'themes', 'Opening': 'opening',
         'GameUrl': 'url', 'Popularity': 'popularity', 'NbPlays': 'nbplays'},
        # Generic
        {'puzzle_id': 'id', 'fen': 'fen', 'moves': 'moves',
         'rating': 'rating', 'themes': 'themes', 'opening': 'opening',
         'name': 'name', 'description': 'desc', 'difficulty': 'difficulty',
         'eco': 'eco'},
    ]

    @classmethod
    def load_file(cls, path: str) -> List[Puzzle]:
        """Load a puzzle file, auto-detect format, return Puzzle list."""
        for loader in cls.LOADERS:
            if loader.can_load(path):
                rows = loader.load(path)
                return cls._normalize(rows, path)
        log(f"No loader for: {path}", "WARN")
        return []

    @classmethod
    def _normalize(cls, rows: List[Dict[str, Any]],
                   source: str = "") -> List[Puzzle]:
        """Convert raw dicts to Puzzle objects, handling varied schemas."""
        puzzles: List[Puzzle] = []
        for i, row in enumerate(rows):
            try:
                puzzle = cls._row_to_puzzle(row, i, source)
                if puzzle:
                    puzzles.append(puzzle)
            except Exception as e:
                if i < 5:
                    log(f"Row {i} parse error: {e}", "WARN")
        log(f"Loaded {len(puzzles)} puzzles from {source}", "LOAD")
        return puzzles

    @classmethod
    def _row_to_puzzle(cls, row: Dict[str, Any], idx: int,
                       source: str) -> Optional[Puzzle]:
        # Try to extract fields with flexible key matching
        def get(keys: List[str], default: Any = "") -> Any:
            for k in keys:
                if k in row:
                    return row[k]
                kl = k.lower()
                for rk, rv in row.items():
                    if rk.lower() == kl:
                        return rv
            return default

        # ID
        pid = get(['PuzzleId', 'puzzle_id', 'id', 'ID'])
        if pid == "":
            pid = idx
        try:
            pid = int(pid)
        except (ValueError, TypeError):
            pid = idx

        # FEN
        fen = str(get(['FEN', 'fen', 'position', 'start_fen'], ""))
        if not fen:
            fen = chess.STARTING_FEN

        # Moves
        moves_raw = str(get(['Moves', 'moves', 'move_list', 'uci'], ""))
        moves = cls._parse_moves(moves_raw)
        if not moves:
            return None

        # Name
        name = str(get(['Name', 'name', 'Title', 'title', 'Event',
                        'puzzle_name'], ""))
        if not name:
            name = f"Puzzle #{pid}"

        # Description
        desc = str(get(['Description', 'desc', 'description',
                        'comment', 'text'], ""))

        # Rating
        rating_raw = get(['Rating', 'rating', 'RatingDeviation',
                          'elo', 'puzzle_rating'], None)
        rating = None
        if rating_raw is not None:
            try:
                rating = int(float(str(rating_raw)))
            except (ValueError, TypeError):
                pass

        # Themes
        themes_raw = str(get(['Themes', 'themes', 'tags', 'tags_list'], ""))
        if themes_raw:
            themes = frozenset(t.strip() for t in re.split(r'[\s,;]+', themes_raw)
                               if t.strip())
        else:
            themes = frozenset()

        # Opening
        opening = str(get(['Opening', 'opening', 'OpeningTags',
                           'opening_name'], ""))

        # ECO
        eco = str(get(['ECO', 'eco'], ""))

        # Difficulty: derive from rating if not explicit
        diff_raw = get(['difficulty', 'Difficulty', 'difficulty_score'], None)
        if diff_raw is not None:
            try:
                difficulty = float(diff_raw)
                difficulty = max(0.0, min(1.0, difficulty))
            except (ValueError, TypeError):
                difficulty = cls._rating_to_difficulty(rating)
        else:
            difficulty = cls._rating_to_difficulty(rating)

        move_count = len(moves)

        return Puzzle(
            id=pid, name=name, fen=fen, moves=tuple(moves),
            desc=desc, difficulty=difficulty, themes=themes,
            rating=rating, move_count=move_count,
            opening=opening, eco=eco, raw_row=row,
        )

    @staticmethod
    def _parse_moves(raw: str) -> List[str]:
        """Parse a UCI move string, handling various formats."""
        if not raw:
            return []
        tokens = raw.strip().split()
        moves = []
        for t in tokens:
            # Skip move numbers like "1." or "1..."
            if MVNUM_RE.match(t):
                continue
            # Skip results
            if t in RESULT_RE:
                continue
            # Validate UCI format
            if UCI_RE.match(t):
                moves.append(t)
            else:
                # Try to parse as SAN — skip for now
                pass
        return moves

    @staticmethod
    def _rating_to_difficulty(rating: Optional[int]) -> float:
        """Map rating to 0.0–1.0 difficulty score."""
        if rating is None:
            return 0.5
        return max(0.0, min(1.0, (rating - 400) / 2800))


# ═══════════════════════════════════════════════════════════════════════════════
#  SETTINGS MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class Settings:
    """Persistent application settings via JSON."""

    _DEFAULTS: Dict[str, Any] = {
        'theme': 'Minimal',
        'flipped': False,
        'sound_enabled': True,
        'sound_volume': 0.7,
        'anim_speed': ANIM_SPEED_DEFAULT,
        'last_file': '',
        'window_geometry': '',
        'export_preset': 'Board Only (544×544)',
    }

    def __init__(self) -> None:
        self._data: Dict[str, Any] = dict(self._DEFAULTS)
        self.load()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def load(self) -> None:
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                self._data.update(saved)
        except Exception as e:
            log(f"Settings load error: {e}", "WARN")

    def save(self) -> None:
        try:
            with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log(f"Settings save error: {e}", "WARN")


# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORTER — GIF / Video export
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleExporter:
    """Exports a puzzle as an animated GIF or MP4."""

    @staticmethod
    def render_frames(puzzle: Puzzle,
                      sq_size: int = SQ_SIZE,
                      theme: BoardTheme = THEMES["Minimal"],
                      flipped: bool = False,
                      anim_speed: int = ANIM_SPEED_DEFAULT,
                      pause_start: float = 1.0,
                      pause_end: float = 2.0,
                      fps: int = 30,
                      progress_cb: Optional[Callable[[float], None]] = None,
                      ) -> List[np.ndarray]:
        """Render all frames for a puzzle animation."""
        engine = ChessEngine()
        engine.load_fen(puzzle.fen)
        frames: List[np.ndarray] = []

        # Start pause
        start_img = BoardRenderer.render(
            engine.board, theme=theme, sq_size=sq_size, flipped=flipped,
            text_overlay=f"{puzzle.name}")
        for _ in range(int(pause_start * fps)):
            frames.append(BoardRenderer.to_numpy(start_img))

        total_moves = len(puzzle.moves)
        for mi, uci in enumerate(puzzle.moves):
            info = engine.make_move_uci(uci)
            if info is None:
                log(f"Bad move {uci} in puzzle {puzzle.id}", "WARN")
                continue

            # Animation frames
            n_anim = max(1, int((anim_speed / 1000.0) * fps))
            for fi in range(n_anim):
                t = (fi + 1) / n_anim
                anim = {
                    'from': info.from_rc, 'to': info.to_rc,
                    'piece_obj': info.piece_obj,
                    'captured': info.captured,
                    'progress': t,
                }
                # Render with anim: show board BEFORE this move
                tmp_engine = ChessEngine()
                tmp_engine.load_fen(puzzle.fen)
                for prev_uci in puzzle.moves[:mi]:
                    tmp_engine.make_move_uci(prev_uci)

                img = BoardRenderer.render(
                    tmp_engine.board,
                    last_move=tmp_engine.last_move,
                    check_squares=tmp_engine.check_squares(),
                    anim_state=anim,
                    sq_size=sq_size, theme=theme, flipped=flipped,
                )
                frames.append(BoardRenderer.to_numpy(img))

            # Still frame after move
            overlay = ""
            if info.is_mate:
                overlay = "CHECKMATE"
            elif info.is_check:
                overlay = "CHECK"

            still_img = BoardRenderer.render(
                engine.board,
                last_move=engine.last_move,
                check_squares=engine.check_squares(),
                sq_size=sq_size, theme=theme, flipped=flipped,
                text_overlay=overlay,
            )
            frames.append(BoardRenderer.to_numpy(still_img))

            # Brief pause between moves
            if mi < total_moves - 1:
                for _ in range(max(1, int(0.3 * fps))):
                    frames.append(BoardRenderer.to_numpy(still_img))

            if progress_cb:
                progress_cb((mi + 1) / total_moves)

        # End pause
        end_img = BoardRenderer.render(
            engine.board,
            last_move=engine.last_move,
            sq_size=sq_size, theme=theme, flipped=flipped,
            text_overlay=puzzle.tier_label if engine.game_over else "")
        for _ in range(int(pause_end * fps)):
            frames.append(BoardRenderer.to_numpy(end_img))

        return frames

    @staticmethod
    def export_gif(puzzle: Puzzle, path: str,
                   sq_size: int = SQ_SIZE,
                   theme: BoardTheme = THEMES["Minimal"],
                   flipped: bool = False,
                   fps: int = 15,
                   progress_cb: Optional[Callable[[float], None]] = None,
                   ) -> bool:
        if not HAS_IMAGEIO:
            log("imageio not available for GIF export", "ERROR")
            return False
        try:
            frames = PuzzleExporter.render_frames(
                puzzle, sq_size=sq_size, theme=theme, flipped=flipped,
                fps=fps, progress_cb=progress_cb)
            # Downsample for GIF (lower fps)
            step = max(1, len(frames) // (len(frames) * fps // 30))
            sampled = frames[::step]
            iio.imwrite(path, sampled, duration=int(1000 / fps),
                        loop=0)
            log(f"GIF saved: {path} ({len(sampled)} frames)", "EXPORT")
            return True
        except Exception as e:
            log(f"GIF export error: {e}", "ERROR")
            return False

    @staticmethod
    def export_video(puzzle: Puzzle, path: str,
                     preset: ExportPreset = EXPORT_PRESETS["Board Only (544×544)"],
                     theme: BoardTheme = THEMES["Minimal"],
                     flipped: bool = False,
                     anim_speed: int = ANIM_SPEED_DEFAULT,
                     progress_cb: Optional[Callable[[float], None]] = None,
                     ) -> bool:
        sq_size = preset.calc_sq_size()
        try:
            frames = PuzzleExporter.render_frames(
                puzzle, sq_size=sq_size, theme=theme, flipped=flipped,
                anim_speed=anim_speed, fps=preset.fps,
                progress_cb=progress_cb)

            if not frames:
                return False

            # Compose frames into preset canvas size
            bx, by, bw, bh = preset.calc_board_rect()
            composed: List[np.ndarray] = []
            bg = np.array(preset.bg, dtype=np.uint8)
            for f in frames:
                canvas = np.full((preset.height, preset.width, 3),
                                 bg, dtype=np.uint8)
                # Resize frame to board rect
                h_src, w_src = f.shape[:2]
                if w_src != bw or h_src != bh:
                    # Simple nearest-neighbor resize
                    row_idx = np.linspace(0, h_src - 1, bh).astype(int)
                    col_idx = np.linspace(0, w_src - 1, bw).astype(int)
                    f_resized = f[np.ix_(row_idx, col_idx)]
                else:
                    f_resized = f
                canvas[by:by + bh, bx:bx + bw] = f_resized
                composed.append(canvas)

            if path.lower().endswith('.gif'):
                if HAS_IMAGEIO:
                    iio.imwrite(path, composed,
                                duration=int(1000 / preset.fps), loop=0)
                    log(f"GIF saved: {path}", "EXPORT")
                    return True
                return False

            if HAS_IMAGEIO and HAS_FFMPEG:
                iio.imwrite(path, composed, fps=preset.fps)
                log(f"Video saved: {path}", "EXPORT")
                return True

            # Fallback: write raw frames, try ffmpeg
            if HAS_FFMPEG:
                tmpdir = tempfile.mkdtemp(prefix="chess_export_")
                for i, frame in enumerate(composed):
                    fpath = os.path.join(tmpdir, f"frame_{i:06d}.png")
                    if HAS_IMAGEIO:
                        iio.imwrite(fpath, frame)
                cmd = [
                    'ffmpeg', '-y', '-framerate', str(preset.fps),
                    '-i', os.path.join(tmpdir, 'frame_%06d.png'),
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-preset', 'medium', '-crf', '23', path,
                ]
                subprocess.run(cmd, capture_output=True, check=True)
                shutil.rmtree(tmpdir, ignore_errors=True)
                log(f"Video saved via ffmpeg: {path}", "EXPORT")
                return True

            log("No video export method available (need imageio[ffmpeg] or ffmpeg)",
                "ERROR")
            return False
        except Exception as e:
            log(f"Video export error: {e}", "ERROR")
            return False


# ═══════════════════════════════════════════════════════════════════════════════
#  CHESS BOARD WIDGET — Interactive board with animation
# ═══════════════════════════════════════════════════════════════════════════════

class ChessBoardWidget(QWidget):
    """Interactive chess board widget with move animation."""

    move_made = Signal(str)        # UCI string
    move_info = Signal(object)     # MoveInfo
    board_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.engine = ChessEngine()
        self.sound = SoundManager()
        self.theme = THEMES["Minimal"]
        self.flipped = False
        self.sq_size = SQ_SIZE

        # Selection state
        self._selected: Optional[Tuple[int, int]] = None
        self._legal_targets: List[Tuple[int, int]] = []

        # Animation state
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(1000 // ANIM_FPS)
        self._anim_timer.timeout.connect(self._anim_tick)
        self._anim_state: Optional[Dict] = None
        self._anim_speed = ANIM_SPEED_DEFAULT
        self._anim_start_time: float = 0.0
        self._pending_info: Optional[MoveInfo] = None

        # Puzzle playback state
        self._puzzle_mode = False
        self._puzzle_moves: List[str] = []
        self._puzzle_idx = 0
        self._auto_play = False
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(800)
        self._auto_timer.timeout.connect(self._auto_step)

        # Text overlay
        self._overlay = ""

        self.setFixedSize(self.sq_size * 8, self.sq_size * 8)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ── Public API ──

    def set_theme(self, name: str) -> None:
        self.theme = THEMES.get(name, THEMES["Minimal"])
        self.update()

    def set_flipped(self, flipped: bool) -> None:
        self.flipped = flipped
        self.update()

    def set_anim_speed(self, ms: int) -> None:
        self._anim_speed = max(50, ms)

    def set_sound_enabled(self, enabled: bool) -> None:
        self.sound.set_enabled(enabled)

    def set_sound_volume(self, vol: float) -> None:
        self.sound.set_volume(vol)

    def load_fen(self, fen: str) -> None:
        self._clear_state()
        self.engine.load_fen(fen)
        self.update()

    def load_puzzle(self, puzzle: Puzzle) -> None:
        """Load a puzzle for playback."""
        self._clear_state()
        self.engine.load_fen(puzzle.fen)
        self._puzzle_mode = True
        self._puzzle_moves = list(puzzle.moves)
        self._puzzle_idx = 0
        self._overlay = puzzle.name
        self.update()
        # Clear overlay after a moment
        QTimer.singleShot(1500, self._clear_overlay)

    def start_auto_play(self, interval: int = 800) -> None:
        self._auto_play = True
        self._auto_timer.setInterval(interval)
        self._auto_timer.start()

    def stop_auto_play(self) -> None:
        self._auto_play = False
        self._auto_timer.stop()

    def puzzle_next_move(self) -> bool:
        """Play the next puzzle move. Returns False if done."""
        if not self._puzzle_mode:
            return False
        if self._puzzle_idx >= len(self._puzzle_moves):
            return False
        uci = self._puzzle_moves[self._puzzle_idx]
        info = self.engine.make_move_uci(uci)
        if info:
            self._puzzle_idx += 1
            self._play_move_sound(info)
            self.update()
            if info.is_mate:
                self._overlay = "CHECKMATE"
                QTimer.singleShot(2500, self._clear_overlay)
            elif info.is_check:
                self._overlay = "CHECK"
                QTimer.singleShot(1000, self._clear_overlay)
            self.move_info.emit(info)
            self.move_made.emit(uci)
            self.board_changed.emit()
            return True
        return False

    def puzzle_prev_move(self) -> bool:
        """Undo last puzzle move."""
        if not self._puzzle_mode:
            return False
        if self._puzzle_idx <= 0:
            return False
        self.engine.undo()
        self._puzzle_idx -= 1
        self._overlay = ""
        self.update()
        self.board_changed.emit()
        return True

    def puzzle_reset(self) -> None:
        """Reset to puzzle starting position."""
        if self._puzzle_mode:
            self.engine.reset_to_initial()
            self._puzzle_idx = 0
            self._overlay = ""
            self._selected = None
            self._legal_targets = []
            self.update()
            self.board_changed.emit()

    @property
    def puzzle_progress(self) -> Tuple[int, int]:
        """Returns (current_move_index, total_moves)."""
        return (self._puzzle_idx, len(self._puzzle_moves))

    @property
    def puzzle_complete(self) -> bool:
        return self._puzzle_mode and self._puzzle_idx >= len(self._puzzle_moves)

    def undo(self) -> None:
        if self._anim_state:
            return
        self.engine.undo()
        self._selected = None
        self._legal_targets = []
        self.update()
        self.board_changed.emit()

    def get_move_list(self) -> List[str]:
        """Get SAN notation for all moves played."""
        board = chess.Board(self.engine.initial_fen or chess.STARTING_FEN)
        san_list = []
        for move in self.engine.board.move_stack:
            san = board.san(move)
            board.push(move)
            san_list.append(san)
        return san_list

    # ── Overrides ──

    def mousePressEvent(self, event) -> None:
        if self._anim_state:
            return
        if event.button() != Qt.LeftButton:
            return
        r, c = self._pixel_to_rc(event.position().toPoint())
        if r < 0 or r > 7 or c < 0 or c > 7:
            return

        # If in puzzle mode, only allow puzzle moves via auto/next
        if self._puzzle_mode:
            return

        piece = self.engine.board.piece_at(
            ChessEngine.rc_to_sq(r, c))

        if self._selected:
            # Try to make a move
            sr, sc = self._selected
            if (r, c) in self._legal_targets:
                # Check promotion
                if self.engine.is_promotion(sr, sc, r, c):
                    promo = self._prompt_promotion()
                    if promo is None:
                        return
                    info = self.engine.make_move(sr, sc, r, c, promo)
                else:
                    info = self.engine.make_move(sr, sc, r, c)
                if info:
                    self._selected = None
                    self._legal_targets = []
                    self._play_move_sound(info)
                    self.update()
                    self.move_info.emit(info)
                    self.move_made.emit(
                        chess.Move(ChessEngine.rc_to_sq(sr, sc),
                                   ChessEngine.rc_to_sq(r, c),
                                   promo).uci() if info.promo else
                        chess.Move(ChessEngine.rc_to_sq(sr, sc),
                                   ChessEngine.rc_to_sq(r, c)).uci())
                    self.board_changed.emit()
                    return
            # Deselect or reselect
            self._selected = None
            self._legal_targets = []
            if piece and self._is_our_piece(piece):
                self._selected = (r, c)
                self._legal_targets = self.engine.legal_targets(r, c)
        else:
            if piece and self._is_our_piece(piece):
                self._selected = (r, c)
                self._legal_targets = self.engine.legal_targets(r, c)

        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Left:
            self.undo()
        elif event.key() == Qt.Key_Right:
            if self._puzzle_mode:
                self.puzzle_next_move()
        elif event.key() == Qt.Key_Space:
            if self._puzzle_mode:
                if self._auto_play:
                    self.stop_auto_play()
                else:
                    self.start_auto_play()
        elif event.key() == Qt.Key_R:
            if self._puzzle_mode:
                self.puzzle_reset()
        elif event.key() == Qt.Key_F:
            self.set_flipped(not self.flipped)

    # ── Painting ──

    def paintEvent(self, event) -> None:
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
            text_overlay=self._overlay,
        )
        qp = QPainter(self)
        qp.drawImage(0, 0, img)
        qp.end()

    # ── Private ──

    def _pixel_to_rc(self, pos) -> Tuple[int, int]:
        x, y = pos.x(), pos.y()
        if self.flipped:
            col = 7 - x // self.sq_size
            row = 7 - y // self.sq_size
        else:
            col = x // self.sq_size
            row = y // self.sq_size
        return row, col

    def _is_our_piece(self, piece: chess.Piece) -> bool:
        return ((piece.color == chess.WHITE and self.engine.turn == 'w') or
                (piece.color == chess.BLACK and self.engine.turn == 'b'))

    def _play_move_sound(self, info: MoveInfo) -> None:
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

    def _prompt_promotion(self) -> Optional[int]:
        items = [
            ("Queen", chess.QUEEN), ("Rook", chess.ROOK),
            ("Bishop", chess.BISHOP), ("Knight", chess.KNIGHT),
        ]
        dialog = QDialog(self)
        dialog.setWindowTitle("Promote pawn")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        result = [None]

        for label, piece_type in items:
            btn = QPushButton(label)
            btn.setProperty("accent", True)
            pt = piece_type

            def make_cb(p):
                def cb():
                    result[0] = p
                    dialog.accept()
                return cb
            btn.clicked.connect(make_cb(pt))
            layout.addWidget(btn)

        dialog.exec()
        return result[0]

    def _clear_state(self) -> None:
        self._selected = None
        self._legal_targets = []
        self._anim_state = None
        self._anim_timer.stop()
        self._pending_info = None
        self._puzzle_mode = False
        self._puzzle_moves = []
        self._puzzle_idx = 0
        self._auto_play = False
        self._auto_timer.stop()
        self._overlay = ""

    def _clear_overlay(self) -> None:
        self._overlay = ""
        self.update()

    def _anim_tick(self) -> None:
        if not self._anim_state:
            self._anim_timer.stop()
            return
        elapsed = (time.monotonic() - self._anim_start_time) * 1000
        progress = min(1.0, elapsed / max(1, self._anim_speed))
        # Ease-out cubic
        progress = 1.0 - (1.0 - progress) ** 3
        self._anim_state['progress'] = progress
        if progress >= 1.0:
            self._anim_state = None
            self._anim_timer.stop()
        self.update()

    def _auto_step(self) -> None:
        if not self.puzzle_next_move():
            self.stop_auto_play()

    def cleanup(self) -> None:
        self._anim_timer.stop()
        self._auto_timer.stop()
        self.sound.cleanup()


# ═══════════════════════════════════════════════════════════════════════════════
#  FILTER PANEL — Search & filter controls
# ═══════════════════════════════════════════════════════════════════════════════

class FilterPanel(QWidget):
    """Side panel with search, difficulty, rating, theme, and sort controls."""

    filter_changed = Signal(FilterCriteria)

    def __init__(self, collection: PuzzleCollection,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._collection = collection
        self._theme_tags: Set[str] = set()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ── Search ──
        search_group = QFrame()
        search_group.setObjectName("searchGroup")
        sl = QVBoxLayout(search_group)
        sl.setContentsMargins(12, 12, 12, 8)
        lbl = QLabel("🔍 Search")
        lbl.setStyleSheet("font-weight:600; font-size:14px; color:#2D7D9A;")
        sl.addWidget(lbl)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Name, theme, opening…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._emit_filter)
        sl.addWidget(self._search_edit)

        # Autocomplete suggestions
        self._suggest_list = QListWidget()
        self._suggest_list.setMaximumHeight(120)
        self._suggest_list.hide()
        self._suggest_list.itemClicked.connect(self._apply_suggestion)
        sl.addWidget(self._suggest_list)
        layout.addWidget(search_group)

        # ── Difficulty ──
        diff_group = QFrame()
        dl = QVBoxLayout(diff_group)
        dl.setContentsMargins(12, 8, 12, 8)
        self._diff_label = QLabel("Difficulty: All")
        self._diff_label.setStyleSheet("font-weight:500;")
        dl.addWidget(self._diff_label)
        self._diff_slider = QSlider(Qt.Horizontal)
        self._diff_slider.setRange(0, 100)
        self._diff_slider.setValue(0)
        self._diff_slider.setTickPosition(QSlider.TicksBelow)
        self._diff_slider.setTickInterval(20)
        self._diff_slider.valueChanged.connect(self._on_diff_changed)
        dl.addWidget(self._diff_slider)
        self._diff_hi_slider = QSlider(Qt.Horizontal)
        self._diff_hi_slider.setRange(0, 100)
        self._diff_hi_slider.setValue(100)
        self._diff_hi_slider.valueChanged.connect(self._on_diff_changed)
        dl.addWidget(self._diff_hi_slider)
        layout.addWidget(diff_group)

        # ── Rating ──
        rating_group = QFrame()
        rl = QVBoxLayout(rating_group)
        rl.setContentsMargins(12, 8, 12, 8)
        self._rating_label = QLabel("Rating: 0–3500")
        self._rating_label.setStyleSheet("font-weight:500;")
        rl.addWidget(self._rating_label)
        rh = QHBoxLayout()
        self._rating_lo = QSpinBox()
        self._rating_lo.setRange(0, 3500); self._rating_lo.setValue(0)
        self._rating_lo.setSingleStep(100)
        self._rating_lo.valueChanged.connect(self._emit_filter)
        rh.addWidget(QLabel("Min")); rh.addWidget(self._rating_lo)
        self._rating_hi = QSpinBox()
        self._rating_hi.setRange(0, 3500); self._rating_hi.setValue(3500)
        self._rating_hi.setSingleStep(100)
        self._rating_hi.valueChanged.connect(self._emit_filter)
        rh.addWidget(QLabel("Max")); rh.addWidget(self._rating_hi)
        rl.addLayout(rh)
        self._require_rating = QCheckBox("Has rating only")
        self._require_rating.stateChanged.connect(self._emit_filter)
        rl.addWidget(self._require_rating)
        layout.addWidget(rating_group)

        # ── Move count ──
        moves_group = QFrame()
        ml = QVBoxLayout(moves_group)
        ml.setContentsMargins(12, 8, 12, 8)
        self._moves_label = QLabel("Moves: 1–50")
        self._moves_label.setStyleSheet("font-weight:500;")
        ml.addWidget(self._moves_label)
        mh = QHBoxLayout()
        self._moves_lo = QSpinBox()
        self._moves_lo.setRange(1, 50); self._moves_lo.setValue(1)
        self._moves_lo.valueChanged.connect(self._emit_filter)
        mh.addWidget(QLabel("Min")); mh.addWidget(self._moves_lo)
        self._moves_hi = QSpinBox()
        self._moves_hi.setRange(1, 50); self._moves_hi.setValue(50)
        self._moves_hi.valueChanged.connect(self._emit_filter)
        mh.addWidget(QLabel("Max")); mh.addWidget(self._moves_hi)
        ml.addLayout(mh)
        layout.addWidget(moves_group)

        # ── Theme tags ──
        theme_group = QFrame()
        tl = QVBoxLayout(theme_group)
        tl.setContentsMargins(12, 8, 12, 8)
        lbl2 = QLabel("🏷 Themes")
        lbl2.setStyleSheet("font-weight:600; color:#2D7D9A;")
        tl.addWidget(lbl2)
        self._theme_edit = QLineEdit()
        self._theme_edit.setPlaceholderText("Type theme…")
        self._theme_edit.textChanged.connect(self._on_theme_text)
        tl.addWidget(self._theme_edit)
        self._theme_suggest = QListWidget()
        self._theme_suggest.setMaximumHeight(100)
        self._theme_suggest.hide()
        self._theme_suggest.itemClicked.connect(self._add_theme_tag)
        tl.addWidget(self._theme_suggest)
        self._tag_layout = QHBoxLayout()
        self._tag_container = QWidget()
        self._tag_container.setLayout(self._tag_layout)
        tl.addWidget(self._tag_container)
        layout.addWidget(theme_group)

        # ── Sort ──
        sort_group = QFrame()
        sol = QVBoxLayout(sort_group)
        sol.setContentsMargins(12, 8, 12, 8)
        lbl3 = QLabel("Sort by")
        lbl3.setStyleSheet("font-weight:500;")
        sol.addWidget(lbl3)
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("Default", SortMode.DEFAULT)
        self._sort_combo.addItem("Name A→Z", SortMode.NAME_ASC)
        self._sort_combo.addItem("Name Z→A", SortMode.NAME_DESC)
        self._sort_combo.addItem("Difficulty ↑", SortMode.DIFFICULTY_ASC)
        self._sort_combo.addItem("Difficulty ↓", SortMode.DIFFICULTY_DESC)
        self._sort_combo.addItem("Rating ↑", SortMode.RATING_ASC)
        self._sort_combo.addItem("Rating ↓", SortMode.RATING_DESC)
        self._sort_combo.addItem("Moves ↑", SortMode.MOVES_ASC)
        self._sort_combo.addItem("Moves ↓", SortMode.MOVES_DESC)
        self._sort_combo.currentIndexChanged.connect(self._emit_filter)
        sol.addWidget(self._sort_combo)
        layout.addWidget(sort_group)

        # ── Reset ──
        self._reset_btn = QPushButton("Reset Filters")
        self._reset_btn.clicked.connect(self._reset_filters)
        layout.addWidget(self._reset_btn)

        layout.addStretch()

        # Filter debounce timer
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)

    def _on_diff_changed(self) -> None:
        lo = self._diff_slider.value()
        hi = self._diff_hi_slider.value()
        if lo > hi:
            self._diff_hi_slider.setValue(lo)
            hi = lo
        tier_names = ["All"] + [t.label for t in DifficultyTier]
        lo_tier = DifficultyTier.from_score(lo / 100.0).label
        hi_tier = DifficultyTier.from_score(hi / 100.0).label
        self._diff_label.setText(f"Difficulty: {lo_tier} – {hi_tier}")
        self._emit_filter()

    def _on_theme_text(self, text: str) -> None:
        idx = self._collection.index
        if not idx:
            self._theme_suggest.hide()
            return
        trie = idx.theme_trie
        if text:
            suggestions = trie.search(text, limit=8)
            if suggestions:
                self._theme_suggest.clear()
                for s in suggestions:
                    self._theme_suggest.addItem(s)
                self._theme_suggest.show()
            else:
                self._theme_suggest.hide()
        else:
            self._theme_suggest.hide()

    def _add_theme_tag(self, item: QListWidgetItem) -> None:
        tag = item.text()
        self._theme_tags.add(tag)
        self._theme_edit.clear()
        self._theme_suggest.hide()
        self._rebuild_tag_chips()
        self._emit_filter()

    def _remove_tag(self, tag: str) -> None:
        self._theme_tags.discard(tag)
        self._rebuild_tag_chips()
        self._emit_filter()

    def _rebuild_tag_chips(self) -> None:
        # Clear existing chips
        while self._tag_layout.count():
            child = self._tag_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for tag in sorted(self._theme_tags):
            chip = QPushButton(f"✕ {tag}")
            chip.setFixedHeight(26)
            chip.setStyleSheet(
                "QPushButton{background:#E0F0F5;border:1px solid #2D7D9A;"
                "border-radius:13px;padding:2px 10px;color:#2D7D9A;"
                "font-size:11px;font-weight:500;}"
                "QPushButton:hover{background:#CCE5ED;}")
            chip.clicked.connect(lambda _, t=tag: self._remove_tag(t))
            self._tag_layout.addWidget(chip)
        self._tag_layout.addStretch()

    def _apply_suggestion(self, item: QListWidgetItem) -> None:
        text = item.text()
        self._search_edit.setText(text)
        self._suggest_list.hide()

    def _emit_filter(self) -> None:
        self._debounce.start()

    def get_criteria(self) -> FilterCriteria:
        lo = self._diff_slider.value() / 100.0
        hi = self._diff_hi_slider.value() / 100.0
        return FilterCriteria(
            text_query=self._search_edit.text().strip(),
            difficulty_range=(lo, hi),
            rating_range=(self._rating_lo.value(), self._rating_hi.value()),
            move_count_range=(self._moves_lo.value(), self._moves_hi.value()),
            theme_tags=frozenset(self._theme_tags),
            sort_mode=self._sort_combo.currentData() or SortMode.DEFAULT,
            require_rating=self._require_rating.isChecked(),
        )

    def _reset_filters(self) -> None:
        self._search_edit.clear()
        self._diff_slider.setValue(0)
        self._diff_hi_slider.setValue(100)
        self._rating_lo.setValue(0)
        self._rating_hi.setValue(3500)
        self._moves_lo.setValue(1)
        self._moves_hi.setValue(50)
        self._require_rating.setChecked(False)
        self._sort_combo.setCurrentIndex(0)
        self._theme_tags.clear()
        self._rebuild_tag_chips()
        self._emit_filter()


# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE LIST WIDGET
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleListWidget(QWidget):
    """Scrollable list of puzzle cards."""

    puzzle_selected = Signal(int)  # puzzle id

    def __init__(self, collection: PuzzleCollection,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._collection = collection
        self._ids: List[int] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hdr = QHBoxLayout()
        self._count_label = QLabel("0 puzzles")
        self._count_label.setStyleSheet("color:#757575; font-size:12px;")
        hdr.addWidget(self._count_label)
        hdr.addStretch()
        layout.addLayout(hdr)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

    def set_ids(self, ids: List[int]) -> None:
        self._ids = ids
        self._list.clear()
        self._count_label.setText(f"{len(ids)} puzzles")
        for pid in ids:
            puzzle = self._collection.get(pid)
            if puzzle:
                self._add_puzzle_item(puzzle)

    def _add_puzzle_item(self, puzzle: Puzzle) -> None:
        tier_color = puzzle.tier_color
        rating_str = f" • {puzzle.rating}" if puzzle.rating else ""
        themes_str = ""
        if puzzle.themes:
            t_list = sorted(puzzle.themes)[:3]
            themes_str = " • " + ", ".join(t_list)
            if len(puzzle.themes) > 3:
                themes_str += f" +{len(puzzle.themes) - 3}"

        text = f"<b style='color:{tier_color}'>●</b> {puzzle.name}"
        sub = (f"<span style='color:#757575;font-size:11px;'>"
               f"{puzzle.tier_label}{rating_str} • "
               f"{puzzle.move_count} moves{themes_str}</span>")
        item = QListWidgetItem()
        item.setData(Qt.UserRole, puzzle.id)
        item.setSizeHint(QSize(0, 52))
        self._list.addItem(item)

        # Use a custom widget for rich formatting
        widget = QWidget()
        wl = QVBoxLayout(widget)
        wl.setContentsMargins(8, 4, 8, 4)
        wl.setSpacing(1)
        name_lbl = QLabel(text)
        name_lbl.setStyleSheet("font-size:13px; font-weight:500;")
        sub_lbl = QLabel(sub)
        sub_lbl.setTextFormat(Qt.RichText)
        wl.addWidget(name_lbl)
        wl.addWidget(sub_lbl)
        self._list.setItemWidget(item, widget)

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._ids):
            self.puzzle_selected.emit(self._ids[row])

    def select_puzzle(self, pid: int) -> None:
        if pid in self._ids:
            row = self._ids.index(pid)
            self._list.setCurrentRow(row)


# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE DETAIL PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleDetailPanel(QWidget):
    """Shows details of the selected puzzle."""

    play_requested = Signal(int)     # puzzle id
    export_requested = Signal(int)   # puzzle id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._puzzle: Optional[Puzzle] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._name_label = QLabel("Select a puzzle")
        self._name_label.setWordWrap(True)
        self._name_label.setStyleSheet("font-size:16px; font-weight:700;")
        layout.addWidget(self._name_label)

        self._tier_label = QLabel("")
        self._tier_label.setStyleSheet("font-size:13px; font-weight:600;")
        layout.addWidget(self._tier_label)

        # Details grid
        grid = QGridLayout()
        grid.setSpacing(6)
        details = ["Rating", "Moves", "Opening", "ECO", "Themes"]
        self._detail_labels: Dict[str, QLabel] = {}
        for i, d in enumerate(details):
            lbl = QLabel(f"{d}:")
            lbl.setStyleSheet("color:#757575; font-weight:500;")
            val = QLabel("—")
            val.setWordWrap(True)
            grid.addWidget(lbl, i, 0)
            grid.addWidget(val, i, 1)
            self._detail_labels[d] = val
        layout.addLayout(grid)

        # Description
        self._desc_label = QLabel("")
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet("color:#555; font-size:12px; "
                                       "padding:8px; background:#F5F5F5; "
                                       "border-radius:6px;")
        self._desc_label.hide()
        layout.addWidget(self._desc_label)

        # FEN
        self._fen_label = QLabel("")
        self._fen_label.setWordWrap(True)
        self._fen_label.setStyleSheet("color:#999; font-size:11px; "
                                      "font-family:monospace;")
        self._fen_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._fen_label.hide()
        layout.addWidget(self._fen_label)

        layout.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        self._play_btn = QPushButton("▶ Play")
        self._play_btn.setProperty("accent", True)
        self._play_btn.clicked.connect(self._on_play)
        self._play_btn.setEnabled(False)
        btn_row.addWidget(self._play_btn)

        self._export_btn = QPushButton("📹 Export")
        self._export_btn.clicked.connect(self._on_export)
        self._export_btn.setEnabled(False)
        btn_row.addWidget(self._export_btn)
        layout.addLayout(btn_row)

    def set_puzzle(self, puzzle: Optional[Puzzle]) -> None:
        self._puzzle = puzzle
        if puzzle is None:
            self._name_label.setText("Select a puzzle")
            self._tier_label.setText("")
            self._desc_label.hide()
            self._fen_label.hide()
            self._play_btn.setEnabled(False)
            self._export_btn.setEnabled(False)
            for v in self._detail_labels.values():
                v.setText("—")
            return

        self._name_label.setText(puzzle.name)
        self._tier_label.setText(
            f"<span style='color:{puzzle.tier_color}'>●</span> "
            f"{puzzle.tier_label}")
        self._detail_labels["Rating"].setText(
            str(puzzle.rating) if puzzle.rating else "—")
        self._detail_labels["Moves"].setText(str(puzzle.move_count))
        self._detail_labels["Opening"].setText(puzzle.opening or "—")
        self._detail_labels["ECO"].setText(puzzle.eco or "—")
        self._detail_labels["Themes"].setText(
            ", ".join(sorted(puzzle.themes)) if puzzle.themes else "—")

        if puzzle.desc:
            self._desc_label.setText(puzzle.desc)
            self._desc_label.show()
        else:
            self._desc_label.hide()

        self._fen_label.setText(f"FEN: {puzzle.fen}")
        self._fen_label.show()
        self._play_btn.setEnabled(True)
        self._export_btn.setEnabled(True)

    def _on_play(self) -> None:
        if self._puzzle:
            self.play_requested.emit(self._puzzle.id)

    def _on_export(self) -> None:
        if self._puzzle:
            self.export_requested.emit(self._puzzle.id)


# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class ExportDialog(QDialog):
    """Dialog for configuring and running puzzle export."""

    def __init__(self, puzzle: Puzzle, settings: Settings,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._puzzle = puzzle
        self._settings = settings
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"Export — {self._puzzle.name}")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        # Preset
        fl = QFormLayout()
        self._preset_combo = QComboBox()
        for name, preset in EXPORT_PRESETS.items():
            self._preset_combo.addItem(name, preset)
        last = self._settings.get('export_preset', 'Board Only (544×544)')
        idx = self._preset_combo.findText(last)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)
        fl.addRow("Preset:", self._preset_combo)

        # Format
        self._format_combo = QComboBox()
        self._format_combo.addItem("MP4 Video", "mp4")
        self._format_combo.addItem("Animated GIF", "gif")
        if not (HAS_IMAGEIO or HAS_FFMPEG):
            self._format_combo.setItemData(0, False, Qt.UserRole - 1)
            self._format_combo.setItemData(1, False, Qt.UserRole - 1)
        fl.addRow("Format:", self._format_combo)

        # FPS
        self._fps_spin = QSpinBox()
        self._fps_spin.setRange(10, 60)
        self._fps_spin.setValue(30)
        fl.addRow("FPS:", self._fps_spin)

        layout.addLayout(fl)

        # Theme
        self._theme_combo = QComboBox()
        for name in THEMES:
            self._theme_combo.addItem(name)
        current = self._settings.get('theme', 'Minimal')
        idx2 = self._theme_combo.findText(current)
        if idx2 >= 0:
            self._theme_combo.setCurrentIndex(idx2)
        fl.addRow("Board theme:", self._theme_combo)

        # Progress
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#757575; font-size:12px;")
        layout.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()
        self._export_btn = QPushButton("Export")
        self._export_btn.setProperty("accent", True)
        self._export_btn.clicked.connect(self._do_export)
        btn_row.addWidget(self._export_btn)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

    def _do_export(self) -> None:
        preset: ExportPreset = self._preset_combo.currentData()
        theme = THEMES.get(self._theme_combo.currentText(), THEMES["Minimal"])
        fmt = self._format_combo.currentData()
        fps = self._fps_spin.value()

        # Build modified preset with custom fps
        actual_preset = ExportPreset(
            preset.name, preset.width, preset.height,
            fps, preset.board_frac, preset.bg, preset.description)

        # Choose save path
        safe_name = SAFE_FS_RE.sub('_', self._puzzle.name)[:50]
        ext = ".gif" if fmt == "gif" else ".mp4"
        default_name = f"{safe_name}{ext}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Export", default_name,
            f"{'GIF' if fmt == 'gif' else 'Video'} files (*{ext})")
        if not path:
            return

        self._export_btn.setEnabled(False)
        self._status.setText("Rendering…")

        def progress_cb(frac: float) -> None:
            # Schedule UI update on main thread
            QTimer.singleShot(0, lambda: self._progress.setValue(int(frac * 100)))

        def run_export() -> None:
            if fmt == "gif":
                ok = PuzzleExporter.export_gif(
                    self._puzzle, path, sq_size=actual_preset.calc_sq_size(),
                    theme=theme, fps=fps, progress_cb=progress_cb)
            else:
                ok = PuzzleExporter.export_video(
                    self._puzzle, path, preset=actual_preset,
                    theme=theme, progress_cb=progress_cb)

            QTimer.singleShot(0, lambda: self._export_done(ok, path))

        threading.Thread(target=run_export, daemon=True).start()

    def _export_done(self, ok: bool, path: str) -> None:
        self._export_btn.setEnabled(True)
        if ok:
            self._status.setText(f"✓ Saved to {path}")
            self._progress.setValue(100)
            self._settings.set('export_preset', self._preset_combo.currentText())
        else:
            self._status.setText("✗ Export failed — check log")
            self._progress.setValue(0)


# ═══════════════════════════════════════════════════════════════════════════════
#  PLAYBACK CONTROLS
# ═══════════════════════════════════════════════════════════════════════════════

class PlaybackControls(QWidget):
    """Transport controls for puzzle playback."""

    next_clicked = Signal()
    prev_clicked = Signal()
    reset_clicked = Signal()
    auto_toggled = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._reset_btn = QPushButton("⏮")
        self._reset_btn.setFixedSize(36, 36)
        self._reset_btn.setToolTip("Reset (R)")
        self._reset_btn.clicked.connect(self.reset_clicked)
        layout.addWidget(self._reset_btn)

        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedSize(36, 36)
        self._prev_btn.setToolTip("Previous move (←)")
        self._prev_btn.clicked.connect(self.prev_clicked)
        layout.addWidget(self._prev_btn)

        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedSize(36, 36)
        self._next_btn.setToolTip("Next move (→)")
        self._next_btn.clicked.connect(self.next_clicked)
        layout.addWidget(self._next_btn)

        self._auto_btn = QPushButton("⏩")
        self._auto_btn.setFixedSize(36, 36)
        self._auto_btn.setToolTip("Auto-play (Space)")
        self._auto_btn.setCheckable(True)
        self._auto_btn.toggled.connect(self.auto_toggled)
        layout.addWidget(self._auto_btn)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet(
            "color:#757575; font-size:11px; padding:0 8px;")
        layout.addWidget(self._progress_label)

        layout.addStretch()

        # Flip button
        self._flip_btn = QPushButton("🔃")
        self._flip_btn.setFixedSize(36, 36)
        self._flip_btn.setToolTip("Flip board (F)")
        layout.addWidget(self._flip_btn)

    def set_progress(self, current: int, total: int) -> None:
        self._progress_label.setText(f"{current}/{total}")

    def set_auto(self, on: bool) -> None:
        self._auto_btn.setChecked(on)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    """Application main window — assembles all components."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Chess Puzzle App")
        self.setMinimumSize(1100, 700)

        # Core state
        self.collection = PuzzleCollection()
        self.settings = Settings()
        self._current_puzzle: Optional[Puzzle] = None
        self._filtered_ids: List[int] = []

        # Build UI
        self._build_ui()
        self._connect_signals()
        self._apply_settings()

        # Load default data if available
        self._try_load_default()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # ── Left: Filter panel ──
        self.filter_panel = FilterPanel(self.collection)
        self.filter_panel.setFixedWidth(260)
        main_layout.addWidget(self.filter_panel)

        # ── Center: Board + controls ──
        center = QVBoxLayout()
        center.setSpacing(8)

        # Board
        self.board_widget = ChessBoardWidget()
        center.addWidget(self.board_widget, alignment=Qt.AlignCenter)

        # Move list display
        self._move_list_label = QLabel("")
        self._move_list_label.setWordWrap(True)
        self._move_list_label.setStyleSheet(
            "color:#555; font-size:12px; font-family:monospace; "
            "padding:6px 10px; background:#FFF; border:1px solid #E0E0E0; "
            "border-radius:6px; min-height:28px;")
        center.addWidget(self._move_list_label)

        # Playback controls
        self.playback = PlaybackControls()
        center.addWidget(self.playback)

        # Status
        self._status_label = QLabel("Load a puzzle file to begin")
        self._status_label.setStyleSheet("color:#999; font-size:11px;")
        center.addWidget(self._status_label)

        center.addStretch()
        main_layout.addLayout(center, stretch=1)

        # ── Right: Puzzle list + details ──
        right = QVBoxLayout()
        right.setSpacing(8)

        self.puzzle_list = PuzzleListWidget(self.collection)
        right.addWidget(self.puzzle_list, stretch=1)

        self.detail_panel = PuzzleDetailPanel()
        self.detail_panel.setFixedWidth(280)
        right.addWidget(self.detail_panel)

        main_layout.addLayout(right)

        # ── Menu bar ──
        self._build_menu()

        # ── Status bar ──
        self.statusBar().showMessage("Ready")

    def _build_menu(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        open_act = file_menu.addAction("&Open Puzzle File…")
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._open_file)

        file_menu.addSeparator()

        load_dir_act = file_menu.addAction("Load &Directory…")
        load_dir_act.triggered.connect(self._open_directory)

        file_menu.addSeparator()

        quit_act = file_menu.addAction("&Quit")
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)

        # View menu
        view_menu = mb.addMenu("&View")
        theme_menu = view_menu.addMenu("Board &Theme")
        for name in THEMES:
            act = theme_menu.addAction(name)
            act.triggered.connect(lambda _, n=name: self._set_theme(n))

        view_menu.addSeparator()
        flip_act = view_menu.addAction("&Flip Board")
        flip_act.setShortcut("F")
        flip_act.triggered.connect(
            lambda: self.board_widget.set_flipped(
                not self.board_widget.flipped))

        # Settings menu
        settings_menu = mb.addMenu("&Settings")
        self._sound_action = settings_menu.addAction("Sound &Enabled")
        self._sound_action.setCheckable(True)
        self._sound_action.setChecked(True)
        self._sound_action.triggered.connect(
            lambda: self.board_widget.set_sound_enabled(
                self._sound_action.isChecked()))

        speed_menu = settings_menu.addMenu("Animation &Speed")
        for ms, label in [(100, "Fast (100ms)"), (250, "Normal (250ms)"),
                          (500, "Slow (500ms)"), (1000, "Very Slow (1s)")]:
            act = speed_menu.addAction(label)
            act.triggered.connect(lambda _, m=ms: self.board_widget.set_anim_speed(m))

    def _connect_signals(self) -> None:
        # Filter debounce
        self.filter_panel._debounce.timeout.connect(self._apply_filter)

        # Puzzle selection
        self.puzzle_list.puzzle_selected.connect(self._on_puzzle_selected)

        # Detail panel actions
        self.detail_panel.play_requested.connect(self._play_puzzle_by_id)
        self.detail_panel.export_requested.connect(self._export_puzzle_by_id)

        # Playback
        self.playback.next_clicked.connect(self.board_widget.puzzle_next_move)
        self.playback.prev_clicked.connect(self.board_widget.puzzle_prev_move)
        self.playback.reset_clicked.connect(self.board_widget.puzzle_reset)
        self.playback.auto_toggled.connect(self._on_auto_toggle)

        # Board changes
        self.board_widget.board_changed.connect(self._on_board_changed)

        # Flip
        self.playback._flip_btn.clicked.connect(
            lambda: self.board_widget.set_flipped(
                not self.board_widget.flipped))

    def _apply_settings(self) -> None:
        self._set_theme(self.settings.get('theme', 'Minimal'))
        self.board_widget.set_flipped(self.settings.get('flipped', False))
        self.board_widget.set_sound_enabled(self.settings.get('sound_enabled', True))
        self.board_widget.set_sound_volume(self.settings.get('sound_volume', 0.7))
        self.board_widget.set_anim_speed(self.settings.get('anim_speed', 250))
        self._sound_action.setChecked(self.settings.get('sound_enabled', True))

        geo = self.settings.get('window_geometry', '')
        if geo:
            self.restoreGeometry(bytes.fromhex(geo))

    def _try_load_default(self) -> None:
        """Try to load puzzle files from the data directory."""
        if not os.path.isdir(DATA_DIR):
            return
        files = []
        for ext in ('*.csv', '*.json', '*.jsonl', '*.parquet', '*.pgn'):
            files.extend(Path(DATA_DIR).glob(ext))
        for f in files[:3]:  # Load up to 3 default files
            self._load_file(str(f))

    # ── File operations ──

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Puzzle File", DATA_DIR,
            "Puzzle files (*.csv *.json *.jsonl *.parquet *.pgn);;All (*)")
        if path:
            self._load_file(path)

    def _open_directory(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Open Puzzle Directory", DATA_DIR)
        if d:
            count = 0
            for ext in ('*.csv', '*.json', '*.jsonl', '*.parquet', '*.pgn'):
                for f in Path(d).glob(ext):
                    self._load_file(str(f))
                    count += 1
            if count == 0:
                self.statusBar().showMessage("No puzzle files found in directory")

    def _load_file(self, path: str) -> None:
        self.statusBar().showMessage(f"Loading {os.path.basename(path)}…")
        QApplication.processEvents()

        puzzles = PuzzleLoader.load_file(path)
        if not puzzles:
            self.statusBar().showMessage(f"No puzzles loaded from {path}")
            return

        self.collection.add_many(puzzles)
        self.collection.build_index()
        self.settings.set('last_file', path)

        # Refresh filter
        self._apply_filter()

        self.statusBar().showMessage(
            f"Loaded {self.collection.count} puzzles from {os.path.basename(path)}")
        self._status_label.setText(
            f"📚 {self.collection.count} puzzles loaded")

    # ── Filtering ──

    def _apply_filter(self) -> None:
        criteria = self.filter_panel.get_criteria()
        self._filtered_ids = self.collection.filter(criteria)
        self.puzzle_list.set_ids(self._filtered_ids)
        n = len(self._filtered_ids)
        self.statusBar().showMessage(f"{n} puzzles match current filters")

    # ── Puzzle interaction ──

    def _on_puzzle_selected(self, pid: int) -> None:
        puzzle = self.collection.get(pid)
        self.detail_panel.set_puzzle(puzzle)

    def _play_puzzle_by_id(self, pid: int) -> None:
        puzzle = self.collection.get(pid)
        if puzzle:
            self._current_puzzle = puzzle
            self.board_widget.load_puzzle(puzzle)
            self.playback.set_progress(0, puzzle.move_count)
            self._status_label.setText(f"♟ Playing: {puzzle.name}")
            self.board_widget.sound.play("start")

    def _export_puzzle_by_id(self, pid: int) -> None:
        puzzle = self.collection.get(pid)
        if puzzle:
            dlg = ExportDialog(puzzle, self.settings, self)
            dlg.exec()

    def _on_board_changed(self) -> None:
        cur, total = self.board_widget.puzzle_progress
        self.playback.set_progress(cur, total)
        # Update move list
        moves = self.board_widget.get_move_list()
        self._move_list_label.setText("  ".join(
            f"{(i // 2) + 1}.{' ' if i % 2 == 0 else '…'}{m}"
            if i % 2 == 0 else m
            for i, m in enumerate(moves)))
        if self.board_widget.puzzle_complete:
            self._status_label.setText("✓ Puzzle complete!")

    def _on_auto_toggle(self, on: bool) -> None:
        if on:
            self.board_widget.start_auto_play()
        else:
            self.board_widget.stop_auto_play()
        self.playback.set_auto(on)

    def _set_theme(self, name: str) -> None:
        self.board_widget.set_theme(name)
        self.settings.set('theme', name)

    # ── Window events ──

    def closeEvent(self, event) -> None:
        # Save settings
        self.settings.set('flipped', self.board_widget.flipped)
        self.settings.set('sound_enabled', self._sound_action.isChecked())
        self.settings.set('sound_volume', self.board_widget.sound._volume)
        self.settings.set('anim_speed', self.board_widget._anim_speed)
        geo = self.saveGeometry().hex()
        self.settings.set('window_geometry', geo.decode() if isinstance(geo, bytes) else geo)
        self.settings.save()
        self.board_widget.cleanup()
        event.accept()


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Chess Puzzle App")
    app.setApplicationVersion("1.0.0")
    app.setStyle("Fusion")

    Palette.apply(app)
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()

    log("Application started", "APP")
    exit_code = app.exec()
    log("Application exiting", "APP")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()