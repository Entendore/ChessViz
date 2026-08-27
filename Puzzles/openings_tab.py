"""Openings tab mixin — extracted from main_window to balance file sizes.
Provides the full openings UI, pagination, step-through navigation, and export.
All file selection uses inline path inputs (no popup dialogs).
"""

import os, math
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit,
    QSpinBox, QLineEdit, QProgressBar, QGroupBox, QCheckBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QPixmap
from constants import log, ExportConfig, THEMES, parse_opening_image, DATA_DIR, HAS_FFMPEG
from export import BatchExportWorker


class OpeningsMixin:
    """Mixin class that provides the Openings Tab for MainWindow."""

    def _build_openings_tab(self):
        from main_window import CheckableListWidget  # avoid circular at module level

        scroll = QWidget()
        l = QVBoxLayout(scroll)
        l.setSpacing(12)

        # ── 1. Database ──────────────────────────────────────────────────
        db_group = QGroupBox("📂 Openings Database")
        db_layout = QVBoxLayout(db_group)

        path_row = QHBoxLayout()
        self.opening_db_path = QLineEdit()
        self.opening_db_path.setPlaceholderText(
            "Database file path (.csv .parquet .pq .duckdb .db .sqlite)…")
        path_row.addWidget(self.opening_db_path, 1)
        btn_load_db = QPushButton("Load")
        btn_load_db.clicked.connect(self.load_openings_db)
        path_row.addWidget(btn_load_db)
        db_layout.addLayout(path_row)

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
        self.opening_filter.textChanged.connect(
            lambda: self._op_filter_timer.start())

        sel_row = QHBoxLayout()
        btn_all = QPushButton("All"); btn_all.setFixedWidth(55)
        btn_all.clicked.connect(self._opening_select_all)
        btn_none = QPushButton("None"); btn_none.setFixedWidth(55)
        btn_none.clicked.connect(self._opening_select_none)
        btn_inv = QPushButton("Invert"); btn_inv.setFixedWidth(60)
        btn_inv.clicked.connect(self._opening_select_invert)
        sel_row.addWidget(btn_all)
        sel_row.addWidget(btn_none)
        sel_row.addWidget(btn_inv)
        sel_row.addStretch()
        fl.addLayout(sel_row)

        range_row = QHBoxLayout()
        self.opening_range_from = QSpinBox()
        self.opening_range_from.setRange(1, 999999)
        self.opening_range_from.setPrefix("#")
        self.opening_range_to = QSpinBox()
        self.opening_range_to.setRange(1, 999999)
        self.opening_range_to.setPrefix("#")
        btn_range = QPushButton("Apply Range")
        btn_range.clicked.connect(self._opening_select_range)
        range_row.addWidget(QLabel("From:"))
        range_row.addWidget(self.opening_range_from)
        range_row.addWidget(QLabel("To:"))
        range_row.addWidget(self.opening_range_to)
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
        nav.addWidget(self.btn_op_prev)
        nav.addWidget(self.op_page_lbl, 1)
        nav.addWidget(self.btn_op_next)
        nav.addWidget(QLabel("Jump:"))
        self.op_jump_spin = QSpinBox()
        self.op_jump_spin.setRange(1, 999999)
        self.op_jump_spin.setFixedWidth(65)
        btn_op_jump = QPushButton("Go"); btn_op_jump.setFixedWidth(35)
        btn_op_jump.clicked.connect(self._op_jump_page)
        nav.addWidget(self.op_jump_spin)
        nav.addWidget(btn_op_jump)
        ll.addLayout(nav)

        l.addWidget(list_group)

        # ── 4. Opening Detail ────────────────────────────────────────────
        detail_group = QGroupBox("♟ Opening Detail")
        dl = QVBoxLayout(detail_group)

        self.opening_img_lbl = QLabel("Opening Image")
        self.opening_img_lbl.setFixedSize(220, 220)
        self.opening_img_lbl.setAlignment(Qt.AlignCenter)
        self.opening_img_lbl.setStyleSheet(
            "background-color: #2b2b2b; border: 1px solid #555;"
            " border-radius: 4px;")
        dl.addWidget(self.opening_img_lbl, alignment=Qt.AlignCenter)

        step_layout = QHBoxLayout()
        step_layout.addStretch()
        btn_start = QPushButton("⏮")
        btn_start.clicked.connect(self.opening_start)
        btn_prev = QPushButton("◀ Prev")
        btn_prev.clicked.connect(self.opening_prev)
        btn_next = QPushButton("Next ▶")
        btn_next.clicked.connect(self.opening_next)
        btn_end = QPushButton("⏭")
        btn_end.clicked.connect(self.opening_end)
        step_layout.addWidget(btn_start)
        step_layout.addWidget(btn_prev)
        step_layout.addWidget(btn_next)
        step_layout.addWidget(btn_end)
        step_layout.addStretch()
        dl.addLayout(step_layout)

        self.opening_moves_te = QTextEdit()
        self.opening_moves_te.setReadOnly(True)
        self.opening_moves_te.setFont(QFont("Courier", 13))
        self.opening_moves_te.setMaximumHeight(80)
        dl.addWidget(self.opening_moves_te)

        l.addWidget(detail_group)

        # ── 5. Export ────────────────────────────────────────────────────
        export_group = QGroupBox("🎬 Export Openings")
        el = QVBoxLayout(export_group)

        # IMPROVEMENT: GIF export option for openings
        gif_row = QHBoxLayout()
        self.opening_exp_gif = QCheckBox("Export as GIF")
        gif_row.addWidget(self.opening_exp_gif)
        self.opening_exp_gif_fps = QSpinBox()
        self.opening_exp_gif_fps.setRange(5, 30)
        self.opening_exp_gif_fps.setValue(12)
        self.opening_exp_gif_fps.setEnabled(False)
        self.opening_exp_gif.toggled.connect(
            self.opening_exp_gif_fps.setEnabled)
        gif_row.addWidget(QLabel("GIF FPS:"))
        gif_row.addWidget(self.opening_exp_gif_fps)
        el.addLayout(gif_row)

        batch_row = QHBoxLayout()
        btn_exp_sel = QPushButton("Export Selected")
        btn_exp_sel.clicked.connect(self._export_openings_batch)
        btn_exp_all = QPushButton("Export All")
        btn_exp_all.clicked.connect(self._export_all_openings_batch)
        batch_row.addWidget(btn_exp_sel)
        batch_row.addWidget(btn_exp_all)
        el.addLayout(batch_row)

        self.opening_progress = QProgressBar()
        self.opening_progress.setRange(0, 100)
        self.opening_progress.setValue(0)
        el.addWidget(self.opening_progress)

        self.opening_status = QLabel("")
        self.opening_status.setWordWrap(True)
        el.addWidget(self.opening_status)

        l.addWidget(export_group)

        l.addStretch()
        self.tabs.addTab(scroll, "📚 Openings")

    # ── Opening pagination helpers ────────────────────────────────────────

    def _op_total_items(self):
        return self.db.get_count('openings',
                                self.opening_filter.text().strip())

    def _op_page_count(self):
        return max(1, math.ceil(self._op_total_items() / self._PAGE_SIZE))

    def _populate_opening_page(self):
        self.opening_list.blockSignals(True)
        self.opening_list.clear()

        filter_text = self.opening_filter.text().strip()
        items = self.db.get_page('openings', self._op_page,
                                 self._PAGE_SIZE, filter_text)

        for item in items:
            di = item['id']
            checked = di in self._op_checked
            name = f"{item.get('eco', '')} - {item.get('name', '')}"
            list_item = self.opening_list.add_checkable_item(
                name, data=item, checked=checked)
            list_item.setData(Qt.UserRole + 1, di)

        self.opening_list.blockSignals(False)
        self._update_opening_nav()
        self._update_opening_sel_label()

    def _update_opening_nav(self):
        total = self._op_total_items()
        pc = max(1, math.ceil(total / self._PAGE_SIZE))
        self.op_page_lbl.setText(
            f"Page {self._op_page + 1} / {pc}  ({total:,} items)")
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
        self.opening_sel_label.setText(
            f"Selected: {cnt:,} / {total:,}")

    def _on_opening_item_changed(self, item):
        di = item.data(Qt.UserRole + 1)
        if di is None: return
        if item.checkState() == Qt.Checked:
            self._op_checked.add(di)
        else:
            self._op_checked.discard(di)
        self._update_opening_sel_label()

    def _apply_opening_filter(self):
        self._op_page = 0
        self._populate_opening_page()

    def _opening_select_all(self):
        filter_text = self.opening_filter.text().strip()
        self._op_checked = set(
            self.db.get_ids_by_filter('openings', filter_text))
        self._populate_opening_page()

    def _opening_select_none(self):
        self._op_checked.clear()
        self._populate_opening_page()

    def _opening_select_invert(self):
        filter_text = self.opening_filter.text().strip()
        all_ids = set(
            self.db.get_ids_by_filter('openings', filter_text))
        self._op_checked = all_ids - self._op_checked
        self._populate_opening_page()

    # FIX: use actual database IDs instead of raw sequential numbers
    def _opening_select_range(self):
        start = self.opening_range_from.value()
        end = self.opening_range_to.value()
        if start > end: start, end = end, start
        all_ids = self.db.get_ids_by_filter('openings')
        for i in range(start - 1, min(end, len(all_ids))):
            self._op_checked.add(all_ids[i])
        self._populate_opening_page()

    def _op_prev_page(self):
        if self._op_page > 0:
            self._op_page -= 1
            self._populate_opening_page()

    def _op_next_page(self):
        if self._op_page < self._op_page_count() - 1:
            self._op_page += 1
            self._populate_opening_page()

    def _op_jump_page(self):
        page = self.op_jump_spin.value() - 1
        if 0 <= page < self._op_page_count():
            self._op_page = page
            self._populate_opening_page()

    # ── Opening display / navigation ─────────────────────────────────────────

    def _opening_fen(self, data):
        fen = data.get('epd', '')
        if not fen:
            fen = ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/"
                   "RNBQKBNR w KQkq -")
        if len(fen.split()) < 6:
            fen += " 0 1"
        return fen

    def select_opening(self, row):
        if row < 0:
            return
        item = self.opening_list.item(row)
        if not item:
            return
        di = item.data(Qt.UserRole + 1)
        if di is None:
            return

        items = self.db.get_items_by_ids('openings', [di])
        if not items:
            return
        data = items[0]

        self._current_opening = data
        self.opening_step_idx = 0
        self.engine.load_fen(self._opening_fen(data))

        img_raw = data.get('img_raw', '')
        img = parse_opening_image(img_raw) if img_raw else None

        if img and not img.isNull():
            pixmap = QPixmap.fromImage(img)
            self.opening_img_lbl.setPixmap(
                pixmap.scaled(210, 210, Qt.KeepAspectRatio,
                              Qt.SmoothTransformation))
        else:
            self.opening_img_lbl.setText("No Image")

        self.board_widget.selected = None
        self.board_widget.legal_targets = []
        self.board_widget.update()
        self.update_opening_display()

    def update_opening_display(self):
        if not hasattr(self, '_current_opening') or not self._current_opening:
            return
        data = self._current_opening
        text = ""
        for i, uci in enumerate(data.get('uci_moves', [])):
            marker = (f"<b><u>{uci}</u></b>"
                      if i == self.opening_step_idx else uci)
            text += marker + " "
            if (i + 1) % 2 == 0: text += "  "
        self.opening_moves_te.setHtml(text)

    def opening_start(self):
        if not self._current_opening: return
        self.opening_step_idx = 0
        self.engine.load_fen(self._opening_fen(self._current_opening))
        self.board_widget.selected = None
        self.board_widget.legal_targets = []
        self.board_widget.update()
        self.update_opening_display()
        self.snd.play("move")

    def opening_prev(self):
        if not self._current_opening: return
        if self.opening_step_idx > 0:
            self.opening_step_idx -= 1
            self.engine.load_fen(self._opening_fen(self._current_opening))
            for uci in self._current_opening.get(
                    'uci_moves', [])[:self.opening_step_idx]:
                self.engine.make_move_uci(uci)
            self.board_widget.selected = None
            self.board_widget.legal_targets = []
            self.board_widget.update()
            self.update_opening_display()
            self.snd.play("move")

    def opening_next(self):
        if not self._current_opening: return
        uci_moves = self._current_opening.get('uci_moves', [])
        if self.opening_step_idx < len(uci_moves):
            uci = uci_moves[self.opening_step_idx]
            self.engine.make_move_uci(uci)
            self.opening_step_idx += 1
            self.board_widget.selected = None
            self.board_widget.legal_targets = []
            self.board_widget.update()
            self.update_opening_display()
            self.snd.play("move")

    def opening_end(self):
        if not self._current_opening: return
        uci_moves = self._current_opening.get('uci_moves', [])
        self.engine.load_fen(self._opening_fen(self._current_opening))
        for uci in uci_moves:
            self.engine.make_move_uci(uci)
        self.opening_step_idx = len(uci_moves)
        self.board_widget.selected = None
        self.board_widget.legal_targets = []
        self.board_widget.update()
        self.update_opening_display()
        self.snd.play("move")

    # ── Opening batch export ─────────────────────────────────────────────────

    def _opening_to_puzzle(self, data):
        name = f"{data.get('eco', '')} - {data.get('name', '')}"
        return {
            'name': name,
            'display_title': data.get('display_title', name),
            'fen': self._opening_fen(data),
            'moves': data.get('uci_moves', []),
            'desc': data.get('pgn', ''),
            'difficulty': 0.5,
        }

    def _export_openings_batch(self):
        if not self._op_checked:
            self.opening_status.setText(
                "No openings checked for export."); return
        openings = self.db.get_items_by_ids('openings',
                                            list(self._op_checked))
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
        # IMPROVEMENT: propagate GIF settings for openings
        cfg.export_gif = self.opening_exp_gif.isChecked()
        cfg.gif_fps = self.opening_exp_gif_fps.value()
        total = len(puzzles)
        log(f"Starting openings batch export: {total} -> {out_dir}", "EXPORT")
        self.opening_progress.setValue(0)
        self.opening_status.setText(f"Batch: 0 / {total}")

        # FIX: use dedicated opening_batch_worker instead of shared self.batch_worker
        if self.opening_batch_worker and self.opening_batch_worker.isRunning():
            self.opening_batch_worker.abort()
            self.opening_batch_worker.wait(3000)

        self.opening_batch_worker = BatchExportWorker(puzzles, out_dir, cfg)
        self.opening_batch_worker.batch_progress.connect(
            self._on_opening_batch_progress)
        self.opening_batch_worker.puzzle_done.connect(
            self._on_opening_batch_done)
        self.opening_batch_worker.puzzle_error.connect(
            self._on_opening_batch_error)
        self.opening_batch_worker.all_done.connect(
            self._on_opening_batch_all_done)
        self.opening_batch_worker.start()

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
        if self.opening_batch_worker:
            self.opening_batch_worker.deleteLater()
            self.opening_batch_worker = None

    def load_openings_db(self):
        path = self.opening_db_path.text().strip()
        if not path:
            self.opening_db_status.setText(
                "Enter a database path above first.")
            return
        if not os.path.exists(path):
            self.opening_db_status.setText(f"File not found: {path}")
            return
        self.opening_db_status.setText("Loading…")
        self._start_data_load("openings", single_file=path)