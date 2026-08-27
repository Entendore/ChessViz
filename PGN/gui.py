import io
import glob
import os
import chess
import chess.pgn
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QTextEdit, QGroupBox, QCheckBox,
    QLineEdit, QComboBox, QFormLayout, QTabWidget, QProgressBar, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QDragEnterEvent, QDropEvent
from widgets import BoardPreviewWidget
from workers import StreamingExportWorker, BatchPGNExportWorker
from engine import _SyncUCI
from constants import THEMES, RESOLUTION_LIST, RESOLUTION_SIZES, find_stockfish, HAS_CV2, HAS_NUMBA, HAS_CUPY, DEFAULT_ANIM_DURATION, BoardTheme

PGN_STYLE = """
QMainWindow, QWidget { background-color: #1e1e22; color: #ddd; font-family: "Segoe UI", Arial, sans-serif; }
QGroupBox { border: 1px solid #3a3a40; border-radius: 6px; margin-top: 12px; padding-top: 16px; font-weight: bold; color: #ccc; font-size: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
QPushButton { background: #2a2a30; color: #ddd; border: 1px solid #3a3a40; border-radius: 5px; padding: 6px 14px; font-size: 12px; }
QPushButton:hover { background: #3a3a42; border-color: #555; }
QPushButton:pressed { background: #4a4a55; }
QPushButton:disabled { background: #222; color: #666; border-color: #333; }
QLineEdit, QTextEdit { background: #26262c; color: #ddd; border: 1px solid #3a3a40; border-radius: 4px; padding: 5px; selection-background-color: #4a6fa5; }
QLineEdit:focus, QTextEdit:focus { border-color: #5a8aba; }
QComboBox { background: #2a2a30; color: #ddd; border: 1px solid #3a3a40; border-radius: 4px; padding: 5px 8px; }
QComboBox:hover { border-color: #555; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: #2a2a30; color: #ddd; selection-background-color: #4a6fa5; border: 1px solid #3a3a40; }
QSpinBox, QDoubleSpinBox { background: #26262c; color: #ddd; border: 1px solid #3a3a40; border-radius: 4px; padding: 4px; }
QTabWidget::pane { border: 1px solid #3a3a40; border-radius: 4px; top: -1px; }
QTabBar::tab { background: #2a2a30; color: #aaa; padding: 8px 18px; border: 1px solid #3a3a40; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; font-size: 12px; }
QTabBar::tab:selected { background: #1e1e22; color: #fff; border-bottom: 2px solid #4a8aba; }
QTabBar::tab:hover:!selected { background: #333340; }
QLabel { color: #ccc; font-size: 12px; }
QCheckBox { color: #ccc; spacing: 6px; font-size: 12px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; border: 1px solid #555; background: #26262c; }
QCheckBox::indicator:checked { background: #4a8aba; border-color: #5a9aca; }
QProgressBar { border: 1px solid #3a3a40; border-radius: 4px; background: #1e1e22; text-align: center; color: #ddd; font-size: 11px; min-height: 22px; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2a6a8a, stop:1 #3a9aba); border-radius: 3px; }
QTableWidget { background-color: #1e1e22; color: #ddd; border: none; gridline-color: #2a2a30; font-size: 12px; }
QTableWidget::item { padding: 4px; border-bottom: 1px solid #2a2a30; }
QTableWidget::item:selected { background-color: #4a6fa5; color: white; }
QHeaderView::section { background-color: #2a2a30; color: #aaa; padding: 5px; border: 1px solid #3a3a40; font-weight: bold; font-size: 11px; }
"""

