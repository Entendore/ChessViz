"""Main application window — Play, Puzzles, and Openings tabs."""

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QComboBox, QTextEdit,
    QFileDialog, QFrame, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from constants import log
from engine import ChessEngine
from sound import SoundManager
from board_widget import ChessBoardWidget
from export import ExportWorker
from puzzles import PUZZLES
from openings_loader import load_openings


class MainWindow(QWidget):                       # was QMainWindow — kept as QWidget for simplicity
    # We embed in a QMainWindow inside app.py, or just use this directly.
    # Keeping the same interface as the original.
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

        # ── Layout ────────────────────────────────────────────────────────────
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.tabs = QTabWidget()
        self.tabs.setFixedWidth(400)
        layout.addWidget(self.tabs)

        board_frame = QFrame()
        board_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        bl = QVBoxLayout(board_frame)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.board_widget)
        layout.addWidget(board_frame, alignment=Qt.AlignCenter)

        self._build_play_tab()
        self._build_puzzle_tab()
        self._build_openings_tab()

        self.snd.play("start")
        log("App initialization complete", "APP")

    # ── Play Tab ──────────────────────────────────────────────────────────────
    def _build_play_tab(self):
        w = QWidget(); l = QVBoxLayout(w)

        self.ai_cb = QComboBox()
        self.ai_cb.addItems([
            "Human vs Human", "Play vs AI (White)", "Play vs AI (Black)"])

        self.depth_cb = QComboBox()
        self.depth_cb.addItems([
            "Depth 1 (Easy)", "Depth 2 (Medium)", "Depth 3 (Hard)"])
        self.depth_cb.setCurrentIndex(1)

        btn_new = QPushButton("♻ New Game")
        btn_new.clicked.connect(self.new_game)

        btn_undo = QPushButton("↩ Undo Move")
        btn_undo.clicked.connect(self.undo)

        self.status_lbl = QLabel("White's turn")
        self.status_lbl.setFont(QFont("Sans", 14, QFont.Bold))
        self.status_lbl.setAlignment(Qt.AlignCenter)

        self.log_te = QTextEdit()
        self.log_te.setReadOnly(True)
        self.log_te.setFont(QFont("Courier", 12))

        l.addWidget(QLabel("Game Mode:"));   l.addWidget(self.ai_cb)
        l.addWidget(QLabel("AI Strength:")); l.addWidget(self.depth_cb)
        l.addWidget(btn_new); l.addWidget(btn_undo)
        l.addWidget(self.status_lbl); l.addWidget(self.log_te)
        self.tabs.addTab(w, "♟ Play")

    # ── Puzzle Tab ────────────────────────────────────────────────────────────
    def _build_puzzle_tab(self):
        w = QWidget(); l = QVBoxLayout(w)

        self.puzzle_list = QListWidget()
        for pz in PUZZLES:
            it = QListWidgetItem(pz["name"])
            it.setData(Qt.UserRole, pz)
            self.puzzle_list.addItem(it)
        self.puzzle_list.setCurrentRow(0)

        btn_load = QPushButton("📋 Load Puzzle")
        btn_load.clicked.connect(self.load_puzzle)

        btn_export = QPushButton("🎬 Export to MP4")
        btn_export.clicked.connect(self.export_mp4)

        self.puzzle_info = QTextEdit()
        self.puzzle_info.setReadOnly(True)

        l.addWidget(QLabel("Select a Puzzle:")); l.addWidget(self.puzzle_list)
        l.addWidget(btn_load); l.addWidget(btn_export)
        l.addWidget(QLabel("Instructions:")); l.addWidget(self.puzzle_info)
        self.tabs.addTab(w, "🧩 Puzzles")

    # ── Openings Tab ──────────────────────────────────────────────────────────
    def _build_openings_tab(self):
        w = QWidget(); l = QVBoxLayout(w)

        btn_load = QPushButton("📂 Load Openings File...")
        btn_load.clicked.connect(self.load_openings_file)

        self.opening_list = QListWidget()
        self.opening_list.currentRowChanged.connect(self.select_opening)

        self.opening_img_lbl = QLabel("Opening Image")
        self.opening_img_lbl.setFixedSize(250, 250)
        self.opening_img_lbl.setAlignment(Qt.AlignCenter)
        self.opening_img_lbl.setStyleSheet(
            "background-color: #2b2b2b; border: 1px solid #555;")

        step_layout = QHBoxLayout()
        btn_start = QPushButton("⏮");  btn_start.clicked.connect(self.opening_start)
        btn_prev  = QPushButton("◀ Prev"); btn_prev.clicked.connect(self.opening_prev)
        btn_next  = QPushButton("Next ▶"); btn_next.clicked.connect(self.opening_next)
        btn_end   = QPushButton("⏭");  btn_end.clicked.connect(self.opening_end)
        step_layout.addWidget(btn_start)
        step_layout.addWidget(btn_prev)
        step_layout.addWidget(btn_next)
        step_layout.addWidget(btn_end)

        self.opening_moves_te = QTextEdit()
        self.opening_moves_te.setReadOnly(True)
        self.opening_moves_te.setFont(QFont("Courier", 13))
        self.opening_moves_te.setMaximumHeight(150)

        self.opening_status = QLabel(
            "Load a CSV, Parquet, DuckDB, or SQLite file to study openings.")
        self.opening_status.setWordWrap(True)

        l.addWidget(btn_load)
        l.addWidget(QLabel("Openings Loaded:")); l.addWidget(self.opening_list)
        l.addWidget(self.opening_img_lbl, alignment=Qt.AlignCenter)
        l.addLayout(step_layout)
        l.addWidget(QLabel("Moves:")); l.addWidget(self.opening_moves_te)
        l.addWidget(self.opening_status)
        self.tabs.addTab(w, "📚 Openings")

    # ── Game logic ────────────────────────────────────────────────────────────
    def new_game(self):
        self.engine.reset(); self.log_te.clear()
        self.board_widget.selected = None; self.board_widget.legal_targets = []
        self.board_widget.update(); self.update_status(); self.snd.play("start")
        log("New game started", "GAME")

    def undo(self):
        if self.engine.undo():
            self.board_widget.selected = None; self.board_widget.legal_targets = []
            self.board_widget.update(); self.update_status(); self.snd.play("move")
        else:
            log("Undo failed — no history", "GAME")

    def on_move(self, notation):
        self.log_te.append(notation); self.update_status()
        if self.engine.game_over:
            log(f"Game over: {self.engine.result}", "GAME")
        if not self.engine.game_over and self.is_ai_turn():
            QTimer.singleShot(200, self.ai_move)

    def is_ai_turn(self):
        idx = self.ai_cb.currentIndex()
        if idx == 1 and self.engine.turn == 'b':
            return True
        if idx == 2 and self.engine.turn == 'w':
            return True
        return False

    def ai_move(self):
        depth = self.depth_cb.currentIndex() + 1
        move = self.engine.get_ai_move(depth)
        if move:
            (fr, fc), (tr, tc) = move
            info = self.engine.make_move(fr, fc, tr, tc)
            if info:
                sfx = ("capture" if info['captured'] != '.'
                       else "castle" if info['castle'] else "move")
                if info['mate']:
                    sfx = "checkmate"
                elif info['check']:
                    sfx = "check"
                self.snd.play(sfx)
                self.log_te.append(info['notation'])
                self.board_widget.selected = None
                self.board_widget.legal_targets = []
                self.board_widget.update()
                self.update_status()
                if self.engine.game_over:
                    log(f"Game over after AI move: {self.engine.result}", "GAME")

    def update_status(self):
        if self.engine.game_over:
            self.status_lbl.setText(self.engine.result)
            self.status_lbl.setStyleSheet("color: red; font-weight: bold;")
            log(f"Status: {self.engine.result}", "GAME")
        else:
            turn = ("White's turn" if self.engine.turn == 'w'
                    else "Black's turn")
            if self.engine.in_check(self.engine.turn):
                turn += " (CHECK!)"
                self.status_lbl.setStyleSheet(
                    "color: orange; font-weight: bold;")
                log(f"Status: {turn}", "GAME")
            else:
                self.status_lbl.setStyleSheet(
                    "color: black; font-weight: bold;")
            self.status_lbl.setText(turn)

    # ── Puzzles ───────────────────────────────────────────────────────────────
    def load_puzzle(self):
        item = self.puzzle_list.currentItem()
        if not item:
            return
        pz = item.data(Qt.UserRole)
        self.engine.load_fen(pz["fen"])
        self.ai_cb.setCurrentIndex(0)
        self.log_te.clear()
        self.puzzle_info.setText(pz.get("desc", ""))
        self.board_widget.selected = None; self.board_widget.legal_targets = []
        self.board_widget.update(); self.update_status(); self.snd.play("start")
        log(f"Puzzle loaded: {pz['name']}", "PUZZLE")

    def export_mp4(self):
        from constants import HAS_NUMPY, HAS_IMAGEIO
        item = self.puzzle_list.currentItem()
        if not item:
            return
        pz = item.data(Qt.UserRole)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save MP4", f"{pz['name']}.mp4", "Video (*.mp4)")
        if not path:
            return
        if not HAS_NUMPY or not HAS_IMAGEIO:
            log("ERROR: MP4 export requires numpy and imageio. "
                "Install via: pip install numpy imageio[ffmpeg]", "EXPORT")
            return
        log(f"Starting MP4 export: {pz['name']} -> {path}", "EXPORT")
        self.export_worker = ExportWorker(pz, path)
        self.export_worker.progress.connect(self._on_export_progress)
        self.export_worker.finished.connect(self.on_export_finished)
        self.export_worker.start()

    def _on_export_progress(self, pct):
        log(f"Export progress: {pct}%", "EXPORT")

    def on_export_finished(self, msg):
        if "ERROR" in msg:
            log(f"Export error: {msg}", "EXPORT")
        else:
            log(f"Export complete: {msg}", "EXPORT")

    # ── Openings ──────────────────────────────────────────────────────────────
    def load_openings_file(self):
        file_filter = (
            "Supported Files (*.csv *.parquet *.duckdb *.db *.sqlite);;"
            "CSV (*.csv);;Parquet (*.parquet);;DuckDB (*.duckdb);;"
            "SQLite (*.db *.sqlite);;All Files (*)")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Openings File", "", file_filter)
        if not path:
            return
        try:
            self.opening_data = load_openings(path)
        except Exception as e:
            log(f"Failed to read file: {e}", "OPENINGS")
            self.opening_status.setText(f"Error: {e}")
            return

        self.opening_list.clear()
        for data in self.opening_data:
            self.opening_list.addItem(f"{data['eco']} - {data['name']}")
        if self.opening_data:
            self.opening_list.setCurrentRow(0)
            self.opening_status.setText(
                f"Loaded {len(self.opening_data)} openings from "
                f"{Path(path).name}")
            log(f"Loaded {len(self.opening_data)} openings from {path}",
                "OPENINGS")
        else:
            self.opening_status.setText("No valid openings found in file.")
            log(f"No valid openings found in {path}", "OPENINGS")

    def _opening_fen(self, data):
        fen = data['epd']
        if not fen:
            fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        if len(fen.split()) < 6:
            fen += " 0 1"
        return fen

    def select_opening(self, row):
        if row < 0 or row >= len(self.opening_data):
            return
        data = self.opening_data[row]
        self.ai_cb.setCurrentIndex(0)
        self.opening_step_idx = 0

        self.engine.load_fen(self._opening_fen(data))

        if data['pixmap'] and not data['pixmap'].isNull():
            self.opening_img_lbl.setPixmap(
                data['pixmap'].scaled(240, 240,
                                      Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation))
        else:
            self.opening_img_lbl.setText("No Image")

        self.board_widget.selected = None; self.board_widget.legal_targets = []
        self.board_widget.update()
        self.update_opening_display()
        log(f"Opening selected: {data['eco']} - {data['name']} "
            f"({len(data['uci_moves'])} moves)", "OPENINGS")

    def update_opening_display(self):
        row = self.opening_list.currentRow()
        if row < 0:
            return
        data = self.opening_data[row]
        text = ""
        for i, uci in enumerate(data['uci_moves']):
            marker = ("<b><u>" + uci + "</u></b>"
                      if i == self.opening_step_idx else uci)
            text += marker + " "
            if (i + 1) % 2 == 0:
                text += "  "
        self.opening_moves_te.setHtml(text)

    def opening_start(self):
        self.opening_step_idx = 0
        self.select_opening(self.opening_list.currentRow())
        self.snd.play("move")
        log("Opening: reset to start", "OPENINGS")

    def opening_prev(self):
        if self.opening_step_idx > 0:
            self.opening_step_idx -= 1
            row = self.opening_list.currentRow()
            if row < 0:
                return
            data = self.opening_data[row]
            self.engine.load_fen(self._opening_fen(data))
            for i in range(self.opening_step_idx):
                m, promo = self.engine.parse_uci(data['uci_moves'][i])
                if m:
                    self.engine.make_move(
                        m[0][0], m[0][1], m[1][0], m[1][1], promo)
            self.board_widget.selected = None
            self.board_widget.legal_targets = []
            self.board_widget.update()
            self.update_opening_display()
            self.snd.play("move")
            log(f"Opening: step back to move {self.opening_step_idx}",
                "OPENINGS")

    def opening_next(self):
        row = self.opening_list.currentRow()
        if row < 0:
            return
        data = self.opening_data[row]
        if self.opening_step_idx < len(data['uci_moves']):
            uci = data['uci_moves'][self.opening_step_idx]
            move, promo = self.engine.parse_uci(uci)
            if move:
                (fr, fc), (tr, tc) = move
                info = self.engine.make_move(fr, fc, tr, tc, promo)
                if info:
                    sfx = ("capture" if info['captured'] != '.'
                           else "castle" if info['castle'] else "move")
                    if info['mate']:
                        sfx = "checkmate"
                    elif info['check']:
                        sfx = "check"
                    self.snd.play(sfx)
            self.opening_step_idx += 1
            self.board_widget.selected = None
            self.board_widget.legal_targets = []
            self.board_widget.update()
            self.update_opening_display()
            log(f"Opening: step forward to move {self.opening_step_idx}",
                "OPENINGS")

    def opening_end(self):
        row = self.opening_list.currentRow()
        if row < 0:
            return
        data = self.opening_data[row]
        self.engine.load_fen(self._opening_fen(data))
        for uci in data['uci_moves']:
            m, promo = self.engine.parse_uci(uci)
            if m:
                self.engine.make_move(
                    m[0][0], m[0][1], m[1][0], m[1][1], promo)
        self.opening_step_idx = len(data['uci_moves'])
        self.board_widget.selected = None
        self.board_widget.legal_targets = []
        self.board_widget.update()
        self.update_opening_display()
        self.snd.play("move")
        log("Opening: jumped to end", "OPENINGS")