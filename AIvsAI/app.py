# app.py
"""
Main application — minimalist settings, move-quality integration,
Lichess-style layout with player bars.
Updated export tab with animation, title/result screen controls.
Dynamic depth ranges and tooltips for each AI engine.
Minimal color theme for settings.
Dramatic, rare quality badges.
"""

import sys
import os
import logging

import chess
import chess.pgn

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
    QGroupBox, QComboBox, QFormLayout, QTabWidget,
    QFileDialog, QSlider, QCheckBox, QFrame,
    QLineEdit, QScrollArea, QSizePolicy, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QPalette, QColor

from constants import (
    AI_MAP, AI_SHORT_NAMES, RESOLUTION_LIST, RESOLUTION_SIZES, THEMES,
    SOUND_THEME_LIST, GAME_NORMAL, GAME_CHECKMATE, GAME_STALEMATE,
    GAME_DRAW, GAME_INSUFFICIENT, SND_GAME_START, DEFAULT_OUTPUT_DIR,
    find_stockfish, MQ_GOOD, MQ_BEST, MQ_GREAT, MQ_MISTAKE,
    MQ_INACCURACY, MQ_BOOK, MQ_BRILLIANT, MQ_BLUNDER,
    MQ_SYMBOLS, MQ_LABELS, MQ_COLORS,
    MQ_ICONS, MQ_SHOW_BADGE, MQ_SHOW_MOVES_BADGE,
    DEFAULT_VIDEO_FPS, DEFAULT_MOVE_DURATION,
    DEFAULT_ANIM_DURATION, DEFAULT_TITLE_DURATION,
    DEFAULT_RESULT_DURATION,
)
from board_renderer import BoardRenderer
from video_renderer import VideoRenderer
from widgets import BoardPreviewWidget, MoveListWidget, EvalBarWidget
from move_analyzer import MoveAnalyzer
from sound_engine import SoundEngine
from workers import GameWorker, ExportWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AIvsAI2MP4")


# ════════════════════════════════════════════════════════════════════
#  Minimal Color Theme — Settings
# ════════════════════════════════════════════════════════════════════
_SETTINGS_GROUP_SS = """
QGroupBox {
    font-weight: 600; font-size: 10px; color: #58586a;
    border: none; border-left: 2px solid #2a2a30;
    border-radius: 0; margin-top: 14px;
    padding: 16px 12px 8px 14px; background-color: transparent;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 14px; padding: 0 8px;
    color: #58586a; font-size: 9px; text-transform: uppercase;
    letter-spacing: 1.5px;
}
"""

_SETTINGS_CONTROL_SS = """
QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {
    background-color: #1c1c20; border: none;
    border-radius: 4px;
    padding: 7px 8px; color: #c8c8d0; min-height: 24px;
    font-size: 12px;
}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus {
    background-color: #202026;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #1c1c20; border: 1px solid #2a2a30;
    border-radius: 4px; color: #c8c8d0;
    selection-background-color: #5b8fd4; selection-color: #fff;
    outline: none;
}
QCheckBox { color: #888898; spacing: 8px; font-size: 11px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: none; background-color: #1c1c20;
}
QCheckBox::indicator:hover { background-color: #242428; }
QCheckBox::indicator:checked { background-color: #5b8fd4; }
QCheckBox::indicator:checked:hover { background-color: #6fa0e4; }
QSlider::groove:horizontal {
    height: 3px; background: #2a2a30; border-radius: 1.5px;
}
QSlider::sub-page:horizontal {
    background: #5b8fd4; border-radius: 1.5px;
}
QSlider::handle:horizontal {
    background: #5b8fd4; width: 12px; height: 12px;
    margin: -5px 0; border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: #6fa0e4; }
QLabel { color: #888898; font-size: 11px; }
QPushButton {
    background: transparent; color: #888898; border: none;
    padding: 4px 2px; font-size: 11px;
}
QPushButton:hover { color: #c8c8d0; }
QToolTip {
    background-color: #1c1c20; color: #c8c8d0; border: none;
    padding: 8px 10px; font-size: 11px; border-radius: 6px;
}
QScrollBar:vertical {
    background: transparent; width: 6px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #3a3a44; border-radius: 3px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #4a4a54; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
"""

_BTN_CONTROL_SS = """
QPushButton {
    background-color: #1c1c20; color: #c8c8d0;
    border: none; border-radius: 4px;
    padding: 8px 14px; font-size: 12px; font-weight: 600;
}
QPushButton:hover { background-color: #303036; }
QPushButton:pressed { background-color: #18181c; }
QPushButton:disabled { color: #3a3a44; background-color: #1a1a1e; }
"""

_BTN_BROWSE_SS = """
QPushButton {
    background: transparent; color: #888898;
    border: 1px solid #2a2a30; border-radius: 4px;
    padding: 5px 10px; font-size: 10px;
}
QPushButton:hover {
    color: #c8c8d0; border-color: #3a3a44; background-color: #1c1c20;
}
"""

