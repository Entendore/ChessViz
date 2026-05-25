"""Main application window — core layout, puzzle tab, settings tab.
Openings tab is provided by the OpeningsMixin in openings_tab.py.
"""

import os, math
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QPushButton, QTextEdit, QFileDialog,
    QFrame, QListWidget, QListWidgetItem, QSlider,
    QSpinBox, QLineEdit, QFormLayout, QComboBox,
    QProgressBar, QGroupBox, QCheckBox, QScrollArea
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from constants import (
    log, ExportConfig, ANIM_SPEED_DEFAULT, ANIM_SPEED_SLOW,
    DATA_DIR, THEMES, HAS_CUPY, HAS_NUMBA
)
from engine import ChessEngine
from sound import SoundManager
from board_widget import ChessBoardWidget
from export import ExportWorker, BatchExportWorker
from data_manager import DataProvider, DataLoadWorker
from openings_tab import OpeningsMixin


# ═══════════════════════════════════════════════════════════════════════════════
#  Checkable list helper
# ═══════════════════════════════════════════════════════════════════════════════

class CheckableListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def add_checkable_item(self, text, data=None, checked=False):
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        if data is not None:
            item.setData(Qt.UserRole, data)
        self.addItem(item)
        return item


# ═══════════════════════════════════════════════════════════════════════════════
#  Main Window
# ═══════════════════════════════════════════════════════════════════════════════

