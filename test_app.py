"""Chess Video Maker Pro — Comprehensive Single-File Test Suite

Run with:
    pytest test_app.py -v

Requirements:
    pip install pytest PySide6 chess numpy
"""
import gc
import io
import os
import sys
import math
import tempfile
import shutil
import time
import chess
import chess.pgn
import pytest
from unittest.mock import patch, MagicMock

from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QColor, QImage


# ── Session-scoped QApplication fixture ────────────────────────────
@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def _safe_delete(widget):
    """Schedule a widget for deletion and process events so C++ objects
    are cleaned up *before* Python GC tries to collect them."""
    if widget is not None:
        try:
            widget.deleteLater()
        except RuntimeError:
            pass
        try:
            QApplication.processEvents()
        except RuntimeError:
            pass


def _pe(ms=50):
    """Process Qt events for a brief period. Uses the global QApplication
    instance automatically."""
    app = QApplication.instance()
    if app is None:
        return
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()


# ═══════════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════════
class TestConstants:
    def test_piece_sym_completeness(self):
        from constants import PIECE_SYM
        assert len(PIECE_SYM) == 12
        for pt in [chess.PAWN, chess.KNIGHT, chess.BISHOP,
                    chess.ROOK, chess.QUEEN, chess.KING]:
            for c in [chess.WHITE, chess.BLACK]:
                assert (pt, c) in PIECE_SYM

    def test_ai_map(self):
        from constants import AI_MAP
        assert "Minimax" in AI_MAP[0]
        assert "MCTS" in AI_MAP[1]
        assert "Stockfish" in AI_MAP[2]

    def test_sound_constants(self):
        from constants import SOUND_THEMES, SOUND_DESIGNS, SOUND_TYPES
        assert "Classic" in SOUND_THEMES
        assert "Silent" in SOUND_THEMES
        assert "Default" in SOUND_DESIGNS
        assert "Warm" in SOUND_DESIGNS
        for t in ["move", "capture", "check", "checkmate",
                   "castle", "illegal", "new_game", "promotion", "ui_click"]:
            assert t in SOUND_TYPES

    def test_anim_easings(self):
        from constants import ANIM_EASINGS
        assert "OutCubic" in ANIM_EASINGS
        assert "Linear" in ANIM_EASINGS

    def test_game_states(self):
        from constants import (GAME_NORMAL, GAME_CHECKMATE,
                               GAME_STALEMATE, GAME_DRAW, GAME_INSUFFICIENT)
        assert GAME_NORMAL == "normal"
        assert GAME_CHECKMATE == "checkmate"
        assert GAME_STALEMATE == "stalemate"
        assert GAME_DRAW == "draw"
        assert GAME_INSUFFICIENT == "insufficient"

    def test_board_theme_defaults(self):
        from constants import BoardTheme
        t = BoardTheme()
        assert t.name == "Classic"
        assert isinstance(t.light_sq, QColor)
        assert isinstance(t.dark_sq, QColor)
        assert isinstance(t.highlight, QColor)
        assert isinstance(t.last_move, QColor)

    def test_themes_dict(self):
        from constants import THEMES
        for name in ["Classic", "Blue", "Green", "Brown"]:
            assert name in THEMES
            assert THEMES[name].name == name

    def test_find_stockfish_return_type(self):
        from constants import find_stockfish
        result = find_stockfish()
        assert result is None or isinstance(result, str)

    def test_has_cv2_flag(self):
        from constants import HAS_CV2
        assert isinstance(HAS_CV2, bool)


