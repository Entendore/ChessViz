#!/usr/bin/env python3
"""
main_window.py — Main window with tabbed settings/export, sound packs,
minimalist dark theme, filtering, pagination, batch export, and FFmpeg export.
"""

import os
import re
import json
import threading

import chess

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSlider, QComboBox, QCheckBox, QGroupBox, QSplitter,
    QStatusBar, QLineEdit, QApplication, QProgressBar, QSpinBox,
    QFileDialog, QFrame, QTabWidget, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont

from config import (
    THEMES, EXPORT_PRESETS, ExportConfig, ExportManifest,
    DATA_DIR, EXPORT_DIR, LICHESS_DB_PATH, EXPORT_MANIFEST_PATH,
    PUZZLES_PER_PAGE, SOUND_PACKS, SOUND_EFFECTS, HAS_FFMPEG, log,
)
from chess_engine import ChessEngine
from sound_manager import SoundManager
from board_widget import ChessBoardWidget, _engine_rc_to_screen_rc, _screen_rc_to_engine_rc
from puzzle_loader import PuzzleLoader, SORT_OPTIONS, SORT_DEFAULT
from puzzle_utils import LICHESS_THEME_LIST
from video_exporter import FFmpegVideoExporter
from utils import sanitize_filename


# ── Minimalist Dark Stylesheet ──────────────────────────────────────────────

_MINIMAL_STYLE = """
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
QComboBox::drop-down {
    border: none;
    width: 18px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #565f89;
    margin-right: 5px;
}
QComboBox QAbstractItemView {
    background: #24283b;
    border: 1px solid #292e42;
    color: #c0caf5;
    selection-background-color: #3d59a1;
    selection-color: #c0caf5;
    font-size: 11px;
}
QSpinBox {
    background: #24283b;
    border: 1px solid #292e42;
    border-radius: 3px;
    color: #c0caf5;
    padding: 2px 4px;
    font-size: 11px;
}
QCheckBox {
    color: #a9b1d6;
    font-size: 11px;
    spacing: 6px;
    background: transparent;
}
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #3b4261;
    border-radius: 2px;
    background: #24283b;
}
QCheckBox::indicator:checked {
    background: #7aa2f7;
    border-color: #7aa2f7;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #292e42;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #7aa2f7;
    border: none;
    width: 12px; height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}
QSlider::sub-page:horizontal {
    background: #3d59a1;
    border-radius: 2px;
}
QProgressBar {
    background: #24283b;
    border: 1px solid #292e42;
    border-radius: 3px;
    text-align: center;
    color: #a9b1d6;
    font-size: 10px;
    height: 14px;
}
QProgressBar::chunk {
    background: #7aa2f7;
    border-radius: 2px;
}
QTextEdit {
    background: #1a1b26;
    border: 1px solid #292e42;
    border-radius: 3px;
    color: #c0caf5;
    font-size: 11px;
}
QListWidget {
    background: #1a1b26;
    border: 1px solid #292e42;
    border-radius: 3px;
    color: #c0caf5;
    font-size: 11px;
}
QListWidget::item {
    padding: 3px 4px;
}
QListWidget::item:selected {
    background: #3d59a1;
    color: #c0caf5;
}
QLineEdit {
    background: #24283b;
    border: 1px solid #292e42;
    border-radius: 3px;
    color: #c0caf5;
    padding: 4px 6px;
    font-size: 11px;
}
QLineEdit:focus {
    border-color: #7aa2f7;
}
QFrame[frameShape="6"] {
    background: #1a1b26;
    border: 1px solid #292e42;
    border-radius: 3px;
}
"""

_BTN_ACCENT = """
QPushButton {
    background: #7aa2f7;
    color: #1a1b26;
    font-weight: bold;
    padding: 5px 10px;
    border: none;
    border-radius: 3px;
    font-size: 11px;
}
QPushButton:hover { background: #9bb8ff; }
QPushButton:disabled { background: #3b4261; color: #565f89; }
"""

_BTN_GHOST = """
QPushButton {
    background: transparent;
    color: #a9b1d6;
    border: 1px solid #292e42;
    padding: 4px 10px;
    border-radius: 3px;
    font-size: 11px;
}
QPushButton:hover { background: #24283b; border-color: #3b4261; }
"""

_BTN_DANGER = """
QPushButton {
    background: transparent;
    color: #f7768e;
    border: 1px solid #f7768e;
    padding: 4px 10px;
    border-radius: 3px;
    font-size: 11px;
}
QPushButton:hover { background: #f7768e; color: #1a1b26; }
"""

_BTN_EXPORT = """
QPushButton {
    background: #7aa2f7;
    color: #1a1b26;
    font-weight: bold;
    padding: 8px;
    border: none;
    border-radius: 4px;
    font-size: 12px;
}
QPushButton:hover { background: #9bb8ff; }
QPushButton:disabled { background: #3b4261; color: #565f89; }
"""

_BTN_BATCH = """
QPushButton {
    background: #9ece6a;
    color: #1a1b26;
    font-weight: bold;
    padding: 6px 10px;
    border: none;
    border-radius: 3px;
    font-size: 11px;
}
QPushButton:hover { background: #b4e88a; }
QPushButton:disabled { background: #3b4261; color: #565f89; }
"""


