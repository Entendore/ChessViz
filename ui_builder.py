"""Chess Video Maker Pro — UI Construction"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QDoubleSpinBox, QTextEdit, QGroupBox, QCheckBox,
    QLineEdit, QComboBox, QFormLayout, QStackedWidget, QTabWidget,
    QSplitter, QListWidget, QScrollArea, QProgressBar, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QToolBox, QFrame,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QShortcut, QKeySequence
from constants import (AI_MAP, THEMES, SOUND_THEMES, SOUND_DESIGNS,
                       SOUND_TYPES, ANIM_EASINGS, RESOLUTION_LIST,
                       DEFAULT_FPS, DEFAULT_HOLD, DEFAULT_RESOLUTION_INDEX)
from board_widget import ChessBoardWidget
from widgets import EvalBarWidget, PromotionWidget

# ── Shared stylesheet for pipeline progress bars ───────────────────
_PROGRESS_STYLE = """
    QProgressBar {
        border: 1px solid #3a3a40;
        border-radius: 4px;
        background-color: #1e1e22;
        text-align: center;
        color: #ddd;
        font-size: 11px;
        min-height: 18px;
    }
    QProgressBar::chunk {
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #2a6a8a, stop:1 #3a9aba);
        border-radius: 3px;
    }
"""
_PROGRESS_STYLE_GREEN = """
    QProgressBar {
        border: 1px solid #3a3a40;
        border-radius: 4px;
        background-color: #1e1e22;
        text-align: center;
        color: #ddd;
        font-size: 11px;
        min-height: 18px;
    }
    QProgressBar::chunk {
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #2a7a2a, stop:1 #3aba3a);
        border-radius: 3px;
    }
"""
_PROGRESS_STYLE_RED = """
    QProgressBar {
        border: 1px solid #3a3a40;
        border-radius: 4px;
        background-color: #1e1e22;
        text-align: center;
        color: #ddd;
        font-size: 11px;
        min-height: 18px;
    }
    QProgressBar::chunk {
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #8a2a2a, stop:1 #ba3a3a);
        border-radius: 3px;
    }
