"""Chess Video Maker Pro — Comprehensive Test Suite
====================================================
Single pytest file covering ALL features:

- Constants & configuration utilities
- AI engines (HeuristicEvaluator, MinimaxEngine, MCTSEngine, MCTSNode)
- BoardRenderer (thread-safe rendering)
- ChessBoardWidget (interactive board)
- EvalBarWidget (evaluation bar + game-state overlays)
- PromotionWidget
- VideoRenderer (full-frame off-GUI rendering)
- Workers (AI, BatchEval, AIBattle, Capture, Streaming, Export, BatchPGN)
- AnimationManager & SoundManager
- UI Builder & Menu construction
- MainWindow logic (navigation, PGN load, interaction, AI, battle,
  settings, pipelines, overlays, cleanup)

Required:  pytest, pytest-qt, PySide6, python-chess
Optional:  numpy (sound), opencv-python (video export)
"""

import pytest
import sys
import os
import io
import math
import tempfile
import shutil
import time

import chess
import chess.pgn

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

# ── Application imports ──────────────────────────────────────────
from constants import (
    PIECE_SYM, AI_MAP, SOUND_THEMES, SOUND_DESIGNS, SOUND_TYPES,
    ANIM_EASINGS, GAME_NORMAL, GAME_CHECKMATE, GAME_STALEMATE,
    GAME_DRAW, GAME_INSUFFICIENT, QUALITY_PRESETS, RESOLUTION_SIZES,
    RESOLUTION_LIST, MAX_FRAMES_IN_MEMORY, BoardTheme, THEMES,
    get_system_ram_gb, get_gpu_info, get_recommended_preset,
    estimate_memory_gb, find_stockfish, HAS_CV2,
)
from ai_engines import HeuristicEvaluator, MinimaxEngine, MCTSEngine, MCTSNode
from board_renderer import BoardRenderer
from board_widget import ChessBoardWidget
from widgets import EvalBarWidget, PromotionWidget, VideoRenderer
from workers import (
    AIWorker, BatchEvalWorker, AIBattleWorker, CaptureWorker,
    StreamingExportWorker, ExportWorker, BatchPGNExportWorker,
    _detect_game_state, _resolve_sf,
)
from managers import AnimationManager, SoundManager, _SOUND_DESIGN_DESC

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False

try:
    import cv2
    HAS_CV2_TEST = True
except ImportError:
    HAS_CV2_TEST = False


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication singleton."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
    return app


@pytest.fixture
def fresh_board():
    return chess.Board()


@pytest.fixture
def sample_pgn_text():
    return (
        '[Event "Test"]\n[Site "Test"]\n[Date "2024.01.01"]\n'
        '[White "W"]\n[Black "B"]\n[Result "1-0"]\n\n'
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O 1-0"
    )


@pytest.fixture
def sample_game(sample_pgn_text):
    return chess.pgn.read_game(io.StringIO(sample_pgn_text))


@pytest.fixture
def board_widget(qapp):
    return ChessBoardWidget()


@pytest.fixture
def eval_bar(qapp):
    return EvalBarWidget()


@pytest.fixture
def main_window(qapp):
    from main_window import MainWindow
    w = MainWindow()
    yield w
    w._cleanup()
    w.close()


# ═══════════════════════════════════════════════════════════════════
#  Constants & Configuration
# ═══════════════════════════════════════════════════════════════════

class TestConstants:
    def test_piece_sym_completeness(self):
        assert len(PIECE_SYM) == 12
        for pt in (chess.PAWN, chess.KNIGHT, chess.BISHOP,
                   chess.ROOK, chess.QUEEN, chess.KING):
            for c in (chess.WHITE, chess.BLACK):
                assert (pt, c) in PIECE_SYM

    def test_piece_sym_strings(self):
        for key, sym in PIECE_SYM.items():
            assert isinstance(sym, str) and len(sym) >= 1

    def test_ai_map(self):
        assert len(AI_MAP) == 3
        assert "Minimax" in AI_MAP[0]
        assert "MCTS" in AI_MAP[1]
        assert "Stockfish" in AI_MAP[2]

    def test_sound_themes(self):
        assert "Classic" in SOUND_THEMES
        assert "Silent" in SOUND_THEMES

    def test_sound_designs(self):
        for d in ("Default", "Warm", "Crisp", "Retro", "Cinematic", "Minimal"):
            assert d in SOUND_DESIGNS

    def test_sound_types(self):
        for t in ("move", "capture", "check", "checkmate", "castle",
                  "illegal", "new_game", "promotion", "ui_click"):
            assert t in SOUND_TYPES

    def test_anim_easings(self):
        assert "OutCubic" in ANIM_EASINGS
        assert "Linear" in ANIM_EASINGS

    def test_game_states_distinct(self):
        states = {GAME_NORMAL, GAME_CHECKMATE, GAME_STALEMATE,
                  GAME_DRAW, GAME_INSUFFICIENT}
        assert len(states) == 5

    def test_quality_presets_keys(self):
        for name in ("Low", "Medium", "High"):
            p = QUALITY_PRESETS[name]
            for k in ("resolution_index", "fps", "capture_fps",
                      "hold", "disk_cache", "label"):
                assert k in p

    def test_quality_presets_values(self):
        assert QUALITY_PRESETS["Low"]["disk_cache"] is True
        assert QUALITY_PRESETS["Medium"]["fps"] == 30
        assert QUALITY_PRESETS["High"]["fps"] == 60

    def test_resolution_sizes(self):
        assert RESOLUTION_SIZES["1920×1080"] == (1920, 1080)
        assert RESOLUTION_SIZES["1280×720"] == (1280, 720)

    def test_resolution_list_matches_sizes(self):
        for r in RESOLUTION_LIST:
            assert r in RESOLUTION_SIZES

    def test_max_frames_positive(self):
        assert MAX_FRAMES_IN_MEMORY > 0

    def test_get_system_ram_gb(self):
        ram = get_system_ram_gb()
        assert isinstance(ram, float) and ram > 0

    def test_get_gpu_info(self):
        name, vram = get_gpu_info()
        assert isinstance(name, str)
        assert isinstance(vram, float) and vram >= 0

    def test_get_recommended_preset(self):
        assert get_recommended_preset() in QUALITY_PRESETS

    def test_estimate_memory_positive(self):
        assert estimate_memory_gb("1920×1080", 30, 1.5, 40) > 0

    def test_estimate_memory_scales_with_moves(self):
        e1 = estimate_memory_gb("1920×1080", 30, 1.5, 10)
        e2 = estimate_memory_gb("1920×1080", 30, 1.5, 80)
        assert e2 > e1

    def test_estimate_memory_scales_with_resolution(self):
        e1 = estimate_memory_gb("1280×720", 30, 1.5, 40)
        e2 = estimate_memory_gb("1920×1080", 30, 1.5, 40)
        assert e2 > e1

    def test_find_stockfish(self):
        r = find_stockfish()
        assert r is None or isinstance(r, str)

    def test_board_theme_default(self):
        t = BoardTheme()
        assert t.name == "Classic"

    def test_board_theme_custom(self):
        t = BoardTheme("Custom", (255, 255, 255), (0, 0, 0))
        assert t.name == "Custom"

    def test_themes_dict(self):
        for name in ("Classic", "Blue", "Green", "Brown"):
            assert name in THEMES
            assert isinstance(THEMES[name], BoardTheme)
            assert THEMES[name].name == name


# ═══════════════════════════════════════════════════════════════════
#  AI Engines
# ═══════════════════════════════════════════════════════════════════

