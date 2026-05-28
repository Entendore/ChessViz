"""
main_window.py — Main application window tying together all components.
"""

import os, json, threading

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QFrame, QListWidget,
    QListWidgetItem, QSlider, QComboBox, QCheckBox,
    QProgressBar, QGroupBox, QSplitter, QFileDialog, QStatusBar,
    QLineEdit, QApplication
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from config import (
    THEMES, EXPORT_PRESETS, ExportConfig, DATA_DIR, LICHESS_DB_PATH, log
)
from engine import ChessEngine
from sound import SoundManager
from board_widget import ChessBoardWidget
from data_provider import DataProvider
from openings_loader import load_openings
from helpers import parse_opening_image


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chess Openings Explorer")
        self.setMinimumSize(1100, 750)

        self.engine = ChessEngine()
        self.sound_mgr = SoundManager()
        self.data = DataProvider()
        self.export_cfg = ExportConfig()
        self.current_opening = None
        self.move_index = 0
        self._uci_sequence = []

        central = QWidget(); self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # --- Left panel ---
        left = QWidget(); left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        search_box = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search openings…")
        self.search_edit.textChanged.connect(self._on_search)
        search_box.addWidget(self.search_edit)
        left_layout.addLayout(search_box)

        self.openings_list = QListWidget()
        self.openings_list.currentRowChanged.connect(self._on_opening_selected)
        left_layout.addWidget(self.openings_list)

        import_btn = QPushButton("Import Openings…")
        import_btn.clicked.connect(self._on_import)
        left_layout.addWidget(import_btn)
        left.setMaximumWidth(300)

        # --- Center panel ---
        center = QWidget(); center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)

        self.board_widget = ChessBoardWidget(self.engine, self.sound_mgr)
        self.board_widget.move_made.connect(self._on_move_made)
        center_layout.addWidget(self.board_widget, alignment=Qt.AlignCenter)

        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("⏮")
        self.btn_start.clicked.connect(self._go_start)
        self.btn_prev  = QPushButton("◀")
        self.btn_prev.clicked.connect(self._go_prev)
        self.btn_next  = QPushButton("▶")
        self.btn_next.clicked.connect(self._go_next)
        self.btn_end   = QPushButton("⏭")
        self.btn_end.clicked.connect(self._go_end)
        self.btn_flip  = QPushButton("🔄")
        self.btn_flip.clicked.connect(self._flip_board)
        for b in (self.btn_start, self.btn_prev, self.btn_next,
                  self.btn_end, self.btn_flip):
            b.setFixedWidth(48); ctrl.addWidget(b)

        self.anim_slider = QSlider(Qt.Horizontal)
        self.anim_slider.setRange(0, 500); self.anim_slider.setValue(250)
        self.anim_slider.setFixedWidth(120)
        self.anim_slider.valueChanged.connect(self._on_anim_speed)
        ctrl.addWidget(QLabel("Speed:"))
        ctrl.addWidget(self.anim_slider)
        ctrl.addStretch()

        # ★ Export button
        self.btn_export = QPushButton("🎬 Export MP4")
        self.btn_export.setStyleSheet(
            "QPushButton{background:#2a82da;color:#fff;font-weight:bold;"
            "padding:6px 14px;border-radius:4px}"
            "QPushButton:hover{background:#3a92ea}")
        self.btn_export.clicked.connect(self._on_export)
        ctrl.addWidget(self.btn_export)

        center_layout.addLayout(ctrl)

        # --- Right panel ---
        right = QWidget(); right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        info_group = QGroupBox("Opening Info")
        info_lay = QVBoxLayout(info_group)
        self.lbl_name = QLabel("—")
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setFont(QFont("Sans", 12, QFont.Bold))
        self.lbl_eco = QLabel(""); self.lbl_epd = QLabel("")
        info_lay.addWidget(self.lbl_name)
        info_lay.addWidget(self.lbl_eco)
        info_lay.addWidget(self.lbl_epd)
        right_layout.addWidget(info_group)

        moves_group = QGroupBox("Moves")
        moves_lay = QVBoxLayout(moves_group)
        self.moves_text = QTextEdit(); self.moves_text.setReadOnly(True)
        self.moves_text.setMaximumHeight(200)
        moves_lay.addWidget(self.moves_text)
        right_layout.addWidget(moves_group)

        settings_group = QGroupBox("Settings")
        settings_lay = QVBoxLayout(settings_group)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES.keys())
        self.theme_combo.currentTextChanged.connect(self._on_theme)
        settings_lay.addWidget(QLabel("Theme:"))
        settings_lay.addWidget(self.theme_combo)

        self.sound_check = QCheckBox("Sound")
        self.sound_check.setChecked(True)
        self.sound_check.toggled.connect(self.sound_mgr.set_enabled)
        settings_lay.addWidget(self.sound_check)

        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100); self.vol_slider.setValue(70)
        self.vol_slider.valueChanged.connect(
            lambda v: self.sound_mgr.set_volume(v / 100.0))
        settings_lay.addWidget(QLabel("Volume:"))
        settings_lay.addWidget(self.vol_slider)
        right_layout.addWidget(settings_group)
        right_layout.addStretch()
        right.setMaximumWidth(260)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left); splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        main_layout.addWidget(splitter)

        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.status.showMessage("Ready — Import an openings file to begin")

        self._refresh_openings_list()
        QTimer.singleShot(100, self._auto_load_bundled)

    # ══════════════════════════════════════════════════════════════════════════
    #  AUTO-LOAD BUNDLED LICHESS DB
    # ══════════════════════════════════════════════════════════════════════════

    def _auto_load_bundled(self):
        if not os.path.exists(LICHESS_DB_PATH):
            self.status.showMessage(
                "No bundled database — use Import to load openings")
            return
        if self.data.get_opening_count() > 0:
            self.status.showMessage(
                f"{self.data.get_opening_count():,} openings ready")
            return
        self.status.showMessage("Loading bundled openings database…")
        QApplication.processEvents()
        log(f"Auto-loading bundled DB: {LICHESS_DB_PATH}", "INIT")

        def _worker():
            try:
                for chunk_count, total in self.data.stream_import(
                        'openings', load_openings(LICHESS_DB_PATH)):
                    log(f"Auto-load chunk: +{chunk_count}  ({total} total)",
                        "IMPORT")
            except Exception as e:
                log(f"Auto-load error: {e}", "ERROR")
                QTimer.singleShot(0, lambda: self.status.showMessage(
                    f"Error loading bundled DB: {e}"))
                return
            QTimer.singleShot(0, self._on_auto_load_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_auto_load_done(self):
        count = self.data.get_opening_count()
        self._refresh_openings_list()
        self.status.showMessage(f"{count:,} openings loaded from lichess DB ✓")

    # ══════════════════════════════════════════════════════════════════════════
    #  OPENINGS LIST
    # ══════════════════════════════════════════════════════════════════════════

    def _refresh_openings_list(self):
        self.openings_list.clear()
        import pandas as pd
        slim = self.data.openings_slim
        if isinstance(slim, pd.DataFrame) and len(slim) > 0:
            for _, row in slim.iterrows():
                title = row.get('display_title', row.get('name', '?'))
                item = QListWidgetItem(str(title))
                item.setData(Qt.UserRole, int(row.get('id', 0)))
                self.openings_list.addItem(item)
            self.status.showMessage(f"{len(slim):,} openings loaded")

    def _on_search(self, text):
        text_lower = text.lower()
        for i in range(self.openings_list.count()):
            item = self.openings_list.item(i)
            item.setHidden(text_lower not in item.text().lower())

    def _on_opening_selected(self, row):
        if row < 0: return
        item = self.openings_list.item(row)
        opening_id = item.data(Qt.UserRole)
        record = self.data.get_opening(opening_id)
        if not record: return
        self.current_opening = record
        self._display_opening(record)

    def _display_opening(self, rec):
        self.lbl_name.setText(
            rec.get('display_title', rec.get('name', '?')))
        self.lbl_eco.setText(f"ECO: {rec.get('eco', '?')}")
        self.lbl_epd.setText(f"EPD: {rec.get('epd', '—')}")
        self.engine.reset(); self.move_index = 0
        uci_moves = rec.get('uci_moves', [])
        if isinstance(uci_moves, str):
            try: uci_moves = json.loads(uci_moves)
            except Exception: uci_moves = uci_moves.split()
        self._uci_sequence = uci_moves
        notations = []
        for uci in uci_moves:
            info = self.engine.make_move_uci(uci)
            if info: notations.append(info['notation'])
        self.moves_text.setPlainText(" ".join(notations))
        self.move_index = len(uci_moves)
        self.board_widget.update()
        img_raw = rec.get('img_raw', '')
        if img_raw: parse_opening_image(img_raw)

    # ══════════════════════════════════════════════════════════════════════════
    #  NAVIGATION
    # ══════════════════════════════════════════════════════════════════════════

    def _go_start(self):
        self.engine.reset(); self.move_index = 0
        if self.current_opening:
            uci = self.current_opening.get('uci_moves', [])
            if isinstance(uci, str):
                try: uci = json.loads(uci)
                except Exception: uci = uci.split()
            self._uci_sequence = uci
        self.board_widget.update()

    def _go_prev(self):
        if self.engine.undo():
            self.move_index = max(0, self.move_index - 1)
            self.board_widget.update()

    def _go_next(self):
        if self.move_index < len(self._uci_sequence):
            self.engine.make_move_uci(self._uci_sequence[self.move_index])
            self.move_index += 1; self.board_widget.update()

    def _go_end(self):
        while self.move_index < len(self._uci_sequence):
            self.engine.make_move_uci(self._uci_sequence[self.move_index])
            self.move_index += 1
        self.board_widget.update()

    def _flip_board(self):
        self.board_widget.flip()

    # ══════════════════════════════════════════════════════════════════════════
    #  SETTINGS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_theme(self, name):
        if name in THEMES:
            self.board_widget.current_theme = THEMES[name]
            self.board_widget.update()

    def _on_anim_speed(self, val):
        self.board_widget.anim_speed = val

    def _on_move_made(self, notation):
        self.status.showMessage(f"Move: {notation}")

    # ══════════════════════════════════════════════════════════════════════════
    #  EXPORT VIDEO
    # ══════════════════════════════════════════════════════════════════════════

    def _on_export(self):
        if not self.current_opening:
            self.status.showMessage("Select an opening first")
            return
        from export_dialog import ExportDialog
        dlg = ExportDialog(self.current_opening, self.export_cfg, self)
        dlg.exec()

    # ══════════════════════════════════════════════════════════════════════════
    #  IMPORT
    # ══════════════════════════════════════════════════════════════════════════

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Openings", DATA_DIR,
            "Data Files (*.csv *.parquet *.pq *.duckdb *.db *.sqlite);;"
            "All Files (*)")
        if not path: return
        self.status.showMessage(f"Importing {path}…")
        QApplication.processEvents()

        def do_import():
            try:
                for chunk_count, total in self.data.stream_import(
                        'openings', load_openings(path)):
                    log(f"Imported chunk: {chunk_count} ({total} total)",
                        "IMPORT")
            except Exception as e:
                log(f"Import error: {e}", "ERROR")
                QTimer.singleShot(0, lambda: self.status.showMessage(
                    f"Import error: {e}"))
                return
            QTimer.singleShot(0, self._refresh_openings_list)

        threading.Thread(target=do_import, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    #  CLEANUP
    # ══════════════════════════════════════════════════════════════════════════

    def closeEvent(self, e):
        self.sound_mgr.cleanup()
        super().closeEvent(e)