class MainWindow(QWidget, OpeningsMixin):
    _PAGE_SIZE = 100

    def __init__(self):
        super().__init__()
        self.setWindowTitle("♚ Chess Learning App")
        log("Initializing Chess Learning App...", "APP")

        self._apply_professional_style()

        # ── Core state ────────────────────────────────────────────────────
        self.engine = ChessEngine()
        self.snd = SoundManager()
        self.db = DataProvider()
        self.board_widget = ChessBoardWidget(self.engine, self.snd)
        self.board_widget.move_made.connect(self.on_move)

        self.export_worker = None
        self.batch_worker = None
        self.puzzles_loaded = False
        self.openings_loaded = False
        self._active_workers = []

        self._pz_page = 0
        self._pz_checked = set()
        
        # Openings mixin state
        self._op_page = 0
        self._op_checked = set()
        self._current_opening = None
        self.opening_step_idx = 0

        # ── Layout ────────────────────────────────────────────────────────
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.setFixedWidth(460)
        layout.addWidget(self.tabs)

        board_frame = QFrame()
        board_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        board_frame.setStyleSheet(
            "QFrame { border: 1px solid #4a4a4f; border-radius: 6px; background: #25252a; }")
        bl = QVBoxLayout(board_frame)
        bl.setContentsMargins(8, 8, 8, 8)
        bl.setSpacing(8)

        top_ctrl = QHBoxLayout()
        top_ctrl.addWidget(QLabel("Theme:"))
        self.theme_cb = QComboBox()
        self.theme_cb.addItems(THEMES.keys())
        self.theme_cb.currentTextChanged.connect(self._change_theme)
        top_ctrl.addWidget(self.theme_cb)

        top_ctrl.addStretch()

        top_ctrl.addWidget(QLabel("Speed:"))
        self.anim_slider = QSlider(Qt.Horizontal)
        self.anim_slider.setRange(0, 600)
        self.anim_slider.setValue(600 - ANIM_SPEED_DEFAULT)
        self.anim_slider.setInvertedAppearance(True)
        self.anim_slider.setFixedWidth(120)
        self.anim_lbl = QLabel(self._fmt_anim(ANIM_SPEED_DEFAULT))
        self.anim_slider.valueChanged.connect(self._update_anim_speed)
        top_ctrl.addWidget(self.anim_slider)
        top_ctrl.addWidget(self.anim_lbl)
        bl.addLayout(top_ctrl)

        bl.addWidget(self.board_widget, alignment=Qt.AlignCenter)
        layout.addWidget(board_frame, alignment=Qt.AlignCenter)

        self._build_puzzle_tab()
        self._build_openings_tab()  # Defined in OpeningsMixin
        self._build_settings_tab()

        self.snd.play("start")
        log("App initialization complete", "APP")

        QTimer.singleShot(50,  lambda: self._start_data_load("puzzles"))
        QTimer.singleShot(100, lambda: self._start_data_load("openings"))

    # ── Fix: Prevent threads from being destroyed while running on exit ────

    def closeEvent(self, event):
        """Gracefully stop all running threads before closing the window."""
        log("Closing application, waiting for threads to finish...", "APP")
        
        # Stop data load workers
        for worker in self._active_workers[:]:
            if worker.isRunning():
                worker.abort()
                worker.wait(2000)  # Wait up to 2 seconds for it to finish
                
        # Stop export workers
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.abort()
            self.export_worker.wait(2000)
            
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.abort()
            self.batch_worker.wait(2000)
            
        event.accept()

    def on_move(self, notation):
        """Handle a move made on the board widget."""
        pass

    # ── Styling ───────────────────────────────────────────────────────────────

    def _apply_professional_style(self):
        self.setStyleSheet("""
            QWidget {
                font-family: 'Segoe UI', Arial, sans-serif;
                color: #d0d0d0;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #4a4a4f;
                border-radius: 6px;
                margin-top: 14px;
                padding: 12px 8px 8px 8px;
                background-color: #2e2e32;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #a0a0a8;
            }
            QPushButton {
                padding: 6px 14px;
                border-radius: 4px;
                background-color: #3c3f41;
                border: 1px solid #4a4a4f;
                color: #d0d0d0;
            }
            QPushButton:hover {
                background-color: #4e5254;
                border-color: #606068;
            }
            QPushButton:pressed {
                background-color: #2d2f30;
            }
            QPushButton:disabled {
                background-color: #2a2a2e;
                color: #606068;
                border-color: #333338;
            }
            QTabWidget::pane {
                border: 1px solid #4a4a4f;
                border-radius: 4px;
                background-color: #25252a;
            }
            QTabBar::tab {
                padding: 8px 18px;
                border: 1px solid #4a4a4f;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                background: #2e2e32;
                color: #a0a0a8;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #3c3f41;
                color: #ffffff;
            }
            QListWidget {
                border: 1px solid #4a4a4f;
                border-radius: 4px;
                background-color: #25252a;
                padding: 2px;
            }
            QListWidget::item {
                padding: 4px;
                border-bottom: 1px solid #333338;
            }
            QListWidget::item:hover {
                background-color: #3c3f41;
            }
            QListWidget::item:selected {
                background-color: #4e5254;
                color: white;
            }
            QLineEdit, QSpinBox, QComboBox {
                padding: 4px 8px;
                border: 1px solid #4a4a4f;
                border-radius: 4px;
                background-color: #25252a;
                color: #d0d0d0;
            }
            QComboBox::drop-down {
                border: none;
            }
            QSlider::groove:horizontal {
                border: 1px solid #4a4a4f;
                height: 6px;
                background: #25252a;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #a0a0a8;
                border: 1px solid #4a4a4f;
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QTextEdit {
                border: 1px solid #4a4a4f;
                border-radius: 4px;
                background-color: #25252a;
                color: #d0d0d0;
            }
            QProgressBar {
                border: 1px solid #4a4a4f;
                border-radius: 4px;
                text-align: center;
                background-color: #25252a;
                color: white;
                height: 20px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #5c9fd6;
                border-radius: 3px;
            }
        """)

    # ── Theme / animation helpers ────────────────────────────────────────────

    def _change_theme(self, name):
        if name in THEMES:
            self.board_widget.current_theme = THEMES[name]
            self.board_widget.update()
            self.theme_cb.blockSignals(True)
            self.theme_cb.setCurrentText(name)
            self.theme_cb.blockSignals(False)
            if hasattr(self, 'settings_theme_cb'):
                self.settings_theme_cb.blockSignals(True)
                self.settings_theme_cb.setCurrentText(name)
                self.settings_theme_cb.blockSignals(False)

    def _fmt_anim(self, ms):
        if ms == 0:   return "Instant"
        if ms <= 100: return f"Fast ({ms}ms)"
        if ms <= 350: return f"Normal ({ms}ms)"
        return f"Slow ({ms}ms)"

    def _update_anim_speed(self, raw_val):
        val = 600 - raw_val
        self.board_widget.anim_speed = val
        
        self.anim_lbl.setText(self._fmt_anim(val))
        self.anim_slider.blockSignals(True)
        self.anim_slider.setValue(raw_val)
        self.anim_slider.blockSignals(False)
        
        if hasattr(self, 'settings_anim_slider'):
            self.settings_anim_lbl.setText(self._fmt_anim(val))
            self.settings_anim_slider.blockSignals(True)
            self.settings_anim_slider.setValue(raw_val)
            self.settings_anim_slider.blockSignals(False)

    # ── Thread-safe data loading ─────────────────────────────────────────────

    def _start_data_load(self, db_type, single_file=None):
        if db_type == "puzzles":
            self.puzzle_list.clear()
            self.puzzle_list.add_checkable_item("Loading puzzles…", checked=False)
            self.puzzles_loaded = False
        else:
            self.opening_list.clear()
            self.opening_list.add_checkable_item("Loading openings…", checked=False)
            self.openings_loaded = False

        if single_file:
            worker = DataLoadWorker(db_type, single_file=single_file)
        else:
            directory = str(Path(DATA_DIR) / db_type)
            worker = DataLoadWorker(db_type, directory=directory)

        worker.setObjectName(f"DataLoadWorker_{db_type}")  # Fix: Name the thread
        worker.data_ready.connect(self._on_data_ready)
        worker.load_error.connect(self._on_load_error)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._active_workers.append(worker)
        worker.start()

    def _on_data_ready(self, db_type, total_count):
        if db_type == "puzzles":
            self.puzzles_loaded = True
            self._pz_checked.clear()
            self._pz_page = 0
            self._populate_puzzle_page()
            self.puzzle_db_status.setText(f"Loaded {total_count:,} puzzles")
        else:
            self.openings_loaded = True
            self._op_checked.clear()
            self._op_page = 0
            self._populate_opening_page()
            self.opening_db_status.setText(f"Loaded {total_count:,} openings")

    def _on_load_error(self, db_type, error_msg):
        log(f"Load error ({db_type}): {error_msg}", "DATA")
        if db_type == "puzzles":
            self.puzzle_db_status.setText(f"Error: {error_msg}")
        else:
            self.opening_db_status.setText(f"Error: {error_msg}")

    def _cleanup_worker(self, worker):
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        if not worker.isRunning():
            worker.deleteLater()
        else:
            worker.finished.connect(worker.deleteLater)

    # ══════════════════════════════════════════════════════════════════════════
    #  PUZZLE TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _build_puzzle_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        l = QVBoxLayout(container)
        l.setSpacing(12)

        # ── 1. Database ──────────────────────────────────────────────────
        db_group = QGroupBox("📂 Puzzle Database")
        db_layout = QHBoxLayout(db_group)
        btn_load_db = QPushButton("Load DB…")
        btn_load_db.clicked.connect(self.load_puzzle_db)
        db_layout.addWidget(btn_load_db)
        self.puzzle_db_status = QLabel("No database loaded")
        self.puzzle_db_status.setAlignment(Qt.AlignCenter)
        db_layout.addWidget(self.puzzle_db_status, 1)
        l.addWidget(db_group)

        # ── 2. Filter & Selection ────────────────────────────────────────
        filter_group = QGroupBox("🔍 Filter & Selection")
        fl = QVBoxLayout(filter_group)
        
        filter_row = QHBoxLayout()
        self.puzzle_filter = QLineEdit()
        self.puzzle_filter.setPlaceholderText("Filter puzzles…")
        filter_row.addWidget(self.puzzle_filter, 1)
        fl.addLayout(filter_row)

        self._pz_filter_timer = QTimer()
        self._pz_filter_timer.setSingleShot(True)
        self._pz_filter_timer.setInterval(300)
        self._pz_filter_timer.timeout.connect(self._apply_puzzle_filter)
        self.puzzle_filter.textChanged.connect(lambda: self._pz_filter_timer.start())

        sel_row = QHBoxLayout()
        btn_all = QPushButton("All"); btn_all.setFixedWidth(55)
        btn_all.clicked.connect(self._puzzle_select_all)
        btn_none = QPushButton("None"); btn_none.setFixedWidth(55)
        btn_none.clicked.connect(self._puzzle_select_none)
        btn_inv = QPushButton("Invert"); btn_inv.setFixedWidth(60)
        btn_inv.clicked.connect(self._puzzle_select_invert)
        sel_row.addWidget(btn_all)
        sel_row.addWidget(btn_none)
        sel_row.addWidget(btn_inv)
        sel_row.addStretch()
        fl.addLayout(sel_row)

        range_row = QHBoxLayout()
        self.puzzle_range_from = QSpinBox()
        self.puzzle_range_from.setRange(1, 999999); self.puzzle_range_from.setPrefix("#")
        self.puzzle_range_to = QSpinBox()
        self.puzzle_range_to.setRange(1, 999999); self.puzzle_range_to.setPrefix("#")
        btn_range = QPushButton("Apply Range")
        btn_range.clicked.connect(self._puzzle_select_range)
        range_row.addWidget(QLabel("From:")); range_row.addWidget(self.puzzle_range_from)
        range_row.addWidget(QLabel("To:")); range_row.addWidget(self.puzzle_range_to)
        range_row.addWidget(btn_range)
        fl.addLayout(range_row)
        
        self.puzzle_sel_label = QLabel("Selected: 0")
        self.puzzle_sel_label.setAlignment(Qt.AlignRight)
        fl.addWidget(self.puzzle_sel_label)
        
        l.addWidget(filter_group)

        # ── 3. Puzzle List ───────────────────────────────────────────────
        list_group = QGroupBox("📋 Puzzles")
        ll = QVBoxLayout(list_group)
        
        self.puzzle_list = CheckableListWidget()
        self.puzzle_list.setMaximumHeight(160)
        self.puzzle_list.itemChanged.connect(self._on_puzzle_item_changed)
        ll.addWidget(self.puzzle_list)

        nav = QHBoxLayout()
        self.btn_pz_prev = QPushButton("◀")
        self.btn_pz_prev.clicked.connect(self._pz_prev_page)
        self.pz_page_lbl = QLabel("Page 0 / 0")
        self.pz_page_lbl.setAlignment(Qt.AlignCenter)
        self.btn_pz_next = QPushButton("▶")
        self.btn_pz_next.clicked.connect(self._pz_next_page)
        nav.addWidget(self.btn_pz_prev)
        nav.addWidget(self.pz_page_lbl, 1)
        nav.addWidget(self.btn_pz_next)
        nav.addWidget(QLabel("Jump:"))
        self.pz_jump_spin = QSpinBox()
        self.pz_jump_spin.setRange(1, 999999); self.pz_jump_spin.setFixedWidth(65)
        btn_jump = QPushButton("Go"); btn_jump.setFixedWidth(35)
        btn_jump.clicked.connect(self._pz_jump_page)
        nav.addWidget(self.pz_jump_spin)
        nav.addWidget(btn_jump)
        ll.addLayout(nav)

        btn_load = QPushButton("📋 Load Selected Puzzle to Board")
        btn_load.clicked.connect(self.load_puzzle)
        ll.addWidget(btn_load)
        
        l.addWidget(list_group)

        # ── 4. Export Settings ───────────────────────────────────────────
        export_group = QGroupBox("🎬 Export Configuration")
        eform = QFormLayout(export_group)
        eform.setSpacing(8)

        self.exp_title = QLineEdit()
        self.exp_title.setPlaceholderText("Leave blank for puzzle name")
        eform.addRow("Title:", self.exp_title)

        self.exp_end = QLineEdit("Solved!")
        eform.addRow("End text:", self.exp_end)

        row_fps = QHBoxLayout()
        self.exp_fps = QSpinBox(); self.exp_fps.setRange(10, 120); self.exp_fps.setValue(30)
        self.exp_workers = QSpinBox(); self.exp_workers.setRange(1, 16); self.exp_workers.setValue(4)
        row_fps.addWidget(self.exp_fps); row_fps.addWidget(QLabel("Workers:")); row_fps.addWidget(self.exp_workers)
        eform.addRow("FPS:", row_fps)

        row_theme = QHBoxLayout()
        self.exp_theme = QComboBox(); self.exp_theme.addItems(THEMES.keys())
        self.exp_theme.setCurrentText(self.theme_cb.currentText())
        row_theme.addWidget(self.exp_theme)
        eform.addRow("Theme:", row_theme)

        row_out = QHBoxLayout()
        self.exp_outdir = QLineEdit()
        self.exp_outdir.setPlaceholderText("Output directory…")
        btn_browse = QPushButton("📁"); btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse_export_dir)
        row_out.addWidget(self.exp_outdir, 1); row_out.addWidget(btn_browse)
        eform.addRow("Output:", row_out)

        self.exp_gpu = QCheckBox("GPU post-process")
        self.exp_gpu.setChecked(HAS_CUPY); self.exp_gpu.setEnabled(HAS_CUPY)
        eform.addRow(self.exp_gpu)

        row_gpu1 = QHBoxLayout()
        self.exp_vignette = QSlider(Qt.Horizontal); self.exp_vignette.setRange(0, 100); self.exp_vignette.setValue(25)
        self.exp_vignette_lbl = QLabel("0.25")
        self.exp_vignette.valueChanged.connect(lambda v: self.exp_vignette_lbl.setText(f"{v/100:.2f}"))
        row_gpu1.addWidget(self.exp_vignette, 1); row_gpu1.addWidget(self.exp_vignette_lbl)
        eform.addRow("Vignette:", row_gpu1)

        row_gpu2 = QHBoxLayout()
        self.exp_contrast = QSlider(Qt.Horizontal); self.exp_contrast.setRange(80, 150); self.exp_contrast.setValue(102)
        self.exp_contrast_lbl = QLabel("1.02")
        self.exp_contrast.valueChanged.connect(lambda v: self.exp_contrast_lbl.setText(f"{v/100:.2f}"))
        row_gpu2.addWidget(self.exp_contrast, 1); row_gpu2.addWidget(self.exp_contrast_lbl)
        eform.addRow("Contrast:", row_gpu2)

        row_gpu3 = QHBoxLayout()
        self.exp_saturation = QSlider(Qt.Horizontal); self.exp_saturation.setRange(80, 150); self.exp_saturation.setValue(105)
        self.exp_saturation_lbl = QLabel("1.05")
        self.exp_saturation.valueChanged.connect(lambda v: self.exp_saturation_lbl.setText(f"{v/100:.2f}"))
        row_gpu3.addWidget(self.exp_saturation, 1); row_gpu3.addWidget(self.exp_saturation_lbl)
        eform.addRow("Saturation:", row_gpu3)

        l.addWidget(export_group)

        # ── 5. Export Actions ────────────────────────────────────────────
        action_group = QGroupBox("🚀 Export Actions")
        al = QVBoxLayout(action_group)
        
        exp_btns = QHBoxLayout()
        self.btn_export_current = QPushButton("Current")
        self.btn_export_current.clicked.connect(self._export_current_puzzle)
        self.btn_export_selected = QPushButton("Selected")
        self.btn_export_selected.clicked.connect(self._export_selected_batch)
        self.btn_export_all = QPushButton("All")
        self.btn_export_all.clicked.connect(self._export_all_batch)
        exp_btns.addWidget(self.btn_export_current)
        exp_btns.addWidget(self.btn_export_selected)
        exp_btns.addWidget(self.btn_export_all)
        al.addLayout(exp_btns)

        self.puzzle_progress = QProgressBar()
        self.puzzle_progress.setRange(0, 100); self.puzzle_progress.setValue(0)
        al.addWidget(self.puzzle_progress)

        self.puzzle_status = QLabel("")
        al.addWidget(self.puzzle_status)

        self.btn_cancel_export = QPushButton("✕ Cancel Export")
        self.btn_cancel_export.clicked.connect(self._cancel_export)
        self.btn_cancel_export.setEnabled(False)
        al.addWidget(self.btn_cancel_export)
        
        l.addWidget(action_group)

        self.puzzle_info = QTextEdit(); self.puzzle_info.setReadOnly(True)
        self.puzzle_info.setMaximumHeight(50)
        l.addWidget(self.puzzle_info)

        l.addStretch()
        scroll.setWidget(container)
        self.tabs.addTab(scroll, "🧩 Puzzles")

    # ── Puzzle pagination helpers ─────────────────────────────────────────

    def _pz_total_items(self):
        return self.db.get_count('puzzles', self.puzzle_filter.text().strip())

    def _pz_page_count(self):
        return max(1, math.ceil(self._pz_total_items() / self._PAGE_SIZE))

    def _populate_puzzle_page(self):
        self.puzzle_list.blockSignals(True)
        self.puzzle_list.clear()

        filter_text = self.puzzle_filter.text().strip()
        items = self.db.get_page('puzzles', self._pz_page, self._PAGE_SIZE, filter_text)

        for item in items:
            di = item['id']
            checked = di in self._pz_checked
            list_item = self.puzzle_list.add_checkable_item(
                item["name"], data=item, checked=checked)
            list_item.setData(Qt.UserRole + 1, di)

        self.puzzle_list.blockSignals(False)
        self._update_puzzle_nav()
        self._update_puzzle_sel_label()

    def _update_puzzle_nav(self):
        total = self._pz_total_items()
        pc = max(1, math.ceil(total / self._PAGE_SIZE))
        self.pz_page_lbl.setText(f"Page {self._pz_page + 1} / {pc}  ({total:,} items)")
        self.btn_pz_prev.setEnabled(self._pz_page > 0)
        self.btn_pz_next.setEnabled(self._pz_page < pc - 1)
        self.pz_jump_spin.setRange(1, pc)
        self.pz_jump_spin.setValue(self._pz_page + 1)
        count = self.db.get_count('puzzles')
        self.puzzle_range_from.setRange(1, max(1, count))
        self.puzzle_range_to.setRange(1, max(1, count))

    def _update_puzzle_sel_label(self, _item=None):
        cnt = len(self._pz_checked)
        total = self.db.get_count('puzzles')
        self.puzzle_sel_label.setText(f"Selected: {cnt:,} / {total:,}")

    def _on_puzzle_item_changed(self, item):
        di = item.data(Qt.UserRole + 1)
        if di is None: return
        if item.checkState() == Qt.Checked:
            self._pz_checked.add(di)
        else:
            self._pz_checked.discard(di)
        self._update_puzzle_sel_label()

    def _apply_puzzle_filter(self):
        self._pz_page = 0
        self._populate_puzzle_page()

    def _puzzle_select_all(self):
        filter_text = self.puzzle_filter.text().strip()
        self._pz_checked = set(self.db.get_ids_by_filter('puzzles', filter_text))
        self._populate_puzzle_page()

    def _puzzle_select_none(self):
        self._pz_checked.clear()
        self._populate_puzzle_page()

    def _puzzle_select_invert(self):
        filter_text = self.puzzle_filter.text().strip()
        all_ids = set(self.db.get_ids_by_filter('puzzles', filter_text))
        self._pz_checked = all_ids - self._pz_checked
        self._populate_puzzle_page()

    def _puzzle_select_range(self):
        start = self.puzzle_range_from.value()
        end = self.puzzle_range_to.value()
        if start > end: start, end = end, start
        for i in range(start, end + 1):
            self._pz_checked.add(i)
        self._populate_puzzle_page()

    def _pz_prev_page(self):
        if self._pz_page > 0:
            self._pz_page -= 1
            self._populate_puzzle_page()

    def _pz_next_page(self):
        if self._pz_page < self._pz_page_count() - 1:
            self._pz_page += 1
            self._populate_puzzle_page()

    def _pz_jump_page(self):
        page = self.pz_jump_spin.value() - 1
        if 0 <= page < self._pz_page_count():
            self._pz_page = page
            self._populate_puzzle_page()

    # ── Build export config ──────────────────────────────────────────────────

    def _build_export_config(self, puzzle_name=""):
        cfg = ExportConfig()
        title_text = self.exp_title.text().strip()
        cfg.title_text = title_text if title_text else puzzle_name
        cfg.end_text = self.exp_end.text()
        cfg.fps = self.exp_fps.value()
        cfg.max_workers = self.exp_workers.value()
        cfg.theme_name = self.exp_theme.currentText()
        cfg.output_dir = self.exp_outdir.text().strip()
        cfg.gpu_post_process = self.exp_gpu.isChecked()
        cfg.gpu_vignette = self.exp_vignette.value() / 100.0
        cfg.gpu_contrast = self.exp_contrast.value() / 100.0
        cfg.gpu_saturation = self.exp_saturation.value() / 100.0
        return cfg

    def _ensure_output_dir(self):
        d = self.exp_outdir.text().strip()
        if not d:
            d = self.settings_outdir.text().strip() if hasattr(self, 'settings_outdir') else ""
        if not d:
            d = str(Path(DATA_DIR) / "exports")
            self.exp_outdir.setText(d)
            if hasattr(self, 'settings_outdir'):
                self.settings_outdir.setText(d)
        os.makedirs(d, exist_ok=True)
        return d

    def _browse_export_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.exp_outdir.setText(d)

    # ── Export: current puzzle ────────────────────────────────────────────────

    def _export_current_puzzle(self):
        item = self.puzzle_list.currentItem()
        if not item:
            self.puzzle_status.setText("No puzzle selected."); return
        pz = item.data(Qt.UserRole)
        if not pz:
            self.puzzle_status.setText("No puzzle data."); return

        pz_copy = dict(pz)
        pz_copy['display_title'] = f"Puzzle #{pz_copy['id']}"

        out_dir = self._ensure_output_dir()
        from constants import sanitize_filename
        filename = sanitize_filename(pz_copy['name']) + ".mp4"
        filepath = os.path.join(out_dir, filename)

        if os.path.exists(filepath):
            base = sanitize_filename(pz_copy['name'])
            i = 2
            while os.path.exists(os.path.join(out_dir, f"{base}_{i}.mp4")):
                i += 1
            filepath = os.path.join(out_dir, f"{base}_{i}.mp4")

        cfg = self._build_export_config(pz_copy.get('display_title', pz_copy['name']))
        log(f"Exporting current puzzle: {pz_copy['name']} -> {filepath}", "EXPORT")
        self._set_exporting(True)
        self.export_worker = ExportWorker(pz_copy, filepath, cfg)
        self.export_worker.start()

    def _export_selected_batch(self):
        if not self._pz_checked:
            self.puzzle_status.setText("No puzzles checked for batch export."); return
            
        puzzles = self.db.get_items_by_ids('puzzles', list(self._pz_checked))
        
        for p in puzzles:
            p['display_title'] = f"Puzzle #{p['id']}"
            
        self._start_batch_export(puzzles)

    def _export_all_batch(self):
        total = self.db.get_count('puzzles')
        if total == 0:
            self.puzzle_status.setText("No puzzles loaded."); return
            
        all_ids = self.db.get_ids_by_filter('puzzles')
        puzzles = self.db.get_items_by_ids('puzzles', all_ids)
        
        for p in puzzles:
            p['display_title'] = f"Puzzle #{p['id']}"
            
        self._start_batch_export(puzzles)

    def _on_single_progress(self, pct):
        self.puzzle_progress.setValue(pct)
        self.puzzle_status.setText(f"Rendering… {pct}%")

    def _on_single_finished(self, msg):
        self.puzzle_status.setText(msg)
        self.puzzle_progress.setValue(100 if "Saved" in msg else 0)
        self._set_exporting(False)
        if self.export_worker:
            self.export_worker.deleteLater()
            self.export_worker = None

    # ── Export: batch ─────────────────────────────────────────────────────────

    def _start_batch_export(self, puzzles):
        out_dir = self._ensure_output_dir()
        cfg = self._build_export_config()
        total = len(puzzles)
        log(f"Starting batch export: {total} puzzles -> {out_dir}", "EXPORT")
        self._set_exporting(True, batch=True)
        self.puzzle_progress.setValue(0)
        self.puzzle_status.setText(f"Batch: 0 / {total}")
        
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.abort()
            self.batch_worker.wait(3000)
            
        self.batch_worker = BatchExportWorker(puzzles, out_dir, cfg)
        self.batch_worker.batch_progress.connect(self._on_batch_progress)
        self.batch_worker.puzzle_progress.connect(self._on_batch_puzzle_progress)
        self.batch_worker.puzzle_done.connect(self._on_batch_puzzle_done)
        self.batch_worker.puzzle_error.connect(self._on_batch_puzzle_error)
        self.batch_worker.all_done.connect(self._on_batch_all_done)
        self.batch_worker.start()

    def _on_batch_progress(self, idx, total, name):
        pct = int(100 * (idx + 1) / total) if total > 0 else 0
        self.puzzle_progress.setValue(pct)
        self.puzzle_status.setText(f"Batch [{idx+1}/{total}]: {name}")

    def _on_batch_puzzle_progress(self, idx, pct):
        pass

    def _on_batch_puzzle_done(self, idx, filepath):
        log(f"Batch puzzle done: {filepath}", "EXPORT")

    def _on_batch_puzzle_error(self, idx, msg):
        log(f"Batch puzzle error: {msg}", "EXPORT")

    def _on_batch_all_done(self, exported, errors, out_dir):
        self.puzzle_progress.setValue(100)
        self.puzzle_status.setText(
            f"Batch done: {exported} exported, {errors} errors → {out_dir}")
        self._set_exporting(False, batch=True)
        if self.batch_worker:
            self.batch_worker.deleteLater()
            self.batch_worker = None

    # ── Cancel / UI state ────────────────────────────────────────────────────

    def _cancel_export(self):
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.abort()
            self.puzzle_status.setText("Cancelling single export…")
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.abort()
            self.puzzle_status.setText("Cancelling batch export…")

    def _set_exporting(self, busy, batch=False):
        self.btn_export_current.setEnabled(not busy)
        self.btn_export_selected.setEnabled(not busy)
        self.btn_export_all.setEnabled(not busy)
        self.btn_cancel_export.setEnabled(busy)

    # ── Load puzzle DB ───────────────────────────────────────────────────────

    def load_puzzle_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Puzzle Database", "",
            "Supported (*.csv *.parquet *.duckdb *.db *.sqlite)")
        if not path: return
        self.puzzle_db_status.setText("Loading…")
        self._start_data_load("puzzles", single_file=path)

    # ── Load puzzle to board ─────────────────────────────────────────────────

    def load_puzzle(self):
        item = self.puzzle_list.currentItem()
        if not item: return
        pz = item.data(Qt.UserRole)
        if not pz: return
        if pz.get("fen"):
            self.engine.load_fen(pz["fen"])
        else:
            self.engine.reset()
        self.puzzle_info.setText(pz.get("desc", ""))
        self.board_widget.selected = None
        self.board_widget.legal_targets = []
        self.board_widget.update()
        self.snd.play("start")

    # ══════════════════════════════════════════════════════════════════════════
    #  SETTINGS TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _build_settings_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        l = QVBoxLayout(container)
        l.setSpacing(12)

        # ── Appearance ──────────────────────────────────────────────────
        appear_group = QGroupBox("🎨 Appearance")
        aform = QFormLayout(appear_group)

        self.settings_theme_cb = QComboBox()
        self.settings_theme_cb.addItems(THEMES.keys())
        self.settings_theme_cb.currentTextChanged.connect(self._change_theme)
        aform.addRow("Theme:", self.settings_theme_cb)

        row_anim = QHBoxLayout()
        self.settings_anim_slider = QSlider(Qt.Horizontal)
        self.settings_anim_slider.setRange(0, 600)
        self.settings_anim_slider.setValue(600 - ANIM_SPEED_DEFAULT)
        self.settings_anim_slider.setInvertedAppearance(True)
        self.settings_anim_lbl = QLabel(self._fmt_anim(ANIM_SPEED_DEFAULT))
        self.settings_anim_slider.valueChanged.connect(self._update_anim_speed)
        row_anim.addWidget(self.settings_anim_slider, 1)
        row_anim.addWidget(self.settings_anim_lbl)
        aform.addRow("Anim Speed:", row_anim)

        l.addWidget(appear_group)

        # ── Export Default Path ──────────────────────────────────────────
        path_group = QGroupBox("📁 Default Export Path")
        pl = QHBoxLayout(path_group)
        self.settings_outdir = QLineEdit(str(Path(DATA_DIR) / "exports"))
        btn_browse = QPushButton("📁"); btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(lambda: self.settings_outdir.setText(
            QFileDialog.getExistingDirectory(self, "Select Default Export Directory") or self.settings_outdir.text()))
        pl.addWidget(self.settings_outdir, 1)
        pl.addWidget(btn_browse)
        l.addWidget(path_group)

        l.addStretch()
        scroll.setWidget(container)
        self.tabs.addTab(scroll, "⚙️ Settings")