class PGNtoMP4Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("📄 PGN → MP4 Converter")
        self.setMinimumSize(1100, 700)
        self.resize(1300, 820)
        self.game, self.move_list, self.eval_cache = None, [], {}
        self.video_bg_color = QColor(30, 30, 32)
        self._worker, self._batch_worker = None, None
        self._current_move_idx, self._all_games = -1, []
        self._build_ui()
        self.setStyleSheet(PGN_STYLE)
        self.setAcceptDrops(True)
        
        QShortcut(QKeySequence(Qt.Key_Left), self, self._go_prev)
        QShortcut(QKeySequence(Qt.Key_Right), self, self._go_next)
        QShortcut(QKeySequence(Qt.Key_Home), self, self._go_first)
        QShortcut(QKeySequence(Qt.Key_End), self, self._go_last)
        
        sf = find_stockfish()
        if sf: self.engine_path_edit.setText(sf)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # ── Left Panel ─────────────────────────────────────────
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.board_preview = BoardPreviewWidget()
        left_layout.addWidget(self.board_preview, stretch=1)

        info_row = QHBoxLayout()
        self.game_info_lbl = QLabel("No game loaded")
        self.game_info_lbl.setStyleSheet("color:#999;font-size:12px;font-weight:bold;")
        info_row.addWidget(self.game_info_lbl)
        info_row.addStretch()
        self.opening_lbl = QLabel("")
        self.opening_lbl.setStyleSheet("color:#7aa;font-size:11px;")
        info_row.addWidget(self.opening_lbl)

        acc_status = []
        if HAS_NUMBA: acc_status.append("Numba✅")
        if HAS_CUPY: acc_status.append("CuPy✅")
        if not acc_status: acc_status.append("CPU Fallback")
        self.acc_lbl = QLabel(f"Accel: {' | '.join(acc_status)}")
        self.acc_lbl.setStyleSheet("color:#6a6;font-size:11px;")
        info_row.addWidget(self.acc_lbl)
        
        left_layout.addLayout(info_row)

        nav_row = QHBoxLayout()
        for text, fn in [("⏮", self._go_first), ("◀", self._go_prev), ("▶", self._go_next), ("⏭", self._go_last)]:
            btn = QPushButton(text)
            btn.setFixedSize(44, 34)
            btn.clicked.connect(fn)
            nav_row.addWidget(btn)
        self.move_pos_lbl = QLabel("0 / 0")
        self.move_pos_lbl.setStyleSheet("color:#9cf;font-size:11px;")
        self.move_pos_lbl.setAlignment(Qt.AlignCenter)
        nav_row.addWidget(self.move_pos_lbl)
        left_layout.addLayout(nav_row)

        self.move_table = QTableWidget()
        self.move_table.setColumnCount(3)
        self.move_table.setHorizontalHeaderLabels(["#", "White", "Black"])
        self.move_table.horizontalHeader().setStretchLastSection(True)
        for i, mode in enumerate([QHeaderView.ResizeToContents, QHeaderView.Stretch, QHeaderView.Stretch]):
            self.move_table.horizontalHeader().setSectionResizeMode(i, mode)
        self.move_table.verticalHeader().setVisible(False)
        self.move_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.move_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.move_table.setShowGrid(False)
        self.move_table.setMaximumHeight(180)
        self.move_table.currentCellChanged.connect(self._on_move_cell)
        left_layout.addWidget(self.move_table)

        main_layout.addLayout(left_layout, stretch=2)

        # ── Right Panel ────────────────────────────────────────
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        tabs = QTabWidget()

        # Tab 1: Input
        input_tab = QWidget()
        input_layout = QVBoxLayout(input_tab)

        file_grp = QGroupBox("PGN File")
        file_lay = QHBoxLayout(file_grp)
        self.pgn_path_edit = QLineEdit()
        self.pgn_path_edit.setPlaceholderText("Select a .pgn file…")
        file_lay.addWidget(self.pgn_path_edit, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._load_pgn_file)
        file_lay.addWidget(browse_btn)
        input_layout.addWidget(file_grp)

        paste_grp = QGroupBox("Or Paste PGN Text")
        paste_lay = QVBoxLayout(paste_grp)
        self.pgn_text_edit = QTextEdit()
        self.pgn_text_edit.setMaximumHeight(100)
        self.pgn_text_edit.setPlaceholderText("Paste PGN text here…")
        paste_lay.addWidget(self.pgn_text_edit)
        paste_btn = QPushButton("📋 Load Pasted PGN")
        paste_btn.clicked.connect(self._paste_pgn)
        paste_lay.addWidget(paste_btn)
        input_layout.addWidget(paste_grp)

        game_grp = QGroupBox("Game Selection")
        game_lay = QHBoxLayout(game_grp)
        game_lay.addWidget(QLabel("Game:"))
        self.game_select_combo = QComboBox()
        self.game_select_combo.setMinimumWidth(200)
        self.game_select_combo.currentIndexChanged.connect(self._on_game_selected)
        game_lay.addWidget(self.game_select_combo, stretch=1)
        input_layout.addWidget(game_grp)

        names_grp = QGroupBox("Player Names (overrides)")
        names_lay = QFormLayout(names_grp)
        self.white_name_edit = QLineEdit()
        self.white_name_edit.setPlaceholderText("Auto from PGN")
        names_lay.addRow("White:", self.white_name_edit)
        self.black_name_edit = QLineEdit()
        self.black_name_edit.setPlaceholderText("Auto from PGN")
        names_lay.addRow("Black:", self.black_name_edit)
        input_layout.addWidget(names_grp)

        input_layout.addStretch()
        tabs.addTab(input_tab, "📂 Input")

        # Tab 2: Export
        export_tab = QWidget()
        export_layout = QVBoxLayout(export_tab)

        vid_grp = QGroupBox("Video Settings")
        vid_form = QFormLayout(vid_grp)
        self.res_combo = QComboBox()
        self.res_combo.addItems(RESOLUTION_LIST)
        vid_form.addRow("Resolution:", self.res_combo)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(10, 120)
        self.fps_spin.setValue(30)
        vid_form.addRow("FPS:", self.fps_spin)
        self.hold_spin = QDoubleSpinBox()
        self.hold_spin.setRange(0.3, 30.0)
        self.hold_spin.setValue(1.5)
        self.hold_spin.setSingleStep(0.5)
        self.hold_spin.setSuffix(" s")
        vid_form.addRow("Hold per move:", self.hold_spin)
        self.anim_spin = QDoubleSpinBox()
        self.anim_spin.setRange(0.0, 3.0)
        self.anim_spin.setValue(DEFAULT_ANIM_DURATION)
        self.anim_spin.setSingleStep(0.1)
        self.anim_spin.setSuffix(" s")
        vid_form.addRow("Move animation:", self.anim_spin)
        export_layout.addWidget(vid_grp)

        out_grp = QGroupBox("Output")
        out_lay = QHBoxLayout(out_grp)
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setText("chess_video.mp4")
        out_lay.addWidget(self.output_path_edit, stretch=1)
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self._browse_output)
        out_lay.addWidget(out_browse)
        export_layout.addWidget(out_grp)

        btn_row = QHBoxLayout()
        self.export_btn = QPushButton("🎬 Export Video")
        self.export_btn.setStyleSheet("QPushButton{background:#2a6a3a;color:#fff;font-weight:bold;padding:10px 20px;}QPushButton:hover{background:#3a8a4a;}QPushButton:disabled{background:#222;color:#666;}")
        self.export_btn.clicked.connect(self._start_export)
        btn_row.addWidget(self.export_btn)
        self.cancel_btn = QPushButton("✖ Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_export)
        btn_row.addWidget(self.cancel_btn)
        export_layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        export_layout.addWidget(self.progress_bar)
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#aaa;font-size:11px;")
        self.status_lbl.setWordWrap(True)
        export_layout.addWidget(self.status_lbl)

        export_layout.addStretch()
        tabs.addTab(export_tab, "🎬 Export")

        # Tab 3: Batch
        batch_tab = QWidget()
        batch_layout = QVBoxLayout(batch_tab)

        bsrc_grp = QGroupBox("PGN Source Folder")
        bsrc_lay = QHBoxLayout(bsrc_grp)
        self.batch_src_edit = QLineEdit()
        self.batch_src_edit.setPlaceholderText("Folder with .pgn files…")
        bsrc_lay.addWidget(self.batch_src_edit, stretch=1)
        bsrc_browse = QPushButton("Browse…")
        bsrc_browse.clicked.connect(self._browse_batch_src)
        bsrc_lay.addWidget(bsrc_browse)
        batch_layout.addWidget(bsrc_grp)

        bdst_grp = QGroupBox("Output Folder")
        bdst_lay = QHBoxLayout(bdst_grp)
        self.batch_dst_edit = QLineEdit()
        self.batch_dst_edit.setPlaceholderText("Output folder…")
        bdst_lay.addWidget(self.batch_dst_edit, stretch=1)
        bdst_browse = QPushButton("Browse…")
        bdst_browse.clicked.connect(self._browse_batch_dst)
        bdst_lay.addWidget(bdst_browse)
        batch_layout.addWidget(bdst_grp)

        bset_grp = QGroupBox("Batch Settings")
        bset_form = QFormLayout(bset_grp)
        self.batch_res_combo = QComboBox()
        self.batch_res_combo.addItems(RESOLUTION_LIST)
        bset_form.addRow("Resolution:", self.batch_res_combo)
        self.batch_fps_spin = QSpinBox()
        self.batch_fps_spin.setRange(10, 120)
        self.batch_fps_spin.setValue(30)
        bset_form.addRow("FPS:", self.batch_fps_spin)
        self.batch_hold_spin = QDoubleSpinBox()
        self.batch_hold_spin.setRange(0.3, 30.0)
        self.batch_hold_spin.setValue(1.5)
        self.batch_hold_spin.setSingleStep(0.5)
        self.batch_hold_spin.setSuffix(" s")
        bset_form.addRow("Hold per move:", self.batch_hold_spin)
        batch_layout.addWidget(bset_grp)

        beval_grp = QGroupBox("Engine Eval (Batch)")
        beval_lay = QFormLayout(beval_grp)
        self.batch_eval_chk = QCheckBox("Run Stockfish during batch export")
        beval_lay.addRow(self.batch_eval_chk)
        batch_layout.addWidget(beval_grp)

        bbtn_row = QHBoxLayout()
        self.batch_start_btn = QPushButton("🚀 Start Batch")
        self.batch_start_btn.setStyleSheet("QPushButton{background:#2a6a3a;color:#fff;font-weight:bold;padding:10px 20px;}QPushButton:hover{background:#3a8a4a;}QPushButton:disabled{background:#222;color:#666;}")
        self.batch_start_btn.clicked.connect(self._start_batch)
        bbtn_row.addWidget(self.batch_start_btn)
        self.batch_cancel_btn = QPushButton("✖ Cancel Batch")
        self.batch_cancel_btn.setEnabled(False)
        self.batch_cancel_btn.clicked.connect(self._cancel_batch)
        bbtn_row.addWidget(self.batch_cancel_btn)
        batch_layout.addLayout(bbtn_row)

        self.batch_progress_lbl = QLabel("")
        self.batch_progress_lbl.setStyleSheet("color:#aaa;font-size:11px;")
        batch_layout.addWidget(self.batch_progress_lbl)
        
        batch_layout.addStretch()
        tabs.addTab(batch_tab, "📦 Batch")

        # Tab 4: Settings
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)

        theme_grp = QGroupBox("Board Theme")
        theme_lay = QFormLayout(theme_grp)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES.keys())
        self.theme_combo.currentTextChanged.connect(self._set_theme)
        theme_lay.addRow("Theme:", self.theme_combo)
        self.flip_chk = QCheckBox("Flip board")
        self.flip_chk.toggled.connect(self._toggle_flip)
        theme_lay.addRow(self.flip_chk)
        settings_layout.addWidget(theme_grp)

        engine_grp = QGroupBox("Stockfish Engine")
        engine_lay = QFormLayout(engine_grp)
        self.engine_path_edit = QLineEdit()
        self.engine_path_edit.setPlaceholderText("Path to Stockfish…")
        engine_lay.addRow("Path:", self.engine_path_edit)
        engine_browse = QPushButton("Browse…")
        engine_browse.clicked.connect(self._browse_engine)
        engine_lay.addRow("", engine_browse)
        self.eval_export_chk = QCheckBox("Run eval during export")
        engine_lay.addRow(self.eval_export_chk)
        self.eval_depth_spin = QSpinBox()
        self.eval_depth_spin.setRange(10, 30)
        self.eval_depth_spin.setValue(18)
        engine_lay.addRow("Eval depth:", self.eval_depth_spin)
        self.eval_preview_btn = QPushButton("🔍 Analyze Current Game")
        self.eval_preview_btn.clicked.connect(self._analyze_game)
        engine_lay.addRow(self.eval_preview_btn)
        settings_layout.addWidget(engine_grp)

        fen_grp = QGroupBox("FEN")
        fen_lay = QHBoxLayout(fen_grp)
        self.fen_lbl = QLabel("—")
        self.fen_lbl.setStyleSheet("color:#9cf;font-size:11px;")
        self.fen_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fen_lay.addWidget(self.fen_lbl, stretch=1)
        copy_fen_btn = QPushButton("📋 Copy")
        copy_fen_btn.clicked.connect(self._copy_fen)
        fen_lay.addWidget(copy_fen_btn)
        settings_layout.addWidget(fen_grp)

        settings_layout.addStretch()
        tabs.addTab(settings_tab, "⚙ Settings")

        right_layout.addWidget(tabs)
        main_layout.addWidget(right_widget, stretch=3)

    def _load_pgn_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PGN File", "", "PGN Files (*.pgn);;All Files (*)")
        if path: self.pgn_path_edit.setText(path); self._load_pgn_from_path(path)

    def _paste_pgn(self):
        text = self.pgn_text_edit.toPlainText().strip()
        if not text: QMessageBox.warning(self, "No PGN", "Paste PGN text first."); return
        self._load_pgn_from_text(text)

    def _load_pgn_from_path(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f: text = f.read()
            self._load_pgn_from_text(text)
        except Exception as e: QMessageBox.critical(self, "Error", f"Failed to read PGN:\n{e}")

    def _load_pgn_from_text(self, text):
        self._all_games = []
        try:
            pgn_io = io.StringIO(text)
            while True:
                game = chess.pgn.read_game(pgn_io)
                if game is None: break
                self._all_games.append(game)
        except Exception as e: QMessageBox.critical(self, "PGN Parse Error", str(e)); return
        if not self._all_games: QMessageBox.warning(self, "No Games", "No valid games found in PGN."); return
        self.game_select_combo.blockSignals(True); self.game_select_combo.clear()
        for i, g in enumerate(self._all_games):
            white, black, date = g.headers.get("White", "?"), g.headers.get("Black", "?"), g.headers.get("Date", "")
            label = f"{i+1}. {white} vs {black}" + (f"  ({date})" if date else ""); self.game_select_combo.addItem(label)
        self.game_select_combo.blockSignals(False)
        if self._all_games: self._load_game(self._all_games[0])

    def _on_game_selected(self, idx):
        if 0 <= idx < len(self._all_games): self._load_game(self._all_games[idx])

    def _load_game(self, game):
        self.game, self.move_list, self.eval_cache, self._current_move_idx = game, list(game.mainline()), {}, -1
        white, black, result, event, opening = game.headers.get("White", "White"), game.headers.get("Black", "Black"), game.headers.get("Result", "*"), game.headers.get("Event", ""), game.headers.get("Opening", "")
        white_elo, black_elo = game.headers.get("WhiteElo", ""), game.headers.get("BlackElo", "")
        if white_elo: white = f"{white} ({white_elo})"
        if black_elo: black = f"{black} ({black_elo})"
        info_text = f"{white} vs {black}  {result}" + (f"  —  {event}" if event else ""); self.game_info_lbl.setText(info_text); self.opening_lbl.setText(opening); self.white_name_edit.setPlaceholderText(white); self.black_name_edit.setPlaceholderText(black)
        self.move_table.blockSignals(True); self.move_table.setRowCount(0); row = 0
        for i, node in enumerate(self.move_list):
            if i % 2 == 0: self.move_table.insertRow(row); self.move_table.setItem(row, 0, QTableWidgetItem(str(row + 1))); self.move_table.setItem(row, 1, QTableWidgetItem(node.san()))
            else: self.move_table.setItem(row, 2, QTableWidgetItem(node.san())); row += 1
        if len(self.move_list) % 2 == 1: self.move_table.setItem(row, 2, QTableWidgetItem(""))
        self.move_table.blockSignals(False); self._go_last()

    def _go_first(self):
        if not self.game: return; self._current_move_idx = -1; self._update_board_position()

    def _go_prev(self):
        if not self.game or self._current_move_idx < 0: return; self._current_move_idx -= 1; self._update_board_position()

    def _go_next(self):
        if not self.game or self._current_move_idx >= len(self.move_list) - 1: return; self._current_move_idx += 1; self._update_board_position()

    def _go_last(self):
        if not self.game: return; self._current_move_idx = len(self.move_list) - 1; self._update_board_position()

    def _on_move_cell(self, row, col, _p1, _p2):
        if not self.move_list: return; idx = row * 2 + (1 if col == 2 else 0)
        if 0 <= idx < len(self.move_list): self._current_move_idx = idx; self._update_board_position(scroll_to=False)

    def _update_board_position(self, scroll_to=True):
        if not self.game: return
        if self._current_move_idx < 0: board, last_move = self.game.board(), None
        else: node = self.move_list[self._current_move_idx]; board, last_move = node.board(), node.move
        self.board_preview.set_board(board, last_move); self.move_pos_lbl.setText(f"{self._current_move_idx + 1} / {len(self.move_list)}"); self.fen_lbl.setText(board.fen())
        self.move_table.blockSignals(True); self.move_table.clearSelection()
        if 0 <= self._current_move_idx < len(self.move_list):
            row, col = self._current_move_idx // 2, 1 if self._current_move_idx % 2 == 0 else 2
            if row < self.move_table.rowCount():
                item = self.move_table.item(row, col)
                if item: self.move_table.setCurrentItem(item);
                if scroll_to: self.move_table.scrollToItem(item)
        self.move_table.blockSignals(False)

    def _set_theme(self, name): self.board_preview.set_theme(THEMES.get(name, BoardTheme()))
    def _toggle_flip(self, checked): self.board_preview.set_flipped(checked)

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Video", "chess_video.mp4", "MP4 Files (*.mp4);;AVI Files (*.avi);;All Files (*)")
        if path: self.output_path_edit.setText(path)

    def _browse_engine(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Stockfish", "", "Executables (*);;All Files (*)")
        if path: self.engine_path_edit.setText(path)

    def _copy_fen(self): QApplication.clipboard().setText(self.fen_lbl.text())

    def _start_export(self):
        if not self.game or not self.move_list: QMessageBox.warning(self, "No Game", "Load a PGN game first."); return
        if self._worker and self._worker.isRunning(): QMessageBox.warning(self, "Busy", "Export already in progress."); return
        theme = THEMES.get(self.theme_combo.currentText(), BoardTheme()); br = BoardRenderer(theme=theme, flipped=self.flip_chk.isChecked())
        wn = self.white_name_edit.text().strip() or self.white_name_edit.placeholderText()
        bn = self.black_name_edit.text().strip() or self.black_name_edit.placeholderText()
        self._worker = StreamingExportWorker(game=self.game, move_list=self.move_list, eval_cache=self.eval_cache, board_renderer=br, video_bg_color=self.video_bg_color, white_name=wn, black_name=bn, overlays=[], fps=self.fps_spin.value(), hold=self.hold_spin.value(), res_str=self.res_combo.currentText(), output_path=self.output_path_edit.text().strip() or "chess_video.mp4", stockfish_path=self.engine_path_edit.text().strip(), eval_during_export=self.eval_export_chk.isChecked(), anim_duration=self.anim_spin.value())
        self._worker.progress.connect(self._on_export_progress); self._worker.export_finished.connect(self._on_export_finished); self._worker.start(); self.export_btn.setEnabled(False); self.cancel_btn.setEnabled(True); self.progress_bar.setValue(0); self.status_lbl.setText("Exporting…")

    def _cancel_export(self):
        if self._worker and self._worker.isRunning(): self._worker.cancel(); self.status_lbl.setText("Cancelling…")

    def _on_export_progress(self, pct, msg): self.progress_bar.setValue(pct); self.status_lbl.setText(msg)

    def _on_export_finished(self, msg):
        self.export_btn.setEnabled(True); self.cancel_btn.setEnabled(False); self.progress_bar.setValue(100 if not msg.startswith("ERROR") else 0); self.status_lbl.setText(msg)
        if msg.startswith("ERROR"): QMessageBox.critical(self, "Export Error", msg)
        elif not msg.startswith("Cancelled"): QMessageBox.information(self, "Export Complete", msg)

    def _browse_batch_src(self):
        path = QFileDialog.getExistingDirectory(self, "Select PGN Source Folder")
        if path: self.batch_src_edit.setText(path)

    def _browse_batch_dst(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if path: self.batch_dst_edit.setText(path)

    def _start_batch(self):
        src_dir, dst_dir = self.batch_src_edit.text().strip(), self.batch_dst_edit.text().strip()
        if not src_dir or not os.path.isdir(src_dir): QMessageBox.warning(self, "Invalid Source", "Select a valid PGN source folder."); return
        if not dst_dir: QMessageBox.warning(self, "Invalid Output", "Select an output folder."); return
        pgn_files = sorted(glob.glob(os.path.join(src_dir, "*.pgn")))
        if not pgn_files: QMessageBox.warning(self, "No PGN Files", f"No .pgn files found in:\n{src_dir}"); return
        theme = THEMES.get(self.theme_combo.currentText(), BoardTheme())
        settings = {"res_str": self.batch_res_combo.currentText(), "fps": self.batch_fps_spin.value(), "hold": self.batch_hold_spin.value(), "anim_duration": self.anim_spin.value(), "theme": theme, "flipped": self.flip_chk.isChecked(), "bg_color": self.video_bg_color, "white_name": "White", "black_name": "Black", "overlays": [], "eval_during": self.batch_eval_chk.isChecked(), "stockfish_path": self.engine_path_edit.text().strip()}
        self._batch_worker = BatchPGNExportWorker(pgn_files, dst_dir, settings); self._batch_worker.batch_progress.connect(self._on_batch_progress); self._batch_worker.game_exported.connect(self._on_batch_game_exported); self._batch_worker.batch_finished.connect(self._on_batch_finished); self._batch_worker.start(); self.batch_start_btn.setEnabled(False); self.batch_cancel_btn.setEnabled(True); self.batch_progress_lbl.setText("Starting batch export…")

    def _cancel_batch(self):
        if self._batch_worker and self._batch_worker.isRunning(): self._batch_worker.cancel()

    def _on_batch_progress(self, c, t, f): self.batch_progress_lbl.setText(f"Processing game {c}/{t} — {f}")
    def _on_batch_game_exported(self, p): pass
    def _on_batch_finished(self, s, f):
        self.batch_start_btn.setEnabled(True); self.batch_cancel_btn.setEnabled(False); msg = f"Batch complete: {s} succeeded, {f} failed"; self.batch_progress_lbl.setText(msg); QMessageBox.information(self, "Batch Complete", msg)

    def _analyze_game(self):
        sf_path = self.engine_path_edit.text().strip()
        if not sf_path or not os.path.isfile(sf_path): QMessageBox.warning(self, "No Engine", "Set a valid Stockfish path first."); return
        if not self.game or not self.move_list: QMessageBox.warning(self, "No Game", "Load a PGN game first."); return
        depth = self.eval_depth_spin.value(); self.eval_preview_btn.setEnabled(False); self.eval_preview_btn.setText("⏳ Analyzing…"); QApplication.processEvents()
        try: uci = _SyncUCI(sf_path)
        except Exception as e: QMessageBox.critical(self, "Engine Error", str(e)); self.eval_preview_btn.setEnabled(True); self.eval_preview_btn.setText("🔍 Analyze Current Game"); return
        self.eval_cache = {}
        try:
            _, ev = uci.analyse(self.game.board().fen(), depth); self.eval_cache[None] = float(ev)
            for i, node in enumerate(self.move_list):
                _, ev = uci.analyse(node.board().fen(), depth); self.eval_cache[node] = float(ev)
                if i % 5 == 0: self.status_lbl.setText(f"Analyzing move {i+1}/{len(self.move_list)}…"); QApplication.processEvents()
        except Exception as e: pass
        finally:
            try: uci.close()
            except Exception: pass
        self.eval_preview_btn.setEnabled(True); self.eval_preview_btn.setText("🔍 Analyze Current Game"); self.status_lbl.setText(f"Analysis complete — {len(self.eval_cache)} positions evaluated")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pgn"): event.acceptProposedAction(); return

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pgn"): self.pgn_path_edit.setText(path); self._load_pgn_from_path(path); break

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F: self._toggle_flip(not self.flip_chk.isChecked()); self.flip_chk.setChecked(not self.flip_chk.isChecked())
        super().keyPressEvent(event)