#!/usr/bin/env python3
"""
main_window.py — Main window with tabs (Settings, Export, Random), sound packs,
minimalist dark theme, filtering, pagination, batch export, FFmpeg export,
auto-save/load. Interactive board play removed.
"""

import os
import re
import json
import random
import threading

import chess

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSlider, QComboBox, QCheckBox, QGroupBox, QSplitter,
    QStatusBar, QLineEdit, QApplication, QProgressBar, QSpinBox,
    QFileDialog, QFrame, QTabWidget, QScrollArea, QMessageBox,
    QDialog, QDialogButtonBox,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont

from config import (
    THEMES, EXPORT_PRESETS, ExportConfig, ExportManifest,
    DATA_DIR, EXPORT_DIR, LICHESS_DB_PATH, EXPORT_MANIFEST_PATH,
    PUZZLES_PER_PAGE, SOUND_PACKS, SOUND_EFFECTS, log,
    AUTOSAVE_DIR, AUTOSAVE_PATH, AUTOSAVE_INTERVAL_MS,
    RANDOM_POSITION_DEFAULT_MOVES, RANDOM_POSITION_MIN_MOVES,
    RANDOM_POSITION_MAX_MOVES,
)
from chess_engine import ChessEngine
from sound_manager import SoundManager
from board_widget import ChessBoardWidget
from puzzle_loader import PuzzleLoader, SORT_OPTIONS, SORT_DEFAULT
from puzzle_utils import LICHESS_THEME_LIST
from video_exporter import FFmpegVideoExporter
from utils import sanitize_filename, HAS_FFMPEG


# ── Minimalist Dark Stylesheet ──────────────────────────────────────────────

_MINIMAL_STYLE = """
QMainWindow { background: #1a1b26; }
QTabWidget::pane {
    border: 1px solid #292e42;
    background: #1a1b26;
    border-radius: 4px;
}
QTabWidget::tab-bar {
    alignment: left;
}
QTabBar::tab {
    background: #1a1b26;
    color: #565f89;
    border: 1px solid #292e42;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    padding: 6px 14px;
    margin-right: 1px;
    font-size: 11px;
    font-weight: bold;
}
QTabBar::tab:selected {
    background: #24283b;
    color: #c0caf5;
    border-bottom: 2px solid #7aa2f7;
}
QTabBar::tab:hover:!selected {
    background: #24283b;
    color: #a9b1d6;
}
QGroupBox {
    background: #1a1b26;
    border: 1px solid #292e42;
    border-radius: 4px;
    margin-top: 10px;
    padding: 10px 8px 6px 8px;
    font-size: 11px;
    font-weight: bold;
    color: #7aa2f7;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 8px;
    color: #7aa2f7;
}
QLabel {
    color: #a9b1d6;
    font-size: 11px;
    background: transparent;
    border: none;
}
QComboBox {
    background: #24283b;
    border: 1px solid #292e42;
    border-radius: 3px;
    color: #c0caf5;
    padding: 3px 6px;
    font-size: 11px;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #565f89;
    margin-right: 5px;
}
QComboBox QAbstractItemView {
    background: #24283b; border: 1px solid #292e42; color: #c0caf5;
    selection-background-color: #3d59a1; selection-color: #c0caf5; font-size: 11px;
}
QSpinBox {
    background: #24283b; border: 1px solid #292e42; border-radius: 3px;
    color: #c0caf5; padding: 2px 4px; font-size: 11px;
}
QCheckBox { color: #a9b1d6; font-size: 11px; spacing: 6px; background: transparent; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #3b4261; border-radius: 2px; background: #24283b; }
QCheckBox::indicator:checked { background: #7aa2f7; border-color: #7aa2f7; }
QSlider::groove:horizontal { height: 4px; background: #292e42; border-radius: 2px; }
QSlider::handle:horizontal { background: #7aa2f7; border: none; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
QSlider::sub-page:horizontal { background: #3d59a1; border-radius: 2px; }
QProgressBar { background: #24283b; border: 1px solid #292e42; border-radius: 3px; text-align: center; color: #a9b1d6; font-size: 10px; height: 14px; }
QProgressBar::chunk { background: #7aa2f7; border-radius: 2px; }
QTextEdit { background: #1a1b26; border: 1px solid #292e42; border-radius: 3px; color: #c0caf5; font-size: 11px; }
QListWidget { background: #1a1b26; border: 1px solid #292e42; border-radius: 3px; color: #c0caf5; font-size: 11px; }
QListWidget::item { padding: 3px 4px; }
QListWidget::item:selected { background: #3d59a1; color: #c0caf5; }
QLineEdit { background: #24283b; border: 1px solid #292e42; border-radius: 3px; color: #c0caf5; padding: 4px 6px; font-size: 11px; }
QLineEdit:focus { border-color: #7aa2f7; }
QFrame[frameShape="6"] { background: #1a1b26; border: 1px solid #292e42; border-radius: 3px; }
QScrollArea { background: #1a1b26; border: none; }
QDialog { background: #1a1b26; }
"""

_BTN_ACCENT = """
QPushButton { background: #7aa2f7; color: #1a1b26; font-weight: bold; padding: 5px 10px; border: none; border-radius: 3px; font-size: 11px; }
QPushButton:hover { background: #9bb8ff; }
QPushButton:disabled { background: #3b4261; color: #565f89; }
"""
_BTN_GHOST = """
QPushButton { background: transparent; color: #a9b1d6; border: 1px solid #292e42; padding: 4px 10px; border-radius: 3px; font-size: 11px; }
QPushButton:hover { background: #24283b; border-color: #3b4261; }
"""
_BTN_DANGER = """
QPushButton { background: transparent; color: #f7768e; border: 1px solid #f7768e; padding: 4px 10px; border-radius: 3px; font-size: 11px; }
QPushButton:hover { background: #f7768e; color: #1a1b26; }
"""
_BTN_EXPORT = """
QPushButton { background: #7aa2f7; color: #1a1b26; font-weight: bold; padding: 8px; border: none; border-radius: 4px; font-size: 12px; }
QPushButton:hover { background: #9bb8ff; }
QPushButton:disabled { background: #3b4261; color: #565f89; }
"""
_BTN_BATCH = """
QPushButton { background: #9ece6a; color: #1a1b26; font-weight: bold; padding: 6px 10px; border: none; border-radius: 3px; font-size: 11px; }
QPushButton:hover { background: #b4e88a; }
QPushButton:disabled { background: #3b4261; color: #565f89; }
"""
_BTN_RANDOM = """
QPushButton { background: #bb9af7; color: #1a1b26; font-weight: bold; padding: 8px 12px; border: none; border-radius: 4px; font-size: 12px; }
QPushButton:hover { background: #c9b4ff; }
QPushButton:disabled { background: #3b4261; color: #565f89; }
"""
_BTN_GREEN = """
QPushButton { background: #9ece6a; color: #1a1b26; font-weight: bold; padding: 6px 10px; border: none; border-radius: 3px; font-size: 11px; }
QPushButton:hover { background: #b4e88a; }
QPushButton:disabled { background: #3b4261; color: #565f89; }
"""


def _format_theme_name(theme_key):
    """Convert camelCase theme key to human-readable form."""
    return re.sub(r'([A-Z])', r' \1', theme_key).strip()


