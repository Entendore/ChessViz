"""Main application window — Puzzles and Openings tabs with themes, lazy loading, and export options."""

from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, QPushButton,
    QTextEdit, QFileDialog, QFrame, QListWidget, QListWidgetItem,
    QSlider, QSpinBox, QLineEdit, QFormLayout, QDialog, QComboBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from constants import log, ExportConfig, ANIM_SPEED_DEFAULT, DATA_DIR, THEMES, MQ_GOOD, MQ_BRILLIANT, MQ_BLUNDER
from engine import ChessEngine
from sound import SoundManager
from board_widget import ChessBoardWidget
from export import ExportWorker
from data_manager import LazyLoadWorker
from puzzle_loader import load_puzzles
from openings_loader import load_openings


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("♚ Chess Learning App")
        log("Initializing Chess Learning App...", "APP")

        self.engine = ChessEngine()
        self.snd = SoundManager()
        self.board_widget = ChessBoardWidget(self.engine, self.snd)
        self.board_widget.move_made.connect(self.on_move)

        self.opening_data = []
        self.opening_step_idx = 0
        self.puzzle_data = []
        self.export_worker = None

        self.puzzles_loaded = False
        self.openings_loaded = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.tabs = QTabWidget()
        self.tabs.setFixedWidth(420)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        board_frame = QFrame()
        board_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        bl = QVBoxLayout(board_frame)
        bl.setContentsMargins(0, 0, 0, 0)
        
        # Controls above board
        top_ctrl = QHBoxLayout()
        top_ctrl.addWidget(QLabel("Theme:"))
        self.theme_cb = QComboBox()
        self.theme_cb.addItems(THEMES.keys())
        self.theme_cb.currentTextChanged.connect(self._change_theme)
        top_ctrl.addWidget(self.theme_cb)
        
        top_ctrl.addWidget(QLabel("Anim:"))
        self.anim_slider = QSlider(Qt.Horizontal)
        self.anim_slider.setRange(0, 600); self.anim_slider.setValue(ANIM_SPEED_DEFAULT)
        self.anim_slider.valueChanged.connect(self._update_anim_speed)
        self.anim_lbl = QLabel(f"{ANIM_SPEED_DEFAULT}ms")
        top_ctrl.addWidget(self.anim_slider); top_ctrl.addWidget(self.anim_lbl)
        bl.addLayout(top_ctrl)
        
        bl.addWidget(self.board_widget, alignment=Qt.AlignCenter)
        layout.addWidget(board_frame, alignment=Qt.AlignCenter)

        self._build_puzzle_tab()
        self._build_openings_tab()

        self.snd.play("start")
        log("App initialization complete", "APP")

    def _change_theme(self, name):
        if name in THEMES:
            self.board_widget.current_theme = THEMES[name]
            self.board_widget.update()

    def _update_anim_speed(self, val):
        self.board_widget.anim_speed = val; self.anim_lbl.setText(f"{val}ms")

    def _on_tab_changed(self, index):
        if index == 0 and not self.puzzles_loaded: self._start_lazy_load("puzzles")
        elif index == 1 and not self.openings_loaded: self._start_lazy_load("openings")

    def _start_lazy_load(self, db_type):
        if db_type == "puzzles":
            self.puzzle_list.clear(); self.puzzle_list.addItem("Loading puzzles...")
            self.puzzles_loaded = True
        else:
            self.opening_list.clear(); self.opening_list.addItem("Loading openings...")
            self.openings_loaded = True
        directory = Path(DATA_DIR) / db_type
        self.load_worker = LazyLoadWorker(db_type, str(directory))
        self.load_worker.data_ready.connect(self._on_data_ready)
        self.load_worker.start()

    def _on_data_ready(self, db_type, data):
        if db_type == "puzzles":
            self.puzzle_data.extend(data); self._refresh_puzzle_list()
            self.puzzle_db_status.setText(f"Loaded {len(data)} items")
        else:
            self.opening_data.extend(data); self._refresh_opening_list()
            self.opening_db_status.setText(f"Loaded {len(data)} items")

    def _build_puzzle_tab(self):
        w = QWidget(); l = QVBoxLayout(w)
        db_layout = QHBoxLayout()
        btn_load_db = QPushButton("📂 Load Puzzle DB..."); btn_load_db.clicked.connect(self.load_puzzle_db)
        db_layout.addWidget(btn_load_db); self.puzzle_db_status = QLabel("")
        db_layout.addWidget(self.puzzle_db_status); l.addLayout(db_layout)

        self.puzzle_list = QListWidget(); self.puzzle_list.addItem("Click tab to load...")
        btn_load = QPushButton("📋 Load Puzzle"); btn_load.clicked.connect(self.load_puzzle)
        btn_export = QPushButton("🎬 Export to MP4..."); btn_export.clicked.connect(self.open_export_dialog)
        self.puzzle_info = QTextEdit(); self.puzzle_info.setReadOnly(True)

        l.addWidget(QLabel("Select a Puzzle:")); l.addWidget(self.puzzle_list)
        l.addWidget(btn_load); l.addWidget(btn_export)
        l.addWidget(QLabel("Instructions:")); l.addWidget(self.puzzle_info)
        self.tabs.addTab(w, "🧩 Puzzles")

    def _build_openings_tab(self):
        w = QWidget(); l = QVBoxLayout(w)
        db_layout = QHBoxLayout()
        btn_load_db = QPushButton("📂 Load Openings DB..."); btn_load_db.clicked.connect(self.load_openings_db)
        db_layout.addWidget(btn_load_db); self.opening_db_status = QLabel("")
        db_layout.addWidget(self.opening_db_status); l.addLayout(db_layout)

        self.opening_list = QListWidget(); self.opening_list.currentRowChanged.connect(self.select_opening)
        self.opening_list.addItem("Click tab to load...")
        self.opening_img_lbl = QLabel("Opening Image"); self.opening_img_lbl.setFixedSize(250, 250); self.opening_img_lbl.setAlignment(Qt.AlignCenter)
        self.opening_img_lbl.setStyleSheet("background-color: #2b2b2b; border: 1px solid #555;")
        
        step_layout = QHBoxLayout()
        btn_start = QPushButton("⏮"); btn_start.clicked.connect(self.opening_start)
        btn_prev  = QPushButton("◀ Prev"); btn_prev.clicked.connect(self.opening_prev)
        btn_next  = QPushButton("Next ▶"); btn_next.clicked.connect(self.opening_next)
        btn_end   = QPushButton("⏭"); btn_end.clicked.connect(self.opening_end)
        step_layout.addWidget(btn_start); step_layout.addWidget(btn_prev); step_layout.addWidget(btn_next); step_layout.addWidget(btn_end)

        self.opening_moves_te = QTextEdit(); self.opening_moves_te.setReadOnly(True)
        self.opening_moves_te.setFont(QFont("Courier", 13)); self.opening_moves_te.setMaximumHeight(150)
        self.opening_status = QLabel(f"Will auto-load from {DATA_DIR}."); self.opening_status.setWordWrap(True)

        l.addWidget(QLabel("Openings Loaded:")); l.addWidget(self.opening_list)
        l.addWidget(self.opening_img_lbl, alignment=Qt.AlignCenter)
        l.addLayout(step_layout); l.addWidget(QLabel("Moves:")); l.addWidget(self.opening_moves_te)
        l.addWidget(self.opening_status)
        self.tabs.addTab(w, "📚 Openings")

    def on_move(self, notation):
        if self.engine.game_over: log(f"Game over: {self.engine.result}", "GAME")

    def _refresh_puzzle_list(self):
        self.puzzle_list.clear()
        for pz in self.puzzle_data:
            it = QListWidgetItem(pz["name"]); it.setData(Qt.UserRole, pz); self.puzzle_list.addItem(it)
        if self.puzzle_data: self.puzzle_list.setCurrentRow(0)

    def load_puzzle_db(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Puzzle Database", "", "Supported (*.csv *.parquet *.duckdb *.db *.sqlite)")
        if not path: return
        try:
            new_puzzles = load_puzzles(path); self.puzzle_data.extend(new_puzzles)
            self._refresh_puzzle_list(); self.puzzle_db_status.setText(f"Added {len(new_puzzles)}")
            self.puzzles_loaded = True
        except Exception as e: self.puzzle_db_status.setText(f"Error: {e}")

    def load_puzzle(self):
        item = self.puzzle_list.currentItem()
        if not item: return
        pz = item.data(Qt.UserRole)
        if not pz: return
        if pz.get("fen"): self.engine.load_fen(pz["fen"])
        else: self.engine.reset()
        self.puzzle_info.setText(pz.get("desc", ""))
        self.board_widget.selected = None; self.board_widget.legal_targets = []
        self.board_widget.move_quality = None
        self.board_widget.update(); self.snd.play("start")

    def open_export_dialog(self):
        item = self.puzzle_list.currentItem()
        if not item: return
        pz = item.data(Qt.UserRole)
        if not pz: return
        
        dialog = QDialog(self); dialog.setWindowTitle("Export MP4 Settings")
        layout = QFormLayout(dialog)
        title_edit = QLineEdit(pz['name']); end_edit = QLineEdit("Solved!")
        fps_spin = QSpinBox(); fps_spin.setRange(10, 120); fps_spin.setValue(30)
        worker_spin = QSpinBox(); worker_spin.setRange(1, 16); worker_spin.setValue(4)
        
        theme_combo = QComboBox(); theme_combo.addItems(THEMES.keys())
        theme_combo.setCurrentText(self.theme_cb.currentText())
        
        mq_combo = QComboBox()
        mq_map = {"None": None, "Good": MQ_GOOD, "Brilliant": MQ_BRILLIANT, "Blunder": MQ_BLUNDER}
        mq_combo.addItems(mq_map.keys())

        layout.addRow("Title Text:", title_edit); layout.addRow("End Text:", end_edit)
        layout.addRow("FPS:", fps_spin); layout.addRow("Parallel Workers:", worker_spin)
        layout.addRow("Theme:", theme_combo); layout.addRow("Move Badge:", mq_combo)
        
        btns = QHBoxLayout()
        ok_btn = QPushButton("Export"); cancel_btn = QPushButton("Cancel")
        btns.addWidget(ok_btn); btns.addWidget(cancel_btn); layout.addRow(btns)
        ok_btn.clicked.connect(dialog.accept); cancel_btn.clicked.connect(dialog.reject)
        
        if dialog.exec() == QDialog.Accepted:
            path, _ = QFileDialog.getSaveFileName(self, "Save MP4", f"{pz['name']}.mp4", "Video (*.mp4)")
            if not path: return
            cfg = ExportConfig()
            cfg.title_text = title_edit.text(); cfg.end_text = end_edit.text()
            cfg.fps = fps_spin.value(); cfg.max_workers = worker_spin.value()
            cfg.theme_name = theme_combo.currentText()
            cfg.move_quality = mq_map[mq_combo.currentText()]
            log(f"Starting MP4 export: {pz['name']} -> {path}", "EXPORT")
            self.export_worker = ExportWorker(pz, path, cfg)
            self.export_worker.progress.connect(lambda pct: log(f"Export progress: {pct}%", "EXPORT"))
            self.export_worker.finished.connect(lambda msg: log(f"Export complete: {msg}", "EXPORT"))
            self.export_worker.start()

    def load_openings_db(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Openings Database", "", "Supported (*.csv *.parquet *.duckdb *.db *.sqlite)")
        if not path: return
        try:
            new_openings = load_openings(path); self.opening_data.extend(new_openings)
            self._refresh_opening_list(); self.opening_db_status.setText(f"Added {len(new_openings)}")
            self.openings_loaded = True
        except Exception as e: self.opening_db_status.setText(f"Error: {e}")

    def _refresh_opening_list(self):
        self.opening_list.clear()
        for data in self.opening_data: self.opening_list.addItem(f"{data['eco']} - {data['name']}")
        if self.opening_data: self.opening_list.setCurrentRow(0)

    def _opening_fen(self, data):
        fen = data['epd']
        if not fen: fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        if len(fen.split()) < 6: fen += " 0 1"
        return fen

    def select_opening(self, row):
        if row < 0 or row >= len(self.opening_data): return
        data = self.opening_data[row]; self.opening_step_idx = 0
        self.engine.load_fen(self._opening_fen(data))
        if data['pixmap'] and not data['pixmap'].isNull(): self.opening_img_lbl.setPixmap(data['pixmap'].scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else: self.opening_img_lbl.setText("No Image")
        self.board_widget.selected = None; self.board_widget.legal_targets = []
        self.board_widget.move_quality = None
        self.board_widget.update(); self.update_opening_display()

    def update_opening_display(self):
        row = self.opening_list.currentRow()
        if row < 0: return
        data = self.opening_data[row]; text = ""
        for i, uci in enumerate(data['uci_moves']):
            marker = f"<b><u>{uci}</u></b>" if i == self.opening_step_idx else uci
            text += marker + " "
            if (i+1)%2==0: text += "  "
        self.opening_moves_te.setHtml(text)

    def opening_start(self):
        self.opening_step_idx = 0; self.select_opening(self.opening_list.currentRow()); self.snd.play("move")

    def opening_prev(self):
        if self.opening_step_idx > 0:
            self.opening_step_idx -= 1; row = self.opening_list.currentRow()
            if row < 0: return
            data = self.opening_data[row]; self.engine.load_fen(self._opening_fen(data))
            for i in range(self.opening_step_idx):
                m, promo = self.engine.parse_uci(data['uci_moves'][i])
                if m: self.engine.make_move(m[0][0], m[0][1], m[1][0], m[1][1], promo)
            self.board_widget.selected = None; self.board_widget.legal_targets = []
            self.board_widget.move_quality = None
            self.board_widget.update(); self.update_opening_display(); self.snd.play("move")

    def opening_next(self):
        row = self.opening_list.currentRow()
        if row < 0: return
        data = self.opening_data[row]
        if self.opening_step_idx < len(data['uci_moves']):
            uci = data['uci_moves'][self.opening_step_idx]
            move, promo = self.engine.parse_uci(uci)
            if move:
                (fr, fc), (tr, tc) = move
                info = self.engine.make_move(fr, fc, tr, tc, promo)
                if info:
                    sfx = ("capture" if info['captured']!='.' else "castle" if info['castle'] else "move")
                    if info['mate']: sfx = "checkmate"
                    elif info['check']: sfx = "check"
                    self.snd.play(sfx)
                    if self.board_widget.anim_speed > 0:
                        self.board_widget.start_animation(fr, fc, tr, tc, info['piece'], info['captured'], '')
            self.opening_step_idx += 1
            self.board_widget.selected = None; self.board_widget.legal_targets = []
            self.update_opening_display()

    def opening_end(self):
        row = self.opening_list.currentRow()
        if row < 0: return
        data = self.opening_data[row]; self.engine.load_fen(self._opening_fen(data))
        for uci in data['uci_moves']:
            m, promo = self.engine.parse_uci(uci)
            if m: self.engine.make_move(m[0][0], m[0][1], m[1][0], m[1][1], promo)
        self.opening_step_idx = len(data['uci_moves'])
        self.board_widget.selected = None; self.board_widget.legal_targets = []
        self.board_widget.move_quality = None
        self.board_widget.update(); self.update_opening_display(); self.snd.play("move")