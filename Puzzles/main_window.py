"""Main application window — batch-enabled, no popups.
Paginated lists for databases of millions of rows.
Checked state tracked in sets (O(1) cross-page operations).
Debounced filter for responsive search on huge datasets.
Professional layout with grouped sections and dedicated settings tab.
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
from PySide6.QtCore import Qt, QTimer, QThread
from PySide6.QtGui import QFont, QPixmap
from constants import (
    log, ExportConfig, ANIM_SPEED_DEFAULT, ANIM_SPEED_SLOW,
    DATA_DIR, THEMES, HAS_CUPY, HAS_NUMBA
)
from engine import ChessEngine
from sound import SoundManager
from board_widget import ChessBoardWidget
from export import ExportWorker, BatchExportWorker
from data_manager import DataLoadWorker


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

class MainWindow(QWidget):
    _PAGE_SIZE = 100

    def __init__(self):
        super().__init__()
        self.setWindowTitle("♚ Chess Learning App")
        log("Initializing Chess Learning App...", "APP")

        self._apply_professional_style()

        self.engine = ChessEngine()
        self.snd = SoundManager()
        self.board_widget = ChessBoardWidget(self.engine, self.snd)
        self.board_widget.move_made.connect(self.on_move)

        self.opening_data = []
        self.opening_step_idx = 0
        self.puzzle_data = []
        self.export_worker = None
        self.batch_worker = None
        self.puzzles_loaded = False
        self.openings_loaded = False
        self._active_workers = []

        self._pz_page = 0
        self._pz_checked = set()
        self._pz_filtered = None

        self._op_page = 0
        self._op_checked = set()
        self._op_filtered = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.setFixedWidth(460)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        board_frame = QFrame()
        board_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        board_frame.setStyleSheet("QFrame { border: 1px solid #4a4a4f; border-radius: 6px; background: #25252a; }")
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
        self._build_openings_tab()
        self._build_settings_tab()

        self.snd.play("start")
        log("App initialization complete", "APP")

        QTimer.singleShot(50,  lambda: self._start_data_load("puzzles"))
        QTimer.singleShot(100, lambda: self._start_data_load("openings"))

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

    def _on_tab_changed(self, index):
        pass

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
        # Use deleteLater so the worker is only destroyed after its event
        # processing is fully complete — never while run() is executing.
        if not worker.isRunning():
            worker.deleteLater()
        else:
            # Safety: schedule deletion once the thread actually finishes
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

        # Create a copy so we don't mutate the cached data
        pz_copy = dict(pz)
        # Use the exact database ID for the title screen
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
        self.export_worker.progress.connect(self._on_single_progress)
        self.export_worker.finished.connect(self._on_single_finished)
        self.export_worker.start()

    def _export_selected_batch(self):
        if not self._pz_checked:
            self.puzzle_status.setText("No puzzles checked for batch export."); return
            
        puzzles = self.db.get_items_by_ids('puzzles', list(self._pz_checked))
        
        # Assign exact database ID to title screen
        for p in puzzles:
            p['display_title'] = f"Puzzle #{p['id']}"
            
        self._start_batch_export(puzzles)

    def _export_all_batch(self):
        total = self.db.get_count('puzzles')
        if total == 0:
            self.puzzle_status.setText("No puzzles loaded."); return
            
        # Fetch IDs in chunks so we don't RAM-spike
        all_ids = self.db.get_ids_by_filter('puzzles')
        puzzles = self.db.get_items_by_ids('puzzles', all_ids)
        
        # Assign exact database ID to title screen
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

    def _export_selected_batch(self):
        puzzles = []
        for i in sorted(self._pz_checked):
            if i < len(self.puzzle_data):
                pz = self.puzzle_data[i]
                pz_copy = dict(pz)
                # Extract just "Puzzle #X" for the title screen
                pz_copy['display_title'] = pz_copy['name'].split(' — ')[0] if ' — ' in pz_copy['name'] else pz_copy['name']
                puzzles.append(pz_copy)
                
        if not puzzles:
            self.puzzle_status.setText("No puzzles checked for batch export."); return
        self._start_batch_export(puzzles)

    def _export_all_batch(self):
        if not self.puzzle_data:
            self.puzzle_status.setText("No puzzles loaded."); return
        
        puzzles = []
        for pz in self.puzzle_data:
            pz_copy = dict(pz)
            # Extract just "Puzzle #X" for the title screen
            pz_copy['display_title'] = pz_copy['name'].split(' — ')[0] if ' — ' in pz_copy['name'] else pz_copy['name']
            puzzles.append(pz_copy)
            
        self._start_batch_export(puzzles)

    def _start_batch_export(self, puzzles):
        out_dir = self._ensure_output_dir()
        cfg = self._build_export_config()
        total = len(puzzles)
        log(f"Starting batch export: {total} puzzles -> {out_dir}", "EXPORT")
        self._set_exporting(True, batch=True)
        self.puzzle_progress.setValue(0)
        self.puzzle_status.setText(f"Batch: 0 / {total}")
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
    #  OPENINGS TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _build_openings_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        l = QVBoxLayout(container)
        l.setSpacing(12)

        # ── 1. Database ──────────────────────────────────────────────────
        db_group = QGroupBox("📂 Openings Database")
        db_layout = QHBoxLayout(db_group)
        btn_load_db = QPushButton("Load Openings DB…")
        btn_load_db.clicked.connect(self.load_openings_db)
        db_layout.addWidget(btn_load_db)
        self.opening_db_status = QLabel("No database loaded")
        self.opening_db_status.setAlignment(Qt.AlignCenter)
        db_layout.addWidget(self.opening_db_status, 1)
        l.addWidget(db_group)

        # ── 2. Filter & Selection ────────────────────────────────────────
        filter_group = QGroupBox("🔍 Filter & Selection")
        fl = QVBoxLayout(filter_group)
        
        filter_row = QHBoxLayout()
        self.opening_filter = QLineEdit()
        self.opening_filter.setPlaceholderText("Filter openings…")
        filter_row.addWidget(self.opening_filter, 1)
        fl.addLayout(filter_row)

        self._op_filter_timer = QTimer()
        self._op_filter_timer.setSingleShot(True)
        self._op_filter_timer.setInterval(300)
        self._op_filter_timer.timeout.connect(self._apply_opening_filter)
        self.opening_filter.textChanged.connect(lambda: self._op_filter_timer.start())

        sel_row = QHBoxLayout()
        btn_all = QPushButton("All"); btn_all.setFixedWidth(55)
        btn_all.clicked.connect(self._opening_select_all)
        btn_none = QPushButton("None"); btn_none.setFixedWidth(55)
        btn_none.clicked.connect(self._opening_select_none)
        btn_inv = QPushButton("Invert"); btn_inv.setFixedWidth(60)
        btn_inv.clicked.connect(self._opening_select_invert)
        sel_row.addWidget(btn_all); sel_row.addWidget(btn_none); sel_row.addWidget(btn_inv)
        sel_row.addStretch()
        fl.addLayout(sel_row)

        range_row = QHBoxLayout()
        self.opening_range_from = QSpinBox()
        self.opening_range_from.setRange(1, 999999); self.opening_range_from.setPrefix("#")
        self.opening_range_to = QSpinBox()
        self.opening_range_to.setRange(1, 999999); self.opening_range_to.setPrefix("#")
        btn_range = QPushButton("Apply Range")
        btn_range.clicked.connect(self._opening_select_range)
        range_row.addWidget(QLabel("From:")); range_row.addWidget(self.opening_range_from)
        range_row.addWidget(QLabel("To:")); range_row.addWidget(self.opening_range_to)
        range_row.addWidget(btn_range)
        fl.addLayout(range_row)
        
        self.opening_sel_label = QLabel("Selected: 0")
        self.opening_sel_label.setAlignment(Qt.AlignRight)
        fl.addWidget(self.opening_sel_label)
        
        l.addWidget(filter_group)

        # ── 3. Openings List ─────────────────────────────────────────────
        list_group = QGroupBox("📚 Openings List")
        ll = QVBoxLayout(list_group)
        
        self.opening_list = CheckableListWidget()
        self.opening_list.setMaximumHeight(130)
        self.opening_list.currentRowChanged.connect(self.select_opening)
        self.opening_list.itemChanged.connect(self._on_opening_item_changed)
        ll.addWidget(self.opening_list)

        nav = QHBoxLayout()
        self.btn_op_prev = QPushButton("◀")
        self.btn_op_prev.clicked.connect(self._op_prev_page)
        self.op_page_lbl = QLabel("Page 0 / 0")
        self.op_page_lbl.setAlignment(Qt.AlignCenter)
        self.btn_op_next = QPushButton("▶")
        self.btn_op_next.clicked.connect(self._op_next_page)
        nav.addWidget(self.btn_op_prev); nav.addWidget(self.op_page_lbl, 1)
        nav.addWidget(self.btn_op_next)
        nav.addWidget(QLabel("Jump:"))
        self.op_jump_spin = QSpinBox(); self.op_jump_spin.setRange(1, 999999); self.op_jump_spin.setFixedWidth(65)
        btn_op_jump = QPushButton("Go"); btn_op_jump.setFixedWidth(35)
        btn_op_jump.clicked.connect(self._op_jump_page)
        nav.addWidget(self.op_jump_spin); nav.addWidget(btn_op_jump)
        ll.addLayout(nav)
        
        l.addWidget(list_group)

        # ── 4. Opening Detail ────────────────────────────────────────────
        detail_group = QGroupBox("♟ Opening Detail")
        dl = QVBoxLayout(detail_group)
        
        self.opening_img_lbl = QLabel("Opening Image")
        self.opening_img_lbl.setFixedSize(220, 220)
        self.opening_img_lbl.setAlignment(Qt.AlignCenter)
        self.opening_img_lbl.setStyleSheet(
            "background-color: #2b2b2b; border: 1px solid #555; border-radius: 4px;")
        dl.addWidget(self.opening_img_lbl, alignment=Qt.AlignCenter)

        step_layout = QHBoxLayout()
        step_layout.addStretch()
        btn_start = QPushButton("⏮"); btn_start.clicked.connect(self.opening_start)
        btn_prev = QPushButton("◀ Prev"); btn_prev.clicked.connect(self.opening_prev)
        btn_next = QPushButton("Next ▶"); btn_next.clicked.connect(self.opening_next)
        btn_end = QPushButton("⏭"); btn_end.clicked.connect(self.opening_end)
        step_layout.addWidget(btn_start); step_layout.addWidget(btn_prev)
        step_layout.addWidget(btn_next); step_layout.addWidget(btn_end)
        step_layout.addStretch()
        dl.addLayout(step_layout)

        self.opening_moves_te = QTextEdit(); self.opening_moves_te.setReadOnly(True)
        self.opening_moves_te.setFont(QFont("Courier", 13))
        self.opening_moves_te.setMaximumHeight(80)
        dl.addWidget(self.opening_moves_te)
        
        l.addWidget(detail_group)

        # ── 5. Export ────────────────────────────────────────────────────
        export_group = QGroupBox("🎬 Export Openings")
        el = QVBoxLayout(export_group)
        
        batch_row = QHBoxLayout()
        btn_exp_sel = QPushButton("Export Selected")
        btn_exp_sel.clicked.connect(self._export_openings_batch)
        btn_exp_all = QPushButton("Export All")
        btn_exp_all.clicked.connect(self._export_all_openings_batch)
        batch_row.addWidget(btn_exp_sel); batch_row.addWidget(btn_exp_all)
        el.addLayout(batch_row)

        self.opening_progress = QProgressBar()
        self.opening_progress.setRange(0, 100); self.opening_progress.setValue(0)
        el.addWidget(self.opening_progress)

        self.opening_status = QLabel("")
        self.opening_status.setWordWrap(True)
        el.addWidget(self.opening_status)
        
        l.addWidget(export_group)

        l.addStretch()
        scroll.setWidget(container)
        self.tabs.addTab(scroll, "📚 Openings")

    # ── Opening pagination helpers ────────────────────────────────────────

    def _op_total_items(self):
        return self.db.get_count('openings', self.opening_filter.text().strip())

    def _op_page_count(self):
        return max(1, math.ceil(self._op_total_items() / self._PAGE_SIZE))

    def _populate_opening_page(self):
        self.opening_list.blockSignals(True)
        self.opening_list.clear()

        filter_text = self.opening_filter.text().strip()
        items = self.db.get_page('openings', self._op_page, self._PAGE_SIZE, filter_text)

        for item in items:
            di = item['id']
            checked = di in self._op_checked
            name = f"{item.get('eco', '')} - {item.get('name', '')}"
            list_item = self.opening_list.add_checkable_item(name, data=item, checked=checked)
            list_item.setData(Qt.UserRole + 1, di)

        self.opening_list.blockSignals(False)
        self._update_opening_nav()
        self._update_opening_sel_label()

    def _update_opening_nav(self):
        total = self._op_total_items()
        pc = max(1, math.ceil(total / self._PAGE_SIZE))
        self.op_page_lbl.setText(f"Page {self._op_page + 1} / {pc}  ({total:,} items)")
        self.btn_op_prev.setEnabled(self._op_page > 0)
        self.btn_op_next.setEnabled(self._op_page < pc - 1)
        self.op_jump_spin.setRange(1, pc)
        self.op_jump_spin.setValue(self._op_page + 1)
        count = self.db.get_count('openings')
        self.opening_range_from.setRange(1, max(1, count))
        self.opening_range_to.setRange(1, max(1, count))

    def _update_opening_sel_label(self, _item=None):
        cnt = len(self._op_checked)
        total = self.db.get_count('openings')
        self.opening_sel_label.setText(f"Selected: {cnt:,} / {total:,}")

    def _apply_opening_filter(self):
        self._op_page = 0
        self._populate_opening_page()

    def _opening_select_all(self):
        filter_text = self.opening_filter.text().strip()
        self._op_checked = set(self.db.get_ids_by_filter('openings', filter_text))
        self._populate_opening_page()

    def _opening_select_none(self):
        self._op_checked.clear()
        self._populate_opening_page()

    def _opening_select_invert(self):
        filter_text = self.opening_filter.text().strip()
        all_ids = set(self.db.get_ids_by_filter('openings', filter_text))
        self._op_checked = all_ids - self._op_checked
        self._populate_opening_page()

    def _opening_select_range(self):
        start = self.opening_range_from.value()
        end = self.opening_range_to.value()
        if start > end: start, end = end, start
        for i in range(start, end + 1): self._op_checked.add(i)
        self._populate_opening_page()

    # ── Opening selection helpers ─────────────────────────────────────────

    def _update_opening_sel_label(self, _item=None):
        cnt = len(self._op_checked)
        total = len(self.opening_data)
        self.opening_sel_label.setText(f"Selected: {cnt:,} / {total:,}")

    def _opening_select_all(self):
        if self._op_filtered is not None:
            self._op_checked.update(self._op_filtered)
        else:
            self._op_checked = set(range(len(self.opening_data)))
        self._populate_opening_page()

    def _opening_select_none(self):
        self._op_checked.clear()
        self._populate_opening_page()

    def _opening_select_invert(self):
        if self._op_filtered is not None:
            all_set = set(self._op_filtered)
        else:
            all_set = set(range(len(self.opening_data)))
        self._op_checked = all_set - self._op_checked
        self._populate_opening_page()

    def _opening_select_range(self):
        start = self.opening_range_from.value() - 1
        end = self.opening_range_to.value() - 1
        if start > end:
            start, end = end, start
        for i in range(start, end + 1):
            self._op_checked.add(i)
        self._populate_opening_page()

    # ── Opening batch export ─────────────────────────────────────────────────

    def _opening_to_puzzle(self, data):
        name = f"{data.get('eco', '')} - {data.get('name', '')}"
        return {
            'name': name,
            'display_title': data.get('display_title', name),
            'fen': self._opening_fen(data),
            'moves': data.get('uci_moves', []),
            'desc': data.get('pgn', ''),
        }

    def _export_openings_batch(self):
        if not self._op_checked:
            self.opening_status.setText("No openings checked for export."); return
        openings = self.db.get_items_by_ids('openings', list(self._op_checked))
        puzzles = [self._opening_to_puzzle(o) for o in openings]
        self._start_openings_batch_export(puzzles)

    def _export_all_openings_batch(self):
        total = self.db.get_count('openings')
        if total == 0:
            self.opening_status.setText("No openings loaded."); return
        all_ids = self.db.get_ids_by_filter('openings')
        openings = self.db.get_items_by_ids('openings', all_ids)
        puzzles = [self._opening_to_puzzle(o) for o in openings]
        self._start_openings_batch_export(puzzles)

    def _start_openings_batch_export(self, puzzles):
        out_dir = self._ensure_output_dir()
        cfg = self._build_export_config()
        total = len(puzzles)
        log(f"Starting openings batch export: {total} -> {out_dir}", "EXPORT")
        self.opening_progress.setValue(0)
        self.opening_status.setText(f"Batch: 0 / {total}")

        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.abort()
            self.batch_worker.wait(3000)

        self.batch_worker = BatchExportWorker(puzzles, out_dir, cfg)
        self.batch_worker.batch_progress.connect(self._on_opening_batch_progress)
        self.batch_worker.puzzle_done.connect(self._on_opening_batch_done)
        self.batch_worker.puzzle_error.connect(self._on_opening_batch_error)
        self.batch_worker.all_done.connect(self._on_opening_batch_all_done)
        self.batch_worker.start()

    def _on_opening_batch_progress(self, idx, total, name):
        pct = int(100 * (idx + 1) / total) if total > 0 else 0
        self.opening_progress.setValue(pct)
        self.opening_status.setText(f"Batch [{idx+1}/{total}]: {name}")

    def _on_opening_batch_done(self, idx, filepath):
        pass

    def _on_opening_batch_error(self, idx, msg):
        log(f"Opening export error: {msg}", "EXPORT")

    def _on_opening_batch_all_done(self, exported, errors, out_dir):
        self.opening_progress.setValue(100)
        self.opening_status.setText(
            f"Batch done: {exported} exported, {errors} errors → {out_dir}")
        if self.batch_worker:
            self.batch_worker.deleteLater()
            self.batch_worker = None

    def load_openings_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Openings Database", "",
            "Supported (*.csv *.parquet *.duckdb *.db *.sqlite)")
        if not path: return
        self.opening_db_status.setText("Loading…")
        self._start_data_load("openings", single_file=path)

    # ── Opening display / navigation ─────────────────────────────────────────

    def _opening_fen(self, data):
        fen = data['epd']
        if not fen:
            fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        if len(fen.split()) < 6:
            fen += " 0 1"
        return fen

    def select_opening(self, row):
        if row < 0: return
        item = self.opening_list.item(row)
        if not item: return
        di = item.data(Qt.UserRole + 1)
        if di is None: return
        
        # Fetch single item from DB
        items = self.db.get_items_by_ids('openings', [di])
        if not items: return
        data = items[0]
        
        self._current_opening_di = di
        self.opening_step_idx = 0
        self.engine.load_fen(self._opening_fen(data))
        
        # Parse image on demand from raw string
        img_raw = data.get('img_raw', '')
        img = parse_opening_image(img_raw) if img_raw else None
        
        if img and not img.isNull():
            pixmap = QPixmap.fromImage(img)
            self.opening_img_lbl.setPixmap(
                pixmap.scaled(210, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.opening_img_lbl.setText("No Image")
            
        self.board_widget.selected = None
        self.board_widget.legal_targets = []
        self.board_widget.update()
        self.update_opening_display()

    def update_opening_display(self):
        item = self.opening_list.currentItem()
        if not item: return
        di = item.data(Qt.UserRole + 1)
        if di is None or di >= len(self.opening_data): return
        data = self.opening_data[di]
        text = ""
        for i, uci in enumerate(data['uci_moves']):
            marker = f"<b><u>{uci}</u></b>" if i == self.opening_step_idx else uci
            text += marker + " "
            if (i + 1) % 2 == 0: text += "  "
        self.opening_moves_te.setHtml(text)

    def _get_current_opening_data(self):
        item = self.opening_list.currentItem()
        if not item: return None
        di = item.data(Qt.UserRole + 1)
        if di is None or di >= len(self.opening_data): return None
        return self.opening_data[di]

    def opening_start(self):
        self.opening_step_idx = 0
        data = self._get_current_opening_data()
        if not data: return
        self.engine.load_fen(self._opening_fen(data))
        self.board_widget.selected = None
        self.board_widget.legal_targets = []
        self.board_widget.update()
        self.update_opening_display()
        self.snd.play("move")

    def opening_prev(self):
        if self.opening_step_idx > 0:
            self.opening_step_idx -= 1
            data = self._get_current_opening_data()
            if not data: return
            self.engine.load_fen(self._opening_fen(data))
            for i in range(self.opening_step_idx):
                self.engine.make_move_uci(data['uci_moves'][i])
            self.board_widget.selected = None
            self.board_widget.legal_targets = []
            self.board_widget.update()
            self.update_opening_display()
            self.snd.play("move")

    def opening_next(self):
        if self.board_widget.animating: return
        data = self._get_current_opening_data()
        if not data: return
        if self.opening_step_idx < len(data['uci_moves']):
            uci = data['uci_moves'][self.opening_step_idx]
            info = self.engine.make_move_uci(uci)
            if info:
                sfx = ("capture" if info['captured'] != '.'
                       else "castle" if info['castle'] else "move")
                if info['mate']: sfx = "checkmate"
                elif info['check']: sfx = "check"
                self.snd.play(sfx)
                if self.board_widget.anim_speed > 0:
                    self.board_widget.start_animation(
                        info['from'][0], info['from'][1],
                        info['to'][0], info['to'][1],
                        info['piece_obj'], info['captured'], '')
                self.opening_step_idx += 1
            self.board_widget.selected = None
            self.board_widget.legal_targets = []
            self.update_opening_display()
            self.board_widget.update()

    def opening_end(self):
        data = self._get_current_opening_data()
        if not data: return
        self.engine.load_fen(self._opening_fen(data))
        for uci in data['uci_moves']:
            self.engine.make_move_uci(uci)
        self.opening_step_idx = len(data['uci_moves'])
        self.board_widget.selected = None
        self.board_widget.legal_targets = []
        self.board_widget.update()
        self.update_opening_display()
        self.snd.play("move")

    # ══════════════════════════════════════════════════════════════════════════
    #  SETTINGS TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _build_settings_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        l = QVBoxLayout(container)
        l.setSpacing(15)

        # ── 1. Appearance & Animation ────────────────────────────────────
        appear_group = QGroupBox("🎨 Appearance & Animation")
        a_form = QFormLayout(appear_group)
        
        self.settings_theme_cb = QComboBox()
        self.settings_theme_cb.addItems(THEMES.keys())
        self.settings_theme_cb.setCurrentText(self.theme_cb.currentText())
        self.settings_theme_cb.currentTextChanged.connect(self._change_theme)
        a_form.addRow("Board Theme:", self.settings_theme_cb)

        speed_row = QHBoxLayout()
        self.settings_anim_slider = QSlider(Qt.Horizontal)
        self.settings_anim_slider.setRange(0, 600)
        self.settings_anim_slider.setValue(600 - ANIM_SPEED_DEFAULT)
        self.settings_anim_slider.setInvertedAppearance(True)
        self.settings_anim_lbl = QLabel(self._fmt_anim(ANIM_SPEED_DEFAULT))
        self.settings_anim_slider.valueChanged.connect(self._update_anim_speed)
        speed_row.addWidget(self.settings_anim_slider, 1)
        speed_row.addWidget(self.settings_anim_lbl)
        a_form.addRow("Anim Speed:", speed_row)
        
        l.addWidget(appear_group)

        # ── 2. Sound ────────────────────────────────────────────────────
        sound_group = QGroupBox("🔊 Sound Settings")
        s_form = QFormLayout(sound_group)
        
        vol_row = QHBoxLayout()
        self.settings_volume_slider = QSlider(Qt.Horizontal)
        self.settings_volume_slider.setRange(0, 100)
        self.settings_volume_slider.setValue(int(self.snd._volume * 100))
        self.settings_volume_lbl = QLabel(f"{int(self.snd._volume * 100)}%")
        self.settings_volume_slider.valueChanged.connect(self._update_volume)
        vol_row.addWidget(self.settings_volume_slider, 1)
        vol_row.addWidget(self.settings_volume_lbl)
        s_form.addRow("Volume:", vol_row)

        self.settings_mute_cb = QCheckBox("Mute all sounds")
        self.settings_mute_cb.toggled.connect(self._toggle_mute)
        s_form.addRow(self.settings_mute_cb)
        
        l.addWidget(sound_group)

        # ── 3. Defaults ─────────────────────────────────────────────────
        default_group = QGroupBox("⚙️ Export Defaults")
        d_form = QFormLayout(default_group)
        
        row_out = QHBoxLayout()
        self.settings_outdir = QLineEdit()
        self.settings_outdir.setPlaceholderText("Default output directory…")
        btn_browse = QPushButton("📁"); btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse_settings_export_dir)
        row_out.addWidget(self.settings_outdir, 1); row_out.addWidget(btn_browse)
        d_form.addRow("Output Dir:", row_out)

        l.addWidget(default_group)

        l.addStretch()
        scroll.setWidget(container)
        self.tabs.addTab(scroll, "⚙️ Settings")

    def _update_volume(self, val):
        self.snd.set_volume(val / 100.0)
        self.settings_volume_lbl.setText(f"{val}%")

    def _toggle_mute(self, checked):
        self.snd.set_enabled(not checked)

    def _browse_settings_export_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Default Output Directory")
        if d:
            self.settings_outdir.setText(d)
            self.exp_outdir.setText(d)

    # ── Move callback ────────────────────────────────────────────────────────

    def on_move(self, notation):
        if self.engine.game_over:
            log(f"Game over: {self.engine.result}", "GAME")

    # ── Cleanup on close ─────────────────────────────────────────────────────

    def closeEvent(self, event):
        # Collect all running workers
        running = []
        for worker in self._active_workers:
            if worker.isRunning():
                worker.abort()
                running.append(worker)
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.abort()
            running.append(self.export_worker)
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.abort()
            running.append(self.batch_worker)

        if not running:
            event.accept()
            return

        # Wait up to 10 seconds total for all threads to finish gracefully
        from datetime import datetime, timedelta
        deadline = datetime.now() + timedelta(seconds=10)

        for worker in running:
            remaining_ms = max(0, int((deadline - datetime.now()).total_seconds() * 1000))
            if remaining_ms == 0:
                break
            worker.wait(remaining_ms)

        # Check if any are STILL running after the deadline
        still_running = [w for w in running if w.isRunning()]
        if still_running:
            log(f"Warning: {len(still_running)} threads still running at close — "
                "forcing accept (may produce QThread warnings)", "APP")

        event.accept()