_BTN_EXPORT_SS = """
QPushButton {
    background: #5b8fd4; color: #fff; border: none;
    border-radius: 6px; font-size: 13px; font-weight: bold;
    padding: 10px 20px;
}
QPushButton:hover { background: #6fa0e4; }
QPushButton:pressed { background: #4a7cc4; }
QPushButton:disabled { background: #2a2a30; color: #4a4a54; }
"""

_LABEL_VALUE_SS = "color:#5b8fd4; font-weight:600; font-size:11px;"


# ════════════════════════════════════════════════════════════════════
#  Main Window
# ════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI vs AI → MP4  ·  Chess Battle")
        self.resize(1200, 800)

        self._game_thread = None
        self._game_worker = None
        self._export_thread = None
        self._export_worker = None

        self._board = chess.Board()
        self._move_list: list[str] = []
        self._move_qualities: list[str] = []
        self._eval_cp = 0.0
        self._game_state = GAME_NORMAL
        self._game_result = ""
        self._game_detail = ""

        self._analyzer = MoveAnalyzer()
        self.sound_engine = SoundEngine(self)
        self._stockfish_path = find_stockfish()

        logger.info("Stockfish path: %s", self._stockfish_path or "NOT FOUND")

        self._init_ui()
        self._apply_tab_style()
        self._reset_game()

        logger.info("Application initialized")

    # ── Player names & info ───────────────────────────────────
    def _get_player_names(self):
        wt = AI_SHORT_NAMES.get(self.white_ai_combo.currentData(), "AI")
        bt = AI_SHORT_NAMES.get(self.black_ai_combo.currentData(), "AI")
        wc = self.white_name_edit.text().strip() if hasattr(self, 'white_name_edit') else ""
        bc = self.black_name_edit.text().strip() if hasattr(self, 'black_name_edit') else ""
        wn = f"{wc} ({wt})" if wc else f"White ({wt})"
        bn = f"{bc} ({bt})" if bc else f"Black ({bt})"
        return wn, bn

    def _get_player_info(self):
        wt = AI_SHORT_NAMES.get(self.white_ai_combo.currentData(), "AI")
        wd = self.white_depth_spin.value() if hasattr(self, 'white_depth_spin') else 1
        bt = AI_SHORT_NAMES.get(self.black_ai_combo.currentData(), "AI")
        bd = self.black_depth_spin.value() if hasattr(self, 'black_depth_spin') else 1
        return f"{wt} (Depth {wd})", f"{bt} (Depth {bd})"

    def _update_player_labels(self):
        wn, bn = self._get_player_names()
        self.black_info_label.setText(f"♚ {bn}")
        self.white_info_label.setText(f"♔ {wn}")

    # ── Dynamic Depth / Tooltip Logic ─────────────────────────
    def _on_engine_changed(self, combo, spin):
        engine_type = combo.currentData()

        if engine_type == 0:  # Minimax
            spin.setRange(1, 8)
            spin.setValue(min(max(spin.value(), 1), 8))
            if spin.value() < 3:
                spin.setValue(4)
            spin.setToolTip(
                "Minimax Search Depth (half-moves ahead)\n\n"
                "• 1-3: Fast, beginner play\n"
                "• 4-5: Intermediate, slower\n"
                "• 6-8: Strong, VERY slow (Python limits)"
            )
        elif engine_type == 1:  # MCTS
            spin.setRange(1, 50)
            spin.setValue(min(max(spin.value(), 1), 50))
            if spin.value() < 5:
                spin.setValue(15)
            spin.setToolTip(
                "MCTS Simulations (value × 100)\n\n"
                "• 5-10: Fast, weak play (500-1000 sims)\n"
                "• 15-25: Moderate strength\n"
                "• 30+: Stronger, linear slowdown"
            )
        elif engine_type == 2:  # Stockfish
            spin.setRange(1, 30)
            spin.setValue(min(max(spin.value(), 1), 30))
            if spin.value() < 5:
                spin.setValue(18)
            spin.setToolTip(
                "Stockfish Search Depth (plies)\n\n"
                "• 1-8: Fast, beginner play\n"
                "• 10-15: Advanced play\n"
                "• 18+: Master level, very fast (C++ engine)"
            )

        self._update_player_labels()

    # ── UI ────────────────────────────────────────────────────
    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # Left: player bars + board + eval bar
        left_outer = QVBoxLayout()
        left_outer.setSpacing(4)

        self.black_info_label = QLabel("♚ Black")
        self.black_info_label.setStyleSheet(
            "font-size:12px; font-weight:600; color:#888898; padding:2px 4px;"
        )
        left_outer.addWidget(self.black_info_label)

        left_layout = QHBoxLayout()
        left_layout.setSpacing(6)
        self.eval_bar = EvalBarWidget()
        self.board_widget = BoardPreviewWidget()
        left_layout.addWidget(self.eval_bar)
        left_layout.addWidget(self.board_widget, 1)
        left_outer.addLayout(left_layout)

        self.white_info_label = QLabel("♔ White")
        self.white_info_label.setStyleSheet(
            "font-size:12px; font-weight:600; color:#888898; padding:2px 4px;"
        )
        left_outer.addWidget(self.white_info_label)

        main_layout.addLayout(left_outer, 5)

        # Right: move list + tabs
        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)

        self.move_list_widget = MoveListWidget()
        right_layout.addWidget(self.move_list_widget, 1)

        # Tabs
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)

        # ──────── Tab 1: Game ─────────────────────────────────
        game_tab = QWidget()
        game_tab.setStyleSheet(_SETTINGS_CONTROL_SS)
        gl = QVBoxLayout(game_tab)
        gl.setContentsMargins(16, 20, 16, 16)
        gl.setSpacing(14)

        # White
        wg = QGroupBox("WHITE")
        wg.setStyleSheet(_SETTINGS_GROUP_SS)
        wf = QFormLayout(wg)
        wf.setContentsMargins(14, 16, 14, 8)
        wf.setSpacing(8)
        self.white_ai_combo = QComboBox()
        self.white_depth_spin = QSpinBox()
        for k, v in AI_MAP.items():
            self.white_ai_combo.addItem(v, k)
        wf.addRow("Engine", self.white_ai_combo)
        wf.addRow("Depth", self.white_depth_spin)
        gl.addWidget(wg)

        # Black
        bg = QGroupBox("BLACK")
        bg.setStyleSheet(_SETTINGS_GROUP_SS)
        bf = QFormLayout(bg)
        bf.setContentsMargins(14, 16, 14, 8)
        bf.setSpacing(8)
        self.black_ai_combo = QComboBox()
        self.black_depth_spin = QSpinBox()
        for k, v in AI_MAP.items():
            self.black_ai_combo.addItem(v, k)
        self.black_ai_combo.setCurrentIndex(1)
        bf.addRow("Engine", self.black_ai_combo)
        bf.addRow("Depth", self.black_depth_spin)
        gl.addWidget(bg)

        # FIX: Use lambda default args to avoid late-binding closures
        self.white_ai_combo.currentIndexChanged.connect(
            lambda _idx, c=self.white_ai_combo, s=self.white_depth_spin:
                self._on_engine_changed(c, s)
        )
        self.black_ai_combo.currentIndexChanged.connect(
            lambda _idx, c=self.black_ai_combo, s=self.black_depth_spin:
                self._on_engine_changed(c, s)
        )
        self.white_depth_spin.valueChanged.connect(self._update_player_labels)
        self.black_depth_spin.valueChanged.connect(self._update_player_labels)

        # Controls
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        self.start_btn = QPushButton("▶  Start")
        self.stop_btn = QPushButton("■  Stop")
        self.reset_btn = QPushButton("↺  Reset")
        self.stop_btn.setEnabled(False)
        for b in (self.start_btn, self.stop_btn, self.reset_btn):
            b.setMinimumHeight(34)
            b.setStyleSheet(_BTN_CONTROL_SS)
        self.start_btn.clicked.connect(self._start_game)
        self.stop_btn.clicked.connect(self._stop_game)
        self.reset_btn.clicked.connect(self._reset_game)
        btn_layout.addWidget(self.start_btn, 1)
        btn_layout.addWidget(self.stop_btn, 1)
        btn_layout.addWidget(self.reset_btn, 1)
        gl.addLayout(btn_layout)

        # Last-move quality indicator
        self.quality_label = QLabel("")
        self.quality_label.setAlignment(Qt.AlignCenter)
        self.quality_label.setStyleSheet(
            "font-size:13px; font-weight:bold; padding:4px;"
        )
        gl.addWidget(self.quality_label)

        gl.addStretch()
        self.tab_widget.addTab(game_tab, "♟  Game")

        # ──────── Tab 2: Settings (minimalist) ────────────────
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.NoFrame)
        settings_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
        )

        sc = QWidget()
        sc.setStyleSheet(_SETTINGS_CONTROL_SS)
        sl = QVBoxLayout(sc)
        sl.setContentsMargins(6, 14, 6, 14)
        sl.setSpacing(16)

        # Appearance
        ag = QGroupBox("APPEARANCE")
        ag.setStyleSheet(_SETTINGS_GROUP_SS)
        af = QFormLayout(ag)
        af.setContentsMargins(14, 16, 14, 8)
        af.setSpacing(8)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES.keys())
        self.theme_combo.currentTextChanged.connect(self._change_theme)
        af.addRow("Theme", self.theme_combo)
        self.flip_check = QCheckBox("Flip board")
        self.flip_check.toggled.connect(self.board_widget.set_flipped)
        af.addRow("", self.flip_check)
        self.show_coords_check = QCheckBox("Coordinates")
        self.show_coords_check.setChecked(True)
        self.show_coords_check.toggled.connect(self.board_widget.set_show_coords)
        af.addRow("", self.show_coords_check)
        self.anim_speed_slider = QSlider(Qt.Horizontal)
        self.anim_speed_slider.setRange(50, 800)
        self.anim_speed_slider.setValue(300)
        self.anim_speed_lbl = QLabel("300 ms")
        self.anim_speed_lbl.setFixedWidth(48)
        self.anim_speed_lbl.setStyleSheet(_LABEL_VALUE_SS)
        self.anim_speed_slider.valueChanged.connect(self._on_anim_speed)
        ar = QHBoxLayout()
        ar.addWidget(self.anim_speed_slider, 1)
        ar.addWidget(self.anim_speed_lbl)
        af.addRow("Anim", ar)
        sl.addWidget(ag)

        # Sound
        sg = QGroupBox("SOUND")
        sg.setStyleSheet(_SETTINGS_GROUP_SS)
        sf = QFormLayout(sg)
        sf.setContentsMargins(14, 16, 14, 8)
        sf.setSpacing(8)
        self.sound_theme_combo = QComboBox()
        if self.sound_engine.enabled:
            self.sound_theme_combo.addItems(self.sound_engine.available_themes)
            self.sound_theme_combo.currentTextChanged.connect(self.sound_engine.set_theme)
        else:
            self.sound_theme_combo.setEnabled(False)
        sf.addRow("Theme", self.sound_theme_combo)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.vol_lbl = QLabel("70%")
        self.vol_lbl.setFixedWidth(32)
        self.vol_lbl.setStyleSheet(_LABEL_VALUE_SS)
        self.volume_slider.valueChanged.connect(self._on_volume)
        vr = QHBoxLayout()
        vr.addWidget(self.volume_slider, 1)
        vr.addWidget(self.vol_lbl)
        sf.addRow("Vol", vr)
        self.mute_check = QCheckBox("Mute")
        self.mute_check.toggled.connect(self.sound_engine.set_muted)
        sf.addRow("", self.mute_check)
        sl.addWidget(sg)

        # Game
        gg = QGroupBox("GAME")
        gg.setStyleSheet(_SETTINGS_GROUP_SS)
        gf = QFormLayout(gg)
        gf.setContentsMargins(14, 16, 14, 8)
        gf.setSpacing(8)
        self.move_delay_spin = QSpinBox()
        self.move_delay_spin.setRange(0, 5000)
        self.move_delay_spin.setValue(100)
        self.move_delay_spin.setSuffix(" ms")
        self.move_delay_spin.setToolTip(
            "Delay between moves during live play\n"
            "(does not affect video export)"
        )
        gf.addRow("Delay", self.move_delay_spin)
        sl.addWidget(gg)

        # Names
        ng = QGroupBox("NAMES")
        ng.setStyleSheet(_SETTINGS_GROUP_SS)
        nf = QFormLayout(ng)
        nf.setContentsMargins(14, 16, 14, 8)
        nf.setSpacing(8)
        self.white_name_edit = QLineEdit()
        self.white_name_edit.setPlaceholderText("White player")
        self.white_name_edit.textChanged.connect(self._update_player_labels)
        nf.addRow("♔", self.white_name_edit)
        self.black_name_edit = QLineEdit()
        self.black_name_edit.setPlaceholderText("Black player")
        self.black_name_edit.textChanged.connect(self._update_player_labels)
        nf.addRow("♚", self.black_name_edit)
        sl.addWidget(ng)

        # Stockfish
        sfg = QGroupBox("STOCKFISH")
        sfg.setStyleSheet(_SETTINGS_GROUP_SS)
        sff = QFormLayout(sfg)
        sff.setContentsMargins(14, 16, 14, 8)
        sff.setSpacing(8)
        self.sf_path_label = QLabel(self._stockfish_path or "Not found")
        self.sf_path_label.setWordWrap(True)
        self.sf_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sf_path_label.setStyleSheet(
            f"color:{'#5eb85e' if self._stockfish_path else '#d04848'};"
            "font-size:11px;"
        )
        sff.addRow("Path", self.sf_path_label)
        self.sf_browse_btn = QPushButton("Browse…")
        self.sf_browse_btn.setFixedWidth(70)
        self.sf_browse_btn.setStyleSheet(_BTN_BROWSE_SS)
        self.sf_browse_btn.clicked.connect(self._browse_stockfish)
        sff.addRow("", self.sf_browse_btn)
        sl.addWidget(sfg)

        # Output
        og = QGroupBox("OUTPUT")
        og.setStyleSheet(_SETTINGS_GROUP_SS)
        of = QFormLayout(og)
        of.setContentsMargins(14, 16, 14, 8)
        of.setSpacing(8)
        self.output_folder_edit = QLineEdit(DEFAULT_OUTPUT_DIR)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_folder_edit, 1)
        self.output_browse_btn = QPushButton("Browse…")
        self.output_browse_btn.setFixedWidth(70)
        self.output_browse_btn.setStyleSheet(_BTN_BROWSE_SS)
        self.output_browse_btn.clicked.connect(self._browse_output_folder)
        out_row.addWidget(self.output_browse_btn)
        of.addRow("Folder", out_row)
        sl.addWidget(og)

        sl.addStretch()
        settings_scroll.setWidget(sc)
        self.tab_widget.addTab(settings_scroll, "⚙  Settings")

        # ──────── Tab 3: Export ───────────────────────────────
        export_scroll = QScrollArea()
        export_scroll.setWidgetResizable(True)
        export_scroll.setFrameShape(QFrame.NoFrame)
        export_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
        )

        export_tab = QWidget()
        export_tab.setStyleSheet(_SETTINGS_CONTROL_SS)
        el = QVBoxLayout(export_tab)
        el.setContentsMargins(16, 20, 16, 16)
        el.setSpacing(14)

        # Video settings
        eg = QGroupBox("VIDEO")
        eg.setStyleSheet(_SETTINGS_GROUP_SS)
        ef = QFormLayout(eg)
        ef.setContentsMargins(14, 16, 14, 8)
        ef.setSpacing(8)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(RESOLUTION_LIST)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(DEFAULT_VIDEO_FPS)
        self.fps_spin.setSuffix(" fps")
        ef.addRow("Resolution", self.resolution_combo)
        ef.addRow("Frame rate", self.fps_spin)
        el.addWidget(eg)

        # Timing
        tg = QGroupBox("TIMING")
        tg.setStyleSheet(_SETTINGS_GROUP_SS)
        tf = QFormLayout(tg)
        tf.setContentsMargins(14, 16, 14, 8)
        tf.setSpacing(8)
        self.move_duration_spin = QDoubleSpinBox()
        self.move_duration_spin.setRange(0.5, 15.0)
        self.move_duration_spin.setValue(DEFAULT_MOVE_DURATION)
        self.move_duration_spin.setSuffix(" s")
        self.move_duration_spin.setSingleStep(0.5)
        self.move_duration_spin.setDecimals(1)
        tf.addRow("Per move", self.move_duration_spin)

        self.anim_duration_spin = QDoubleSpinBox()
        self.anim_duration_spin.setRange(0.1, 3.0)
        self.anim_duration_spin.setValue(DEFAULT_ANIM_DURATION)
        self.anim_duration_spin.setSuffix(" s")
        self.anim_duration_spin.setSingleStep(0.1)
        self.anim_duration_spin.setDecimals(1)
        tf.addRow("Animation", self.anim_duration_spin)

        self.title_duration_spin = QDoubleSpinBox()
        self.title_duration_spin.setRange(0.0, 10.0)
        self.title_duration_spin.setValue(DEFAULT_TITLE_DURATION)
        self.title_duration_spin.setSuffix(" s")
        self.title_duration_spin.setSingleStep(0.5)
        self.title_duration_spin.setDecimals(1)
        tf.addRow("Title card", self.title_duration_spin)

        self.result_duration_spin = QDoubleSpinBox()
        self.result_duration_spin.setRange(0.0, 15.0)
        self.result_duration_spin.setValue(DEFAULT_RESULT_DURATION)
        self.result_duration_spin.setSuffix(" s")
        self.result_duration_spin.setSingleStep(0.5)
        self.result_duration_spin.setDecimals(1)
        tf.addRow("Result card", self.result_duration_spin)
        el.addWidget(tg)

        # Features
        fg = QGroupBox("FEATURES")
        fg.setStyleSheet(_SETTINGS_GROUP_SS)
        ff = QFormLayout(fg)
        ff.setContentsMargins(14, 16, 14, 8)
        ff.setSpacing(8)
        self.show_title_check = QCheckBox("Title screen")
        self.show_title_check.setChecked(True)
        ff.addRow("", self.show_title_check)
        self.show_result_check = QCheckBox("Result screen")
        self.show_result_check.setChecked(True)
        ff.addRow("", self.show_result_check)
        el.addWidget(fg)

        # Estimated duration
        self.estimate_label = QLabel("")
        self.estimate_label.setStyleSheet(
            "color:#5b8fd4; font-size:11px; font-weight:600; padding:4px;"
        )
        self._update_export_estimate()
        self.move_duration_spin.valueChanged.connect(self._update_export_estimate)
        self.title_duration_spin.valueChanged.connect(self._update_export_estimate)
        self.result_duration_spin.valueChanged.connect(self._update_export_estimate)
        self.show_title_check.toggled.connect(self._update_export_estimate)
        self.show_result_check.toggled.connect(self._update_export_estimate)
        el.addWidget(self.estimate_label)

        # Export button
        self.export_btn = QPushButton("🎬  Export to MP4")
        self.export_btn.setMinimumHeight(42)
        self.export_btn.setStyleSheet(_BTN_EXPORT_SS)
        self.export_btn.clicked.connect(self._export_mp4)
        el.addWidget(self.export_btn)

        self.export_progress_label = QLabel("")
        self.export_progress_label.setAlignment(Qt.AlignCenter)
        self.export_progress_label.setStyleSheet(
            "color:#58586a; font-size:11px;"
        )
        el.addWidget(self.export_progress_label)

        el.addStretch()
        export_scroll.setWidget(export_tab)
        self.tab_widget.addTab(export_scroll, "🎬  Export")

        right_layout.addWidget(self.tab_widget)

        # Status
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#2a2a30;")
        right_layout.addWidget(sep)
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            "padding:4px 2px; color:#58586a; font-size:11px;"
        )
        right_layout.addWidget(self.status_label)

        main_layout.addLayout(right_layout, 2)

        # Initialize ranges/tooltips on startup
        self._on_engine_changed(self.white_ai_combo, self.white_depth_spin)
        self._on_engine_changed(self.black_ai_combo, self.black_depth_spin)

        self._update_player_labels()

    def _update_export_estimate(self):
        n = len(self._move_list)
        move_dur = self.move_duration_spin.value()
        title_dur = self.title_duration_spin.value() if self.show_title_check.isChecked() else 0
        result_dur = self.result_duration_spin.value() if self.show_result_check.isChecked() else 0
        total = title_dur + n * move_dur + result_dur
        mins = int(total // 60)
        secs = int(total % 60)
        self.estimate_label.setText(
            f"⏱  Estimated duration: {mins}:{secs:02d}  ({n} moves × {move_dur:.1f}s)"
        )

    def _apply_tab_style(self):
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none; border-radius: 8px;
                background-color: #262628;
            }
            QTabBar::tab {
                background: transparent; color: #58586a;
                border: none; border-bottom: 2px solid transparent;
                padding: 8px 18px; margin-right: 2px;
                font-size: 11px; font-weight: 600;
            }
            QTabBar::tab:selected {
                color: #c8c8d0; border-bottom-color: #5b8fd4;
            }
            QTabBar::tab:hover:!selected {
                color: #888898; border-bottom-color: #3a3a44;
            }
        """)

    # ── Settings callbacks ────────────────────────────────────
    def _on_volume(self, v):
        self.vol_lbl.setText(f"{v}%")
        self.sound_engine.set_volume(v / 100.0)

    def _on_anim_speed(self, v):
        self.anim_speed_lbl.setText(f"{v} ms")
        self.board_widget.set_anim_duration(v)

    def _browse_stockfish(self):
        filt = (
            "Executables (*.exe);;All Files (*)"
            if sys.platform == "win32" else "All Files (*)"
        )
        path, _ = QFileDialog.getOpenFileName(self, "Stockfish", "", filt)
        if path:
            self._stockfish_path = path
            self.sf_path_label.setText(path)
            self.sf_path_label.setStyleSheet(
                "color:#5eb85e; font-size:11px;"
            )

    def _browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Output Folder")
        if folder:
            self.output_folder_edit.setText(folder)

    # ── Game controls ─────────────────────────────────────────
    def _start_game(self):
        if self._game_thread and self._game_thread.isRunning():
            return

        # Validate Stockfish selection
        w_type = self.white_ai_combo.currentData()
        b_type = self.black_ai_combo.currentData()
        if (w_type == 2 or b_type == 2) and not self._stockfish_path:
            QMessageBox.warning(
                self, "Stockfish Not Found",
                "Stockfish is selected but the path is not configured.\n"
                "Please browse to the Stockfish executable in Settings."
            )
            return

        self._reset_game()
        self.status_label.setText("Game running…")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        wt = AI_SHORT_NAMES.get(self.white_ai_combo.currentData(), "AI")
        bt = AI_SHORT_NAMES.get(self.black_ai_combo.currentData(), "AI")
        wd = self.white_depth_spin.value()
        bd = self.black_depth_spin.value()
        logger.info("Starting game: White=%s (depth %d) vs Black=%s (depth %d)",
                     wt, wd, bt, bd)

        self._game_thread = QThread()
        self._game_worker = GameWorker(
            white_type=self.white_ai_combo.currentData(),
            white_depth=self.white_depth_spin.value(),
            black_type=self.black_ai_combo.currentData(),
            black_depth=self.black_depth_spin.value(),
            stockfish_path=self._stockfish_path,
            move_delay=self.move_delay_spin.value(),
        )
        self._game_worker.moveToThread(self._game_thread)
        self._game_thread.started.connect(self._game_worker.run)
        self._game_worker.move_made.connect(self._on_move_made)
        self._game_worker.game_over.connect(self._on_game_over)
        self._game_worker.error.connect(self._on_error)
        self._game_worker.finished.connect(self._on_game_finished)
        self._game_thread.start()

    def _stop_game(self):
        if self._game_worker:
            self._game_worker.stop()
        self.status_label.setText("Stopped.")

    def _reset_game(self):
        if self._game_worker:
            self._game_worker.stop()
            try:
                self._game_worker.move_made.disconnect(self._on_move_made)
                self._game_worker.game_over.disconnect(self._on_game_over)
                self._game_worker.error.disconnect(self._on_error)
                self._game_worker.finished.disconnect(self._on_game_finished)
            except RuntimeError:
                pass
        if self._game_thread and self._game_thread.isRunning():
            self._game_thread.quit()
            self._game_thread.wait(3000)
        self._game_thread = None
        self._game_worker = None

        self._board.reset()
        self._move_list.clear()
        self._move_qualities.clear()
        self._eval_cp = 0.0
        self._game_state = GAME_NORMAL
        self._game_result = ""
        self._game_detail = ""
        self._analyzer.reset()

        self.board_widget.set_board(self._board)
        self.board_widget.set_move_quality(MQ_GOOD)
        self.move_list_widget.clear()
        self.eval_bar.set_eval(0.0)
        self.eval_bar.reset_game_state()
        self.quality_label.setText("")
        self.quality_label.setStyleSheet("")
        self.status_label.setText("Ready")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._update_export_estimate()

    # ── Game callbacks ────────────────────────────────────────
    def _on_move_made(self, board, move, eval_cp, nodes, policy,
                      game_state, result, detail):
        self._board = board
        self._game_state = game_state
        self._game_result = result
        self._game_detail = detail

        prev_board = board.copy()
        prev_board.pop()
        is_white = (prev_board.turn == chess.WHITE)
        quality = self._analyzer.push(eval_cp, is_white, prev_board, move)
        self._move_qualities.append(quality)
        self._eval_cp = eval_cp

        san = prev_board.san(move)
        self._move_list.append(san)

        self.board_widget.animate_move(move)
        # FIX: Use a copied reference to avoid late-binding issues
        QTimer.singleShot(
            350,
            lambda b=self._board.copy(), m=move: self.board_widget.set_board(b, m),
        )
        self.board_widget.set_move_quality(quality)

        self.move_list_widget.add_move(san, quality)
        self.eval_bar.set_eval(eval_cp)

        if game_state != GAME_NORMAL:
            self.eval_bar.set_game_state(game_state, result, detail)

        self.sound_engine.play_move_sound(prev_board, move)

        # ── Dramatic quality label ────────────────────────────
        icon = MQ_ICONS.get(quality, "")
        lbl = MQ_LABELS.get(quality, "")
        color = MQ_COLORS.get(quality, QColor(150, 150, 150)).name()

        if quality in MQ_SHOW_BADGE:
            # Brilliant or Blunder — dramatic display
            quality_txt = f"{icon}  {lbl}" if icon else lbl
            self.quality_label.setText(f"  {quality_txt}  ")
            self.quality_label.setStyleSheet(
                f"font-size:15px; font-weight:bold; padding:6px 12px; "
                f"color:white; background-color:{color}; "
                f"border-radius:6px; border:2px solid rgba(255,255,255,60);"
            )
        elif quality == MQ_MISTAKE:
            quality_txt = f"{icon}  {lbl}" if icon else lbl
            self.quality_label.setText(f"  {quality_txt}  ")
            self.quality_label.setStyleSheet(
                f"font-size:13px; font-weight:bold; padding:4px 10px; "
                f"color:{color}; "
                f"background-color:rgba(230,140,30,30); "
                f"border-radius:4px; border:1px solid {color};"
            )
        elif quality == MQ_GREAT:
            quality_txt = f"{icon}  {lbl}" if icon else lbl
            self.quality_label.setText(f"  {quality_txt}  ")
            self.quality_label.setStyleSheet(
                f"font-size:13px; font-weight:bold; padding:4px 10px; "
                f"color:{color}; "
                f"background-color:rgba(50,170,80,25); "
                f"border-radius:4px; border:1px solid {color};"
            )
        else:
            # Good/Best/Inaccuracy/Book
            if quality == MQ_INACCURACY:
                quality_txt = f"{icon}  {lbl}" if icon else lbl
                self.quality_label.setText(quality_txt)
                self.quality_label.setStyleSheet(
                    f"font-size:11px; font-weight:600; padding:4px; "
                    f"color:{color};"
                )
            else:
                self.quality_label.setText("")
                self.quality_label.setStyleSheet("")

        # Status
        eval_str = (
            f"M{int(abs(eval_cp) - 10000)}" if abs(eval_cp) > 9000
            else f"{eval_cp / 100.0:+.2f}"
        )
        icon_str = f" {icon}" if icon else ""
        self.status_label.setText(
            f"Move {len(self._move_list)}: {san}{icon_str}  |  Eval: {eval_str}"
        )

        self._update_export_estimate()

    def _on_game_over(self, state, result, detail):
        self.status_label.setText(f"Game Over: {detail} ({result})")
        self.sound_engine.play_game_end(state)
        self._update_export_estimate()

    def _on_error(self, msg):
        logger.error("Error: %s", msg)
        self.status_label.setText(f"Error: {msg}")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _on_game_finished(self):
        if self._game_thread:
            self._game_thread.quit()
            self._game_thread.wait()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ── Theme ─────────────────────────────────────────────────
    def _change_theme(self, name):
        t = THEMES.get(name)
        if t:
            self.board_widget.set_theme(t)

    # ── Export ────────────────────────────────────────────────
    def _export_mp4(self):
        if not self._move_list:
            self.status_label.setText("No moves to export.")
            return

        output_dir = self.output_folder_edit.text().strip() or DEFAULT_OUTPUT_DIR
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            self.status_label.setText(f"Cannot create folder: {e}")
            return

        default_path = os.path.join(output_dir, "chess_game.mp4")
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Video", default_path, "MP4 (*.mp4);;All (*)"
        )
        if not save_path:
            return

        pgn = self._generate_pgn()
        wn, bn = self._get_player_names()
        wi, bi = self._get_player_info()

        res = self.resolution_combo.currentText()
        fps = self.fps_spin.value()
        logger.info("Exporting MP4: path=%s, resolution=%s, fps=%d, moves=%d",
                     save_path, res, fps, len(self._move_list))

        self._export_thread = QThread()
        self._export_worker = ExportWorker(
            pgn_text=pgn,
            save_path=save_path,
            resolution_key=res,
            fps=fps,
            board_theme=THEMES.get(self.theme_combo.currentText()),
            white_name=wn,
            black_name=bn,
            white_engine_info=wi,
            black_engine_info=bi,
            eval_history=self._analyzer.evals,
            move_qualities=self._move_qualities,
            move_duration=self.move_duration_spin.value(),
            anim_duration=self.anim_duration_spin.value(),
            title_duration=self.title_duration_spin.value(),
            result_duration=self.result_duration_spin.value(),
            show_title=self.show_title_check.isChecked(),
            show_result=self.show_result_check.isChecked(),
            sound_engine=self.sound_engine,
        )
        self._export_worker.moveToThread(self._export_thread)
        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.error.connect(self._on_error)

        self.export_btn.setEnabled(False)
        self.export_progress_label.setText("Preparing…")
        self._export_thread.start()

    def _on_export_progress(self, v):
        self.export_progress_label.setText(f"Rendering… {v}%")
        self.status_label.setText(f"Exporting… {v}%")

    def _on_export_finished(self, path):
        self.export_btn.setEnabled(True)
        self.export_progress_label.setText("")
        if self._export_thread:
            self._export_thread.quit()
            self._export_thread.wait()
        self._export_worker = None
        if path:
            self.status_label.setText(f"✓ Export complete: {path}")
            logger.info("Export complete: %s", path)
        else:
            self.status_label.setText("Export cancelled.")

    def _generate_pgn(self):
        wn, bn = self._get_player_names()
        game = chess.pgn.Game()
        game.headers["White"] = wn
        game.headers["Black"] = bn
        game.headers["Result"] = self._game_result or "*"
        node = game
        tb = chess.Board()
        for san in self._move_list:
            move = tb.parse_san(san)
            node = node.add_variation(move)
            tb.push(move)
        return str(game)


# ════════════════════════════════════════════════════════════════════
#  Entry Point
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)

    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(38, 38, 40))
    pal.setColor(QPalette.WindowText,      QColor(200, 200, 208))
    pal.setColor(QPalette.Base,            QColor(28, 28, 32))
    pal.setColor(QPalette.AlternateBase,   QColor(38, 38, 40))
    pal.setColor(QPalette.ToolTipBase,     QColor(28, 28, 32))
    pal.setColor(QPalette.ToolTipText,     QColor(200, 200, 208))
    pal.setColor(QPalette.Text,            QColor(200, 200, 208))
    pal.setColor(QPalette.Button,          QColor(38, 38, 40))
    pal.setColor(QPalette.ButtonText,      QColor(200, 200, 208))
    pal.setColor(QPalette.BrightText,      QColor(255, 55, 55))
    pal.setColor(QPalette.Link,            QColor(91, 143, 212))
    pal.setColor(QPalette.Highlight,       QColor(91, 143, 212))
    pal.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(pal)

    window = MainWindow()
    window.show()
    logger.info("Window shown — entering main event loop")
    sys.exit(app.exec())