# ── Main Window ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("♟ Chess Puzzle Studio")
        self.setMinimumSize(1200, 780)
        self.setStyleSheet(_MINIMAL_STYLE)

        # ── Core objects ────────────────────────────────────────────────
        self.engine = ChessEngine()
        self.sound_mgr = SoundManager()
        self.puzzle_loader = PuzzleLoader()
        self.export_manifest = ExportManifest(EXPORT_MANIFEST_PATH)
        self.export_cfg = ExportConfig()

        # ── Puzzle state ────────────────────────────────────────────────
        self.current_puzzle = None
        self.move_index = 0
        self._uci_sequence = []
        self._notations = []
        self._practice_mode = False  # Unused, kept for state compatibility

        # ── Export state ────────────────────────────────────────────────
        self._exporter = None
        self._export_thread = None
        self._single_exporting = False

        # ── Batch export state ──────────────────────────────────────────
        self._batch_exporting = False
        self._batch_exporter = None
        self._batch_total = 0
        self._batch_completed = 0
        self._batch_cancelled = False

        # ── Auto-play state ─────────────────────────────────────────────
        self._auto_playing = False
        self._loop_enabled = True
        self._auto_delay = 800
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._auto_advance)

        # ── Search debounce timer ───────────────────────────────────────
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._apply_search_filter)

        # ── Auto-save timer ─────────────────────────────────────────────
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self._auto_save)
        self._autosave_dirty = False

        # ── Streak ──────────────────────────────────────────────────────
        self._streak = 0
        self._best_streak = 0

        # ── Pending puzzle ──────────────────────────────────────────────
        self._pending_puzzle_id = ''
        self._pending_move_index = 0

        # ── Build UI ────────────────────────────────────────────────────
        self._build_ui()

        # ── Auto-load ───────────────────────────────────────────────────
        self._auto_load_state()
        QTimer.singleShot(100, self._auto_load_bundled)

        # ── Start auto-save timer ───────────────────────────────────────
        self._autosave_timer.start()

    # ══════════════════════════════════════════════════════════════════════════
    #  UI CONSTRUCTION
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── LEFT PANEL ──────────────────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)
        left.setFixedWidth(310)

        # Search
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Search puzzles…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        ll.addWidget(self.search_edit)

        # Filters
        filter_grp = QGroupBox("Filters")
        fl = QVBoxLayout(filter_grp)
        fl.setContentsMargins(8, 14, 8, 6)
        fl.setSpacing(4)

        # Rating range
        rl = QHBoxLayout()
        rl.setSpacing(4)
        rl.addWidget(QLabel("Rating:"))
        self.min_rating_spin = QSpinBox()
        self.min_rating_spin.setRange(0, 3500)
        self.min_rating_spin.setSingleStep(100)
        self.min_rating_spin.setValue(0)
        self.min_rating_spin.setSpecialValueText("Min")
        rl.addWidget(self.min_rating_spin)
        rl.addWidget(QLabel("–"))
        self.max_rating_spin = QSpinBox()
        self.max_rating_spin.setRange(0, 3500)
        self.max_rating_spin.setSingleStep(100)
        self.max_rating_spin.setValue(0)
        self.max_rating_spin.setSpecialValueText("Max")
        rl.addWidget(self.max_rating_spin)
        fl.addLayout(rl)

        # Theme filter
        tl = QHBoxLayout()
        tl.setSpacing(4)
        tl.addWidget(QLabel("Theme:"))
        self.theme_filter_combo = QComboBox()
        self.theme_filter_combo.addItem("All", "")
        for theme_key in sorted(LICHESS_THEME_LIST, key=lambda t: _format_theme_name(t)):
            self.theme_filter_combo.addItem(_format_theme_name(theme_key), theme_key)
        tl.addWidget(self.theme_filter_combo, 1)
        fl.addLayout(tl)

        # Sort
        sl = QHBoxLayout()
        sl.setSpacing(4)
        sl.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        for key, (display, _) in SORT_OPTIONS.items():
            self.sort_combo.addItem(display, key)
        self.sort_combo.setCurrentIndex(0)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sl.addWidget(self.sort_combo, 1)
        fl.addLayout(sl)

        # Filter buttons
        fbl = QHBoxLayout()
        self.apply_filter_btn = QPushButton("Apply")
        self.apply_filter_btn.setStyleSheet(_BTN_ACCENT)
        self.apply_filter_btn.clicked.connect(self._apply_filters)
        self.reset_filter_btn = QPushButton("Reset")
        self.reset_filter_btn.setStyleSheet(_BTN_GHOST)
        self.reset_filter_btn.clicked.connect(self._reset_filters)
        fbl.addWidget(self.apply_filter_btn)
        fbl.addWidget(self.reset_filter_btn)
        fl.addLayout(fbl)
        ll.addWidget(filter_grp)

        # Puzzle list
        self.puzzle_list = QListWidget()
        self.puzzle_list.currentRowChanged.connect(self._on_puzzle_selected)
        self.puzzle_list.itemChanged.connect(self._on_item_check_changed)
        ll.addWidget(self.puzzle_list, 1)

        # Selection controls
        sel_row = QHBoxLayout()
        sel_row.setSpacing(4)
        self.select_all_btn = QPushButton("✅ All")
        self.select_all_btn.setFixedWidth(60)
        self.select_all_btn.setStyleSheet(_BTN_GHOST)
        self.select_all_btn.clicked.connect(self._select_all_puzzles)
        sel_row.addWidget(self.select_all_btn)
        self.deselect_all_btn = QPushButton("⬜ None")
        self.deselect_all_btn.setFixedWidth(60)
        self.deselect_all_btn.setStyleSheet(_BTN_GHOST)
        self.deselect_all_btn.clicked.connect(self._deselect_all_puzzles)
        sel_row.addWidget(self.deselect_all_btn)
        self.selected_count_label = QLabel("0 selected")
        self.selected_count_label.setStyleSheet("color: #565f89; font-size: 10px;")
        sel_row.addWidget(self.selected_count_label, 1)
        ll.addLayout(sel_row)

        # Pagination
        pag_frame = QFrame()
        pag_frame.setFrameShape(QFrame.StyledPanel)
        pag_l = QVBoxLayout(pag_frame)
        pag_l.setContentsMargins(6, 6, 6, 6)
        pag_l.setSpacing(3)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(2)
        self.first_page_btn = QPushButton("⏮")
        self.first_page_btn.setFixedWidth(28)
        self.first_page_btn.setStyleSheet(_BTN_GHOST)
        self.first_page_btn.clicked.connect(self._go_first_page)
        nav_row.addWidget(self.first_page_btn)
        self.prev_page_btn = QPushButton("◀")
        self.prev_page_btn.setFixedWidth(28)
        self.prev_page_btn.setStyleSheet(_BTN_GHOST)
        self.prev_page_btn.clicked.connect(self._go_prev_page)
        nav_row.addWidget(self.prev_page_btn)
        self.page_label = QLabel("1 / 1")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setFont(QFont("Sans", 9))
        nav_row.addWidget(self.page_label, 1)
        self.next_page_btn = QPushButton("▶")
        self.next_page_btn.setFixedWidth(28)
        self.next_page_btn.setStyleSheet(_BTN_GHOST)
        self.next_page_btn.clicked.connect(self._go_next_page)
        nav_row.addWidget(self.next_page_btn)
        self.last_page_btn = QPushButton("⏭")
        self.last_page_btn.setFixedWidth(28)
        self.last_page_btn.setStyleSheet(_BTN_GHOST)
        self.last_page_btn.clicked.connect(self._go_last_page)
        nav_row.addWidget(self.last_page_btn)
        pag_l.addLayout(nav_row)

        info_row = QHBoxLayout()
        info_row.setSpacing(4)
        info_row.addWidget(QLabel("Per page:"))
        self.per_page_combo = QComboBox()
        self.per_page_combo.addItems(["50", "100", "200", "500"])
        self.per_page_combo.setCurrentText(str(PUZZLES_PER_PAGE))
        self.per_page_combo.setFixedWidth(70)
        self.per_page_combo.currentTextChanged.connect(self._on_per_page_changed)
        info_row.addWidget(self.per_page_combo)
        self.total_label = QLabel("0 puzzles")
        self.total_label.setFont(QFont("Sans", 8))
        self.total_label.setStyleSheet("color: #565f89;")
        info_row.addWidget(self.total_label, 1)
        pag_l.addLayout(info_row)
        ll.addWidget(pag_frame)

        # Import button
        import_btn = QPushButton("📂 Import Puzzles…")
        import_btn.setStyleSheet(_BTN_GHOST)
        import_btn.clicked.connect(self._on_import)
        ll.addWidget(import_btn)

        # ── CENTER PANEL ────────────────────────────────────────────────
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)

        # Board
        self.board_widget = ChessBoardWidget(self.engine, self.sound_mgr)
        cl.addWidget(self.board_widget, alignment=Qt.AlignCenter)

        # Playback controls
        nav1 = QHBoxLayout()
        nav1.setSpacing(3)
        b = QPushButton("⏮")
        b.setFixedWidth(34)
        b.setToolTip("Go to start")
        b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self._go_start)
        nav1.addWidget(b)
        b = QPushButton("◀")
        b.setFixedWidth(34)
        b.setToolTip("Step back")
        b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self._go_prev)
        nav1.addWidget(b)
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(46)
        self.play_btn.setToolTip("Play puzzle animation")
        self._style_play_btn(False)
        self.play_btn.clicked.connect(self._toggle_play)
        nav1.addWidget(self.play_btn)
        b = QPushButton("▶")
        b.setFixedWidth(34)
        b.setToolTip("Step forward")
        b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self._go_next)
        nav1.addWidget(b)
        b = QPushButton("⏭")
        b.setFixedWidth(34)
        b.setToolTip("Go to end")
        b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self._go_end)
        nav1.addWidget(b)
        self.loop_btn = QPushButton("🔁")
        self.loop_btn.setFixedWidth(34)
        self.loop_btn.setCheckable(True)
        self.loop_btn.setChecked(True)
        self.loop_btn.setToolTip("Loop playback")
        self.loop_btn.toggled.connect(self._on_loop_toggle)
        nav1.addWidget(self.loop_btn)
        b = QPushButton("🔄")
        b.setFixedWidth(34)
        b.setToolTip("Flip board")
        b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self._flip_board)
        nav1.addWidget(b)

        nav1.addSpacing(8)
        nav1.addWidget(QLabel("Anim:"))
        self.anim_slider = QSlider(Qt.Horizontal)
        self.anim_slider.setRange(0, 500)
        self.anim_slider.setValue(250)
        self.anim_slider.setFixedWidth(80)
        self.anim_slider.valueChanged.connect(
            lambda v: setattr(self.board_widget, 'anim_speed', v))
        nav1.addWidget(self.anim_slider)
        nav1.addSpacing(4)
        nav1.addWidget(QLabel("Gap:"))
        self.gap_slider = QSlider(Qt.Horizontal)
        self.gap_slider.setRange(100, 3000)
        self.gap_slider.setValue(800)
        self.gap_slider.setFixedWidth(80)
        self._gap_label = QLabel("0.8s")
        self._gap_label.setFixedWidth(32)
        self.gap_slider.valueChanged.connect(self._on_gap_changed)
        nav1.addWidget(self.gap_slider)
        nav1.addWidget(self._gap_label)
        cl.addLayout(nav1)

        # Move scrubber
        nav2 = QHBoxLayout()
        self.move_scrubber = QSlider(Qt.Horizontal)
        self.move_scrubber.setRange(0, 0)
        self.move_scrubber.setValue(0)
        self.move_scrubber.sliderMoved.connect(self._on_scrubber_moved)
        nav2.addWidget(self.move_scrubber, 1)
        self.scrubber_label = QLabel("0 / 0")
        self.scrubber_label.setFixedWidth(70)
        self.scrubber_label.setAlignment(Qt.AlignCenter)
        nav2.addWidget(self.scrubber_label)
        cl.addLayout(nav2)

        # ── RIGHT PANEL ─────────────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        right.setFixedWidth(310)

        # Puzzle info
        ig = QGroupBox("Puzzle")
        il = QVBoxLayout(ig)
        il.setContentsMargins(8, 14, 8, 6)
        il.setSpacing(2)
        self.lbl_name = QLabel("—")
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setFont(QFont("Sans", 11, QFont.Bold))
        self.lbl_name.setStyleSheet("color: #c0caf5; font-size: 13px;")
        self.lbl_rating = QLabel("")
        self.lbl_rating.setStyleSheet("color: #e0af68; font-size: 11px; font-weight: bold;")
        self.lbl_themes = QLabel("")
        self.lbl_themes.setWordWrap(True)
        self.lbl_themes.setStyleSheet("color: #565f89; font-size: 10px;")
        self.lbl_fen = QLabel("")
        self.lbl_fen.setWordWrap(True)
        self.lbl_fen.setStyleSheet("color: #3b4261; font-size: 9px; font-family: monospace;")
        self.lbl_export_status = QLabel("")
        self.lbl_export_status.setWordWrap(True)
        self.lbl_export_status.setStyleSheet("color: #565f89; font-size: 10px;")
        il.addWidget(self.lbl_name)
        il.addWidget(self.lbl_rating)
        il.addWidget(self.lbl_themes)
        il.addWidget(self.lbl_fen)
        il.addWidget(self.lbl_export_status)
        rl.addWidget(ig)

        # Moves display
        mg = QGroupBox("Moves")
        ml = QVBoxLayout(mg)
        ml.setContentsMargins(8, 14, 8, 6)
        self.moves_text = QTextEdit()
        self.moves_text.setReadOnly(True)
        self.moves_text.setMaximumHeight(100)
        self.moves_text.setFont(QFont("Sans", 10))
        ml.addWidget(self.moves_text)
        rl.addWidget(mg)

        # Tab widget (Settings / Export / Random)
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)

        # ── SETTINGS TAB ────────────────────────────────────────────────
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.NoFrame)
        settings_content = QWidget()
        sl_layout = QVBoxLayout(settings_content)
        sl_layout.setContentsMargins(8, 8, 8, 8)
        sl_layout.setSpacing(10)

        # Board settings
        board_grp = QGroupBox("Board")
        bl = QVBoxLayout(board_grp)
        bl.setContentsMargins(8, 14, 8, 6)
        bl.setSpacing(6)
        bl.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES.keys())
        self.theme_combo.currentTextChanged.connect(self._on_theme)
        bl.addWidget(self.theme_combo)
        self.show_coords_check = QCheckBox("Coordinates")
        self.show_coords_check.setChecked(True)
        self.show_coords_check.toggled.connect(
            lambda v: setattr(self.board_widget, 'show_coords', v))
        bl.addWidget(self.show_coords_check)
        self.show_arrow_check = QCheckBox("Move arrows")
        self.show_arrow_check.setChecked(True)
        self.show_arrow_check.toggled.connect(
            lambda v: setattr(self.board_widget, 'show_arrow', v))
        bl.addWidget(self.show_arrow_check)
        sl_layout.addWidget(board_grp)

        # Sound settings
        sound_grp = QGroupBox("Sound Effects")
        sbl = QVBoxLayout(sound_grp)
        sbl.setContentsMargins(8, 14, 8, 6)
        sbl.setSpacing(6)
        self.sound_check = QCheckBox("Sound effects")
        self.sound_check.setChecked(True)
        self.sound_check.setStyleSheet("font-weight: bold;")
        self.sound_check.toggled.connect(self.sound_mgr.set_enabled)
        sbl.addWidget(self.sound_check)

        vol_row = QHBoxLayout()
        vol_row.setSpacing(6)
        vol_row.addWidget(QLabel("Volume:"))
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(70)
        self._vol_label = QLabel("70%")
        self._vol_label.setFixedWidth(30)
        self._vol_label.setStyleSheet("color: #565f89;")
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        vol_row.addWidget(self.vol_slider, 1)
        vol_row.addWidget(self._vol_label)
        sbl.addLayout(vol_row)

        sbl.addWidget(QLabel("Sound pack:"))
        self.sound_pack_combo = QComboBox()
        for pack_name in SOUND_PACKS:
            self.sound_pack_combo.addItem(pack_name, pack_name)
        self.sound_pack_combo.currentTextChanged.connect(self._on_sound_pack_changed)
        sbl.addWidget(self.sound_pack_combo)

        self._effect_checks = {}
        effect_row1 = QHBoxLayout()
        effect_row1.setSpacing(4)
        effect_row2 = QHBoxLayout()
        effect_row2.setSpacing(4)
        for effect_key, effect_label in [("move", "Move"), ("capture", "Capture"),
                                          ("check", "Check"), ("checkmate", "Mate"),
                                          ("castle", "Castle")]:
            cb = QCheckBox(effect_label)
            cb.setChecked(True)
            cb.toggled.connect(
                lambda v, k=effect_key: self.sound_mgr.set_effect_enabled(k, v))
            self._effect_checks[effect_key] = cb
            effect_row1.addWidget(cb)
        for effect_key, effect_label in [("promote", "Promote"), ("start", "Start"),
                                          ("solved", "Solved"), ("error", "Error")]:
            cb = QCheckBox(effect_label)
            cb.setChecked(True)
            cb.toggled.connect(
                lambda v, k=effect_key: self.sound_mgr.set_effect_enabled(k, v))
            self._effect_checks[effect_key] = cb
            effect_row2.addWidget(cb)
        sbl.addLayout(effect_row1)
        sbl.addLayout(effect_row2)

        # Auto-save option
        self.autosave_check = QCheckBox("Auto-save state")
        self.autosave_check.setChecked(True)
        self.autosave_check.setToolTip("Automatically save window state and settings")
        sbl.addWidget(self.autosave_check)

        sl_layout.addWidget(sound_grp)
        sl_layout.addStretch()

        settings_scroll.setWidget(settings_content)
        self.tab_widget.addTab(settings_scroll, "⚙ Settings")

        # ── RANDOM TAB ──────────────────────────────────────────────────
        random_scroll = QScrollArea()
        random_scroll.setWidgetResizable(True)
        random_scroll.setFrameShape(QFrame.NoFrame)
        random_content = QWidget()
        rnd_layout = QVBoxLayout(random_content)
        rnd_layout.setContentsMargins(8, 8, 8, 8)
        rnd_layout.setSpacing(10)

        # Random from database
        db_grp = QGroupBox("🎲 Random from Database")
        db_l = QVBoxLayout(db_grp)
        db_l.setContentsMargins(8, 14, 8, 6)
        db_l.setSpacing(8)

        self.random_db_btn = QPushButton("🎲  Random Puzzle")
        self.random_db_btn.setStyleSheet(_BTN_RANDOM)
        self.random_db_btn.clicked.connect(self._on_random_puzzle)
        db_l.addWidget(self.random_db_btn)

        hint1 = QLabel("Pick a random puzzle from the loaded database, matching current filters.")
        hint1.setStyleSheet("color: #565f89; font-size: 10px;")
        hint1.setWordWrap(True)
        db_l.addWidget(hint1)

        # Rating filter for random
        rrf = QHBoxLayout()
        rrf.setSpacing(4)
        rrf.addWidget(QLabel("Rating:"))
        self.random_min_rating = QSpinBox()
        self.random_min_rating.setRange(0, 3500)
        self.random_min_rating.setSingleStep(100)
        self.random_min_rating.setValue(0)
        self.random_min_rating.setSpecialValueText("Min")
        rrf.addWidget(self.random_min_rating)
        rrf.addWidget(QLabel("–"))
        self.random_max_rating = QSpinBox()
        self.random_max_rating.setRange(0, 3500)
        self.random_max_rating.setSingleStep(100)
        self.random_max_rating.setValue(0)
        self.random_max_rating.setSpecialValueText("Max")
        rrf.addWidget(self.random_max_rating)
        db_l.addLayout(rrf)

        # Theme filter for random
        rtf = QHBoxLayout()
        rtf.setSpacing(4)
        rtf.addWidget(QLabel("Theme:"))
        self.random_theme_combo = QComboBox()
        self.random_theme_combo.addItem("All", "")
        for theme_key in sorted(LICHESS_THEME_LIST, key=lambda t: _format_theme_name(t)):
            self.random_theme_combo.addItem(_format_theme_name(theme_key), theme_key)
        rtf.addWidget(self.random_theme_combo, 1)
        db_l.addLayout(rtf)

        # Auto-advance
        self.random_auto_check = QCheckBox("Auto-play next random on solve/fail")
        self.random_auto_check.setChecked(False)
        db_l.addWidget(self.random_auto_check)

        # Random streak counter
        streak_row = QHBoxLayout()
        streak_row.setSpacing(4)
        self.lbl_streak = QLabel("Streak: 0")
        self.lbl_streak.setStyleSheet("color: #9ece6a; font-size: 12px; font-weight: bold;")
        self.lbl_streak_val = QLabel("Best: 0")
        self.lbl_streak_val.setStyleSheet("color: #565f89; font-size: 10px;")
        streak_row.addWidget(self.lbl_streak)
        streak_row.addWidget(self.lbl_streak_val, 1)
        db_l.addLayout(streak_row)

        rnd_layout.addWidget(db_grp)

        # Generate random position
        gen_grp = QGroupBox("🧩 Generate Position")
        gen_l = QVBoxLayout(gen_grp)
        gen_l.setContentsMargins(8, 14, 8, 6)
        gen_l.setSpacing(8)

        gen_hint = QLabel("Generate a random chess position by playing random moves from the start.")
        gen_hint.setStyleSheet("color: #565f89; font-size: 10px;")
        gen_hint.setWordWrap(True)
        gen_l.addWidget(gen_hint)

        gen_row1 = QHBoxLayout()
        gen_row1.setSpacing(4)
        gen_row1.addWidget(QLabel("Half-moves:"))
        self.gen_moves_spin = QSpinBox()
        self.gen_moves_spin.setRange(RANDOM_POSITION_MIN_MOVES, RANDOM_POSITION_MAX_MOVES)
        self.gen_moves_spin.setValue(RANDOM_POSITION_DEFAULT_MOVES)
        gen_row1.addWidget(self.gen_moves_spin)
        gen_l.addLayout(gen_row1)

        self.gen_random_pos_btn = QPushButton("🧩  Generate Position")
        self.gen_random_pos_btn.setStyleSheet(_BTN_GREEN)
        self.gen_random_pos_btn.clicked.connect(self._on_generate_position)
        gen_l.addWidget(self.gen_random_pos_btn)

        self.gen_from_fen_btn = QPushButton("📋  Load FEN…")
        self.gen_from_fen_btn.setStyleSheet(_BTN_GHOST)
        self.gen_from_fen_btn.clicked.connect(self._on_load_fen)
        gen_l.addWidget(self.gen_from_fen_btn)

        self.gen_copy_fen_btn = QPushButton("📋  Copy FEN")
        self.gen_copy_fen_btn.setStyleSheet(_BTN_GHOST)
        self.gen_copy_fen_btn.clicked.connect(self._on_copy_fen)
        gen_l.addWidget(self.gen_copy_fen_btn)

        rnd_layout.addWidget(gen_grp)

        rnd_layout.addStretch()

        random_scroll.setWidget(random_content)
        self.tab_widget.addTab(random_scroll, "🎲 Random")

        # ── EXPORT TAB ──────────────────────────────────────────────────
        export_scroll = QScrollArea()
        export_scroll.setWidgetResizable(True)
        export_scroll.setFrameShape(QFrame.NoFrame)
        export_content = QWidget()
        el_layout = QVBoxLayout(export_content)
        el_layout.setContentsMargins(8, 8, 8, 8)
        el_layout.setSpacing(8)

        # Resolution preset
        res_grp = QGroupBox("Resolution")
        resl = QVBoxLayout(res_grp)
        resl.setContentsMargins(8, 14, 8, 6)
        resl.setSpacing(6)
        resl.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(EXPORT_PRESETS.keys())
        self.preset_combo.setCurrentText(self.export_cfg.preset_name)
        self.preset_combo.currentTextChanged.connect(self._on_preset)
        resl.addWidget(self.preset_combo)
        quality_hint = QLabel("Quality: YouTube-optimized H.264 (auto bitrate)")
        quality_hint.setStyleSheet("color: #3b4261; font-size: 9px;")
        resl.addWidget(quality_hint)
        el_layout.addWidget(res_grp)

        # Title & End
        te_grp = QGroupBox("Title & End")
        tel = QVBoxLayout(te_grp)
        tel.setContentsMargins(8, 14, 8, 6)
        tel.setSpacing(6)
        self.title_check = QCheckBox("Title screen")
        self.title_check.setChecked(True)
        tel.addWidget(self.title_check)
        th = QHBoxLayout()
        th.setSpacing(4)
        th.addWidget(QLabel("Duration:"))
        self.title_spin = QSpinBox()
        self.title_spin.setRange(1, 15)
        self.title_spin.setValue(3)
        self.title_spin.setSuffix("s")
        th.addWidget(self.title_spin)
        tel.addLayout(th)
        self.end_check = QCheckBox("End hold")
        self.end_check.setChecked(True)
        tel.addWidget(self.end_check)
        eh = QHBoxLayout()
        eh.setSpacing(4)
        eh.addWidget(QLabel("Duration:"))
        self.end_spin = QSpinBox()
        self.end_spin.setRange(1, 15)
        self.end_spin.setValue(3)
        self.end_spin.setSuffix("s")
        eh.addWidget(self.end_spin)
        tel.addLayout(eh)
        el_layout.addWidget(te_grp)

        # Timing
        tm_grp = QGroupBox("Timing")
        tml = QVBoxLayout(tm_grp)
        tml.setContentsMargins(8, 14, 8, 6)
        tml.setSpacing(6)
        tml.addWidget(QLabel("Move animation:"))
        ah = QHBoxLayout()
        self.anim_dur_slider = QSlider(Qt.Horizontal)
        self.anim_dur_slider.setRange(2, 30)
        self.anim_dur_slider.setValue(5)
        self.anim_dur_label = QLabel("0.5s")
        self.anim_dur_label.setStyleSheet("color: #565f89;")
        self.anim_dur_slider.valueChanged.connect(
            lambda v: self.anim_dur_label.setText(f"{v / 10:.1f}s"))
        ah.addWidget(self.anim_dur_slider, 1)
        ah.addWidget(self.anim_dur_label)
        tml.addLayout(ah)
        tml.addWidget(QLabel("Pause after move:"))
        ph = QHBoxLayout()
        self.pause_slider = QSlider(Qt.Horizontal)
        self.pause_slider.setRange(2, 30)
        self.pause_slider.setValue(8)
        self.pause_label = QLabel("0.8s")
        self.pause_label.setStyleSheet("color: #565f89;")
        self.pause_slider.valueChanged.connect(
            lambda v: self.pause_label.setText(f"{v / 10:.1f}s"))
        ph.addWidget(self.pause_slider, 1)
        ph.addWidget(self.pause_label)
        tml.addLayout(ph)
        el_layout.addWidget(tm_grp)

        # Single export
        self.export_btn = QPushButton("▶  Export Current Puzzle")
        self.export_btn.setStyleSheet(_BTN_EXPORT)
        self.export_btn.clicked.connect(self._on_export)
        el_layout.addWidget(self.export_btn)
        self.export_progress = QProgressBar()
        self.export_progress.setVisible(False)
        el_layout.addWidget(self.export_progress)
        self.export_status = QLabel("")
        self.export_status.setWordWrap(True)
        self.export_status.setStyleSheet("color: #565f89; font-size: 10px;")
        el_layout.addWidget(self.export_status)

        # Batch export
        batch_grp = QGroupBox("Batch Export")
        btl = QVBoxLayout(batch_grp)
        btl.setContentsMargins(8, 14, 8, 6)
        btl.setSpacing(6)
        self.batch_hint_label = QLabel(
            "Check puzzles in the list, then batch export them all.")
        self.batch_hint_label.setStyleSheet("color: #565f89; font-size: 10px;")
        self.batch_hint_label.setWordWrap(True)
        btl.addWidget(self.batch_hint_label)
        batch_btn_row = QHBoxLayout()
        batch_btn_row.setSpacing(4)
        self.batch_selected_btn = QPushButton("📋 Export Selected")
        self.batch_selected_btn.setStyleSheet(_BTN_BATCH)
        self.batch_selected_btn.clicked.connect(self._on_batch_export_selected)
        batch_btn_row.addWidget(self.batch_selected_btn)
        self.batch_page_btn = QPushButton("📄 Export Page")
        self.batch_page_btn.setStyleSheet(_BTN_BATCH)
        self.batch_page_btn.clicked.connect(self._on_batch_export_page)
        batch_btn_row.addWidget(self.batch_page_btn)
        btl.addLayout(batch_btn_row)
        self.batch_cancel_btn = QPushButton("✕ Cancel Batch")
        self.batch_cancel_btn.setStyleSheet(_BTN_DANGER)
        self.batch_cancel_btn.clicked.connect(self._on_batch_cancel)
        self.batch_cancel_btn.setVisible(False)
        btl.addWidget(self.batch_cancel_btn)
        self.batch_progress = QProgressBar()
        self.batch_progress.setVisible(False)
        btl.addWidget(self.batch_progress)
        self.batch_status = QLabel("")
        self.batch_status.setWordWrap(True)
        self.batch_status.setStyleSheet("color: #565f89; font-size: 10px;")
        btl.addWidget(self.batch_status)
        el_layout.addWidget(batch_grp)
        el_layout.addStretch()

        export_scroll.setWidget(export_content)
        self.tab_widget.addTab(export_scroll, "🎬 Export")
        rl.addWidget(self.tab_widget, 1)

        # ── Splitter ────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        root.addWidget(splitter)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.setStyleSheet("color: #565f89; font-size: 10px;")
        self.status.showMessage("Ready")

    # ══════════════════════════════════════════════════════════════════════════
    #  WINDOW CLOSE / CLEANUP
    # ══════════════════════════════════════════════════════════════════════════

    def closeEvent(self, event):
        self._stop_auto_play()
        self._on_batch_cancel()
        if self._exporter:
            self._exporter.cancel()
        if self._batch_exporter:
            self._batch_exporter.cancel()
        self._auto_save()
        self.export_manifest.close()
        self.puzzle_loader.close()
        self.sound_mgr.cleanup()
        event.accept()

    # ══════════════════════════════════════════════════════════════════════════
    #  PLAYBACK CONTROLS
    # ══════════════════════════════════════════════════════════════════════════

    def _style_play_btn(self, is_playing):
        if is_playing:
            self.play_btn.setText("⏸")
            self.play_btn.setToolTip("Pause")
            self.play_btn.setStyleSheet(
                "QPushButton{background:#e0af68;color:#1a1b26;font-weight:bold;"
                "font-size:15px;padding:4px;border:none;border-radius:4px}"
                "QPushButton:hover{background:#ebc07a}")
        else:
            self.play_btn.setText("▶")
            self.play_btn.setToolTip("Play puzzle animation")
            self.play_btn.setStyleSheet(
                "QPushButton{background:#7aa2f7;color:#1a1b26;font-weight:bold;"
                "font-size:15px;padding:4px;border:none;border-radius:4px}"
                "QPushButton:hover{background:#9bb8ff}")

    def _on_volume_changed(self, value):
        self.sound_mgr.set_volume(value / 100.0)
        self._vol_label.setText(f"{value}%")

    def _on_gap_changed(self, value):
        self._auto_delay = value
        self._gap_label.setText(f"{value / 1000:.1f}s")

    def _on_loop_toggle(self, checked):
        self._loop_enabled = checked

    def _flip_board(self):
        self.board_widget.flip()

    def _toggle_play(self):
        if self._auto_playing:
            self._stop_auto_play()
        else:
            self._start_auto_play()

    def _start_auto_play(self):
        if not self.current_puzzle:
            return
        if self.move_index >= len(self._uci_sequence):
            self._go_start()
        self._auto_playing = True
        self._style_play_btn(True)
        self._auto_advance()

    def _stop_auto_play(self):
        self._auto_playing = False
        self._auto_timer.stop()
        self._style_play_btn(False)

    def _auto_advance(self):
        if not self.current_puzzle or self.move_index >= len(self._uci_sequence):
            if self._loop_enabled:
                self._go_start()
                self._auto_timer.start(self._auto_delay)
            else:
                self._stop_auto_play()
                if self.current_puzzle:
                    self.sound_mgr.play('solved')
            return

        uci = self._uci_sequence[self.move_index]
        info = self.engine.make_move_uci(uci)
        if info:
            self._notations.append(info['notation'])
            self.move_index += 1
            self._update_moves_display()
            self._update_scrubber()
            self.board_widget.update()

            # Sound
            if info.get('mate'):
                self.sound_mgr.play('checkmate')
            elif info.get('check'):
                self.sound_mgr.play('check')
            elif info.get('captured', '.') != '.':
                self.sound_mgr.play('capture')
            elif info.get('castle'):
                self.sound_mgr.play('castle')
            else:
                self.sound_mgr.play('move')

            if self.move_index < len(self._uci_sequence):
                self._auto_timer.start(self._auto_delay)
            elif self._loop_enabled:
                self._auto_timer.start(self._auto_delay * 3)
            else:
                self._stop_auto_play()
                self.sound_mgr.play('solved')
        else:
            log(f"Auto-play: illegal move {uci}, stopping", "PLAYBACK")
            self._stop_auto_play()
            self.sound_mgr.play('error')

    def _go_start(self):
        if not self.current_puzzle:
            return
        self._stop_auto_play()
        fen = self.current_puzzle.get('fen', '')
        if fen:
            self.engine.load_fen(fen)
        else:
            self.engine.reset()
        self._notations = []
        self.move_index = 0
        # Replay setup moves
        setup_count = self.current_puzzle.get('setup_count', 0)
        for i in range(setup_count):
            if i < len(self._uci_sequence):
                info = self.engine.make_move_uci(self._uci_sequence[i])
                if info:
                    self._notations.append(info['notation'])
                    self.move_index += 1
        self._update_moves_display()
        self._update_scrubber()
        self.board_widget.update()

    def _go_end(self):
        if not self.current_puzzle:
            return
        self._stop_auto_play()
        # Play all remaining moves
        while self.move_index < len(self._uci_sequence):
            info = self.engine.make_move_uci(self._uci_sequence[self.move_index])
            if info:
                self._notations.append(info['notation'])
                self.move_index += 1
            else:
                break
        self._update_moves_display()
        self._update_scrubber()
        self.board_widget.update()

    def _go_prev(self):
        if not self.current_puzzle or self.move_index <= 0:
            return
        self._stop_auto_play()
        # Rewind: restart and replay up to move_index - 1
        target = self.move_index - 1
        self._go_start()
        for i in range(target):
            if i < len(self._uci_sequence):
                info = self.engine.make_move_uci(self._uci_sequence[i])
                if info:
                    self._notations.append(info['notation'])
                    self.move_index += 1
        self._update_moves_display()
        self._update_scrubber()
        self.board_widget.update()

    def _go_next(self):
        if not self.current_puzzle or self.move_index >= len(self._uci_sequence):
            return
        self._stop_auto_play()
        info = self.engine.make_move_uci(self._uci_sequence[self.move_index])
        if info:
            self._notations.append(info['notation'])
            self.move_index += 1
            self._update_moves_display()
            self._update_scrubber()
            self.board_widget.update()
            if info.get('mate'):
                self.sound_mgr.play('checkmate')
            elif info.get('check'):
                self.sound_mgr.play('check')
            elif info.get('captured', '.') != '.':
                self.sound_mgr.play('capture')
            elif info.get('castle'):
                self.sound_mgr.play('castle')
            else:
                self.sound_mgr.play('move')

    def _on_scrubber_moved(self, value):
        if not self.current_puzzle:
            return
        if value == self.move_index:
            return
        self._stop_auto_play()
        # Rewind to start, then replay to target
        fen = self.current_puzzle.get('fen', '')
        if fen:
            self.engine.load_fen(fen)
        else:
            self.engine.reset()
        self._notations = []
        setup_count = self.current_puzzle.get('setup_count', 0)
        start_idx = setup_count
        # Always replay setup
        for i in range(setup_count):
            if i < len(self._uci_sequence):
                info = self.engine.make_move_uci(self._uci_sequence[i])
                if info:
                    self._notations.append(info['notation'])
        # Replay up to value
        for i in range(start_idx, min(value, len(self._uci_sequence))):
            info = self.engine.make_move_uci(self._uci_sequence[i])
            if info:
                self._notations.append(info['notation'])
        self.move_index = min(value, len(self._uci_sequence))
        self._update_moves_display()
        self._update_scrubber()
        self.board_widget.update()

    # ══════════════════════════════════════════════════════════════════════════
    #  DISPLAY HELPERS
    # ══════════════════════════════════════════════════════════════════════════

    def _display_puzzle(self, puzzle):
        self.current_puzzle = puzzle
        self.move_index = 0
        self._uci_sequence = list(puzzle.get('moves', []))
        self._notations = []

        fen = puzzle.get('fen', '')
        if fen:
            self.engine.load_fen(fen)
        else:
            self.engine.reset()

        # Play setup moves (e.g. Lichess first move)
        setup_count = puzzle.get('setup_count', 0)
        for i in range(setup_count):
            if i < len(self._uci_sequence):
                info = self.engine.make_move_uci(self._uci_sequence[i])
                if info:
                    self._notations.append(info['notation'])
                    self.move_index += 1

        self._update_moves_display()
        self._update_scrubber()
        self._update_puzzle_info(puzzle)
        self.board_widget.update()
        self.sound_mgr.play('start')
        self._stop_auto_play()

    def _update_puzzle_info(self, puzzle):
        self.lbl_name.setText(puzzle.get('name', '—'))
        rating = puzzle.get('rating', 0)
        self.lbl_rating.setText(f"Rating: {rating}" if rating else "")
        self.lbl_themes.setText(puzzle.get('themes', ''))
        self.lbl_fen.setText(puzzle.get('fen', ''))

        # Export status
        pid = puzzle.get('id', '')
        if pid and self.export_manifest.is_exported(pid):
            info = self.export_manifest.get_info(pid)
            if info:
                self.lbl_export_status.setText(f"✅ Exported ({info.get('preset_name', '')})")
            else:
                self.lbl_export_status.setText("✅ Exported")
        else:
            self.lbl_export_status.setText("")

    def _update_moves_display(self):
        if not self._notations:
            self.moves_text.setPlainText("")
            return
        lines = []
        for i in range(0, len(self._notations), 2):
            move_num = i // 2 + 1
            white = self._notations[i] if i < len(self._notations) else ""
            black = self._notations[i + 1] if i + 1 < len(self._notations) else ""
            lines.append(f"{move_num}. {white} {black}")
        self.moves_text.setPlainText("  ".join(lines))

    def _update_scrubber(self):
        n = len(self._uci_sequence)
        self.move_scrubber.setRange(0, n)
        self.move_scrubber.setValue(self.move_index)
        self.scrubber_label.setText(f"{self.move_index} / {n}")

    # ══════════════════════════════════════════════════════════════════════════
    #  PUZZLE LIST & FILTERS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_puzzle_selected(self, row):
        if 0 <= row < len(self.puzzle_loader.puzzles):
            puzzle = self.puzzle_loader.puzzles[row]
            self._display_puzzle(puzzle)

    def _on_item_check_changed(self, item):
        self._update_selected_count()

    def _select_all_puzzles(self):
        for i in range(self.puzzle_list.count()):
            item = self.puzzle_list.item(i)
            item.setCheckState(Qt.Checked)
        self._update_selected_count()

    def _deselect_all_puzzles(self):
        for i in range(self.puzzle_list.count()):
            item = self.puzzle_list.item(i)
            item.setCheckState(Qt.Unchecked)
        self._update_selected_count()

    def _update_selected_count(self):
        count = sum(1 for i in range(self.puzzle_list.count())
                    if self.puzzle_list.item(i).checkState() == Qt.Checked)
        self.selected_count_label.setText(f"{count} selected")

    def _get_selected_puzzles(self):
        result = []
        for i in range(self.puzzle_list.count()):
            item = self.puzzle_list.item(i)
            if item.checkState() == Qt.Checked and 0 <= i < len(self.puzzle_loader.puzzles):
                result.append(self.puzzle_loader.puzzles[i])
        return result

    def _apply_filters(self):
        filters = {}
        min_r = self.min_rating_spin.value()
        max_r = self.max_rating_spin.value()
        if min_r > 0:
            filters['min_rating'] = min_r
        if max_r > 0:
            filters['max_rating'] = max_r
        theme = self.theme_filter_combo.currentData()
        if theme:
            filters['theme'] = theme
        search = self.search_edit.text().strip()
        if search:
            filters['search'] = search
        self.puzzle_loader.set_filters(filters)
        self._refresh_puzzle_list()

    def _reset_filters(self):
        self.min_rating_spin.setValue(0)
        self.max_rating_spin.setValue(0)
        self.theme_filter_combo.setCurrentIndex(0)
        self.search_edit.clear()
        self.puzzle_loader.clear_filters()
        self._refresh_puzzle_list()

    def _apply_search_filter(self):
        self._apply_filters()

    def _on_search_changed(self, text):
        self._search_timer.start()

    def _on_sort_changed(self, index):
        sort_key = self.sort_combo.currentData()
        self.puzzle_loader.sort_by = sort_key
        self._refresh_puzzle_list()

    def _on_per_page_changed(self, text):
        try:
            val = int(text)
            self.puzzle_loader.page_size = val
        except ValueError:
            pass
        self._refresh_puzzle_list()

    def _refresh_puzzle_list(self):
        self.puzzle_list.blockSignals(True)
        current_row = self.puzzle_list.currentRow()
        self.puzzle_list.clear()

        for puzzle in self.puzzle_loader.puzzles:
            name = puzzle.get('name', 'Puzzle')
            rating = puzzle.get('rating', 0)
            label = f"{name}  ({rating})" if rating else name
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.puzzle_list.addItem(item)

        if 0 <= current_row < self.puzzle_list.count():
            self.puzzle_list.setCurrentRow(current_row)

        self.puzzle_list.blockSignals(False)
        self._update_pagination()

    def _update_pagination(self):
        page = self.puzzle_loader.current_page
        total_pages = self.puzzle_loader.total_pages
        self.page_label.setText(f"{page + 1} / {total_pages}")
        self.total_label.setText(f"{self.puzzle_loader.filtered_count} puzzles")

    def _go_first_page(self):
        self.puzzle_loader.first_page()
        self._refresh_puzzle_list()

    def _go_prev_page(self):
        self.puzzle_loader.prev_page()
        self._refresh_puzzle_list()

    def _go_next_page(self):
        self.puzzle_loader.next_page()
        self._refresh_puzzle_list()

    def _go_last_page(self):
        self.puzzle_loader.last_page()
        self._refresh_puzzle_list()

    # ══════════════════════════════════════════════════════════════════════════
    #  IMPORT
    # ══════════════════════════════════════════════════════════════════════════

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Puzzles", DATA_DIR,
            "Puzzle Files (*.csv *.json *.parquet *.pgn *.tsv *.txt);;All Files (*)")
        if not path:
            return
        try:
            self.puzzle_loader.load_file(path)
            self._refresh_puzzle_list()
            self.status.showMessage(f"Loaded {self.puzzle_loader.total_count} puzzles")
        except Exception as e:
            QMessageBox.warning(self, "Import Error", str(e))

    def _auto_load_bundled(self):
        """Attempt to load the bundled Lichess database on startup."""
        if os.path.exists(LICHESS_DB_PATH):
            try:
                self.puzzle_loader.load_parquet(LICHESS_DB_PATH)
                self._refresh_puzzle_list()
                self.status.showMessage(
                    f"Loaded {self.puzzle_loader.total_count} puzzles from database")
                self._restore_pending_puzzle()
            except Exception as e:
                log(f"Auto-load bundled DB error: {e}", "INIT")
        else:
            os.makedirs(DATA_DIR, exist_ok=True)
            self.status.showMessage("No puzzle database found. Import one to get started.")

    # ══════════════════════════════════════════════════════════════════════════
    #  SETTINGS CALLBACKS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_theme(self, name):
        if name in THEMES:
            self.board_widget.current_theme = THEMES[name]
            self.export_cfg.theme_name = name
            self.board_widget.update()

    def _on_sound_pack_changed(self, name):
        self.sound_mgr.switch_pack(name)
        self.export_cfg.sound_pack = name

    # ══════════════════════════════════════════════════════════════════════════
    #  RANDOM TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _on_random_puzzle(self):
        # Apply random tab filters
        filters = {}
        min_r = self.random_min_rating.value()
        max_r = self.random_max_rating.value()
        if min_r > 0:
            filters['min_rating'] = min_r
        if max_r > 0:
            filters['max_rating'] = max_r
        theme = self.random_theme_combo.currentData()
        if theme:
            filters['theme'] = theme

        # Temporarily apply filters to get a random puzzle
        old_filters = self.puzzle_loader.filters
        self.puzzle_loader.set_filters(filters)
        puzzle = self.puzzle_loader.get_random_puzzle()
        if not puzzle:
            # Try without filters
            self.puzzle_loader.set_filters({})
            puzzle = self.puzzle_loader.get_random_puzzle()
        # Restore original filters
        self.puzzle_loader.set_filters(old_filters)

        if puzzle:
            self._display_puzzle(puzzle)
            self.status.showMessage("Random puzzle loaded")
        else:
            self.status.showMessage("No puzzles available for random selection")

    def _on_generate_position(self):
        n_moves = self.gen_moves_spin.value()
        board = chess.Board()
        for _ in range(n_moves):
            legal = list(board.legal_moves)
            if not legal:
                break
            board.push(random.choice(legal))
        fen = board.fen()
        self.engine.load_fen(fen)
        self.current_puzzle = {
            'name': f'Generated Position ({n_moves} half-moves)',
            'fen': fen,
            'moves': [],
            'setup_count': 0,
        }
        self._uci_sequence = []
        self._notations = []
        self.move_index = 0
        self._update_moves_display()
        self._update_scrubber()
        self._update_puzzle_info(self.current_puzzle)
        self.board_widget.update()
        self.sound_mgr.play('start')
        self._stop_auto_play()

    def _on_load_fen(self):
        from PySide6.QtWidgets import QInputDialog
        fen, ok = QInputDialog.getText(self, "Load FEN", "Enter FEN string:")
        if ok and fen.strip():
            try:
                self.engine.load_fen(fen.strip())
                self.current_puzzle = {
                    'name': 'Custom FEN Position',
                    'fen': fen.strip(),
                    'moves': [],
                    'setup_count': 0,
                }
                self._uci_sequence = []
                self._notations = []
                self.move_index = 0
                self._update_moves_display()
                self._update_scrubber()
                self._update_puzzle_info(self.current_puzzle)
                self.board_widget.update()
                self.sound_mgr.play('start')
                self._stop_auto_play()
            except Exception as e:
                QMessageBox.warning(self, "Invalid FEN", str(e))

    def _on_copy_fen(self):
        if self.engine.board:
            fen = self.engine.board.fen()
            QApplication.clipboard().setText(fen)
            self.status.showMessage(f"FEN copied: {fen}")

    # ══════════════════════════════════════════════════════════════════════════
    #  EXPORT TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _on_preset(self, name):
        self.export_cfg.apply_preset(name)

    def _sync_export_config(self):
        """Sync UI values into export config before exporting."""
        cfg = self.export_cfg
        cfg.title_enabled = self.title_check.isChecked()
        cfg.title_text = self.current_puzzle.get('name', '') if self.current_puzzle else ''
        cfg.title_duration = self.title_spin.value()
        cfg.end_enabled = self.end_check.isChecked()
        cfg.end_duration = self.end_spin.value()
        cfg.move_speed = self.anim_dur_slider.value() / 10.0
        cfg.pause_after_move = self.pause_slider.value() / 10.0
        cfg.loop_count = 1

    def _on_export(self):
        if not HAS_FFMPEG:
            QMessageBox.warning(self, "FFmpeg Not Found",
                                "FFmpeg is required for video export.\n"
                                "Install it and add to your system PATH.")
            return
        if not self.current_puzzle:
            QMessageBox.information(self, "No Puzzle", "Select a puzzle first.")
            return
        if self._single_exporting:
            return

        self._sync_export_config()
        os.makedirs(EXPORT_DIR, exist_ok=True)
        name = sanitize_filename(self.current_puzzle.get('name', 'puzzle'))
        output_path = os.path.join(EXPORT_DIR, f"{name}.mp4")

        self._single_exporting = True
        self.export_btn.setEnabled(False)
        self.export_progress.setVisible(True)
        self.export_progress.setRange(0, 100)
        self.export_progress.setValue(0)
        self.export_status.setText("Exporting…")

        self._exporter = FFmpegVideoExporter(self.export_cfg)
        self._exporter.progress.connect(self._on_export_progress)
        self._exporter.finished.connect(self._on_export_finished)
        self._exporter.error.connect(self._on_export_error)
        self._exporter.log_msg.connect(lambda msg: log(msg, "EXPORT"))

        self._export_thread = self._exporter.export_puzzle_threaded(
            self.current_puzzle, output_path)

    def _on_export_progress(self, current, total):
        if total > 0:
            pct = int(100 * current / total)
            self.export_progress.setValue(pct)

    def _on_export_finished(self, path):
        self._single_exporting = False
        self.export_btn.setEnabled(True)
        self.export_progress.setVisible(False)
        self.export_status.setText(f"✅ Exported: {os.path.basename(path)}")
        self.status.showMessage(f"Export complete: {path}")
        # Mark as exported
        if self.current_puzzle:
            pid = self.current_puzzle.get('id', '')
            if pid:
                self.export_manifest.mark_exported(
                    pid, path, self.export_cfg.preset_name,
                    self.current_puzzle.get('name', ''))
                self._update_puzzle_info(self.current_puzzle)

    def _on_export_error(self, msg):
        self._single_exporting = False
        self.export_btn.setEnabled(True)
        self.export_progress.setVisible(False)
        self.export_status.setText(f"❌ Error: {msg[:100]}")
        self.status.showMessage(f"Export error: {msg}")

    def _on_batch_export_selected(self):
        puzzles = self._get_selected_puzzles()
        if not puzzles:
            QMessageBox.information(self, "No Selection",
                                    "Check some puzzles in the list first.")
            return
        self._start_batch_export(puzzles)

    def _on_batch_export_page(self):
        puzzles = list(self.puzzle_loader.puzzles)
        if not puzzles:
            QMessageBox.information(self, "No Puzzles", "No puzzles on this page.")
            return
        self._start_batch_export(puzzles)

    def _start_batch_export(self, puzzles):
        if not HAS_FFMPEG:
            QMessageBox.warning(self, "FFmpeg Not Found",
                                "FFmpeg is required for video export.")
            return
        if self._batch_exporting:
            return

        self._sync_export_config()
        os.makedirs(EXPORT_DIR, exist_ok=True)
        self._batch_exporting = True
        self._batch_cancelled = False
        self._batch_total = len(puzzles)
        self._batch_completed = 0

        self.batch_selected_btn.setEnabled(False)
        self.batch_page_btn.setEnabled(False)
        self.batch_cancel_btn.setVisible(True)
        self.batch_progress.setVisible(True)
        self.batch_progress.setRange(0, self._batch_total)
        self.batch_progress.setValue(0)
        self.batch_status.setText(f"Exporting 0 / {self._batch_total}…")

        self._batch_exporter = FFmpegVideoExporter(self.export_cfg)
        self._batch_exporter.batch_puzzle_done.connect(self._on_batch_puzzle_done)
        self._batch_exporter.finished.connect(self._on_batch_finished)
        self._batch_exporter.error.connect(self._on_batch_error)
        self._batch_exporter.log_msg.connect(lambda msg: log(msg, "BATCH"))

        self._batch_exporter.export_batch(puzzles, EXPORT_DIR)

    def _on_batch_puzzle_done(self, idx, total, name):
        self._batch_completed = idx
        self.batch_progress.setValue(idx)
        self.batch_status.setText(f"Exported {idx} / {total}: {name}")

    def _on_batch_finished(self, output_dir):
        self._finish_batch()
        self.batch_status.setText(
            f"✅ Batch complete: {self._batch_completed} puzzles exported")
        self.status.showMessage("Batch export complete")

    def _on_batch_error(self, msg):
        self._finish_batch()
        self.batch_status.setText(f"❌ Batch error: {msg[:100]}")

    def _on_batch_cancel(self):
        if self._batch_exporting and self._batch_exporter:
            self._batch_cancelled = True
            self._batch_exporter.cancel()
        self._finish_batch()

    def _finish_batch(self):
        self._batch_exporting = False
        self.batch_selected_btn.setEnabled(True)
        self.batch_page_btn.setEnabled(True)
        self.batch_cancel_btn.setVisible(False)
        self.batch_progress.setVisible(False)

    # ══════════════════════════════════════════════════════════════════════════
    #  AUTO-SAVE / AUTO-LOAD
    # ══════════════════════════════════════════════════════════════════════════

    def _auto_save(self):
        """Save current application state to disk."""
        if not self.autosave_check.isChecked():
            return
        try:
            os.makedirs(AUTOSAVE_DIR, exist_ok=True)
            state = {
                'version': 1,
                'window_geometry': self.saveGeometry().toBase64().data().decode(),
                'window_state': self.saveState().toBase64().data().decode(),
                'splitter_state': self.findChild(QSplitter).saveState().toBase64().data().decode(),
                'board_theme': self.theme_combo.currentText(),
                'show_coords': self.show_coords_check.isChecked(),
                'show_arrow': self.show_arrow_check.isChecked(),
                'sound_enabled': self.sound_check.isChecked(),
                'sound_volume': self.vol_slider.value(),
                'sound_pack': self.sound_pack_combo.currentText(),
                'anim_speed': self.anim_slider.value(),
                'auto_delay': self.gap_slider.value(),
                'loop_enabled': self.loop_btn.isChecked(),
                'flipped': self.board_widget.flipped,
                'export_config': self.export_cfg.to_dict(),
                'min_rating_filter': self.min_rating_spin.value(),
                'max_rating_filter': self.max_rating_spin.value(),
                'theme_filter': self.theme_filter_combo.currentData(),
                'sort_by': self.sort_combo.currentData(),
                'per_page': self.per_page_combo.currentText(),
                'random_min_rating': self.random_min_rating.value(),
                'random_max_rating': self.random_max_rating.value(),
                'random_theme': self.random_theme_combo.currentData(),
                'random_auto_advance': self.random_auto_check.isChecked(),
                'gen_moves': self.gen_moves_spin.value(),
                'streak': self._streak,
                'best_streak': self._best_streak,
            }
            if self.current_puzzle:
                state['current_puzzle_id'] = str(self.current_puzzle.get('id', ''))
                state['current_move_index'] = self.move_index

            with open(AUTOSAVE_PATH, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            self._autosave_dirty = False
        except Exception as e:
            log(f"Auto-save error: {e}", "AUTOSAVE")

    def _auto_load_state(self):
        """Load saved application state from disk."""
        if not os.path.exists(AUTOSAVE_PATH):
            return
        try:
            with open(AUTOSAVE_PATH, 'r', encoding='utf-8') as f:
                state = json.load(f)

            if 'window_geometry' in state:
                from PySide6.QtCore import QByteArray
                self.restoreGeometry(QByteArray.fromBase64(state['window_geometry'].encode()))
            if 'window_state' in state:
                from PySide6.QtCore import QByteArray
                self.restoreState(QByteArray.fromBase64(state['window_state'].encode()))

            if 'splitter_state' in state:
                from PySide6.QtCore import QByteArray
                splitter = self.findChild(QSplitter)
                if splitter:
                    splitter.restoreState(QByteArray.fromBase64(state['splitter_state'].encode()))

            if 'board_theme' in state:
                idx = self.theme_combo.findText(state['board_theme'])
                if idx >= 0:
                    self.theme_combo.setCurrentIndex(idx)

            if 'show_coords' in state:
                self.show_coords_check.setChecked(state['show_coords'])
            if 'show_arrow' in state:
                self.show_arrow_check.setChecked(state['show_arrow'])

            if 'sound_enabled' in state:
                self.sound_check.setChecked(state['sound_enabled'])
            if 'sound_volume' in state:
                self.vol_slider.setValue(state['sound_volume'])
            if 'sound_pack' in state:
                idx = self.sound_pack_combo.findText(state['sound_pack'])
                if idx >= 0:
                    self.sound_pack_combo.setCurrentIndex(idx)

            if 'anim_speed' in state:
                self.anim_slider.setValue(state['anim_speed'])
            if 'auto_delay' in state:
                self.gap_slider.setValue(state['auto_delay'])
            if 'loop_enabled' in state:
                self.loop_btn.setChecked(state['loop_enabled'])
            if 'flipped' in state:
                if state['flipped'] != self.board_widget.flipped:
                    self.board_widget.flip()

            if 'export_config' in state:
                self.export_cfg.load_dict(state['export_config'])
                if 'preset_name' in state['export_config']:
                    idx = self.preset_combo.findText(state['export_config']['preset_name'])
                    if idx >= 0:
                        self.preset_combo.setCurrentIndex(idx)

            if 'min_rating_filter' in state:
                self.min_rating_spin.setValue(state['min_rating_filter'])
            if 'max_rating_filter' in state:
                self.max_rating_spin.setValue(state['max_rating_filter'])
            if 'theme_filter' in state and state['theme_filter']:
                idx = self.theme_filter_combo.findData(state['theme_filter'])
                if idx >= 0:
                    self.theme_filter_combo.setCurrentIndex(idx)
            if 'sort_by' in state:
                idx = self.sort_combo.findData(state['sort_by'])
                if idx >= 0:
                    self.sort_combo.setCurrentIndex(idx)
            if 'per_page' in state:
                idx = self.per_page_combo.findText(state['per_page'])
                if idx >= 0:
                    self.per_page_combo.setCurrentIndex(idx)

            if 'random_min_rating' in state:
                self.random_min_rating.setValue(state['random_min_rating'])
            if 'random_max_rating' in state:
                self.random_max_rating.setValue(state['random_max_rating'])
            if 'random_theme' in state and state['random_theme']:
                idx = self.random_theme_combo.findData(state['random_theme'])
                if idx >= 0:
                    self.random_theme_combo.setCurrentIndex(idx)
            if 'random_auto_advance' in state:
                self.random_auto_check.setChecked(state['random_auto_advance'])
            if 'gen_moves' in state:
                self.gen_moves_spin.setValue(state['gen_moves'])

            if 'streak' in state:
                self._streak = state['streak']
                self.lbl_streak.setText(f"Streak: {self._streak}")
            if 'best_streak' in state:
                self._best_streak = state['best_streak']
                self.lbl_streak_val.setText(f"Best: {self._best_streak}")

            self._pending_puzzle_id = state.get('current_puzzle_id', '')
            self._pending_move_index = state.get('current_move_index', 0)

            log("Auto-saved state restored", "AUTOSAVE")
        except Exception as e:
            log(f"Auto-load error: {e}", "AUTOSAVE")

    def _restore_pending_puzzle(self):
        """Restore the puzzle that was active when the app was last closed."""
        pid = getattr(self, '_pending_puzzle_id', '')
        if not pid:
            return
        puzzle = self.puzzle_loader.get_puzzle_by_id(pid)
        if puzzle:
            self._display_puzzle(puzzle)
            target_idx = getattr(self, '_pending_move_index', 0)
            if target_idx > 0 and target_idx <= len(self._uci_sequence):
                self._stop_auto_play()
                for i in range(target_idx):
                    info = self.engine.make_move_uci(self._uci_sequence[i])
                    if not info:
                        break
                    self.move_index = i + 1
                self._update_moves_display()
                self._update_scrubber()
                self.board_widget.update()
        self._pending_puzzle_id = ''
        self._pending_move_index = 0