"""Chess Video Maker Pro — Main Window UI Construction"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QDoubleSpinBox, QTextEdit, QGroupBox, QCheckBox,
    QLineEdit, QComboBox, QFormLayout, QStackedWidget,
    QTabWidget, QSplitter, QListWidget, QScrollArea, QProgressBar,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QShortcut, QKeySequence

from constants import AI_MAP, THEMES
from board_widget import ChessBoardWidget
from eval_bar import EvalBarWidget
from dialogs import PromotionWidget


def build_ui(w):
    """Construct the full UI on the MainWindow instance *w*."""
    central = QWidget()
    w.setCentralWidget(central)
    main_h = QHBoxLayout(central)
    main_h.setContentsMargins(6, 6, 6, 6)

    # ── LEFT: eval bar + board + promo widget ──
    left = QVBoxLayout()
    left.setContentsMargins(0, 0, 0, 0)
    left_row = QHBoxLayout()
    w.eval_bar_widget = EvalBarWidget()
    w.board_widget = ChessBoardWidget()
    w.board_widget.squareClicked.connect(w._on_sq_click)
    left_row.addWidget(w.eval_bar_widget)
    left_row.addWidget(w.board_widget, stretch=1)
    left.addLayout(left_row, stretch=1)
    w.promo_widget = PromotionWidget()
    left.addWidget(w.promo_widget)

    # ── CENTER: Tabs ──
    center = QVBoxLayout()
    w.tabs = QTabWidget()
    _build_moves_tab(w)
    _build_database_tab(w)
    _build_assets_tab(w)
    center.addWidget(w.tabs)

    # ── RIGHT: Tabbed Settings ──
    w.right_tabs = QTabWidget()
    w.right_tabs.setDocumentMode(True)
    _build_battle_tab(w)
    _build_analysis_tab(w)
    _build_video_tab(w)

    right = QVBoxLayout()
    right.setContentsMargins(0, 0, 0, 0)
    right.addWidget(w.right_tabs)

    splitter = QSplitter(Qt.Horizontal)
    for layout in (left, center, right):
        sw = QWidget()
        sw.setLayout(layout)
        splitter.addWidget(sw)
    splitter.setStretchFactor(0, 5)
    splitter.setStretchFactor(1, 3)
    splitter.setStretchFactor(2, 2)
    main_h.addWidget(splitter)
    w.statusBar().showMessage(
        "Ready — Click '📊 Eval Game' to fill the Eval Bar for all moves!"
    )


def build_menu(w):
    """Construct the menu bar and keyboard shortcuts on *w*."""
    mb = w.menuBar()
    fm = mb.addMenu("&File")
    fm.addAction("New Game", QKeySequence("Ctrl+N"), w._new_game)
    fm.addAction("Load PGN…", QKeySequence("Ctrl+O"), w._load_pgn)
    fm.addSeparator()
    fm.addAction("Exit", QKeySequence("Ctrl+Q"), w.close)
    vm = mb.addMenu("&View")
    vm.addAction("Flip Board", QKeySequence("F"), w._flip_board)
    QShortcut(QKeySequence(Qt.Key_Left), w, w._go_prev)
    QShortcut(QKeySequence(Qt.Key_Right), w, w._go_next)
    QShortcut(QKeySequence(Qt.Key_Home), w, w._go_first)
    QShortcut(QKeySequence(Qt.Key_End), w, w._go_last)
    QShortcut(QKeySequence(Qt.Key_Space), w, w._toggle_play)


# ── Private tab builders ──────────────────────────────────────────

def _build_moves_tab(w):
    moves_w = QWidget()
    moves_l = QVBoxLayout(moves_w)
    w.move_listbox = QListWidget()
    w.move_listbox.currentRowChanged.connect(w._on_move_row)
    w.move_listbox.setFont(QFont("Consolas", 11))
    moves_l.addWidget(w.move_listbox, stretch=1)
    nav = QGridLayout()
    for i, (t, fn) in enumerate([
        ("⏮", w._go_first), ("◀", w._go_prev),
        ("▶", w._go_next), ("⏭", w._go_last),
    ]):
        b = QPushButton(t); b.setFixedSize(52, 36); b.clicked.connect(fn)
        nav.addWidget(b, 0, i)
    w.btn_play = QPushButton("▶ Play")
    w.btn_play.clicked.connect(w._toggle_play)
    nav.addWidget(w.btn_play, 0, 4, 1, 2)
    w.speed_slider = QSlider(Qt.Horizontal)
    w.speed_slider.setRange(1, 50); w.speed_slider.setValue(8)
    nav.addWidget(QLabel("Speed:"), 1, 0, 1, 2)
    nav.addWidget(w.speed_slider, 1, 2, 1, 4)
    moves_l.addLayout(nav)
    cg = QGroupBox("Annotation")
    cl = QVBoxLayout(cg)
    w.anno_edit = QTextEdit()
    w.anno_edit.setMaximumHeight(60)
    w.anno_edit.setPlaceholderText("Comment for YouTube overlay…")
    cl.addWidget(w.anno_edit)
    ab = QPushButton("Apply Comment"); ab.clicked.connect(w._apply_comment)
    cl.addWidget(ab)
    moves_l.addWidget(cg)
    w.tabs.addTab(moves_w, "♜ Moves")


def _build_database_tab(w):
    db_w = QWidget(); db_l = QVBoxLayout(db_w)

    # ── Folder path (inline, no dialog) ──
    fol_g = QGroupBox("PGN Database Folder"); fol_l = QVBoxLayout(fol_g)
    fol_row = QHBoxLayout()
    w.db_folder_edit = QLineEdit()
    w.db_folder_edit.setPlaceholderText("Enter or paste folder path…")
    fol_row.addWidget(w.db_folder_edit, stretch=1)
    db_set = QPushButton("Set Folder"); db_set.clicked.connect(w._set_pgn_db_folder)
    fol_row.addWidget(db_set)
    db_scan = QPushButton("Scan"); db_scan.clicked.connect(w._scan_pgn_db)
    fol_row.addWidget(db_scan)
    fol_l.addLayout(fol_row)
    w.db_path_lbl = QLabel("Folder: None")
    fol_l.addWidget(w.db_path_lbl)
    db_l.addWidget(fol_g)

    # ── File list ──
    w.db_list = QListWidget()
    w.db_list.itemDoubleClicked.connect(w._load_selected_pgn_db)
    db_l.addWidget(w.db_list, stretch=1)
    h_load = QHBoxLayout()
    w.db_game_idx = QSpinBox(); w.db_game_idx.setRange(1, 100000); w.db_game_idx.setValue(1)
    h_load.addWidget(QLabel("Game # (In File):")); h_load.addWidget(w.db_game_idx)
    load_btn = QPushButton("Load Selected File"); load_btn.clicked.connect(w._load_selected_pgn_db)
    h_load.addWidget(load_btn)
    db_l.addLayout(h_load)

    # ── PGN Input (inline, no dialog) ──
    inp_g = QGroupBox("PGN Input"); inp_l = QVBoxLayout(inp_g)
    w.pgn_text_edit = QTextEdit()
    w.pgn_text_edit.setMaximumHeight(100)
    w.pgn_text_edit.setPlaceholderText("Paste PGN text here…")
    inp_l.addWidget(w.pgn_text_edit)
    pgn_btn_row = QHBoxLayout()
    load_text_btn = QPushButton("📋 Load PGN Text"); load_text_btn.clicked.connect(w._load_pgn_text)
    pgn_btn_row.addWidget(load_text_btn)
    pgn_btn_row.addStretch()
    inp_l.addLayout(pgn_btn_row)
    file_row = QHBoxLayout()
    w.pgn_file_edit = QLineEdit()
    w.pgn_file_edit.setPlaceholderText("Enter PGN file path…")
    file_row.addWidget(w.pgn_file_edit, stretch=1)
    load_file_btn = QPushButton("📄 Load File"); load_file_btn.clicked.connect(w._load_pgn_from_file)
    file_row.addWidget(load_file_btn)
    inp_l.addLayout(file_row)
    db_l.addWidget(inp_g)

    w.tabs.addTab(db_w, "📂 PGN Database")


def _build_assets_tab(w):
    img_w = QWidget(); img_l = QVBoxLayout(img_w)

    # ── Image folder (inline, no dialog) ──
    fol_g = QGroupBox("Image Folder"); fol_l = QVBoxLayout(fol_g)
    fol_row = QHBoxLayout()
    w.img_folder_edit = QLineEdit()
    w.img_folder_edit.setPlaceholderText("Enter or paste image folder path…")
    fol_row.addWidget(w.img_folder_edit, stretch=1)
    img_set = QPushButton("Set Folder"); img_set.clicked.connect(w._set_img_folder)
    fol_row.addWidget(img_set)
    img_scan = QPushButton("Scan"); img_scan.clicked.connect(w._scan_img_db)
    fol_row.addWidget(img_scan)
    fol_l.addLayout(fol_row)
    w.img_path_lbl = QLabel("Folder: None")
    fol_l.addWidget(w.img_path_lbl)
    img_l.addWidget(fol_g)

    w.img_list = QListWidget()
    w.img_list.setViewMode(QListWidget.IconMode)
    w.img_list.setIconSize(QSize(80, 80))
    w.img_list.setResizeMode(QListWidget.Adjust)
    img_l.addWidget(w.img_list, stretch=1)
    ov_grp = QGroupBox("Add to Video Canvas"); ov_l = QFormLayout(ov_grp)
    w.ov_pos_combo = QComboBox()
    w.ov_pos_combo.addItems(["White Player Face", "Black Player Face", "Center Logo", "Watermark (BR)"])
    ov_l.addRow("Position:", w.ov_pos_combo)
    add_btn = QPushButton("➕ Add Image Overlay"); add_btn.clicked.connect(w._add_overlay)
    ov_l.addRow(add_btn)
    rem_btn = QPushButton("🗑 Clear All Overlays"); rem_btn.clicked.connect(w._clear_overlays)
    ov_l.addRow(rem_btn)
    img_l.addWidget(ov_grp)
    w.tabs.addTab(img_w, "🖼 Image Assets")


def _build_battle_tab(w):
    scroll = QScrollArea(); scroll.setWidgetResizable(True)
    inner = QWidget(); bl = QVBoxLayout(inner); bl.setContentsMargins(8, 8, 8, 8)
    vs_g = QGroupBox("⚔️ AI vs AI Battle"); vs_l = QFormLayout(vs_g)
    w.white_ai_combo = QComboBox(); w.white_ai_combo.addItems(AI_MAP.values())
    vs_l.addRow("White AI:", w.white_ai_combo)
    w.white_ai_str = QSpinBox(); w.white_ai_str.setRange(1, 5000); w.white_ai_str.setValue(3)
    vs_l.addRow("W. Depth/Sims:", w.white_ai_str)
    w.black_ai_combo = QComboBox(); w.black_ai_combo.addItems(AI_MAP.values()); w.black_ai_combo.setCurrentIndex(1)
    vs_l.addRow("Black AI:", w.black_ai_combo)
    w.black_ai_str = QSpinBox(); w.black_ai_str.setRange(1, 5000); w.black_ai_str.setValue(100)
    vs_l.addRow("B. Depth/Sims:", w.black_ai_str)
    w.battle_delay = QSpinBox(); w.battle_delay.setRange(50, 5000); w.battle_delay.setValue(500); w.battle_delay.setSuffix(" ms")
    vs_l.addRow("Move Delay:", w.battle_delay)
    btn_row = QHBoxLayout()
    w.start_battle_btn = QPushButton("⚔️ Start Battle"); w.start_battle_btn.clicked.connect(w._start_ai_vs_ai)
    w.stop_battle_btn = QPushButton("⏹ Stop"); w.stop_battle_btn.clicked.connect(w._stop_ai_vs_ai); w.stop_battle_btn.setEnabled(False)
    btn_row.addWidget(w.start_battle_btn); btn_row.addWidget(w.stop_battle_btn)
    vs_l.addRow(btn_row)
    bl.addWidget(vs_g); bl.addStretch(); scroll.setWidget(inner)
    w.right_tabs.addTab(scroll, "⚔️ Battle")


def _build_analysis_tab(w):
    scroll = QScrollArea(); scroll.setWidgetResizable(True)
    inner = QWidget(); al = QVBoxLayout(inner); al.setContentsMargins(8, 8, 8, 8)
    ai_g = QGroupBox("🧠 AI Engine Lab"); ai_l = QVBoxLayout(ai_g)
    eng_row = QHBoxLayout(); eng_row.addWidget(QLabel("Engine:"))
    w.ai_combo = QComboBox(); w.ai_combo.addItems(AI_MAP.values())
    w.ai_combo.currentTextChanged.connect(w._toggle_ai_ui)
    eng_row.addWidget(w.ai_combo, stretch=1); ai_l.addLayout(eng_row)
    w.ai_stack = QStackedWidget()
    mm_w = QWidget(); mm_l = QFormLayout(mm_w)
    w.mm_depth = QSpinBox(); w.mm_depth.setRange(1, 4); w.mm_depth.setValue(3)
    mm_l.addRow("Depth:", w.mm_depth); w.ai_stack.addWidget(mm_w)
    mcts_w = QWidget(); mcts_l = QFormLayout(mcts_w)
    w.m_iters = QSpinBox(); w.m_iters.setRange(100, 5000); w.m_iters.setValue(500); w.m_iters.setSingleStep(100)
    mcts_l.addRow("Sims:", w.m_iters); w.ai_stack.addWidget(mcts_w)
    sf_w = QWidget(); sf_l = QFormLayout(sf_w)
    w.engine_path_edit = QLineEdit(); w.engine_path_edit.setPlaceholderText("Path to stockfish…")
    sf_l.addRow("Path:", w.engine_path_edit)
    # No "Browse" button — type or paste the path directly
    w.ai_stack.addWidget(sf_w); ai_l.addWidget(w.ai_stack)
    w.run_ai_btn = QPushButton("🔬 Run Analysis"); w.run_ai_btn.clicked.connect(w._run_engine); ai_l.addWidget(w.run_ai_btn)
    eval_row = QHBoxLayout()
    w.eval_game_btn = QPushButton("📊 Eval Game"); w.eval_game_btn.clicked.connect(w._start_batch_eval)
    w.stop_eval_btn = QPushButton("⏹ Stop"); w.stop_eval_btn.clicked.connect(w._stop_batch_eval); w.stop_eval_btn.setEnabled(False)
    eval_row.addWidget(w.eval_game_btn); eval_row.addWidget(w.stop_eval_btn); ai_l.addLayout(eval_row)
    w.eval_label = QLabel("Eval: —"); w.eval_label.setStyleSheet("font-weight:bold; font-size:13px;")
    w.pv_label = QLabel("Nodes: —"); ai_l.addWidget(w.eval_label); ai_l.addWidget(w.pv_label)
    pol_row = QHBoxLayout()
    w.policy_chk = QCheckBox("Show AI Policy"); w.policy_chk.setChecked(True)
    w.clear_policy_btn = QPushButton("Clear Policy"); w.clear_policy_btn.clicked.connect(w._clear_policy)
    pol_row.addWidget(w.policy_chk); pol_row.addWidget(w.clear_policy_btn); ai_l.addLayout(pol_row)
    al.addWidget(ai_g); al.addStretch(); scroll.setWidget(inner)
    w.right_tabs.addTab(scroll, "🧠 Analysis")


def _build_video_tab(w):
    scroll = QScrollArea(); scroll.setWidgetResizable(True)
    inner = QWidget(); vl = QVBoxLayout(inner); vl.setContentsMargins(8, 8, 8, 8)

    # ── Players & Canvas ──
    pc_g = QGroupBox("Players & Canvas"); pc_l = QFormLayout(pc_g)
    w.bg_color_combo = QComboBox()
    w.bg_color_combo.addItems(["Dark Gray", "Black", "Dark Blue", "Dark Green", "Dark Red",
                                "White", "Light Gray", "Navy"])
    w.bg_color_combo.currentTextChanged.connect(w._pick_bg_color)
    pc_l.addRow("Background:", w.bg_color_combo)
    w.white_name_edit = QLineEdit("White"); w.black_name_edit = QLineEdit("Black")
    w.white_name_edit.textChanged.connect(w._update_names); w.black_name_edit.textChanged.connect(w._update_names)
    pc_l.addRow("White:", w.white_name_edit); pc_l.addRow("Black:", w.black_name_edit)
    vl.addWidget(pc_g)

    # ── Board Appearance ──
    ba_g = QGroupBox("Board Appearance"); ba_l = QFormLayout(ba_g)
    w.theme_combo = QComboBox(); w.theme_combo.addItems(THEMES.keys())
    w.theme_combo.currentTextChanged.connect(w._theme_changed); ba_l.addRow("Theme:", w.theme_combo)
    w.flip_btn = QPushButton("Flip Board"); w.flip_btn.clicked.connect(w._flip_board); ba_l.addRow(w.flip_btn)
    vl.addWidget(ba_g)

    # ── Export Settings ──
    es_g = QGroupBox("Export Settings"); es_l = QFormLayout(es_g)
    w.fps_spin = QSpinBox(); w.fps_spin.setRange(1, 120); w.fps_spin.setValue(60)
    es_l.addRow("Capture FPS:", w.fps_spin)
    w.anim_spin = QDoubleSpinBox(); w.anim_spin.setRange(0.0, 3.0); w.anim_spin.setValue(0.3)
    w.anim_spin.setSingleStep(0.1); w.anim_spin.setSuffix(" s"); es_l.addRow("Anim:", w.anim_spin)
    w.hold_spin = QDoubleSpinBox(); w.hold_spin.setRange(0.1, 10.0); w.hold_spin.setValue(1.5)
    w.hold_spin.setSingleStep(0.1); w.hold_spin.setSuffix(" s"); es_l.addRow("Hold:", w.hold_spin)
    vl.addWidget(es_g)

    # ── Capture ──
    cap_g = QGroupBox("Capture"); cap_l = QVBoxLayout(cap_g)
    w.auto_btn = QPushButton("🎬 Auto-Capture All"); w.auto_btn.clicked.connect(w._auto_capture); cap_l.addWidget(w.auto_btn)
    w.frame_count_lbl = QLabel("Frames: 0"); w.frame_count_lbl.setAlignment(Qt.AlignCenter); cap_l.addWidget(w.frame_count_lbl)
    w.clear_btn = QPushButton("Clear All Frames"); w.clear_btn.clicked.connect(w._clear_frames); cap_l.addWidget(w.clear_btn)
    vl.addWidget(cap_g)

    # ── Inline Export (no popup dialog) ──
    ex_g = QGroupBox("💾 Export Video"); ex_l = QFormLayout(ex_g)
    w.export_res_combo = QComboBox()
    w.export_res_combo.addItems(["1920×1080 (1080p)", "1280×720 (720p)", "3840×2160 (4K)"])
    ex_l.addRow("Resolution:", w.export_res_combo)
    w.export_fps_spin = QSpinBox(); w.export_fps_spin.setRange(1, 120); w.export_fps_spin.setValue(60)
    ex_l.addRow("Export FPS:", w.export_fps_spin)
    w.export_path_edit = QLineEdit()
    w.export_path_edit.setPlaceholderText("Output file path, e.g. ~/chess_video.mp4")
    ex_l.addRow("Output:", w.export_path_edit)
    w.export_progress_bar = QProgressBar(); w.export_progress_bar.setValue(0)
    ex_l.addRow(w.export_progress_bar)
    w.export_status_lbl = QLabel(""); ex_l.addRow(w.export_status_lbl)
    ex_btn_row = QHBoxLayout()
    w.export_start_btn = QPushButton("🎬 Start Export"); w.export_start_btn.clicked.connect(w._start_inline_export)
    w.export_cancel_btn = QPushButton("⏹ Cancel"); w.export_cancel_btn.clicked.connect(w._cancel_export)
    w.export_cancel_btn.setEnabled(False)
    ex_btn_row.addWidget(w.export_start_btn); ex_btn_row.addWidget(w.export_cancel_btn)
    ex_l.addRow(ex_btn_row)
    vl.addWidget(ex_g)

    vl.addStretch(); scroll.setWidget(inner)
    w.right_tabs.addTab(scroll, "🎬 Video")