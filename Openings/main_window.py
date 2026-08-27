"""
main_window.py — Main window with chess.com-style layout, inline export panel,
FFmpeg MP4 export, animated playback, export manifest tracking, and chunked
lazy-loading for the openings list.
"""

import os, json, threading, subprocess, tempfile, shutil

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSlider, QComboBox, QCheckBox, QGroupBox, QSplitter,
    QStatusBar, QLineEdit, QApplication, QProgressBar, QSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor

from config import (
    THEMES, EXPORT_PRESETS, ExportConfig, DATA_DIR, EXPORT_DIR,
    LICHESS_DB_PATH, EXPORT_MANIFEST_PATH, HAS_FFMPEG, log
)
from engine import ChessEngine
from sound import SoundManager
from board_widget import ChessBoardWidget
from data_provider import DataProvider, ExportTracker
from openings_loader import load_openings
from rendering import render_composite_frame, render_export_title_card, qimage_to_np
from helpers import sanitize_filename

import chess
import numpy as np


# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT WORKER
# ═══════════════════════════════════════════════════════════════════════════════

from PySide6.QtCore import QThread

class ExportWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, opening_rec, cfg, theme):
        super().__init__()
        self.rec = opening_rec; self.cfg = cfg; self.theme = theme

    def run(self):
        try:
            self._do_export()
        except Exception as e:
            self.error.emit(str(e))

    def _do_export(self):
        rec = self.rec; cfg = self.cfg; theme = self.theme
        preset = cfg.preset
        w, h = preset.width, preset.height
        sq = preset.calc_sq_size(); fps = cfg.fps
        bg = preset.bg

        uci_moves = rec.get('uci_moves', [])
        if isinstance(uci_moves, str):
            try: uci_moves = json.loads(uci_moves)
            except Exception: uci_moves = uci_moves.split()

        board = chess.Board(); notations = []
        for u in uci_moves:
            try:
                move = chess.Move.from_uci(u)
                if move in board.legal_moves:
                    notations.append(board.san(move)); board.push(move)
                else: break
            except Exception: break
        num_moves = len(notations)

        anim_dur = cfg.move_anim_duration
        pause_dur = cfg.pause_after_move
        frames_per_anim = max(1, int(fps * anim_dur))
        frames_per_pause = max(1, int(fps * pause_dur))
        title_frames = int(fps * cfg.title_duration) if cfg.title_enabled else 0
        end_frames = int(fps * cfg.end_hold_duration) if cfg.end_hold_enabled else 0
        move_frames = num_moves * (frames_per_anim + frames_per_pause)
        init_frames = fps
        total_frames = title_frames + init_frames + move_frames + end_frames

        tmpdir = tempfile.mkdtemp(prefix="chess_export_")
        frame_path = os.path.join(tmpdir, "frame_%06d.png")

        fname = sanitize_filename(rec.get('display_title', rec.get('name', 'opening')))
        out_dir = EXPORT_DIR; os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{fname}.mp4")

        frame_idx = 0

        if title_frames > 0:
            title_img = render_export_title_card(
                rec.get('display_title', rec.get('name', '?')),
                rec.get('eco', '?'), num_moves, w, h, bg)
            for _ in range(title_frames):
                title_img.save(frame_path % frame_idx)
                frame_idx += 1
                self.progress.emit(frame_idx, total_frames)

        b = chess.Board()
        for _ in range(init_frames):
            img = render_composite_frame(
                b, notations, -1, width=w, height=h, sq_size=sq,
                theme=theme, opening_name=rec.get('display_title', ''),
                eco=rec.get('eco', ''), bg_color=bg)
            img.save(frame_path % frame_idx); frame_idx += 1
            self.progress.emit(frame_idx, total_frames)

        b = chess.Board()
        for mi in range(num_moves):
            uci = uci_moves[mi]
            try:
                move = chess.Move.from_uci(uci)
                if move not in b.legal_moves: break
            except Exception: break

            fr_sq = move.from_square; to_sq = move.to_square
            bfr = 7 - chess.square_rank(fr_sq); bfc = chess.square_file(fr_sq)
            btr = 7 - chess.square_rank(to_sq); btc = chess.square_file(to_sq)

            is_ep = b.is_en_passant(move)
            if is_ep:
                ep_cap_sq = chess.square(chess.square_file(to_sq),
                                         chess.square_rank(fr_sq))
                cap = b.piece_at(ep_cap_sq)
            else:
                cap = b.piece_at(to_sq)
            captured = cap.symbol() if cap else '.'
            piece_obj = chess.Piece(b.piece_at(fr_sq).piece_type,
                                    b.piece_at(fr_sq).color)

            for fi in range(frames_per_anim):
                t = fi / max(1, frames_per_anim - 1)
                t_ease = 1.0 - (1.0 - t) ** 3
                anim_st = {'from': (bfr, bfc), 'to': (btr, btc),
                           'piece_obj': piece_obj, 'captured': captured,
                           'progress': t_ease}
                last_mv = ((bfr, bfc), (btr, btc))
                img = render_composite_frame(
                    b, notations, mi, last_move=last_mv,
                    anim_state=anim_st, width=w, height=h, sq_size=sq,
                    theme=theme, opening_name=rec.get('display_title', ''),
                    eco=rec.get('eco', ''), bg_color=bg)
                img.save(frame_path % frame_idx); frame_idx += 1
                self.progress.emit(frame_idx, total_frames)

            b.push(move)
            last_mv = ((bfr, bfc), (btr, btc))
            chk = []
            if b.is_check():
                king_sq = b.king(b.turn)
                chk = [(7 - chess.square_rank(king_sq), chess.square_file(king_sq))]

            for _ in range(frames_per_pause):
                img = render_composite_frame(
                    b, notations, mi, last_move=last_mv,
                    check_squares=chk, width=w, height=h, sq_size=sq,
                    theme=theme, opening_name=rec.get('display_title', ''),
                    eco=rec.get('eco', ''), bg_color=bg)
                img.save(frame_path % frame_idx); frame_idx += 1
                self.progress.emit(frame_idx, total_frames)

        if end_frames > 0:
            chk = []
            if b.is_check():
                king_sq = b.king(b.turn)
                chk = [(7 - chess.square_rank(king_sq), chess.square_file(king_sq))]
            last_mv_board = None
            if b.move_stack:
                lm = b.peek()
                last_mv_board = ((7 - chess.square_rank(lm.from_square),
                                  chess.square_file(lm.from_square)),
                                 (7 - chess.square_rank(lm.to_square),
                                  chess.square_file(lm.to_square)))
            for _ in range(end_frames):
                img = render_composite_frame(
                    b, notations, num_moves - 1, last_move=last_mv_board,
                    check_squares=chk, width=w, height=h, sq_size=sq,
                    theme=theme, opening_name=rec.get('display_title', ''),
                    eco=rec.get('eco', ''), bg_color=bg)
                img.save(frame_path % frame_idx); frame_idx += 1
                self.progress.emit(frame_idx, total_frames)

        if not HAS_FFMPEG:
            shutil.rmtree(tmpdir, ignore_errors=True)
            self.error.emit("ffmpeg not found — install ffmpeg and add to PATH")
            return

        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", frame_path,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", str(cfg.ffmpeg_crf),
            "-preset", cfg.ffmpeg_preset,
            "-movflags", "+faststart",
            out_path
        ]
        log(f"FFmpeg command: {' '.join(cmd)}", "EXPORT")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log(f"FFmpeg error: {result.stderr[-500:]}", "EXPORT")
            shutil.rmtree(tmpdir, ignore_errors=True)
            self.error.emit(f"FFmpeg error: {result.stderr[:200]}")
            return

        shutil.rmtree(tmpdir, ignore_errors=True)
        log(f"Export complete: {out_path}", "EXPORT")
        self.finished.emit(out_path)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

