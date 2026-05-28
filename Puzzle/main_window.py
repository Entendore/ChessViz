#!/usr/bin/env python3
"""Main application window — puzzle controls inline, tabs in right panel."""

import os
import shutil
import threading
import chess

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QTextEdit, QFrame,
    QListWidget, QListWidgetItem, QSlider, QSpinBox,
    QLineEdit, QFormLayout, QComboBox, QProgressBar,
    QGroupBox, QCheckBox, QFileDialog, QScrollArea,
    QSplitter, QMessageBox, QDoubleSpinBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from config import (
    THEMES, EXPORT_PRESETS, ExportConfig, MiniColors, SOUND_PRESETS,
    ANIM_SPEED_DEFAULT, SQ_SIZE, LayoutMode, LAYOUT_MODES, PUZZLES_PER_PAGE,
    DATA_DIR, LICHESS_PARQUET_NAME,
)
from utils import log, sanitize_filename
from chess_engine import ChessEngine
from sound_manager import SoundManager
from board_widget import ChessBoardWidget
from puzzle_loader import PuzzleLoader
from video_exporter import FFmpegVideoExporter

HAS_FFMPEG = shutil.which('ffmpeg') is not None

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chess Puzzle Studio")
        self.setMinimumSize(1100, 750)

        self.engine = ChessEngine()
        self.sound_mgr = SoundManager()
        self.export_config = ExportConfig()
        self.exporter = None

        self.puzzles = []
        self.current_puzzle_idx = -1
        self.current_puzzle = None
        self.puzzle_move_idx = 0
        self.puzzle_mode = False
        self.auto_play_timer = QTimer(self)
        self.auto_play_timer.setSingleShot(True)
        self.auto_play_timer.timeout.connect(self._auto_play_response)

        self.current_page = 0
        self.total_pages = 0
        self.total_puzzle_count = 0

        self._build_ui()
        self._connect_signals()
        self._apply_theme()
        QTimer.singleShot(100, self._auto_load_lichess_db)

    # ── UI Construction ─────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        main_layout = QVBoxLayout(central); main_layout.setContentsMargins(6, 6, 6, 6)
        splitter = QSplitter(Qt.Horizontal)

        # ── Left: Puzzle List ──
        left_panel = self._build_puzzle_list_panel()
        splitter.addWidget(left_panel)

        # ── Center: Board + Controls ──
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(4, 4, 4, 4)
        center_layout.setSpacing(4)

        self.board_widget = ChessBoardWidget(self.engine, self.sound_mgr)
        center_layout.addWidget(self.board_widget, alignment=Qt.AlignCenter)

        # Compact puzzle info
        info_frame = QFrame()
        info_frame.setObjectName("puzzleInfoFrame")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(8, 2, 8, 2)
        info_layout.setSpacing(1)

        name_row = QHBoxLayout()
        self.puzzle_name_label = QLabel("—")
        self.puzzle_name_label.setWordWrap(True)
        self.puzzle_name_label.setStyleSheet(
            f"color: {MiniColors.accent}; font-weight: bold; font-size: 13px;")
        self.puzzle_diff_label = QLabel("—")
        self.puzzle_diff_label.setStyleSheet(
            f"color: {MiniColors.yellow}; font-size: 12px;")
        name_row.addWidget(self.puzzle_name_label, stretch=1)
        name_row.addWidget(self.puzzle_diff_label)
        info_layout.addLayout(name_row)

        self.puzzle_desc_label = QLabel("—")
        self.puzzle_desc_label.setWordWrap(True)
        self.puzzle_desc_label.setMaximumHeight(36)
        self.puzzle_desc_label.setStyleSheet(
            f"color: {MiniColors.text_dim}; font-size: 11px;")
        info_layout.addWidget(self.puzzle_desc_label)
        center_layout.addWidget(info_frame)

        # Control buttons row
        ctrl_row = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Prev")
        self.btn_next = QPushButton("Next ▶")
        self.btn_reset = QPushButton("↺ Reset")
        self.btn_hint = QPushButton("💡 Hint")
        self.btn_prev.clicked.connect(self._on_prev_puzzle)
        self.btn_next.clicked.connect(self._on_next_puzzle)
        self.btn_reset.clicked.connect(self._on_reset_puzzle)
        self.btn_hint.clicked.connect(self._on_hint)
        ctrl_row.addWidget(self.btn_prev)
        ctrl_row.addWidget(self.btn_next)
        ctrl_row.addWidget(self.btn_reset)
        ctrl_row.addWidget(self.btn_hint)
        center_layout.addLayout(ctrl_row)

        self.puzzle_status_label = QLabel("")
        self.puzzle_status_label.setAlignment(Qt.AlignCenter)
        self.puzzle_status_label.setStyleSheet(
            f"color: {MiniColors.green}; font-weight: bold; font-size: 14px;")
        center_layout.addWidget(self.puzzle_status_label)

        center_layout.addStretch()
        splitter.addWidget(center_panel)

        # ── Right: Tabs (History, Export, Settings) ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_panel.setMinimumWidth(320)

        self.tabs = QTabWidget()
        self._build_history_tab()
        self._build_export_tab()
        self._build_settings_tab()
        right_layout.addWidget(self.tabs)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 2)
        main_layout.addWidget(splitter)
        self.statusBar().showMessage("Ready — Load a puzzle file to begin")

    # ── Left Panel ──

    def _build_puzzle_list_panel(self):
        panel = QWidget(); layout = QVBoxLayout(panel)
        btn_load = QPushButton("📁 Load Puzzle File"); btn_load.setObjectName("accentButton"); btn_load.clicked.connect(self._on_load_file)
        layout.addWidget(btn_load)

        filter_group = QGroupBox("Filters"); filter_layout = QFormLayout(filter_group)
        self.combo_theme_filter = QComboBox(); self.combo_theme_filter.addItem("All Themes")
        from puzzle_utils import LICHESS_THEME_LIST
        self.combo_theme_filter.addItems(LICHESS_THEME_LIST)
        self.combo_theme_filter.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addRow("Theme:", self.combo_theme_filter)
        rating_layout = QHBoxLayout()
        self.spin_min_rating = QSpinBox(); self.spin_min_rating.setRange(0, 3500); self.spin_min_rating.setValue(0)
        self.spin_max_rating = QSpinBox(); self.spin_max_rating.setRange(0, 3500); self.spin_max_rating.setValue(3500)
        rating_layout.addWidget(QLabel("Min:")); rating_layout.addWidget(self.spin_min_rating)
        rating_layout.addWidget(QLabel("Max:")); rating_layout.addWidget(self.spin_max_rating)
        filter_layout.addRow("Rating:", rating_layout)
        btn_apply_filter = QPushButton("Apply Filters"); btn_apply_filter.clicked.connect(self._on_filter_changed)
        filter_layout.addRow(btn_apply_filter)
        layout.addWidget(filter_group)

        self.puzzle_list = QListWidget(); self.puzzle_list.currentRowChanged.connect(self._on_puzzle_selected)
        layout.addWidget(self.puzzle_list)

        page_layout = QHBoxLayout()
        self.btn_prev_page = QPushButton("◀"); self.btn_prev_page.clicked.connect(self._on_prev_page)
        self.btn_next_page = QPushButton("▶"); self.btn_next_page.clicked.connect(self._on_next_page)
        self.page_label = QLabel("Page 0/0"); self.page_label.setAlignment(Qt.AlignCenter)
        page_layout.addWidget(self.btn_prev_page); page_layout.addWidget(self.page_label, stretch=1); page_layout.addWidget(self.btn_next_page)
        layout.addLayout(page_layout)

        self.puzzle_count_label = QLabel("0 puzzles"); self.puzzle_count_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.puzzle_count_label)
        return panel

    # ── Right Panel Tabs ──

    def _build_history_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Move History"))
        self.history_text = QTextEdit(); self.history_text.setReadOnly(True); self.history_text.setFont(QFont("Monospace", 10))
        layout.addWidget(self.history_text)
        self.fen_label = QLabel("FEN: —"); self.fen_label.setWordWrap(True); self.fen_label.setFont(QFont("Monospace", 8))
        layout.addWidget(self.fen_label)
        self.tabs.addTab(tab, "📜 History")

    def _build_export_tab(self):
        tab = QWidget(); scroll = QScrollArea(); scroll.setWidget(tab); scroll.setWidgetResizable(True)
        layout = QVBoxLayout(tab)

        # Preset & Layout
        preset_group = QGroupBox("Resolution & Layout"); preset_layout = QFormLayout(preset_group)
        self.combo_preset = QComboBox()
        for name in EXPORT_PRESETS: self.combo_preset.addItem(name)
        self.combo_preset.setCurrentText(self.export_config.preset_name)
        self.combo_preset.currentTextChanged.connect(self._on_preset_changed)
        preset_layout.addRow("Preset:", self.combo_preset)
        self.combo_layout = QComboBox()
        for mode, text in LAYOUT_MODES.items(): self.combo_layout.addItem(text, mode)
        self.combo_layout.setCurrentIndex(1)
        self.combo_layout.currentIndexChanged.connect(self._on_layout_changed)
        preset_layout.addRow("Layout:", self.combo_layout)
        self.spin_fps = QComboBox(); self.spin_fps.addItems(["30", "60"]); self.spin_fps.setCurrentText("30")
        preset_layout.addRow("Frame Rate:", self.spin_fps)
        layout.addWidget(preset_group)

        # Animation Phases
        phase_group = QGroupBox("Animation Phases"); phase_layout = QFormLayout(phase_group)

        self.chk_title = QCheckBox(); self.chk_title.setChecked(True)
        self.spin_title_dur = QDoubleSpinBox(); self.spin_title_dur.setRange(1.0, 10.0); self.spin_title_dur.setValue(3.0); self.spin_title_dur.setSingleStep(0.5)
        phase_layout.addRow("Title Screen:", self.chk_title); phase_layout.addRow("Title Duration (s):", self.spin_title_dur)

        self.chk_hold = QCheckBox(); self.chk_hold.setChecked(True)
        self.spin_hold_dur = QDoubleSpinBox(); self.spin_hold_dur.setRange(1.0, 15.0); self.spin_hold_dur.setValue(3.0); self.spin_hold_dur.setSingleStep(0.5)
        self.edit_hold_text = QLineEdit("White to play")
        phase_layout.addRow("Position Hold:", self.chk_hold); phase_layout.addRow("Hold Duration (s):", self.spin_hold_dur); phase_layout.addRow("Overlay Text:", self.edit_hold_text)

        self.spin_move_speed = QDoubleSpinBox(); self.spin_move_speed.setRange(0.3, 5.0); self.spin_move_speed.setValue(1.0); self.spin_move_speed.setSingleStep(0.1)
        self.spin_pause = QDoubleSpinBox(); self.spin_pause.setRange(0.0, 3.0); self.spin_pause.setValue(0.5); self.spin_pause.setSingleStep(0.1)
        self.chk_pause_key = QCheckBox(); self.chk_pause_key.setChecked(True)
        self.spin_loops = QSpinBox(); self.spin_loops.setRange(1, 10); self.spin_loops.setValue(1)
        phase_layout.addRow("Move Speed (s):", self.spin_move_speed); phase_layout.addRow("Pause Between (s):", self.spin_pause)
        phase_layout.addRow("Pause on Key Moves:", self.chk_pause_key); phase_layout.addRow("Loop Count:", self.spin_loops)

        self.chk_end = QCheckBox(); self.chk_end.setChecked(True)
        self.spin_end_dur = QDoubleSpinBox(); self.spin_end_dur.setRange(1.0, 10.0); self.spin_end_dur.setValue(3.0); self.spin_end_dur.setSingleStep(0.5)
        phase_layout.addRow("End Screen:", self.chk_end); phase_layout.addRow("End Duration (s):", self.spin_end_dur)
        layout.addWidget(phase_group)

        # Visuals
        vis_group = QGroupBox("Visuals"); vis_layout = QFormLayout(vis_group)
        self.chk_highlight = QCheckBox(); self.chk_highlight.setChecked(True)
        self.chk_move_list = QCheckBox(); self.chk_move_list.setChecked(True)
        self.chk_coords = QCheckBox(); self.chk_coords.setChecked(True)
        self.chk_postproc = QCheckBox(); self.chk_postproc.setChecked(True)
        self.chk_arrow_export = QCheckBox(); self.chk_arrow_export.setChecked(True)
        vis_layout.addRow("Highlight Last Move:", self.chk_highlight)
        vis_layout.addRow("Move List Visible:", self.chk_move_list)
        vis_layout.addRow("Board Coordinates:", self.chk_coords)
        vis_layout.addRow("Show Arrows:", self.chk_arrow_export)
        vis_layout.addRow("Post-Processing:", self.chk_postproc)
        layout.addWidget(vis_group)

        # Output & Sound Design
        out_group = QGroupBox("Output & Sound Design"); out_layout = QFormLayout(out_group)
        self.combo_preset_ff = QComboBox(); self.combo_preset_ff.addItems(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        self.combo_preset_ff.setCurrentText("medium")
        out_layout.addRow("Encode Speed:", self.combo_preset_ff)

        self.combo_sound_preset = QComboBox()
        for name in SOUND_PRESETS:
            self.combo_sound_preset.addItem(name)
        self.combo_sound_preset.setCurrentText("None")
        out_layout.addRow("Sound Design:", self.combo_sound_preset)

        self.lbl_sound_desc = QLabel("")
        self.lbl_sound_desc.setWordWrap(True)
        self.lbl_sound_desc.setStyleSheet(f"color: {MiniColors.text_dim}; font-size: 11px;")
        self.combo_sound_preset.currentTextChanged.connect(self._on_sound_preset_changed)
        out_layout.addRow("", self.lbl_sound_desc)

        layout.addWidget(out_group)

        btn_layout = QHBoxLayout()
        self.btn_export = QPushButton("🎬 Export Current"); self.btn_export.setObjectName("accentButton"); self.btn_export.clicked.connect(self._on_export)
        self.btn_export_batch = QPushButton("📦 Batch Export Page"); self.btn_export_batch.clicked.connect(self._on_batch_export)
        self.btn_cancel_export = QPushButton("✖ Cancel"); self.btn_cancel_export.clicked.connect(self._on_cancel_export); self.btn_cancel_export.setEnabled(False)
        btn_layout.addWidget(self.btn_export); btn_layout.addWidget(self.btn_export_batch); btn_layout.addWidget(self.btn_cancel_export)
        layout.addLayout(btn_layout)

        self.progress_bar = QProgressBar(); self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar); layout.addStretch()
        self.tabs.addTab(scroll, "🎬 Export")

    def _build_settings_tab(self):
        tab = QWidget(); layout = QFormLayout(tab)
        self.combo_theme = QComboBox(); self.combo_theme.addItems(THEMES.keys()); self.combo_theme.setCurrentText("Midnight")
        self.combo_theme.currentTextChanged.connect(self._on_theme_changed)
        layout.addRow("Board theme:", self.combo_theme)

        self.chk_arrow = QCheckBox(); self.chk_arrow.setChecked(True)
        self.chk_arrow.toggled.connect(self._on_arrow_toggled)
        layout.addRow("Show move arrows:", self.chk_arrow)

        self.chk_sound = QCheckBox(); self.chk_sound.setChecked(True); self.chk_sound.toggled.connect(self._on_sound_toggled)
        layout.addRow("Sound enabled:", self.chk_sound)
        self.slider_volume = QSlider(Qt.Horizontal); self.slider_volume.setRange(0, 100); self.slider_volume.setValue(70)
        self.slider_volume.valueChanged.connect(self._on_volume_changed)
        layout.addRow("Volume:", self.slider_volume)
        self.slider_anim_speed = QSlider(Qt.Horizontal); self.slider_anim_speed.setRange(0, 500); self.slider_anim_speed.setValue(ANIM_SPEED_DEFAULT)
        self.slider_anim_speed.valueChanged.connect(self._on_anim_speed_changed)
        layout.addRow("        UI Anim speed (ms):", self.slider_anim_speed)
        self.lbl_anim_speed = QLabel(f"{ANIM_SPEED_DEFAULT} ms"); layout.addRow("", self.lbl_anim_speed)
        ffmpeg_status = "✅ Available" if HAS_FFMPEG else "❌ Not found"
        layout.addRow("FFmpeg:", QLabel(ffmpeg_status))
        self.tabs.addTab(tab, "⚙ Settings")

    def _connect_signals(self):
        self.board_widget.move_made.connect(self._on_move_made)

    # ── Puzzle Loading & Pagination ─────────────────────────────────────

    def _on_load_file(self):
        """UI button trigger for loading files."""
        path, _ = QFileDialog.getOpenFileName(self, "Open Puzzle File", "",
            "Puzzle files (*.csv *.json *.parquet *.pgn *.tsv);;All files (*)")
        if path:
            self._load_puzzle_file(path)

    def _load_puzzle_file(self, path):
        """Core file loading logic, separated out so it can be called by auto-loader."""
        try:
            self.puzzle_loader.load_file(path)
            self.current_page = 0
            if self.puzzle_loader.lazy_store:
                self.total_puzzle_count = self.puzzle_loader.lazy_store.filtered_total
            else:
                self.total_puzzle_count = len(self.puzzle_loader.puzzles)
            self.total_pages = max(1, (self.total_puzzle_count + PUZZLES_PER_PAGE - 1) // PUZZLES_PER_PAGE)
            self._load_current_page()
            self.statusBar().showMessage(f"Loaded {self.total_puzzle_count} puzzles from {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))

    def _load_current_page(self):
        if self.puzzle_loader.lazy_store:
            self.puzzles = self.puzzle_loader.lazy_store.get_page(self.current_page)
        else:
            start = self.current_page * PUZZLES_PER_PAGE
            self.puzzles = self.puzzle_loader.puzzles[start:start + PUZZLES_PER_PAGE]
        self.puzzle_list.clear()
        for p in self.puzzles:
            item = QListWidgetItem(p['name'][:80]); item.setData(Qt.UserRole, p); self.puzzle_list.addItem(item)
        self.puzzle_count_label.setText(f"{self.total_puzzle_count} puzzles")
        self.page_label.setText(f"Page {self.current_page + 1}/{self.total_pages}")
        if self.puzzles: self.puzzle_list.setCurrentRow(0)

    def _on_prev_page(self):
        if self.current_page > 0: self.current_page -= 1; self._load_current_page()

    def _on_next_page(self):
        if self.current_page < self.total_pages - 1: self.current_page += 1; self._load_current_page()

    def _on_filter_changed(self):
        if not self.puzzle_loader.lazy_store: return
        filters = {'min_rating': self.spin_min_rating.value(), 'max_rating': self.spin_max_rating.value(),
                   'theme': self.combo_theme_filter.currentText() if self.combo_theme_filter.currentIndex() > 0 else None}
        self.puzzle_loader.lazy_store.set_filters(filters)
        self.total_puzzle_count = self.puzzle_loader.lazy_store.filtered_total
        self.total_pages = max(1, (self.total_puzzle_count + PUZZLES_PER_PAGE - 1) // PUZZLES_PER_PAGE)
        self.current_page = 0; self._load_current_page()

    def _on_puzzle_selected(self, row):
        if row < 0 or row >= len(self.puzzles): return
        self.current_puzzle_idx = row; self.current_puzzle = self.puzzles[row]; self._start_puzzle()

    def _start_puzzle(self):
        p = self.current_puzzle
        if not p: return
        fen = p.get('fen', '')
        if fen: self.engine.load_fen(fen)
        else: self.engine.reset()
        self.puzzle_move_idx = 0; self.puzzle_mode = True; self.auto_play_timer.stop()
        self.puzzle_name_label.setText(p.get('name', '—'))
        self.puzzle_diff_label.setText(f"{p.get('difficulty', 0):.2f}")
        self.puzzle_desc_label.setText(p.get('desc', '—'))
        self.puzzle_status_label.setText("")
        self.history_text.clear(); self.fen_label.setText(f"FEN: {self.engine.board.fen()}")
        self.board_widget.selected = None; self.board_widget.legal_targets = []; self.board_widget.update()
        setup_count = p.get('setup_count', 0)
        if setup_count > 0:
            self.puzzle_status_label.setText("Playing setup move...")
            QTimer.singleShot(400, self._auto_play_setup)

    def _auto_play_setup(self):
        if not self.current_puzzle or not self.puzzle_mode: return
        moves = self.current_puzzle.get('moves', [])
        if self.puzzle_move_idx < len(moves):
            next_uci = moves[self.puzzle_move_idx]; info = self.engine.make_move_uci(next_uci)
            if info:
                self.puzzle_move_idx += 1; self.history_text.append(f"Setup: {info['notation']}")
                self.fen_label.setText(f"FEN: {self.engine.board.fen()}"); self.board_widget.update()
                self.puzzle_status_label.setText("Your turn")
            else: self.puzzle_status_label.setText("Setup error")

    def _on_prev_puzzle(self):
        if self.current_puzzle_idx > 0: self.puzzle_list.setCurrentRow(self.current_puzzle_idx - 1)
    def _on_next_puzzle(self):
        if self.current_puzzle_idx < len(self.puzzles) - 1: self.puzzle_list.setCurrentRow(self.current_puzzle_idx + 1)
    def _on_reset_puzzle(self):
        if self.current_puzzle: self._start_puzzle()

    def _on_hint(self):
        if not self.current_puzzle or not self.puzzle_mode: return
        moves = self.current_puzzle.get('moves', [])
        if self.puzzle_move_idx < len(moves):
            next_uci = moves[self.puzzle_move_idx]; info = self.engine.make_move_uci(next_uci)
            if info:
                self.puzzle_move_idx += 1
                self.history_text.append(f"{'White' if self.engine.board.turn == chess.BLACK else 'Black'}: {info['notation']} (Hint)")
                self.fen_label.setText(f"FEN: {self.engine.board.fen()}"); self.board_widget.update()
                if self.puzzle_move_idx < len(moves): self._schedule_auto_play()
                else: self.puzzle_mode = False; self.puzzle_status_label.setText("Puzzle complete!")

    def _on_move_made(self, notation):
        if not notation: return
        turn_str = 'White' if self.engine.board.turn == chess.BLACK else 'Black'
        self.history_text.append(f"{turn_str}: {notation}"); self.fen_label.setText(f"FEN: {self.engine.board.fen()}")
        if self.puzzle_mode and self.current_puzzle:
            moves = self.current_puzzle.get('moves', [])
            if self.puzzle_move_idx < len(moves): self._schedule_auto_play()
            else: self.puzzle_mode = False; self.puzzle_status_label.setText("Puzzle complete!")
        if self.engine.game_over: self.puzzle_mode = False; self.puzzle_status_label.setText(f"Game Over: {self.engine.result}")

    def _schedule_auto_play(self):
        if not self.current_puzzle: return
        if self.puzzle_move_idx < len(self.current_puzzle.get('moves', [])): self.auto_play_timer.start(600)

    def _auto_play_response(self):
        if not self.current_puzzle or not self.puzzle_mode: return
        moves = self.current_puzzle.get('moves', [])
        if self.puzzle_move_idx >= len(moves): return
        next_uci = moves[self.puzzle_move_idx]; info = self.engine.make_move_uci(next_uci)
        if info:
            self.puzzle_move_idx += 1; turn_str = 'White' if self.engine.board.turn == chess.BLACK else 'Black'
            self.history_text.append(f"{turn_str}: {info['notation']}"); self.fen_label.setText(f"FEN: {self.engine.board.fen()}")
            if self.engine.game_over: self.puzzle_mode = False; self.puzzle_status_label.setText(f"Game Over: {self.engine.result}")
            elif self.puzzle_move_idx >= len(moves): self.puzzle_mode = False; self.puzzle_status_label.setText("Puzzle complete!")
            self.board_widget.update()
        else: log(f"Failed to auto-play response: {next_uci}", "PUZZLE")

    # ── Settings Callbacks ──────────────────────────────────────────────

    def _on_theme_changed(self, name):
        if name in THEMES: self.board_widget.current_theme = THEMES[name]; self.export_config.theme_name = name; self.board_widget.update()

    def _on_arrow_toggled(self, checked):
        self.board_widget.show_arrow = checked
        self.board_widget.update()

    def _on_sound_toggled(self, checked): self.sound_mgr.set_enabled(checked)
    def _on_volume_changed(self, val): self.sound_mgr.set_volume(val / 100.0)
    def _on_anim_speed_changed(self, val): self.board_widget.anim_speed = val; self.lbl_anim_speed.setText(f"{val} ms")

    def _on_preset_changed(self, name):
        self.export_config.apply_preset(name)
        idx = self.combo_layout.findData(self.export_config.layout_mode)
        if idx >= 0: self.combo_layout.setCurrentIndex(idx)

    def _on_layout_changed(self, idx):
        mode = self.combo_layout.itemData(idx)
        if mode: self.export_config.layout_mode = mode

    def _on_sound_preset_changed(self, name):
        preset = SOUND_PRESETS.get(name, {})
        desc = preset.get('description', '')
        self.lbl_sound_desc.setText(desc)
        self.export_config.sound_preset = name

    # ── Export Logic ────────────────────────────────────────────────────

    def _sync_export_config(self):
        cfg = self.export_config
        cfg.fps = int(self.spin_fps.currentText())
        cfg.title_enabled = self.chk_title.isChecked(); cfg.title_duration = self.spin_title_dur.value()
        cfg.position_hold_enabled = self.chk_hold.isChecked(); cfg.position_hold_duration = self.spin_hold_dur.value()
        cfg.position_overlay_text = self.edit_hold_text.text()
        cfg.end_enabled = self.chk_end.isChecked(); cfg.end_duration = self.spin_end_dur.value()
        cfg.move_speed = self.spin_move_speed.value(); cfg.pause_after_move = self.spin_pause.value()
        cfg.pause_on_key_moves = self.chk_pause_key.isChecked()
        cfg.loop_count = self.spin_loops.value()
        cfg.highlight_last_move = self.chk_highlight.isChecked(); cfg.move_list_visible = self.chk_move_list.isChecked()
        cfg.coordinate_visible = self.chk_coords.isChecked(); cfg.gpu_post_process = self.chk_postproc.isChecked()
        cfg.show_arrow = self.chk_arrow_export.isChecked()
        cfg.ffmpeg_preset = self.combo_preset_ff.currentText()
        cfg.audio_path = ""  # Audio browse removed; only sound presets used
        cfg.theme_name = self.combo_theme.currentText()
        cfg.sound_preset = self.combo_sound_preset.currentText()
        # Width/Height sync from preset
        p = EXPORT_PRESETS.get(self.combo_preset.currentText())
        if p: cfg.target_width = p.width; cfg.target_height = p.height

    def _create_exporter(self):
        self._sync_export_config()
        self.exporter = FFmpegVideoExporter(self.export_config)
        self.exporter.progress.connect(self._on_export_progress)
        self.exporter.finished.connect(self._on_export_finished)
        self.exporter.error.connect(self._on_export_error)
        self.exporter.log_msg.connect(lambda m: self.statusBar().showMessage(m))
        # Pass sound design to exporter
        self.exporter.set_sound_design(self.sound_mgr, self.export_config.sound_preset)

    def _on_export(self):
        if not self.current_puzzle: QMessageBox.warning(self, "Export", "No puzzle selected."); return
        if not HAS_FFMPEG: QMessageBox.critical(self, "Export Error", "FFmpeg not found!"); return
        ext = '.mp4'
        default_name = sanitize_filename(self.current_puzzle.get('name', 'puzzle')) + ext
        path, _ = QFileDialog.getSaveFileName(self, "Export Video", default_name, f"Video (*{ext});;All files (*)")
        if not path: return
        self._create_exporter()
        self.progress_bar.setVisible(True); self.progress_bar.setValue(0)
        self.btn_export.setEnabled(False); self.btn_export_batch.setEnabled(False); self.btn_cancel_export.setEnabled(True)
        self.exporter.export_puzzle_threaded(self.current_puzzle, path)

    def _on_batch_export(self):
        puzzles_to_export = self.puzzles
        if not puzzles_to_export: QMessageBox.warning(self, "Export", "No puzzles loaded."); return
        if not HAS_FFMPEG: QMessageBox.critical(self, "Export Error", "FFmpeg not found!"); return
        output_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if not output_dir: return
        self._create_exporter()
        self.progress_bar.setVisible(True); self.progress_bar.setValue(0)
        self.btn_export.setEnabled(False); self.btn_export_batch.setEnabled(False); self.btn_cancel_export.setEnabled(True)
        threading.Thread(target=self.exporter.export_batch, args=(puzzles_to_export, output_dir), daemon=True).start()

    def _on_cancel_export(self):
        if self.exporter: self.exporter.cancel()

    def _on_export_progress(self, current, total):
        if total > 0: self.progress_bar.setMaximum(total); self.progress_bar.setValue(current)

    def _on_export_finished(self, path):
        self.progress_bar.setVisible(False); self.btn_export.setEnabled(True); self.btn_export_batch.setEnabled(True); self.btn_cancel_export.setEnabled(False)
        self.statusBar().showMessage(f"Export complete: {path}"); self.exporter = None

    def _on_export_error(self, msg):
        self.progress_bar.setVisible(False); self.btn_export.setEnabled(True); self.btn_export_batch.setEnabled(True); self.btn_cancel_export.setEnabled(False)
        QMessageBox.critical(self, "Export Error", msg); self.exporter = None

    # ── Minimalist Theme ────────────────────────────────────────────────

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background: {MiniColors.bg}; }}
            QWidget {{ color: {MiniColors.text}; font-size: 13px; font-family: 'Inter', 'Segoe UI', sans-serif; }}
            QTabWidget::pane {{ border: 1px solid {MiniColors.border}; background: {MiniColors.bg}; }}
            QTabBar::tab {{ background: {MiniColors.surface}; padding: 8px 16px; border: 1px solid {MiniColors.border_subtle}; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; color: {MiniColors.text_dim}; }}
            QTabBar::tab:selected {{ background: {MiniColors.surface2}; color: {MiniColors.accent}; border-bottom: 2px solid {MiniColors.accent}; }}
            QGroupBox {{ border: 1px solid {MiniColors.border_subtle}; border-radius: 6px; margin-top: 12px; padding-top: 16px; background: {MiniColors.surface}; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {MiniColors.text_subtle}; }}
            QPushButton {{ background: {MiniColors.surface2}; border: 1px solid {MiniColors.border}; border-radius: 4px; padding: 6px 14px; color: {MiniColors.text}; }}
            QPushButton:hover {{ background: {MiniColors.border}; }}
            QPushButton:pressed {{ background: {MiniColors.text_dim}; }}
            QPushButton:disabled {{ background: {MiniColors.bg}; color: {MiniColors.border}; }}
            QPushButton#accentButton {{ background: {MiniColors.accent_dim}; color: white; border: 1px solid {MiniColors.accent}; }}
            QPushButton#accentButton:hover {{ background: {MiniColors.accent}; }}
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{ background: {MiniColors.surface}; border: 1px solid {MiniColors.border_subtle}; border-radius: 4px; padding: 4px 8px; color: {MiniColors.text}; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{ background: {MiniColors.surface}; selection-background-color: {MiniColors.accent_dim}; }}
            QListWidget {{ background: {MiniColors.surface}; border: 1px solid {MiniColors.border_subtle}; border-radius: 4px; }}
            QListWidget::item:selected {{ background: {MiniColors.accent_dim}; color: white; }}
            QTextEdit {{ background: {MiniColors.surface}; border: 1px solid {MiniColors.border_subtle}; border-radius: 4px; color: {MiniColors.text}; }}
            QProgressBar {{ border: 1px solid {MiniColors.border_subtle}; border-radius: 4px; text-align: center; background: {MiniColors.surface}; color: {MiniColors.text}; }}
            QProgressBar::chunk {{ background: {MiniColors.accent}; border-radius: 3px; }}
            QSlider::groove:horizontal {{ background: {MiniColors.surface2}; height: 4px; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: {MiniColors.accent}; width: 14px; margin: -5px 0; border-radius: 7px; }}
            QSlider::sub-page:horizontal {{ background: {MiniColors.accent_dim}; border-radius: 2px; }}
            QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 3px; border: 1px solid {MiniColors.border}; background: {MiniColors.surface}; }}
            QCheckBox::indicator:checked {{ background: {MiniColors.accent}; border-color: {MiniColors.accent}; }}
            QScrollArea {{ border: none; }}
            QLabel {{ background: transparent; }}
            QFrame#puzzleInfoFrame {{ background: {MiniColors.surface}; border: 1px solid {MiniColors.border_subtle}; border-radius: 6px; }}
        """)

    def closeEvent(self, event):
        self.auto_play_timer.stop()
        if self.exporter: self.exporter.cancel()
        self.puzzle_loader.close(); self.sound_mgr.cleanup()
        event.accept()

    def _auto_load_lichess_db(self):
        """Attempts to auto-load the Lichess puzzle database from the data directory."""
        db_path = os.path.join(DATA_DIR, LICHESS_PARQUET_NAME)
        if os.path.exists(db_path):
            self.statusBar().showMessage(f"Auto-loading {LICHESS_PARQUET_NAME}...")
            try:
                self._load_puzzle_file(db_path)
            except Exception as e:
                self.statusBar().showMessage(f"Failed to auto-load Lichess db: {e}")
        else:
            self.statusBar().showMessage("Ready — Load a puzzle file to begin")