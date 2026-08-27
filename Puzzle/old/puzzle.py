#!/usr/bin/env python3
"""
Chess Puzzle Studio — Professional Chess Puzzle Creator & YouTube Video Generator
Supports loading 5M+ puzzle databases with batch and selective rendering.
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
    QDialogButtonBox, QRadioButton, QButtonGroup, QTableView,
    QHeaderView, QAbstractItemView, QStyledItemDelegate,
)
from PySide6.QtCore import (
    Qt, QRect, QRectF, Signal, QTimer, QPointF, QUrl, QSize, QObject,
    QThread, Signal as QSignal, QSettings, QMutex, QWaitCondition,
    QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QRadialGradient,
    QImage, QPixmap, QPolygonF, QPainterPath, QTransform, QPalette,
    QAction, QIcon, QFontMetrics, QLinearGradient,
)

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
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
SETTINGS_PATH = os.path.join(APP_DIR, "puzzle_studio_settings.json")
os.makedirs(DATA_DIR, exist_ok=True)

SQ_SIZE = 68
BOARD_PX = SQ_SIZE * 8
ANIM_FPS = 60
ANIM_SPEED_DEFAULT = 300

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
            if tier.lo <= score < tier.hi: return tier
        return cls.EXPERT

    @classmethod
    def from_rating(cls, rating: int) -> "DifficultyTier":
        if rating < 800: return cls.BEGINNER
        if rating < 1200: return cls.EASY
        if rating < 1600: return cls.MEDIUM
        if rating < 2000: return cls.HARD
        return cls.EXPERT

class VideoStyle(Enum):
    CINEMATIC = "Cinematic"; MINIMAL = "Minimal"; NEON = "Neon"
    CLASSIC = "Classic"; DARK = "Dark"

class ExportFormat(Enum):
    MP4 = "mp4"; GIF = "gif"; PNG_SEQ = "png_sequence"

# ═══════════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
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
    def tier(self) -> DifficultyTier: return DifficultyTier.from_score(self.difficulty)
    @property
    def tier_color(self) -> str: return self.tier.color
    @property
    def tier_label(self) -> str: return self.tier.label
    @property
    def search_text(self) -> str:
        return ' '.join([self.name, self.desc, self.opening, ' '.join(self.themes)]).lower()
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

@dataclass(frozen=True, slots=True)
class MoveInfo:
    from_rc: Tuple[int, int]; to_rc: Tuple[int, int]
    piece_symbol: str; piece_obj: chess.Piece; captured: str
    is_castle: bool; is_ep: bool; promo: Optional[int]
    is_check: bool; is_mate: bool; notation: str

@dataclass
class VideoConfig:
    width: int = 1920; height: int = 1080; fps: int = 30
    board_theme_name: str = "Classic"
    style: VideoStyle = VideoStyle.CINEMATIC
    flip_board: bool = False
    show_title_card: bool = True; show_solution: bool = True
    title_duration: float = 3.0; pause_duration: float = 2.0
    move_duration: float = 0.8; think_duration: float = 3.0; end_duration: float = 2.5
    show_arrows: bool = True; show_coordinates: bool = True
    show_move_list: bool = True; show_difficulty: bool = True
    bg_color: Tuple[int, int, int] = (32, 32, 36)
    accent_color: Tuple[int, int, int] = (45, 125, 154)
    title_text: str = ""; subtitle_text: str = ""; channel_name: str = ""
    logo_path: str = ""; watermark: bool = False
    format: ExportFormat = ExportFormat.MP4; quality: int = 85

    @property
    def is_portrait(self) -> bool: return self.height > self.width
    @property
    def is_shorts(self) -> bool: return self.height > self.width and self.height >= 1920
    @property
    def calc_sq_size(self) -> int:
        if self.is_portrait: bw = int(self.width * 0.92)
        else: bw = int(min(self.width * 0.55, self.height * 0.85))
        return max(8, (bw // 8) * 8 // 8)
    @property
    def board_pixel_size(self) -> int: return self.calc_sq_size * 8
    @property
    def board_origin(self) -> Tuple[int, int]:
        bw = self.board_pixel_size
        if self.is_portrait: return (self.width - bw) // 2, int(self.height * 0.22)
        return int(self.width * 0.04), (self.height - bw) // 2
    @property
    def info_rect(self) -> Tuple[int, int, int, int]:
        bw = self.board_pixel_size; _, by = self.board_origin
        x = int(self.width * 0.04) + bw + int(self.width * 0.04)
        return x, by, self.width - x - int(self.width * 0.04), bw

EXPORT_PRESETS = {
    "YouTube 1080p": VideoConfig(width=1920, height=1080, fps=30),
    "YouTube 4K": VideoConfig(width=3840, height=2160, fps=30),
    "YouTube Shorts": VideoConfig(width=1080, height=1920, fps=30,
                                  think_duration=2.5, move_duration=0.7),
    "TikTok": VideoConfig(width=1080, height=1920, fps=30,
                           think_duration=2.5, move_duration=0.7),
    "Board Only (544)": VideoConfig(width=544, height=544, fps=30,
                                    show_title_card=False, show_move_list=False,
                                    show_difficulty=False),
    "Custom": VideoConfig(),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  TRIE
# ═══════════════════════════════════════════════════════════════════════════════

class TrieNode:
    __slots__ = ('children', 'is_end', 'count')
    def __init__(self):
        self.children: Dict[str, "TrieNode"] = {}
        self.is_end: bool = False; self.count: int = 0

class Trie:
    def __init__(self):
        self.root = TrieNode(); self._size = 0
    def insert(self, word: str):
        node = self.root
        for ch in word.lower():
            if ch not in node.children: node.children[ch] = TrieNode()
            node = node.children[ch]; node.count += 1
        node.is_end = True; self._size += 1
    def search(self, prefix: str, limit: int = 20) -> List[str]:
        node = self.root
        for ch in prefix.lower():
            if ch not in node.children: return []
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
    @property
    def size(self) -> int: return self._size

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE INDEX — Efficient filtering for millions of puzzles
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleIndex:
    def __init__(self, puzzles: Sequence[Puzzle]):
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
            pid = p.id; self._puzzles[pid] = p
            for tag in p.themes: self._tag_index[tag].add(pid)
            for token in p.search_tokens: self._token_index[token].add(pid)
            self._diff_sorted.append((p.difficulty, pid))
            if p.rating is not None:
                self._rating_sorted.append((float(p.rating), pid))
            self._moves_sorted.append((p.move_count, pid))
            self._name_sorted.append((p.name.lower(), pid))
        self._diff_sorted.sort(); self._rating_sorted.sort()
        self._moves_sorted.sort(); self._name_sorted.sort()
        for tag in self._tag_index: self._theme_trie.insert(tag)

    def get(self, pid) -> Optional[Puzzle]: return self._puzzles.get(pid)
    def __len__(self): return len(self._puzzles)
    def __contains__(self, pid): return pid in self._puzzles
    @property
    def all_ids(self) -> Set[int]: return set(self._puzzles.keys())
    @property
    def all_themes(self) -> List[str]: return sorted(self._tag_index.keys())
    @property
    def theme_trie(self) -> Trie: return self._theme_trie

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

    def ids_with_tag(self, tag) -> Set[int]: return self._tag_index.get(tag.lower(), set())
    def ids_with_any_tag(self, tags) -> Set[int]:
        result: Set[int] = set()
        for tag in tags: result |= self.ids_with_tag(tag)
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
        if criteria.is_trivial: return sorted(self._puzzles.keys())
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
        if not candidates: result = self.all_ids
        else:
            candidates.sort(key=len); result = candidates[0]
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
        for p in puzzles: self.add(p)

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
        self._puzzles.clear(); self._index = None; self._next_id = 0

    def next_id(self) -> int:
        nid = self._next_id; self._next_id += 1; return nid

    def remove(self, pid: int):
        self._puzzles = [p for p in self._puzzles if p.id != pid]
        self._index = None

    def save_json(self, path: str):
        data = []
        for p in self._puzzles:
            data.append({
                'id': p.id, 'name': p.name, 'fen': p.fen,
                'moves': list(p.moves), 'desc': p.desc,
                'difficulty': p.difficulty, 'themes': list(p.themes),
                'rating': p.rating, 'move_count': p.move_count,
                'opening': p.opening, 'eco': p.eco,
            })
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_json(self, path: str) -> int:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        count = 0
        for d in data:
            p = Puzzle(
                id=d.get('id', self.next_id()), name=d.get('name', ''),
                fen=d['fen'], moves=tuple(d['moves']), desc=d.get('desc', ''),
                difficulty=d.get('difficulty', 0.5),
                themes=frozenset(d.get('themes', [])),
                rating=d.get('rating'),
                move_count=d.get('move_count', len(d['moves'])),
                opening=d.get('opening', ''), eco=d.get('eco', ''),
            )
            self.add(p); count += 1
        return count

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE LOADER — Streaming CSV/TSV for 5M+ row databases
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleLoader:
    """Streaming loader for large chess puzzle databases.

    Supports:
      - Lichess CSV format (PuzzleId,FEN,Moves,Rating,RatingDeviation,
        Popularity,NbPlays,Themes,GameUrl,OpeningFamily,OpeningVariation)
      - Custom CSV with configurable column mapping
      - JSON array format
    """

    # Lichess standard columns
    LICHESS_COLS = {
        'id': 0, 'fen': 1, 'moves': 2, 'rating': 3,
        'rating_deviation': 4, 'popularity': 5, 'nb_plays': 6,
        'themes': 7, 'game_url': 8, 'opening_family': 9, 'opening_variation': 10,
    }

    @staticmethod
    def detect_format(path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        if ext == '.json': return 'json'
        if ext in ('.parquet', '.pq'): return 'parquet'
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            first_line = f.readline(8192)
        if first_line.startswith('{') or first_line.startswith('['): return 'json'
        if '\t' in first_line: return 'tsv'
        return 'csv'

    @staticmethod
    def count_lines(path: str) -> int:
        """Fast line count for progress tracking."""
        count = 0
        with open(path, 'rb') as f:
            buf = bytearray(1024 * 1024)
            while True:
                n = f.readinto(buf)
                if n == 0: break
                count += buf[:n].count(b'\n')
        return count

    @staticmethod
    def stream_lichess_csv(path: str, limit: int = 0, skip: int = 0,
                           callback: Optional[Callable[[int, int], None]] = None
                           ) -> Iterator[Puzzle]:
        """Stream Lichess-format CSV, yielding Puzzle objects."""
        total = PuzzleLoader.count_lines(path) - 1  # minus header
        if callback: callback(0, total)
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header: return
            # Detect column indices from header
            col_map = {}
            header_lower = [h.strip().lower() for h in header]
            for name, idx in PuzzleLoader.LICHESS_COLS.items():
                if name in header_lower:
                    col_map[name] = header_lower.index(name)
                elif idx < len(header):
                    col_map[name] = idx

            skipped = 0; yielded = 0; pid = 0
            for row in reader:
                if skipped < skip:
                    skipped += 1; continue
                if limit and yielded >= limit: break
                try:
                    pid += 1
                    fen = row[col_map.get('fen', 1)]
                    moves_str = row[col_map.get('moves', 2)]
                    moves_list = moves_str.split()
                    rating_val = row[col_map.get('rating', 3)]
                    rating = int(float(rating_val)) if rating_val else None
                    themes_str = row[col_map.get('themes', 7)]
                    themes = frozenset(t.strip() for t in themes_str.split() if t.strip())
                    opening = row[col_map.get('opening_family', 9)] if len(row) > 9 else ""
                    puzzle_id_str = row[col_map.get('id', 0)]
                    difficulty = min(1.0, max(0.0, (rating or 1000) / 3000.0))
                    p = Puzzle(
                        id=pid,
                        name=f"Puzzle {puzzle_id_str}",
                        fen=fen, moves=tuple(moves_list),
                        desc=f"Rating: {rating or '?'} | {themes_str}",
                        difficulty=difficulty, themes=themes,
                        rating=rating, move_count=len(moves_list),
                        opening=opening,
                    )
                    yielded += 1
                    if callback and pid % 5000 == 0:
                        callback(pid, total)
                    yield p
                except (IndexError, ValueError) as e:
                    continue
            if callback: callback(total, total)

    @staticmethod
    def stream_custom_csv(path: str, col_mapping: Dict[str, int],
                          limit: int = 0, skip: int = 0,
                          callback: Optional[Callable[[int, int], None]] = None
                          ) -> Iterator[Puzzle]:
        total = PuzzleLoader.count_lines(path) - 1
        if callback: callback(0, total)
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            skipped = 0; yielded = 0; pid = 0
            for row in reader:
                if skipped < skip:
                    skipped += 1; continue
                if limit and yielded >= limit: break
                try:
                    pid += 1
                    fen = row[col_mapping['fen']]
                    moves_str = row[col_mapping['moves']]
                    moves_list = moves_str.split()
                    rating_val = row[col_mapping.get('rating', -1)] if 'rating' in col_mapping and col_mapping['rating'] < len(row) else ""
                    rating = int(float(rating_val)) if rating_val else None
                    themes_str = row[col_mapping.get('themes', -1)] if 'themes' in col_mapping and col_mapping['themes'] < len(row) else ""
                    themes = frozenset(t.strip() for t in themes_str.split() if t.strip())
                    name_val = row[col_mapping.get('name', -1)] if 'name' in col_mapping and col_mapping['name'] < len(row) else f"Puzzle {pid}"
                    difficulty = min(1.0, max(0.0, (rating or 1000) / 3000.0))
                    p = Puzzle(
                        id=pid, name=name_val, fen=fen,
                        moves=tuple(moves_list),
                        desc=themes_str, difficulty=difficulty,
                        themes=themes, rating=rating,
                        move_count=len(moves_list),
                    )
                    yielded += 1
                    if callback and pid % 5000 == 0:
                        callback(pid, total)
                    yield p
                except (IndexError, ValueError):
                    continue
            if callback: callback(total, total)

# ═══════════════════════════════════════════════════════════════════════════════
#  BACKGROUND LOAD WORKER
# ═══════════════════════════════════════════════════════════════════════════════

class LoadWorker(QThread):
    progress = Signal(int, int)    # current, total
    loaded = Signal(int)            # count loaded
    finished = Signal()
    error = Signal(str)

    def __init__(self, path: str, fmt: str = "auto",
                 limit: int = 0, skip: int = 0,
                 col_mapping: Optional[Dict[str, int]] = None):
        super().__init__()
        self.path = path; self.fmt = fmt; self.limit = limit
        self.skip = skip; self.col_mapping = col_mapping
        self.puzzles: List[Puzzle] = []
        self._cancel = False

    def cancel(self): self._cancel = True

    def run(self):
        try:
            if self.fmt == "auto":
                self.fmt = PuzzleLoader.detect_format(self.path)
            count = 0
            if self.fmt in ('csv', 'tsv'):
                if self.col_mapping:
                    it = PuzzleLoader.stream_custom_csv(
                        self.path, self.col_mapping, self.limit, self.skip,
                        self._cb)
                else:
                    it = PuzzleLoader.stream_lichess_csv(
                        self.path, self.limit, self.skip, self._cb)
                for p in it:
                    if self._cancel: break
                    self.puzzles.append(p); count += 1
            elif self.fmt == 'json':
                # For JSON we load all at once (not ideal for 5M but supported)
                with open(self.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                total = len(data)
                for i, d in enumerate(data):
                    if self._cancel: break
                    if i < self.skip: continue
                    if self.limit and count >= self.limit: break
                    moves = d.get('moves', [])
                    p = Puzzle(
                        id=d.get('id', count + 1),
                        name=d.get('name', f'Puzzle {count+1}'),
                        fen=d['fen'], moves=tuple(moves) if isinstance(moves, list) else tuple(moves.split()),
                        desc=d.get('desc', ''), difficulty=d.get('difficulty', 0.5),
                        themes=frozenset(d.get('themes', [])),
                        rating=d.get('rating'), move_count=d.get('move_count', len(moves)),
                        opening=d.get('opening', ''), eco=d.get('eco', ''),
                    )
                    self.puzzles.append(p); count += 1
                    if count % 5000 == 0: self.progress.emit(count, total)
            self.loaded.emit(count)
        except Exception as e:
            self.error.emit(str(e))
        self.finished.emit()

    def _cb(self, current, total):
        if self._cancel: return
        self.progress.emit(current, total)

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD THEME
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class BoardTheme:
    name: str
    light_sq: Tuple[int, int, int]; dark_sq: Tuple[int, int, int]
    border: Tuple[int, int, int] = (180, 180, 180)
    highlight: Tuple[int, int, int, int] = (45, 125, 154, 70)
    last_move: Tuple[int, int, int, int] = (45, 125, 154, 50)
    arrow: Tuple[int, int, int, int] = (45, 125, 154, 180)
    bg: Tuple[int, int, int] = (250, 250, 250)
    coord: Tuple[int, int, int] = (160, 160, 160)
    def qcolor(self, attr: str) -> QColor:
        return QColor(*getattr(self, attr))

THEMES: Dict[str, BoardTheme] = {
    "Minimal": BoardTheme("Minimal", (245, 245, 245), (222, 222, 222),
                           border=(200, 200, 200), highlight=(45, 125, 154, 50),
                           last_move=(45, 125, 154, 35), arrow=(45, 125, 154, 160),
                           bg=(250, 250, 250), coord=(180, 180, 180)),
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
#  MINIMAL COLOR PALETTE & STYLESHEET
# ═══════════════════════════════════════════════════════════════════════════════

class Palette:
    BG = "#F8F9FA"; BG2 = "#F1F3F5"; BG3 = "#E9ECEF"; CARD = "#FFFFFF"
    TEXT = "#212529"; TEXT2 = "#868E96"; TEXT3 = "#CED4DA"; INV = "#FFFFFF"
    ACCENT = "#2D7D9A"; ACCENT_H = "#247A95"; ACCENT_L = "#E3F2F5"
    BORDER = "#DEE2E6"; BORDER_L = "#E9ECEF"
    ERROR = "#E03131"; SUCCESS = "#2F9E44"; WARN = "#E8590C"

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
QMainWindow, QWidget { background:#F8F9FA; color:#212529;
    font-family:"Inter","Segoe UI","SF Pro",sans-serif; font-size:13px; }
QLabel { color:#212529; background:transparent; }
QPushButton { background:#FFF; border:1px solid #DEE2E6; border-radius:5px;
    padding:6px 14px; color:#212529; font-weight:500; min-height:18px; }
QPushButton:hover { background:#F1F3F5; border-color:#ADB5BD; }
QPushButton:pressed { background:#E9ECEF; }
QPushButton[accent="true"] { background:#2D7D9A; color:#FFF; border:1px solid #247A95; }
QPushButton[accent="true"]:hover { background:#247A95; }
QPushButton[danger="true"] { background:#E03131; color:#FFF; border:1px solid #C92A2A; }
QPushButton[danger="true"]:hover { background:#C92A2A; }
QPushButton[outline="true"] { background:transparent; border:1px solid #2D7D9A; color:#2D7D9A; }
QPushButton[outline="true"]:hover { background:#E3F2F5; }
QLineEdit { background:#FFF; border:1px solid #DEE2E6; border-radius:5px;
    padding:6px 10px; selection-background-color:#2D7D9A; selection-color:#FFF; }
QLineEdit:focus { border-color:#2D7D9A; }
QComboBox { background:#FFF; border:1px solid #DEE2E6; border-radius:5px;
    padding:5px 10px; min-height:20px; }
QComboBox::drop-down { border:none; width:24px; }
QComboBox::down-arrow { image:none; border-left:4px solid transparent;
    border-right:4px solid transparent; border-top:5px solid #868E96; }
QSpinBox { background:#FFF; border:1px solid #DEE2E6; border-radius:5px; padding:5px 8px; }
QSlider::groove:horizontal { height:4px; background:#DEE2E6; border-radius:2px; }
QSlider::handle:horizontal { background:#2D7D9A; width:14px; height:14px;
    margin:-5px 0; border-radius:7px; }
QSlider::sub-page:horizontal { background:#2D7D9A; border-radius:2px; }
QListWidget { background:#FFF; border:1px solid #DEE2E6; border-radius:5px;
    outline:none; padding:2px; }
QListWidget::item { padding:6px 8px; border-bottom:1px solid #F1F3F5; border-radius:2px; }
QListWidget::item:selected { background:#E3F2F5; color:#212529; }
QListWidget::item:hover { background:#F8F9FA; }
QTextEdit { background:#FFF; border:1px solid #DEE2E6; border-radius:5px; padding:4px; }
QTabWidget::pane { border:1px solid #DEE2E6; border-radius:5px; background:#FFF; top:-1px; }
QTabBar::tab { background:#F8F9FA; border:1px solid #DEE2E6; border-bottom:none;
    border-top-left-radius:5px; border-top-right-radius:5px;
    padding:7px 16px; margin-right:1px; color:#868E96; font-weight:500; }
QTabBar::tab:selected { background:#FFF; color:#2D7D9A; border-bottom:2px solid #2D7D9A; }
QProgressBar { border:1px solid #DEE2E6; border-radius:3px; text-align:center;
    background:#F1F3F5; height:18px; color:#868E96; font-size:11px; }
QProgressBar::chunk { background:#2D7D9A; border-radius:2px; }
QCheckBox { spacing:6px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #CED4DA;
    border-radius:3px; background:#FFF; }
QCheckBox::indicator:checked { background:#2D7D9A; border-color:#2D7D9A; }
QGroupBox { border:1px solid #DEE2E6; border-radius:5px; margin-top:12px;
    padding-top:16px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; color:#2D7D9A; }
QScrollArea { border:none; background:transparent; }
QStatusBar { background:#FFF; border-top:1px solid #DEE2E6; color:#868E96;
    font-size:12px; padding:3px 8px; }
QToolTip { background:#212529; color:#FFF; border:none; border-radius:3px;
    padding:5px 8px; font-size:12px; }
QSplitter::handle { background:#DEE2E6; width:1px; }
QToolBar { background:#FFF; border-bottom:1px solid #DEE2E6; spacing:4px; padding:3px; }
QTableView { background:#FFF; border:1px solid #DEE2E6; border-radius:5px;
    gridline-color:#F1F3F5; selection-background-color:#E3F2F5; }
QTableView::item { padding:4px 6px; }
QHeaderView::section { background:#F8F9FA; border:1px solid #DEE2E6;
    padding:5px 8px; font-weight:600; color:#868E96; }
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  CHESS ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class ChessEngine:
    def __init__(self):
        self.board = chess.Board(); self.game_over = False
        self.result = ""; self.last_move = None; self.initial_fen = None
        self.move_history: List[MoveInfo] = []
        self.san_history: List[str] = []

    def reset(self):
        self.board.reset(); self.game_over = False; self.result = ""
        self.last_move = None; self.initial_fen = None
        self.move_history.clear(); self.san_history.clear()

    def reset_to_initial(self):
        if self.initial_fen: self.load_fen(self.initial_fen)
        else: self.reset()

    @staticmethod
    def sq_to_rc(sq) -> Tuple[int, int]: return 7 - chess.square_rank(sq), chess.square_file(sq)
    @staticmethod
    def rc_to_sq(r, c) -> int: return chess.square(c, 7 - r)

    @property
    def turn(self) -> str: return 'w' if self.board.turn == chess.WHITE else 'b'
    @property
    def turn_name(self) -> str: return "White" if self.board.turn == chess.WHITE else "Black"

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
               (piece.color == chess.BLACK and tr == 7): return True
        return False

    def make_move(self, fr, fc, tr, tc, promo=None) -> Optional[MoveInfo]:
        from_sq = self.rc_to_sq(fr, fc); to_sq = self.rc_to_sq(tr, tc)
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
        cap = self.board.piece_at(
            chess.square(chess.square_file(to_sq), chess.square_rank(from_sq))
        ) if is_ep else self.board.piece_at(to_sq)
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
        self.move_history.append(info); self.san_history.append(notation)
        return info

    def make_move_uci(self, uci_str) -> Optional[MoveInfo]:
        try:
            move = chess.Move.from_uci(uci_str)
        except ValueError: return None
        if move in self.board.legal_moves:
            fr, fc = self.sq_to_rc(move.from_square)
            tr, tc = self.sq_to_rc(move.to_square)
            return self.make_move(fr, fc, tr, tc, move.promotion)
        return None

    def undo(self) -> bool:
        if self.board.move_stack:
            self.board.pop(); self.move_history.pop(); self.san_history.pop()
            self.game_over = self.board.is_game_over()
            self.result = self.board.result() if self.game_over else ""
            if self.board.move_stack:
                last = self.board.peek()
                self.last_move = (self.sq_to_rc(last.from_square),
                                  self.sq_to_rc(last.to_square))
            else: self.last_move = None
            return True
        return False

    def load_fen(self, fen) -> bool:
        try: self.board.set_fen(fen)
        except ValueError: return False
        self.game_over = self.board.is_game_over()
        self.result = self.board.result() if self.game_over else ""
        self.last_move = None; self.initial_fen = fen
        self.move_history.clear(); self.san_history.clear()
        return True

    def san_move_list(self) -> str:
        if not self.san_history: return ""
        lines = []; temp_board = chess.Board()
        if self.initial_fen: temp_board.set_fen(self.initial_fen)
        for san in self.san_history:
            if temp_board.turn == chess.WHITE:
                lines.append(f"{temp_board.fullmove_number}. {san}")
            else: lines.append(san)
            try:
                move = temp_board.parse_san(san); temp_board.push(move)
            except Exception: break
        return " ".join(lines)

# ═══════════════════════════════════════════════════════════════════════════════
#  SOUND MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class SoundManager:
    def __init__(self):
        self._tmpdir = tempfile.mkdtemp(prefix="chess_sfx_")
        self._sounds: Dict[str, Any] = {}; self._enabled = True; self._volume = 0.7
        self._generate(); self._load()

    @staticmethod
    def _to_wav(path, samples, sr=44100):
        int_data = np.clip(samples, -32768, 32767).astype(np.int16)
        with wave.open(path, 'w') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(int_data.tobytes())

    @staticmethod
    def _tone(freq, dur, vol=0.4, sr=44100):
        t = np.arange(int(sr * dur), dtype=np.float64)
        return 32767.0 * vol * np.sin(2.0 * np.pi * freq * t / sr)

    @staticmethod
    def _env(samples, attack=0.005, release=0.03, sr=44100):
        out = samples.copy(); n = len(out)
        ai = min(int(sr * attack), n); ri = min(int(sr * release), n)
        if ai > 1: out[:ai] *= np.linspace(0, 1, ai)
        if ri > 1: out[-ri:] *= np.linspace(1, 0, ri)
        return out

    def _generate(self):
        d = self._tmpdir; sr = 44100
        self._to_wav(os.path.join(d, "move.wav"), self._env(self._tone(800, 0.06)))
        self._to_wav(os.path.join(d, "capture.wav"), self._env(self._tone(300, 0.10, 0.5)))
        self._to_wav(os.path.join(d, "check.wav"), self._env(self._tone(1000, 0.12, 0.5)))
        self._to_wav(os.path.join(d, "checkmate.wav"),
                     self._env(np.concatenate([self._tone(800, 0.15, 0.5),
                                               self._tone(400, 0.25, 0.5)])))
        self._to_wav(os.path.join(d, "error.wav"), self._env(self._tone(200, 0.10, 0.4)))

    def _load(self):
        for name in ("move", "capture", "check", "checkmate", "error"):
            fx = QSoundEffect()
            fx.setSource(QUrl.fromLocalFile(os.path.join(self._tmpdir, f"{name}.wav")))
            fx.setVolume(self._volume); self._sounds[name] = fx

    def set_volume(self, vol): self._volume = max(0.0, min(1.0, vol))
    def set_enabled(self, en): self._enabled = en
    def play(self, name):
        if self._enabled:
            s = self._sounds.get(name)
            if s: s.stop(); s.play()
    def cleanup(self):
        for s in self._sounds.values(): s.stop()
        self._sounds.clear()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD RENDERER
# ═══════════════════════════════════════════════════════════════════════════════

class BoardRenderer:
    _tl = threading.local()

    @staticmethod
    def _assets(sz):
        isz = int(sz * 100)
        if getattr(BoardRenderer._tl, 'cache_sz', -1) == isz:
            return BoardRenderer._tl.assets
        fp = QFont("Segoe UI Emoji", sz * 0.9)
        fp.setStyleStrategy(QFont.PreferAntialias)
        fc = QFont("Sans", max(7, int(sz * 0.13)), QFont.Bold)
        BoardRenderer._tl.cache_sz = isz
        BoardRenderer._tl.assets = (fp, fc)
        return fp, fc

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

        def src(r, c): return (7 - r, 7 - c) if flipped else (r, c)

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
                grad = QRadialGradient(x + sz/2, y + sz/2, sz * 0.7)
                grad.setColorAt(0, QColor(255, 30, 30, 180))
                grad.setColorAt(1, QColor(255, 0, 0, 0))
                p.setBrush(QBrush(grad)); p.setPen(Qt.NoPen)
                p.drawRect(x, y, sz, sz)
            if legal_targets and (r, c) in legal_targets:
                cx, cy = x + sz//2, y + sz//2
                if board.piece_at(sq):
                    p.setPen(QPen(QColor(0, 0, 0, 50), max(3, sz // 14)))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(cx - sz*5//12, cy - sz*5//12, sz*10//12, sz*10//12)
                else:
                    p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 60))
                    p.drawEllipse(cx - sz//6, cy - sz//6, sz//3, sz//3)

        if last_move:
            (fr, fc), (tr, tc) = last_move
            sfr, sfc = src(fr, fc); str_, stc = src(tr, tc)
            BoardRenderer._draw_arrow(p, sfc*sz+sz//2, sfr*sz+sz//2,
                                      stc*sz+sz//2, str_*sz+sz//2,
                                      theme.qcolor('arrow'), sz)

        for sq in chess.SQUARES:
            r, c = 7 - chess.square_rank(sq), chess.square_file(sq)
            if (r, c) in skip_sq: continue
            piece = board.piece_at(sq)
            if piece:
                sr, sc = src(r, c)
                BoardRenderer._draw_piece(p, piece, sr, sc, sz, font_piece)

        if anim_state and anim_state.get('piece_obj'):
            fr, fc_ = anim_state['from']; tr, tc_ = anim_state['to']
            t = anim_state['progress']; obj = anim_state['piece_obj']
            ir = fr + (tr - fr) * t; ic = fc_ + (tc_ - fc_) * t
            if flipped: scr_ir = 7 - ir; scr_ic = 7 - ic
            else: scr_ir = ir; scr_ic = ic
            lift = 4.0 * t * (1.0 - t) * 0.15
            scale = 1.0 + 4.0 * t * (1.0 - t) * 0.08
            sa = 30 + int(70 * max(0, lift / 0.15))
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, sa))
            sy = scr_ir * sz + sz * 0.82
            p.drawEllipse(QRectF(scr_ic * sz + (sz*scale - sz*0.65)/2,
                                 sy, sz*0.65, sz*0.12))
            y_lift = scr_ir * sz - (sz * lift)
            BoardRenderer._draw_piece_at(p, obj, y_lift / sz, scr_ic, sz,
                                         sz*scale, sz*scale, font_piece)

        # Coordinates
        p.setFont(font_coord)
        cm = max(3, int(sz * 0.04)); csz = max(12, sz // 5)
        for ci in range(8):
            fc = FILES_STR[7 - ci] if flipped else FILES_STR[ci]
            is_light = (7 + ci) % 2 == 0
            p.setPen(theme.qcolor('dark_sq' if is_light else 'light_sq'))
            p.drawText(QRect(ci*sz+sz-csz-cm, 7*sz+cm, csz, csz), Qt.AlignCenter, fc)
        for ri in range(8):
            rc = RANKS_STR[7 - ri] if flipped else RANKS_STR[ri]
            is_light = ri % 2 == 0
            p.setPen(theme.qcolor('dark_sq' if is_light else 'light_sq'))
            p.drawText(QRect(cm, ri*sz+cm, csz, csz), Qt.AlignCenter, rc)

        if text_overlay:
            p.fillRect(0, sz*4 - 28, sz*8, 56, QColor(0, 0, 0, 160))
            p.setPen(Qt.white); p.setFont(QFont("Sans", max(12, sz//4), QFont.Bold))
            p.drawText(QRect(0, sz*4-28, sz*8, 56), Qt.AlignCenter, text_overlay)
        p.end()
        return img

    @staticmethod
    def render_full_frame(board, config: VideoConfig, last_move=None,
                          move_list_text="", puzzle_title="",
                          difficulty_label="", difficulty_color="#FFD54F",
                          turn_text="", phase_text="",
                          theme_name="Classic") -> QImage:
        theme = THEMES.get(theme_name, THEMES["Classic"])
        w, h = config.width, config.height
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(*config.bg_color))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        sq = config.calc_sq_size; bx, by = config.board_origin; bw = config.board_pixel_size

        # Shadow
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 30))
        p.drawRoundedRect(bx+4, by+4, bw, bw, 4, 4)

        # Board
        board_img = BoardRenderer.render(board, last_move=last_move,
                                         sq_size=sq, theme=theme,
                                         flipped=config.flip_board)
        scaled = board_img.scaled(bw, bw, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawImage(bx, by, scaled)

        # Border
        p.setPen(QPen(QColor(*theme.border), 2)); p.setBrush(Qt.NoBrush)
        p.drawRect(bx-1, by-1, bw+2, bw+2)

        accent = QColor(*config.accent_color)

        if config.is_portrait:
            if puzzle_title:
                p.setPen(Qt.white)
                p.setFont(QFont("Sans", max(14, w//28), QFont.Bold))
                fm = QFontMetrics(p.font())
                title = fm.elidedText(puzzle_title, Qt.ElideRight, w - 40)
                p.drawText(QRect(20, by - max(50, h//18), w-40, max(40, h//20)),
                           Qt.AlignCenter, title)
            if difficulty_label and config.show_difficulty:
                p.setFont(QFont("Sans", max(10, w//45), QFont.Bold))
                p.setPen(Qt.white); dc = QColor(difficulty_color)
                bw2 = max(80, w//6); bh = max(22, w//35)
                bx2 = (w - bw2)//2; by2 = by - max(25, h//30)
                p.setBrush(dc)
                p.drawRoundedRect(bx2, by2, bw2, bh, bh//2, bh//2)
                p.drawText(QRect(bx2, by2, bw2, bh), Qt.AlignCenter, difficulty_label)
            if move_list_text and config.show_move_list:
                p.setFont(QFont("Courier", max(11, w//40), QFont.Bold))
                p.setPen(QColor(200, 200, 200))
                p.drawText(QRect(20, by+bw+max(12, h//40), w-40, max(30, h//20)),
                           Qt.AlignCenter, move_list_text)
            if turn_text:
                p.setFont(QFont("Sans", max(10, w//48)))
                p.setPen(accent)
                p.drawText(QRect(20, by+bw+max(45, h//18), w-40, max(24, h//30)),
                           Qt.AlignCenter, turn_text)
        else:
            ix, iy, iw, ih = config.info_rect
            if puzzle_title:
                p.setPen(Qt.white)
                p.setFont(QFont("Sans", max(14, iw//18), QFont.Bold))
                fm = QFontMetrics(p.font())
                title = fm.elidedText(puzzle_title, Qt.ElideRight, iw - 20)
                p.drawText(QRect(ix, iy, iw, max(36, ih//10)), Qt.AlignLeft, title)
            if difficulty_label and config.show_difficulty:
                p.setFont(QFont("Sans", max(10, iw//35), QFont.Bold))
                p.setPen(Qt.white); dc = QColor(difficulty_color)
                badge_w = max(80, iw//4); badge_h = max(22, iw//25)
                badge_y = iy + max(45, ih//8)
                p.setBrush(dc)
                p.drawRoundedRect(ix, badge_y, badge_w, badge_h, badge_h//2, badge_h//2)
                p.drawText(QRect(ix, badge_y, badge_w, badge_h), Qt.AlignCenter, difficulty_label)
            if move_list_text and config.show_move_list:
                p.setFont(QFont("Courier", max(11, iw//40), QFont.Bold))
                p.setPen(QColor(200, 200, 200))
                ml_y = iy + max(85, ih//5)
                p.drawText(QRect(ix, ml_y, iw, max(24, ih//15)), Qt.AlignLeft, move_list_text)
            if turn_text:
                p.setFont(QFont("Sans", max(10, iw//45)))
                p.setPen(accent)
                p.drawText(QRect(ix, iy + ih - max(40, ih//10), iw, max(24, ih//15)),
                           Qt.AlignLeft, turn_text)
            if phase_text:
                p.setFont(QFont("Sans", max(12, iw//30), QFont.Bold))
                p.setPen(accent)
                p.drawText(QRect(ix, iy + ih - max(70, ih//6), iw, max(28, ih//12)),
                           Qt.AlignCenter, phase_text)
        p.end()
        return img

    @staticmethod
    def _draw_piece(painter, piece, row, col, sz, font):
        is_white = piece.color == chess.WHITE
        sym_map = {'K':'♚','Q':'♛','R':'♜','B':'♝','N':'♞','P':'♟'}
        sym = sym_map.get(piece.symbol().upper(), '?')
        x, y = col * sz, row * sz
        painter.setFont(font)
        # Outline
        painter.setPen(QColor(0, 0, 0) if is_white else QColor(40, 40, 40))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    painter.drawText(QRect(x+dx, y+dy, sz, sz), Qt.AlignCenter, sym)
        painter.setPen(QColor(255, 255, 255) if is_white else QColor(30, 30, 30))
        painter.drawText(QRect(x, y, sz, sz), Qt.AlignCenter, sym)

    @staticmethod
    def _draw_piece_at(painter, piece, row_f, col, sz, w, h, font):
        is_white = piece.color == chess.WHITE
        sym_map = {'K':'♚','Q':'♛','R':'♜','B':'♝','N':'♞','P':'♟'}
        sym = sym_map.get(piece.symbol().upper(), '?')
        x, y = col * sz, int(row_f * sz)
        painter.setFont(font)
        painter.setPen(QColor(0, 0, 0) if is_white else QColor(40, 40, 40))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    painter.drawText(QRect(x+dx, y+dy, sz, sz), Qt.AlignCenter, sym)
        painter.setPen(QColor(255, 255, 255) if is_white else QColor(30, 30, 30))
        painter.drawText(QRect(x, y, sz, sz), Qt.AlignCenter, sym)

    @staticmethod
    def _draw_arrow(painter, x1, y1, x2, y2, color, sz):
        painter.setPen(QPen(color, max(2, sz // 12), Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(int(x1), int(y1), int(x2), int(y2))
        angle = math.atan2(y2 - y1, x2 - x1)
        arr_sz = max(6, sz // 6)
        p1 = QPointF(x2 - arr_sz * math.cos(angle - 0.4),
                      y2 - arr_sz * math.sin(angle - 0.4))
        p2 = QPointF(x2 - arr_sz * math.cos(angle + 0.4),
                      y2 - arr_sz * math.sin(angle + 0.4))
        tri = QPolygonF([QPointF(x2, y2), p1, p2])
        painter.setPen(Qt.NoPen); painter.setBrush(color)
        painter.drawPolygon(tri)

# ═══════════════════════════════════════════════════════════════════════════════
#  FRAME GENERATOR & VIDEO EXPORTER
# ═══════════════════════════════════════════════════════════════════════════════

class FrameGenerator:
    """Generate frames for a single puzzle video."""

    @staticmethod
    def generate_puzzle_frames(puzzle: Puzzle, config: VideoConfig,
                               callback: Optional[Callable[[int, int], None]] = None
                               ) -> List[np.ndarray]:
        engine = ChessEngine()
        if not engine.load_fen(puzzle.fen):
            return []
        frames: List[np.ndarray] = []
        fps = config.fps
        # Title card
        if config.show_title_card:
            for i in range(int(config.title_duration * fps)):
                t = i / max(1, int(config.title_duration * fps) - 1)
                img = BoardRenderer.render_full_frame(
                    engine.board, config, puzzle_title=puzzle.name,
                    difficulty_label=puzzle.tier_label,
                    difficulty_color=puzzle.tier_color,
                    theme_name=config.board_theme_name,
                    phase_text="Solve the puzzle" if t > 0.3 else "")
                frames.append(BoardRenderer._qimg_to_np(img))
        # Think phase
        think_frames = int(config.think_duration * fps)
        for i in range(think_frames):
            phase = "Thinking..." if i < think_frames * 0.7 else "Ready?"
            img = BoardRenderer.render_full_frame(
                engine.board, config, puzzle_title=puzzle.name,
                difficulty_label=puzzle.tier_label,
                difficulty_color=puzzle.tier_color,
                theme_name=config.board_theme_name, phase_text=phase)
            frames.append(BoardRenderer._qimg_to_np(img))
        # Solution moves
        if config.show_solution:
            for mi, uci_move in enumerate(puzzle.moves):
                info = engine.make_move_uci(uci_move)
                if not info: break
                move_frames = int(config.move_duration * fps)
                for fi in range(move_frames):
                    last_mv = (info.from_rc, info.to_rc)
                    img = BoardRenderer.render_full_frame(
                        engine.board, config, last_move=last_mv,
                        move_list_text=engine.san_move_list(),
                        puzzle_title=puzzle.name,
                        difficulty_label=puzzle.tier_label,
                        difficulty_color=puzzle.tier_color,
                        turn_text=engine.turn_name + " to move",
                        theme_name=config.board_theme_name)
                    frames.append(BoardRenderer._qimg_to_np(img))
                # Pause between moves
                pause_frames = int(config.pause_duration * fps)
                for fi in range(pause_frames):
                    last_mv = (info.from_rc, info.to_rc)
                    img = BoardRenderer.render_full_frame(
                        engine.board, config, last_move=last_mv,
                        move_list_text=engine.san_move_list(),
                        puzzle_title=puzzle.name,
                        difficulty_label=puzzle.tier_label,
                        difficulty_color=puzzle.tier_color,
                        theme_name=config.board_theme_name)
                    frames.append(BoardRenderer._qimg_to_np(img))
                if callback: callback(mi + 1, len(puzzle.moves))
        # End phase
        for i in range(int(config.end_duration * fps)):
            result_text = "Checkmate!" if engine.game_over and "0-1" not in engine.result and "1-0" not in engine.result else engine.result
            if not result_text: result_text = "Done"
            img = BoardRenderer.render_full_frame(
                engine.board, config,
                move_list_text=engine.san_move_list(),
                puzzle_title=puzzle.name,
                difficulty_label=puzzle.tier_label,
                difficulty_color=puzzle.tier_color,
                phase_text=result_text,
                theme_name=config.board_theme_name)
            frames.append(BoardRenderer._qimg_to_np(img))
        return frames

    @staticmethod
    def render_single_frame(puzzle: Puzzle, config: VideoConfig,
                            move_index: int = -1) -> QImage:
        """Render a single frame (for preview)."""
        engine = ChessEngine()
        if not engine.load_fen(puzzle.fen): return QImage()
        last_mv = None
        if move_index >= 0:
            for i, uci in enumerate(puzzle.moves[:move_index + 1]):
                info = engine.make_move_uci(uci)
                if info: last_mv = (info.from_rc, info.to_rc)
        return BoardRenderer.render_full_frame(
            engine.board, config, last_move=last_mv,
            move_list_text=engine.san_move_list(),
            puzzle_title=puzzle.name,
            difficulty_label=puzzle.tier_label,
            difficulty_color=puzzle.tier_color,
            theme_name=config.board_theme_name)

    @staticmethod
    def save_png_sequence(puzzle: Puzzle, config: VideoConfig,
                          output_dir: str, callback=None) -> int:
        """Save frames as PNG sequence. Returns count of frames saved."""
        engine = ChessEngine()
        if not engine.load_fen(puzzle.fen): return 0
        os.makedirs(output_dir, exist_ok=True)
        count = 0
        fps = config.fps
        # Title
        if config.show_title_card:
            for i in range(int(config.title_duration * fps)):
                img = BoardRenderer.render_full_frame(
                    engine.board, config, puzzle_title=puzzle.name,
                    difficulty_label=puzzle.tier_label,
                    difficulty_color=puzzle.tier_color,
                    theme_name=config.board_theme_name)
                path = os.path.join(output_dir, f"{count:06d}.png")
                img.save(path); count += 1
        # Think
        for i in range(int(config.think_duration * fps)):
            img = BoardRenderer.render_full_frame(
                engine.board, config, puzzle_title=puzzle.name,
                difficulty_label=puzzle.tier_label,
                difficulty_color=puzzle.tier_color,
                theme_name=config.board_theme_name, phase_text="Thinking...")
            path = os.path.join(output_dir, f"{count:06d}.png")
            img.save(path); count += 1
        # Moves
        if config.show_solution:
            for mi, uci_move in enumerate(puzzle.moves):
                info = engine.make_move_uci(uci_move)
                if not info: break
                for fi in range(int(config.move_duration * fps)):
                    last_mv = (info.from_rc, info.to_rc)
                    img = BoardRenderer.render_full_frame(
                        engine.board, config, last_move=last_mv,
                        move_list_text=engine.san_move_list(),
                        puzzle_title=puzzle.name,
                        difficulty_label=puzzle.tier_label,
                        difficulty_color=puzzle.tier_color,
                        theme_name=config.board_theme_name)
                    path = os.path.join(output_dir, f"{count:06d}.png")
                    img.save(path); count += 1
                if callback: callback(mi + 1, len(puzzle.moves))
        return count

    @staticmethod
    def save_board_png(puzzle: Puzzle, path: str, sq_size: int = 80,
                       theme_name: str = "Minimal", flipped: bool = False) -> bool:
        """Save just the board as a PNG image."""
        engine = ChessEngine()
        if not engine.load_fen(puzzle.fen): return False
        theme = THEMES.get(theme_name, THEMES["Minimal"])
        img = BoardRenderer.render(engine.board, sq_size=sq_size,
                                   theme=theme, flipped=flipped)
        return img.save(path)

# Add helper to BoardRenderer
@staticmethod
def _qimg_to_np(qimg: QImage) -> np.ndarray:
    qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.bits()
    ptr.setsize(h * w * 4)
    arr = np.frombuffer(ptr, np.uint8).reshape((h, w, 4)).copy()
    return arr[:, :, :3]  # drop alpha for video

BoardRenderer._qimg_to_np = _qimg_to_np

# ═══════════════════════════════════════════════════════════════════════════════
#  BATCH RENDER WORKER
# ═══════════════════════════════════════════════════════════════════════════════

class BatchRenderWorker(QThread):
    progress = Signal(int, int)       # current puzzle, total puzzles
    puzzle_progress = Signal(str)     # current puzzle name
    frame_count = Signal(int)         # frames rendered for current puzzle
    done = Signal(int)                # total rendered
    error = Signal(str)

    def __init__(self, puzzles: List[Puzzle], config: VideoConfig,
                 output_dir: str, export_type: str = "png"):
        super().__init__()
        self.puzzles = puzzles; self.config = config
        self.output_dir = output_dir; self.export_type = export_type
        self._cancel = False

    def cancel(self): self._cancel = True

    def run(self):
        total = len(self.puzzles); rendered = 0
        os.makedirs(self.output_dir, exist_ok=True)
        for i, puzzle in enumerate(self.puzzles):
            if self._cancel: break
            self.puzzle_progress.emit(puzzle.name)
            self.progress.emit(i, total)
            try:
                safe_name = puzzle.safe_filename()
                if self.export_type == "png_board":
                    path = os.path.join(self.output_dir, f"{safe_name}.png")
                    FrameGenerator.save_board_png(
                        puzzle, path, sq_size=80,
                        theme_name=self.config.board_theme_name)
                elif self.export_type == "png_seq":
                    pdir = os.path.join(self.output_dir, safe_name)
                    FrameGenerator.save_png_sequence(
                        puzzle, self.config, pdir)
                elif self.export_type == "mp4" and HAS_IMAGEIO:
                    frames = FrameGenerator.generate_puzzle_frames(puzzle, self.config)
                    if frames:
                        path = os.path.join(self.output_dir, f"{safe_name}.mp4")
                        iio.imwrite(path, frames, fps=self.config.fps,
                                    codec='libx264', quality=min(10, max(1, 11 - self.config.quality // 10)))
                elif self.export_type == "gif" and HAS_IMAGEIO:
                    frames = FrameGenerator.generate_puzzle_frames(puzzle, self.config)
                    if frames:
                        # Subsample for GIF size
                        step = max(1, len(frames) // 60)
                        frames_sub = frames[::step]
                        path = os.path.join(self.output_dir, f"{safe_name}.gif")
                        iio.imwrite(path, frames_sub, duration=int(1000 / self.config.fps * step),
                                    loop=0)
                elif self.export_type == "frame_preview":
                    # Just render a single preview frame per puzzle
                    img = FrameGenerator.render_single_frame(puzzle, self.config)
                    if not img.isNull():
                        path = os.path.join(self.output_dir, f"{safe_name}.png")
                        img.save(path)
                rendered += 1
            except Exception as e:
                log(f"Error rendering puzzle {puzzle.id}: {e}", "ERROR")
                continue
        self.done.emit(rendered)

# ═══════════════════════════════════════════════════════════════════════════════
#  VIRTUAL PUZZLE TABLE MODEL — For millions of rows
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleTableModel(QAbstractTableModel):
    COLUMNS = ["ID", "Name", "Rating", "Moves", "Difficulty", "Themes"]
    COL_KEYS = ["id", "name", "rating", "move_count", "difficulty", "themes"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._puzzles: List[Puzzle] = []
        self._filtered_ids: List[int] = []
        self._id_to_row: Dict[int, int] = {}
        self._chunk_size = 5000
        self._loaded_rows = 0

    def set_puzzles(self, puzzles: List[Puzzle]):
        self.beginResetModel()
        self._puzzles = puzzles
        self._filtered_ids = [p.id for p in puzzles]
        self._id_to_row = {p.id: i for i, p in enumerate(puzzles)}
        self._loaded_rows = min(self._chunk_size, len(puzzles))
        self.endResetModel()

    def set_filtered_ids(self, puzzles: List[Puzzle], ids: List[int]):
        self.beginResetModel()
        self._puzzles = puzzles
        self._filtered_ids = ids
        self._id_to_row = {pid: i for i, pid in enumerate(ids)}
        self._loaded_rows = min(self._chunk_size, len(ids))
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return min(self._loaded_rows, len(self._filtered_ids))

    def columnCount(self, parent=QModelIndex()): return len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.COLUMNS[section]
        return None

    def canFetchMore(self, parent=QModelIndex()):
        return self._loaded_rows < len(self._filtered_ids)

    def fetchMore(self, parent=QModelIndex()):
        remaining = len(self._filtered_ids) - self._loaded_rows
        to_fetch = min(remaining, self._chunk_size)
        self.beginInsertRows(parent, self._loaded_rows,
                             self._loaded_rows + to_fetch - 1)
        self._loaded_rows += to_fetch
        self.endInsertRows()

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        row = index.row()
        if row >= len(self._filtered_ids): return None
        pid = self._filtered_ids[row]
        # Find puzzle
        p = None
        if 0 <= pid - 1 < len(self._puzzles) and self._puzzles[pid - 1].id == pid:
            p = self._puzzles[pid - 1]
        else:
            for pp in self._puzzles:
                if pp.id == pid: p = pp; break
        if not p: return None
        col = index.column()
        key = self.COL_KEYS[col]
        if role == Qt.DisplayRole:
            if key == "rating": return str(p.rating) if p.rating else "—"
            if key == "difficulty": return f"{p.difficulty:.0%}"
            if key == "themes": return ", ".join(sorted(p.themes)[:3])
            return str(getattr(p, key, ""))
        elif role == Qt.UserRole:
            return pid
        elif role == Qt.ForegroundRole:
            if key == "difficulty":
                return QColor(p.tier_color)
        return None

    def puzzle_at_row(self, row: int) -> Optional[int]:
        if 0 <= row < len(self._filtered_ids):
            return self._filtered_ids[row]
        return None

    def total_count(self) -> int: return len(self._filtered_ids)

# ═══════════════════════════════════════════════════════════════════════════════
#  CHESS BOARD WIDGET
# ═══════════════════════════════════════════════════════════════════════════════

class ChessBoardWidget(QWidget):
    puzzle_selected = Signal(object)
    move_made = Signal(MoveInfo)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = ChessEngine()
        self.theme = THEMES["Minimal"]
        self.flipped = False
        self.selected_sq = None
        self.legal_targets_list = None
        self.anim_timer = QTimer()
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._anim_tick)
        self.anim_state = None
        self.anim_start_time = 0
        self.anim_duration = ANIM_SPEED_DEFAULT
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.sound = None
        self._puzzle_mode = False
        self._puzzle_moves: List[str] = []
        self._puzzle_move_idx = 0

    def set_sound(self, sound: SoundManager): self.sound = sound
    def set_theme(self, name: str): self.theme = THEMES.get(name, THEMES["Minimal"]); self.update()
    def flip(self): self.flipped = not self.flipped; self.update()

    def load_puzzle(self, puzzle: Puzzle):
        self.engine.load_fen(puzzle.fen)
        self._puzzle_mode = True
        self._puzzle_moves = list(puzzle.moves)
        self._puzzle_move_idx = 0
        self.selected_sq = None; self.legal_targets_list = None
        self.update()

    def next_puzzle_move(self) -> bool:
        if self._puzzle_mode and self._puzzle_move_idx < len(self._puzzle_moves):
            uci = self._puzzle_moves[self._puzzle_move_idx]
            info = self.engine.make_move_uci(uci)
            if info:
                self._puzzle_move_idx += 1
                if self.sound:
                    if info.is_mate: self.sound.play("checkmate")
                    elif info.is_check: self.sound.play("check")
                    elif info.captured != '.': self.sound.play("capture")
                    else: self.sound.play("move")
                self.move_made.emit(info)
            self.update()
            return True
        return False

    def prev_puzzle_move(self) -> bool:
        if self.engine.move_history:
            self.engine.undo()
            if self._puzzle_move_idx > 0: self._puzzle_move_idx -= 1
            self.update(); return True
        return False

    def reset_puzzle(self):
        self.engine.reset_to_initial()
        self._puzzle_move_idx = 0
        self.selected_sq = None; self.legal_targets_list = None
        self.update()

    def _sq_size(self): return min(self.width(), self.height()) // 8

    def paintEvent(self, event):
        sz = self._sq_size()
        img = BoardRenderer.render(
            self.engine.board, last_move=self.engine.last_move,
            selected=self.selected_sq,
            legal_targets=self.legal_targets_list,
            check_squares=self.engine.check_squares(),
            anim_state=self.anim_state,
            sq_size=sz, theme=self.theme, flipped=self.flipped)
        painter = QPainter(self)
        ox = (self.width() - sz * 8) // 2
        oy = (self.height() - sz * 8) // 2
        painter.drawImage(ox, oy, img)
        painter.end()

    def mousePressEvent(self, event):
        sz = self._sq_size()
        ox = (self.width() - sz * 8) // 2
        oy = (self.height() - sz * 8) // 2
        mx, my = event.position().x() - ox, event.position().y() - oy
        if mx < 0 or my < 0 or mx >= sz * 8 or my >= sz * 8: return
        if self.flipped: col, row = int(mx // sz), int(my // sz)
        else: col, row = int(mx // sz), int(my // sz)
        if self.flipped: r, c = 7 - row, 7 - col
        else: r, c = row, col
        self._handle_click(r, c)

    def _handle_click(self, r, c):
        if self.engine.game_over: return
        piece = self.engine.board.piece_at(ChessEngine.rc_to_sq(r, c))
        if self.selected_sq:
            sr, sc = self.selected_sq
            if (r, c) in (self.legal_targets_list or []):
                promo = None
                if self.engine.is_promotion(sr, sc, r, c):
                    promo = chess.QUEEN
                info = self.engine.make_move(sr, sc, r, c, promo)
                if info and self.sound:
                    if info.is_mate: self.sound.play("checkmate")
                    elif info.is_check: self.sound.play("check")
                    elif info.captured != '.': self.sound.play("capture")
                    elif info.is_castle: self.sound.play("castle")
                    else: self.sound.play("move")
                self.selected_sq = None; self.legal_targets_list = None
                self.update(); return
            elif piece and piece.color == self.engine.board.turn:
                self.selected_sq = (r, c)
                self.legal_targets_list = self.engine.legal_targets(r, c)
                self.update(); return
            else:
                self.selected_sq = None; self.legal_targets_list = None
                self.update(); return
        if piece and piece.color == self.engine.board.turn:
            self.selected_sq = (r, c)
            self.legal_targets_list = self.engine.legal_targets(r, c)
            if self.sound: self.sound.play("start")
        self.update()

    def _anim_tick(self):
        if not self.anim_state: self.anim_timer.stop(); return
        elapsed = time.time() - self.anim_start_time
        progress = min(1.0, elapsed / (self.anim_duration / 1000.0))
        self.anim_state['progress'] = progress
        if progress >= 1.0:
            self.anim_state = None; self.anim_timer.stop()
        self.update()

# ═══════════════════════════════════════════════════════════════════════════════
#  BATCH RENDER DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class BatchRenderDialog(QDialog):
    def __init__(self, puzzles: List[Puzzle], config: VideoConfig, parent=None):
        super().__init__(parent)
        self.puzzles = puzzles; self.config = copy.deepcopy(config)
        self.worker = None
        self.setWindowTitle("Batch Render")
        self.setMinimumSize(520, 480)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Info
        info = QLabel(f"Puzzles to render: {len(self.puzzles):,}")
        info.setStyleSheet("font-weight:600; font-size:14px;")
        layout.addWidget(info)

        # Export type
        type_group = QGroupBox("Export Type")
        type_layout = QVBoxLayout(type_group)
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "Board PNG (fast)",
            "Preview Frame PNG",
            "PNG Sequence (full video frames)",
            "MP4 Video" if HAS_IMAGEIO else "MP4 Video (install imageio)",
            "GIF" if HAS_IMAGEIO else "GIF (install imageio)",
        ])
        self.type_combo.setCurrentIndex(0)
        type_layout.addWidget(self.type_combo)
        layout.addWidget(type_group)

        # Video preset
        preset_group = QGroupBox("Video Preset")
        preset_layout = QFormLayout(preset_group)
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(EXPORT_PRESETS.keys()))
        self.preset_combo.setCurrentText("YouTube 1080p")
        preset_layout.addRow("Preset:", self.preset_combo)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEMES.keys()))
        self.theme_combo.setCurrentText("Minimal")
        preset_layout.addRow("Board Theme:", self.theme_combo)
        layout.addWidget(preset_group)

        # Output
        out_group = QGroupBox("Output")
        out_layout = QHBoxLayout(out_group)
        self.out_edit = QLineEdit(os.path.join(DATA_DIR, "batch_output"))
        out_btn = QPushButton("Browse…")
        out_btn.clicked.connect(self._browse_output)
        out_layout.addWidget(self.out_edit, 1)
        out_layout.addWidget(out_btn)
        layout.addWidget(out_group)

        # Progress
        prog_group = QGroupBox("Progress")
        prog_layout = QVBoxLayout(prog_group)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        prog_layout.addWidget(self.progress_bar)
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color:#868E96;")
        prog_layout.addWidget(self.status_label)
        layout.addWidget(prog_group)

        # Buttons
        btn_layout = QHBoxLayout()
        self.render_btn = QPushButton("Start Render")
        self.render_btn.setProperty("accent", True)
        self.render_btn.clicked.connect(self._start_render)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel_render)
        self.cancel_btn.setEnabled(False)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.render_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Output Directory")
        if d: self.out_edit.setText(d)

    def _get_export_type(self) -> str:
        idx = self.type_combo.currentIndex()
        return ["png_board", "frame_preview", "png_seq", "mp4", "gif"][idx]

    def _start_render(self):
        preset_name = self.preset_combo.currentText()
        self.config = copy.deepcopy(EXPORT_PRESETS.get(preset_name, VideoConfig()))
        self.config.board_theme_name = self.theme_combo.currentText()
        output_dir = self.out_edit.text()
        if not output_dir:
            QMessageBox.warning(self, "Error", "Set output directory"); return
        export_type = self._get_export_type()
        self.worker = BatchRenderWorker(self.puzzles, self.config, output_dir, export_type)
        self.worker.progress.connect(self._on_progress)
        self.worker.puzzle_progress.connect(self._on_puzzle)
        self.worker.done.connect(self._on_done)
        self.worker.error.connect(self._on_error)
        self.worker.start()
        self.render_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status_label.setText("Rendering…")

    def _cancel_render(self):
        if self.worker: self.worker.cancel()
        self.status_label.setText("Cancelling…")

    def _on_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def _on_puzzle(self, name):
        self.status_label.setText(f"Rendering: {name}")

    def _on_done(self, count):
        self.status_label.setText(f"Done! Rendered {count} puzzles.")
        self.render_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(self.progress_bar.maximum())

    def _on_error(self, msg):
        self.status_label.setText(f"Error: {msg}")
        self.render_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

# ═══════════════════════════════════════════════════════════════════════════════
#  LOAD DATABASE DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class LoadDatabaseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Load Puzzle Database")
        self.setMinimumSize(500, 400)
        self.worker = None
        self._puzzles: List[Puzzle] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # File
        file_group = QGroupBox("Source File")
        file_layout = QHBoxLayout(file_group)
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Select CSV, TSV, or JSON file…")
        file_btn = QPushButton("Browse…")
        file_btn.clicked.connect(self._browse)
        file_layout.addWidget(self.file_edit, 1)
        file_layout.addWidget(file_btn)
        layout.addWidget(file_group)

        # Format
        fmt_group = QGroupBox("Format")
        fmt_layout = QFormLayout(fmt_group)
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(["Auto-detect", "Lichess CSV", "Custom CSV/TSV", "JSON"])
        fmt_layout.addRow("Format:", self.fmt_combo)
        layout.addWidget(fmt_group)

        # Limits
        limit_group = QGroupBox("Limits (for large databases)")
        limit_layout = QFormLayout(limit_group)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 10000000)
        self.limit_spin.setValue(0)
        self.limit_spin.setSpecialValueText("No limit")
        self.limit_spin.setToolTip("0 = no limit, load all puzzles")
        limit_layout.addRow("Max puzzles:", self.limit_spin)
        self.skip_spin = QSpinBox()
        self.skip_spin.setRange(0, 10000000)
        self.skip_spin.setValue(0)
        limit_layout.addRow("Skip first:", self.skip_spin)
        layout.addWidget(limit_group)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color:#868E96;")
        layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()
        self.load_btn = QPushButton("Load")
        self.load_btn.setProperty("accent", True)
        self.load_btn.clicked.connect(self._start_load)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel_load)
        self.cancel_btn.setEnabled(False)
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.load_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.ok_btn)
        layout.addLayout(btn_layout)

    def _browse(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Open Puzzle Database", "",
            "Database Files (*.csv *.tsv *.json *.pzl);;All Files (*)")
        if f: self.file_edit.setText(f)

    def _start_load(self):
        path = self.file_edit.text()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "Error", "Select a valid file"); return
        fmt_idx = self.fmt_combo.currentIndex()
        fmt_map = {0: "auto", 1: "csv", 2: "csv", 3: "json"}
        fmt = fmt_map.get(fmt_idx, "auto")
        self.worker = LoadWorker(path, fmt, self.limit_spin.value(), self.skip_spin.value())
        self.worker.progress.connect(self._on_progress)
        self.worker.loaded.connect(self._on_loaded)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()
        self.load_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.ok_btn.setEnabled(False)
        self.status_label.setText("Loading…")

    def _cancel_load(self):
        if self.worker: self.worker.cancel()
        self.status_label.setText("Cancelling…")

    def _on_progress(self, current, total):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
            self.status_label.setText(f"Loading… {current:,} / {total:,}")

    def _on_loaded(self, count):
        self.status_label.setText(f"Loaded {count:,} puzzles")

    def _on_finished(self):
        if self.worker:
            self._puzzles = self.worker.puzzles
        self.load_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.ok_btn.setEnabled(len(self._puzzles) > 0)
        self.progress_bar.setValue(self.progress_bar.maximum())

    def _on_error(self, msg):
        self.status_label.setText(f"Error: {msg}")
        self.load_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def get_puzzles(self) -> List[Puzzle]:
        return self._puzzles

# ═══════════════════════════════════════════════════════════════════════════════
#  FILTER PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class FilterPanel(QWidget):
    filter_changed = Signal(FilterCriteria)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._themes: List[str] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        # Search
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search puzzles…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._emit)
        layout.addWidget(QLabel("Search"))
        layout.addWidget(self.search_edit)

        # Rating range
        layout.addWidget(QLabel("Rating"))
        rl = QHBoxLayout()
        self.rating_lo = QSpinBox(); self.rating_lo.setRange(0, 3500); self.rating_lo.setValue(0)
        self.rating_hi = QSpinBox(); self.rating_hi.setRange(0, 3500); self.rating_hi.setValue(3500)
        rl.addWidget(self.rating_lo); rl.addWidget(QLabel("–")); rl.addWidget(self.rating_hi)
        layout.addLayout(rl)
        self.rating_lo.valueChanged.connect(self._emit)
        self.rating_hi.valueChanged.connect(self._emit)
        self.require_rating_cb = QCheckBox("Has rating")
        self.require_rating_cb.stateChanged.connect(self._emit)
        layout.addWidget(self.require_rating_cb)

        # Move count range
        layout.addWidget(QLabel("Moves"))
        ml = QHBoxLayout()
        self.moves_lo = QSpinBox(); self.moves_lo.setRange(1, 50); self.moves_lo.setValue(1)
        self.moves_hi = QSpinBox(); self.moves_hi.setRange(1, 50); self.moves_hi.setValue(50)
        ml.addWidget(self.moves_lo); ml.addWidget(QLabel("–")); ml.addWidget(self.moves_hi)
        layout.addLayout(ml)
        self.moves_lo.valueChanged.connect(self._emit)
        self.moves_hi.valueChanged.connect(self._emit)

        # Theme filter
        layout.addWidget(QLabel("Theme"))
        self.theme_edit = QLineEdit()
        self.theme_edit.setPlaceholderText("Type theme tag…")
        self.theme_edit.setClearButtonEnabled(True)
        self.theme_edit.textChanged.connect(self._emit)
        layout.addWidget(self.theme_edit)

        # Sort
        layout.addWidget(QLabel("Sort"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Default", "Name ↑", "Name ↓",
                                   "Difficulty ↑", "Difficulty ↓",
                                   "Rating ↑", "Rating ↓",
                                   "Moves ↑", "Moves ↓"])
        self.sort_combo.currentIndexChanged.connect(self._emit)
        layout.addWidget(self.sort_combo)

        layout.addStretch()

    def set_themes(self, themes: List[str]):
        self._themes = themes

    def _emit(self):
        sort_modes = [
            SortMode.DEFAULT, SortMode.NAME_ASC, SortMode.NAME_DESC,
            SortMode.DIFFICULTY_ASC, SortMode.DIFFICULTY_DESC,
            SortMode.RATING_ASC, SortMode.RATING_DESC,
            SortMode.MOVES_ASC, SortMode.MOVES_DESC,
        ]
        theme_text = self.theme_edit.text().strip()
        theme_tags = frozenset(t.strip() for t in theme_text.split() if t.strip()) if theme_text else frozenset()
        criteria = FilterCriteria(
            text_query=self.search_edit.text().strip(),
            rating_range=(self.rating_lo.value(), self.rating_hi.value()),
            move_count_range=(self.moves_lo.value(), self.moves_hi.value()),
            theme_tags=theme_tags,
            sort_mode=sort_modes[self.sort_combo.currentIndex()],
            require_rating=self.require_rating_cb.isChecked(),
        )
        self.filter_changed.emit(criteria)

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE BROWSER PANEL — Virtual table for millions of rows
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleBrowserPanel(QWidget):
    puzzle_activated = Signal(object)  # Puzzle

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = PuzzleTableModel()
        self._puzzles: List[Puzzle] = []
        self._puzzle_map: Dict[int, Puzzle] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(4)

        # Count label
        self.count_label = QLabel("0 puzzles")
        self.count_label.setStyleSheet("font-weight:600; color:#2D7D9A; padding:4px;")
        layout.addWidget(self.count_label)

        # Table
        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table)

        # Buttons
        btn_layout = QHBoxLayout()
        self.render_selected_btn = QPushButton("Render Selected")
        self.render_selected_btn.setProperty("accent", True)
        self.render_selected_btn.setEnabled(False)
        btn_layout.addWidget(self.render_selected_btn)
        self.render_all_btn = QPushButton("Render All Filtered")
        self.render_all_btn.setEnabled(False)
        btn_layout.addWidget(self.render_all_btn)
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(self.select_all_btn)
        layout.addLayout(btn_layout)

    def set_puzzles(self, puzzles: List[Puzzle]):
        self._puzzles = puzzles
        self._puzzle_map = {p.id: p for p in puzzles}
        self._model.set_puzzles(puzzles)
        self.count_label.setText(f"{len(puzzles):,} puzzles")

    def set_filtered_ids(self, ids: List[int]):
        self._model.set_filtered_ids(self._puzzles, ids)
        self.count_label.setText(f"{len(ids):,} shown of {len(self._puzzles):,}")

    def get_selected_puzzles(self) -> List[Puzzle]:
        indexes = self.table.selectionModel().selectedRows()
        result = []
        for idx in indexes:
            pid = self._model.puzzle_at_row(idx.row())
            if pid is not None and pid in self._puzzle_map:
                result.append(self._puzzle_map[pid])
        return result

    def get_all_filtered_puzzles(self) -> List[Puzzle]:
        result = []
        for pid in self._model._filtered_ids:
            if pid in self._puzzle_map:
                result.append(self._puzzle_map[pid])
        return result

    def _on_double_click(self, index):
        pid = self._model.puzzle_at_row(index.row())
        if pid is not None and pid in self._puzzle_map:
            self.puzzle_activated.emit(self._puzzle_map[pid])

    def _select_all(self):
        self.table.selectAll()

# ═══════════════════════════════════════════════════════════════════════════════
#  VIDEO EDITOR PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class VideoEditorPanel(QWidget):
    render_requested = Signal(VideoConfig)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = VideoConfig()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Preset
        form = QFormLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(EXPORT_PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(self._on_preset)
        form.addRow("Preset:", self.preset_combo)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEMES.keys()))
        self.theme_combo.currentTextChanged.connect(self._update_config)
        form.addRow("Board Theme:", self.theme_combo)

        self.flip_cb = QCheckBox("Flip Board")
        self.flip_cb.stateChanged.connect(self._update_config)
        form.addRow(self.flip_cb)

        self.title_cb = QCheckBox("Show Title Card")
        self.title_cb.setChecked(True)
        self.title_cb.stateChanged.connect(self._update_config)
        form.addRow(self.title_cb)

        self.solution_cb = QCheckBox("Show Solution")
        self.solution_cb.setChecked(True)
        self.solution_cb.stateChanged.connect(self._update_config)
        form.addRow(self.solution_cb)

        self.movelist_cb = QCheckBox("Show Move List")
        self.movelist_cb.setChecked(True)
        self.movelist_cb.stateChanged.connect(self._update_config)
        form.addRow(self.movelist_cb)

        self.difficulty_cb = QCheckBox("Show Difficulty")
        self.difficulty_cb.setChecked(True)
        self.difficulty_cb.stateChanged.connect(self._update_config)
        form.addRow(self.difficulty_cb)

        # Durations
        self.think_spin = QDoubleSpinBox()
        self.think_spin.setRange(0.5, 10.0); self.think_spin.setValue(3.0); self.think_spin.setSingleStep(0.5)
        self.think_spin.valueChanged.connect(self._update_config)
        form.addRow("Think (s):", self.think_spin)

        self.move_spin = QDoubleSpinBox()
        self.move_spin.setRange(0.2, 5.0); self.move_spin.setValue(0.8); self.move_spin.setSingleStep(0.1)
        self.move_spin.valueChanged.connect(self._update_config)
        form.addRow("Move (s):", self.move_spin)

        self.pause_spin = QDoubleSpinBox()
        self.pause_spin.setRange(0.0, 5.0); self.pause_spin.setValue(2.0); self.pause_spin.setSingleStep(0.5)
        self.pause_spin.valueChanged.connect(self._update_config)
        form.addRow("Pause (s):", self.pause_spin)

        layout.addLayout(form)

        # Custom title
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Override title (optional)")
        self.title_edit.textChanged.connect(self._update_config)
        layout.addWidget(QLabel("Title Override"))
        layout.addWidget(self.title_edit)

        layout.addStretch()

        # Render current
        self.render_btn = QPushButton("Render Current Puzzle")
        self.render_btn.setProperty("accent", True)
        layout.addWidget(self.render_btn)

    def _on_preset(self, name):
        if name in EXPORT_PRESETS:
            self.config = copy.deepcopy(EXPORT_PRESETS[name])
            self._update_config()

    def _update_config(self):
        self.config.board_theme_name = self.theme_combo.currentText()
        self.config.flip_board = self.flip_cb.isChecked()
        self.config.show_title_card = self.title_cb.isChecked()
        self.config.show_solution = self.solution_cb.isChecked()
        self.config.show_move_list = self.movelist_cb.isChecked()
        self.config.show_difficulty = self.difficulty_cb.isChecked()
        self.config.think_duration = self.think_spin.value()
        self.config.move_duration = self.move_spin.value()
        self.config.pause_duration = self.pause_spin.value()
        self.config.title_text = self.title_edit.text()

    def get_config(self) -> VideoConfig:
        self._update_config()
        return copy.deepcopy(self.config)

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE INFO PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleInfoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._puzzle: Optional[Puzzle] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        self.title_label = QLabel("No puzzle selected")
        self.title_label.setStyleSheet("font-weight:700; font-size:16px; color:#212529;")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        # Meta
        meta_layout = QGridLayout()
        self.rating_label = QLabel("—")
        self.difficulty_label = QLabel("—")
        self.moves_label = QLabel("—")
        self.themes_label = QLabel("—")
        self.opening_label = QLabel("—")
        self.fen_label = QLabel("—")
        self.fen_label.setWordWrap(True)
        self.fen_label.setStyleSheet("font-family:monospace; font-size:11px; color:#868E96;")

        meta_layout.addWidget(QLabel("Rating:"), 0, 0)
        meta_layout.addWidget(self.rating_label, 0, 1)
        meta_layout.addWidget(QLabel("Difficulty:"), 1, 0)
        meta_layout.addWidget(self.difficulty_label, 1, 1)
        meta_layout.addWidget(QLabel("Moves:"), 2, 0)
        meta_layout.addWidget(self.moves_label, 2, 1)
        meta_layout.addWidget(QLabel("Opening:"), 3, 0)
        meta_layout.addWidget(self.opening_label, 3, 1)
        layout.addLayout(meta_layout)

        layout.addWidget(QLabel("Themes:"))
        self.themes_label.setWordWrap(True)
        self.themes_label.setStyleSheet("color:#2D7D9A;")
        layout.addWidget(self.themes_label)

        layout.addWidget(QLabel("FEN:"))
        layout.addWidget(self.fen_label)

        # Move list
        self.move_list_label = QLabel("")
        self.move_list_label.setWordWrap(True)
        self.move_list_label.setStyleSheet("font-family:monospace; font-size:12px; padding:6px; background:#FFF; border:1px solid #DEE2E6; border-radius:4px;")
        layout.addWidget(QLabel("Solution:"))
        layout.addWidget(self.move_list_label)

        layout.addStretch()

    def set_puzzle(self, puzzle: Optional[Puzzle]):
        self._puzzle = puzzle
        if not puzzle:
            self.title_label.setText("No puzzle selected")
            self.rating_label.setText("—")
            self.difficulty_label.setText("—")
            self.moves_label.setText("—")
            self.themes_label.setText("—")
            self.opening_label.setText("—")
            self.fen_label.setText("—")
            self.move_list_label.setText("")
            return
        self.title_label.setText(puzzle.name)
        self.rating_label.setText(str(puzzle.rating) if puzzle.rating else "—")
        self.difficulty_label.setText(puzzle.tier_label)
        self.difficulty_label.setStyleSheet(f"color:{puzzle.tier_color}; font-weight:600;")
        self.moves_label.setText(str(puzzle.move_count))
        self.themes_label.setText(", ".join(sorted(puzzle.themes)))
        self.opening_label.setText(puzzle.opening or "—")
        self.fen_label.setText(puzzle.fen)
        # Build move notation
        engine = ChessEngine()
        engine.load_fen(puzzle.fen)
        notations = []
        for uci in puzzle.moves:
            info = engine.make_move_uci(uci)
            if info: notations.append(info.notation)
        self.move_list_label.setText(" ".join(notations))

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chess Puzzle Studio")
        self.setMinimumSize(1200, 750)
        self.collection = PuzzleCollection()
        self.sound = SoundManager()
        self.current_puzzle: Optional[Puzzle] = None
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(300)
        self._filter_timer.timeout.connect(self._apply_filter)
        self._build_ui()
        self._build_toolbar()
        self._build_statusbar()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(0); main_layout.setContentsMargins(0, 0, 0, 0)

        # Left: Filter + Browser
        left_splitter = QSplitter(Qt.Vertical)
        self.filter_panel = FilterPanel()
        self.filter_panel.filter_changed.connect(self._on_filter_changed)
        left_splitter.addWidget(self.filter_panel)

        self.browser = PuzzleBrowserPanel()
        self.browser.puzzle_activated.connect(self._on_puzzle_activated)
        self.browser.render_selected_btn.clicked.connect(self._render_selected)
        self.browser.render_all_btn.clicked.connect(self._render_all_filtered)
        left_splitter.addWidget(self.browser)
        left_splitter.setSizes([250, 500])
        left_splitter.setMinimumWidth(360)

        # Center: Board
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(8, 8, 8, 8)
        self.board = ChessBoardWidget()
        self.board.set_sound(self.sound)
        center_layout.addWidget(self.board, 1)

        # Board controls
        ctrl = QHBoxLayout()
        self.flip_btn = QPushButton("Flip")
        self.flip_btn.clicked.connect(self.board.flip)
        self.prev_btn = QPushButton("◀ Prev Move")
        self.prev_btn.clicked.connect(self.board.prev_puzzle_move)
        self.next_btn = QPushButton("Next Move ▶")
        self.next_btn.clicked.connect(self.board.next_puzzle_move)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self.board.reset_puzzle)
        ctrl.addWidget(self.flip_btn)
        ctrl.addWidget(self.prev_btn)
        ctrl.addWidget(self.next_btn)
        ctrl.addWidget(self.reset_btn)
        center_layout.addLayout(ctrl)

        # Right: Tabs (Info + Video)
        right_tabs = QTabWidget()
        self.info_panel = PuzzleInfoPanel()
        right_tabs.addTab(self.info_panel, "Info")
        self.video_panel = VideoEditorPanel()
        self.video_panel.render_btn.clicked.connect(self._render_current)
        right_tabs.addTab(self.video_panel, "Video")
        right_tabs.setMinimumWidth(280)

        # Main splitter
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(center_widget)
        main_splitter.addWidget(right_tabs)
        main_splitter.setSizes([360, 500, 300])

        main_layout.addWidget(main_splitter)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        load_db_action = QAction("Load Database", self)
        load_db_action.setToolTip("Load a puzzle database (supports 5M+ puzzles)")
        load_db_action.triggered.connect(self._load_database)
        tb.addAction(load_db_action)

        load_json_action = QAction("Load JSON", self)
        load_json_action.triggered.connect(self._load_json)
        tb.addAction(load_json_action)

        save_action = QAction("Save JSON", self)
        save_action.triggered.connect(self._save_json)
        tb.addAction(save_action)

        tb.addSeparator()

        batch_action = QAction("Batch Render", self)
        batch_action.setToolTip("Batch render puzzles as videos/images")
        batch_action.triggered.connect(self._render_all_filtered)
        tb.addAction(batch_action)

        tb.addSeparator()

        clear_action = QAction("Clear All", self)
        clear_action.triggered.connect(self._clear_all)
        tb.addAction(clear_action)

    def _build_statusbar(self):
        self.statusBar().showMessage("Ready — Load a database to get started")

    # ─── Actions ───

    def _load_database(self):
        dlg = LoadDatabaseDialog(self)
        if dlg.exec() == QDialog.Accepted:
            puzzles = dlg.get_puzzles()
            if puzzles:
                self.collection.clear()
                self.collection.add_many(puzzles)
                self.collection.build_index()
                self.browser.set_puzzles(self.collection.puzzles)
                if self.collection.index:
                    self.filter_panel.set_themes(self.collection.index.all_themes)
                self.statusBar().showMessage(
                    f"Loaded {len(puzzles):,} puzzles | {len(self.collection.index.all_themes)} themes")
                log(f"Database loaded: {len(puzzles):,} puzzles")

    def _load_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open JSON", "", "JSON Files (*.json);;All Files (*)")
        if path:
            self.collection.clear()
            count = self.collection.load_json(path)
            self.collection.build_index()
            self.browser.set_puzzles(self.collection.puzzles)
            if self.collection.index:
                self.filter_panel.set_themes(self.collection.index.all_themes)
            self.statusBar().showMessage(f"Loaded {count:,} puzzles from JSON")

    def _save_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save JSON", "", "JSON Files (*.json)")
        if path:
            self.collection.save_json(path)
            self.statusBar().showMessage(f"Saved {self.collection.count:,} puzzles")

    def _clear_all(self):
        if self.collection.count > 0:
            r = QMessageBox.question(
                self, "Clear", f"Clear all {self.collection.count:,} puzzles?")
            if r != QMessageBox.Yes: return
        self.collection.clear()
        self.browser.set_puzzles([])
        self.current_puzzle = None
        self.info_panel.set_puzzle(None)
        self.board.engine.reset()
        self.board.update()
        self.statusBar().showMessage("Cleared")

    def _on_filter_changed(self, criteria: FilterCriteria):
        self._filter_timer.start()

    def _apply_filter(self):
        if not self.collection.index: return
        criteria = FilterCriteria(
            text_query=self.filter_panel.search_edit.text().strip(),
            rating_range=(self.filter_panel.rating_lo.value(),
                          self.filter_panel.rating_hi.value()),
            move_count_range=(self.filter_panel.moves_lo.value(),
                              self.filter_panel.moves_hi.value()),
            theme_tags=frozenset(t.strip() for t in
                                  self.filter_panel.theme_edit.text().split() if t.strip()),
            sort_mode=[SortMode.DEFAULT, SortMode.NAME_ASC, SortMode.NAME_DESC,
                       SortMode.DIFFICULTY_ASC, SortMode.DIFFICULTY_DESC,
                       SortMode.RATING_ASC, SortMode.RATING_DESC,
                       SortMode.MOVES_ASC, SortMode.MOVES_DESC][
                          self.filter_panel.sort_combo.currentIndex()],
            require_rating=self.filter_panel.require_rating_cb.isChecked(),
        )
        ids = self.collection.filter(criteria)
        self.browser.set_filtered_ids(ids)
        self.browser.render_selected_btn.setEnabled(True)
        self.browser.render_all_btn.setEnabled(True)

    def _on_puzzle_activated(self, puzzle: Puzzle):
        self.current_puzzle = puzzle
        self.board.load_puzzle(puzzle)
        self.info_panel.set_puzzle(puzzle)
        self.statusBar().showMessage(f"Loaded: {puzzle.name} (Rating: {puzzle.rating or '?'})")

    def _render_current(self):
        if not self.current_puzzle:
            QMessageBox.information(self, "Info", "Select a puzzle first"); return
        config = self.video_panel.get_config()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Video", self.current_puzzle.safe_filename(),
            "PNG (*.png);;MP4 (*.mp4)" if HAS_IMAGEIO else "PNG (*.png)")
        if not path: return
        if path.endswith('.png'):
            if path.endswith('_board.png') or 'board' in path:
                FrameGenerator.save_board_png(self.current_puzzle, path,
                                              theme_name=config.board_theme_name)
            else:
                img = FrameGenerator.render_single_frame(self.current_puzzle, config)
                img.save(path)
        elif path.endswith('.mp4') and HAS_IMAGEIO:
            frames = FrameGenerator.generate_puzzle_frames(self.current_puzzle, config)
            iio.imwrite(path, frames, fps=config.fps, codec='libx264')
        self.statusBar().showMessage(f"Saved: {path}")

    def _render_selected(self):
        selected = self.browser.get_selected_puzzles()
        if not selected:
            QMessageBox.information(self, "Info", "Select puzzles in the table first"); return
        config = self.video_panel.get_config()
        dlg = BatchRenderDialog(selected, config, self)
        dlg.exec()

    def _render_all_filtered(self):
        all_puzzles = self.browser.get_all_filtered_puzzles()
        if not all_puzzles:
            QMessageBox.information(self, "Info", "No puzzles to render"); return
        config = self.video_panel.get_config()
        dlg = BatchRenderDialog(all_puzzles, config, self)
        dlg.exec()

    def closeEvent(self, event):
        self.sound.cleanup()
        event.accept()

# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    Palette.apply(app)
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()