_LIST_CHUNK_SIZE = 200          # items per lazy-load batch
_SEARCH_DEBOUNCE_MS = 250      # debounce delay for search typing

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("♟ Chess Openings Explorer")
        self.setMinimumSize(1200, 780)

        self.engine = ChessEngine()
        self.sound_mgr = SoundManager()
        self.data = DataProvider()
        self.export_tracker = ExportTracker(EXPORT_MANIFEST_PATH)
        self.export_cfg = ExportConfig()
        self.current_opening = None
        self.move_index = 0
        self._uci_sequence = []
        self._notations = []
        self._export_worker = None

        # Auto-play state
        self._auto_playing = False
        self._loop_enabled = True
        self._auto_delay = 800
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._auto_advance)

        # Chunked-list state
        self._list_offset = 0        # how many items currently in the list
        self._total_count = 0        # total available (slim or search)
        self._search_mode = False
        self._search_query = ""
        self._list_loading = False   # guard against recursive loads

        # Debounced search timer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._do_search)

        self._build_ui()

        self._load_initial_list()
        QTimer.singleShot(100, self._auto_load_bundled)

    # ══════════════════════════════════════════════════════════════════════════
    #  UI CONSTRUCTION
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QHBoxLayout(central); root.setContentsMargins(6, 6, 6, 6)

        # ── LEFT: openings list ────────────────────────────────────────────
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0)
        self.search_edit = QLineEdit(); self.search_edit.setPlaceholderText("Search openings…")
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        ll.addWidget(self.search_edit)

        self.openings_list = QListWidget()
        self.openings_list.currentRowChanged.connect(self._on_opening_selected)
        # NEW: scroll-to-load-more
        self.openings_list.verticalScrollBar().valueChanged.connect(
            self._on_list_scroll)
        ll.addWidget(self.openings_list)

        # NEW: list count indicator
        self.list_count_label = QLabel("0 / 0 openings")
        self.list_count_label.setAlignment(Qt.AlignCenter)
        self.list_count_label.setStyleSheet("color: #888; font-size: 10px; padding: 2px;")
        ll.addWidget(self.list_count_label)

        import_btn = QPushButton("📂 Import Openings…")
        import_btn.clicked.connect(self._on_import)
        ll.addWidget(import_btn)
        left.setMaximumWidth(280)

        # ── CENTER: board + nav ────────────────────────────────────────────
        center = QWidget(); cl = QVBoxLayout(center); cl.setContentsMargins(0, 0, 0, 0)
        self.board_widget = ChessBoardWidget(self.engine, self.sound_mgr)
        self.board_widget.move_made.connect(self._on_move_made)
        cl.addWidget(self.board_widget, alignment=Qt.AlignCenter)

        # Row 1: Transport controls
        nav1 = QHBoxLayout(); nav1.setSpacing(3)
        b = QPushButton("⏮"); b.setFixedWidth(34); b.setToolTip("Go to start")
        b.clicked.connect(self._go_start); nav1.addWidget(b)
        b = QPushButton("◀"); b.setFixedWidth(34); b.setToolTip("Step back")
        b.clicked.connect(self._go_prev); nav1.addWidget(b)
        self.play_btn = QPushButton("▶"); self.play_btn.setFixedWidth(46)
        self.play_btn.setToolTip("Play opening animation")
        self._style_play_btn(False)
        self.play_btn.clicked.connect(self._toggle_play)
        nav1.addWidget(self.play_btn)
        b = QPushButton("▶"); b.setFixedWidth(34); b.setToolTip("Step forward")
        b.clicked.connect(self._go_next); nav1.addWidget(b)
        b = QPushButton("⏭"); b.setFixedWidth(34); b.setToolTip("Go to end")
        b.clicked.connect(self._go_end); nav1.addWidget(b)
        self.loop_btn = QPushButton("🔁"); self.loop_btn.setFixedWidth(34)
        self.loop_btn.setCheckable(True); self.loop_btn.setChecked(True)
        self.loop_btn.setToolTip("Loop playback")
        self.loop_btn.toggled.connect(self._on_loop_toggle)
        nav1.addWidget(self.loop_btn)
        b = QPushButton("🔄"); b.setFixedWidth(34); b.setToolTip("Flip board")
        b.clicked.connect(self._flip_board); nav1.addWidget(b)
        nav1.addSpacing(8)
        nav1.addWidget(QLabel("Anim:"))
        self.anim_slider = QSlider(Qt.Horizontal)
        self.anim_slider.setRange(0, 500); self.anim_slider.setValue(250)
        self.anim_slider.setFixedWidth(80)
        self.anim_slider.valueChanged.connect(
            lambda v: setattr(self.board_widget, 'anim_speed', v))
        nav1.addWidget(self.anim_slider)
        nav1.addSpacing(4)
        nav1.addWidget(QLabel("Gap:"))
        self.gap_slider = QSlider(Qt.Horizontal)
        self.gap_slider.setRange(100, 3000); self.gap_slider.setValue(800)
        self.gap_slider.setFixedWidth(80)
        self._gap_label = QLabel("0.8s"); self._gap_label.setFixedWidth(32)
        self.gap_slider.valueChanged.connect(self._on_gap_changed)
        nav1.addWidget(self.gap_slider); nav1.addWidget(self._gap_label)
        cl.addLayout(nav1)

        # Row 2: Move scrubber
        nav2 = QHBoxLayout()
        self.move_scrubber = QSlider(Qt.Horizontal)
        self.move_scrubber.setRange(0, 0); self.move_scrubber.setValue(0)
        self.move_scrubber.sliderMoved.connect(self._on_scrubber_moved)
        nav2.addWidget(self.move_scrubber, 1)
        self.scrubber_label = QLabel("0 / 0")
        self.scrubber_label.setFixedWidth(70)
        self.scrubber_label.setAlignment(Qt.AlignCenter)
        nav2.addWidget(self.scrubber_label)
        cl.addLayout(nav2)

        # ── RIGHT: info + export ───────────────────────────────────────────
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0)
        right.setMaximumWidth(310)

        # Info
        ig = QGroupBox("Opening"); il = QVBoxLayout(ig)
        self.lbl_name = QLabel("—"); self.lbl_name.setWordWrap(True)
        self.lbl_name.setFont(QFont("Sans", 11, QFont.Bold))
        self.lbl_eco = QLabel(""); self.lbl_epd = QLabel("")
        self.lbl_export_status = QLabel("Not exported")
        self.lbl_export_status.setWordWrap(True)
        self.lbl_export_status.setStyleSheet("color: #888888; font-size: 10px;")
        il.addWidget(self.lbl_name); il.addWidget(self.lbl_eco)
        il.addWidget(self.lbl_epd); il.addWidget(self.lbl_export_status)
        rl.addWidget(ig)

        # Moves
        mg = QGroupBox("Moves"); ml = QVBoxLayout(mg)
        self.moves_text = QTextEdit(); self.moves_text.setReadOnly(True)
        self.moves_text.setMaximumHeight(140)
        self.moves_text.setFont(QFont("Sans", 10))
        ml.addWidget(self.moves_text)
        rl.addWidget(mg)

        # Settings
        sg = QGroupBox("Settings"); sl = QVBoxLayout(sg)
        self.theme_combo = QComboBox(); self.theme_combo.addItems(THEMES.keys())
        self.theme_combo.currentTextChanged.connect(self._on_theme)
        sl.addWidget(QLabel("Theme:")); sl.addWidget(self.theme_combo)
        self.sound_check = QCheckBox("Sound"); self.sound_check.setChecked(True)
        self.sound_check.toggled.connect(self.sound_mgr.set_enabled)
        sl.addWidget(self.sound_check)
        self.vol_slider = QSlider(Qt.Horizontal); self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(70)
        self.vol_slider.valueChanged.connect(lambda v: self.sound_mgr.set_volume(v / 100.0))
        sl.addWidget(QLabel("Volume:")); sl.addWidget(self.vol_slider)
        rl.addWidget(sg)

        # ── EXPORT PANEL
        eg = QGroupBox("🎬 Export MP4"); el = QVBoxLayout(eg)
        el.addWidget(QLabel("Resolution:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(EXPORT_PRESETS.keys())
        self.preset_combo.setCurrentText(self.export_cfg.preset_name)
        self.preset_combo.currentTextChanged.connect(self._on_preset)
        el.addWidget(self.preset_combo)
        self.title_check = QCheckBox("Title screen"); self.title_check.setChecked(True)
        el.addWidget(self.title_check)
        th = QHBoxLayout(); th.addWidget(QLabel("Duration:"))
        self.title_spin = QSpinBox(); self.title_spin.setRange(1, 15)
        self.title_spin.setValue(3); self.title_spin.setSuffix("s")
        th.addWidget(self.title_spin); el.addLayout(th)
        self.end_check = QCheckBox("End hold"); self.end_check.setChecked(True)
        el.addWidget(self.end_check)
        eh = QHBoxLayout(); eh.addWidget(QLabel("Duration:"))
        self.end_spin = QSpinBox(); self.end_spin.setRange(1, 15)
        self.end_spin.setValue(3); self.end_spin.setSuffix("s")
        eh.addWidget(self.end_spin); el.addLayout(eh)
        el.addWidget(QLabel("Move animation:"))
        ah = QHBoxLayout()
        self.anim_dur_slider = QSlider(Qt.Horizontal)
        self.anim_dur_slider.setRange(2, 30); self.anim_dur_slider.setValue(5)
        self.anim_dur_label = QLabel("0.5s")
        self.anim_dur_slider.valueChanged.connect(
            lambda v: self.anim_dur_label.setText(f"{v/10:.1f}s"))
        ah.addWidget(self.anim_dur_slider); ah.addWidget(self.anim_dur_label)
        el.addLayout(ah)
        el.addWidget(QLabel("Pause after move:"))
        ph = QHBoxLayout()
        self.pause_slider = QSlider(Qt.Horizontal)
        self.pause_slider.setRange(2, 30); self.pause_slider.setValue(8)
        self.pause_label = QLabel("0.8s")
        self.pause_slider.valueChanged.connect(
            lambda v: self.pause_label.setText(f"{v/10:.1f}s"))
        ph.addWidget(self.pause_slider); ph.addWidget(self.pause_label)
        el.addLayout(ph)
        qh = QHBoxLayout(); qh.addWidget(QLabel("CRF:"))
        self.crf_spin = QSpinBox(); self.crf_spin.setRange(15, 35)
        self.crf_spin.setValue(20)
        qh.addWidget(self.crf_spin); el.addLayout(qh)
        self.export_btn = QPushButton("▶  Export MP4")
        self.export_btn.setStyleSheet(
            "QPushButton{background:#2a82da;color:#fff;font-weight:bold;"
            "padding:8px;border-radius:4px}"
            "QPushButton:hover{background:#3a92ea}"
            "QPushButton:disabled{background:#555}")
        self.export_btn.clicked.connect(self._on_export)
        el.addWidget(self.export_btn)
        self.export_progress = QProgressBar(); self.export_progress.setVisible(False)
        el.addWidget(self.export_progress)
        self.export_status = QLabel(""); self.export_status.setWordWrap(True)
        el.addWidget(self.export_status)
        rl.addWidget(eg)
        rl.addStretch()

        # ── Assemble splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left); splitter.addWidget(center); splitter.addWidget(right)
        splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        root.addWidget(splitter)

        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.status.showMessage("Ready")

    # ══════════════════════════════════════════════════════════════════════════
    #  CHUNKED LIST LOADING
    # ══════════════════════════════════════════════════════════════════════════

    def _load_initial_list(self):
        """Clear the list and load the first chunk."""
        self.openings_list.clear()
        self._list_offset = 0
        self._list_loading = False

        if self._search_mode:
            self._total_count = self.data.search_openings_count(self._search_query)
            items = self.data.search_openings_sliced(
                self._search_query, 0, _LIST_CHUNK_SIZE)
        else:
            self._total_count = self.data.get_opening_count()
            items = self.data.get_openings_slice(0, _LIST_CHUNK_SIZE)

        self._populate_list_items(items)
        self._list_offset = len(items)
        self._update_list_count()

    def _load_more_items(self):
        """Append the next chunk to the list (scroll-to-load-more)."""
        if self._list_loading or self._list_offset >= self._total_count:
            return
        self._list_loading = True

        if self._search_mode:
            items = self.data.search_openings_sliced(
                self._search_query, self._list_offset, _LIST_CHUNK_SIZE)
        else:
            items = self.data.get_openings_slice(
                self._list_offset, _LIST_CHUNK_SIZE)

        self._populate_list_items(items)
        self._list_offset += len(items)
        self._list_loading = False
        self._update_list_count()

    def _populate_list_items(self, items):
        """Create QListWidgetItems for a batch of slim records."""
        exported_ids = self.export_tracker.exported_ids   # set of str ids
        for row in items:
            title = str(row.get('display_title', row.get('name', '?')))
            item_id = int(row.get('id', 0))
            if str(item_id) in exported_ids:
                title += "  🎬"
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, item_id)
            self.openings_list.addItem(item)

    def _update_list_count(self):
        showing = self.openings_list.count()
        if self._search_mode:
            self.list_count_label.setText(
                f"🔍 {showing:,} / {self._total_count:,} results")
            self.status.showMessage(
                f"Search “{self._search_query}”: {showing:,}/{self._total_count:,}")
        else:
            if self._total_count == 0:
                self.list_count_label.setText("No openings loaded")
            elif showing < self._total_count:
                self.list_count_label.setText(
                    f"{showing:,} / {self._total_count:,} openings  (scroll ↓)")
            else:
                self.list_count_label.setText(
                    f"{self._total_count:,} openings ✓")
            self.status.showMessage(
                f"{showing:,}/{self._total_count:,} openings loaded")

    def _on_list_scroll(self, value):
        """When the user scrolls near the bottom, load more items."""
        sb = self.openings_list.verticalScrollBar()
        # Trigger when within 30 pixels of the bottom
        if value >= sb.maximum() - 30:
            self._load_more_items()

    # ══════════════════════════════════════════════════════════════════════════
    #  DEBOUNCED SEARCH
    # ══════════════════════════════════════════════════════════════════════════

    def _on_search_text_changed(self, text):
        """Restart the debounce timer on every keystroke."""
        self._search_timer.start()

    def _do_search(self):
        """Actually perform the search (called after debounce)."""
        query = self.search_edit.text().strip()
        if query:
            self._search_mode = True
            self._search_query = query
        else:
            self._search_mode = False
            self._search_query = ""
        self._load_initial_list()

    # ══════════════════════════════════════════════════════════════════════════
    #  PLAY-BUTTON STYLING
    # ══════════════════════════════════════════════════════════════════════════

    def _style_play_btn(self, is_playing):
        if is_playing:
            self.play_btn.setText("⏸"); self.play_btn.setToolTip("Pause")
            self.play_btn.setStyleSheet(
                "QPushButton{background:#da822a;color:#fff;font-weight:bold;"
                "font-size:15px;padding:4px;border-radius:4px}"
                "QPushButton:hover{background:#ea924a}")
        else:
            self.play_btn.setText("▶"); self.play_btn.setToolTip("Play opening animation")
            self.play_btn.setStyleSheet(
                "QPushButton{background:#2a82da;color:#fff;font-weight:bold;"
                "font-size:15px;padding:4px;border-radius:4px}"
                "QPushButton:hover{background:#3a92ea}")

    # ══════════════════════════════════════════════════════════════════════════
    #  AUTO-PLAY CONTROLS
    # ══════════════════════════════════════════════════════════════════════════

    def _toggle_play(self):
        if self._auto_playing: self._stop_auto_play()
        else: self._start_auto_play()

    def _start_auto_play(self):
        if not self._uci_sequence: return
        if self.move_index >= len(self._uci_sequence):
            self.engine.reset(); self.move_index = 0
            self._update_moves_display(); self._update_scrubber()
            self.board_widget.update()
        self._auto_playing = True
        self.board_widget.auto_playing = True
        self._style_play_btn(True)
        self._auto_advance()

    def _stop_auto_play(self):
        self._auto_playing = False; self._auto_timer.stop()
        self.board_widget.auto_playing = False; self._style_play_btn(False)

    def _auto_advance(self):
        if not self._auto_playing: return
        if self.move_index >= len(self._uci_sequence):
            if self._loop_enabled:
                self.engine.reset(); self.move_index = 0
                self._update_moves_display(); self._update_scrubber()
                self.board_widget.update()
                self._auto_timer.start(max(600, self._auto_delay))
            else:
                self._stop_auto_play()
            return
        self._apply_next_move_animated()

    def _schedule_next_auto(self):
        self._auto_timer.start(self._auto_delay)

    def _apply_next_move_animated(self):
        if self.move_index >= len(self._uci_sequence): return
        uci = self._uci_sequence[self.move_index]
        info = self.engine.make_move_uci(uci)
        if info:
            self.move_index += 1
            self._update_moves_display(); self._update_scrubber()
            if self.board_widget.anim_speed > 0:
                self.board_widget.start_animation(
                    info['from'][0], info['from'][1],
                    info['to'][0], info['to'][1],
                    info['piece_obj'], info['captured'], info['notation'])
            else:
                self.board_widget.update()
                if self._auto_playing: self._schedule_next_auto()
        else:
            self._stop_auto_play()

    def _on_loop_toggle(self, checked):
        self._loop_enabled = checked
        self.loop_btn.setStyleSheet(
            "QPushButton{background:#2a82da;color:#fff;border-radius:4px;"
            "font-size:13px;padding:3px}" if checked else
            "QPushButton{background:#555;color:#aaa;border-radius:4px;"
            "font-size:13px;padding:3px}")

    def _on_gap_changed(self, value):
        self._auto_delay = value
        self._gap_label.setText(f"{value/1000:.1f}s")

    # ══════════════════════════════════════════════════════════════════════════
    #  MOVE DISPLAY
    # ══════════════════════════════════════════════════════════════════════════

    def _update_moves_display(self):
        if not self._notations:
            self.moves_text.setHtml('<span style="color:#666;">No moves</span>')
            return
        parts = []
        for i, notation in enumerate(self._notations):
            if i % 2 == 0:
                move_num = i // 2 + 1
                parts.append(f'<span style="color:#7777aa;">{move_num}.</span> ')
            if i < self.move_index:
                if i == self.move_index - 1:
                    parts.append(
                        f'<span style="background:#2a82da;color:#fff;'
                        f'padding:1px 5px;border-radius:3px;font-weight:bold;">'
                        f'{notation}</span> ')
                else:
                    parts.append(f'{notation} ')
            else:
                parts.append(
                    f'<span style="color:#555566;">{notation}</span> ')
        self.moves_text.setHtml(''.join(parts))

    # ══════════════════════════════════════════════════════════════════════════
    #  SCRUBBER
    # ══════════════════════════════════════════════════════════════════════════

    def _update_scrubber(self):
        n = len(self._uci_sequence)
        self.move_scrubber.blockSignals(True)
        self.move_scrubber.setRange(0, n); self.move_scrubber.setValue(self.move_index)
        self.move_scrubber.blockSignals(False)
        self.scrubber_label.setText(f"{self.move_index} / {n}")

    def _on_scrubber_moved(self, value):
        self._stop_auto_play()
        self.engine.reset(); self.move_index = 0
        for i in range(value):
            info = self.engine.make_move_uci(self._uci_sequence[i])
            if info: self.move_index += 1
            else: break
        self._update_moves_display(); self._update_scrubber()
        self.board_widget.update()

    # ══════════════════════════════════════════════════════════════════════════
    #  AUTO-LOAD
    # ══════════════════════════════════════════════════════════════════════════

    def _auto_load_bundled(self):
        if not os.path.exists(LICHESS_DB_PATH):
            self.status.showMessage("No bundled DB — use Import to load openings")
            return
        if self.data.get_opening_count() > 0:
            self.status.showMessage(f"{self.data.get_opening_count():,} openings ready ✓")
            self._load_initial_list()          # refresh with chunked loading
            return
        self.status.showMessage("Loading bundled openings database…")
        QApplication.processEvents()

        def _w():
            try:
                for n, t in self.data.stream_import('openings', load_openings(LICHESS_DB_PATH)):
                    log(f"Auto-load: +{n}  ({t})", "IMPORT")
            except Exception as e:
                log(f"Auto-load error: {e}", "ERROR")
                QTimer.singleShot(0, lambda: self.status.showMessage(f"Load error: {e}"))
                return
            QTimer.singleShot(0, self._on_auto_load_done)

        threading.Thread(target=_w, daemon=True).start()

    def _on_auto_load_done(self):
        self._load_initial_list()
        c = self.data.get_opening_count()
        self.status.showMessage(f"{c:,} openings loaded from lichess DB ✓")

    # ══════════════════════════════════════════════════════════════════════════
    #  OPENINGS LIST — SELECTION
    # ══════════════════════════════════════════════════════════════════════════

    def _on_opening_selected(self, row):
        if row < 0: return
        item = self.openings_list.item(row)
        opening_id = item.data(Qt.UserRole)
        rec = self.data.get_opening(opening_id)
        if not rec: return
        self.current_opening = rec; self._display_opening(rec)

        # Update export status indicator
        export_info = self.export_tracker.get_info(rec.get('id'))
        if export_info:
            ts = export_info.get('timestamp', '')
            path = export_info.get('path', '')
            self.lbl_export_status.setText(f"🎬 Exported {ts}\n{path}")
            self.lbl_export_status.setStyleSheet("color: #66ff66; font-size: 10px;")
        else:
            self.lbl_export_status.setText("Not exported")
            self.lbl_export_status.setStyleSheet("color: #888888; font-size: 10px;")

    def _display_opening(self, rec):
        self.lbl_name.setText(rec.get('display_title', rec.get('name', '?')))
        self.lbl_eco.setText(f"ECO: {rec.get('eco', '?')}")
        self.lbl_epd.setText(f"EPD: {rec.get('epd', '—')}")

        self._stop_auto_play()

        uci = rec.get('uci_moves', [])
        if isinstance(uci, str):
            try: uci = json.loads(uci)
            except Exception: uci = uci.split()

        temp_board = chess.Board()
        self._notations = []; valid_uci = []
        for u in uci:
            try:
                move = chess.Move.from_uci(u)
                if move in temp_board.legal_moves:
                    self._notations.append(temp_board.san(move))
                    temp_board.push(move); valid_uci.append(u)
                else: break
            except Exception: break
        self._uci_sequence = valid_uci

        self.engine.reset(); self.move_index = 0
        self._update_moves_display(); self._update_scrubber()
        self.board_widget.update()

        if self._uci_sequence:
            QTimer.singleShot(450, self._start_auto_play)

    # ══════════════════════════════════════════════════════════════════════════
    #  SCRUBBER
    # ══════════════════════════════════════════════════════════════════════════

    def _update_scrubber(self):
        n = len(self._uci_sequence)
        self.move_scrubber.blockSignals(True)
        self.move_scrubber.setRange(0, n); self.move_scrubber.setValue(self.move_index)
        self.move_scrubber.blockSignals(False)
        self.scrubber_label.setText(f"{self.move_index} / {n}")

    def _on_scrubber_moved(self, value):
        self._stop_auto_play()
        self.engine.reset(); self.move_index = 0
        for i in range(value):
            info = self.engine.make_move_uci(self._uci_sequence[i])
            if info: self.move_index += 1
            else: break
        self._update_moves_display(); self._update_scrubber()
        self.board_widget.update()

    # ══════════════════════════════════════════════════════════════════════════
    #  NAVIGATION
    # ══════════════════════════════════════════════════════════════════════════

    def _go_start(self):
        if self.board_widget.animating: return
        self._stop_auto_play()
        self.engine.reset(); self.move_index = 0
        self._update_moves_display(); self._update_scrubber()
        self.board_widget.update()

    def _go_prev(self):
        if self.board_widget.animating: return
        self._stop_auto_play()
        if self.engine.undo():
            self.move_index = max(0, self.move_index - 1)
            self._update_moves_display(); self._update_scrubber()
            self.board_widget.update()

    def _go_next(self):
        if self.board_widget.animating: return
        self._stop_auto_play()
        self._apply_next_move_animated()

    def _go_end(self):
        if self.board_widget.animating: return
        self._stop_auto_play()
        while self.move_index < len(self._uci_sequence):
            info = self.engine.make_move_uci(self._uci_sequence[self.move_index])
            if info: self.move_index += 1
            else: break
        self._update_moves_display(); self._update_scrubber()
        self.board_widget.update()

    def _flip_board(self): self.board_widget.flip()

    # ══════════════════════════════════════════════════════════════════════════
    #  MOVE-MADE HANDLER
    # ══════════════════════════════════════════════════════════════════════════

    def _on_move_made(self, notation):
        self.status.showMessage(f"Move: {notation}")
        if self._auto_playing:
            self._schedule_next_auto()

    # ══════════════════════════════════════════════════════════════════════════
    #  SETTINGS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_theme(self, name):
        if name in THEMES:
            self.board_widget.current_theme = THEMES[name]
            self.board_widget.update()

    # ══════════════════════════════════════════════════════════════════════════
    #  EXPORT
    # ══════════════════════════════════════════════════════════════════════════

    def _on_preset(self, name):
        self.export_cfg.apply_preset(name)

    def _on_export(self):
        if not self.current_opening:
            self.export_status.setText("Select an opening first")
            self.export_status.setStyleSheet("color: #ff6666")
            return
        if not HAS_FFMPEG:
            self.export_status.setText("ffmpeg not found — install and add to PATH")
            self.export_status.setStyleSheet("color: #ff6666")
            return
        if self._export_worker and self._export_worker.isRunning():
            return

        cfg = self.export_cfg
        cfg.title_enabled = self.title_check.isChecked()
        cfg.title_duration = self.title_spin.value()
        cfg.end_hold_enabled = self.end_check.isChecked()
        cfg.end_hold_duration = self.end_spin.value()
        cfg.move_anim_duration = self.anim_dur_slider.value() / 10.0
        cfg.pause_after_move = self.pause_slider.value() / 10.0
        cfg.ffmpeg_crf = self.crf_spin.value()
        theme = THEMES.get(cfg.theme_name, THEMES["Classic"])

        self._stop_auto_play()

        self.export_btn.setEnabled(False)
        self.export_progress.setVisible(True); self.export_progress.setValue(0)
        self.export_status.setText("Exporting…")
        self.export_status.setStyleSheet("color: #aaaaaa")

        self._export_worker = ExportWorker(self.current_opening, cfg, theme)
        self._export_worker.progress.connect(self._export_progress)
        self._export_worker.finished.connect(self._export_done)
        self._export_worker.error.connect(self._export_error)
        self._export_worker.start()

    def _export_progress(self, cur, total):
        self.export_progress.setMaximum(total); self.export_progress.setValue(cur)
        pct = cur * 100 // max(1, total)
        self.export_status.setText(f"Rendering frame {cur}/{total}  ({pct}%)")

    def _export_done(self, path):
        self.export_btn.setEnabled(True); self.export_progress.setVisible(False)
        if path and self.current_opening:
            # Record in manifest
            self.export_tracker.mark_exported(self.current_opening.get('id'), path)

            self.export_status.setText(f"✓ Saved: {path}")
            self.export_status.setStyleSheet("color: #66ff66")
            self.status.showMessage(f"Export complete: {path}")

            # Update info panel
            export_info = self.export_tracker.get_info(self.current_opening.get('id'))
            if export_info:
                ts = export_info.get('timestamp', '')
                self.lbl_export_status.setText(f"🎬 Exported {ts}\n{path}")
                self.lbl_export_status.setStyleSheet("color: #66ff66; font-size: 10px;")

            # Update just the current list item (avoid full reload)
            current_row = self.openings_list.currentRow()
            if current_row >= 0:
                item = self.openings_list.item(current_row)
                title = str(self.current_opening.get('display_title',
                            self.current_opening.get('name', '?')))
                if "🎬" not in item.text():
                    item.setText(title + "  🎬")
        elif not path:
            self.export_status.setText("Export failed — no output")
            self.export_status.setStyleSheet("color: #ff6666")

    def _export_error(self, msg):
        self.export_btn.setEnabled(True); self.export_progress.setVisible(False)
        self.export_status.setText(f"Error: {msg}")
        self.export_status.setStyleSheet("color: #ff6666")

    # ══════════════════════════════════════════════════════════════════════════
    #  IMPORT
    # ══════════════════════════════════════════════════════════════════════════

    def _on_import(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Openings", DATA_DIR,
            "Data Files (*.csv *.parquet *.pq *.duckdb *.db *.sqlite);;All Files (*)")
        if not path: return
        self.status.showMessage(f"Importing {path}…")
        QApplication.processEvents()

        def _w():
            try:
                for n, t in self.data.stream_import('openings', load_openings(path)):
                    log(f"Imported chunk: +{n} ({t})", "IMPORT")
            except Exception as e:
                log(f"Import error: {e}", "ERROR")
                QTimer.singleShot(0, lambda: self.status.showMessage(f"Import error: {e}"))
                return
            QTimer.singleShot(0, self._on_import_done)

        threading.Thread(target=_w, daemon=True).start()

    def _on_import_done(self):
        """Called after import completes — reload the list with fresh chunks."""
        self._search_mode = False
        self._search_query = ""
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self._load_initial_list()

    # ══════════════════════════════════════════════════════════════════════════
    #  CLEANUP
    # ══════════════════════════════════════════════════════════════════════════

    def closeEvent(self, e):
        self._stop_auto_play()
        if self._export_worker and self._export_worker.isRunning():
            self._export_worker.terminate(); self._export_worker.wait(3000)
        self.sound_mgr.cleanup()
        super().closeEvent(e)