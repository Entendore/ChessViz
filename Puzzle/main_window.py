#!/usr/bin/env python3
"""Main application window with puzzle, export, and settings tabs."""

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
    QSplitter, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from config import (
    THEMES, EXPORT_PRESETS, ExportConfig,
    ANIM_SPEED_SLOW, ANIM_SPEED_DEFAULT, ANIM_SPEED_FAST, SQ_SIZE,
)
from utils import log, sanitize_filename
from chess_engine import ChessEngine
from sound_manager import SoundManager
from board_widget import ChessBoardWidget
from puzzle_loader import PuzzleLoader
from video_exporter import FFmpegVideoExporter

# ── Local Dependency Check ──────────────────────────────────────────────────

HAS_FFMPEG = shutil.which('ffmpeg') is not None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chess Puzzle Studio")
        self.setMinimumSize(1100, 750)

        # Core objects
        self.engine = ChessEngine()
        self.sound_mgr = SoundManager()
        self.puzzle_loader = PuzzleLoader()
        self.export_config = ExportConfig()
        self.exporter = None
        self.export_thread = None

        # Puzzle state
        self.puzzles = []
        self.current_puzzle_idx = -1
        self.current_puzzle = None
        self.puzzle_move_idx = 0
        self.puzzle_mode = False
        self.auto_play_timer = QTimer(self)
        self.auto_play_timer.setSingleShot(True)
        self.auto_play_timer.timeout.connect(self._auto_play_response)

        self._build_ui()
        self._connect_signals()
        self._apply_theme()

    # ── UI Construction ─────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Horizontal)

        left_panel = self._build_puzzle_list_panel()
        splitter.addWidget(left_panel)

        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)

        self.board_widget = ChessBoardWidget(self.engine, self.sound_mgr)
        center_layout.addWidget(self.board_widget, alignment=Qt.AlignCenter)

        self.tabs = QTabWidget()
        self.tabs.setMaximumHeight(320)
        self._build_puzzle_tab()
        self._build_export_tab()
        self._build_settings_tab()
        center_layout.addWidget(self.tabs)

        splitter.addWidget(center_panel)

        right_panel = self._build_history_panel()
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)

        main_layout.addWidget(splitter)
        self.statusBar().showMessage("Ready — Load a puzzle file to begin")

    def _build_puzzle_list_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        btn_load = QPushButton("📁 Load Puzzle File")
        btn_load.clicked.connect(self._on_load_file)
        layout.addWidget(btn_load)

        self.puzzle_list = QListWidget()
        self.puzzle_list.currentRowChanged.connect(self._on_puzzle_selected)
        layout.addWidget(self.puzzle_list)

        self.puzzle_count_label = QLabel("0 puzzles")
        layout.addWidget(self.puzzle_count_label)
        return panel

    def _build_history_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("Move History"))
        self.history_text = QTextEdit()
        self.history_text.setReadOnly(True)
        self.history_text.setFont(QFont("Monospace", 10))
        layout.addWidget(self.history_text)

        self.fen_label = QLabel("FEN: —")
        self.fen_label.setWordWrap(True)
        self.fen_label.setFont(QFont("Monospace", 8))
        layout.addWidget(self.fen_label)
        return panel

    # ── Puzzle Tab ──────────────────────────────────────────────────────

    def _build_puzzle_tab(self):
        tab = QWidget()
        layout = QHBoxLayout(tab)

        info_group = QGroupBox("Puzzle Info")
        info_layout = QFormLayout(info_group)
        self.puzzle_name_label = QLabel("—")
        self.puzzle_name_label.setWordWrap(True)
        self.puzzle_diff_label = QLabel("—")
        self.puzzle_desc_label = QLabel("—")
        self.puzzle_desc_label.setWordWrap(True)
        info_layout.addRow("Name:", self.puzzle_name_label)
        info_layout.addRow("Difficulty:", self.puzzle_diff_label)
        info_layout.addRow("Description:", self.puzzle_desc_label)
        layout.addWidget(info_group)

        ctrl_group = QGroupBox("Controls")
        ctrl_layout = QVBoxLayout(ctrl_group)
        btn_row1 = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Prev")
        self.btn_next = QPushButton("Next ▶")
        self.btn_reset = QPushButton("↺ Reset")
        self.btn_hint = QPushButton("💡 Hint")
        btn_row1.addWidget(self.btn_prev)
        self.btn_prev.clicked.connect(self._on_prev_puzzle)
        btn_row1.addWidget(self.btn_next)
        self.btn_next.clicked.connect(self._on_next_puzzle)
        btn_row1.addWidget(self.btn_reset)
        self.btn_reset.clicked.connect(self._on_reset_puzzle)
        btn_row1.addWidget(self.btn_hint)
        self.btn_hint.clicked.connect(self._on_hint)
        ctrl_layout.addLayout(btn_row1)

        self.puzzle_status_label = QLabel("")
        self.puzzle_status_label.setAlignment(Qt.AlignCenter)
        ctrl_layout.addWidget(self.puzzle_status_label)
        layout.addWidget(ctrl_group)

        self.tabs.addTab(tab, "♟ Puzzle")

    # ── Export Tab ──────────────────────────────────────────────────────

    def _build_export_tab(self):
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(tab)
        scroll.setWidgetResizable(True)
        layout = QVBoxLayout(tab)

        # Preset
        preset_group = QGroupBox("Preset")
        preset_layout = QFormLayout(preset_group)
        self.combo_preset = QComboBox()
        for name in EXPORT_PRESETS:
            self.combo_preset.addItem(name)
        self.combo_preset.setCurrentText(self.export_config.preset_name)
        self.combo_preset.currentTextChanged.connect(self._on_preset_changed)
        preset_layout.addRow("Preset:", self.combo_preset)

        self.spin_width = QSpinBox(); self.spin_width.setRange(128, 7680); self.spin_width.setValue(self.export_config.target_width)
        self.spin_height = QSpinBox(); self.spin_height.setRange(128, 4320); self.spin_height.setValue(self.export_config.target_height)
        self.spin_fps = QSpinBox(); self.spin_fps.setRange(1, 120); self.spin_fps.setValue(self.export_config.fps)
        preset_layout.addRow("Width:", self.spin_width)
        preset_layout.addRow("Height:", self.spin_height)
        preset_layout.addRow("FPS:", self.spin_fps)
        layout.addWidget(preset_group)

        # Title / End
        card_group = QGroupBox("Title / End Cards")
        card_layout = QFormLayout(card_group)
        self.chk_title = QCheckBox(); self.chk_title.setChecked(self.export_config.title_enabled)
        self.edit_title = QLineEdit(self.export_config.title_text)
        self.spin_title_dur = QSpinBox(); self.spin_title_dur.setRange(1, 30); self.spin_title_dur.setValue(int(self.export_config.title_duration))
        self.chk_end = QCheckBox(); self.chk_end.setChecked(self.export_config.end_enabled)
        self.edit_end = QLineEdit(self.export_config.end_text)
        self.spin_end_dur = QSpinBox(); self.spin_end_dur.setRange(1, 30); self.spin_end_dur.setValue(int(self.export_config.end_duration))
        card_layout.addRow("Title card:", self.chk_title); card_layout.addRow("Title text:", self.edit_title); card_layout.addRow("Title duration (s):", self.spin_title_dur)
        card_layout.addRow("End card:", self.chk_end); card_layout.addRow("End text:", self.edit_end); card_layout.addRow("End duration (s):", self.spin_end_dur)
        layout.addWidget(card_group)

        # Animation
        anim_group = QGroupBox("Animation")
        anim_layout = QFormLayout(anim_group)
        self.spin_anim_dur = QSpinBox(); self.spin_anim_dur.setRange(1, 100); self.spin_anim_dur.setValue(int(self.export_config.move_anim_duration * 10))
        self.spin_pause = QSpinBox(); self.spin_pause.setRange(1, 100); self.spin_pause.setValue(int(self.export_config.pause_after_move * 10))
        anim_layout.addRow("Move anim (×0.1s):", self.spin_anim_dur); anim_layout.addRow("Pause after (×0.1s):", self.spin_pause)
        layout.addWidget(anim_group)

        # FFmpeg
        ffmpeg_group = QGroupBox("FFmpeg Encoding")
        ffmpeg_layout = QFormLayout(ffmpeg_group)
        self.spin_crf = QSpinBox(); self.spin_crf.setRange(0, 51); self.spin_crf.setValue(self.export_config.ffmpeg_crf)
        self.combo_preset_ff = QComboBox(); self.combo_preset_ff.addItems(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        self.combo_preset_ff.setCurrentText(self.export_config.ffmpeg_preset)
        self.chk_gif = QCheckBox(); self.chk_gif.setChecked(self.export_config.export_gif)
        self.spin_gif_fps = QSpinBox(); self.spin_gif_fps.setRange(1, 30); self.spin_gif_fps.setValue(self.export_config.gif_fps)
        ffmpeg_layout.addRow("CRF:", self.spin_crf); ffmpeg_layout.addRow("Preset:", self.combo_preset_ff)
        ffmpeg_layout.addRow("Export as GIF:", self.chk_gif); ffmpeg_layout.addRow("GIF FPS:", self.spin_gif_fps)
        layout.addWidget(ffmpeg_group)

        # Audio
        audio_group = QGroupBox("Audio")
        audio_layout = QFormLayout(audio_group)
        self.edit_audio_path = QLineEdit(self.export_config.audio_path)
        btn_audio_browse = QPushButton("Browse…")
        btn_audio_browse.clicked.connect(self._on_browse_audio)
        audio_row = QHBoxLayout(); audio_row.addWidget(self.edit_audio_path); audio_row.addWidget(btn_audio_browse)
        audio_layout.addRow("Audio file:", audio_row)
        layout.addWidget(audio_group)

        # Post-processing
        pp_group = QGroupBox("Post-Processing")
        pp_layout = QFormLayout(pp_group)
        self.chk_postproc = QCheckBox(); self.chk_postproc.setChecked(self.export_config.gpu_post_process)
        self.slider_vignette = QSlider(Qt.Horizontal); self.slider_vignette.setRange(0, 100); self.slider_vignette.setValue(int(self.export_config.gpu_vignette * 100))
        self.slider_contrast = QSlider(Qt.Horizontal); self.slider_contrast.setRange(80, 150); self.slider_contrast.setValue(int(self.export_config.gpu_contrast * 100))
        self.slider_saturation = QSlider(Qt.Horizontal); self.slider_saturation.setRange(50, 200); self.slider_saturation.setValue(int(self.export_config.gpu_saturation * 100))
        pp_layout.addRow("Enable:", self.chk_postproc); pp_layout.addRow("Vignette:", self.slider_vignette)
        pp_layout.addRow("Contrast:", self.slider_contrast); pp_layout.addRow("Saturation:", self.slider_saturation)
        layout.addWidget(pp_group)

        # Export buttons
        btn_layout = QHBoxLayout()
        self.btn_export = QPushButton("🎬 Export Current Puzzle"); self.btn_export.clicked.connect(self._on_export)
        self.btn_export_batch = QPushButton("📦 Batch Export All"); self.btn_export_batch.clicked.connect(self._on_batch_export)
        self.btn_cancel_export = QPushButton("✖ Cancel"); self.btn_cancel_export.clicked.connect(self._on_cancel_export); self.btn_cancel_export.setEnabled(False)
        btn_layout.addWidget(self.btn_export); btn_layout.addWidget(self.btn_export_batch); btn_layout.addWidget(self.btn_cancel_export)
        layout.addLayout(btn_layout)

        self.progress_bar = QProgressBar(); self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        layout.addStretch()
        self.tabs.addTab(scroll, "🎬 Export")

    # ── Settings Tab ────────────────────────────────────────────────────

    def _build_settings_tab(self):
        tab = QWidget()
        layout = QFormLayout(tab)
        self.combo_theme = QComboBox(); self.combo_theme.addItems(THEMES.keys()); self.combo_theme.setCurrentText("Classic")
        self.combo_theme.currentTextChanged.connect(self._on_theme_changed)
        layout.addRow("Board theme:", self.combo_theme)
        self.chk_sound = QCheckBox(); self.chk_sound.setChecked(True); self.chk_sound.toggled.connect(self._on_sound_toggled)
        layout.addRow("Sound enabled:", self.chk_sound)
        self.slider_volume = QSlider(Qt.Horizontal); self.slider_volume.setRange(0, 100); self.slider_volume.setValue(70)
        self.slider_volume.valueChanged.connect(self._on_volume_changed)
        layout.addRow("Volume:", self.slider_volume)
        self.slider_anim_speed = QSlider(Qt.Horizontal); self.slider_anim_speed.setRange(0, 500); self.slider_anim_speed.setValue(ANIM_SPEED_DEFAULT)
        self.slider_anim_speed.valueChanged.connect(self._on_anim_speed_changed)
        layout.addRow("Animation speed (ms):", self.slider_anim_speed)
        self.lbl_anim_speed = QLabel(f"{ANIM_SPEED_DEFAULT} ms"); layout.addRow("", self.lbl_anim_speed)
        ffmpeg_status = "✅ Available" if HAS_FFMPEG else "❌ Not found"
        layout.addRow("FFmpeg:", QLabel(ffmpeg_status))
        self.tabs.addTab(tab, "⚙ Settings")

    # ── Signal Connections ──────────────────────────────────────────────

    def _connect_signals(self):
        self.board_widget.move_made.connect(self._on_move_made)

    # ── Puzzle Loading ──────────────────────────────────────────────────

    def _on_load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Puzzle File", "",
            "Puzzle files (*.csv *.json *.parquet *.pgn *.tsv);;All files (*)")
        if not path: return
        try:
            puzzles = self.puzzle_loader.load_file(path)
            self.puzzles = puzzles
            self.puzzle_list.clear()
            for p in puzzles:
                item = QListWidgetItem(p['name'][:80])
                item.setData(Qt.UserRole, p)
                self.puzzle_list.addItem(item)
            self.puzzle_count_label.setText(f"{len(puzzles)} puzzles")
            if puzzles: self.puzzle_list.setCurrentRow(0)
            self.statusBar().showMessage(f"Loaded {len(puzzles)} puzzles from {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))

    def _on_puzzle_selected(self, row):
        if row < 0 or row >= len(self.puzzles): return
        self.current_puzzle_idx = row
        self.current_puzzle = self.puzzles[row]
        self._start_puzzle()

    def _start_puzzle(self):
        p = self.current_puzzle
        if not p: return
        fen = p.get('fen', '')
        if fen: self.engine.load_fen(fen)
        else: self.engine.reset()
        self.puzzle_move_idx = 0
        self.puzzle_mode = True
        self.auto_play_timer.stop()
        self.puzzle_name_label.setText(p.get('name', '—'))
        self.puzzle_diff_label.setText(f"{p.get('difficulty', 0):.2f}")
        self.puzzle_desc_label.setText(p.get('desc', '—'))
        self.puzzle_status_label.setText("Your turn" if p.get('moves') else "")
        self.history_text.clear()
        self.fen_label.setText(f"FEN: {self.engine.board.fen()}")
        self.board_widget.selected = None; self.board_widget.legal_targets = []; self.board_widget.update()

    # ── Navigation ──────────────────────────────────────────────────────

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
            next_uci = moves[self.puzzle_move_idx]
            info = self.engine.make_move_uci(next_uci)
            if info:
                self.puzzle_move_idx += 1
                self.history_text.append(f"{'White' if self.engine.board.turn == chess.BLACK else 'Black'}: {info['notation']} (Hint)")
                self.fen_label.setText(f"FEN: {self.engine.board.fen()}")
                self.board_widget.update()
                if self.puzzle_move_idx < len(moves): self._schedule_auto_play()
                else: self.puzzle_mode = False; self.puzzle_status_label.setText("Puzzle complete!")

    # ── Move Handling ───────────────────────────────────────────────────

    def _on_move_made(self, notation):
        if not notation: return
        turn_str = 'White' if self.engine.board.turn == chess.BLACK else 'Black'
        self.history_text.append(f"{turn_str}: {notation}")
        self.fen_label.setText(f"FEN: {self.engine.board.fen()}")
        if self.puzzle_mode and self.current_puzzle:
            moves = self.current_puzzle.get('moves', [])
            if self.puzzle_move_idx < len(moves): self._schedule_auto_play()
            else: self.puzzle_mode = False; self.puzzle_status_label.setText("Puzzle complete!")
        if self.engine.game_over: self.puzzle_mode = False; self.puzzle_status_label.setText(f"Game Over: {self.engine.result}")

    def _schedule_auto_play(self):
        if not self.current_puzzle: return
        moves = self.current_puzzle.get('moves', [])
        if self.puzzle_move_idx < len(moves): self.auto_play_timer.start(600)

    def _auto_play_response(self):
        if not self.current_puzzle or not self.puzzle_mode: return
        moves = self.current_puzzle.get('moves', [])
        if self.puzzle_move_idx >= len(moves): return
        next_uci = moves[self.puzzle_move_idx]
        info = self.engine.make_move_uci(next_uci)
        if info:
            self.puzzle_move_idx += 1
            turn_str = 'White' if self.engine.board.turn == chess.BLACK else 'Black'
            self.history_text.append(f"{turn_str}: {info['notation']}")
            self.fen_label.setText(f"FEN: {self.engine.board.fen()}")
            if self.engine.game_over: self.puzzle_mode = False; self.puzzle_status_label.setText(f"Game Over: {self.engine.result}")
            elif self.puzzle_move_idx >= len(moves): self.puzzle_mode = False; self.puzzle_status_label.setText("Puzzle complete!")
            self.board_widget.update()
        else: log(f"Failed to auto-play response: {next_uci}", "PUZZLE")

    # ── Settings Handlers ───────────────────────────────────────────────

    def _on_theme_changed(self, name):
        if name in THEMES: self.board_widget.current_theme = THEMES[name]; self.export_config.theme_name = name; self.board_widget.update()
    def _on_sound_toggled(self, checked): self.sound_mgr.set_enabled(checked)
    def _on_volume_changed(self, val): self.sound_mgr.set_volume(val / 100.0)
    def _on_anim_speed_changed(self, val): self.board_widget.anim_speed = val; self.lbl_anim_speed.setText(f"{val} ms")

    # ── Export Handlers ─────────────────────────────────────────────────

    def _on_preset_changed(self, name):
        self.export_config.apply_preset(name)
        self.spin_width.setValue(self.export_config.target_width); self.spin_height.setValue(self.export_config.target_height)
        self.spin_fps.setValue(self.export_config.fps)

    def _on_browse_audio(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Audio File", "", "Audio (*.mp3 *.wav *.aac *.ogg *.flac);;All files (*)")
        if path: self.edit_audio_path.setText(path)

    def _sync_export_config(self):
        cfg = self.export_config
        cfg.target_width = self.spin_width.value(); cfg.target_height = self.spin_height.value(); cfg.fps = self.spin_fps.value()
        cfg.title_enabled = self.chk_title.isChecked(); cfg.title_text = self.edit_title.text(); cfg.title_duration = self.spin_title_dur.value()
        cfg.end_enabled = self.chk_end.isChecked(); cfg.end_text = self.edit_end.text(); cfg.end_duration = self.spin_end_dur.value()
        cfg.move_anim_duration = self.spin_anim_dur.value() / 10.0; cfg.pause_after_move = self.spin_pause.value() / 10.0
        cfg.ffmpeg_crf = self.spin_crf.value(); cfg.ffmpeg_preset = self.combo_preset_ff.currentText()
        cfg.export_gif = self.chk_gif.isChecked(); cfg.gif_fps = self.spin_gif_fps.value(); cfg.audio_path = self.edit_audio_path.text().strip()
        cfg.gpu_post_process = self.chk_postproc.isChecked(); cfg.gpu_vignette = self.slider_vignette.value() / 100.0
        cfg.gpu_contrast = self.slider_contrast.value() / 100.0; cfg.gpu_saturation = self.slider_saturation.value() / 100.0
        cfg.theme_name = self.combo_theme.currentText()

    def _create_exporter(self):
        self._sync_export_config()
        self.exporter = FFmpegVideoExporter(self.export_config)
        self.exporter.progress.connect(self._on_export_progress)
        self.exporter.finished.connect(self._on_export_finished)
        self.exporter.error.connect(self._on_export_error)
        self.exporter.log_msg.connect(lambda m: self.statusBar().showMessage(m))

    def _on_export(self):
        if not self.current_puzzle: QMessageBox.warning(self, "Export", "No puzzle selected."); return
        if not HAS_FFMPEG: QMessageBox.critical(self, "Export Error", "FFmpeg not found!\nInstall ffmpeg and add it to your system PATH."); return
        ext = '.gif' if self.export_config.export_gif else '.mp4'
        default_name = sanitize_filename(self.current_puzzle.get('name', 'puzzle')) + ext
        path, _ = QFileDialog.getSaveFileName(self, "Export Video", default_name, f"Video (*{ext});;All files (*)")
        if not path: return
        self._create_exporter()
        self.progress_bar.setVisible(True); self.progress_bar.setValue(0)
        self.btn_export.setEnabled(False); self.btn_export_batch.setEnabled(False); self.btn_cancel_export.setEnabled(True)
        self.exporter.export_puzzle_threaded(self.current_puzzle, path)

    def _on_batch_export(self):
        if not self.puzzles: QMessageBox.warning(self, "Export", "No puzzles loaded."); return
        if not HAS_FFMPEG: QMessageBox.critical(self, "Export Error", "FFmpeg not found!\nInstall ffmpeg and add it to your system PATH."); return
        output_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if not output_dir: return
        self._create_exporter()
        self.progress_bar.setVisible(True); self.progress_bar.setValue(0)
        self.btn_export.setEnabled(False); self.btn_export_batch.setEnabled(False); self.btn_cancel_export.setEnabled(True)
        t = threading.Thread(target=self.exporter.export_batch, args=(self.puzzles, output_dir), daemon=True); t.start()

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

    # ── Theme & Cleanup ─────────────────────────────────────────────────

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow { background: #2b2b2b; }
            QWidget { color: #e0e0e0; font-size: 13px; }
            QTabWidget::pane { border: 1px solid #555; background: #2b2b2b; }
            QTabBar::tab { background: #3c3c3c; padding: 6px 12px; border: 1px solid #555; }
            QTabBar::tab:selected { background: #4a4a4a; border-bottom: 2px solid #88c0d0; }
            QGroupBox { border: 1px solid #555; border-radius: 4px; margin-top: 8px; padding-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QPushButton { background: #3c3c3c; border: 1px solid #666; border-radius: 4px; padding: 5px 12px; }
            QPushButton:hover { background: #4a4a4a; }
            QPushButton:pressed { background: #555; }
            QPushButton:disabled { background: #2a2a2a; color: #666; }
            QComboBox, QSpinBox, QLineEdit { background: #3c3c3c; border: 1px solid #666; border-radius: 3px; padding: 3px; }
            QListWidget { background: #1e1e1e; border: 1px solid #555; }
            QListWidget::item:selected { background: #4a6984; }
            QTextEdit { background: #1e1e1e; border: 1px solid #555; }
            QProgressBar { border: 1px solid #555; border-radius: 3px; text-align: center; background: #1e1e1e; }
            QProgressBar::chunk { background: #88c0d0; }
            QSlider::groove:horizontal { background: #3c3c3c; height: 6px; border-radius: 3px; }
            QSlider::handle:horizontal { background: #88c0d0; width: 14px; margin: -4px 0; border-radius: 7px; }
            QCheckBox::indicator { width: 14px; height: 14px; }
        """)

    def closeEvent(self, event):
        self.auto_play_timer.stop()
        if self.exporter: self.exporter.cancel()
        self.sound_mgr.cleanup()
        event.accept()