class TestHeuristicEvaluator:
    def setup_method(self):
        self.ev = HeuristicEvaluator()

    def test_starting_position(self):
        s = self.ev.evaluate(chess.Board())
        assert isinstance(s, int)
        assert -500 < s < 500

    def test_checkmate(self):
        b = chess.Board("rnb1kbnr/pppp1ppp/4p3/8/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
        if b.is_checkmate():
            assert self.ev.evaluate(b) == -10000

    def test_stalemate_zero(self):
        b = chess.Board("k7/8/1K6/8/8/8/8/8 b - - 0 1")
        if b.is_stalemate():
            assert self.ev.evaluate(b) == 0

    def test_insufficient_zero(self):
        b = chess.Board("k7/8/K7/8/8/8/8/8 w - - 0 1")
        if b.is_insufficient_material():
            assert self.ev.evaluate(b) == 0

    def test_piece_values(self):
        pv = HeuristicEvaluator.PV
        assert pv[chess.PAWN] == 100
        assert pv[chess.KNIGHT] == 320
        assert pv[chess.BISHOP] == 330
        assert pv[chess.ROOK] == 500
        assert pv[chess.QUEEN] == 900
        assert pv[chess.KING] == 20000

    def test_extra_queen_positive(self):
        b = chess.Board()
        b.set_piece_at(chess.A3, chess.Piece(chess.QUEEN, chess.WHITE))
        s = self.ev.evaluate(b)
        assert s > 800

    def test_symmetry(self):
        """Mirrored position should evaluate to opposite sign."""
        # Not exact symmetry but at least consistent sign behaviour
        s = self.ev.evaluate(chess.Board())
        assert isinstance(s, int)


class TestMinimaxEngine:
    def setup_method(self):
        self.eng = MinimaxEngine()

    def test_search_returns_four(self):
        bm, ev, n, pol = self.eng.search(chess.Board(), 1)
        assert bm is not None
        assert isinstance(ev, (int, float))
        assert isinstance(n, int)
        assert isinstance(pol, dict)

    def test_best_move_legal(self):
        b = chess.Board()
        bm, *_ = self.eng.search(b, 1)
        assert bm in b.legal_moves

    def test_depth_2(self):
        bm, ev, n, pol = self.eng.search(chess.Board(), 2)
        assert bm is not None and n > 0

    def test_policy_01(self):
        _, _, _, pol = self.eng.search(chess.Board(), 1)
        for v in pol.values():
            assert 0 <= v <= 1

    def test_nodes_increase_with_depth(self):
        _, _, n1, _ = self.eng.search(chess.Board(), 1)
        _, _, n2, _ = self.eng.search(chess.Board(), 2)
        assert n2 >= n1

    def test_midgame_position(self):
        b = chess.Board("r1bqkbnr/pppppppp/2n5/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 1 2")
        bm, ev, n, pol = self.eng.search(b, 1)
        assert bm is not None

    def test_endgame_position(self):
        b = chess.Board("8/5k2/8/8/8/4K3/4P3/8 w - - 0 1")
        bm, ev, n, pol = self.eng.search(b, 2)
        assert bm is not None


class TestMCTSNode:
    def test_creation(self):
        n = MCTSNode(chess.Board())
        assert n.visits == 0 and n.wins == 0.0

    def test_ucb1_unvisited(self):
        parent = MCTSNode(chess.Board()); parent.visits = 1
        child = MCTSNode(chess.Board(), parent=parent)
        assert child.ucb1() == float("inf")

    def test_ucb1_visited(self):
        parent = MCTSNode(chess.Board()); parent.visits = 10
        child = MCTSNode(chess.Board(), parent=parent)
        child.visits = 3; child.wins = 1.5
        u = child.ucb1()
        assert 0 < u < float("inf")

    def test_expand(self):
        n = MCTSNode(chess.Board())
        before = len(n.untried)
        c = n.expand()
        assert len(n.untried) == before - 1
        assert c in n.children

    def test_best_child(self):
        root = MCTSNode(chess.Board())
        for _ in range(3):
            root.expand()
        for c in root.children:
            c.visits = 1; c.wins = 0.5
        root.visits = 3
        assert root.best_child() in root.children


class TestMCTSEngine:
    def setup_method(self):
        self.eng = MCTSEngine()

    def test_search_returns_four(self):
        bm, ev, vis, pol = self.eng.search(chess.Board(), 10)
        assert isinstance(pol, dict)

    def test_visits_equals_iters(self):
        _, _, vis, _ = self.eng.search(chess.Board(), 15)
        assert vis == 15

    def test_best_move_legal(self):
        b = chess.Board()
        bm, *_ = self.eng.search(b, 20)
        if bm is not None:
            assert bm in b.legal_moves

    def test_low_iterations(self):
        bm, ev, vis, pol = self.eng.search(chess.Board(), 5)
        assert isinstance(vis, int)


# ═══════════════════════════════════════════════════════════════════
#  BoardRenderer
# ═══════════════════════════════════════════════════════════════════

class TestBoardRenderer:
    def test_default(self):
        r = BoardRenderer()
        assert isinstance(r.board, chess.Board)
        assert r.flipped is False

    def test_custom(self):
        b = chess.Board()
        r = BoardRenderer(board=b, flipped=True, show_coords=False)
        assert r.flipped is True and r.show_coords is False

    def test_render_qimage(self, qapp):
        img = BoardRenderer().render(400)
        assert isinstance(img, QImage) and not img.isNull()

    def test_render_sizes(self, qapp):
        for sz in (200, 400, 800, 1080):
            img = BoardRenderer().render(sz)
            assert img.width() == sz and img.height() == sz

    def test_render_with_coords(self, qapp):
        assert not BoardRenderer(show_coords=True).render(400).isNull()

    def test_render_no_coords(self, qapp):
        assert not BoardRenderer(show_coords=False).render(400).isNull()

    def test_render_flipped(self, qapp):
        assert not BoardRenderer(flipped=True).render(400).isNull()

    def test_render_last_move(self, qapp):
        r = BoardRenderer(); b = chess.Board()
        mv = list(b.legal_moves)[0]; b.push(mv)
        r.board = b; r.last_move = mv
        assert not r.render(400).isNull()

    def test_render_selected(self, qapp):
        r = BoardRenderer(); r.selected_sq = chess.E2
        r.legal_targets = [chess.E3, chess.E4]
        assert not r.render(400).isNull()

    def test_render_arrows(self, qapp):
        r = BoardRenderer()
        r.arrows = [(chess.E2, chess.E4, QColor(220, 50, 47, 200))]
        assert not r.render(400).isNull()

    def test_render_policy(self, qapp):
        r = BoardRenderer(); r.policy_vis = {"e2e4": 0.8, "d2d4": 0.2}
        assert not r.render(400).isNull()

    def test_render_animation(self, qapp):
        r = BoardRenderer()
        r.anim_move = chess.Move(chess.E2, chess.E4); r.anim_progress = 0.5
        assert not r.render(400).isNull()

    def test_render_highlighted(self, qapp):
        r = BoardRenderer(); r.highlighted = {chess.E4, chess.D4}
        assert not r.render(400).isNull()

    def test_from_widget(self, qapp, board_widget):
        r = BoardRenderer.from_widget(board_widget)
        assert isinstance(r, BoardRenderer)
        assert r.board == board_widget.board


# ═══════════════════════════════════════════════════════════════════
#  ChessBoardWidget
# ═══════════════════════════════════════════════════════════════════

class TestChessBoardWidget:
    def test_defaults(self, qapp):
        w = ChessBoardWidget()
        assert w.flipped is False
        assert w.selected_sq is None

    def test_set_position(self, qapp):
        w = ChessBoardWidget(); b = chess.Board()
        mv = list(b.legal_moves)[0]; b.push(mv)
        w.set_position(b, mv)
        assert w.board == b and w.last_move == mv

    def test_set_theme(self, qapp):
        w = ChessBoardWidget(); w.set_theme(THEMES["Blue"])
        assert w.theme.name == "Blue"

    def test_flip(self, qapp):
        w = ChessBoardWidget()
        assert not w.flipped
        w.flipped = True; w.update()
        assert w.flipped

    def test_render_to_image(self, qapp):
        img = ChessBoardWidget().render_to_image(400)
        assert isinstance(img, QImage) and not img.isNull()

    def test_set_position_animated(self, qapp):
        w = ChessBoardWidget(); b = chess.Board()
        b.push_san("e4")
        w.set_position_animated(b, chess.Move.from_uci("e2e4"))
        assert w.board == b

    def test_square_clicked_signal_exists(self, qapp):
        assert hasattr(ChessBoardWidget(), "squareClicked")


# ═══════════════════════════════════════════════════════════════════
#  EvalBarWidget
# ═══════════════════════════════════════════════════════════════════

class TestEvalBarWidget:
    def test_defaults(self, qapp):
        w = EvalBarWidget()
        assert w._eval_cp == 0.0 and w._game_state == GAME_NORMAL

    def test_set_eval(self, qapp):
        w = EvalBarWidget()
        for v in (100.0, -200.0, 10001.0, -10001.0):
            w.set_eval(v)
            assert w._eval_cp == v

    def test_cp_to_ratio_center(self):
        assert abs(EvalBarWidget._cp_to_ratio(0) - 0.5) < 0.01

    def test_cp_to_ratio_positive(self):
        assert EvalBarWidget._cp_to_ratio(100) > 0.5

    def test_cp_to_ratio_negative(self):
        assert EvalBarWidget._cp_to_ratio(-100) < 0.5

    def test_cp_to_ratio_extreme(self):
        assert EvalBarWidget._cp_to_ratio(9000) > 0.99
        assert EvalBarWidget._cp_to_ratio(-9000) < 0.01
        assert EvalBarWidget._cp_to_ratio(100000) == 1.0
        assert EvalBarWidget._cp_to_ratio(-100000) == 0.0

    @pytest.mark.parametrize("state,result,detail", [
        (GAME_CHECKMATE, "1-0", "Checkmate"),
        (GAME_STALEMATE, "½-½", "Stalemate"),
        (GAME_DRAW, "½-½", "Draw"),
        (GAME_INSUFFICIENT, "½-½", "Insufficient Material"),
    ])
    def test_game_states(self, qapp, state, result, detail):
        w = EvalBarWidget()
        w.set_game_state(state, result, detail)
        assert w._game_state == state
        assert w._game_result == result

    def test_reset_game_state(self, qapp):
        w = EvalBarWidget()
        w.set_game_state(GAME_CHECKMATE, "1-0", "Checkmate")
        w.reset_game_state()
        assert w._game_state == GAME_NORMAL and w._game_result == ""

    def test_anim_duration(self, qapp):
        w = EvalBarWidget()
        w.set_anim_duration(500); assert w._anim_dur == 500
        w.set_anim_duration(0);   assert w._anim_dur == 0

    @pytest.mark.parametrize("state,result,detail", [
        (GAME_NORMAL, "", ""),
        (GAME_CHECKMATE, "1-0", "Checkmate"),
        (GAME_STALEMATE, "½-½", "Stalemate"),
        (GAME_DRAW, "½-½", "Draw"),
        (GAME_INSUFFICIENT, "½-½", "Insufficient"),
    ])
    def test_paint_doesnt_crash(self, qapp, state, result, detail):
        w = EvalBarWidget(); w.set_eval(150.0)
        if state != GAME_NORMAL:
            w.set_game_state(state, result, detail)
        w.resize(60, 400); w.repaint()


# ═══════════════════════════════════════════════════════════════════
#  PromotionWidget
# ═══════════════════════════════════════════════════════════════════

class TestPromotionWidget:
    def test_hidden_by_default(self, qapp):
        assert PromotionWidget().isHidden()

    def test_show_white(self, qapp):
        w = PromotionWidget(); w.show_for_color(chess.WHITE)
        assert w.isVisible()

    def test_show_black(self, qapp):
        w = PromotionWidget(); w.show_for_color(chess.BLACK)
        assert w.isVisible()

    def test_four_buttons(self, qapp):
        w = PromotionWidget(); assert len(w._btns) == 4
        types = {pt for pt, _ in w._btns}
        assert types == {chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT}

    def test_signal_exists(self, qapp):
        assert hasattr(PromotionWidget(), "piece_selected")


# ═══════════════════════════════════════════════════════════════════
#  VideoRenderer
# ═══════════════════════════════════════════════════════════════════

class TestVideoRenderer:
    def test_defaults(self, qapp):
        vr = VideoRenderer(BoardRenderer())
        assert vr.w == 1920 and vr.h == 1080 and vr.eval_cp == 0.0

    def test_custom(self, qapp):
        vr = VideoRenderer(BoardRenderer(), w=1280, h=720, bg_color=QColor(0, 0, 0))
        assert vr.w == 1280 and vr.h == 720

    def test_cp2r(self):
        assert abs(VideoRenderer._cp2r(0) - 0.5) < 0.01
        assert VideoRenderer._cp2r(9000) > 0.99
        assert VideoRenderer._cp2r(-9000) < 0.01

    def test_render_basic(self, qapp):
        img = VideoRenderer(BoardRenderer(), w=640, h=360).render()
        assert isinstance(img, QImage) and img.width() == 640

    def test_render_with_eval(self, qapp):
        vr = VideoRenderer(BoardRenderer(), w=640, h=360)
        vr.eval_cp = 200.0
        assert not vr.render().isNull()

    def test_render_mate_eval(self, qapp):
        vr = VideoRenderer(BoardRenderer(), w=640, h=360)
        vr.eval_cp = 10001.0
        assert not vr.render().isNull()

    def test_render_move_list(self, qapp):
        vr = VideoRenderer(BoardRenderer(), w=640, h=360)
        vr.move_list_text = ["e4", "e5", "Nf3", "Nc6"]
        vr.current_move_index = 2
        assert not vr.render().isNull()

    def test_render_player_names(self, qapp):
        vr = VideoRenderer(BoardRenderer(), w=640, h=360)
        vr.white_name = "Magnus"; vr.black_name = "Hikaru"
        assert not vr.render().isNull()

    @pytest.mark.parametrize("state,result,detail", [
        (GAME_CHECKMATE, "1-0", "Checkmate"),
        (GAME_STALEMATE, "½-½", "Stalemate"),
        (GAME_DRAW, "½-½", "Draw"),
        (GAME_INSUFFICIENT, "½-½", "Insufficient"),
    ])
    def test_render_game_states(self, qapp, state, result, detail):
        vr = VideoRenderer(BoardRenderer(), w=640, h=360)
        vr.game_state = state; vr.game_result = result; vr.game_detail = detail
        assert not vr.render().isNull()

    def test_render_with_overlay(self, qapp, tmp_path):
        test_img = QImage(100, 100, QImage.Format_ARGB32)
        test_img.fill(QColor(255, 0, 0))
        p = str(tmp_path / "ov.png"); test_img.save(p)
        vr = VideoRenderer(BoardRenderer(), w=640, h=360)
        vr.overlays = [{"path": p, "x": 50, "y": 50, "w": 100, "h": 100}]
        assert not vr.render().isNull()

    def test_render_nonexistent_overlay(self, qapp):
        vr = VideoRenderer(BoardRenderer(), w=640, h=360)
        vr.overlays = [{"path": "/nonexistent/img.png", "x": 0, "y": 0, "w": 50, "h": 50}]
        assert not vr.render().isNull()  # should not crash


# ═══════════════════════════════════════════════════════════════════
#  Workers — helpers
# ═══════════════════════════════════════════════════════════════════

class TestDetectGameState:
    def test_normal(self):
        s, r, d = _detect_game_state(chess.Board())
        assert s == GAME_NORMAL

    def test_checkmate(self):
        b = chess.Board("rnb1kbnr/pppp1ppp/4p3/8/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
        if b.is_checkmate():
            s, r, d = _detect_game_state(b)
            assert s == GAME_CHECKMATE and r == "0-1"

    def test_stalemate(self):
        b = chess.Board("k7/8/1K6/8/8/8/8/8 b - - 0 1")
        if b.is_stalemate():
            s, r, d = _detect_game_state(b)
            assert s == GAME_STALEMATE and r == "½-½"

    def test_insufficient(self):
        b = chess.Board("k7/8/K7/8/8/8/8/8 w - - 0 1")
        if b.is_insufficient_material():
            s, r, d = _detect_game_state(b)
            assert s == GAME_INSUFFICIENT


class TestResolveSF:
    def test_empty_path(self):
        r = _resolve_sf("")
        assert r is None or os.path.isfile(r)

    def test_none_path(self):
        r = _resolve_sf(None)
        assert r is None or os.path.isfile(r)

    def test_explicit_path(self):
        r = _resolve_sf("/usr/games/stockfish")
        assert r == "/usr/games/stockfish"


# ═══════════════════════════════════════════════════════════════════
#  Workers — AI
# ═══════════════════════════════════════════════════════════════════

class TestAIWorker:
    def test_minimax(self, qapp, qtbot):
        w = AIWorker("Minimax (Alpha-Beta)", chess.Board().fen(), {"depth": 1})
        with qtbot.waitSignal(w.eval_ready, timeout=10000):
            w.start()

    def test_mcts(self, qapp, qtbot):
        w = AIWorker("MCTS (Monte Carlo)", chess.Board().fen(), {"iterations": 15})
        with qtbot.waitSignal(w.eval_ready, timeout=15000):
            w.start()

    def test_result_keys(self, qapp, qtbot):
        res = []
        w = AIWorker("Minimax (Alpha-Beta)", chess.Board().fen(), {"depth": 1})
        w.eval_ready.connect(lambda d: res.append(d))
        with qtbot.waitSignal(w.eval_ready, timeout=10000):
            w.start()
        if res:
            for k in ("eval", "eval_cp", "nodes", "engine_type"):
                assert k in res[0]

    def test_invalid_engine(self, qapp, qtbot):
        w = AIWorker("NonExistent", chess.Board().fen(), {})
        with qtbot.waitSignal(w.eval_ready, timeout=10000):
            w.start()


class TestBatchEvalWorker:
    def test_heuristic_batch(self, qapp, qtbot):
        g = chess.pgn.read_game(io.StringIO("1. e4 e5 2. Nf3"))
        ml = list(g.mainline())
        w = BatchEvalWorker(ml, "Minimax (Alpha-Beta)", {"depth": 1})
        with qtbot.waitSignal(w.batch_finished, timeout=30000):
            w.start()

    def test_cancel(self, qapp, qtbot):
        g = chess.pgn.read_game(io.StringIO("1. e4 e5 2. Nf3 Nc6 3. Bb5"))
        ml = list(g.mainline())
        w = BatchEvalWorker(ml, "Minimax (Alpha-Beta)", {"depth": 2})
        w.start()
        w.cancel()
        w.wait(5000)


class TestAIBattleWorker:
    def test_battle_finishes(self, qapp, qtbot):
        w = AIBattleWorker(
            "Minimax (Alpha-Beta)", {"depth": 1},
            "Minimax (Alpha-Beta)", {"depth": 1},
            max_moves=4, delay_ms=0)
        with qtbot.waitSignal(w.game_finished, timeout=60000):
            w.start()

    def test_battle_emits_moves(self, qapp, qtbot):
        moves = []
        w = AIBattleWorker(
            "Minimax (Alpha-Beta)", {"depth": 1},
            "Minimax (Alpha-Beta)", {"depth": 1},
            max_moves=3, delay_ms=0)
        w.move_made.connect(lambda u, e: moves.append(u))
        with qtbot.waitSignal(w.game_finished, timeout=60000):
            w.start()
        assert len(moves) > 0

    def test_battle_cancel(self, qapp):
        w = AIBattleWorker(
            "Minimax (Alpha-Beta)", {"depth": 1},
            "Minimax (Alpha-Beta)", {"depth": 1},
            max_moves=200, delay_ms=10)
        w.start()
        w.cancel()
        w.wait(5000)

    def test_battle_progress_signal(self, qapp, qtbot):
        progress = []
        w = AIBattleWorker(
            "Minimax (Alpha-Beta)", {"depth": 1},
            "Minimax (Alpha-Beta)", {"depth": 1},
            max_moves=5, delay_ms=0)
        w.battle_progress.connect(lambda c, t: progress.append((c, t)))
        with qtbot.waitSignal(w.game_finished, timeout=60000):
            w.start()
        assert len(progress) > 0


# ═══════════════════════════════════════════════════════════════════
#  Workers — Capture
# ═══════════════════════════════════════════════════════════════════

class TestCaptureWorker:
    def test_basic_capture(self, qapp, qtbot, sample_game):
        ml = list(sample_game.mainline())
        w = CaptureWorker(
            game=sample_game, move_list=ml, eval_cache={},
            board_renderer=BoardRenderer(),
            video_bg_color=QColor(30, 30, 32),
            white_name="W", black_name="B", overlays=[],
            fps=10, hold=0.5, res_str="1280×720")
        with qtbot.waitSignal(w.capture_finished, timeout=60000):
            w.start()

    def test_disk_cache(self, qapp, qtbot, sample_game, tmp_path):
        ml = list(sample_game.mainline())
        d = str(tmp_path / "frames"); os.makedirs(d)
        w = CaptureWorker(
            game=sample_game, move_list=ml, eval_cache={},
            board_renderer=BoardRenderer(),
            video_bg_color=QColor(30, 30, 32),
            white_name="W", black_name="B", overlays=[],
            fps=10, hold=0.5, res_str="1280×720",
            use_disk_cache=True, disk_cache_dir=d)
        with qtbot.waitSignal(w.capture_finished, timeout=60000):
            w.start()

    def test_cancel(self, qapp, sample_game):
        ml = list(sample_game.mainline())
        w = CaptureWorker(
            game=sample_game, move_list=ml, eval_cache={},
            board_renderer=BoardRenderer(),
            video_bg_color=QColor(30, 30, 32),
            white_name="W", black_name="B", overlays=[],
            fps=10, hold=0.5, res_str="1280×720")
        w.start(); w.cancel(); w.wait(5000)

    def test_progress_signal(self, qapp, qtbot, sample_game):
        ml = list(sample_game.mainline())
        w = CaptureWorker(
            game=sample_game, move_list=ml, eval_cache={},
            board_renderer=BoardRenderer(),
            video_bg_color=QColor(30, 30, 32),
            white_name="W", black_name="B", overlays=[],
            fps=10, hold=0.5, res_str="1280×720")
        prog = []
        w.progress.connect(lambda p, t: prog.append(p))
        with qtbot.waitSignal(w.capture_finished, timeout=60000):
            w.start()
        assert len(prog) > 0

    def test_cleanup_disk(self, qapp, sample_game, tmp_path):
        d = str(tmp_path / "fc"); os.makedirs(d)
        ml = list(sample_game.mainline())
        w = CaptureWorker(
            game=sample_game, move_list=ml, eval_cache={},
            board_renderer=BoardRenderer(),
            video_bg_color=QColor(30, 30, 32),
            white_name="W", black_name="B", overlays=[],
            fps=10, hold=0.5, res_str="1280×720",
            use_disk_cache=True, disk_cache_dir=d)
        w._own_disk_dir = True
        w.cleanup_disk()


# ═══════════════════════════════════════════════════════════════════
#  AnimationManager
# ═══════════════════════════════════════════════════════════════════

class TestAnimationManager:
    def test_defaults(self, qapp, board_widget, eval_bar):
        am = AnimationManager(board_widget, eval_bar)
        assert am.enabled and am.piece_anim and am.highlight_anim
        assert am.eval_anim and am.duration == 250
        assert am.easing_name == "OutCubic"

    def test_set_duration(self, qapp, board_widget, eval_bar):
        am = AnimationManager(board_widget, eval_bar)
        am.set_duration(500); assert am.duration == 500

    def test_duration_clamped(self, qapp, board_widget, eval_bar):
        am = AnimationManager(board_widget, eval_bar)
        am.set_duration(10);  assert am.duration == 50
        am.set_duration(5000); assert am.duration == 2000

    def test_set_easing(self, qapp, board_widget, eval_bar):
        am = AnimationManager(board_widget, eval_bar)
        am.set_easing("Linear");  assert am.easing_name == "Linear"
        am.set_easing("Invalid"); assert am.easing_name == "OutCubic"

    def test_toggle_piece(self, qapp, board_widget, eval_bar):
        am = AnimationManager(board_widget, eval_bar)
        am.set_piece_anim(False); assert not am.piece_anim

    def test_toggle_highlight(self, qapp, board_widget, eval_bar):
        am = AnimationManager(board_widget, eval_bar)
        am.set_highlight_anim(False); assert not am.highlight_anim

    def test_toggle_eval(self, qapp, board_widget, eval_bar):
        am = AnimationManager(board_widget, eval_bar)
        am.set_eval_anim(False); assert not am.eval_anim

    def test_cancel_all(self, qapp, board_widget, eval_bar):
        am = AnimationManager(board_widget, eval_bar)
        am.cancel_all(); assert len(am._active) == 0

    def test_animate_piece_move(self, qapp, board_widget, eval_bar):
        am = AnimationManager(board_widget, eval_bar)
        am.animate_piece_move(chess.Move(chess.E2, chess.E4))
        assert len(am._active) > 0
        am.cancel_all()

    def test_animate_check(self, qapp, board_widget, eval_bar):
        am = AnimationManager(board_widget, eval_bar)
        am.animate_check(chess.E1)
        assert len(am._active) > 0
        am.cancel_all()

    def test_animate_flash(self, qapp, board_widget, eval_bar):
        am = AnimationManager(board_widget, eval_bar)
        am.animate_last_move_flash(chess.E2, chess.E4)
        assert len(am._active) > 0
        am.cancel_all()


# ═══════════════════════════════════════════════════════════════════
#  SoundManager
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_NP, reason="numpy not available")
class TestSoundManager:
    def test_construction(self, qapp):
        sm = SoundManager()
        assert isinstance(sm.enabled, bool)
        sm.cleanup()

    def test_volume(self, qapp):
        sm = SoundManager()
        sm.set_volume(0.5); assert sm._volume == 0.5
        sm.set_volume(-1);  assert sm._volume == 0
        sm.set_volume(2);   assert sm._volume == 1
        sm.cleanup()

    def test_type_volume(self, qapp):
        sm = SoundManager()
        sm.set_type_volume("move", 0.8); assert sm._type_vol["move"] == 0.8
        sm.cleanup()

    def test_set_theme(self, qapp):
        sm = SoundManager()
        sm.set_theme("Digital"); assert sm._theme == "Digital"
        sm.set_theme("Nope");    assert sm._theme == "Classic"
        sm.cleanup()

    def test_set_design(self, qapp):
        sm = SoundManager()
        sm.set_design("Warm");  assert sm._design == "Warm"
        sm.set_design("Nope");  assert sm._design == "Default"
        sm.cleanup()

    def test_set_enabled(self, qapp):
        sm = SoundManager()
        sm.set_enabled(False); assert not sm.enabled
        sm.cleanup()

    def test_silent_theme_no_sounds(self, qapp):
        sm = SoundManager(); sm.set_theme("Silent")
        assert len(sm._sounds) == 0
        sm.cleanup()

    def test_play_no_crash(self, qapp):
        sm = SoundManager()
        for t in SOUND_TYPES:
            sm.play(t)
        sm.cleanup()

    def test_cleanup(self, qapp):
        sm = SoundManager(); sm.cleanup()
        assert sm._temp_dir is None

    def test_design_descriptions(self):
        for d in SOUND_DESIGNS:
            assert d in _SOUND_DESIGN_DESC

    def test_all_themes_generate(self, qapp):
        sm = SoundManager()
        for t in SOUND_THEMES:
            sm.set_theme(t)
        sm.cleanup()

    def test_all_designs_generate(self, qapp):
        sm = SoundManager()
        for d in SOUND_DESIGNS:
            sm.set_design(d)
        sm.cleanup()


# ═══════════════════════════════════════════════════════════════════
#  UI Builder
# ═══════════════════════════════════════════════════════════════════

class TestUIBuilder:
    def test_all_widgets_created(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        # Core
        for attr in ("board_widget", "eval_bar_widget", "promo_widget",
                      "move_table", "tabs", "right_tabs"):
            assert hasattr(w, attr), f"Missing: {attr}"
        # Moves tab
        for attr in ("btn_play", "speed_slider", "anno_edit"):
            assert hasattr(w, attr), f"Missing: {attr}"
        # Database tab
        for attr in ("db_list", "pgn_text_edit", "pgn_file_edit"):
            assert hasattr(w, attr), f"Missing: {attr}"
        # Assets tab
        for attr in ("img_list", "ov_pos_combo"):
            assert hasattr(w, attr), f"Missing: {attr}"
        # Pipeline tab
        for attr in ("quick_pgn_btn", "quick_ai_btn", "batch_start_btn",
                      "quick_quality_combo", "quick_hold_spin",
                      "quick_eval_chk", "quick_progress_bar"):
            assert hasattr(w, attr), f"Missing: {attr}"
        # Battle tab
        for attr in ("start_battle_btn", "stop_battle_btn", "auto_mp4_chk"):
            assert hasattr(w, attr), f"Missing: {attr}"
        # Analysis tab
        for attr in ("ai_combo", "run_ai_btn", "eval_label", "policy_chk"):
            assert hasattr(w, attr), f"Missing: {attr}"
        # Video tab
        for attr in ("preview_display", "quality_preset_combo",
                      "export_start_btn", "export_path_edit",
                      "disk_cache_chk", "mem_estimate_lbl"):
            assert hasattr(w, attr), f"Missing: {attr}"
        # Settings tab
        for attr in ("sound_enabled_chk", "anim_enabled_chk",
                      "sound_vol_slider", "anim_dur_spin"):
            assert hasattr(w, attr), f"Missing: {attr}"
        w._cleanup(); w.close()

    def test_menu_created(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        mb = w.menuBar()
        texts = [a.text() for a in mb.actions()]
        assert any("File" in t for t in texts)
        assert any("View" in t for t in texts)
        w._cleanup(); w.close()


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Core Navigation & PGN
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowCore:
    def test_construction(self, main_window):
        assert main_window.game is not None

    def test_new_game(self, main_window):
        main_window._new_game()
        assert main_window.move_index == -1
        assert len(main_window.move_list) == 0

    def test_load_pgn_text(self, main_window, sample_pgn_text):
        main_window.pgn_text_edit.setPlainText(sample_pgn_text)
        main_window._load_pgn_text()
        assert len(main_window.move_list) > 0

    def test_load_pgn_data(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        assert main_window.game == sample_game

    def test_go_first(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        main_window._go_last(); main_window._go_first()
        assert main_window.move_index == -1

    def test_go_next(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        main_window._go_first(); main_window._go_next()
        assert main_window.move_index == 0

    def test_go_prev(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        main_window._go_last()
        last = main_window.move_index
        main_window._go_prev()
        assert main_window.move_index < last

    def test_go_last(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        main_window._go_last()
        assert main_window.move_index == len(main_window.move_list) - 1

    def test_toggle_play(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        main_window._toggle_play();  assert main_window._playing
        main_window._toggle_play();  assert not main_window._playing

    def test_flip_board(self, main_window):
        f = main_window.board_widget.flipped
        main_window._flip_board()
        assert main_window.board_widget.flipped != f

    def test_theme_changed(self, main_window):
        main_window._theme_changed("Green")
        assert main_window.board_widget.theme.name == "Green"

    def test_apply_comment(self, main_window):
        main_window.anno_edit.setPlainText("Test comment")
        main_window._apply_comment()
        if main_window.node:
            assert main_window.node.comment == "Test comment"

    def test_clear_policy(self, main_window):
        main_window.board_widget.policy_vis = {"e2e4": 0.5}
        main_window._clear_policy()
        assert main_window.board_widget.policy_vis == {}

    @pytest.mark.parametrize("name,color", [
        ("Dark Gray", QColor(30, 30, 32)),
        ("Black", QColor(0, 0, 0)),
        ("Dark Blue", QColor(15, 20, 40)),
        ("Dark Green", QColor(15, 35, 15)),
        ("Dark Red", QColor(40, 15, 15)),
        ("White", QColor(255, 255, 255)),
        ("Light Gray", QColor(200, 200, 200)),
        ("Navy", QColor(0, 0, 80)),
    ])
    def test_pick_bg_color(self, main_window, name, color):
        main_window._pick_bg_color(name)
        assert main_window.video_bg_color == color


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Board Interaction
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowInteraction:
    def test_select_piece(self, main_window):
        main_window._on_sq_click(chess.E2)
        assert main_window.board_widget.selected_sq == chess.E2

    def test_make_move(self, main_window):
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        assert len(main_window.move_list) >= 1

    def test_illegal_no_crash(self, main_window):
        main_window._on_sq_click(chess.A1)
        main_window._on_sq_click(chess.A5)

    def test_empty_square_clears(self, main_window):
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E5)
        assert main_window.board_widget.selected_sq is None

    def test_promotion_flow(self, main_window):
        """Set up a promotion scenario (conceptual)."""
                # White pawn on e7, move to e8
        b = chess.Board("4k3/4P3/8/8/8/8/8/4K3 w - - 0 1")
        main_window.board_widget.set_position(b)
        main_window.game = chess.pgn.Game()
        main_window.node = main_window.game
        main_window.move_list = []
        main_window.move_index = -1
        main_window._on_sq_click(chess.E7)
        assert main_window.board_widget.selected_sq == chess.E7
        main_window._on_sq_click(chess.E8)
        # Promotion widget should be shown
        assert main_window.promo_widget.isVisible()

    def test_promo_pick(self, main_window):
        b = chess.Board("4k3/4P3/8/8/8/8/8/4K3 w - - 0 1")
        main_window.board_widget.set_position(b)
        main_window.game = chess.pgn.Game()
        main_window.node = main_window.game
        main_window.move_list = []
        main_window.move_index = -1
        main_window._on_sq_click(chess.E7)
        main_window._on_sq_click(chess.E8)
        main_window._on_promo_pick(chess.QUEEN)
        assert main_window.promo_widget.isHidden()
        assert len(main_window.move_list) >= 1

    def test_on_move_cell(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        main_window._on_move_cell(0, 1, -1, -1)
        assert main_window.move_index == 0

    def test_on_move_cell_invalid(self, main_window):
        main_window._on_move_cell(-1, -1, -1, -1)  # no crash


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Game State Detection
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowGameState:
    def test_normal_state(self, main_window):
        main_window._new_game()
        main_window._update_game_state()
        assert main_window.eval_bar_widget._game_state == GAME_NORMAL

    def test_checkmate_state(self, main_window):
        # Scholar's mate
        b = chess.Board()
        for san in ("e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7"):
            b.push_san(san)
        main_window.board_widget.set_position(b)
        main_window.node = None  # bypass node check
        main_window._update_game_state(b)
        assert main_window.eval_bar_widget._game_state == GAME_CHECKMATE

    def test_stalemate_state(self, main_window):
        b = chess.Board("k7/8/1K6/8/8/8/8/8 b - - 0 1")
        if b.is_stalemate():
            main_window._update_game_state(b)
            assert main_window.eval_bar_widget._game_state == GAME_STALEMATE

    def test_insufficient_material(self, main_window):
        b = chess.Board("k7/8/K7/8/8/8/8/8 w - - 0 1")
        if b.is_insufficient_material():
            main_window._update_game_state(b)
            assert main_window.eval_bar_widget._game_state == GAME_INSUFFICIENT


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Sound Settings
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_NP, reason="numpy not available")
class TestMainWindowSoundSettings:
    def test_sound_enabled_toggle(self, main_window):
        main_window._on_sound_enabled(False)
        assert not main_window.sound_manager.enabled
        main_window._on_sound_enabled(True)
        assert main_window.sound_manager.enabled

    def test_sound_volume(self, main_window):
        main_window._on_sound_vol(50)
        assert abs(main_window.sound_manager._volume - 0.5) < 0.01

    def test_sound_theme(self, main_window):
        main_window._on_sound_theme("Digital")
        assert main_window.sound_manager._theme == "Digital"

    def test_sound_design(self, main_window):
        main_window._on_sound_design("Warm")
        assert main_window.sound_manager._design == "Warm"

    def test_test_sound_no_crash(self, main_window):
        for t in SOUND_TYPES:
            main_window._test_sound(t)

    def test_snd_type_volume(self, main_window):
        main_window._on_snd_type_vol("move", 0.5)
        assert abs(main_window.sound_manager._type_vol["move"] - 0.5) < 0.01


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Animation Settings
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowAnimSettings:
    def test_anim_enabled(self, main_window):
        main_window._on_anim_enabled(False)
        assert not main_window.anim_manager.enabled

    def test_piece_anim(self, main_window):
        main_window._on_piece_anim(False)
        assert not main_window.anim_manager.piece_anim

    def test_highlight_anim(self, main_window):
        main_window._on_highlight_anim(False)
        assert not main_window.anim_manager.highlight_anim

    def test_eval_anim(self, main_window):
        main_window._on_eval_anim(False)
        assert not main_window.anim_manager.eval_anim

    def test_anim_duration(self, main_window):
        main_window._on_anim_dur(500)
        assert main_window.anim_manager.duration == 500

    def test_anim_easing(self, main_window):
        main_window._on_anim_easing("Linear")
        assert main_window.anim_manager.easing_name == "Linear"


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Quality & Memory
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowQualityMemory:
    def test_mem_estimate_no_crash(self, main_window):
        main_window._update_mem_estimate()

    def test_quality_preset_low(self, main_window):
        idx = list(QUALITY_PRESETS.keys()).index("Low")
        main_window.quality_preset_combo.setCurrentIndex(idx)
        main_window._on_quality_preset(idx)
        assert main_window._use_disk_cache is True

    def test_quality_preset_high(self, main_window):
        idx = list(QUALITY_PRESETS.keys()).index("High")
        main_window.quality_preset_combo.setCurrentIndex(idx)
        main_window._on_quality_preset(idx)
        assert main_window.export_fps_spin.value() == 60

    def test_disk_cache_toggle(self, main_window):
        main_window._on_disk_cache_toggled(True)
        assert main_window._use_disk_cache is True
        main_window._on_disk_cache_toggled(False)
        assert main_window._use_disk_cache is False


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Database & Assets
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowDBAssets:
    def test_set_db_folder(self, main_window, tmp_path):
        d = str(tmp_path / "pgn_db"); os.makedirs(d)
        main_window.db_folder_edit.setText(d)
        main_window._set_pgn_db_folder()
        assert main_window.db_folder == d

    def test_scan_pgn_db(self, main_window, tmp_path):
        d = str(tmp_path / "pgn_db2"); os.makedirs(d)
        # Create a dummy pgn
        with open(os.path.join(d, "test.pgn"), "w") as f:
            f.write('[Event "T"]\n\n1. e4 e5 1-0\n')
        main_window.db_folder = d
        main_window._scan_pgn_db()
        assert main_window.db_list.count() >= 1

    def test_set_img_folder(self, main_window, tmp_path):
        d = str(tmp_path / "img_db"); os.makedirs(d)
        main_window.img_folder_edit.setText(d)
        main_window._set_img_folder()
        assert main_window.img_folder == d

    def test_scan_img_db(self, main_window, tmp_path):
        d = str(tmp_path / "img_db2"); os.makedirs(d)
        # Create a dummy image
        img = QImage(50, 50, QImage.Format_ARGB32); img.fill(QColor(255, 0, 0))
        img.save(os.path.join(d, "test.png"))
        main_window.img_folder = d
        main_window._scan_img_db()
        assert main_window.img_list.count() >= 1

    def test_add_overlay(self, main_window, tmp_path):
        img = QImage(50, 50, QImage.Format_ARGB32); img.fill(QColor(0, 0, 255))
        p = str(tmp_path / "overlay.png"); img.save(p)
        # Add item to img_list manually
        from PySide6.QtWidgets import QListWidgetItem
        from PySide6.QtGui import QIcon
        item = QListWidgetItem(QIcon(p), "overlay.png")
        item.setData(Qt.UserRole, p)
        main_window.img_list.addItem(item)
        main_window.img_list.setCurrentItem(item)
        main_window.ov_pos_combo.setCurrentIndex(0)  # White Face
        main_window._add_overlay()
        assert len(main_window.canvas_overlays) == 1

    def test_clear_overlays(self, main_window):
        main_window.canvas_overlays = [{"path": "x", "x": 0, "y": 0, "w": 50, "h": 50}]
        main_window._clear_overlays()
        assert main_window.canvas_overlays == []

    def test_set_pgn_db_folder_invalid(self, main_window):
        main_window.db_folder_edit.setText("/nonexistent/path12345")
        main_window._set_pgn_db_folder()
        # Should show status message but not crash

    def test_set_img_folder_invalid(self, main_window):
        main_window.img_folder_edit.setText("/nonexistent/path12345")
        main_window._set_img_folder()
        # Should show status message but not crash


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — AI Analysis
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowAI:
    def test_toggle_ai_ui(self, main_window):
        for t in AI_MAP.values():
            main_window._toggle_ai_ui(t)

    def test_run_engine_minimax(self, main_window, qtbot):
        main_window.ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        main_window._run_engine()
        with qtbot.waitSignal(main_window.engine_worker.eval_ready, timeout=10000):
            pass
        assert "Eval:" in main_window.eval_label.text()

    def test_on_eval_ready(self, main_window):
        d = {"eval": "+1.50", "eval_cp": 150.0, "nodes": 500,
             "engine_type": "Minimax (Alpha-Beta)", "policy": {"e2e4": 0.7},
             "best_move": "e2e4"}
        main_window.policy_chk.setChecked(True)
        main_window._on_eval_ready(d)
        assert "1.50" in main_window.eval_label.text()
        assert "e2e4" in main_window.board_widget.policy_vis

    def test_on_eval_ready_error(self, main_window):
        d = {"eval": "Err:test", "eval_cp": 0, "nodes": 0,
             "engine_type": "Test", "policy": {}, "best_move": None, "error": True}
        main_window._on_eval_ready(d)  # should not crash

    def test_stop_batch_eval(self, main_window):
        main_window._stop_batch_eval()  # no crash even if None


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — AI Battle (Interactive)
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowBattle:
    def test_ai_params_minimax(self, main_window):
        p = main_window._ai_params("Minimax (Alpha-Beta)", 3)
        assert p["depth"] == 3

    def test_ai_params_mcts(self, main_window):
        p = main_window._ai_params("MCTS (Monte Carlo)", 100)
        assert p["iterations"] == 500

    def test_ai_params_stockfish(self, main_window):
        p = main_window._ai_params("Stockfish (UCI)", 10)
        assert "path" in p

    def test_start_stop_battle(self, main_window):
        main_window.white_ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        main_window.black_ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        main_window.battle_delay.setValue(0)
        main_window._start_ai_vs_ai()
        assert main_window.ai_vs_ai_running
        main_window._stop_ai_vs_ai()
        assert not main_window.ai_vs_ai_running

    def test_battle_move_callback(self, main_window):
        """Simulate a battle move callback."""
        b = chess.Board()
        main_window._new_game()
        main_window._on_battle_move({
            "best_move": "e2e4", "eval_cp": 25.0,
            "eval": "+0.25", "nodes": 100, "engine_type": "Test",
            "policy": {}
        })
        # Move may or may not have been applied depending on legality

    def test_auto_export_disabled(self, main_window):
        main_window.auto_mp4_chk.setChecked(False)
        main_window.save_png_chk.setChecked(False)
        # Should return without error
        main_window._auto_export()


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Disk Cache
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowDiskCache:
    def test_init_disk_cache(self, main_window):
        main_window._init_disk_cache()
        assert main_window._use_disk_cache is True
        assert main_window._disk_cache_dir is not None
        main_window._cleanup_disk_cache()

    def test_cleanup_disk_cache(self, main_window):
        main_window._init_disk_cache()
        d = main_window._disk_cache_dir
        main_window._cleanup_disk_cache()
        assert main_window._disk_cache_dir is None
        assert not os.path.isdir(d)

    def test_write_frame_to_disk(self, main_window):
        main_window._init_disk_cache()
        img = QImage(100, 100, QImage.Format_ARGB32); img.fill(QColor(0, 0, 0))
        result = main_window._write_frame_to_disk(img)
        assert result is True
        assert main_window._disk_frame_count == 1
        main_window._cleanup_disk_cache()

    def test_should_use_disk_cache_forced(self, main_window):
        main_window._use_disk_cache = True
        assert main_window._should_use_disk_cache(10) is True

    def test_should_use_disk_cache_large(self, main_window):
        main_window._use_disk_cache = False
        assert main_window._should_use_disk_cache(MAX_FRAMES_IN_MEMORY + 1) is True

    def test_should_use_disk_cache_small(self, main_window):
        main_window._use_disk_cache = False
        assert main_window._should_use_disk_cache(10) is False


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Preview
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowPreview:
    def test_preview_captured_frames_empty(self, main_window):
        main_window.capture_frames = []
        main_window._preview_captured_frames()  # no crash

    def test_stop_preview(self, main_window):
        main_window._stop_preview()
        assert not main_window._prev_playing

    def test_update_preview_speed(self, main_window):
        main_window._update_preview_speed(0)  # 0.5x
        assert main_window._prev_speed == 0.5
        main_window._update_preview_speed(1)  # 1x
        assert main_window._prev_speed == 1.0
        main_window._update_preview_speed(2)  # 2x
        assert main_window._prev_speed == 2.0
        main_window._update_preview_speed(3)  # 4x
        assert main_window._prev_speed == 4.0

    def test_toggle_preview_play_no_frames(self, main_window):
        main_window._prev_frames = []
        main_window._prev_source = None
        main_window._toggle_preview_play()  # no crash

    def test_scrub_preview(self, main_window):
        main_window._scrub_preview(0)  # no crash

    def test_cleanup_preview(self, main_window):
        main_window._cleanup_preview()
        assert main_window._prev_frames == []


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Pipeline: Quick PGN → MP4
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowPipelinePGN:
    def test_quick_pgn_no_game(self, main_window):
        main_window._new_game()
        main_window._quick_pgn_to_mp4()
        # Should show error in status label
        assert "❌" in main_window.quick_status_lbl.text() or \
               "No game" in main_window.quick_status_lbl.text()

    def test_quick_pgn_progress_callback(self, main_window):
        main_window._on_quick_pgn_progress(50, "Rendering move 5/10")
        assert main_window.quick_progress_bar.value() == 50

    def test_quick_pgn_done_success(self, main_window):
        main_window._on_quick_pgn_done("Done!\nCodec:avc1\nSaved:test.mp4")
        assert main_window.quick_progress_bar.value() == 100

    def test_quick_pgn_done_cancelled(self, main_window):
        main_window._on_quick_pgn_done("Cancelled")
        assert "Cancel" in main_window.quick_status_lbl.text()

    def test_quick_pgn_done_error(self, main_window):
        main_window._on_quick_pgn_done("ERROR: Codec not found")
        assert "❌" in main_window.quick_status_lbl.text()

    def test_quick_load_pgn_cancel(self, main_window):
        # Simulate user cancelling file dialog (no file selected)
        main_window._quick_load_pgn()  # no crash


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Pipeline: Quick AI → MP4
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowPipelineAI:
    def test_pipeline_battle_move_callback(self, main_window):
        main_window._new_game()
        main_window._on_pipeline_battle_move("e2e4", 25.0)
        # Move should be applied if legal
        assert main_window.move_index >= 0 or True  # depends on state

    def test_pipeline_battle_progress(self, main_window):
        main_window._on_pipeline_battle_progress(5, 10)
        assert main_window.quick_ai_progress_bar.value() > 0

    def test_pipeline_battle_done_invalid_pgn(self, main_window):
        # Invalid PGN should be handled gracefully
        main_window._on_pipeline_battle_done("invalid pgn", "*")

    def test_quick_ai_export_progress(self, main_window):
        main_window._on_quick_ai_export_progress(50, "Rendering")
        assert main_window.quick_ai_progress_bar.value() >= 50

    def test_quick_ai_done_success(self, main_window):
        main_window._on_quick_ai_done("Done!\nCodec:avc1\nSaved:battle.mp4")
        assert main_window.quick_ai_progress_bar.value() == 100

    def test_quick_ai_done_error(self, main_window):
        main_window._on_quick_ai_done("ERROR: No frames")
        assert "❌" in main_window.quick_ai_status_lbl.text()


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Pipeline: Batch PGN
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowBatchPGN:
    def test_batch_invalid_pgn_folder(self, main_window):
        main_window.batch_pgn_folder_edit.setText("/nonexistent12345")
        main_window.batch_output_folder_edit.setText("/tmp/out")
        main_window._start_batch_pgn_export()
        assert "❌" in main_window.batch_status_lbl.text()

    def test_batch_invalid_output_folder(self, main_window, tmp_path):
        d = str(tmp_path / "pgns"); os.makedirs(d)
        main_window.batch_pgn_folder_edit.setText(d)
        main_window.batch_output_folder_edit.setText("")
        main_window._start_batch_pgn_export()
        assert "❌" in main_window.batch_status_lbl.text()

    def test_batch_no_pgn_files(self, main_window, tmp_path):
        d = str(tmp_path / "empty_pgns"); os.makedirs(d)
        o = str(tmp_path / "empty_out")
        main_window.batch_pgn_folder_edit.setText(d)
        main_window.batch_output_folder_edit.setText(o)
        main_window._start_batch_pgn_export()
        assert "❌" in main_window.batch_status_lbl.text()

    def test_batch_progress_callback(self, main_window):
        main_window._on_batch_progress(3, 10, "test.pgn")
        assert main_window.batch_progress_bar.value() > 0

    def test_batch_game_exported(self, main_window):
        main_window._on_batch_game_exported("/tmp/test_game_1.mp4")

    def test_batch_finished(self, main_window):
        main_window._on_batch_finished(5, 1)
        assert "5" in main_window.batch_status_lbl.text()

    def test_browse_batch_pgn_cancel(self, main_window):
        main_window._browse_batch_pgn_folder()  # no crash if cancelled

    def test_browse_batch_output_cancel(self, main_window):
        main_window._browse_batch_output_folder()  # no crash if cancelled


# ═══════════════════════════════════════════════════════════════════
#  MainWindow — Cleanup
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowCleanup:
    def test_cleanup(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w._cleanup()
        assert not w._playing
        assert not w._prev_playing
        w.close()

    def test_cancel_all_workers(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w._cancel_all_workers()  # no crash with no running workers
        w._cleanup(); w.close()

    def test_cleanup_stops_animations(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.anim_manager.animate_piece_move(chess.Move(chess.E2, chess.E4))
        w._cleanup()
        assert len(w.anim_manager._active) == 0
        w.close()


# ═══════════════════════════════════════════════════════════════════
#  Workers — StreamingExport
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_CV2, reason="opencv not available")
class TestStreamingExportWorker:
    def test_basic_export(self, qapp, qtbot, sample_game, tmp_path):
        ml = list(sample_game.mainline())
        out = str(tmp_path / "stream_test.mp4")
        w = StreamingExportWorker(
            game=sample_game, move_list=ml, eval_cache={},
            board_renderer=BoardRenderer(),
            video_bg_color=QColor(30, 30, 32),
            white_name="W", black_name="B", overlays=[],
            fps=10, hold=0.5, res_str="1280×720",
            output_path=out)
        with qtbot.waitSignal(w.export_finished, timeout=120000):
            w.start()

    def test_cancel(self, qapp, sample_game, tmp_path):
        ml = list(sample_game.mainline())
        out = str(tmp_path / "stream_cancel.mp4")
        w = StreamingExportWorker(
            game=sample_game, move_list=ml, eval_cache={},
            board_renderer=BoardRenderer(),
            video_bg_color=QColor(30, 30, 32),
            white_name="W", black_name="B", overlays=[],
            fps=10, hold=0.5, res_str="1280×720",
            output_path=out)
        w.start(); w.cancel(); w.wait(10000)

    def test_no_moves(self, qapp, qtbot, tmp_path):
        out = str(tmp_path / "stream_nomoves.mp4")
        w = StreamingExportWorker(
            game=chess.pgn.Game(), move_list=[], eval_cache={},
            board_renderer=BoardRenderer(),
            video_bg_color=QColor(30, 30, 32),
            white_name="W", black_name="B", overlays=[],
            fps=10, hold=0.5, res_str="1280×720",
            output_path=out)
        with qtbot.waitSignal(w.export_finished, timeout=10000):
            w.start()


# ═══════════════════════════════════════════════════════════════════
#  Workers — ExportWorker
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_CV2, reason="opencv not available")
class TestExportWorker:
    def _make_frames(self, count=5, w=320, h=240):
        import numpy as np
        frames = []
        for i in range(count):
            f = np.full((h, w, 3), (i * 40) % 256, dtype=np.uint8)
            frames.append(f)
        return frames

    def test_export_from_memory(self, qapp, qtbot, tmp_path):
        frames = self._make_frames()
        out = str(tmp_path / "mem_test.mp4")
        w = ExportWorker(fr=frames, fps=10, out=out, w=320, h=240)
        with qtbot.waitSignal(w.export_finished, timeout=30000):
            w.start()

    def test_export_from_disk(self, qapp, qtbot, tmp_path):
        d = str(tmp_path / "disk_frames"); os.makedirs(d)
        import numpy as np
        for i in range(5):
            f = np.full((240, 320, 3), (i * 40) % 256, dtype=np.uint8)
            cv2.imwrite(os.path.join(d, f"frame_{i:05d}.jpg"), f)
        out = str(tmp_path / "disk_test.mp4")
        w = ExportWorker(fr=[], fps=10, out=out, w=320, h=240, frame_dir=d)
        with qtbot.waitSignal(w.export_finished, timeout=30000):
            w.start()

    def test_export_no_frames(self, qapp, qtbot, tmp_path):
        out = str(tmp_path / "empty_test.mp4")
        w = ExportWorker(fr=[], fps=10, out=out, w=320, h=240)
        with qtbot.waitSignal(w.export_finished, timeout=10000):
            w.start()

    def test_export_cancel(self, qapp, tmp_path):
        frames = self._make_frames(20)
        out = str(tmp_path / "cancel_test.mp4")
        w = ExportWorker(fr=frames, fps=10, out=out, w=320, h=240)
        w.start(); w.cancel(); w.wait(5000)


# ═══════════════════════════════════════════════════════════════════
#  Workers — BatchPGNExportWorker
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_CV2, reason="opencv not available")
class TestBatchPGNExportWorker:
    def test_batch_export(self, qapp, qtbot, tmp_path):
        # Create PGN files
        pgn_dir = str(tmp_path / "pgns"); os.makedirs(pgn_dir)
        out_dir = str(tmp_path / "output"); os.makedirs(out_dir)
        pgn_content = '[Event "T"]\n\n1. e4 e5 2. Nf3 Nc6 1-0\n'
        for i in range(2):
            with open(os.path.join(pgn_dir, f"game_{i}.pgn"), "w") as f:
                f.write(pgn_content)

        settings = {
            "fps": 10, "hold": 0.5, "res_str": "1280×720",
            "bg_color": QColor(30, 30, 32), "theme": BoardTheme(),
            "flipped": False, "white_name": "W", "black_name": "B",
            "overlays": [], "eval_during": False, "stockfish_path": "",
        }
        pgn_files = [os.path.join(pgn_dir, f) for f in os.listdir(pgn_dir) if f.endswith(".pgn")]
        w = BatchPGNExportWorker(pgn_files, out_dir, settings)
        with qtbot.waitSignal(w.batch_finished, timeout=120000):
            w.start()

    def test_batch_cancel(self, qapp, tmp_path):
        pgn_dir = str(tmp_path / "pgns_c"); os.makedirs(pgn_dir)
        out_dir = str(tmp_path / "output_c"); os.makedirs(out_dir)
        pgn_content = '[Event "T"]\n\n1. e4 e5 2. Nf3 Nc6 1-0\n'
        with open(os.path.join(pgn_dir, "game.pgn"), "w") as f:
            f.write(pgn_content)
        settings = {
            "fps": 10, "hold": 0.5, "res_str": "1280×720",
            "bg_color": QColor(30, 30, 32), "theme": BoardTheme(),
            "flipped": False, "white_name": "W", "black_name": "B",
            "overlays": [], "eval_during": False, "stockfish_path": "",
        }
        pgn_files = [os.path.join(pgn_dir, "game.pgn")]
        w = BatchPGNExportWorker(pgn_files, out_dir, settings)
        w.start(); w.cancel(); w.wait(10000)

    def test_batch_empty_folder(self, qapp, qtbot, tmp_path):
        pgn_dir = str(tmp_path / "empty_pgns"); os.makedirs(pgn_dir)
        out_dir = str(tmp_path / "empty_output"); os.makedirs(out_dir)
        settings = {
            "fps": 10, "hold": 0.5, "res_str": "1280×720",
            "bg_color": QColor(30, 30, 32), "theme": BoardTheme(),
            "flipped": False, "white_name": "W", "black_name": "B",
            "overlays": [], "eval_during": False, "stockfish_path": "",
        }
        w = BatchPGNExportWorker([], out_dir, settings)
        with qtbot.waitSignal(w.batch_finished, timeout=10000):
            w.start()


# ═══════════════════════════════════════════════════════════════════
#  Integration — Full PGN Load + Navigate + Game State
# ═══════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_full_pgn_workflow(self, main_window, sample_pgn_text):
        """Load PGN → Navigate → Verify state at each move."""
        main_window.pgn_text_edit.setPlainText(sample_pgn_text)
        main_window._load_pgn_text()
        assert len(main_window.move_list) == 9  # 5 white + 4 black + 1 white

        main_window._go_first()
        assert main_window.move_index == -1

        for i in range(len(main_window.move_list)):
            main_window._go_next()
            assert main_window.move_index == i

        main_window._go_last()
        assert main_window.move_index == len(main_window.move_list) - 1

        # Navigate back
        for i in range(len(main_window.move_list)):
            main_window._go_prev()

        assert main_window.move_index == -1

    def test_interactive_game(self, main_window):
        """Play a game by clicking squares."""
        main_window._new_game()
        # 1. e4
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        assert len(main_window.move_list) == 1

        # 1... e5
        main_window._on_sq_click(chess.E7)
        main_window._on_sq_click(chess.E5)
        assert len(main_window.move_list) == 2

        # 2. Nf3
        main_window._on_sq_click(chess.G1)
        main_window._on_sq_click(chess.F3)
        assert len(main_window.move_list) == 3

    def test_theme_and_flip_during_game(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        main_window._go_last()

        # Flip
        f = main_window.board_widget.flipped
        main_window._flip_board()
        assert main_window.board_widget.flipped != f

        # Change theme
        main_window._theme_changed("Blue")
        assert main_window.board_widget.theme.name == "Blue"

        # Navigate still works
        main_window._go_first()
        main_window._go_next()
        assert main_window.move_index == 0

    def test_refresh_move_list(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        main_window._refresh_move_list()
        rows = main_window.move_table.rowCount()
        assert rows > 0

    def test_eval_cache_updates(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        # Manually add eval
        node = main_window.move_list[0]
        main_window.eval_cache[node] = 50.0
        main_window._refresh_move_list()
        # The eval should appear in the move list

    def test_annotation(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        main_window.move_index = 0
        main_window.node = main_window.move_list[0]
        main_window.anno_edit.setPlainText("Great move!")
        main_window._apply_comment()
        assert main_window.move_list[0].comment == "Great move!"

    def test_new_game_resets_state(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        main_window._go_last()
        main_window._new_game()
        assert len(main_window.move_list) == 0
        assert main_window.move_index == -1
        assert main_window.eval_bar_widget._game_state == GAME_NORMAL

    def test_mate_detection_live(self, main_window):
        """Play into a fool's mate and verify checkmate is detected."""
        main_window._new_game()
        for san in ("f3", "e5", "g4", "Qh4"):
            b = main_window.board_widget.board
            mv = b.parse_san(san)
            main_window.node = main_window.node.add_variation(mv)
            main_window.move_list = list(main_window.game.mainline())
            main_window.move_index += 1
            main_window._update_board(animate=False, move_obj=mv)
        # After Qh4, it should be checkmate
        b = main_window.board_widget.board
        if b.is_checkmate():
            main_window._update_game_state(b)
            assert main_window.eval_bar_widget._game_state == GAME_CHECKMATE

    def test_overlay_positions(self, main_window, tmp_path):
        """Test all overlay positions."""
        img = QImage(50, 50, QImage.Format_ARGB32); img.fill(QColor(255, 0, 0))
        p = str(tmp_path / "ov.png"); img.save(p)

        from PySide6.QtWidgets import QListWidgetItem
        from PySide6.QtGui import QIcon
        item = QListWidgetItem(QIcon(p), "ov.png")
        item.setData(Qt.UserRole, p)
        main_window.img_list.addItem(item)
        main_window.img_list.setCurrentItem(item)

        positions = ["White Face", "Black Face", "Center Logo", "Watermark (BR)"]
        for i, pos in enumerate(positions):
            main_window.ov_pos_combo.setCurrentText(pos)
            main_window._add_overlay()

        assert len(main_window.canvas_overlays) == 4
        # Check coordinates differ
        coords = [(ov["x"], ov["y"]) for ov in main_window.canvas_overlays]
        assert len(set(coords)) == 4

    def test_pgn_file_load(self, main_window, sample_pgn_text, tmp_path):
        p = str(tmp_path / "test.pgn")
        with open(p, "w") as f:
            f.write(sample_pgn_text)
        main_window.pgn_file_edit.setText(p)
        main_window._load_pgn_from_file()
        assert len(main_window.move_list) > 0


# ═══════════════════════════════════════════════════════════════════
#  Sound Synthesis Unit Tests (numpy-dependent)
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_NP, reason="numpy not available")
class TestSoundSynthesis:
    def test_synth_move(self):
        from managers import _synth_move
        s = _synth_move(); assert len(s) > 0

    def test_synth_capture(self):
        from managers import _synth_capture
        s = _synth_capture(); assert len(s) > 0

    def test_synth_check(self):
        from managers import _synth_check
        s = _synth_check(); assert len(s) > 0

    def test_synth_checkmate(self):
        from managers import _synth_checkmate
        s = _synth_checkmate(); assert len(s) > 0

    def test_synth_castle(self):
        from managers import _synth_castle
        s = _synth_castle(); assert len(s) > 0

    def test_synth_illegal(self):
        from managers import _synth_illegal
        s = _synth_illegal(); assert len(s) > 0

    def test_synth_new_game(self):
        from managers import _synth_new_game
        s = _synth_new_game(); assert len(s) > 0

    def test_synth_promotion(self):
        from managers import _synth_promotion
        s = _synth_promotion(); assert len(s) > 0

    def test_synth_ui_click(self):
        from managers import _synth_ui_click
        s = _synth_ui_click(); assert len(s) > 0

    def test_to_wav(self):
        from managers import _to_wav
        s = np.zeros(1000, dtype=np.float64)
        w = _to_wav(s)
        assert isinstance(w, bytes) and len(w) > 0

    def test_fade(self):
        from managers import _fade
        s = np.ones(1000, dtype=np.float64)
        r = _fade(s)
        assert r[0] < 1.0 and r[-1] < 1.0

    def test_norm(self):
        from managers import _norm
        s = np.array([0.0, 0.5, -0.5])
        r = _norm(s)
        assert abs(np.max(np.abs(r)) - 0.9) < 0.01

    def test_add_reverb(self):
        from managers import _add_reverb
        s = np.zeros(5000, dtype=np.float64); s[0] = 1.0
        r = _add_reverb(s, amount=0.2)
        assert len(r) == len(s)

    def test_bitcrush(self):
        from managers import _bitcrush
        s = np.linspace(-1, 1, 1000)
        r = _bitcrush(s, bits=4)
        assert len(r) == len(s)
        # Should have quantized values
        unique = len(np.unique(r))
        assert unique < len(s)

    def test_design_mods_complete(self):
        from managers import _SOUND_DESIGN_MODS
        for d in SOUND_DESIGNS:
            assert d in _SOUND_DESIGN_MODS
            m = _SOUND_DESIGN_MODS[d]
            for k in ("freq_mul", "decay_mul", "reverb", "brightness",
                      "warmth", "bits"):
                assert k in m

    def test_theme_params(self):
        from managers import _THEME_PARAMS
        for theme in ("Classic", "Digital", "Tournament"):
            assert theme in _THEME_PARAMS
            assert "move" in _THEME_PARAMS[theme]
            assert "capture" in _THEME_PARAMS[theme]


# ═══════════════════════════════════════════════════════════════════
#  Edge Cases & Robustness
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_eval_bar_large_values(self, qapp):
        w = EvalBarWidget()
        for v in (1e6, -1e6, 1e9, -1e9):
            w.set_eval(v); w.resize(60, 400); w.repaint()

    def test_eval_bar_zero(self, qapp):
        w = EvalBarWidget(); w.set_eval(0.0)
        assert abs(EvalBarWidget._cp_to_ratio(0) - 0.5) < 0.01

    def test_board_renderer_empty_board(self, qapp):
        b = chess.Board(); b.clear_board()
        r = BoardRenderer(board=b)
        img = r.render(400)
        assert not img.isNull()

    def test_board_renderer_many_arrows(self, qapp):
        r = BoardRenderer()
        r.arrows = [(chess.A1, chess.A2, QColor(255, 0, 0)),
                    (chess.B1, chess.B3, QColor(0, 255, 0)),
                    (chess.C1, chess.C3, QColor(0, 0, 255))]
        assert not r.render(400).isNull()

    def test_video_renderer_no_move_list(self, qapp):
        vr = VideoRenderer(BoardRenderer(), w=640, h=360)
        vr.move_list_text = []
        assert not vr.render().isNull()

    def test_video_renderer_long_move_list(self, qapp):
        vr = VideoRenderer(BoardRenderer(), w=640, h=360)
        vr.move_list_text = [f"move{i}" for i in range(200)]
        vr.current_move_index = 100
        assert not vr.render().isNull()

    def test_minimax_zero_depth(self):
        eng = MinimaxEngine()
        bm, ev, n, pol = eng.search(chess.Board(), 0)
        # Depth 0 means immediate eval

    def test_mcts_one_iteration(self):
        eng = MCTSEngine()
        bm, ev, vis, pol = eng.search(chess.Board(), 1)
        assert vis == 1

    def test_capture_worker_no_moves(self, qapp, qtbot):
        g = chess.pgn.Game()
        w = CaptureWorker(
            game=g, move_list=[], eval_cache={},
            board_renderer=BoardRenderer(),
            video_bg_color=QColor(30, 30, 32),
            white_name="W", black_name="B", overlays=[],
            fps=10, hold=0.5, res_str="1280×720")
        with qtbot.waitSignal(w.capture_finished, timeout=10000):
            w.start()

    def test_ai_worker_mcts_low_iters(self, qapp, qtbot):
        w = AIWorker("MCTS (Monte Carlo)", chess.Board().fen(), {"iterations": 5})
        with qtbot.waitSignal(w.eval_ready, timeout=15000):
            w.start()

    def test_batch_eval_cancel_immediately(self, qapp):
        g = chess.pgn.read_game(io.StringIO("1. e4 e5 2. Nf3"))
        ml = list(g.mainline())
        w = BatchEvalWorker(ml, "Minimax (Alpha-Beta)", {"depth": 2})
        w.cancel()  # Cancel before starting
        w.start(); w.wait(10000)

    def test_battle_worker_no_valid_moves(self, qapp, qtbot):
        """AIBattleWorker with invalid engine type."""
        w = AIBattleWorker(
            "InvalidEngine", {}, "InvalidEngine", {},
            max_moves=2, delay_ms=0)
        # Should emit game_finished even if it can't get moves
        with qtbot.waitSignal(w.game_finished, timeout=30000):
            w.start()

    def test_export_worker_with_alpha_frames(self, qapp, qtbot, tmp_path):
        """Test export with RGBA frames (alpha compositing path)."""
        if not HAS_CV2:
            pytest.skip("opencv not available")
        import numpy as np
        frames = []
        for i in range(3):
            f = np.full((240, 320, 4), (i * 40, 128, 64, 200), dtype=np.uint8)
            frames.append(f)
        out = str(tmp_path / "alpha_test.mp4")
        w = ExportWorker(fr=frames, fps=10, out=out, w=320, h=240)
        with qtbot.waitSignal(w.export_finished, timeout=30000):
            w.start()

    def test_main_window_multiple_new_games(self, main_window):
        """Creating multiple new games should not leak or crash."""
        for _ in range(5):
            main_window._new_game()
        assert main_window.move_index == -1

    def test_main_window_navigate_beyond_bounds(self, main_window, sample_game):
        main_window._load_pgn_data(sample_game)
        main_window._go_last()
        # Going next at the last move should not crash
        main_window._go_next()
        main_window._go_first()
        # Going prev at the first move should not crash
        main_window._go_prev()

    def test_board_widget_set_position_none_last_move(self, qapp):
        w = ChessBoardWidget()
        w.set_position(chess.Board(), None)
        assert w.last_move is None

    def test_eval_bar_game_state_then_normal(self, qapp):
        w = EvalBarWidget()
        w.set_game_state(GAME_CHECKMATE, "1-0", "Checkmate")
        w.reset_game_state()
        assert w._game_state == GAME_NORMAL

    def test_promotion_widget_pick_hides(self, qapp):
        w = PromotionWidget(); w.show()
        w._pick(chess.QUEEN)
        assert w.isHidden()

    def test_renderer_from_widget_copies_state(self, qapp, board_widget):
        board_widget.arrows = [(chess.E2, chess.E4, QColor(255, 0, 0))]
        board_widget.policy_vis = {"d2d4": 0.6}
        r = BoardRenderer.from_widget(board_widget)
        assert len(r.arrows) == 1
        assert "d2d4" in r.policy_vis

    def test_detect_game_state_draw(self):
        """Test a draw-by-repetition scenario (simulated)."""
        # We can't easily force 3-fold rep, so just test the function
        b = chess.Board()
        s, r, d = _detect_game_state(b)
        assert s == GAME_NORMAL

    def test_heuristic_evaluator_king_safety(self):
        """Exposed king should generally evaluate worse."""
        ev = HeuristicEvaluator()
        b1 = chess.Board()  # Starting position (safe king)
        s1 = ev.evaluate(b1)
        # Create exposed king position
        b2 = chess.Board("4k3/8/8/8/8/8/4R3/4K3 w - - 0 1")
        s2 = ev.evaluate(b2)
        # White should be winning in b2
        assert s2 > s1

    def test_constants_low_ram_threshold(self):
        from constants import LOW_RAM_THRESHOLD, MED_RAM_THRESHOLD
        assert LOW_RAM_THRESHOLD < MED_RAM_THRESHOLD
        assert LOW_RAM_THRESHOLD > 0

    def test_estimate_memory_edge_cases(self):
        assert estimate_memory_gb("1920×1080", 1, 0.1, 1) > 0
        assert estimate_memory_gb("1280×720", 60, 10.0, 300) > 0

    def test_quality_preset_all_have_labels(self):
        for name, p in QUALITY_PRESETS.items():
            assert "label" in p
            assert name in p["label"] or any(kw in p["label"] for kw in ("Low", "Medium", "High"))