"""

def _make_progress_bar(style=_PROGRESS_STYLE):
    pb = QProgressBar()
    pb.setValue(0)
    pb.setTextVisible(True)
    pb.setFormat("%p%")
    pb.setStyleSheet(style)
    return pb


def build_ui(w):
    central = QWidget(); w.setCentralWidget(central)
    mh = QHBoxLayout(central); mh.setContentsMargins(6, 6, 6, 6)

    # ── Left: eval bar + board ─────────────────────────────────────
    left = QVBoxLayout(); left.setContentsMargins(0,0,0,0)
    lr = QHBoxLayout()
    w.eval_bar_widget = EvalBarWidget()
    w.board_widget = ChessBoardWidget()
    w.board_widget.squareClicked.connect(w._on_sq_click)
    lr.addWidget(w.eval_bar_widget); lr.addWidget(w.board_widget, stretch=1)
    left.addLayout(lr, stretch=1)
    w.promo_widget = PromotionWidget(); left.addWidget(w.promo_widget)

    # ── Center: tabs ────────────────────────────────────────────────
    center = QVBoxLayout()
    w.tabs = QTabWidget()
    _build_moves_tab(w); _build_db_tab(w); _build_assets_tab(w)
    center.addWidget(w.tabs)

    # ── Right: tabs ─────────────────────────────────────────────────
    w.right_tabs = QTabWidget(); w.right_tabs.setDocumentMode(True)
    _build_pipeline_tab(w)
    _build_battle_tab(w)
    _build_analysis_tab(w)
    _build_video_tab(w)
    _build_settings_tab(w)
    right = QVBoxLayout(); right.setContentsMargins(0,0,0,0)
    right.addWidget(w.right_tabs)

    sp = QSplitter(Qt.Horizontal)
    for l in (left, center, right):
        sw = QWidget(); sw.setLayout(l); sp.addWidget(sw)
    sp.setStretchFactor(0, 5); sp.setStretchFactor(1, 3); sp.setStretchFactor(2, 2)
    mh.addWidget(sp)


def build_menu(w):
    mb = w.menuBar()
    fm = mb.addMenu("&File")
    fm.addAction("New Game", QKeySequence("Ctrl+N"), w._new_game)
    fm.addAction("Load PGN…", QKeySequence("Ctrl+O"), w._load_pgn)
    fm.addSeparator()
    fm.addAction("Quick PGN → MP4", QKeySequence("Ctrl+Shift+E"), w._quick_pgn_to_mp4)
    fm.addSeparator()
    fm.addAction("Exit", QKeySequence("Ctrl+Q"), w.close)
    vm = mb.addMenu("&View")
    vm.addAction("Flip Board", QKeySequence("F"), w._flip_board)
    QShortcut(QKeySequence(Qt.Key_Left), w, w._go_prev)
    QShortcut(QKeySequence(Qt.Key_Right), w, w._go_next)
    QShortcut(QKeySequence(Qt.Key_Home), w, w._go_first)
    QShortcut(QKeySequence(Qt.Key_End), w, w._go_last)
    QShortcut(QKeySequence(Qt.Key_Space), w, w._toggle_play)


def _build_moves_tab(w):
    mw = QWidget(); ml = QVBoxLayout(mw)
    w.move_table = QTableWidget(); w.move_table.setColumnCount(3)
    w.move_table.setHorizontalHeaderLabels(["#", "White", "Black"])
    w.move_table.horizontalHeader().setStretchLastSection(True)
    w.move_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    w.move_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    w.move_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
    w.move_table.verticalHeader().setVisible(False)
    w.move_table.setSelectionBehavior(QAbstractItemView.SelectItems)
    w.move_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    w.move_table.currentCellChanged.connect(w._on_move_cell)
    w.move_table.setFont(QFont("Consolas", 11)); w.move_table.setShowGrid(False)
    w.move_table.setStyleSheet(
        "QTableWidget{background-color:#1e1e22;color:#ddd;border:none}"
        "QTableWidget::item{padding:4px;border-bottom:1px solid #2a2a30}"
        "QTableWidget::item:selected{background-color:#4a6fa5;color:white}"
        "QHeaderView::section{background-color:#2a2a30;color:#aaa;"
        "padding:4px;border:1px solid #3a3a40;font-weight:bold}")
    ml.addWidget(w.move_table, stretch=1)

    nav = QGridLayout()
    for i, (t, fn) in enumerate([
        ("⏮", w._go_first), ("◀", w._go_prev),
        ("▶", w._go_next), ("⏭", w._go_last)]):
        b = QPushButton(t); b.setFixedSize(52, 36); b.clicked.connect(fn)
        nav.addWidget(b, 0, i)
    w.btn_play = QPushButton("▶ Play"); w.btn_play.clicked.connect(w._toggle_play)
    nav.addWidget(w.btn_play, 0, 4, 1, 2)
    w.speed_slider = QSlider(Qt.Horizontal); w.speed_slider.setRange(1, 50)
    w.speed_slider.setValue(8)
    nav.addWidget(QLabel("Speed:"), 1, 0, 1, 2)
    nav.addWidget(w.speed_slider, 1, 2, 1, 4)
    ml.addLayout(nav)

    cg = QGroupBox("Annotation"); cl = QVBoxLayout(cg)
    w.anno_edit = QTextEdit(); w.anno_edit.setMaximumHeight(60)
    w.anno_edit.setPlaceholderText("Comment…"); cl.addWidget(w.anno_edit)
    ab = QPushButton("Apply Comment"); ab.clicked.connect(w._apply_comment)
    cl.addWidget(ab); ml.addWidget(cg)
    w.tabs.addTab(mw, "♜ Moves")


def _build_db_tab(w):
    dw = QWidget(); dl = QVBoxLayout(dw)
    fg = QGroupBox("PGN Database Folder"); fl = QVBoxLayout(fg)
    fr = QHBoxLayout()
    w.db_folder_edit = QLineEdit(); w.db_folder_edit.setPlaceholderText("Folder path…")
    fr.addWidget(w.db_folder_edit, stretch=1)
    bs = QPushButton("Set"); bs.clicked.connect(w._set_pgn_db_folder); fr.addWidget(bs)
    bsc = QPushButton("Scan"); bsc.clicked.connect(w._scan_pgn_db); fr.addWidget(bsc)
    fl.addLayout(fr); w.db_path_lbl = QLabel("Folder: None"); fl.addWidget(w.db_path_lbl)
    dl.addWidget(fg)
    w.db_list = QListWidget(); w.db_list.itemDoubleClicked.connect(w._load_selected_pgn_db)
    dl.addWidget(w.db_list, stretch=1)
    hl = QHBoxLayout()
    w.db_game_idx = QSpinBox(); w.db_game_idx.setRange(1, 100000); w.db_game_idx.setValue(1)
    hl.addWidget(QLabel("Game #:")); hl.addWidget(w.db_game_idx)
    lb = QPushButton("Load"); lb.clicked.connect(w._load_selected_pgn_db); hl.addWidget(lb)
    dl.addLayout(hl)

    ig = QGroupBox("PGN Input"); il = QVBoxLayout(ig)
    w.pgn_text_edit = QTextEdit(); w.pgn_text_edit.setMaximumHeight(100)
    w.pgn_text_edit.setPlaceholderText("Paste PGN…"); il.addWidget(w.pgn_text_edit)
    pr = QHBoxLayout()
    ltb = QPushButton("📋 Load Text"); ltb.clicked.connect(w._load_pgn_text); pr.addWidget(ltb)
    il.addLayout(pr)
    fhr = QHBoxLayout()
    w.pgn_file_edit = QLineEdit(); w.pgn_file_edit.setPlaceholderText("File path…")
    fhr.addWidget(w.pgn_file_edit, stretch=1)
    lfb = QPushButton("📄 Load"); lfb.clicked.connect(w._load_pgn_from_file); fhr.addWidget(lfb)
    il.addLayout(fhr); dl.addWidget(ig)
    w.tabs.addTab(dw, "📂 Database")


def _build_assets_tab(w):
    iw = QWidget(); il = QVBoxLayout(iw)
    fg = QGroupBox("Image Folder"); fl = QVBoxLayout(fg)
    fr = QHBoxLayout()
    w.img_folder_edit = QLineEdit(); w.img_folder_edit.setPlaceholderText("Image folder path…")
    fr.addWidget(w.img_folder_edit, stretch=1)
    bs = QPushButton("Set"); bs.clicked.connect(w._set_img_folder); fr.addWidget(bs)
    bsc = QPushButton("Scan"); bsc.clicked.connect(w._scan_img_db); fr.addWidget(bsc)
    fl.addLayout(fr); w.img_path_lbl = QLabel("Folder: None"); fl.addWidget(w.img_path_lbl)
    il.addWidget(fg)
    w.img_list = QListWidget(); w.img_list.setViewMode(QListWidget.IconMode)
    w.img_list.setIconSize(QSize(80, 80)); w.img_list.setResizeMode(QListWidget.Adjust)
    il.addWidget(w.img_list, stretch=1)
    og = QGroupBox("Add to Canvas"); ol = QFormLayout(og)
    w.ov_pos_combo = QComboBox()
    w.ov_pos_combo.addItems(["White Face", "Black Face", "Center Logo", "Watermark (BR)"])
    ol.addRow("Position:", w.ov_pos_combo)
    ab = QPushButton("➕ Add"); ab.clicked.connect(w._add_overlay); ol.addRow(ab)
    rb = QPushButton("🗑 Clear"); rb.clicked.connect(w._clear_overlays); ol.addRow(rb)
    il.addWidget(og)
    w.tabs.addTab(iw, "🖼 Assets")


# ════════════════════════════════════════════════════════════════════
#  Helper: build a simple Resolution + FPS + Hold row group
# ════════════════════════════════════════════════════════════════════
def _add_quality_controls(w, layout, prefix):
    """Add Resolution + FPS + Hold controls to a layout."""
    rr = QHBoxLayout(); rr.addWidget(QLabel("Resolution:"))
    res_combo = QComboBox(); res_combo.addItems(RESOLUTION_LIST)
    res_combo.setCurrentIndex(DEFAULT_RESOLUTION_INDEX)
    rr.addWidget(res_combo, stretch=1); layout.addLayout(rr)

    fr = QHBoxLayout(); fr.addWidget(QLabel("FPS:"))
    fps_spin = QSpinBox(); fps_spin.setRange(1, 60); fps_spin.setValue(DEFAULT_FPS)
    fr.addWidget(fps_spin); layout.addLayout(fr)

    hr = QHBoxLayout(); hr.addWidget(QLabel("Hold per move:"))
    hold_spin = QDoubleSpinBox(); hold_spin.setRange(0.3, 10.0)
    hold_spin.setValue(DEFAULT_HOLD); hold_spin.setSingleStep(0.1); hold_spin.setSuffix(" s")
    hr.addWidget(hold_spin); layout.addLayout(hr)

    setattr(w, f"{prefix}_res_combo", res_combo)
    setattr(w, f"{prefix}_fps_spin", fps_spin)
    setattr(w, f"{prefix}_hold_spin", hold_spin)
    return res_combo, fps_spin, hold_spin


# ════════════════════════════════════════════════════════════════════
#  Pipeline Tab — with cancel buttons and improved progress
# ════════════════════════════════════════════════════════════════════
def _build_pipeline_tab(w):
    sc = QScrollArea(); sc.setWidgetResizable(True)
    inner = QWidget()
    pl = QVBoxLayout(inner); pl.setContentsMargins(8, 8, 8, 8)

    # ── Quick PGN → MP4 ───────────────────────────────────────────
    pg = QGroupBox("📄 PGN → MP4 Pipeline")
    pgl = QVBoxLayout(pg)

    pgl.addWidget(QLabel("Load a PGN and export a video in one click."))
    pgl.addWidget(QLabel("The game must be loaded first (Database tab)."))

    hr = QHBoxLayout()
    w.quick_load_btn = QPushButton("📂 Load PGN File")
    w.quick_load_btn.clicked.connect(w._quick_load_pgn)
    hr.addWidget(w.quick_load_btn)
    w.quick_pgn_status = QLabel("No game loaded")
    w.quick_pgn_status.setStyleSheet("color:#999;font-size:11px")
    hr.addWidget(w.quick_pgn_status, stretch=1)
    pgl.addLayout(hr)

    # Output filename
    ofr = QHBoxLayout()
    ofr.addWidget(QLabel("Output:"))
    w.quick_output_edit = QLineEdit()
    w.quick_output_edit.setPlaceholderText("chess_video.mp4")
    w.quick_output_edit.setText("chess_pgn_video.mp4")
    ofr.addWidget(w.quick_output_edit, stretch=1)
    pgl.addLayout(ofr)

    _add_quality_controls(w, pgl, "quick")

    # Eval during capture
    w.quick_eval_chk = QCheckBox("🧠 Evaluate positions (Stockfish)")
    w.quick_eval_chk.setChecked(False)
    w.quick_eval_chk.setToolTip("Run Stockfish evaluation on each position during capture.\n"
                                "Adds eval bar values but slows capture significantly.")
    pgl.addWidget(w.quick_eval_chk)

    # Go + Cancel buttons
    btn_row = QHBoxLayout()
    w.quick_pgn_btn = QPushButton("🚀 PGN → MP4")
    w.quick_pgn_btn.setMinimumHeight(36)
    w.quick_pgn_btn.setStyleSheet(
        "QPushButton{background:#2a6a2a;color:white;font-size:13px;font-weight:bold;"
        "border-radius:6px;padding:6px}"
        "QPushButton:hover{background:#3a8a3a}"
        "QPushButton:disabled{background:#444;color:#888}")
    w.quick_pgn_btn.clicked.connect(w._quick_pgn_to_mp4)
    btn_row.addWidget(w.quick_pgn_btn, stretch=1)

    w.quick_pgn_cancel_btn = QPushButton("⏹ Cancel")
    w.quick_pgn_cancel_btn.setMinimumHeight(36)
    w.quick_pgn_cancel_btn.setEnabled(False)
    w.quick_pgn_cancel_btn.setStyleSheet(
        "QPushButton{background:#6a3a3a;color:white;font-size:12px;"
        "border-radius:6px;padding:6px}"
        "QPushButton:hover{background:#8a4a4a}"
        "QPushButton:disabled{background:#444;color:#888}")
    w.quick_pgn_cancel_btn.clicked.connect(w._cancel_quick_pgn)
    btn_row.addWidget(w.quick_pgn_cancel_btn)
    pgl.addLayout(btn_row)

    # Progress
    w.quick_progress_bar = _make_progress_bar(_PROGRESS_STYLE_GREEN)
    pgl.addWidget(w.quick_progress_bar)
    w.quick_status_lbl = QLabel("")
    w.quick_status_lbl.setStyleSheet("color:#aaa;font-size:11px")
    w.quick_status_lbl.setWordWrap(True)
    pgl.addWidget(w.quick_status_lbl)

    pl.addWidget(pg)

    # ── Quick AI vs AI → MP4 ──────────────────────────────────────
    ag = QGroupBox("⚔️ AI vs AI → MP4 Pipeline")
    agl = QVBoxLayout(ag)

    agl.addWidget(QLabel("Run an AI battle and auto-export to MP4."))

    # AI selection
    wrow = QHBoxLayout()
    wrow.addWidget(QLabel("White:"))
    w.quick_w_ai_combo = QComboBox(); w.quick_w_ai_combo.addItems(AI_MAP.values())
    wrow.addWidget(w.quick_w_ai_combo, stretch=1)
    w.quick_w_ai_str = QSpinBox(); w.quick_w_ai_str.setRange(1, 5000); w.quick_w_ai_str.setValue(3)
    wrow.addWidget(QLabel("Str:")); wrow.addWidget(w.quick_w_ai_str)
    agl.addLayout(wrow)

    brow = QHBoxLayout()
    brow.addWidget(QLabel("Black:"))
    w.quick_b_ai_combo = QComboBox(); w.quick_b_ai_combo.addItems(AI_MAP.values())
    w.quick_b_ai_combo.setCurrentIndex(1)
    brow.addWidget(w.quick_b_ai_combo, stretch=1)
    w.quick_b_ai_str = QSpinBox(); w.quick_b_ai_str.setRange(1, 5000); w.quick_b_ai_str.setValue(100)
    brow.addWidget(QLabel("Str:")); brow.addWidget(w.quick_b_ai_str)
    agl.addLayout(brow)

    # Max moves + delay
    mrow = QHBoxLayout()
    mrow.addWidget(QLabel("Max moves:"))
    w.quick_max_moves_spin = QSpinBox()
    w.quick_max_moves_spin.setRange(10, 300); w.quick_max_moves_spin.setValue(80)
    mrow.addWidget(w.quick_max_moves_spin)
    mrow.addWidget(QLabel("  Delay:"))
    w.quick_battle_delay = QSpinBox()
    w.quick_battle_delay.setRange(10, 5000); w.quick_battle_delay.setValue(200)
    w.quick_battle_delay.setSuffix(" ms")
    w.quick_battle_delay.setToolTip("Delay between AI moves during battle.\n"
                                    "Higher = slower but easier to follow.")
    mrow.addWidget(w.quick_battle_delay)
    agl.addLayout(mrow)

    # AI output filename
    aofr = QHBoxLayout()
    aofr.addWidget(QLabel("Output:"))
    w.quick_ai_output_edit = QLineEdit()
    w.quick_ai_output_edit.setPlaceholderText("chess_battle.mp4")
    w.quick_ai_output_edit.setText("chess_battle.mp4")
    aofr.addWidget(w.quick_ai_output_edit, stretch=1)
    agl.addLayout(aofr)

    _add_quality_controls(w, agl, "quick_ai")

    # Show eval during battle checkbox
    w.quick_ai_show_eval_chk = QCheckBox("📊 Show eval during battle")
    w.quick_ai_show_eval_chk.setChecked(True)
    w.quick_ai_show_eval_chk.setToolTip("Update the eval bar as the battle progresses.")
    agl.addWidget(w.quick_ai_show_eval_chk)

    # Go + Cancel buttons
    ai_btn_row = QHBoxLayout()
    w.quick_ai_btn = QPushButton("🚀 AI Battle → MP4")
    w.quick_ai_btn.setMinimumHeight(36)
    w.quick_ai_btn.setStyleSheet(
        "QPushButton{background:#6a2a2a;color:white;font-size:13px;font-weight:bold;"
        "border-radius:6px;padding:6px}"
        "QPushButton:hover{background:#8a3a3a}"
        "QPushButton:disabled{background:#444;color:#888}")
    w.quick_ai_btn.clicked.connect(w._quick_ai_to_mp4)
    ai_btn_row.addWidget(w.quick_ai_btn, stretch=1)

    w.quick_ai_cancel_btn = QPushButton("⏹ Cancel")
    w.quick_ai_cancel_btn.setMinimumHeight(36)
    w.quick_ai_cancel_btn.setEnabled(False)
    w.quick_ai_cancel_btn.setStyleSheet(
        "QPushButton{background:#6a3a3a;color:white;font-size:12px;"
        "border-radius:6px;padding:6px}"
        "QPushButton:hover{background:#8a4a4a}"
        "QPushButton:disabled{background:#444;color:#888}")
    w.quick_ai_cancel_btn.clicked.connect(w._cancel_quick_ai)
    ai_btn_row.addWidget(w.quick_ai_cancel_btn)
    agl.addLayout(ai_btn_row)

    # AI progress — two-phase: battle (0-50%) + export (50-100%)
    w.quick_ai_progress_bar = _make_progress_bar(_PROGRESS_STYLE_RED)
    agl.addWidget(w.quick_ai_progress_bar)
    w.quick_ai_phase_lbl = QLabel("")
    w.quick_ai_phase_lbl.setStyleSheet("color:#888;font-size:10px")
    agl.addWidget(w.quick_ai_phase_lbl)
    w.quick_ai_status_lbl = QLabel("")
    w.quick_ai_status_lbl.setStyleSheet("color:#aaa;font-size:11px")
    w.quick_ai_status_lbl.setWordWrap(True)
    agl.addWidget(w.quick_ai_status_lbl)

    pl.addWidget(ag)

    # ── Batch PGN → MP4 ──────────────────────────────────────────
    bg = QGroupBox("📁 Batch PGN → MP4")
    bgl = QVBoxLayout(bg)

    bgl.addWidget(QLabel("Render all games from a folder of PGN files."))

    ifr = QHBoxLayout()
    ifr.addWidget(QLabel("PGN Folder:"))
    w.batch_pgn_folder_edit = QLineEdit()
    w.batch_pgn_folder_edit.setPlaceholderText("Folder containing .pgn files...")
    ifr.addWidget(w.batch_pgn_folder_edit, stretch=1)
    w.batch_pgn_browse_btn = QPushButton("📂")
    w.batch_pgn_browse_btn.setFixedWidth(40)
    w.batch_pgn_browse_btn.clicked.connect(w._browse_batch_pgn_folder)
    ifr.addWidget(w.batch_pgn_browse_btn)
    bgl.addLayout(ifr)

    ofrr = QHBoxLayout()
    ofrr.addWidget(QLabel("Output Folder:"))
    w.batch_output_folder_edit = QLineEdit()
    w.batch_output_folder_edit.setPlaceholderText("Where to save MP4 files...")
    ofrr.addWidget(w.batch_output_folder_edit, stretch=1)
    w.batch_output_browse_btn = QPushButton("📂")
    w.batch_output_browse_btn.setFixedWidth(40)
    w.batch_output_browse_btn.clicked.connect(w._browse_batch_output_folder)
    ofrr.addWidget(w.batch_output_browse_btn)
    bgl.addLayout(ofrr)

    _add_quality_controls(w, bgl, "batch")

    w.batch_eval_chk = QCheckBox("🧠 Evaluate positions (Slower)")
    w.batch_eval_chk.setChecked(False)
    bgl.addWidget(w.batch_eval_chk)

    # Batch buttons
    batch_btn_row = QHBoxLayout()
    w.batch_start_btn = QPushButton("🚀 Start Batch Render")
    w.batch_start_btn.setMinimumHeight(36)
    w.batch_start_btn.setStyleSheet(
        "QPushButton{background:#2a4a6a;color:white;font-size:13px;font-weight:bold;"
        "border-radius:6px;padding:6px}"
        "QPushButton:hover{background:#3a6a8a}"
        "QPushButton:disabled{background:#444;color:#888}")
    w.batch_start_btn.clicked.connect(w._start_batch_pgn_export)
    batch_btn_row.addWidget(w.batch_start_btn, stretch=1)

    w.batch_cancel_btn = QPushButton("⏹ Cancel")
    w.batch_cancel_btn.setMinimumHeight(36)
    w.batch_cancel_btn.setEnabled(False)
    w.batch_cancel_btn.setStyleSheet(
        "QPushButton{background:#6a3a3a;color:white;font-size:12px;"
        "border-radius:6px;padding:6px}"
        "QPushButton:hover{background:#8a4a4a}"
        "QPushButton:disabled{background:#444;color:#888}")
    w.batch_cancel_btn.clicked.connect(w._cancel_batch)
    batch_btn_row.addWidget(w.batch_cancel_btn)
    bgl.addLayout(batch_btn_row)

    w.batch_progress_bar = _make_progress_bar()
    bgl.addWidget(w.batch_progress_bar)
    w.batch_status_lbl = QLabel("")
    w.batch_status_lbl.setStyleSheet("color:#aaa;font-size:11px")
    w.batch_status_lbl.setWordWrap(True)
    bgl.addWidget(w.batch_status_lbl)

    pl.addWidget(bg)

    pl.addStretch()
    sc.setWidget(inner)
    w.right_tabs.addTab(sc, "🚀 Pipeline")


def _build_battle_tab(w):
    sc = QScrollArea(); sc.setWidgetResizable(True)
    inner = QWidget(); bl = QVBoxLayout(inner); bl.setContentsMargins(8,8,8,8)

    vg = QGroupBox("⚔️ AI vs AI (Interactive)"); vl = QFormLayout(vg)
    w.white_ai_combo = QComboBox(); w.white_ai_combo.addItems(AI_MAP.values())
    vl.addRow("White:", w.white_ai_combo)
    w.white_ai_str = QSpinBox(); w.white_ai_str.setRange(1, 5000); w.white_ai_str.setValue(3)
    vl.addRow("W. Str:", w.white_ai_str)
    w.black_ai_combo = QComboBox(); w.black_ai_combo.addItems(AI_MAP.values())
    w.black_ai_combo.setCurrentIndex(1)
    vl.addRow("Black:", w.black_ai_combo)
    w.black_ai_str = QSpinBox(); w.black_ai_str.setRange(1, 5000); w.black_ai_str.setValue(100)
    vl.addRow("B. Str:", w.black_ai_str)
    w.battle_delay = QSpinBox(); w.battle_delay.setRange(50, 5000)
    w.battle_delay.setValue(500); w.battle_delay.setSuffix(" ms")
    vl.addRow("Delay:", w.battle_delay)
    br = QHBoxLayout()
    w.start_battle_btn = QPushButton("⚔️ Start")
    w.start_battle_btn.clicked.connect(w._start_ai_vs_ai)
    w.stop_battle_btn = QPushButton("⏹ Stop")
    w.stop_battle_btn.clicked.connect(w._stop_ai_vs_ai)
    w.stop_battle_btn.setEnabled(False)
    br.addWidget(w.start_battle_btn); br.addWidget(w.stop_battle_btn)
    vl.addRow(br)
    bl.addWidget(vg)

    og = QGroupBox("📁 Output"); ol = QVBoxLayout(og)
    w.auto_mp4_chk = QCheckBox("🎬 Auto-export MP4"); w.auto_mp4_chk.setChecked(True)
    ol.addWidget(w.auto_mp4_chk)
    w.save_png_chk = QCheckBox("🖼 Save PNGs"); ol.addWidget(w.save_png_chk)
    w.output_dir_lbl = QLabel("Output: mp4 files/"); ol.addWidget(w.output_dir_lbl)
    bl.addWidget(og)

    bl.addStretch(); sc.setWidget(inner)
    w.right_tabs.addTab(sc, "⚔️ Battle")


def _build_analysis_tab(w):
    sc = QScrollArea(); sc.setWidgetResizable(True)
    inner = QWidget(); al = QVBoxLayout(inner); al.setContentsMargins(8,8,8,8)

    ag = QGroupBox("🧠 AI Lab"); aal = QVBoxLayout(ag)
    er = QHBoxLayout(); er.addWidget(QLabel("Engine:"))
    w.ai_combo = QComboBox(); w.ai_combo.addItems(AI_MAP.values())
    w.ai_combo.currentTextChanged.connect(w._toggle_ai_ui)
    er.addWidget(w.ai_combo, stretch=1); aal.addLayout(er)

    w.ai_stack = QStackedWidget()
    mmw = QWidget(); mml = QFormLayout(mmw)
    w.mm_depth = QSpinBox(); w.mm_depth.setRange(1, 4); w.mm_depth.setValue(3)
    mml.addRow("Depth:", w.mm_depth); w.ai_stack.addWidget(mmw)
    mcw = QWidget(); mcl = QFormLayout(mcw)
    w.m_iters = QSpinBox(); w.m_iters.setRange(100, 5000)
    w.m_iters.setValue(500); w.m_iters.setSingleStep(100)
    mcl.addRow("Sims:", w.m_iters); w.ai_stack.addWidget(mcw)
    sfw = QWidget(); sfl = QFormLayout(sfw)
    w.engine_path_edit = QLineEdit(); w.engine_path_edit.setPlaceholderText("Stockfish path…")
    sfl.addRow("Path:", w.engine_path_edit); w.ai_stack.addWidget(sfw)
    aal.addWidget(w.ai_stack)

    w.run_ai_btn = QPushButton("🔬 Run"); w.run_ai_btn.clicked.connect(w._run_engine)
    aal.addWidget(w.run_ai_btn)

    evr = QHBoxLayout()
    w.eval_game_btn = QPushButton("📊 Eval Game")
    w.eval_game_btn.clicked.connect(w._start_batch_eval)
    w.stop_eval_btn = QPushButton("⏹ Stop")
    w.stop_eval_btn.clicked.connect(w._stop_batch_eval)
    w.stop_eval_btn.setEnabled(False)
    evr.addWidget(w.eval_game_btn); evr.addWidget(w.stop_eval_btn)
    aal.addLayout(evr)

    w.eval_label = QLabel("Eval: —")
    w.eval_label.setStyleSheet("font-weight:bold;font-size:13px")
    w.pv_label = QLabel("Nodes: —"); aal.addWidget(w.eval_label); aal.addWidget(w.pv_label)

    pr = QHBoxLayout()
    w.policy_chk = QCheckBox("Show Policy"); w.policy_chk.setChecked(True)
    w.clear_policy_btn = QPushButton("Clear")
    w.clear_policy_btn.clicked.connect(w._clear_policy)
    pr.addWidget(w.policy_chk); pr.addWidget(w.clear_policy_btn)
    aal.addLayout(pr); al.addWidget(ag)
    al.addStretch(); sc.setWidget(inner)
    w.right_tabs.addTab(sc, "🧠 Analysis")


def _build_video_tab(w):
    main_splitter = QSplitter(Qt.Vertical)

    # ── TOP: Video Preview ─────────────────────────────────────────
    preview_widget = QWidget(); pvl = QVBoxLayout(preview_widget)
    pvl.setContentsMargins(4,4,4,4)
    pg = QGroupBox("📹 Video Preview"); pll = QVBoxLayout(pg)

    w.preview_display = QLabel(); w.preview_display.setAlignment(Qt.AlignCenter)
    w.preview_display.setMinimumSize(320, 180)
    w.preview_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    w.preview_display.setStyleSheet(
        "QLabel{background:#1a1a1e;border:1px solid #3a3a40;"
        "border-radius:4px;color:#555;font-size:11px}")
    w.preview_display.setText("📹 No preview")
    pll.addWidget(w.preview_display, stretch=1)

    tb = QHBoxLayout(); tb.setSpacing(3)
    w.preview_play_btn = QPushButton("▶"); w.preview_play_btn.setFixedSize(30, 24)
    w.preview_play_btn.setEnabled(False)
    w.preview_play_btn.clicked.connect(w._toggle_preview_play); tb.addWidget(w.preview_play_btn)
    w.preview_stop_btn = QPushButton("⏹"); w.preview_stop_btn.setFixedSize(30, 24)
    w.preview_stop_btn.setEnabled(False)
    w.preview_stop_btn.clicked.connect(w._stop_preview); tb.addWidget(w.preview_stop_btn)
    w.preview_slider = QSlider(Qt.Horizontal); w.preview_slider.setRange(0, 0)
    w.preview_slider.sliderMoved.connect(w._scrub_preview)
    tb.addWidget(w.preview_slider, stretch=1)
    w.preview_time_lbl = QLabel("0/0"); w.preview_time_lbl.setFixedWidth(72)
    w.preview_time_lbl.setAlignment(Qt.AlignCenter)
    w.preview_time_lbl.setStyleSheet("color:#999;font-size:10px")
    tb.addWidget(w.preview_time_lbl)
    w.preview_speed_combo = QComboBox()
    w.preview_speed_combo.addItems(["0.5×", "1×", "2×", "4×"])
    w.preview_speed_combo.setCurrentIndex(1); w.preview_speed_combo.setFixedWidth(52)
    w.preview_speed_combo.currentIndexChanged.connect(w._update_preview_speed)
    tb.addWidget(w.preview_speed_combo)
    pll.addLayout(tb)

    bbr = QHBoxLayout()
    w.preview_frames_btn = QPushButton("🎬 Preview Frames")
    w.preview_frames_btn.clicked.connect(w._preview_captured_frames); bbr.addWidget(w.preview_frames_btn)
    w.preview_mp4_btn = QPushButton("📼 Preview MP4")
    w.preview_mp4_btn.clicked.connect(w._preview_mp4); bbr.addWidget(w.preview_mp4_btn)
    pll.addLayout(bbr)

    mr = QHBoxLayout()
    w.preview_mp4_path = QLineEdit(); w.preview_mp4_path.setPlaceholderText("MP4 path…")
    mr.addWidget(w.preview_mp4_path, stretch=1); pll.addLayout(mr)
    pvl.addWidget(pg); main_splitter.addWidget(preview_widget)

    # ── BOTTOM: Export & Capture Settings ──────────────────────────
    sc = QScrollArea(); sc.setWidgetResizable(True)
    inner = QWidget(); vl = QVBoxLayout(inner); vl.setContentsMargins(8,8,8,8)

    # Players & Canvas
    pcg = QGroupBox("Players & Canvas"); pcl = QFormLayout(pcg)
    w.bg_color_combo = QComboBox()
    w.bg_color_combo.addItems(["Dark Gray","Black","Dark Blue","Dark Green",
                                "Dark Red","White","Light Gray","Navy"])
    w.bg_color_combo.currentTextChanged.connect(w._pick_bg_color)
    pcl.addRow("Background:", w.bg_color_combo)
    w.white_name_edit = QLineEdit("White"); w.black_name_edit = QLineEdit("Black")
    w.white_name_edit.textChanged.connect(w._update_names)
    w.black_name_edit.textChanged.connect(w._update_names)
    pcl.addRow("White:", w.white_name_edit); pcl.addRow("Black:", w.black_name_edit)
    vl.addWidget(pcg)

    # Board Appearance
    bg2 = QGroupBox("Board Appearance"); bl2 = QFormLayout(bg2)
    w.theme_combo = QComboBox(); w.theme_combo.addItems(THEMES.keys())
    w.theme_combo.currentTextChanged.connect(w._theme_changed)
    bl2.addRow("Theme:", w.theme_combo)
    w.flip_btn = QPushButton("Flip Board"); w.flip_btn.clicked.connect(w._flip_board)
    bl2.addRow(w.flip_btn); vl.addWidget(bg2)

    # Capture Settings
    eg = QGroupBox("Capture Settings"); el = QFormLayout(eg)
    w.fps_spin = QSpinBox(); w.fps_spin.setRange(1, 60); w.fps_spin.setValue(DEFAULT_FPS)
    el.addRow("FPS:", w.fps_spin)
    w.hold_spin = QDoubleSpinBox(); w.hold_spin.setRange(0.1, 10.0)
    w.hold_spin.setValue(DEFAULT_HOLD); w.hold_spin.setSingleStep(0.1); w.hold_spin.setSuffix(" s")
    el.addRow("Hold:", w.hold_spin)
    w.disk_cache_chk = QCheckBox("💾 Disk Cache (low RAM mode)")
    w.disk_cache_chk.setToolTip("Write frames to disk during capture instead of keeping them in RAM.")
    w.disk_cache_chk.setChecked(False)
    w.disk_cache_chk.toggled.connect(w._on_disk_cache_toggled)
    el.addRow(w.disk_cache_chk)
    vl.addWidget(eg)

    # Capture
    cg = QGroupBox("Capture"); ccl = QVBoxLayout(cg)
    w.auto_btn = QPushButton("🎬 Auto-Capture All"); w.auto_btn.clicked.connect(w._auto_capture)
    ccl.addWidget(w.auto_btn)
    w.frame_count_lbl = QLabel("Frames: 0"); w.frame_count_lbl.setAlignment(Qt.AlignCenter)
    ccl.addWidget(w.frame_count_lbl)
    w.clear_btn = QPushButton("Clear"); w.clear_btn.clicked.connect(w._clear_frames)
    ccl.addWidget(w.clear_btn); vl.addWidget(cg)

    # Export Video
    xg = QGroupBox("💾 Export Video"); xl = QFormLayout(xg)
    w.export_res_combo = QComboBox(); w.export_res_combo.addItems(RESOLUTION_LIST)
    w.export_res_combo.setCurrentIndex(DEFAULT_RESOLUTION_INDEX)
    xl.addRow("Resolution:", w.export_res_combo)
    w.export_path_edit = QLineEdit(); w.export_path_edit.setPlaceholderText("Output path…")
    xl.addRow("Output:", w.export_path_edit)
    w.export_progress_bar = _make_progress_bar(_PROGRESS_STYLE_GREEN)
    xl.addRow(w.export_progress_bar)
    w.export_status_lbl = QLabel(""); xl.addRow(w.export_status_lbl)
    xr = QHBoxLayout()
    w.export_start_btn = QPushButton("🎬 Export")
    w.export_start_btn.clicked.connect(w._start_inline_export)
    w.export_cancel_btn = QPushButton("⏹ Cancel")
    w.export_cancel_btn.clicked.connect(w._cancel_export)
    w.export_cancel_btn.setEnabled(False)
    xr.addWidget(w.export_start_btn); xr.addWidget(w.export_cancel_btn)
    xl.addRow(xr)
    w.stream_export_btn = QPushButton("🚀 Stream Export (Low RAM)")
    w.stream_export_btn.setToolTip("Render and export in one pass with constant memory usage.")
    w.stream_export_btn.clicked.connect(w._start_streaming_export)
    xl.addRow(w.stream_export_btn); vl.addWidget(xg)

    vl.addStretch(); sc.setWidget(inner); main_splitter.addWidget(sc)
    main_splitter.setStretchFactor(0, 3); main_splitter.setStretchFactor(1, 2)
    w.right_tabs.addTab(main_splitter, "🎬 Video")


# ════════════════════════════════════════════════════════════════════
#  Settings Tab — Sound Design, Animation Easing, more controls
# ════════════════════════════════════════════════════════════════════
def _build_settings_tab(w):
    sc = QScrollArea(); sc.setWidgetResizable(True)
    inner = QWidget(); sl = QVBoxLayout(inner); sl.setContentsMargins(4,4,4,4)
    toolbox = QToolBox()
    toolbox.setStyleSheet("""
        QToolBox::tab{background-color:#2a2a30;color:#ccc;font-weight:bold;
            font-size:13px;border:1px solid #3a3a40;border-radius:4px;padding:6px;margin-bottom:2px}
        QToolBox::tab:selected{background-color:#3a4a6a;color:white}
        QToolBox::tab:hover{background-color:#353540}""")

    # ── Sound ──────────────────────────────────────────────────────
    sound_page = QWidget(); sgl = QVBoxLayout(sound_page); sgl.setContentsMargins(8,12,8,8)
    w.sound_enabled_chk = QCheckBox("Enable Sound"); w.sound_enabled_chk.setChecked(True)
    w.sound_enabled_chk.toggled.connect(w._on_sound_enabled); sgl.addWidget(w.sound_enabled_chk)

    vr = QHBoxLayout(); vr.addWidget(QLabel("Volume:"))
    w.sound_vol_slider = QSlider(Qt.Horizontal); w.sound_vol_slider.setRange(0, 100)
    w.sound_vol_slider.setValue(70); w.sound_vol_slider.valueChanged.connect(w._on_sound_vol)
    vr.addWidget(w.sound_vol_slider, stretch=1)
    w.sound_vol_lbl = QLabel("70%"); w.sound_vol_lbl.setFixedWidth(40); vr.addWidget(w.sound_vol_lbl)
    sgl.addLayout(vr)

    tr = QHBoxLayout(); tr.addWidget(QLabel("Theme:"))
    w.sound_theme_combo = QComboBox(); w.sound_theme_combo.addItems(SOUND_THEMES)
    w.sound_theme_combo.currentTextChanged.connect(w._on_sound_theme)
    tr.addWidget(w.sound_theme_combo, stretch=1); sgl.addLayout(tr)

    # Sound Design (NEW)
    dr = QHBoxLayout(); dr.addWidget(QLabel("Design:"))
    w.sound_design_combo = QComboBox(); w.sound_design_combo.addItems(SOUND_DESIGNS)
    w.sound_design_combo.setCurrentIndex(0)
    w.sound_design_combo.currentTextChanged.connect(w._on_sound_design)
    dr.addWidget(w.sound_design_combo, stretch=1); sgl.addLayout(dr)

    w.sound_design_desc = QLabel("🎵 Default — Standard balanced sound")
    w.sound_design_desc.setStyleSheet("color:#888;font-size:10px")
    w.sound_design_desc.setWordWrap(True)
    sgl.addWidget(w.sound_design_desc)

    sgl.addStretch()
    toolbox.addItem(sound_page, "🔊 Sound")

    # ── Animation ──────────────────────────────────────────────────
    anim_page = QWidget(); agl = QVBoxLayout(anim_page); agl.setContentsMargins(8,12,8,8)
    w.anim_enabled_chk = QCheckBox("Enable Animations"); w.anim_enabled_chk.setChecked(True)
    w.anim_enabled_chk.toggled.connect(w._on_anim_enabled); agl.addWidget(w.anim_enabled_chk)

    dur_row = QHBoxLayout(); dur_row.addWidget(QLabel("Duration:"))
    w.anim_dur_spin = QSpinBox(); w.anim_dur_spin.setRange(50, 2000)
    w.anim_dur_spin.setValue(250); w.anim_dur_spin.setSuffix(" ms"); w.anim_dur_spin.setSingleStep(25)
    w.anim_dur_spin.valueChanged.connect(w._on_anim_dur)
    dur_row.addWidget(w.anim_dur_spin); agl.addLayout(dur_row)

    # Easing (NEW)
    ease_row = QHBoxLayout(); ease_row.addWidget(QLabel("Easing:"))
    w.anim_easing_combo = QComboBox(); w.anim_easing_combo.addItems(ANIM_EASINGS)
    w.anim_easing_combo.setCurrentIndex(0)  # OutCubic
    w.anim_easing_combo.currentTextChanged.connect(w._on_anim_easing)
    ease_row.addWidget(w.anim_easing_combo, stretch=1); agl.addLayout(ease_row)

    # Individual animation toggles
    w.anim_piece_chk = QCheckBox("Piece Move Animation"); w.anim_piece_chk.setChecked(True)
    w.anim_piece_chk.toggled.connect(w._on_anim_piece)
    agl.addWidget(w.anim_piece_chk)

    w.anim_highlight_chk = QCheckBox("Highlight Animation (check/flash)"); w.anim_highlight_chk.setChecked(True)
    w.anim_highlight_chk.toggled.connect(w._on_anim_highlight)
    agl.addWidget(w.anim_highlight_chk)

    w.anim_eval_chk = QCheckBox("Eval Bar Smooth Animation"); w.anim_eval_chk.setChecked(True)
    w.anim_eval_chk.toggled.connect(w._on_anim_eval)
    agl.addWidget(w.anim_eval_chk)

    agl.addStretch()
    toolbox.addItem(anim_page, "✨ Animation")

    # ── Engine ─────────────────────────────────────────────────────
    engine_page = QWidget(); egl = QVBoxLayout(engine_page); egl.setContentsMargins(8,12,8,8)
    egl.addWidget(QLabel("Stockfish engine path (for eval & AI battle):"))
    epr = QHBoxLayout()
    w.settings_engine_path = QLineEdit()
    w.settings_engine_path.setPlaceholderText("Auto-detect or set path…")
    epr.addWidget(w.settings_engine_path, stretch=1)
    w.settings_engine_browse = QPushButton("📂")
    w.settings_engine_browse.setFixedWidth(36)
    w.settings_engine_browse.clicked.connect(w._browse_engine_path)
    epr.addWidget(w.settings_engine_browse)
    w.settings_engine_detect = QPushButton("🔍 Auto")
    w.settings_engine_detect.clicked.connect(w._auto_detect_engine)
    epr.addWidget(w.settings_engine_detect)
    egl.addLayout(epr)
    w.settings_engine_status = QLabel("")
    w.settings_engine_status.setStyleSheet("color:#888;font-size:10px")
    egl.addWidget(w.settings_engine_status)
    egl.addStretch()
    toolbox.addItem(engine_page, "🐟 Engine")

    sl.addWidget(toolbox); sc.setWidget(inner)
    w.right_tabs.addTab(sc, "⚙️ Settings")