def _format_theme_name(theme_key):
    """Convert camelCase theme key like 'backRankMate' to 'Back Rank Mate'."""
    return re.sub(r'([A-Z])', r' \1', theme_key).strip()


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("♟ Chess Puzzle Studio")
        self.setMinimumSize(1200, 780)
        self.setStyleSheet(_MINIMAL_STYLE)

        self.engine = ChessEngine()
        self.sound_mgr = SoundManager()
        self.puzzle_loader = PuzzleLoader()
        self.export_manifest = ExportManifest(EXPORT_MANIFEST_PATH)
        self.export_cfg = ExportConfig()
        self.current_puzzle = None
        self.move_index = 0
        self._uci_sequence = []
        self._notations = []
        self._exporter = None
        self._export_thread = None

        # Batch export state
        self._batch_exporting = False
        self._batch_queue = []
        self._batch_total = 0
        self._batch_completed = 0
        self._batch_cancelled = False

        # Auto-play state
        self._auto_playing = False
        self._loop_enabled = True
        self._auto_delay = 800
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._auto_advance)

        # Search debounce
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._apply_search_filter)

        self._build_ui()
        QTimer.singleShot(100, self._auto_load_bundled)

    # ══════════════════════════════════════════════════════════════════════════
    #  UI CONSTRUCTION
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QHBoxLayout(central); root.setContentsMargins(6, 6, 6, 6); root.setSpacing(6)

        # ── LEFT: filters + puzzle list + pagination ────────────────────
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4); left.setFixedWidth(310)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Search puzzles…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        ll.addWidget(self.search_edit)

        # ── Filter group
        filter_grp = QGroupBox("Filters"); fl = QVBoxLayout(filter_grp)
        fl.setContentsMargins(8, 14, 8, 6); fl.setSpacing(4)

        rl = QHBoxLayout(); rl.setSpacing(4)
        rl.addWidget(QLabel("Rating:"))
        self.min_rating_spin = QSpinBox(); self.min_rating_spin.setRange(0, 3500)
        self.min_rating_spin.setSingleStep(100); self.min_rating_spin.setValue(0)
        self.min_rating_spin.setSpecialValueText("Min")
        rl.addWidget(self.min_rating_spin)
        rl.addWidget(QLabel("–"))
        self.max_rating_spin = QSpinBox(); self.max_rating_spin.setRange(0, 3500)
        self.max_rating_spin.setSingleStep(100); self.max_rating_spin.setValue(0)
        self.max_rating_spin.setSpecialValueText("Max")
        rl.addWidget(self.max_rating_spin)
        fl.addLayout(rl)

        tl = QHBoxLayout(); tl.setSpacing(4)
        tl.addWidget(QLabel("Theme:"))
        self.theme_filter_combo = QComboBox()
        self.theme_filter_combo.addItem("All", "")
        for theme_key in sorted(LICHESS_THEME_LIST, key=lambda t: _format_theme_name(t)):
            self.theme_filter_combo.addItem(_format_theme_name(theme_key), theme_key)
        tl.addWidget(self.theme_filter_combo, 1)
        fl.addLayout(tl)

        sl = QHBoxLayout(); sl.setSpacing(4)
        sl.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        for key, (display, _) in SORT_OPTIONS.items():
            self.sort_combo.addItem(display, key)
        self.sort_combo.setCurrentIndex(0)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sl.addWidget(self.sort_combo, 1)
        fl.addLayout(sl)

        fbl = QHBoxLayout()
        self.apply_filter_btn = QPushButton("Apply"); self.apply_filter_btn.setStyleSheet(_BTN_ACCENT)
        self.apply_filter_btn.clicked.connect(self._apply_filters)
        self.reset_filter_btn = QPushButton("Reset"); self.reset_filter_btn.setStyleSheet(_BTN_GHOST)
        self.reset_filter_btn.clicked.connect(self._reset_filters)
        fbl.addWidget(self.apply_filter_btn); fbl.addWidget(self.reset_filter_btn)
        fl.addLayout(fbl)
        ll.addWidget(filter_grp)

        # ── Puzzle list (checkable items for batch)
        self.puzzle_list = QListWidget()
        self.puzzle_list.currentRowChanged.connect(self._on_puzzle_selected)
        ll.addWidget(self.puzzle_list, 1)

        # ── Batch select row
        sel_row = QHBoxLayout(); sel_row.setSpacing(4)
        self.select_all_btn = QPushButton("✅ All"); self.select_all_btn.setFixedWidth(60)
        self.select_all_btn.setToolTip("Select all on page")
        self.select_all_btn.setStyleSheet(_BTN_GHOST)
        self.select_all_btn.clicked.connect(self._select_all_puzzles)
        sel_row.addWidget(self.select_all_btn)
        self.deselect_all_btn = QPushButton("⬜ None"); self.deselect_all_btn.setFixedWidth(60)
        self.deselect_all_btn.setToolTip("Deselect all")
        self.deselect_all_btn.setStyleSheet(_BTN_GHOST)
        self.deselect_all_btn.clicked.connect(self._deselect_all_puzzles)
        sel_row.addWidget(self.deselect_all_btn)
        self.selected_count_label = QLabel("0 selected")
        self.selected_count_label.setStyleSheet("color: #565f89; font-size: 10px;")
        sel_row.addWidget(self.selected_count_label, 1)
        ll.addLayout(sel_row)

        # ── Pagination
        pag_frame = QFrame(); pag_frame.setFrameShape(QFrame.StyledPanel)
        pag_l = QVBoxLayout(pag_frame); pag_l.setContentsMargins(6, 6, 6, 6); pag_l.setSpacing(3)

        nav_row = QHBoxLayout(); nav_row.setSpacing(2)
        self.first_page_btn = QPushButton("⏮"); self.first_page_btn.setFixedWidth(28)
        self.first_page_btn.setToolTip("First page"); self.first_page_btn.setStyleSheet(_BTN_GHOST)
        self.first_page_btn.clicked.connect(self._go_first_page); nav_row.addWidget(self.first_page_btn)
        self.prev_page_btn = QPushButton("◀"); self.prev_page_btn.setFixedWidth(28)
        self.prev_page_btn.setToolTip("Previous page"); self.prev_page_btn.setStyleSheet(_BTN_GHOST)
        self.prev_page_btn.clicked.connect(self._go_prev_page); nav_row.addWidget(self.prev_page_btn)
        self.page_label = QLabel("1 / 1"); self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setFont(QFont("Sans", 9)); nav_row.addWidget(self.page_label, 1)
        self.next_page_btn = QPushButton("▶"); self.next_page_btn.setFixedWidth(28)
        self.next_page_btn.setToolTip("Next page"); self.next_page_btn.setStyleSheet(_BTN_GHOST)
        self.next_page_btn.clicked.connect(self._go_next_page); nav_row.addWidget(self.next_page_btn)
        self.last_page_btn = QPushButton("⏭"); self.last_page_btn.setFixedWidth(28)
        self.last_page_btn.setToolTip("Last page"); self.last_page_btn.setStyleSheet(_BTN_GHOST)
        self.last_page_btn.clicked.connect(self._go_last_page); nav_row.addWidget(self.last_page_btn)
        pag_l.addLayout(nav_row)

        info_row = QHBoxLayout(); info_row.setSpacing(4)
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

        import_btn = QPushButton("📂 Import Puzzles…"); import_btn.setStyleSheet(_BTN_GHOST)
        import_btn.clicked.connect(self._on_import); ll.addWidget(import_btn)

        # ── CENTER: board + nav ────────────────────────────────────────────
        center = QWidget(); cl = QVBoxLayout(center); cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        self.board_widget = ChessBoardWidget(self.engine, self.sound_mgr)
        self.board_widget.move_made.connect(self._on_move_made)
        cl.addWidget(self.board_widget, alignment=Qt.AlignCenter)

        # Transport controls
        nav1 = QHBoxLayout(); nav1.setSpacing(3)
        b = QPushButton("⏮"); b.setFixedWidth(34); b.setToolTip("Go to start"); b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self._go_start); nav1.addWidget(b)
        b = QPushButton("◀"); b.setFixedWidth(34); b.setToolTip("Step back"); b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self._go_prev); nav1.addWidget(b)
        self.play_btn = QPushButton("▶"); self.play_btn.setFixedWidth(46)
        self.play_btn.setToolTip("Play puzzle animation")
        self._style_play_btn(False); self.play_btn.clicked.connect(self._toggle_play)
        nav1.addWidget(self.play_btn)
        b = QPushButton("▶"); b.setFixedWidth(34); b.setToolTip("Step forward"); b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self._go_next); nav1.addWidget(b)
        b = QPushButton("⏭"); b.setFixedWidth(34); b.setToolTip("Go to end"); b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self._go_end); nav1.addWidget(b)
        self.loop_btn = QPushButton("🔁"); self.loop_btn.setFixedWidth(34)
        self.loop_btn.setCheckable(True); self.loop_btn.setChecked(True)
        self.loop_btn.setToolTip("Loop playback")
        self.loop_btn.toggled.connect(self._on_loop_toggle); nav1.addWidget(self.loop_btn)
        b = QPushButton("🔄"); b.setFixedWidth(34); b.setToolTip("Flip board"); b.setStyleSheet(_BTN_GHOST)
        b.clicked.connect(self._flip_board); nav1.addWidget(b)
        nav1.addSpacing(8)
        nav1.addWidget(QLabel("Anim:"))
        self.anim_slider = QSlider(Qt.Horizontal)
        self.anim_slider.setRange(0, 500); self.anim_slider.setValue(250); self.anim_slider.setFixedWidth(80)
        self.anim_slider.valueChanged.connect(lambda v: setattr(self.board_widget, 'anim_speed', v))
        nav1.addWidget(self.anim_slider)
        nav1.addSpacing(4)
        nav1.addWidget(QLabel("Gap:"))
        self.gap_slider = QSlider(Qt.Horizontal)
        self.gap_slider.setRange(100, 3000); self.gap_slider.setValue(800); self.gap_slider.setFixedWidth(80)
        self._gap_label = QLabel("0.8s"); self._gap_label.setFixedWidth(32)
        self.gap_slider.valueChanged.connect(self._on_gap_changed)
        nav1.addWidget(self.gap_slider); nav1.addWidget(self._gap_label)
        cl.addLayout(nav1)

        # Move scrubber
        nav2 = QHBoxLayout()
        self.move_scrubber = QSlider(Qt.Horizontal)
        self.move_scrubber.setRange(0, 0); self.move_scrubber.setValue(0)
        self.move_scrubber.sliderMoved.connect(self._on_scrubber_moved)
        nav2.addWidget(self.move_scrubber, 1)
        self.scrubber_label = QLabel("0 / 0"); self.scrubber_label.setFixedWidth(70)
        self.scrubber_label.setAlignment(Qt.AlignCenter); nav2.addWidget(self.scrubber_label)
        cl.addLayout(nav2)

        # ── RIGHT: info + tabbed settings/export ───────────────────────────
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4); right.setFixedWidth(310)

        # Puzzle info
        ig = QGroupBox("Puzzle"); il = QVBoxLayout(ig)
        il.setContentsMargins(8, 14, 8, 6); il.setSpacing(2)
        self.lbl_name = QLabel("—"); self.lbl_name.setWordWrap(True)
        self.lbl_name.setFont(QFont("Sans", 11, QFont.Bold))
        self.lbl_name.setStyleSheet("color: #c0caf5; font-size: 13px;")
        self.lbl_rating = QLabel("")
        self.lbl_rating.setStyleSheet("color: #e0af68; font-size: 11px; font-weight: bold;")
        self.lbl_themes = QLabel(""); self.lbl_themes.setWordWrap(True)
        self.lbl_themes.setStyleSheet("color: #565f89; font-size: 10px;")
        self.lbl_fen = QLabel(""); self.lbl_fen.setWordWrap(True)
        self.lbl_fen.setStyleSheet("color: #3b4261; font-size: 9px; font-family: monospace;")
        self.lbl_export_status = QLabel(""); self.lbl_export_status.setWordWrap(True)
        self.lbl_export_status.setStyleSheet("color: #565f89; font-size: 10px;")
        il.addWidget(self.lbl_name); il.addWidget(self.lbl_rating)
        il.addWidget(self.lbl_themes); il.addWidget(self.lbl_fen)
        il.addWidget(self.lbl_export_status)
        rl.addWidget(ig)

        # Moves
        mg = QGroupBox("Moves"); ml = QVBoxLayout(mg)
        ml.setContentsMargins(8, 14, 8, 6)
        self.moves_text = QTextEdit(); self.moves_text.setReadOnly(True)
        self.moves_text.setMaximumHeight(100)
        self.moves_text.setFont(QFont("Sans", 10))
        ml.addWidget(self.moves_text)
        rl.addWidget(mg)

        # ── TAB WIDGET: Settings + Export ───────────────────────────────────
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)

        # ── SETTINGS TAB ───────────────────────────────────────────────────
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.NoFrame)
        settings_content = QWidget()
        sl_layout = QVBoxLayout(settings_content)
        sl_layout.setContentsMargins(8, 8, 8, 8); sl_layout.setSpacing(10)

        # Board section
        board_grp = QGroupBox("Board"); bl = QVBoxLayout(board_grp)
        bl.setContentsMargins(8, 14, 8, 6); bl.setSpacing(6)
        bl.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox(); self.theme_combo.addItems(THEMES.keys())
        self.theme_combo.currentTextChanged.connect(self._on_theme); bl.addWidget(self.theme_combo)
        self.show_coords_check = QCheckBox("Coordinates"); self.show_coords_check.setChecked(True)
        bl.addWidget(self.show_coords_check)
        self.show_arrow_check = QCheckBox("Move arrows"); self.show_arrow_check.setChecked(True)
        self.show_arrow_check.toggled.connect(
            lambda v: setattr(self.board_widget, 'show_arrow', v))
        bl.addWidget(self.show_arrow_check)
        sl_layout.addWidget(board_grp)

        # Sound section
        sound_grp = QGroupBox("Sound Effects"); sbl = QVBoxLayout(sound_grp)
        sbl.setContentsMargins(8, 14, 8, 6); sbl.setSpacing(6)

        self.sound_check = QCheckBox("Sound effects"); self.sound_check.setChecked(True)
        self.sound_check.setStyleSheet("font-weight: bold;")
        self.sound_check.toggled.connect(self.sound_mgr.set_enabled)
        sbl.addWidget(self.sound_check)

        vol_row = QHBoxLayout(); vol_row.setSpacing(6)
        vol_row.addWidget(QLabel("Volume:"))
        self.vol_slider = QSlider(Qt.Horizontal); self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(70)
        self._vol_label = QLabel("70%"); self._vol_label.setFixedWidth(30)
        self._vol_label.setStyleSheet("color: #565f89;")
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        vol_row.addWidget(self.vol_slider, 1); vol_row.addWidget(self._vol_label)
        sbl.addLayout(vol_row)

        sbl.addWidget(QLabel("Sound pack:"))
        self.sound_pack_combo = QComboBox()
        for pack_name in SOUND_PACKS:
            self.sound_pack_combo.addItem(pack_name, pack_name)
        self.sound_pack_combo.currentTextChanged.connect(self._on_sound_pack_changed)
        sbl.addWidget(self.sound_pack_combo)

        # Per-effect toggles
        self._effect_checks = {}
        effect_row1 = QHBoxLayout(); effect_row1.setSpacing(4)
        effect_row2 = QHBoxLayout(); effect_row2.setSpacing(4)
        effect_labels = [
            ("move", "Move"), ("capture", "Capture"), ("check", "Check"),
            ("checkmate", "Mate"), ("castle", "Castle"),
        ]
        effect_labels2 = [
            ("promote", "Promote"), ("start", "Start"), ("solved", "Solved"),
            ("error", "Error"),
        ]
        for effect_key, effect_label in effect_labels:
            cb = QCheckBox(effect_label); cb.setChecked(True)
            cb.toggled.connect(lambda v, k=effect_key: self.sound_mgr.set_effect_enabled(k, v))
            self._effect_checks[effect_key] = cb
            effect_row1.addWidget(cb)
        for effect_key, effect_label in effect_labels2:
            cb = QCheckBox(effect_label); cb.setChecked(True)
            cb.toggled.connect(lambda v, k=effect_key: self.sound_mgr.set_effect_enabled(k, v))
            self._effect_checks[effect_key] = cb
            effect_row2.addWidget(cb)
        sbl.addLayout(effect_row1)
        sbl.addLayout(effect_row2)

        sl_layout.addWidget(sound_grp)
        sl_layout.addStretch()
        settings_scroll.setWidget(settings_content)
        self.tab_widget.addTab(settings_scroll, "⚙ Settings")

        # ── EXPORT TAB ─────────────────────────────────────────────────────
        export_scroll = QScrollArea()
        export_scroll.setWidgetResizable(True)
        export_scroll.setFrameShape(QFrame.NoFrame)
        export_content = QWidget()
        el_layout = QVBoxLayout(export_content)
        el_layout.setContentsMargins(8, 8, 8, 8); el_layout.setSpacing(8)

        # Resolution
        res_grp = QGroupBox("Resolution"); resl = QVBoxLayout(res_grp)
        resl.setContentsMargins(8, 14, 8, 6); resl.setSpacing(6)
        resl.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(EXPORT_PRESETS.keys())
        self.preset_combo.setCurrentText(self.export_cfg.preset_name)
        self.preset_combo.currentTextChanged.connect(self._on_preset)
        resl.addWidget(self.preset_combo)

        quality_hint = QLabel("Quality: YouTube-optimized (auto)")
        quality_hint.setStyleSheet("color: #3b4261; font-size: 9px;")
        resl.addWidget(quality_hint)
        el_layout.addWidget(res_grp)

        # Title / End
        te_grp = QGroupBox("Title & End"); tel = QVBoxLayout(te_grp)
        tel.setContentsMargins(8, 14, 8, 6); tel.setSpacing(6)
        self.title_check = QCheckBox("Title screen"); self.title_check.setChecked(True)
        tel.addWidget(self.title_check)
        th = QHBoxLayout(); th.setSpacing(4); th.addWidget(QLabel("Duration:"))
        self.title_spin = QSpinBox(); self.title_spin.setRange(1, 15)
        self.title_spin.setValue(3); self.title_spin.setSuffix("s")
        th.addWidget(self.title_spin); tel.addLayout(th)
        self.end_check = QCheckBox("End hold"); self.end_check.setChecked(True)
        tel.addWidget(self.end_check)
        eh = QHBoxLayout(); eh.setSpacing(4); eh.addWidget(QLabel("Duration:"))
        self.end_spin = QSpinBox(); self.end_spin.setRange(1, 15)
        self.end_spin.setValue(3); self.end_spin.setSuffix("s")
        eh.addWidget(self.end_spin); tel.addLayout(eh)
        el_layout.addWidget(te_grp)

        # Timing
        tm_grp = QGroupBox("Timing"); tml = QVBoxLayout(tm_grp)
        tml.setContentsMargins(8, 14, 8, 6); tml.setSpacing(6)

        tml.addWidget(QLabel("Move animation:"))
        ah = QHBoxLayout()
        self.anim_dur_slider = QSlider(Qt.Horizontal)
        self.anim_dur_slider.setRange(2, 30); self.anim_dur_slider.setValue(5)
        self.anim_dur_label = QLabel("0.5s")
        self.anim_dur_label.setStyleSheet("color: #565f89;")
        self.anim_dur_slider.valueChanged.connect(
            lambda v: self.anim_dur_label.setText(f"{v/10:.1f}s"))
        ah.addWidget(self.anim_dur_slider, 1); ah.addWidget(self.anim_dur_label)
        tml.addLayout(ah)

        tml.addWidget(QLabel("Pause after move:"))
        ph = QHBoxLayout()
        self.pause_slider = QSlider(Qt.Horizontal)
        self.pause_slider.setRange(2, 30); self.pause_slider.setValue(8)
        self.pause_label = QLabel("0.8s")
        self.pause_label.setStyleSheet("color: #565f89;")
        self.pause_slider.valueChanged.connect(
            lambda v: self.pause_label.setText(f"{v/10:.1f}s"))
        ph.addWidget(self.pause_slider, 1); ph.addWidget(self.pause_label)
        tml.addLayout(ph)

        el_layout.addWidget(tm_grp)

        # ── Single Export ──────────────────────────────────────────────────
        self.export_btn = QPushButton("▶  Export Current Puzzle"); self.export_btn.setStyleSheet(_BTN_EXPORT)
        self.export_btn.clicked.connect(self._on_export)
        el_layout.addWidget(self.export_btn)

        self.export_progress = QProgressBar(); self.export_progress.setVisible(False)
        el_layout.addWidget(self.export_progress)

        self.export_status = QLabel(""); self.export_status.setWordWrap(True)
        self.export_status.setStyleSheet("color: #565f89; font-size: 10px;")
        el_layout.addWidget(self.export_status)

        # ── Batch Export ───────────────────────────────────────────────────
        batch_grp = QGroupBox("Batch Export"); btl = QVBoxLayout(batch_grp)
        btl.setContentsMargins(8, 14, 8, 6); btl.setSpacing(6)

        self.batch_hint_label = QLabel(
            "Check puzzles in the list, then batch export them all.")
        self.batch_hint_label.setStyleSheet("color: #565f89; font-size: 10px;")
        self.batch_hint_label.setWordWrap(True)
        btl.addWidget(self.batch_hint_label)

        batch_btn_row = QHBoxLayout(); batch_btn_row.setSpacing(4)
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

        self.batch_progress = QProgressBar(); self.batch_progress.setVisible(False)
        btl.addWidget(self.batch_progress)

        self.batch_status = QLabel(""); self.batch_status.setWordWrap(True)
        self.batch_status.setStyleSheet("color: #565f89; font-size: 10px;")
        btl.addWidget(self.batch_status)

        el_layout.addWidget(batch_grp)

        el_layout.addStretch()
        export_scroll.setWidget(export_content)
        self.tab_widget.addTab(export_scroll, "🎬 Export")

        rl.addWidget(self.tab_widget, 1)

        # ── Assemble splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left); splitter.addWidget(center); splitter.addWidget(right)
        splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        root.addWidget(splitter)

        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.status.setStyleSheet("color: #565f89; font-size: 10px;")
        self.status.showMessage("Ready")

    # ══════════════════════════════════════════════════════════════════════════
    #  PLAY-BUTTON STYLING
    # ══════════════════════════════════════════════════════════════════════════

    def _style_play_btn(self, is_playing):
        if is_playing:
            self.play_btn.setText("⏸"); self.play_btn.setToolTip("Pause")
            self.play_btn.setStyleSheet("""
                QPushButton{background:#e0af68;color:#1a1b26;font-weight:bold;
                font-size:15px;padding:4px;border:none;border-radius:4px}
                QPushButton:hover{background:#ebc07a}""")
        else:
            self.play_btn.setText("▶"); self.play_btn.setToolTip("Play puzzle animation")
            self.play_btn.setStyleSheet("""
                QPushButton{background:#7aa2f7;color:#1a1b26;font-weight:bold;
                font-size:15px;padding:4px;border:none;border-radius:4px}
                QPushButton:hover{background:#9bb8ff}""")

    # ══════════════════════════════════════════════════════════════════════════
    #  SOUND CONTROLS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_volume_changed(self, value):
        self.sound_mgr.set_volume(value / 100.0)
        self._vol_label.setText(f"{value}%")

    def _on_sound_pack_changed(self, text):
        self.sound_mgr.switch_pack(text)
        self.export_cfg.sound_pack = text

    # ══════════════════════════════════════════════════════════════════════════
    #  PUZZLE LIST SELECTION (batch checkboxes)
    # ══════════════════════════════════════════════════════════════════════════

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
        """Return list of puzzle dicts for all checked items in the puzzle list."""
        puzzles = []
        for i in range(self.puzzle_list.count()):
            item = self.puzzle_list.item(i)
            if item.checkState() == Qt.Checked:
                puzzle_idx = item.data(Qt.UserRole)
                if 0 <= puzzle_idx < len(self.puzzle_loader.puzzles):
                    puzzles.append(self.puzzle_loader.puzzles[puzzle_idx])
        return puzzles

    # ══════════════════════════════════════════════════════════════════════════
    #  FILTERING
    # ══════════════════════════════════════════════════════════════════════════

    def _collect_filters(self):
        filters = {}
        min_r = self.min_rating_spin.value()
        max_r = self.max_rating_spin.value()
        if min_r > 0: filters['min_rating'] = min_r
        if max_r > 0: filters['max_rating'] = max_r
        theme_data = self.theme_filter_combo.currentData()
        if theme_data: filters['theme'] = theme_data
        search = self.search_edit.text().strip()
        if search: filters['search'] = search
        return filters

    def _apply_filters(self):
        filters = self._collect_filters()
        self.puzzle_loader.set_filters(filters)
        self._refresh_puzzle_list(); self._update_pagination_ui()
        n = self.puzzle_loader.filtered_count
        self.status.showMessage(
            f"Filters applied — {n:,} of {self.puzzle_loader.total_count:,} puzzles match")

    def _reset_filters(self):
        self.search_edit.blockSignals(True); self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.min_rating_spin.setValue(0); self.max_rating_spin.setValue(0)
        self.theme_filter_combo.setCurrentIndex(0)
        self.puzzle_loader.clear_filters()
        self._refresh_puzzle_list(); self._update_pagination_ui()
        self.status.showMessage(f"Filters cleared — {self.puzzle_loader.total_count:,} puzzles")

    def _on_search_changed(self, text):
        self._search_timer.start()

    def _apply_search_filter(self):
        filters = self._collect_filters()
        self.puzzle_loader.set_filters(filters)
        self._refresh_puzzle_list(); self._update_pagination_ui()

    def _on_sort_changed(self, index):
        sort_key = self.sort_combo.currentData()
        if sort_key:
            self.puzzle_loader.sort_by = sort_key
            self._refresh_puzzle_list(); self._update_pagination_ui()

    # ══════════════════════════════════════════════════════════════════════════
    #  PAGINATION
    # ══════════════════════════════════════════════════════════════════════════

    def _update_pagination_ui(self):
        loader = self.puzzle_loader
        page = loader.current_page + 1
        total_p = loader.total_pages
        filtered = loader.filtered_count
        total = loader.total_count

        self.page_label.setText(f"{page} / {total_p}")
        self.total_label.setText(
            f"{filtered:,}" + (f" of {total:,}" if filtered != total else "") + " puzzles")

        self.prev_page_btn.setEnabled(page > 1)
        self.first_page_btn.setEnabled(page > 1)
        self.next_page_btn.setEnabled(page < total_p)
        self.last_page_btn.setEnabled(page < total_p)

    def _go_first_page(self):
        self.puzzle_loader.first_page()
        self._refresh_puzzle_list(); self._update_pagination_ui()

    def _go_prev_page(self):
        self.puzzle_loader.prev_page()
        self._refresh_puzzle_list(); self._update_pagination_ui()

    def _go_next_page(self):
        self.puzzle_loader.next_page()
        self._refresh_puzzle_list(); self._update_pagination_ui()

    def _go_last_page(self):
        self.puzzle_loader.last_page()
        self._refresh_puzzle_list(); self._update_pagination_ui()

    def _on_per_page_changed(self, text):
        try:
            size = int(text)
            self.puzzle_loader.page_size = size
            self._refresh_puzzle_list(); self._update_pagination_ui()
        except ValueError:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    #  PUZZLE LIST
    # ══════════════════════════════════════════════════════════════════════════

    def _refresh_puzzle_list(self):
        self.puzzle_list.blockSignals(True); self.puzzle_list.clear()
        puzzles = self.puzzle_loader.puzzles
        pids = [str(p.get('id', '')) for p in puzzles]
        exported_ids = self.export_manifest.get_exported_ids(pids) if pids else set()

        for idx, puzzle in enumerate(puzzles):
            title = str(puzzle.get('name', f'Puzzle #{idx+1}'))
            pid = str(puzzle.get('id', ''))
            if pid in exported_ids: title += "  🎬"
            rating = puzzle.get('rating', 0)
            if rating:
                try: title = f"[{int(float(rating))}] {title}"
                except (ValueError, TypeError): pass
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, idx)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.puzzle_list.addItem(item)

        self.puzzle_list.blockSignals(False)
        if puzzles: self.puzzle_list.setCurrentRow(0)
        self._update_selected_count()

    def _on_puzzle_selected(self, row):
        if row < 0: return
        item = self.puzzle_list.item(row)
        if item is None: return
        puzzle_idx = item.data(Qt.UserRole)
        if puzzle_idx < 0 or puzzle_idx >= len(self.puzzle_loader.puzzles): return
        puzzle = self.puzzle_loader.puzzles[puzzle_idx]
        self.current_puzzle = puzzle
        self._display_puzzle(puzzle)

        pid = str(puzzle.get('id', ''))
        export_info = self.export_manifest.get_info(pid)
        if export_info:
            ts = export_info.get('timestamp', '')
            self.lbl_export_status.setText(f"🎬 Exported {ts}")
            self.lbl_export_status.setStyleSheet("color: #9ece6a; font-size: 10px;")
        else:
            self.lbl_export_status.setText("Not exported")
            self.lbl_export_status.setStyleSheet("color: #3b4261; font-size: 10px;")

    # ══════════════════════════════════════════════════════════════════════════
    #  AUTO-PLAY CONTROLS
    # ══════════════════════════════════════════════════════════════════════════

    def _toggle_play(self):
        if self._auto_playing: self._stop_auto_play()
        else: self._start_auto_play()

    def _start_auto_play(self):
        if not self._uci_sequence: return
        if self.move_index >= len(self._uci_sequence):
            self._reset_engine_to_puzzle_start()
            self.move_index = 0
            self._update_moves_display(); self._update_scrubber()
            self.board_widget.update()
        self._auto_playing = True; self.board_widget.auto_playing = True
        self._style_play_btn(True); self._auto_advance()

    def _stop_auto_play(self):
        self._auto_playing = False; self._auto_timer.stop()
        self.board_widget.auto_playing = False; self._style_play_btn(False)

    def _auto_advance(self):
        if not self._auto_playing: return
        if self.move_index >= len(self._uci_sequence):
            if self._loop_enabled:
                self._reset_engine_to_puzzle_start()
                self.move_index = 0
                self._update_moves_display(); self._update_scrubber()
                self.board_widget.update()
                self._auto_timer.start(max(600, self._auto_delay))
            else:
                self._stop_auto_play()
            return
        self._apply_next_move_animated()

    def _schedule_next_auto(self):
        self._auto_timer.start(self._auto_delay)

    def _apply_next_move_animated(self):
        if self.move_index >= len(self._uci_sequence): return
        uci = self._uci_sequence[self.move_index]
        info = self.engine.make_move_uci(uci)
        if info:
            self.move_index += 1
            self._update_moves_display(); self._update_scrubber()
            if self.board_widget.anim_speed > 0:
                flipped = self.board_widget.flipped
                sr, sc = _engine_rc_to_screen_rc(info['from'][0], info['from'][1], flipped)
                tr, tc = _engine_rc_to_screen_rc(info['to'][0], info['to'][1], flipped)
                self.board_widget.start_animation(
                    sr, sc, tr, tc, info['piece_obj'], info['captured'], info['notation'])
            else:
                self.board_widget.update()
                if self._auto_playing: self._schedule_next_auto()
        else:
            self._stop_auto_play()

    def _on_loop_toggle(self, checked):
        self._loop_enabled = checked
        self.loop_btn.setStyleSheet(
            "QPushButton{background:#7aa2f7;color:#1a1b26;border:none;"
            "border-radius:4px;font-size:13px;padding:3px}" if checked else
            "QPushButton{background:#24283b;color:#565f89;border:1px solid #292e42;"
            "border-radius:4px;font-size:13px;padding:3px}")

    def _on_gap_changed(self, value):
        self._auto_delay = value
        self._gap_label.setText(f"{value/1000:.1f}s")

    # ══════════════════════════════════════════════════════════════════════════
    #  MOVE DISPLAY
    # ══════════════════════════════════════════════════════════════════════════

    def _update_moves_display(self):
        if not self._notations:
            self.moves_text.setHtml('<span style="color:#3b4261;">No moves</span>')
            return
        parts = []
        for i, notation in enumerate(self._notations):
            if i % 2 == 0:
                move_num = i // 2 + 1
                parts.append(f'<span style="color:#3b4261;">{move_num}.</span> ')
            if i < self.move_index:
                if i == self.move_index - 1:
                    parts.append(
                        f'<span style="background:#7aa2f7;color:#1a1b26;'
                        f'padding:1px 5px;border-radius:3px;font-weight:bold;">'
                        f'{notation}</span> ')
                else:
                    parts.append(f'<span style="color:#c0caf5;">{notation}</span> ')
            else:
                parts.append(f'<span style="color:#3b4261;">{notation}</span> ')
        self.moves_text.setHtml(''.join(parts))

    # ══════════════════════════════════════════════════════════════════════════
    #  SCRUBBER
    # ══════════════════════════════════════════════════════════════════════════

    def _update_scrubber(self):
        n = len(self._uci_sequence)
        self.move_scrubber.blockSignals(True)
        self.move_scrubber.setRange(0, n); self.move_scrubber.setValue(self.move_index)
        self.move_scrubber.blockSignals(False)
        self.scrubber_label.setText(f"{self.move_index} / {n}")

    def _on_scrubber_moved(self, value):
        self._stop_auto_play()
        self._reset_engine_to_puzzle_start()
        self.move_index = 0
        for i in range(value):
            info = self.engine.make_move_uci(self._uci_sequence[i])
            if info: self.move_index += 1
            else: break
        self._update_moves_display(); self._update_scrubber()
        self.board_widget.update()

    # ══════════════════════════════════════════════════════════════════════════
    #  ENGINE HELPERS
    # ══════════════════════════════════════════════════════════════════════════

    def _reset_engine_to_puzzle_start(self):
        if self.current_puzzle and self.current_puzzle.get('fen'):
            self.engine.load_fen(self.current_puzzle['fen'])
        else:
            self.engine.reset()

    # ══════════════════════════════════════════════════════════════════════════
    #  AUTO-LOAD
    # ══════════════════════════════════════════════════════════════════════════

    def _auto_load_bundled(self):
        if not os.path.exists(LICHESS_DB_PATH):
            self.status.showMessage("No bundled DB — use Import to load puzzles")
            return
        if self.puzzle_loader.has_puzzles:
            self._refresh_puzzle_list(); self._update_pagination_ui()
            self.status.showMessage(f"{self.puzzle_loader.total_count:,} puzzles ready ✓")
            return
        self.status.showMessage("Loading bundled puzzles database…")
        QApplication.processEvents()

        def _w():
            try:
                self.puzzle_loader.load_parquet(LICHESS_DB_PATH)
                log(f"Auto-load: {self.puzzle_loader.total_count} puzzles", "IMPORT")
            except Exception as e:
                log(f"Auto-load error: {e}", "ERROR")
                QTimer.singleShot(0, lambda: self.status.showMessage(f"Load error: {e}"))
                return
            QTimer.singleShot(0, self._on_auto_load_done)

        threading.Thread(target=_w, daemon=True).start()

    def _on_auto_load_done(self):
        self._refresh_puzzle_list(); self._update_pagination_ui()
        self.status.showMessage(f"{self.puzzle_loader.total_count:,} puzzles loaded ✓")

    # ══════════════════════════════════════════════════════════════════════════
    #  DISPLAY PUZZLE
    # ══════════════════════════════════════════════════════════════════════════

    def _display_puzzle(self, puzzle):
        self.lbl_name.setText(puzzle.get('name', '—'))
        rating = puzzle.get('rating', '')
        if rating:
            try: self.lbl_rating.setText(f"⭐ {int(float(rating))}")
            except (ValueError, TypeError): self.lbl_rating.setText("")
        else:
            self.lbl_rating.setText("")
        themes = puzzle.get('themes', '')
        if themes:
            display_themes = ' · '.join(_format_theme_name(t) for t in themes.split()[:4])
            self.lbl_themes.setText(f"🏷 {display_themes}")
        else:
            self.lbl_themes.setText("")
        fen = puzzle.get('fen', '')
        self.lbl_fen.setText(fen[:55] + ('…' if len(fen) > 55 else '') if fen else "")

        self._stop_auto_play()

        uci = puzzle.get('moves', [])
        if isinstance(uci, str):
            try: uci = json.loads(uci)
            except Exception: uci = uci.split()

        start_fen = fen if fen else None
        temp_board = chess.Board(start_fen) if start_fen else chess.Board()
        self._notations = []; valid_uci = []
        for u in uci:
            try:
                move = chess.Move.from_uci(u)
                if move in temp_board.legal_moves:
                    self._notations.append(temp_board.san(move))
                    temp_board.push(move); valid_uci.append(u)
                else: break
            except Exception: break
        self._uci_sequence = valid_uci

        if start_fen: self.engine.load_fen(start_fen)
        else: self.engine.reset()
        self.move_index = 0
        self._update_moves_display(); self._update_scrubber()
        self.board_widget.update()

        if self._uci_sequence:
            QTimer.singleShot(450, self._start_auto_play)

    # ══════════════════════════════════════════════════════════════════════════
    #  NAVIGATION
    # ══════════════════════════════════════════════════════════════════════════

    def _go_start(self):
        if self.board_widget.animating: return
        self._stop_auto_play(); self._reset_engine_to_puzzle_start()
        self.move_index = 0
        self._update_moves_display(); self._update_scrubber()
        self.board_widget.update()

    def _go_prev(self):
        if self.board_widget.animating: return
        self._stop_auto_play()
        if self.engine.undo():
            self.move_index = max(0, self.move_index - 1)
            self._update_moves_display(); self._update_scrubber()
            self.board_widget.update()

    def _go_next(self):
        if self.board_widget.animating: return
        self._stop_auto_play(); self._apply_next_move_animated()

    def _go_end(self):
        if self.board_widget.animating: return
        self._stop_auto_play()
        while self.move_index < len(self._uci_sequence):
            info = self.engine.make_move_uci(self._uci_sequence[self.move_index])
            if info: self.move_index += 1
            else: break
        self._update_moves_display(); self._update_scrubber()
        self.board_widget.update()

    def _flip_board(self):
        self.board_widget.flip()

    # ══════════════════════════════════════════════════════════════════════════
    #  MOVE-MADE HANDLER
    # ══════════════════════════════════════════════════════════════════════════

    def _on_move_made(self, notation):
        self.status.showMessage(f"Move: {notation}")
        if self._auto_playing: self._schedule_next_auto()

    # ══════════════════════════════════════════════════════════════════════════
    #  SETTINGS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_theme(self, name):
        if name in THEMES:
            self.board_widget.current_theme = THEMES[name]
            self.board_widget.update()

    # ══════════════════════════════════════════════════════════════════════════
    #  SINGLE EXPORT
    # ══════════════════════════════════════════════════════════════════════════

    def _on_preset(self, name):
        self.export_cfg.apply_preset(name)

    def _on_export(self):
        if not self.current_puzzle:
            self.export_status.setText("Select a puzzle first")
            self.export_status.setStyleSheet("color: #f7768e; font-size: 10px;")
            return
        if not HAS_FFMPEG:
            self.export_status.setText("ffmpeg not found — install and add to PATH")
            self.export_status.setStyleSheet("color: #f7768e; font-size: 10px;")
            return
        if self._exporter is not None: return
        if self._batch_exporting:
            self.export_status.setText("Batch export in progress — wait or cancel")
            self.export_status.setStyleSheet("color: #e0af68; font-size: 10px;")
            return

        self._stop_auto_play()

        cfg = self.export_cfg
        cfg.title_enabled = self.title_check.isChecked()
        cfg.title_duration = self.title_spin.value()
        cfg.end_enabled = self.end_check.isChecked()
        cfg.end_duration = self.end_spin.value()
        cfg.move_speed = self.anim_dur_slider.value() / 10.0
        cfg.pause_after_move = self.pause_slider.value() / 10.0
        cfg.theme_name = self.theme_combo.currentText()
        cfg.coordinate_visible = self.show_coords_check.isChecked()
        cfg.show_arrow = self.show_arrow_check.isChecked()

        cfg.title_text = self.current_puzzle.get('name', 'Chess Puzzle')
        cfg.end_text = "Solved!"

        os.makedirs(EXPORT_DIR, exist_ok=True)
        fname = sanitize_filename(cfg.title_text)
        out_path = os.path.join(EXPORT_DIR, f"{fname}.mp4")

        self.export_btn.setEnabled(False)
        self.export_progress.setVisible(True); self.export_progress.setValue(0)
        self.export_status.setText("Exporting…")
        self.export_status.setStyleSheet("color: #565f89; font-size: 10px;")

        self._exporter = FFmpegVideoExporter(cfg)
        self._exporter.progress.connect(self._export_progress_cb)
        self._exporter.finished.connect(self._export_done)
        self._exporter.error.connect(self._export_error)
        self._exporter.log_msg.connect(lambda msg: log(msg, "EXPORT"))

        self._export_thread = threading.Thread(
            target=self._exporter.export_puzzle,
            args=(self.current_puzzle, out_path), daemon=True)
        self._export_thread.start()

    def _export_progress_cb(self, cur, total):
        self.export_progress.setMaximum(total); self.export_progress.setValue(cur)
        pct = cur * 100 // max(1, total)
        self.export_status.setText(f"Rendering {cur}/{total}  ({pct}%)")

    def _export_done(self, path):
        self.export_btn.setEnabled(True); self.export_progress.setVisible(False)
        self._exporter = None; self._export_thread = None

        if path and self.current_puzzle:
            pid = str(self.current_puzzle.get('id', ''))
            self.export_manifest.mark_exported(pid, path)
            self.export_status.setText(f"✓ {path}")
            self.export_status.setStyleSheet("color: #9ece6a; font-size: 10px;")
            self.status.showMessage(f"Export complete: {path}")

            export_info = self.export_manifest.get_info(pid)
            if export_info:
                ts = export_info.get('timestamp', '')
                self.lbl_export_status.setText(f"🎬 Exported {ts}")
                self.lbl_export_status.setStyleSheet("color: #9ece6a; font-size: 10px;")

            current_row = self.puzzle_list.currentRow()
            self._refresh_puzzle_list()
            if current_row >= 0: self.puzzle_list.setCurrentRow(current_row)
        else:
            self.export_status.setText("Export failed")
            self.export_status.setStyleSheet("color: #f7768e; font-size: 10px;")

    def _export_error(self, msg):
        self.export_btn.setEnabled(True); self.export_progress.setVisible(False)
        self._exporter = None; self._export_thread = None
        self.export_status.setText(f"✗ {msg}")
        self.export_status.setStyleSheet("color: #f7768e; font-size: 10px;")

    # ══════════════════════════════════════════════════════════════════════════
    #  BATCH EXPORT
    # ══════════════════════════════════════════════════════════════════════════

    def _on_batch_export_selected(self):
        """Export all checked puzzles in the list."""
        puzzles = self._get_selected_puzzles()
        if not puzzles:
            self.batch_status.setText("No puzzles selected — check items in the list")
            self.batch_status.setStyleSheet("color: #e0af68; font-size: 10px;")
            return
        self._start_batch_export(puzzles)

    def _on_batch_export_page(self):
        """Export all puzzles on the current page."""
        puzzles = list(self.puzzle_loader.puzzles)
        if not puzzles:
            self.batch_status.setText("No puzzles on this page")
            self.batch_status.setStyleSheet("color: #e0af68; font-size: 10px;")
            return
        self._start_batch_export(puzzles)

    def _start_batch_export(self, puzzles):
        if self._batch_exporting:
            self.batch_status.setText("Batch already in progress")
            self.batch_status.setStyleSheet("color: #e0af68; font-size: 10px;")
            return
        if not HAS_FFMPEG:
            self.batch_status.setText("ffmpeg not found — install and add to PATH")
            self.batch_status.setStyleSheet("color: #f7768e; font-size: 10px;")
            return
        if self._exporter is not None:
            self.batch_status.setText("Single export in progress — wait or cancel")
            self.batch_status.setStyleSheet("color: #e0af68; font-size: 10px;")
            return

        self._stop_auto_play()

        # Apply current settings
        cfg = self.export_cfg
        cfg.title_enabled = self.title_check.isChecked()
        cfg.title_duration = self.title_spin.value()
        cfg.end_enabled = self.end_check.isChecked()
        cfg.end_duration = self.end_spin.value()
        cfg.move_speed = self.anim_dur_slider.value() / 10.0
        cfg.pause_after_move = self.pause_slider.value() / 10.0
        cfg.theme_name = self.theme_combo.currentText()
        cfg.coordinate_visible = self.show_coords_check.isChecked()
        cfg.show_arrow = self.show_arrow_check.isChecked()

        self._batch_exporting = True
        self._batch_cancelled = False
        self._batch_total = len(puzzles)
        self._batch_completed = 0
        self._batch_queue = puzzles

        # Create batch output directory
        os.makedirs(EXPORT_DIR, exist_ok=True)
        batch_dir = os.path.join(EXPORT_DIR, "batch")
        os.makedirs(batch_dir, exist_ok=True)

        # UI updates
        self.batch_progress.setVisible(True)
        self.batch_progress.setMaximum(self._batch_total)
        self.batch_progress.setValue(0)
        self.batch_cancel_btn.setVisible(True)
        self.batch_selected_btn.setEnabled(False)
        self.batch_page_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.batch_status.setText(f"Starting batch: {self._batch_total} puzzles…")
        self.batch_status.setStyleSheet("color: #565f89; font-size: 10px;")
        self.status.showMessage(f"Batch export started: {self._batch_total} puzzles")

        self._exporter = FFmpegVideoExporter(cfg)
        self._exporter.batch_puzzle_done.connect(self._batch_puzzle_done_cb)
        self._exporter.finished.connect(self._batch_finished_cb)
        self._exporter.error.connect(self._batch_error_cb)
        self._exporter.log_msg.connect(lambda msg: log(msg, "BATCH"))

        self._exporter.export_batch(puzzles, batch_dir)

    def _batch_puzzle_done_cb(self, completed, total, puzzle_name):
        self._batch_completed = completed
        self.batch_progress.setValue(completed)
        pct = completed * 100 // max(1, total)
        self.batch_status.setText(f"Exported {completed}/{total} ({pct}%) — {puzzle_name}")
        self.status.showMessage(f"Batch: {completed}/{total} — {puzzle_name}")

        # Mark each exported puzzle in manifest
        if completed > 0 and completed <= len(self._batch_queue):
            puzzle = self._batch_queue[completed - 1]
            pid = str(puzzle.get('id', ''))
            fname = sanitize_filename(puzzle.get('name', f'puzzle_{completed}'))
            ext = '.gif' if self.export_cfg.export_gif else '.mp4'
            batch_dir = os.path.join(EXPORT_DIR, "batch")
            out_path = os.path.join(batch_dir, f"{fname}{ext}")
            self.export_manifest.mark_exported(pid, out_path, self.export_cfg.preset_name,
                                               puzzle.get('name', ''))

    def _batch_finished_cb(self, output_dir):
        self._batch_exporting = False
        self._exporter = None

        self.batch_cancel_btn.setVisible(False)
        self.batch_selected_btn.setEnabled(True)
        self.batch_page_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

        if self._batch_cancelled:
            self.batch_status.setText(
                f"Batch cancelled — {self._batch_completed}/{self._batch_total} exported")
            self.batch_status.setStyleSheet("color: #e0af68; font-size: 10px;")
            self.status.showMessage("Batch export cancelled")
        else:
            self.batch_status.setText(
                f"✓ Batch complete: {self._batch_completed}/{self._batch_total} puzzles exported")
            self.batch_status.setStyleSheet("color: #9ece6a; font-size: 10px;")
            self.status.showMessage(f"Batch export complete: {output_dir}")

        # Refresh puzzle list to show exported indicators
        current_row = self.puzzle_list.currentRow()
        self._refresh_puzzle_list()
        if current_row >= 0: self.puzzle_list.setCurrentRow(current_row)

    def _batch_error_cb(self, msg):
        self._batch_exporting = False
        self._exporter = None

        self.batch_cancel_btn.setVisible(False)
        self.batch_selected_btn.setEnabled(True)
        self.batch_page_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

        self.batch_status.setText(f"✗ Batch error: {msg}")
        self.batch_status.setStyleSheet("color: #f7768e; font-size: 10px;")
        self.status.showMessage(f"Batch export error: {msg}")

    def _on_batch_cancel(self):
        if self._exporter:
            self._exporter.cancel()
        self._batch_cancelled = True
        self.batch_status.setText("Cancelling…")
        self.batch_status.setStyleSheet("color: #e0af68; font-size: 10px;")
        self.batch_cancel_btn.setEnabled(False)

    # ══════════════════════════════════════════════════════════════════════════
    #  IMPORT
    # ══════════════════════════════════════════════════════════════════════════

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Puzzles", DATA_DIR,
            "All Supported (*.csv *.json *.parquet *.pgn *.tsv);;"
            "CSV (*.csv);;JSON (*.json);;Parquet (*.parquet);;PGN (*.pgn);;TSV (*.tsv)")
        if not path: return
        self.status.showMessage(f"Importing {os.path.basename(path)}…")
        QApplication.processEvents()

        def _w():
            try:
                self.puzzle_loader.load_file(path)
                log(f"Imported {self.puzzle_loader.total_count} puzzles from {path}", "IMPORT")
            except Exception as e:
                log(f"Import error: {e}", "ERROR")
                QTimer.singleShot(0, lambda: self.status.showMessage(f"Import error: {e}"))
                return
            QTimer.singleShot(0, self._on_import_done)

        threading.Thread(target=_w, daemon=True).start()

    def _on_import_done(self):
        self._refresh_puzzle_list(); self._update_pagination_ui()
        self.status.showMessage(f"{self.puzzle_loader.total_count:,} puzzles imported ✓")

    # ══════════════════════════════════════════════════════════════════════════
    #  CLOSE
    # ══════════════════════════════════════════════════════════════════════════

    def closeEvent(self, event):
        self._stop_auto_play()
        if self._exporter:
            self._exporter.cancel()
        self.export_manifest.close()
        self.sound_mgr.cleanup()
        event.accept()