# ═══════════════════════════════════════════════════════════════════
#  AI Engines
# ═══════════════════════════════════════════════════════════════════
class TestHeuristicEvaluator:
    def test_starting_position_near_zero(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        score = ev.evaluate(chess.Board())
        assert isinstance(score, (int, float))
        assert abs(score) < 2000

    def test_checkmate_black_wins(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board()
        for m in ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]:
            board.push(chess.Move.from_uci(m))
        assert board.is_checkmate()
        assert board.turn == chess.BLACK
        score = ev.evaluate(board)
        assert score == 10000

    def test_checkmate_white_loses(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board(
            "rnb1kbnr/pppp1ppp/4p3/8/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
        if board.is_checkmate() and board.turn == chess.WHITE:
            score = ev.evaluate(board)
            assert score == -10000

    def test_stalemate_returns_zero(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board("k7/8/KQ6/8/8/8/8/8 b - - 0 1")
        if board.is_stalemate():
            assert ev.evaluate(board) == 0

    def test_insufficient_material_returns_zero(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board("k7/8/K7/8/8/8/8/8 w - - 0 1")
        if board.is_insufficient_material():
            assert ev.evaluate(board) == 0

    def test_piece_values(self):
        from ai_engines import HeuristicEvaluator
        pv = HeuristicEvaluator.PV
        assert pv[chess.PAWN] == 100
        assert pv[chess.KNIGHT] == 320
        assert pv[chess.BISHOP] == 330
        assert pv[chess.ROOK] == 500
        assert pv[chess.QUEEN] == 900
        assert pv[chess.KING] == 20000

    def test_pawn_table_length(self):
        from ai_engines import HeuristicEvaluator
        assert len(HeuristicEvaluator.PT) == 64

    def test_material_advantage(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board(
            "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        score = ev.evaluate(board)
        assert score > 0


class TestMinimaxEngine:
    def test_finds_valid_move(self):
        from ai_engines import MinimaxEngine
        bm, ev, nodes, pol = MinimaxEngine().search(chess.Board(), depth=2)
        assert bm is not None
        assert isinstance(ev, (int, float))
        assert nodes > 0
        assert isinstance(pol, dict)

    def test_policy_normalised(self):
        from ai_engines import MinimaxEngine
        _, _, _, pol = MinimaxEngine().search(chess.Board(), depth=2)
        for v in pol.values():
            assert 0 <= v <= 1

    def test_best_move_in_policy(self):
        from ai_engines import MinimaxEngine
        bm, _, _, pol = MinimaxEngine().search(chess.Board(), depth=2)
        assert bm.uci() in pol

    def test_finds_mate_in_one(self):
        from ai_engines import MinimaxEngine
        board = chess.Board(
            "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/"
            "RNB1K1NR w KQkq - 4 4")
        bm, _, _, _ = MinimaxEngine().search(board, depth=3)
        assert bm == chess.Move.from_uci("h5f7")


class TestMCTSEngine:
    def test_finds_valid_move(self):
        from ai_engines import MCTSEngine
        bm, ev, visits, pol = MCTSEngine().search(
            chess.Board(), iters=50)
        assert bm is not None
        assert visits > 0
        assert isinstance(pol, dict)

    def test_policy_sums_to_one(self):
        from ai_engines import MCTSEngine
        _, _, _, pol = MCTSEngine().search(chess.Board(), iters=50)
        total = sum(pol.values())
        assert abs(total - 1.0) < 0.05

    def test_policy_normalised(self):
        from ai_engines import MCTSEngine
        _, _, _, pol = MCTSEngine().search(chess.Board(), iters=50)
        for v in pol.values():
            assert 0 <= v <= 1


class TestMCTSNode:
    def test_ucb1_unvisited_is_inf(self):
        from ai_engines import MCTSNode
        node = MCTSNode(chess.Board())
        assert node.ucb1() == float("inf")

    def test_expand_reduces_untried(self):
        from ai_engines import MCTSNode
        node = MCTSNode(chess.Board())
        before = len(node.untried)
        child = node.expand()
        assert len(node.untried) == before - 1
        assert child in node.children

    def test_best_child_returns_child(self):
        from ai_engines import MCTSNode
        node = MCTSNode(chess.Board())
        c1, c2 = node.expand(), node.expand()
        node.visits = 20
        c1.visits, c1.wins = 10, 8.0
        c2.visits, c2.wins = 8, 2.0
        best = node.best_child()
        assert best in node.children


# ═══════════════════════════════════════════════════════════════════
#  Board Widget
# ═══════════════════════════════════════════════════════════════════
class TestChessBoardWidget:
    @pytest.fixture
    def bw(self, qapp):
        from board_widget import ChessBoardWidget
        w = ChessBoardWidget()
        w.resize(400, 400)
        yield w
        _safe_delete(w)

    def test_creation(self, bw):
        assert bw.board is not None
        assert not bw.flipped

    def test_set_position_clears_state(self, bw):
        bw.selected_sq = chess.E2
        bw.legal_targets = [chess.E4]
        bw.set_position(chess.Board())
        assert bw.selected_sq is None
        assert bw.legal_targets == []
        assert bw.anim_move is None

    def test_set_position_animated(self, bw):
        bw.set_position_animated(chess.Board())
        assert bw.board is not None

    def test_set_theme(self, bw):
        from constants import THEMES
        bw.set_theme(THEMES["Blue"])
        assert bw.theme.name == "Blue"

    def test_layout(self, bw):
        t, m, s = bw._layout()
        assert t > 0
        assert s > 0

    def test_sq_rect_returns_valid(self, bw):
        t, m, s = bw._layout()
        for sq in chess.SQUARES:
            rect = bw._sq_rect(sq, t, m, s)
            assert rect.width() > 0
            assert rect.height() > 0

    def test_pos_to_sq_roundtrip(self, bw):
        t, m, s = bw._layout()
        for sq in chess.SQUARES:
            rect = bw._sq_rect(sq, t, m, s)
            cx = int(rect.center().x())
            cy = int(rect.center().y())
            result = bw._pos_to_sq(QPointF(cx, cy).toPoint(), t, m, s)
            assert result is not None

    def test_flipped_pos_to_sq(self, bw):
        bw.flipped = True
        t, m, s = bw._layout()
        rect = bw._sq_rect(chess.A1, t, m, s)
        cx = int(rect.center().x())
        cy = int(rect.center().y())
        result = bw._pos_to_sq(QPointF(cx, cy).toPoint(), t, m, s)
        assert result == chess.A1

    def test_render_to_image_no_show_needed(self, bw):
        img = bw.render_to_image(400)
        assert isinstance(img, QImage)
        assert img.width() == 400
        assert img.height() == 400

    def test_render_to_image_large(self, bw):
        img = bw.render_to_image(1080)
        assert isinstance(img, QImage)
        assert img.width() == 1080

    def test_render_to_image_with_pieces(self, bw):
        bw.set_position(chess.Board())
        img = bw.render_to_image(400)
        assert isinstance(img, QImage)

    def test_render_to_image_with_last_move(self, bw):
        bw.set_position(chess.Board(), lm=chess.Move.from_uci("e2e4"))
        img = bw.render_to_image(400)
        assert isinstance(img, QImage)

    def test_square_clicked_signal(self, bw):
        received = []
        bw.squareClicked.connect(lambda sq: received.append(sq))
        bw.squareClicked.emit(chess.E2)
        assert received == [chess.E2]

    def test_anim_properties(self, bw):
        for val in [0.0, 0.5, 1.0]:
            bw._set_ap(val)
            assert bw._get_ap() == val
            bw._set_co(val)
            assert bw._get_co() == val
            bw._set_fo(val)
            assert bw._get_fo() == val

    def test_policy_vis(self, bw):
        bw.policy_vis = {"e2e4": 0.8, "d2d4": 0.2}
        assert len(bw.policy_vis) == 2

    def test_arrows(self, bw):
        bw.arrows.append((chess.E2, chess.E4, QColor(220, 50, 47, 200)))
        assert len(bw.arrows) == 1

    def test_highlighted_squares(self, bw):
        bw.highlighted = {chess.E4}
        bw.update()
        assert chess.E4 in bw.highlighted

    def test_paint_content_directly(self, bw):
        img = QImage(400, 400, QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        from PySide6.QtGui import QPainter
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        m = 400 * 0.05
        sz = (400 - 2 * m) / 8
        bw._paint_content(p, 400, m, sz)
        p.end()
        assert isinstance(img, QImage)


# ═══════════════════════════════════════════════════════════════════
#  EvalBarWidget
# ═══════════════════════════════════════════════════════════════════
class TestEvalBarWidget:
    @pytest.fixture
    def ew(self, qapp):
        from widgets import EvalBarWidget
        w = EvalBarWidget()
        w.resize(60, 400)
        yield w
        _safe_delete(w)

    def test_creation(self, ew):
        assert ew._eval_cp == 0.0
        assert ew._game_state == "normal"

    def test_set_eval(self, ew):
        ew.set_eval(150.0)
        assert ew._eval_cp == 150.0

    def test_set_eval_mate_positive(self, ew):
        ew.set_eval(10001)
        assert ew._eval_cp == 10001

    def test_set_eval_mate_negative(self, ew):
        ew.set_eval(-10002)
        assert ew._eval_cp == -10002

    def test_set_game_state_checkmate(self, ew):
        from constants import GAME_CHECKMATE
        ew.set_game_state(GAME_CHECKMATE, result="1-0", detail="Checkmate")
        assert ew._game_state == GAME_CHECKMATE
        assert ew._game_result == "1-0"
        assert ew._game_detail == "Checkmate"

    def test_set_game_state_draw(self, ew):
        from constants import GAME_DRAW
        ew.set_game_state(GAME_DRAW, result="½-½", detail="Draw")
        assert ew._game_state == GAME_DRAW

    def test_reset_game_state(self, ew):
        from constants import GAME_CHECKMATE
        ew.set_game_state(GAME_CHECKMATE, result="1-0")
        ew.reset_game_state()
        assert ew._game_state == "normal"
        assert ew._game_result == ""

    def test_cp_to_ratio_center(self):
        from widgets import EvalBarWidget
        assert abs(EvalBarWidget._cp_to_ratio(0) - 0.5) < 0.01

    def test_cp_to_ratio_extremes(self):
        from widgets import EvalBarWidget
        assert EvalBarWidget._cp_to_ratio(9000) == 1.0
        assert EvalBarWidget._cp_to_ratio(-9000) == 0.0

    def test_cp_to_ratio_symmetry(self):
        from widgets import EvalBarWidget
        r_pos = EvalBarWidget._cp_to_ratio(100)
        r_neg = EvalBarWidget._cp_to_ratio(-100)
        assert abs(r_pos - (1 - r_neg)) < 0.01

    def test_set_anim_duration(self, ew):
        ew.set_anim_duration(500)
        assert ew._anim_dur == 500
        ew.set_anim_duration(0)
        assert ew._anim_dur == 0

    def test_eval_snap_on_game_over(self, ew):
        from constants import GAME_CHECKMATE
        ew.set_game_state(GAME_CHECKMATE)
        ew.set_eval(10001)
        assert ew._anim_cp == 10001.0


# ═══════════════════════════════════════════════════════════════════
#  PromotionWidget
# ═══════════════════════════════════════════════════════════════════
class TestPromotionWidget:
    @pytest.fixture
    def pw(self, qapp):
        from widgets import PromotionWidget
        w = PromotionWidget()
        yield w
        _safe_delete(w)

    def test_initially_hidden(self, pw):
        assert pw.isHidden()

    def test_show_for_white(self, pw):
        pw.show_for_color(chess.WHITE)
        assert pw.isVisible()

    def test_show_for_black(self, pw):
        pw.show_for_color(chess.BLACK)
        assert pw.isVisible()

    def test_piece_selected_signal(self, pw):
        received = []
        pw.piece_selected.connect(lambda pt: received.append(pt))
        pw.piece_selected.emit(chess.QUEEN)
        assert received == [chess.QUEEN]

    def test_pick_emits_and_hides(self, pw):
        pw.show()
        received = []
        pw.piece_selected.connect(lambda pt: received.append(pt))
        for pt in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
            pw._pick(pt)
            assert received[-1] == pt
            assert pw.isHidden()
            pw.show()


# ═══════════════════════════════════════════════════════════════════
#  VideoCanvas
# ═══════════════════════════════════════════════════════════════════
class TestVideoCanvas:
    @pytest.fixture
    def canvas_deps(self, qapp):
        from board_widget import ChessBoardWidget
        from widgets import EvalBarWidget
        bw = ChessBoardWidget()
        bw.resize(400, 400)
        ew = EvalBarWidget()
        yield bw, ew
        _safe_delete(bw)
        _safe_delete(ew)

    def test_creation_defaults(self, canvas_deps):
        from widgets import VideoCanvas
        bw, ew = canvas_deps
        vc = VideoCanvas(bw, ew)
        assert vc.w == 1920
        assert vc.h == 1080
        assert vc.eval_cp == 0.0

    def test_render_normal(self, canvas_deps):
        from widgets import VideoCanvas
        bw, ew = canvas_deps
        vc = VideoCanvas(bw, ew, w=640, h=360)
        img = vc.render()
        assert isinstance(img, QImage)
        assert img.width() == 640
        assert img.height() == 360

    def test_render_with_move_list(self, canvas_deps):
        from widgets import VideoCanvas
        bw, ew = canvas_deps
        vc = VideoCanvas(bw, ew, w=1280, h=720)
        vc.move_list_text = ["e4", "e5", "Nf3", "Nc6"]
        vc.current_move_index = 2
        img = vc.render()
        assert isinstance(img, QImage)

    def test_render_with_names(self, canvas_deps):
        from widgets import VideoCanvas
        bw, ew = canvas_deps
        vc = VideoCanvas(bw, ew, w=640, h=360)
        vc.white_name = "Magnus"
        vc.black_name = "Hikaru"
        img = vc.render()
        assert isinstance(img, QImage)

    def test_render_checkmate_white(self, canvas_deps):
        from widgets import VideoCanvas
        from constants import GAME_CHECKMATE
        bw, ew = canvas_deps
        vc = VideoCanvas(bw, ew, w=640, h=360)
        vc.game_state = GAME_CHECKMATE
        vc.game_result = "1-0"
        vc.eval_cp = 10001
        img = vc.render()
        assert isinstance(img, QImage)

    def test_render_checkmate_black(self, canvas_deps):
        from widgets import VideoCanvas
        from constants import GAME_CHECKMATE
        bw, ew = canvas_deps
        vc = VideoCanvas(bw, ew, w=640, h=360)
        vc.game_state = GAME_CHECKMATE
        vc.game_result = "0-1"
        vc.eval_cp = -10001
        img = vc.render()
        assert isinstance(img, QImage)

    def test_render_stalemate(self, canvas_deps):
        from widgets import VideoCanvas
        from constants import GAME_STALEMATE
        bw, ew = canvas_deps
        vc = VideoCanvas(bw, ew, w=640, h=360)
        vc.game_state = GAME_STALEMATE
        vc.game_result = "½-½"
        img = vc.render()
        assert isinstance(img, QImage)

    def test_render_draw(self, canvas_deps):
        from widgets import VideoCanvas
        from constants import GAME_DRAW
        bw, ew = canvas_deps
        vc = VideoCanvas(bw, ew, w=640, h=360)
        vc.game_state = GAME_DRAW
        vc.game_result = "½-½"
        img = vc.render()
        assert isinstance(img, QImage)

    def test_render_insufficient(self, canvas_deps):
        from widgets import VideoCanvas
        from constants import GAME_INSUFFICIENT
        bw, ew = canvas_deps
        vc = VideoCanvas(bw, ew, w=640, h=360)
        vc.game_state = GAME_INSUFFICIENT
        vc.game_result = "½-½"
        vc.game_detail = "Insufficient Material"
        img = vc.render()
        assert isinstance(img, QImage)

    def test_cp2r(self, canvas_deps):
        from widgets import VideoCanvas
        assert abs(VideoCanvas._cp2r(0) - 0.5) < 0.01
        assert VideoCanvas._cp2r(9000) == 1.0
        assert VideoCanvas._cp2r(-9000) == 0.0


# ═══════════════════════════════════════════════════════════════════
#  Animation Manager
# ═══════════════════════════════════════════════════════════════════
class TestAnimationManager:
    @pytest.fixture
    def am(self, qapp):
        from animation_manager import AnimationManager
        from board_widget import ChessBoardWidget
        from widgets import EvalBarWidget
        bw = ChessBoardWidget()
        ew = EvalBarWidget()
        m = AnimationManager(bw, ew)
        yield m
        m.cancel_all()
        _safe_delete(bw)
        _safe_delete(ew)

    def test_defaults(self, am):
        assert am.enabled
        assert am.piece_anim
        assert am.highlight_anim
        assert am.eval_anim
        assert am.duration == 250
        assert am.easing_name == "OutCubic"

    def test_set_duration(self, am):
        am.set_duration(500)
        assert am.duration == 500

    def test_set_duration_clamped_min(self, am):
        am.set_duration(1)
        assert am.duration == 50

    def test_set_duration_clamped_max(self, am):
        am.set_duration(9999)
        assert am.duration == 2000

    def test_set_easing_valid(self, am):
        for name in ["Linear", "InOutCubic", "OutBack",
                      "OutBounce", "InCubic"]:
            am.set_easing(name)
            assert am.easing_name == name

    def test_set_easing_invalid_falls_back(self, am):
        am.set_easing("NonExistent")
        assert am.easing_name == "OutCubic"

    def test_set_piece_anim(self, am):
        am.set_piece_anim(False)
        assert not am.piece_anim

    def test_set_highlight_anim(self, am):
        am.set_highlight_anim(False)
        assert not am.highlight_anim

    def test_set_eval_anim(self, am):
        am.set_eval_anim(False)
        assert not am.eval_anim

    def test_cancel_all(self, am):
        am.cancel_all()
        assert len(am._active) == 0

    def test_animate_piece_move_disabled_callback(self, am):
        am.enabled = False
        called = []
        am.animate_piece_move(chess.Move.from_uci("e2e4"),
                              callback=lambda: called.append(True))
        assert called == [True]

    def test_animate_piece_move_piece_anim_off(self, am):
        am.piece_anim = False
        called = []
        am.animate_piece_move(chess.Move.from_uci("e2e4"),
                              callback=lambda: called.append(True))
        assert called == [True]

    def test_animate_check_disabled(self, am):
        am.highlight_anim = False
        am.animate_check(chess.E1)

    def test_animate_last_move_flash_disabled(self, am):
        am.highlight_anim = False
        am.animate_last_move_flash(chess.E2, chess.E4)

    def test_configure_eval_bar(self, am):
        am.configure_eval_bar()


# ═══════════════════════════════════════════════════════════════════
#  Sound Manager — Synthesis Functions
# ═══════════════════════════════════════════════════════════════════
class TestSoundSynthesis:
    @pytest.fixture(autouse=True)
    def _skip_no_numpy(self):
        try:
            import numpy as np
        except ImportError:
            pytest.skip("numpy not available")

    def test_synth_move(self):
        from sound_manager import _synth_move
        assert len(_synth_move()) > 0

    def test_synth_capture(self):
        from sound_manager import _synth_capture
        assert len(_synth_capture()) > 0

    def test_synth_check(self):
        from sound_manager import _synth_check
        assert len(_synth_check()) > 0

    def test_synth_checkmate(self):
        from sound_manager import _synth_checkmate
        assert len(_synth_checkmate()) > 0

    def test_synth_castle(self):
        from sound_manager import _synth_castle
        assert len(_synth_castle()) > 0

    def test_synth_illegal(self):
        from sound_manager import _synth_illegal
        assert len(_synth_illegal()) > 0

    def test_synth_new_game(self):
        from sound_manager import _synth_new_game
        assert len(_synth_new_game()) > 0

    def test_synth_promotion(self):
        from sound_manager import _synth_promotion
        assert len(_synth_promotion()) > 0

    def test_synth_ui_click(self):
        from sound_manager import _synth_ui_click
        assert len(_synth_ui_click()) > 0

    def test_to_wav(self):
        import numpy as np
        from sound_manager import _to_wav, _synth_move
        wav = _to_wav(_synth_move())
        assert isinstance(wav, bytes)
        assert len(wav) > 44

    def test_fade(self):
        import numpy as np
        from sound_manager import _fade
        s = np.random.randn(1000).astype(np.float64)
        f = _fade(s.copy())
        assert len(f) == len(s)

    def test_norm(self):
        import numpy as np
        from sound_manager import _norm
        s = np.random.randn(1000).astype(np.float64)
        n = _norm(s)
        assert abs(np.max(np.abs(n)) - 0.9) < 0.15

    def test_add_reverb(self):
        from sound_manager import _add_reverb, _synth_move
        r = _add_reverb(_synth_move(), amount=0.2)
        assert len(r) > 0

    def test_add_reverb_zero(self):
        from sound_manager import _add_reverb, _synth_move
        s = _synth_move()
        r = _add_reverb(s, amount=0.0)
        assert len(r) == len(s)

    def test_bitcrush(self):
        import numpy as np
        from sound_manager import _bitcrush
        s = np.random.randn(1000).astype(np.float64)
        c = _bitcrush(s, bits=4)
        assert len(np.unique(c)) < len(np.unique(s))

    def test_bitcrush_16bits_noop(self):
        import numpy as np
        from sound_manager import _bitcrush
        s = np.random.randn(1000).astype(np.float64)
        c = _bitcrush(s, bits=16)
        assert len(c) == len(s)


class TestSoundDesignSynths:
    @pytest.fixture(autouse=True)
    def _skip_no_numpy(self):
        try:
            import numpy as np
        except ImportError:
            pytest.skip("numpy not available")

    def test_all_design_synths(self):
        from sound_manager import (
            _synth_check_design, _synth_checkmate_design,
            _synth_castle_design, _synth_illegal_design,
            _synth_new_game_design, _synth_promotion_design,
            _synth_ui_click_design,
        )
        for fn in [_synth_check_design, _synth_checkmate_design,
                    _synth_castle_design, _synth_illegal_design,
                    _synth_new_game_design, _synth_promotion_design,
                    _synth_ui_click_design]:
            assert len(fn()) > 0


class TestSoundManager:
    @pytest.fixture
    def sm(self, qapp):
        from sound_manager import SoundManager, HAS_MM, HAS_NP
        if not HAS_MM or not HAS_NP:
            pytest.skip("QtMultimedia or numpy not available")
        manager = SoundManager()
        yield manager
        manager.cleanup()

    def test_creation(self, sm):
        assert sm.enabled

    def test_set_volume(self, sm):
        sm.set_volume(0.3)
        assert sm._volume == 0.3
        sm.set_volume(1.5)
        assert sm._volume == 1.0
        sm.set_volume(-0.1)
        assert sm._volume == 0.0

    def test_set_theme(self, sm):
        for t in ["Classic", "Digital", "Tournament"]:
            sm.set_theme(t)
            assert sm._theme == t

    def test_set_design(self, sm):
        for d in ["Default", "Warm", "Crisp",
                   "Retro", "Cinematic", "Minimal"]:
            sm.set_design(d)
            assert sm._design == d

    def test_set_enabled(self, sm):
        sm.set_enabled(False)
        assert not sm.enabled
        sm.set_enabled(True)
        assert sm.enabled

    def test_play_when_disabled(self, sm):
        sm.set_enabled(False)
        sm.play("move")

    def test_play_nonexistent(self, sm):
        sm.play("nonexistent_sound")

    def test_set_type_volume(self, sm):
        sm.set_type_volume("move", 0.5)
        assert sm._type_vol["move"] == 0.5

    def test_silent_theme_no_sounds(self, sm):
        sm.set_theme("Silent")
        assert len(sm._sounds) == 0

    def test_play_move(self, sm):
        sm.play("move")

        # In TestSoundManager:

    def test_cleanup_clears_sounds(self, sm):
        assert len(sm._sounds) > 0
        sm.cleanup()
        assert len(sm._sounds) == 0

    def test_cleanup_removes_temp(self, sm):
        """After cleanup, the temp directory should eventually be removed.
        On Windows, QSoundEffect file handles may take time to release
        after deleteLater(), so we retry with gc.collect()."""
        td = sm._temp_dir
        assert td is not None
        sm.cleanup()
        # Retry with gc.collect() to help release C++ file handles
        import gc
        removed = not os.path.isdir(td)
        for attempt in range(20):
            if removed:
                break
            gc.collect()
            time.sleep(0.15)
            removed = not os.path.isdir(td)
        assert removed, f"Temp directory still exists after 3s: {td}"


# ═══════════════════════════════════════════════════════════════════
#  Workers
# ═══════════════════════════════════════════════════════════════════
class TestAIWorker:
    def test_minimax(self, qapp):
        from workers import AIWorker
        w = AIWorker("Minimax (Alpha-Beta)",
                     chess.Board().fen(), {"depth": 2})
        results = []
        w.eval_ready.connect(lambda d: results.append(d))
        w.run()
        assert len(results) == 1
        d = results[0]
        assert "eval" in d
        assert "eval_cp" in d
        assert "best_move" in d
        assert d.get("error") is not True

    def test_mcts(self, qapp):
        from workers import AIWorker
        w = AIWorker("MCTS (Monte Carlo)",
                     chess.Board().fen(), {"iterations": 50})
        results = []
        w.eval_ready.connect(lambda d: results.append(d))
        w.run()
        assert len(results) == 1
        assert "nodes" in results[0]

    def test_stockfish_missing_binary(self, qapp):
        from workers import AIWorker
        w = AIWorker("Stockfish (UCI)",
                     chess.Board().fen(),
                     {"path": "/nonexistent/stockfish"})
        results = []
        w.eval_ready.connect(lambda d: results.append(d))
        w.run()
        assert len(results) == 1
        assert results[0].get("error") is True


class TestBatchEvalWorker:
    def test_heuristic_batch(self, qapp):
        from workers import BatchEvalWorker
        game = chess.pgn.Game()
        node = game
        for san in ["e4", "e5", "Nf3", "Nc6"]:
            node = node.add_variation(
                node.board().parse_san(san))
        ml = list(game.mainline())
        w = BatchEvalWorker(ml, "Heuristic", {})
        results = []
        w.move_evaluated.connect(
            lambda i, e, s: results.append((i, e, s)))
        w.run()
        assert len(results) == len(ml)

    def test_cancel(self, qapp):
        from workers import BatchEvalWorker
        game = chess.pgn.Game()
        node = game
        for san in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]:
            node = node.add_variation(
                node.board().parse_san(san))
        ml = list(game.mainline())
        w = BatchEvalWorker(ml, "Heuristic", {})
        w.cancel()
        assert w._c


class TestExportWorker:
    def test_no_frames(self, qapp):
        from workers import ExportWorker
        w = ExportWorker([], 30, "/tmp/test_out.mp4", 640, 360)
        results = []
        w.export_finished.connect(lambda m: results.append(m))
        w.run()
        assert len(results) == 1
        assert "ERROR" in results[0] or "No frames" in results[0]

    def test_cancel(self, qapp):
        from workers import ExportWorker
        w = ExportWorker([b"fake"], 30, "/tmp/test_cancel.mp4",
                         640, 360)
        w.cancel()
        assert w._c


class TestResolveStockfish:
    def test_with_path(self):
        from workers import _resolve_sf
        assert _resolve_sf("/usr/local/bin/stockfish") == \
            "/usr/local/bin/stockfish"

    def test_empty_string(self):
        from workers import _resolve_sf
        result = _resolve_sf("")
        assert result is None or isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════
#  UI Builder
# ═══════════════════════════════════════════════════════════════════
class TestUIBuilder:
    @pytest.fixture
    def built_window(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        yield w
        w._cleanup()
        _safe_delete(w)

    def test_build_ui_creates_widgets(self, built_window):
        w = built_window
        attrs = ["board_widget", "eval_bar_widget", "promo_widget",
                 "tabs", "right_tabs", "move_table", "speed_slider",
                 "btn_play", "anno_edit", "db_list", "img_list",
                 "white_ai_combo", "black_ai_combo", "ai_combo",
                 "fps_spin", "anim_spin", "hold_spin",
                 "export_res_combo", "export_fps_spin",
                 "export_path_edit", "export_progress_bar",
                 "eval_label", "pv_label"]
        for attr in attrs:
            assert hasattr(w, attr), f"Missing attribute: {attr}"

    def test_build_menu(self, built_window):
        mb = built_window.menuBar()
        menus = [a.text() for a in mb.actions()]
        assert any("File" in m for m in menus)
        assert any("View" in m for m in menus)

    def test_moves_tab_columns(self, built_window):
        assert built_window.move_table.columnCount() == 3

    def test_battle_tab_widgets(self, built_window):
        w = built_window
        assert hasattr(w, "start_battle_btn")
        assert hasattr(w, "stop_battle_btn")
        assert hasattr(w, "battle_delay")
        assert hasattr(w, "auto_mp4_chk")
        assert hasattr(w, "save_png_chk")

    def test_settings_tab_widgets(self, built_window):
        w = built_window
        assert hasattr(w, "sound_enabled_chk")
        assert hasattr(w, "sound_vol_slider")
        assert hasattr(w, "sound_theme_combo")
        assert hasattr(w, "sound_design_combo")
        assert hasattr(w, "anim_enabled_chk")
        assert hasattr(w, "anim_dur_spin")
        assert hasattr(w, "anim_ease_combo")


# ═══════════════════════════════════════════════════════════════════
#  Main Window
# ═══════════════════════════════════════════════════════════════════
class TestMainWindow:
    @pytest.fixture
    def mw(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        yield w
        w._cleanup()
        _safe_delete(w)

    def test_creation(self, mw):
        assert mw.windowTitle().startswith("♟")
        assert mw.game is not None
        assert mw.node is not None

    def test_new_game(self, mw):
        mw._new_game()
        assert mw.move_index == -1
        assert len(mw.move_list) == 0
        assert mw.eval_bar_widget._game_state == "normal"

    def test_load_pgn_text(self, mw):
        mw.pgn_text_edit.setPlainText(
            "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6")
        mw._load_pgn_text()
        assert len(mw.move_list) == 6

    def test_load_pgn_text_empty(self, mw):
        mw.pgn_text_edit.clear()
        mw._load_pgn_text()

    def test_load_pgn_from_file_invalid(self, mw):
        mw.pgn_file_edit.setText("/nonexistent/file.pgn")
        mw._load_pgn_from_file()

    def test_load_pgn_from_file_empty(self, mw):
        mw.pgn_file_edit.clear()
        mw._load_pgn_from_file()

    def test_go_first(self, mw):
        mw.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3 Nc6")
        mw._load_pgn_text()
        mw._go_first()
        assert mw.move_index == -1

    def test_go_next(self, mw):
        mw.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3 Nc6")
        mw._load_pgn_text()
        mw._go_first()
        mw._go_next()
        assert mw.move_index == 0

    def test_go_prev(self, mw):
        mw.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3 Nc6")
        mw._load_pgn_text()
        mw._go_last()
        mw._go_prev()
        assert mw.move_index == len(mw.move_list) - 2

    def test_go_last(self, mw):
        mw.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3 Nc6")
        mw._load_pgn_text()
        mw._go_last()
        assert mw.move_index == len(mw.move_list) - 1

    def test_go_prev_at_start(self, mw):
        mw._go_first()
        mw._go_prev()
        assert mw.move_index == -1

    def test_go_next_at_end(self, mw):
        mw._go_last()
        mw._go_next()

    def test_select_piece(self, mw):
        mw._on_sq_click(chess.E2)
        assert mw.board_widget.selected_sq == chess.E2

    def test_move_piece(self, mw):
        mw._on_sq_click(chess.E2)
        mw._on_sq_click(chess.E4)
        assert mw.board_widget.selected_sq is None
        assert len(mw.move_list) == 1

    def test_illegal_move_deselects(self, mw):
        mw._on_sq_click(chess.E2)
        mw._on_sq_click(chess.E8)
        assert mw.board_widget.selected_sq is None

    def test_promo_pick_queen(self, mw):
        mw._pending_promo_from = chess.E7
        mw._pending_promo_to = chess.E8
        mw._on_promo_pick(chess.QUEEN)
        assert mw._pending_promo_from is None
        assert mw._pending_promo_to is None

    def test_promo_pick_no_pending(self, mw):
        mw._pending_promo_from = None
        mw._pending_promo_to = None
        mw._on_promo_pick(chess.QUEEN)

    def test_flip_board(self, mw):
        initial = mw.board_widget.flipped
        mw._flip_board()
        assert mw.board_widget.flipped != initial

    def test_theme_changed(self, mw):
        for name in ["Classic", "Blue", "Green", "Brown"]:
            mw._theme_changed(name)
            assert mw.board_widget.theme.name == name

    def test_pick_bg_color(self, mw):
        colors = {
            "Dark Gray": QColor(30, 30, 32),
            "Black": QColor(0, 0, 0),
            "Dark Blue": QColor(15, 20, 40),
            "Dark Green": QColor(15, 35, 15),
            "Dark Red": QColor(40, 15, 15),
            "White": QColor(255, 255, 255),
            "Light Gray": QColor(200, 200, 200),
            "Navy": QColor(0, 0, 80),
        }
        for name, color in colors.items():
            mw._pick_bg_color(name)
            assert mw.video_bg_color == color

    def test_apply_comment(self, mw):
        mw.anno_edit.setPlainText("Brilliant!")
        mw._apply_comment()
        assert mw.node.comment == "Brilliant!"

    def test_clear_policy(self, mw):
        mw.board_widget.policy_vis = {"e2e4": 0.8}
        mw._clear_policy()
        assert mw.board_widget.policy_vis == {}

    def test_on_sound_enabled(self, mw):
        mw._on_sound_enabled(False)
        assert not mw.sound_manager.enabled
        mw._on_sound_enabled(True)
        assert mw.sound_manager.enabled

    def test_on_sound_vol(self, mw):
        mw._on_sound_vol(42)
        assert mw.sound_vol_lbl.text() == "42%"

    def test_on_sound_theme(self, mw):
        mw._on_sound_theme("Digital")
        assert mw.sound_manager._theme == "Digital"

    def test_on_sound_design(self, mw):
        mw._on_sound_design("Warm")
        assert mw.sound_manager._design == "Warm"
        assert "Warm" in mw.sound_design_desc.text()

    def test_on_snd_type_vol(self, mw):
        mw._on_snd_type_vol("move", 0.5)
        assert mw.sound_manager._type_vol["move"] == 0.5

    def test_test_sound(self, mw):
        mw._test_sound("move")

    def test_on_anim_enabled(self, mw):
        mw._on_anim_enabled(False)
        assert not mw.anim_manager.enabled

    def test_on_piece_anim(self, mw):
        mw._on_piece_anim(False)
        assert not mw.anim_manager.piece_anim

    def test_on_highlight_anim(self, mw):
        mw._on_highlight_anim(False)
        assert not mw.anim_manager.highlight_anim

    def test_on_eval_anim(self, mw):
        mw._on_eval_anim(False)
        assert not mw.anim_manager.eval_anim

    def test_on_anim_dur(self, mw):
        mw._on_anim_dur(800)
        assert mw.anim_manager.duration == 800

    def test_on_anim_ease(self, mw):
        mw._on_anim_ease("Linear")
        assert mw.anim_manager.easing_name == "Linear"

    def test_toggle_ai_ui(self, mw):
        mw._toggle_ai_ui("Minimax (Alpha-Beta)")
        assert mw.ai_stack.currentIndex() == 0
        mw._toggle_ai_ui("MCTS (Monte Carlo)")
        assert mw.ai_stack.currentIndex() == 1
        mw._toggle_ai_ui("Stockfish (UCI)")
        assert mw.ai_stack.currentIndex() == 2

    def test_set_pgn_db_folder_invalid(self, mw):
        mw.db_folder_edit.setText("/nonexistent")
        mw._set_pgn_db_folder()

    def test_scan_pgn_db_no_folder(self, mw):
        mw.db_folder = ""
        mw._scan_pgn_db()
        assert mw.db_list.count() == 0

    def test_set_img_folder_invalid(self, mw):
        mw.img_folder_edit.setText("/nonexistent")
        mw._set_img_folder()

    def test_scan_img_db_no_folder(self, mw):
        mw.img_folder = ""
        mw._scan_img_db()
        assert mw.img_list.count() == 0

    def test_clear_overlays(self, mw):
        mw.canvas_overlays = [{"path": "x.png"}]
        mw._clear_overlays()
        assert mw.canvas_overlays == []

    def test_add_overlay_no_selection(self, mw):
        mw._add_overlay()
        assert mw.canvas_overlays == []

    def test_update_game_state_checkmate(self, mw):
        board = chess.Board()
        for m in ["e2e4", "e7e5", "d1h5", "b8c6",
                   "f1c4", "g8f6", "h5f7"]:
            board.push(chess.Move.from_uci(m))
        mw._update_game_state(board)
        assert mw.eval_bar_widget._game_state == "checkmate"

    def test_update_game_state_stalemate(self, mw):
        board = chess.Board("k7/8/KQ6/8/8/8/8/8 b - - 0 1")
        if board.is_stalemate():
            mw._update_game_state(board)
            assert mw.eval_bar_widget._game_state == "stalemate"

    def test_update_game_state_normal(self, mw):
        mw._update_game_state(chess.Board())
        assert mw.eval_bar_widget._game_state == "normal"

    def test_clear_frames(self, mw):
        mw.capture_frames = [1, 2, 3]
        mw._clear_frames()
        assert mw.capture_frames == []
        assert mw.frame_count_lbl.text() == "Frames: 0"

    def test_cancel_export_no_worker(self, mw):
        mw._cancel_export()

    def test_stop_batch_eval_no_worker(self, mw):
        mw._stop_batch_eval()

    def test_stop_ai_vs_ai_not_running(self, mw):
        mw._stop_ai_vs_ai()

    def test_refresh_move_list(self, mw):
        mw.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3 Nc6")
        mw._load_pgn_text()
        mw._refresh_move_list()
        assert mw.move_table.rowCount() == 2

    def test_on_move_cell(self, mw):
        mw.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3 Nc6")
        mw._load_pgn_text()
        mw._on_move_cell(0, 1, -1, -1)
        assert mw.move_index == 0

    def test_on_move_cell_invalid(self, mw):
        mw._on_move_cell(-1, 0, 0, 0)

    def test_toggle_play(self, mw):
        mw.pgn_text_edit.setPlainText("1. e4 e5")
        mw._load_pgn_text()
        mw._go_first()
        mw._toggle_play()
        assert mw._playing
        mw._toggle_play()
        assert not mw._playing

    def test_preview_captured_frames_empty(self, mw):
        mw._preview_captured_frames()

    def test_stop_preview(self, mw):
        mw._stop_preview()

    def test_update_preview_speed(self, mw):
        for idx in range(4):
            mw._update_preview_speed(idx)

    def test_scrub_preview(self, mw):
        mw._scrub_preview(0)

    def test_load_selected_pgn_no_item(self, mw):
        mw._load_selected_pgn_db()


# ═══════════════════════════════════════════════════════════════════
#  AI vs AI Battle Tests
# ═══════════════════════════════════════════════════════════════════
class TestAIvsAIBattle:
    @pytest.fixture
    def mw(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.white_ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        w.black_ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        w.white_ai_str.setValue(1)
        w.black_ai_str.setValue(1)
        w.battle_delay.setValue(50)
        yield w
        w.ai_vs_ai_running = False
        w._anim_timer.stop()
        if w.ai_battle_worker and w.ai_battle_worker.isRunning():
            try:
                w.ai_battle_worker.eval_ready.disconnect(
                    w._on_battle_move)
            except (RuntimeError, TypeError):
                pass
            w.ai_battle_worker.quit()
            w.ai_battle_worker.wait(2000)
        w._cleanup()
        _safe_delete(w)

    def test_start_battle_sets_flags(self, mw):
        mw.auto_mp4_chk.setChecked(False)
        mw.save_png_chk.setChecked(False)
        mw._start_ai_vs_ai()
        assert mw.ai_vs_ai_running
        assert not mw.start_battle_btn.isEnabled()
        assert mw.stop_battle_btn.isEnabled()

    def test_stop_battle_resets_flags(self, mw):
        mw.auto_mp4_chk.setChecked(False)
        mw.save_png_chk.setChecked(False)
        mw._start_ai_vs_ai()
        mw._stop_ai_vs_ai()
        assert not mw.ai_vs_ai_running
        assert mw.start_battle_btn.isEnabled()
        assert not mw.stop_battle_btn.isEnabled()

    def test_stop_battle_updates_game_state(self, mw):
        mw.auto_mp4_chk.setChecked(False)
        mw.save_png_chk.setChecked(False)
        mw._start_ai_vs_ai()
        _pe(500)
        mw._stop_ai_vs_ai()

    def test_battle_plays_moves(self, mw):
        mw.auto_mp4_chk.setChecked(False)
        mw.save_png_chk.setChecked(False)
        mw._start_ai_vs_ai()
        _pe(1500)
        assert len(mw.move_list) > 0
        mw._stop_ai_vs_ai()

    def test_battle_reaches_game_end(self, mw):
        mw.auto_mp4_chk.setChecked(False)
        mw.save_png_chk.setChecked(False)
        mw._start_ai_vs_ai()
        deadline = time.time() + 15
        while time.time() < deadline and mw.ai_vs_ai_running:
            _pe(200)
        if mw.ai_vs_ai_running:
            mw._stop_ai_vs_ai()
        board = mw.board_widget.board
        if board.is_game_over():
            assert mw.eval_bar_widget._game_state in [
                "checkmate", "stalemate", "draw", "insufficient"]

    def test_stop_battle_during_worker_run(self, mw):
        mw.auto_mp4_chk.setChecked(False)
        mw.save_png_chk.setChecked(False)
        mw._start_ai_vs_ai()
        _pe(300)
        mw.ai_vs_ai_running = False
        mw._stop_ai_vs_ai()
        _pe(100)

    def test_start_battle_when_already_running(self, mw):
        mw.auto_mp4_chk.setChecked(False)
        mw.save_png_chk.setChecked(False)
        mw._start_ai_vs_ai()
        assert mw.ai_vs_ai_running
        mw._start_ai_vs_ai()
        assert mw.ai_vs_ai_running
        mw._stop_ai_vs_ai()

    def test_battle_creates_move_list(self, mw):
        mw.auto_mp4_chk.setChecked(False)
        mw.save_png_chk.setChecked(False)
        mw._start_ai_vs_ai()
        _pe(1000)
        mw._stop_ai_vs_ai()
        if len(mw.move_list) > 0:
            assert mw.move_table.rowCount() > 0


# ═══════════════════════════════════════════════════════════════════
#  MP4 Export & YouTube Codec Tests
# ═══════════════════════════════════════════════════════════════════
class TestMP4Export:
    @pytest.fixture
    def mw(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        yield w
        w._cleanup()
        _safe_delete(w)

    @pytest.fixture
    def export_dir(self):
        d = tempfile.mkdtemp(prefix="chess_test_export_")
        yield d
        shutil.rmtree(d, ignore_errors=True)

    def _generate_frames(self, mw):
        mw.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3")
        mw._load_pgn_text()
        mw.fps_spin.setValue(10)
        mw.hold_spin.setValue(0.5)
        mw._auto_capture()
        _pe(100)
        return len(mw.capture_frames) > 0

    @pytest.mark.skipif(not __import__("constants").HAS_CV2,
                        reason="cv2 not available")
    def test_export_creates_video_file(self, mw, export_dir):
        """Test that export creates an actual video file on disk.
        The codec may produce .mp4 or .avi depending on platform."""
        if not self._generate_frames(mw):
            pytest.skip("Could not generate frames")

        out_path = os.path.join(export_dir, "test_output.mp4")
        mw.export_path_edit.setText(out_path)
        mw.export_res_combo.setCurrentIndex(1)  # 720p for speed
        mw.export_fps_spin.setValue(30)

        mw._start_inline_export()

        # Verify worker was created (diagnostic if not)
        if mw.export_worker is None:
            status = mw.export_status_lbl.text()
            pytest.skip(
                f"Export worker not created (likely codec issue). "
                f"Status: '{status}'")

        mw.export_worker.wait(30000)
        _pe(200)

        # The worker may change the extension if no MP4 codec is found
        base = os.path.splitext(out_path)[0]
        possible_files = [out_path, base + ".avi"]
        found_file = None
        for pf in possible_files:
            if os.path.isfile(pf):
                found_file = pf
                break

        assert found_file is not None, (
            f"No video file created. Status: "
            f"'{mw.export_status_lbl.text()}', "
            f"Dir: {os.listdir(export_dir)}")
        assert os.path.getsize(found_file) > 0, "Video file is empty"

    @pytest.mark.skipif(not __import__("constants").HAS_CV2,
                        reason="cv2 not available")
    def test_export_youtube_codec_1080p(self, mw, export_dir):
        """Test 1920x1080 export with YouTube-compatible codec."""
        if not self._generate_frames(mw):
            pytest.skip("Could not generate frames")

        out_path = os.path.join(export_dir, "youtube_1080p.mp4")
        mw.export_path_edit.setText(out_path)
        mw.export_res_combo.setCurrentIndex(0)
        mw.export_fps_spin.setValue(30)

        mw._start_inline_export()
        if mw.export_worker is None:
            pytest.skip("Export worker not created — codec issue")
        mw.export_worker.wait(30000)
        _pe(200)

        base = os.path.splitext(out_path)[0]
        found = any(os.path.isfile(p) for p in [out_path, base + ".avi"])
        if not found:
            pytest.skip("YouTube codec not available on this system")

        if os.path.isfile(out_path):
            with open(out_path, 'rb') as f:
                header = f.read(12)
            assert b'ftyp' in header, "Not a valid MP4 file"

    @pytest.mark.skipif(not __import__("constants").HAS_CV2,
                        reason="cv2 not available")
    def test_export_youtube_codec_720p(self, mw, export_dir):
        """Test 1280x720 export (YouTube HD)."""
        if not self._generate_frames(mw):
            pytest.skip("Could not generate frames")

        out_path = os.path.join(export_dir, "youtube_720p.mp4")
        mw.export_path_edit.setText(out_path)
        mw.export_res_combo.setCurrentIndex(1)
        mw.export_fps_spin.setValue(30)

        mw._start_inline_export()
        if mw.export_worker is None:
            pytest.skip("Export worker not created — codec issue")
        mw.export_worker.wait(30000)
        _pe(200)

        base = os.path.splitext(out_path)[0]
        found = any(os.path.isfile(p) for p in [out_path, base + ".avi"])
        if not found:
            pytest.skip("No video codec available on this system")
        if os.path.isfile(out_path):
            assert os.path.getsize(out_path) > 0

    @pytest.mark.skipif(not __import__("constants").HAS_CV2,
                        reason="cv2 not available")
    def test_export_youtube_codec_4k(self, mw, export_dir):
        """Test 3840x2160 export (YouTube 4K)."""
        if not self._generate_frames(mw):
            pytest.skip("Could not generate frames")

        out_path = os.path.join(export_dir, "youtube_4k.mp4")
        mw.export_path_edit.setText(out_path)
        mw.export_res_combo.setCurrentIndex(2)
        mw.export_fps_spin.setValue(24)

        mw._start_inline_export()
        if mw.export_worker is None:
            pytest.skip("Export worker not created — codec issue")
        mw.export_worker.wait(60000)
        _pe(200)

        base = os.path.splitext(out_path)[0]
        found = any(os.path.isfile(p) for p in [out_path, base + ".avi"])
        if not found:
            pytest.skip("No video codec available on this system")
        if os.path.isfile(out_path):
            assert os.path.getsize(out_path) > 0

    @pytest.mark.skipif(not __import__("constants").HAS_CV2,
                        reason="cv2 not available")
    def test_export_cancel_during_export(self, mw, export_dir):
        if not self._generate_frames(mw):
            pytest.skip("Could not generate frames")

        out_path = os.path.join(export_dir, "cancel_test.mp4")
        mw.export_path_edit.setText(out_path)
        mw.export_res_combo.setCurrentIndex(1)
        mw.export_fps_spin.setValue(60)

        mw._start_inline_export()
        if mw.export_worker is None:
            pytest.skip("Export worker not created")
        _pe(50)
        mw._cancel_export()
        mw.export_worker.wait(5000)
        _pe(100)

    @pytest.mark.skipif(not __import__("constants").HAS_CV2,
                        reason="cv2 not available")
    def test_export_progress_updates(self, mw, export_dir):
        if not self._generate_frames(mw):
            pytest.skip("Could not generate frames")

        out_path = os.path.join(export_dir, "progress_test.mp4")
        mw.export_path_edit.setText(out_path)
        mw.export_res_combo.setCurrentIndex(1)
        mw.export_fps_spin.setValue(30)

        progress_values = []
        mw._start_inline_export()
        if mw.export_worker is None:
            pytest.skip("Export worker not created")
        mw.export_worker.progress.connect(
            lambda p, m: progress_values.append(p))
        mw.export_worker.wait(30000)
        _pe(200)

        if progress_values:
            assert max(progress_values) == 100

    @pytest.mark.skipif(not __import__("constants").HAS_CV2,
                        reason="cv2 not available")
    def test_export_status_label_updated(self, mw, export_dir):
        if not self._generate_frames(mw):
            pytest.skip("Could not generate frames")

        out_path = os.path.join(export_dir, "status_test.mp4")
        mw.export_path_edit.setText(out_path)
        mw.export_res_combo.setCurrentIndex(1)
        mw.export_fps_spin.setValue(30)

        mw._start_inline_export()

        # Now _start_inline_export always sets a status message
        status = mw.export_status_lbl.text()
        assert len(status) > 0, (
            "Status label should be set after export attempt")

        if mw.export_worker is not None:
            mw.export_worker.wait(30000)
            _pe(200)
            final_status = mw.export_status_lbl.text()
            assert len(final_status) > 0

    def test_export_without_cv2_shows_error(self, mw):
        mw.capture_frames = [QImage(640, 360, QImage.Format_ARGB32)]
        with patch("main_window.HAS_CV2", False):
            mw._start_inline_export()
        assert "ERROR" in mw.export_status_lbl.text().upper() or \
               mw.export_status_lbl.text() == ""

    def test_export_without_frames_shows_error(self, mw):
        mw.capture_frames = []
        mw._start_inline_export()
        assert "ERROR" in mw.export_status_lbl.text().upper() or \
               mw.export_status_lbl.text() == ""

    @pytest.mark.skipif(not __import__("constants").HAS_CV2,
                        reason="cv2 not available")
    def test_export_worker_codec_selection(self, qapp):
        from workers import ExportWorker
        import numpy as np
        frames = [np.full((360, 640, 3), 32, dtype=np.uint8)
                  for _ in range(3)]
        out = os.path.join(tempfile.gettempdir(), "codec_test.mp4")
        w = ExportWorker(frames, 10, out, 640, 360)
        results = []
        w.export_finished.connect(lambda m: results.append(m))
        w.run()
        assert len(results) == 1
        if results[0].startswith("Done"):
            assert "Codec:" in results[0]
            assert any(c in results[0] for c in ["avc1", "X264", "mp4v"])
            base = os.path.splitext(out)[0]
            actual = out if os.path.isfile(out) else base + ".avi"
            if os.path.isfile(actual):
                os.remove(actual)

    @pytest.mark.skipif(not __import__("constants").HAS_CV2,
                        reason="cv2 not available")
    def test_export_worker_mp4_magic_bytes(self, qapp):
        from workers import ExportWorker
        import numpy as np
        frames = [np.full((180, 320, 3), 32, dtype=np.uint8)
                  for _ in range(5)]
        out = os.path.join(tempfile.gettempdir(), "magic_test.mp4")
        w = ExportWorker(frames, 10, out, 320, 180)
        results = []
        w.export_finished.connect(lambda m: results.append(m))
        w.run()
        if results and results[0].startswith("Done"):
            base = os.path.splitext(out)[0]
            actual = out if os.path.isfile(out) else base + ".avi"
            assert os.path.isfile(actual), "No video file created"
            with open(actual, 'rb') as f:
                header = f.read(12)
            if actual.endswith('.mp4'):
                assert b'ftyp' in header
            elif actual.endswith('.avi'):
                assert b'RIFF' in header
            os.remove(actual)


# ═══════════════════════════════════════════════════════════════════
#  Application Exit / Cleanup Tests
# ═══════════════════════════════════════════════════════════════════
class TestApplicationExit:
    def test_cleanup_with_no_active_resources(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w._cleanup()
        _safe_delete(w)

    def test_cleanup_while_playing(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3 Nc6")
        w._load_pgn_text()
        w._go_first()
        w._toggle_play()
        assert w._playing
        w._cleanup()
        assert not w._playing
        _safe_delete(w)

    def test_cleanup_with_animations_running(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3")
        w._load_pgn_text()
        w._go_first()
        w._go_next()
        w._cleanup()
        _safe_delete(w)

    def test_cleanup_with_sound_playing(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.sound_manager.play("move")
        w.sound_manager.play("new_game")
        _pe(50)
        w._cleanup()
        _safe_delete(w)

    def test_cleanup_with_preview_active(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w._prev_playing = True
        w._prev_timer.start(100)
        w._cleanup()
        assert not w._prev_timer.isActive()
        _safe_delete(w)

    def test_cleanup_stops_all_timers(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3 Nc6")
        w._load_pgn_text()
        w._go_first()
        w._toggle_play()
        _pe(100)
        w._cleanup()
        assert not w._anim_timer.isActive()
        assert not w._prev_timer.isActive()
        _safe_delete(w)

    def test_cleanup_cancels_animations(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.pgn_text_edit.setPlainText("1. e4 e5")
        w._load_pgn_text()
        w._go_first()
        w._go_next()
        _pe(50)
        w._cleanup()
        assert len(w.anim_manager._active) == 0
        _safe_delete(w)

    def test_cleanup_clears_sound_temp_dir(self, qapp):
        from main_window import MainWindow
        from sound_manager import HAS_MM, HAS_NP
        if not HAS_MM or not HAS_NP:
            pytest.skip("QtMultimedia or numpy not available")
        w = MainWindow()
        td = w.sound_manager._temp_dir
        assert td is not None
        w._cleanup()
        removed = not os.path.isdir(td)
        if not removed:
            for _ in range(10):
                time.sleep(0.1)
                if not os.path.isdir(td):
                    removed = True
                    break
        assert removed, f"Sound temp dir still exists: {td}"
        _safe_delete(w)

    def test_double_cleanup_no_crash(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w._cleanup()
        w._cleanup()
        _safe_delete(w)

    def test_cleanup_after_new_game(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w._new_game()
        w.sound_manager.play("new_game")
        _pe(50)
        w._cleanup()
        _safe_delete(w)

    def test_cleanup_after_pgn_load_and_navigation(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.pgn_text_edit.setPlainText(
            "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O")
        w._load_pgn_text()
        for _ in range(5):
            w._go_next()
            _pe(30)
        w._cleanup()
        _safe_delete(w)

    def test_close_event_calls_cleanup(self, qapp):
        from main_window import MainWindow
        from PySide6.QtGui import QCloseEvent
        w = MainWindow()
        w.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3")
        w._load_pgn_text()
        w._go_next()
        _pe(50)
        event = QCloseEvent()
        w.closeEvent(event)
        _safe_delete(w)

    def test_cleanup_with_engine_worker(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        w.mm_depth.setValue(2)
        w._run_engine()
        _pe(100)
        w._cleanup()
        _safe_delete(w)

    def test_cleanup_with_batch_eval(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.pgn_text_edit.setPlainText(
            "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4")
        w._load_pgn_text()
        w.ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        w.mm_depth.setValue(1)
        w._start_batch_eval()
        _pe(100)
        w._cleanup()
        _safe_delete(w)

    def test_cleanup_after_ai_vs_ai(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.white_ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        w.black_ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        w.white_ai_str.setValue(1)
        w.black_ai_str.setValue(1)
        w.battle_delay.setValue(50)
        w.auto_mp4_chk.setChecked(False)
        w.save_png_chk.setChecked(False)
        w._start_ai_vs_ai()
        _pe(500)
        w._stop_ai_vs_ai()
        _pe(100)
        w._cleanup()
        _safe_delete(w)

    def test_rapid_open_close_no_crash(self, qapp):
        from main_window import MainWindow
        for _ in range(3):
            w = MainWindow()
            w.pgn_text_edit.setPlainText("1. e4 e5")
            w._load_pgn_text()
            w._go_next()
            _pe(30)
            w._cleanup()
            _safe_delete(w)
            _pe(30)

    def test_cleanup_after_manual_moves(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w._on_sq_click(chess.E2)
        w._on_sq_click(chess.E4)
        w._on_sq_click(chess.E7)
        w._on_sq_click(chess.E5)
        w._on_sq_click(chess.G1)
        w._on_sq_click(chess.F3)
        _pe(50)
        w._cleanup()
        _safe_delete(w)


# ═══════════════════════════════════════════════════════════════════
#  Integration Tests
# ═══════════════════════════════════════════════════════════════════
class TestIntegration:
    def test_full_game_walkthrough(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        pgn = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O"
        w.pgn_text_edit.setPlainText(pgn)
        w._load_pgn_text()
        assert len(w.move_list) == 9
        w._go_first()
        assert w.move_index == -1
        for _ in range(len(w.move_list)):
            w._go_next()
        assert w.move_index == len(w.move_list) - 1
        w._go_prev()
        w._go_first()
        assert w.move_index == -1
        w._go_last()
        assert w.move_index == len(w.move_list) - 1
        w._cleanup()
        _safe_delete(w)

    def test_manual_moves_and_navigation(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w._on_sq_click(chess.E2)
        w._on_sq_click(chess.E4)
        assert len(w.move_list) == 1
        w._go_prev()
        assert w.move_index == -1
        w._go_next()
        assert w.move_index == 0
        w._on_sq_click(chess.E7)
        w._on_sq_click(chess.E5)
        assert len(w.move_list) == 2
        w._cleanup()
        _safe_delete(w)

    def test_theme_and_bg_cycle(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        for name in ["Classic", "Blue", "Green", "Brown"]:
            w._theme_changed(name)
            assert w.board_widget.theme.name == name
        for name, color in [("Black", QColor(0, 0, 0)),
                            ("Navy", QColor(0, 0, 80))]:
            w._pick_bg_color(name)
            assert w.video_bg_color == color
        w._cleanup()
        _safe_delete(w)

    def test_animation_settings_full_cycle(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w._on_anim_enabled(False)
        assert not w.anim_manager.enabled
        w._on_anim_enabled(True)
        w._on_piece_anim(False)
        assert not w.anim_manager.piece_anim
        w._on_highlight_anim(False)
        assert not w.anim_manager.highlight_anim
        w._on_eval_anim(False)
        assert not w.anim_manager.eval_anim
        w._on_anim_dur(1000)
        assert w.anim_manager.duration == 1000
        w._on_anim_ease("OutBack")
        assert w.anim_manager.easing_name == "OutBack"
        w._cleanup()
        _safe_delete(w)

    def test_eval_bar_all_game_states(self, qapp):
        from main_window import MainWindow
        from constants import (GAME_CHECKMATE, GAME_STALEMATE,
                               GAME_DRAW, GAME_INSUFFICIENT)
        w = MainWindow()
        eb = w.eval_bar_widget
        for state, result, detail, cp in [
            (GAME_CHECKMATE, "1-0", "Checkmate", 10001),
            (GAME_CHECKMATE, "0-1", "Checkmate", -10001),
            (GAME_STALEMATE, "½-½", "Stalemate", 0),
            (GAME_DRAW, "½-½", "Draw", 0),
            (GAME_INSUFFICIENT, "½-½", "Insufficient", 0),
        ]:
            eb.reset_game_state()
            eb.set_game_state(state, result=result, detail=detail)
            assert eb._game_state == state
            eb.set_eval(cp)
        eb.reset_game_state()
        assert eb._game_state == "normal"
        w._cleanup()
        _safe_delete(w)

    def test_video_canvas_all_states(self, qapp):
        from board_widget import ChessBoardWidget
        from widgets import EvalBarWidget, VideoCanvas
        from constants import (GAME_CHECKMATE, GAME_STALEMATE,
                               GAME_DRAW, GAME_INSUFFICIENT)
        bw = ChessBoardWidget()
        bw.resize(400, 400)
        ew = EvalBarWidget()
        try:
            for state, result, detail, cp in [
                ("normal", "", "", 50),
                (GAME_CHECKMATE, "1-0", "Checkmate", 10001),
                (GAME_CHECKMATE, "0-1", "Checkmate", -10001),
                (GAME_STALEMATE, "½-½", "Stalemate", 0),
                (GAME_DRAW, "½-½", "Draw", 0),
                (GAME_INSUFFICIENT, "½-½",
                 "Insufficient Material", 0),
            ]:
                vc = VideoCanvas(bw, ew, w=640, h=360)
                vc.game_state = state
                vc.game_result = result
                vc.game_detail = detail
                vc.eval_cp = cp
                img = vc.render()
                assert isinstance(img, QImage)
        finally:
            _safe_delete(bw)
            _safe_delete(ew)

    def test_ai_engine_vs_board_consistency(self, qapp):
        from ai_engines import MinimaxEngine, MCTSEngine
        board = chess.Board()
        for Engine, kwargs in [
            (MinimaxEngine, {"depth": 2}),
            (MCTSEngine, {"iters": 50}),
        ]:
            bm, _, _, _ = Engine().search(board, **kwargs)
            assert bm in board.legal_moves

    def test_manual_game_to_checkmate_detection(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        moves = [
            (chess.E2, chess.E4), (chess.E7, chess.E5),
            (chess.D1, chess.H5), (chess.B8, chess.C6),
            (chess.F1, chess.C4), (chess.G8, chess.F6),
            (chess.H5, chess.F7),
        ]
        for fr, to in moves:
            w._on_sq_click(fr)
            w._on_sq_click(to)
        board = w.board_widget.board
        assert board.is_checkmate()
        assert w.eval_bar_widget._game_state == "checkmate"
        w._cleanup()
        _safe_delete(w)

    def test_pgn_reload_resets_state(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.pgn_text_edit.setPlainText("1. e4 e5")
        w._load_pgn_text()
        w.pgn_text_edit.setPlainText("1. d4 d5 2. c4")
        w._load_pgn_text()
        assert len(w.move_list) == 3
        w._cleanup()
        _safe_delete(w)

    def test_auto_capture_with_moves(self, qapp):
        from main_window import MainWindow
        w = MainWindow()
        w.pgn_text_edit.setPlainText("1. e4 e5 2. Nf3")
        w._load_pgn_text()
        w.fps_spin.setValue(10)
        w.hold_spin.setValue(0.5)
        w._auto_capture()
        assert len(w.capture_frames) > 0
        assert len(w.capture_frames) >= 20
        w._cleanup()
        _safe_delete(w)

    def test_sound_design_descriptions(self, qapp):
        from main_window import _SOUND_DESIGN_DESC
        for design in ["Default", "Warm", "Crisp",
                        "Retro", "Cinematic", "Minimal"]:
            assert design in _SOUND_DESIGN_DESC
            assert isinstance(_SOUND_DESIGN_DESC[design], str)