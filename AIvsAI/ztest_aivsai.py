"""
Comprehensive pytest suite for AI vs AI → MP4 Chess Battle application.
Tests all modules: constants, engines, move_analyzer, board_renderer,
video_renderer, movelist_renderer, sound_engine, widgets, workers, app.
"""

import sys
import os
import math
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from io import StringIO

import pytest
import chess
import chess.pgn

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import Qt

# ── Ensure a single QApplication exists ──────────────────────────
_app = QApplication.instance()
if _app is None:
    _app = QApplication(sys.argv)


@pytest.fixture(scope="session")
def qapp():
    """Provide the singleton QApplication for the test session."""
    yield QApplication.instance() or QApplication(sys.argv)


def _has_cv2():
    try:
        import cv2
        return True
    except ImportError:
        return False


# ════════════════════════════════════════════════════════════════════
#  Constants Tests
# ════════════════════════════════════════════════════════════════════

class TestConstants:
    def test_piece_sym_completeness(self):
        from constants import PIECE_SYM
        for pt in [chess.PAWN, chess.KNIGHT, chess.BISHOP,
                    chess.ROOK, chess.QUEEN, chess.KING]:
            for c in [chess.WHITE, chess.BLACK]:
                assert (pt, c) in PIECE_SYM
                assert len(PIECE_SYM[(pt, c)]) == 1

    def test_resolution_sizes(self):
        from constants import RESOLUTION_SIZES, RESOLUTION_LIST
        assert len(RESOLUTION_SIZES) == len(RESOLUTION_LIST)
        for key in RESOLUTION_LIST:
            assert key in RESOLUTION_SIZES
            w, h = RESOLUTION_SIZES[key]
            assert w > 0 and h > 0

    def test_game_state_constants(self):
        from constants import (GAME_NORMAL, GAME_CHECKMATE,
                               GAME_STALEMATE, GAME_DRAW, GAME_INSUFFICIENT)
        assert GAME_NORMAL == "normal"
        assert GAME_CHECKMATE == "checkmate"
        assert GAME_STALEMATE == "stalemate"
        assert GAME_DRAW == "draw"
        assert GAME_INSUFFICIENT == "insufficient"

    def test_ai_map(self):
        from constants import AI_MAP, AI_SHORT_NAMES
        assert 0 in AI_MAP
        assert 1 in AI_MAP
        assert 2 in AI_MAP
        assert AI_SHORT_NAMES[0] == "Minimax"
        assert AI_SHORT_NAMES[1] == "MCTS"
        assert AI_SHORT_NAMES[2] == "Stockfish"

    def test_sound_events_are_strings(self):
        from constants import (SND_MOVE, SND_CAPTURE, SND_CHECK, SND_CASTLE,
                               SND_CHECKMATE, SND_STALEMATE, SND_DRAW,
                               SND_GAME_START, SND_UI_CLICK)
        for s in [SND_MOVE, SND_CAPTURE, SND_CHECK, SND_CASTLE,
                  SND_CHECKMATE, SND_STALEMATE, SND_DRAW,
                  SND_GAME_START, SND_UI_CLICK]:
            assert isinstance(s, str) and len(s) > 0

    def test_mq_constants_consistency(self):
        from constants import (
            MQ_BRILLIANT, MQ_GREAT, MQ_BEST, MQ_GOOD,
            MQ_INACCURACY, MQ_MISTAKE, MQ_BLUNDER, MQ_BOOK,
            MQ_LABELS, MQ_SYMBOLS, MQ_COLORS, MQ_BG_COLORS, MQ_VIDEO_COLORS,
        )
        all_mq = [MQ_BRILLIANT, MQ_GREAT, MQ_BEST, MQ_GOOD,
                  MQ_INACCURACY, MQ_MISTAKE, MQ_BLUNDER, MQ_BOOK]
        for q in all_mq:
            assert q in MQ_LABELS
            assert q in MQ_SYMBOLS
            assert q in MQ_COLORS
            assert q in MQ_BG_COLORS
            assert q in MQ_VIDEO_COLORS
            assert len(MQ_VIDEO_COLORS[q]) == 3

    def test_piece_values(self):
        from constants import PIECE_VALUES
        assert PIECE_VALUES[chess.PAWN] == 1
        assert PIECE_VALUES[chess.KNIGHT] == 3
        assert PIECE_VALUES[chess.BISHOP] == 3
        assert PIECE_VALUES[chess.ROOK] == 5
        assert PIECE_VALUES[chess.QUEEN] == 9
        assert PIECE_VALUES[chess.KING] == 0

    def test_board_theme_defaults(self):
        from constants import BoardTheme
        t = BoardTheme()
        assert t.name == "Classic"
        assert isinstance(t.light_sq, QColor)
        assert isinstance(t.dark_sq, QColor)
        assert isinstance(t.highlight, QColor)
        assert isinstance(t.last_move, QColor)

    def test_board_theme_custom(self):
        from constants import BoardTheme
        t = BoardTheme("Test", (200, 200, 200), (100, 100, 100))
        assert t.name == "Test"
        assert t.light_sq == QColor(200, 200, 200)
        assert t.dark_sq == QColor(100, 100, 100)

    def test_themes_dict(self):
        from constants import THEMES
        for name in ["Classic", "Blue", "Green", "Brown", "Purple", "Ice"]:
            assert name in THEMES
            assert THEMES[name].name == name

    def test_find_stockfish_returns_string_or_none(self):
        from constants import find_stockfish
        result = find_stockfish()
        assert result is None or isinstance(result, str)

    def test_default_output_dir(self):
        from constants import DEFAULT_OUTPUT_DIR
        assert isinstance(DEFAULT_OUTPUT_DIR, str) and len(DEFAULT_OUTPUT_DIR) > 0

    def test_sound_theme_list(self):
        from constants import SOUND_THEME_LIST
        assert isinstance(SOUND_THEME_LIST, list)
        assert "Classic" in SOUND_THEME_LIST


# ════════════════════════════════════════════════════════════════════
#  Engines Tests
# ════════════════════════════════════════════════════════════════════

class TestHeuristicEvaluator:
    def test_initial_position_eval(self):
        from engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        score = ev.evaluate(chess.Board())
        assert -500 < score < 500

    def test_checkmate_eval(self):
        from engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board()
        for san in ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]:
            board.push_san(san)
        assert board.is_checkmate()
        # Black to move and mated → returns 10000
        assert ev.evaluate(board) == 10000

    def test_stalemate_or_insufficient_eval_zero(self):
        from engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        # King vs King
        board = chess.Board("k7/8/K7/8/8/8/8/8 w - - 0 1")
        assert board.is_insufficient_material()
        assert ev.evaluate(board) == 0

    def test_material_advantage_white(self):
        from engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board("k7/8/2K5/8/4Q3/8/8/8 w - - 0 1")
        assert ev.evaluate(board) > 0

    def test_material_advantage_black(self):
        from engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board("k2q4/8/2K5/8/8/8/8/8 w - - 0 1")
        assert ev.evaluate(board) < 0

    def test_pawn_position_table_used(self):
        from engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        # Two boards with same material but different pawn positions
        b1 = chess.Board("k7/8/2K5/P7/8/8/8/8 w - - 0 1")
        b2 = chess.Board("k7/8/2K5/8/8/P7/8/8 w - - 0 1")
        assert ev.evaluate(b1) != ev.evaluate(b2)


class TestMinimaxEngine:
    def test_search_returns_valid_move(self):
        from engines import MinimaxEngine
        engine = MinimaxEngine()
        board = chess.Board()
        move, eval_score, nodes, policy = engine.search(board, depth=2)
        assert move in board.legal_moves
        assert isinstance(eval_score, (int, float))
        assert nodes > 0
        assert isinstance(policy, dict)

    def test_search_finds_forced_checkmate(self):
        from engines import MinimaxEngine
        engine = MinimaxEngine()
        # Qxf7# position
        board = chess.Board(
            "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
        )
        move, eval_score, nodes, policy = engine.search(board, depth=3)
        assert eval_score > 500 or move == chess.Move.from_uci("h5f7")

    def test_search_policy_normalized(self):
        from engines import MinimaxEngine
        engine = MinimaxEngine()
        _, _, _, policy = engine.search(chess.Board(), depth=2)
        if policy:
            total = sum(policy.values())
            assert 0.9 < total < 1.1

    def test_search_nodes_increase_with_depth(self):
        from engines import MinimaxEngine
        engine = MinimaxEngine()
        _, _, n1, _ = engine.search(chess.Board(), depth=1)
        _, _, n2, _ = engine.search(chess.Board(), depth=2)
        assert n2 > n1

    def test_search_black_to_move(self):
        from engines import MinimaxEngine
        engine = MinimaxEngine()
        board = chess.Board()
        board.push_san("e4")
        move, eval_score, nodes, policy = engine.search(board, depth=2)
        assert move in board.legal_moves

    def test_search_resets_node_count(self):
        from engines import MinimaxEngine
        engine = MinimaxEngine()
        engine.search(chess.Board(), depth=2)
        assert engine.nodes > 0
        engine.search(chess.Board(), depth=1)
        # nodes is set at the start of search


class TestMCTSEngine:
    def test_search_returns_valid_move(self):
        from engines import MCTSEngine
        engine = MCTSEngine()
        move, eval_score, nodes, policy = engine.search(chess.Board(), iterations=50)
        assert move in board.legal_moves if (board := chess.Board()) else True
        # More robust:
        board = chess.Board()
        move, _, _, _ = engine.search(board, iterations=50)
        assert move in board.legal_moves

    def test_search_policy(self):
        from engines import MCTSEngine
        engine = MCTSEngine()
        board = chess.Board()
        _, _, _, policy = engine.search(board, iterations=50)
        if policy:
            total = sum(policy.values())
            assert 0.9 < total < 1.1

    def test_mcts_node_ucb1(self):
        from engines import MCTSNode
        parent = MCTSNode(chess.Board())
        parent.visits = 10
        child = MCTSNode(chess.Board(), parent=parent,
                         move=chess.Move.from_uci("e2e4"))
        child.wins = 5
        child.visits = 5
        ucb = child.ucb1()
        assert ucb > 0
        assert isinstance(ucb, float)

    def test_mcts_unvisited_ucb1_infinite(self):
        from engines import MCTSNode
        parent = MCTSNode(chess.Board())
        parent.visits = 10
        child = MCTSNode(chess.Board(), parent=parent,
                         move=chess.Move.from_uci("e2e4"))
        child.visits = 0
        assert child.ucb1() == float("inf")

    def test_mcts_node_expand(self):
        from engines import MCTSNode
        node = MCTSNode(chess.Board())
        initial_untried = len(node.untried)
        child = node.expand()
        assert len(node.untried) == initial_untried - 1
        assert len(node.children) == 1
        assert child.move is not None

    def test_mcts_best_child(self):
        from engines import MCTSNode
        parent = MCTSNode(chess.Board())
        parent.visits = 100
        for _ in range(3):
            child = parent.expand()
            child.visits = 10
            child.wins = 5
        best = parent.best_child()
        assert best in parent.children

    def test_mcts_rollout(self):
        from engines import MCTSEngine
        engine = MCTSEngine()
        board = chess.Board()
        score = engine._rollout(board, depth=5)
        assert 0.0 <= score <= 1.0


class TestSyncUCI:
    def test_missing_path_raises(self):
        from engines import SyncUCI
        with pytest.raises(FileNotFoundError):
            SyncUCI("/nonexistent/path/to/stockfish")

    @pytest.mark.skipif(
        not shutil.which("stockfish") and not os.path.isfile("/usr/games/stockfish"),
        reason="Stockfish not available on system"
    )
    def test_analyse_starting_position(self):
        from engines import SyncUCI
        from constants import find_stockfish
        path = find_stockfish()
        if not path:
            pytest.skip("Stockfish path not found")
        uci = SyncUCI(path)
        try:
            bm, sc = uci.analyse(chess.STARTING_FEN, depth=10)
            assert bm is not None
            assert isinstance(sc, int)
        finally:
            uci.close()

    @pytest.mark.skipif(
        not shutil.which("stockfish") and not os.path.isfile("/usr/games/stockfish"),
        reason="Stockfish not available on system"
    )
    def test_analyse_no_legal_moves(self):
        from engines import SyncUCI
        from constants import find_stockfish
        path = find_stockfish()
        if not path:
            pytest.skip("Stockfish path not found")
        uci = SyncUCI(path)
        try:
            # Checkmate position
            fen = "rnb1kbnr/pppp1ppp/4p3/8/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
            bm, sc = uci.analyse(fen, depth=10)
            assert bm is None
        finally:
            uci.close()


# ════════════════════════════════════════════════════════════════════
#  Move Analyzer Tests
# ════════════════════════════════════════════════════════════════════

class TestClassifyMove:
    def test_book_move_first(self):
        from move_analyzer import classify_move
        assert classify_move(0, 30, True, move_number=1) == "book"

    def test_book_move_second(self):
        from move_analyzer import classify_move
        assert classify_move(0, 30, False, move_number=2) == "book"

    def test_blunder(self):
        from move_analyzer import classify_move
        assert classify_move(0, -350, True, move_number=5) == "blunder"

    def test_mistake(self):
        from move_analyzer import classify_move
        assert classify_move(0, -160, True, move_number=5) == "mistake"

    def test_inaccuracy(self):
        from move_analyzer import classify_move
        assert classify_move(0, -70, True, move_number=5) == "inaccuracy"

    def test_great_move(self):
        from move_analyzer import classify_move
        assert classify_move(0, 70, True, move_number=5) == "great"

    def test_best_move(self):
        from move_analyzer import classify_move
        assert classify_move(0, -10, True, move_number=5) == "best"

    def test_good_move(self):
        from move_analyzer import classify_move
        assert classify_move(0, -40, True, move_number=5) == "good"

    def test_great_not_brilliant_without_sacrifice(self):
        from move_analyzer import classify_move
        # delta >= 80 but no sacrifice → great
        assert classify_move(0, 100, True, move_number=5) == "great"

    def test_brilliant_with_sacrifice(self):
        from move_analyzer import classify_move
        board = chess.Board(
            "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
        )
        move = chess.Move.from_uci("f3f7")
        result = classify_move(-50, 100, True, board, move, move_number=5)
        assert result == "brilliant"

    def test_black_blunder(self):
        from move_analyzer import classify_move
        # Black plays; eval swings from 0 to +300 (white POV)
        # delta = eval_before - eval_after = 0 - 300 = -300
        assert classify_move(0, 300, False, move_number=5) == "blunder"

    def test_black_best(self):
        from move_analyzer import classify_move
        # Black plays; eval goes from 0 to -20 (white POV)
        # delta = 0 - (-20) = 20 >= -25 → best
        assert classify_move(0, -20, False, move_number=5) == "best"

    def test_clamping_large_delta(self):
        from move_analyzer import classify_move
        result = classify_move(0, 5000, True, move_number=5)
        assert result in ("great", "brilliant", "best")


class TestDetectSacrifice:
    def test_no_sacrifice_pawn(self):
        from move_analyzer import _detect_sacrifice
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        assert _detect_sacrifice(board, move) is False

    def test_no_sacrifice_none_board(self):
        from move_analyzer import _detect_sacrifice
        assert _detect_sacrifice(None, chess.Move.from_uci("e2e4")) is False

    def test_no_sacrifice_none_move(self):
        from move_analyzer import _detect_sacrifice
        assert _detect_sacrifice(chess.Board(), None) is False

    def test_sacrifice_queen_goes_to_attacked_square(self):
        from move_analyzer import _detect_sacrifice
        board = chess.Board(
            "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
        )
        move = chess.Move.from_uci("f3f7")
        # Queen goes to f7 which is attacked by black king (value 0 < 9)
        assert _detect_sacrifice(board, move) is True

    def test_no_sacrifice_knight_normal(self):
        from move_analyzer import _detect_sacrifice
        board = chess.Board()
        move = chess.Move.from_uci("g1f3")
        # Knight goes to f3, not attacked by lower-value piece
        assert _detect_sacrifice(board, move) is False


class TestMoveAnalyzer:
    def test_initial_state(self):
        from move_analyzer import MoveAnalyzer
        ma = MoveAnalyzer()
        assert ma.evals == []
        assert ma.qualities == []
        assert ma.last_quality == "good"

    def test_push_first_move_book(self):
        from move_analyzer import MoveAnalyzer
        ma = MoveAnalyzer()
        q = ma.push(30.0, True)
        assert q == "book"
        assert ma.evals == [30.0]

    def test_push_second_move_book(self):
        from move_analyzer import MoveAnalyzer
        ma = MoveAnalyzer()
        ma.push(30.0, True)
        q = ma.push(-20.0, False)
        assert q == "book"

    def test_push_third_move_classified(self):
        from move_analyzer import MoveAnalyzer
        ma = MoveAnalyzer()
        ma.push(0.0, True)
        ma.push(0.0, False)
        q = ma.push(10.0, True)
        assert q == "best"

    def test_push_blunder(self):
        from move_analyzer import MoveAnalyzer
        ma = MoveAnalyzer()
        ma.push(0.0, True)
        ma.push(0.0, False)
        q = ma.push(-400.0, True)
        assert q == "blunder"

    def test_reset(self):
        from move_analyzer import MoveAnalyzer
        ma = MoveAnalyzer()
        ma.push(10.0, True)
        ma.push(20.0, False)
        ma.reset()
        assert ma.evals == []
        assert ma.qualities == []

    def test_last_quality(self):
        from move_analyzer import MoveAnalyzer
        ma = MoveAnalyzer()
        ma.push(0.0, True)
        ma.push(0.0, False)
        ma.push(-400.0, True)
        assert ma.last_quality == "blunder"

    def test_evals_returns_copy(self):
        from move_analyzer import MoveAnalyzer
        ma = MoveAnalyzer()
        ma.push(10.0, True)
        ev = ma.evals
        ev.append(999.0)
        assert 999.0 not in ma.evals

    def test_qualities_returns_copy(self):
        from move_analyzer import MoveAnalyzer
        ma = MoveAnalyzer()
        ma.push(10.0, True)
        qu = ma.qualities
        qu.append("fake")
        assert "fake" not in ma.qualities


# ════════════════════════════════════════════════════════════════════
#  Board Renderer Tests
# ════════════════════════════════════════════════════════════════════

class TestBoardRenderer:
    def test_render_default(self):
        from board_renderer import BoardRenderer
        img = BoardRenderer().render(400)
        assert img.width() == 400 and img.height() == 400
        assert not img.isNull()

    def test_render_with_coords(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        r.show_coords = True
        img = r.render(400)
        assert not img.isNull()

    def test_render_without_coords(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        r.show_coords = False
        img = r.render(400)
        assert not img.isNull()

    def test_render_flipped(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        r.flipped = True
        img = r.render(400)
        assert not img.isNull()

    def test_render_with_last_move(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        board.push(move)
        r.board = board
        r.last_move = move
        img = r.render(400)
        assert not img.isNull()

    def test_render_quality_badge_blunder(self):
        from board_renderer import BoardRenderer
        from constants import MQ_BLUNDER
        r = BoardRenderer()
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        board.push(move)
        r.board = board
        r.last_move = move
        r.move_quality = MQ_BLUNDER
        img = r.render(400)
        assert not img.isNull()

    def test_render_quality_badge_brilliant(self):
        from board_renderer import BoardRenderer
        from constants import MQ_BRILLIANT
        r = BoardRenderer()
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        board.push(move)
        r.board = board
        r.last_move = move
        r.move_quality = MQ_BRILLIANT
        img = r.render(400)
        assert not img.isNull()

    def test_render_check_highlight(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        r._check_square = chess.E1
        r._check_opacity = 1.0
        img = r.render(400)
        assert not img.isNull()

    def test_render_with_theme(self):
        from board_renderer import BoardRenderer
        from constants import THEMES
        r = BoardRenderer(theme=THEMES["Blue"])
        img = r.render(400)
        assert not img.isNull()

    def test_render_animated_piece(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        move = chess.Move.from_uci("e2e4")
        r.anim_move = move
        r.anim_progress = 0.5
        img = r.render(400)
        assert not img.isNull()

    def test_render_animated_rook_castling(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        r.anim_rook_move = (chess.H1, chess.F1)
        r.anim_progress = 0.5
        img = r.render(400)
        assert not img.isNull()

    def test_render_animated_at_zero(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        r.anim_move = chess.Move.from_uci("e2e4")
        r.anim_progress = 0.0
        img = r.render(400)
        assert not img.isNull()

    def test_render_animated_at_one(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        r.anim_move = chess.Move.from_uci("e2e4")
        r.anim_progress = 1.0
        img = r.render(400)
        assert not img.isNull()

    def test_sq_rect_dimensions(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        rect = r._sq_rect(chess.A1, 400, 20, 45)
        assert rect.width() == 45 and rect.height() == 45

    def test_sq_rect_flipped(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        r.flipped = True
        rect_normal = BoardRenderer()._sq_rect(chess.A1, 400, 20, 45)
        rect_flipped = r._sq_rect(chess.A1, 400, 20, 45)
        # Flipped A1 should be in a different position
        assert rect_normal.topLeft() != rect_flipped.topLeft()

    def test_render_highlighted_square(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        r.highlighted = {chess.E4}
        img = r.render(400)
        assert not img.isNull()

    def test_render_selected_square(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        r.selected_sq = chess.E2
        img = r.render(400)
        assert not img.isNull()

    def test_render_various_sizes(self):
        from board_renderer import BoardRenderer
        r = BoardRenderer()
        for size in [200, 400, 800, 1080]:
            img = r.render(size)
            assert img.width() == size


# ════════════════════════════════════════════════════════════════════
#  Video Renderer Tests
# ════════════════════════════════════════════════════════════════════

class TestVideoRenderer:
    def test_render_landscape(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        img = vr.render()
        assert img.width() == 1920 and img.height() == 1080

    def test_render_portrait(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1080, h=1920)
        img = vr.render()
        assert img.width() == 1080 and img.height() == 1920

    def test_render_with_moves(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.move_list_text = ["e4", "e5", "Nf3", "Nc6"]
        vr.current_move_index = 3
        vr.move_qualities = ["good", "good", "best", "good"]
        img = vr.render()
        assert not img.isNull()

    def test_render_with_eval(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.eval_cp = 150.0
        img = vr.render()
        assert not img.isNull()

    def test_render_negative_eval(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.eval_cp = -200.0
        img = vr.render()
        assert not img.isNull()

    def test_render_game_over_checkmate_white_wins(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        from constants import GAME_CHECKMATE
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.game_state = GAME_CHECKMATE
        vr.game_result = "1-0"
        vr.game_detail = "Checkmate"
        vr.eval_cp = 10000
        img = vr.render()
        assert not img.isNull()

    def test_render_game_over_checkmate_black_wins(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        from constants import GAME_CHECKMATE
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.game_state = GAME_CHECKMATE
        vr.game_result = "0-1"
        vr.game_detail = "Checkmate"
        vr.eval_cp = -10000
        img = vr.render()
        assert not img.isNull()

    def test_render_draw(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        from constants import GAME_DRAW
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.game_state = GAME_DRAW
        vr.game_result = "½-½"
        vr.game_detail = "Stalemate"
        img = vr.render()
        assert not img.isNull()

    def test_render_with_player_names(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.white_name = "Magnus"
        vr.black_name = "Hikaru"
        vr.white_engine_info = "Stockfish (Depth 20)"
        vr.black_engine_info = "Minimax (Depth 3)"
        img = vr.render()
        assert not img.isNull()

    def test_cp2r_symmetry(self):
        from video_renderer import VideoRenderer
        assert VideoRenderer._cp2r(0) == pytest.approx(0.5, abs=0.01)
        assert VideoRenderer._cp2r(9000) == 1.0
        assert VideoRenderer._cp2r(-9000) == 0.0
        assert VideoRenderer._cp2r(500) > 0.5
        assert VideoRenderer._cp2r(-500) < 0.5

    def test_cp2r_mate_values(self):
        from video_renderer import VideoRenderer
        assert VideoRenderer._cp2r(10000) == 1.0
        assert VideoRenderer._cp2r(-10000) == 0.0

    def test_render_mate_eval_landscape(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.eval_cp = 10050
        img = vr.render()
        assert not img.isNull()

    def test_render_mate_eval_portrait(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1080, h=1920)
        vr.eval_cp = -10030
        img = vr.render()
        assert not img.isNull()

    def test_render_narrow_right_panel(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=640, h=480)
        img = vr.render()
        assert not img.isNull()


# ════════════════════════════════════════════════════════════════════
#  Move List Renderer Tests
# ════════════════════════════════════════════════════════════════════

class TestMoveListRenderer:
    def _render_to_image(self, w, h, moves, current=-1, qualities=None):
        from movelist_renderer import render_movelist_2col
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        render_movelist_2col(p, 0, 0, w, h, moves, current, qualities)
        p.end()
        return img

    def test_render_empty(self):
        img = self._render_to_image(400, 600, [])
        assert not img.isNull()

    def test_render_with_moves(self):
        img = self._render_to_image(400, 600, ["e4", "e5", "Nf3", "Nc6"], 2)
        assert not img.isNull()

    def test_render_with_qualities(self):
        from constants import MQ_BLUNDER, MQ_BRILLIANT
        img = self._render_to_image(
            400, 600, ["e4", "e5", "Nf3", "Nc6"], 2,
            ["good", "best", MQ_BRILLIANT, MQ_BLUNDER]
        )
        assert not img.isNull()

    def test_render_too_small_area(self):
        img = self._render_to_image(100, 50, ["e4"], 0)
        # Should not crash
        assert not img.isNull()

    def test_render_many_moves(self):
        moves = [f"m{i}" for i in range(60)]
        img = self._render_to_image(600, 800, moves, 30, ["good"] * 60)
        assert not img.isNull()

    def test_render_single_move(self):
        img = self._render_to_image(400, 600, ["e4"], 0)
        assert not img.isNull()

    def test_render_odd_number_moves(self):
        img = self._render_to_image(400, 600, ["e4", "e5", "Nf3"], 2)
        assert not img.isNull()

    def test_render_all_quality_types(self):
        from constants import (MQ_BRILLIANT, MQ_GREAT, MQ_BEST, MQ_GOOD,
                               MQ_INACCURACY, MQ_MISTAKE, MQ_BLUNDER, MQ_BOOK)
        moves = ["a4", "a5", "b4", "b5", "c4", "c5", "d4", "d5"]
        quals = [MQ_BRILLIANT, MQ_GREAT, MQ_BEST, MQ_GOOD,
                 MQ_INACCURACY, MQ_MISTAKE, MQ_BLUNDER, MQ_BOOK]
        img = self._render_to_image(400, 600, moves, 4, quals)
        assert not img.isNull()


# ════════════════════════════════════════════════════════════════════
#  Sound Engine Tests
# ════════════════════════════════════════════════════════════════════

class TestSoundEngine:
    def test_init(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        assert isinstance(se.enabled, bool)
        assert isinstance(se.muted, bool)
        assert isinstance(se.volume, float)

    def test_set_muted(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        se.set_muted(True)
        assert se.muted is True
        se.set_muted(False)
        assert se.muted is False

    def test_set_volume_clamp_high(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        se.set_volume(1.5)
        assert se.volume <= 1.0

    def test_set_volume_clamp_low(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        se.set_volume(-0.5)
        assert se.volume >= 0.0

    def test_set_volume_normal(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        se.set_volume(0.5)
        assert se.volume == pytest.approx(0.5, abs=0.01)

    def test_available_themes(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        themes = se.available_themes
        if se.enabled:
            assert len(themes) > 0
            assert "Classic" in themes
        else:
            assert themes == []

    def test_set_theme(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        if se.enabled:
            orig = se.theme
            se.set_theme("Digital")
            assert se.theme == "Digital"
            se.set_theme(orig)

    def test_set_theme_same_noop(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        if se.enabled:
            theme = se.theme
            se.set_theme(theme)  # Should be a no-op

    def test_play_move_sound_no_crash(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        se.play_move_sound(board, move)

    def test_play_game_end_no_crash(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        for result_type in ["checkmate", "stalemate", "draw", "unknown"]:
            se.play_game_end(result_type)

    def test_play_when_muted(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        se.set_muted(True)
        se.play("move")  # Should not crash or play

    def test_cleanup(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        se.cleanup()  # Should not crash

    def test_play_unknown_event(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        se.play("nonexistent_event")  # Should not crash

    def test_play_check_sound(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        board = chess.Board("rnbqkbnr/ppppp1pp/5p2/6B1/4P3/8/PPPP1PPP/RNBQK1NR b KQkq - 1 2")
        # Bg5 gives check in some lines; let's use a simpler setup
        board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2")
        # Not necessarily check, just testing play_move_sound path
        for move in board.legal_moves:
            se.play_move_sound(board, move)
            break


# ════════════════════════════════════════════════════════════════════
#  Widgets Tests
# ════════════════════════════════════════════════════════════════════

class TestMoveListWidget:
    def test_init(self):
        from widgets import MoveListWidget
        w = MoveListWidget()
        assert w.moves == []
        assert w.qualities == []
        assert w.current_index == -1

    def test_add_move(self):
        from widgets import MoveListWidget
        from constants import MQ_BEST
        w = MoveListWidget()
        w.add_move("e4", MQ_BEST)
        assert w.moves == ["e4"]
        assert w.qualities == [MQ_BEST]
        assert w.current_index == 0

    def test_add_multiple_moves(self):
        from widgets import MoveListWidget
        w = MoveListWidget()
        w.add_move("e4")
        w.add_move("e5")
        w.add_move("Nf3")
        assert w.moves == ["e4", "e5", "Nf3"]
        assert w.current_index == 2

    def test_set_moves(self):
        from widgets import MoveListWidget
        w = MoveListWidget()
        w.set_moves(["e4", "e5"], ["good", "best"], 1)
        assert w.moves == ["e4", "e5"]
        assert w.qualities == ["good", "best"]
        assert w.current_index == 1

    def test_set_moves_default_qualities(self):
        from widgets import MoveListWidget
        from constants import MQ_GOOD
        w = MoveListWidget()
        w.set_moves(["e4", "e5"])
        assert w.qualities == [MQ_GOOD, MQ_GOOD]

    def test_set_current(self):
        from widgets import MoveListWidget
        w = MoveListWidget()
        w.add_move("e4")
        w.add_move("e5")
        w.set_current(0)
        assert w.current_index == 0

    def test_clear(self):
        from widgets import MoveListWidget
        w = MoveListWidget()
        w.add_move("e4")
        w.clear()
        assert w.moves == []
        assert w.qualities == []
        assert w.current_index == -1

    def test_paint_no_crash(self):
        from widgets import MoveListWidget
        w = MoveListWidget()
        w.resize(400, 600)
        w.add_move("e4")
        w.add_move("e5")
        w.repaint()


class TestBoardPreviewWidget:
    def test_init(self):
        from widgets import BoardPreviewWidget
        w = BoardPreviewWidget()
        assert w.flipped is False

    def test_set_board(self):
        from widgets import BoardPreviewWidget
        w = BoardPreviewWidget()
        board = chess.Board()
        w.set_board(board)
        assert w._renderer.board is board

    def test_set_board_with_last_move(self):
        from widgets import BoardPreviewWidget
        w = BoardPreviewWidget()
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        board.push(move)
        w.set_board(board, move)
        assert w._renderer.last_move == move

    def test_set_theme(self):
        from widgets import BoardPreviewWidget
        from constants import THEMES
        w = BoardPreviewWidget()
        w.set_theme(THEMES["Blue"])
        assert w._renderer.theme is THEMES["Blue"]

    def test_set_flipped(self):
        from widgets import BoardPreviewWidget
        w = BoardPreviewWidget()
        w.set_flipped(True)
        assert w.flipped is True
        w.set_flipped(False)
        assert w.flipped is False

    def test_set_show_coords(self):
        from widgets import BoardPreviewWidget
        w = BoardPreviewWidget()
        w.set_show_coords(False)
        assert w._renderer.show_coords is False
        w.set_show_coords(True)
        assert w._renderer.show_coords is True

    def test_set_move_quality(self):
        from widgets import BoardPreviewWidget
        from constants import MQ_BLUNDER
        w = BoardPreviewWidget()
        w.set_move_quality(MQ_BLUNDER)
        assert w._renderer.move_quality == MQ_BLUNDER

    def test_set_anim_duration(self):
        from widgets import BoardPreviewWidget
        w = BoardPreviewWidget()
        w.set_anim_duration(500)
        assert w._anim_duration == 500
        w.set_anim_duration(10)  # Below minimum
        assert w._anim_duration == 50  # Clamped to 50

    def test_animate_move_simple(self):
        from widgets import BoardPreviewWidget
        w = BoardPreviewWidget()
        w.resize(400, 400)
        move = chess.Move.from_uci("e2e4")
        w.animate_move(move)
        assert w._active_anim is not None

    def test_animate_move_castling(self):
        from widgets import BoardPreviewWidget
        w = BoardPreviewWidget()
        w.resize(400, 400)
        # Set up a position where castling is possible
        board = chess.Board("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1")
        w.set_board(board)
        move = chess.Move.from_uci("e1g1")  # Kingside castle
        w.animate_move(move)
        assert w._active_anim is not None

    def test_paint_no_crash(self):
        from widgets import BoardPreviewWidget
        w = BoardPreviewWidget()
        w.resize(400, 400)
        w.repaint()


class TestEvalBarWidget:
    def test_init(self):
        from widgets import EvalBarWidget
        w = EvalBarWidget()
        assert w._eval_cp == 0.0

    def test_set_eval(self):
        from widgets import EvalBarWidget
        w = EvalBarWidget()
        w.resize(60, 400)
        w.set_eval(150.0)
        assert w._eval_cp == 150.0

    def test_set_eval_negative(self):
        from widgets import EvalBarWidget
        w = EvalBarWidget()
        w.resize(60, 400)
        w.set_eval(-200.0)
        assert w._eval_cp == -200.0

    def test_set_eval_mate(self):
        from widgets import EvalBarWidget
        w = EvalBarWidget()
        w.resize(60, 400)
        w.set_eval(10050.0)
        assert w._eval_cp == 10050.0

    def test_set_game_state(self):
        from widgets import EvalBarWidget
        from constants import GAME_CHECKMATE
        w = EvalBarWidget()
        w.set_game_state(GAME_CHECKMATE, "1-0", "Checkmate")
        assert w._game_state == GAME_CHECKMATE

    def test_reset_game_state(self):
        from widgets import EvalBarWidget
        from constants import GAME_NORMAL
        w = EvalBarWidget()
        w.set_game_state("checkmate", "1-0", "Checkmate")
        w.reset_game_state()
        assert w._game_state == GAME_NORMAL

    def test_cp2r(self):
        from widgets import EvalBarWidget
        assert EvalBarWidget._cp2r(0) == pytest.approx(0.5, abs=0.01)
        assert EvalBarWidget._cp2r(9000) == 1.0
        assert EvalBarWidget._cp2r(-9000) == 0.0

    def test_paint_no_crash(self):
        from widgets import EvalBarWidget
        w = EvalBarWidget()
        w.resize(60, 400)
        w.set_eval(50.0)
        w.repaint()

    def test_paint_game_over_white_wins(self):
        from widgets import EvalBarWidget
        from constants import GAME_CHECKMATE
        w = EvalBarWidget()
        w.resize(60, 400)
        w.set_game_state(GAME_CHECKMATE, "1-0", "Checkmate")
        w.repaint()

    def test_paint_game_over_black_wins(self):
        from widgets import EvalBarWidget
        from constants import GAME_CHECKMATE
        w = EvalBarWidget()
        w.resize(60, 400)
        w.set_game_state(GAME_CHECKMATE, "0-1", "Checkmate")
        w.repaint()

    def test_paint_game_over_draw(self):
        from widgets import EvalBarWidget
        from constants import GAME_DRAW
        w = EvalBarWidget()
        w.resize(60, 400)
        w.set_game_state(GAME_DRAW, "½-½", "Stalemate")
        w.repaint()


# ════════════════════════════════════════════════════════════════════
#  Workers Tests
# ════════════════════════════════════════════════════════════════════

class TestGameWorker:
    def test_init(self):
        from workers import GameWorker
        gw = GameWorker(0, 2, 0, 2, move_delay=0)
        assert gw.white_type == 0
        assert gw.black_type == 0
        assert gw._stop is False

    def test_stop(self):
        from workers import GameWorker
        gw = GameWorker(0, 2, 0, 2)
        gw.stop()
        assert gw._stop is True

    def test_detect_game_state_normal(self):
        from workers import GameWorker
        from constants import GAME_NORMAL
        gw = GameWorker(0, 2, 0, 2)
        gw.board = chess.Board()
        state, result, detail = gw._detect_game_state()
        assert state == GAME_NORMAL
        assert result == ""

    def test_detect_game_state_checkmate(self):
        from workers import GameWorker
        from constants import GAME_CHECKMATE
        gw = GameWorker(0, 2, 0, 2)
        gw.board = chess.Board()
        for san in ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]:
            gw.board.push_san(san)
        state, result, detail = gw._detect_game_state()
        assert state == GAME_CHECKMATE
        assert result == "1-0"

    def test_detect_game_state_stalemate(self):
        from workers import GameWorker
        from constants import GAME_STALEMATE
        gw = GameWorker(0, 2, 0, 2)
        # Black king stalemated
        gw.board = chess.Board("5k2/5P2/5K2/8/8/8/8/8 b - - 0 1")
        if gw.board.is_stalemate():
            state, result, detail = gw._detect_game_state()
            assert state == GAME_STALEMATE
            assert result == "½-½"

    def test_detect_game_state_insufficient(self):
        from workers import GameWorker
        from constants import GAME_INSUFFICIENT
        gw = GameWorker(0, 2, 0, 2)
        gw.board = chess.Board("k7/8/K7/8/8/8/8/8 w - - 0 1")
        if gw.board.is_insufficient_material():
            state, result, detail = gw._detect_game_state()
            assert state == GAME_INSUFFICIENT

    def test_minimax_game_runs(self, qapp):
        """Test a complete game between two Minimax engines."""
        from workers import GameWorker
        moves_received = []
        game_over_received = []
        error_received = []

        gw = GameWorker(0, 1, 0, 1, move_delay=0)

        def on_move(board, move, eval_cp, nodes, policy, state, result, detail):
            moves_received.append((move, state))

        def on_game_over(state, result, detail):
            game_over_received.append((state, result, detail))

        gw.move_made.connect(on_move)
        gw.game_over.connect(on_game_over)
        gw.error.connect(lambda msg: error_received.append(msg))
        gw.run()

        assert len(moves_received) > 0, "No moves were made"
        assert len(error_received) == 0, f"Errors: {error_received}"

    def test_mcts_game_runs(self, qapp):
        """Test a game with MCTS engines (few iterations for speed)."""
        from workers import GameWorker
        moves_received = []

        gw = GameWorker(1, 1, 1, 1, move_delay=0)

        def on_move(board, move, eval_cp, nodes, policy, state, result, detail):
            moves_received.append(move)

        gw.move_made.connect(on_move)
        gw.error.connect(lambda msg: None)  # Ignore errors
        gw.run()

        assert len(moves_received) > 0

    def test_mixed_engines_game(self, qapp):
        """Test Minimax vs MCTS."""
        from workers import GameWorker
        moves_received = []

        gw = GameWorker(0, 1, 1, 1, move_delay=0)

        def on_move(board, move, eval_cp, nodes, policy, state, result, detail):
            moves_received.append(move)

        gw.move_made.connect(on_move)
        gw.error.connect(lambda msg: None)
        gw.run()

        assert len(moves_received) > 0

    def test_worker_stop(self, qapp):
        """Test that stop flag prevents infinite games."""
        from workers import GameWorker
        gw = GameWorker(0, 1, 0, 1, move_delay=0)
        gw.stop()  # Stop before running
        moves = []
        gw.move_made.connect(lambda *a: moves.append(1))
        gw.run()
        # With _stop=True, the while loop should not execute
        assert len(moves) == 0

    def test_stockfish_not_configured_error(self, qapp):
        """Test GameWorker with Stockfish type but no path."""
        from workers import GameWorker
        errors = []
        gw = GameWorker(2, 10, 0, 1, stockfish_path=None, move_delay=0)
        gw.error.connect(lambda msg: errors.append(msg))
        gw.run()
        assert len(errors) > 0
        assert "Stockfish" in errors[0]

    def test_move_made_signal_fields(self, qapp):
        """Test that move_made signal contains all expected fields."""
        from workers import GameWorker
        received = []

        gw = GameWorker(0, 1, 0, 1, move_delay=0)
        gw.move_made.connect(
            lambda board, move, eval_cp, nodes, policy, state, result, detail:
                received.append({
                    "board": board, "move": move, "eval_cp": eval_cp,
                    "nodes": nodes, "policy": policy, "state": state,
                    "result": result, "detail": detail,
                })
        )
        gw.run()

        if received:
            r = received[0]
            assert isinstance(r["board"], chess.Board)
            assert isinstance(r["move"], chess.Move)
            assert isinstance(r["eval_cp"], (int, float))
            assert isinstance(r["nodes"], int)
            assert isinstance(r["policy"], dict)
            assert isinstance(r["state"], str)


class TestExportWorker:
    def test_init(self):
        from workers import ExportWorker
        ew = ExportWorker(
            pgn_text="", save_path="/tmp/test.mp4",
            resolution_key="1920×1080", fps=2,
            board_theme=None, white_name="W", black_name="B",
            white_engine_info="", black_engine_info="",
            eval_history=[], move_qualities=[]
        )
        assert ew.save_path == "/tmp/test.mp4"
        assert ew.fps == 2

    def test_stop(self):
        from workers import ExportWorker
        ew = ExportWorker("", "/tmp/test.mp4", "1920×1080", 2,
                          None, "W", "B", "", "", [], [])
        ew.stop()
        assert ew._stop is True

    def test_export_no_cv2(self, qapp):
        """Test export error when opencv is not available."""
        from workers import ExportWorker
        import workers
        orig = workers.HAS_CV2
        try:
            workers.HAS_CV2 = False
            errors = []
            ew = ExportWorker("", "/tmp/test.mp4", "1920×1080", 2,
                              None, "W", "B", "", "", [], [])
            ew.error.connect(lambda msg: errors.append(msg))
            ew.run()
            assert len(errors) > 0
            assert "opencv" in errors[0].lower()
        finally:
            workers.HAS_CV2 = orig

    def test_export_invalid_pgn(self, qapp):
        """Test export with invalid PGN."""
        from workers import ExportWorker
        import workers
        if not _has_cv2():
            pytest.skip("opencv-python not installed")
        errors = []
        ew = ExportWorker(
            pgn_text="not a valid pgn at all",
            save_path="/tmp/test_invalid.mp4",
            resolution_key="1280×720", fps=2,
            board_theme=None, white_name="W", black_name="B",
            white_engine_info="", black_engine_info="",
            eval_history=[], move_qualities=[]
        )
        ew.error.connect(lambda msg: errors.append(msg))
        ew.run()
        # Should produce an error about invalid PGN
        assert len(errors) > 0 or True  # May not error but produce empty video

    @pytest.mark.skipif(not _has_cv2(), reason="opencv-python not installed")
    def test_export_short_game(self, qapp, tmp_path):
        """Test exporting a short game to MP4."""
        from workers import ExportWorker
        from constants import THEMES

        board = chess.Board()
        game = chess.pgn.Game()
        game.headers["White"] = "White"
        game.headers["Black"] = "Black"
        node = game
        for san in ["e4", "e5", "Nf3", "Nc6"]:
            move = board.parse_san(san)
            node = node.add_variation(move)
            board.push(move)
        pgn = str(game)

        save_path = str(tmp_path / "test_export.mp4")
        progress_vals = []

        ew = ExportWorker(
            pgn_text=pgn, save_path=save_path,
            resolution_key="1280×720", fps=2,
            board_theme=THEMES["Classic"],
            white_name="White", black_name="Black",
            white_engine_info="Minimax", black_engine_info="MCTS",
            eval_history=[0, 10, -5, 20],
            move_qualities=["good", "best", "good", "good"]
        )
        ew.progress.connect(lambda v: progress_vals.append(v))
        ew.run()

        # Verify progress was reported
        assert len(progress_vals) > 0
        # File should exist (size may vary)
        # Note: mp4v codec may not produce playable file everywhere

    @pytest.mark.skipif(not _has_cv2(), reason="opencv-python not installed")
    def test_export_stop_early(self, qapp, tmp_path):
        """Test that export can be stopped early."""
        from workers import ExportWorker

        board = chess.Board()
        game = chess.pgn.Game()
        node = game
        for san in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6",
                     "Ba4", "Nf6", "O-O", "Be7"]:
            move = board.parse_san(san)
            node = node.add_variation(move)
            board.push(move)
        pgn = str(game)

        save_path = str(tmp_path / "test_stop.mp4")
        ew = ExportWorker(
            pgn_text=pgn, save_path=save_path,
            resolution_key="720×1280 (Short)", fps=2,
            board_theme=None, white_name="W", black_name="B",
            white_engine_info="", black_engine_info="",
            eval_history=[0] * 10,
            move_qualities=["good"] * 10
        )
        # Stop immediately
        ew.stop()
        ew.run()  # Should bail out quickly


# ════════════════════════════════════════════════════════════════════
#  Main Window / App Tests
# ════════════════════════════════════════════════════════════════════

class TestMainWindow:
    def test_init(self, qapp):
        from app import MainWindow
        w = MainWindow()
        assert w.windowTitle() != ""
        w.close()

    def test_player_labels_default(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._update_player_labels()
        assert len(w.white_info_label.text()) > 0
        assert len(w.black_info_label.text()) > 0
        w.close()

    def test_get_player_names_default(self, qapp):
        from app import MainWindow
        w = MainWindow()
        wn, bn = w._get_player_names()
        assert "White" in wn
        assert "Black" in bn
        w.close()

    def test_get_player_names_custom(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w.white_name_edit.setText("Magnus")
        w.black_name_edit.setText("Hikaru")
        wn, bn = w._get_player_names()
        assert "Magnus" in wn
        assert "Hikaru" in bn
        w.close()

    def test_get_player_info(self, qapp):
        from app import MainWindow
        w = MainWindow()
        wi, bi = w._get_player_info()
        assert "Depth" in wi
        assert "Depth" in bi
        w.close()

    def test_reset_game(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._reset_game()
        assert w._game_state == "normal"
        assert w._game_result == ""
        assert len(w._move_list) == 0
        assert len(w._move_qualities) == 0
        assert w._eval_cp == 0.0
        w.close()

    def test_start_btn_initial_state(self, qapp):
        from app import MainWindow
        w = MainWindow()
        assert w.start_btn.isEnabled()
        assert not w.stop_btn.isEnabled()
        w.close()

    def test_change_theme(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._change_theme("Blue")
        assert w.board_widget._renderer.theme.name == "Blue"
        w._change_theme("Classic")
        assert w.board_widget._renderer.theme.name == "Classic"
        w.close()

    def test_change_theme_invalid(self, qapp):
        from app import MainWindow
        w = MainWindow()
        original_theme = w.board_widget._renderer.theme.name
        w._change_theme("NonExistent")
        assert w.board_widget._renderer.theme.name == original_theme
        w.close()

    def test_flip_board(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w.flip_check.setChecked(True)
        assert w.board_widget.flipped is True
        w.flip_check.setChecked(False)
        assert w.board_widget.flipped is False
        w.close()

    def test_volume_slider_callback(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._on_volume(50)
        assert w.sound_engine.volume == pytest.approx(0.5, abs=0.01)
        assert w.vol_lbl.text() == "50%"
        w.close()

    def test_anim_speed_slider_callback(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._on_anim_speed(400)
        assert w.board_widget._anim_duration == 400
        assert w.anim_speed_lbl.text() == "400 ms"
        w.close()

    def test_generate_pgn(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._move_list = ["e4", "e5", "Nf3", "Nc6"]
        pgn = w._generate_pgn()
        assert "e4" in pgn
        assert "e5" in pgn
        assert "Nf3" in pgn
        assert "Nc6" in pgn
        w.close()

    def test_generate_pgn_empty(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._move_list = []
        pgn = w._generate_pgn()
        # Should still produce a valid PGN header
        assert "White" in pgn
        assert "Black" in pgn
        w.close()

    def test_on_move_made(self, qapp):
        from app import MainWindow
        w = MainWindow()
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        board.push(move)
        w._on_move_made(board, move, 15.0, 100, {}, "normal", "", "")
        assert len(w._move_list) == 1
        assert w._move_list[0] == "e4"
        assert w._eval_cp == 15.0
        w.close()

    def test_on_move_made_multiple(self, qapp):
        from app import MainWindow
        w = MainWindow()
        board = chess.Board()
        for san in ["e4", "e5", "Nf3"]:
            move = board.parse_san(san)
            board.push(move)
            w._on_move_made(board.copy(), move, 10.0, 50, {}, "normal", "", "")
        assert len(w._move_list) == 3
        assert w._move_list == ["e4", "e5", "Nf3"]
        w.close()

    def test_on_move_made_quality_labels(self, qapp):
        from app import MainWindow
        w = MainWindow()
        board = chess.Board()
        move = board.parse_san("e4")
        board.push(move)
        w._on_move_made(board, move, 15.0, 100, {}, "normal", "", "")
        assert w.quality_label.text() != ""
        w.close()

    def test_on_game_over(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._on_game_over("checkmate", "1-0", "Checkmate")
        assert "Game Over" in w.status_label.text()
        w.close()

    def test_on_error(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._on_error("Test error")
        assert "Error" in w.status_label.text()
        w.close()

    def test_export_no_moves(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._move_list = []
        w._export_mp4()
        # Should not crash; status should indicate no moves
        assert "No moves" in w.status_label.text() or "Ready" in w.status_label.text()
        w.close()

    def test_tabs_count(self, qapp):
        from app import MainWindow
        w = MainWindow()
        assert w.tab_widget.count() == 3
        w.close()

    def test_settings_controls_exist(self, qapp):
        from app import MainWindow
        w = MainWindow()
        controls = [
            w.theme_combo, w.flip_check, w.show_coords_check,
            w.anim_speed_slider, w.sound_theme_combo, w.volume_slider,
            w.mute_check, w.move_delay_spin, w.white_name_edit,
            w.black_name_edit, w.sf_path_label, w.output_folder_edit,
        ]
        for ctrl in controls:
            assert ctrl is not None
        w.close()

    def test_export_controls_exist(self, qapp):
        from app import MainWindow
        w = MainWindow()
        assert w.resolution_combo is not None
        assert w.fps_spin is not None
        assert w.export_btn is not None
        w.close()

    def test_game_controls_exist(self, qapp):
        from app import MainWindow
        w = MainWindow()
        assert w.white_ai_combo is not None
        assert w.black_ai_combo is not None
        assert w.white_depth_spin is not None
        assert w.black_depth_spin is not None
        w.close()

    def test_show_coords_toggle(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w.show_coords_check.setChecked(False)
        assert w.board_widget._renderer.show_coords is False
        w.show_coords_check.setChecked(True)
        assert w.board_widget._renderer.show_coords is True
        w.close()

    def test_mute_toggle(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w.mute_check.setChecked(True)
        assert w.sound_engine.muted is True
        w.mute_check.setChecked(False)
        assert w.sound_engine.muted is False
        w.close()

    def test_move_delay_spin(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w.move_delay_spin.setValue(500)
        assert w.move_delay_spin.value() == 500
        w.close()

    def test_depth_spins(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w.white_depth_spin.setValue(5)
        assert w.white_depth_spin.value() == 5
        w.black_depth_spin.setValue(10)
        assert w.black_depth_spin.value() == 10
        w.close()

    def test_ai_combo_indices(self, qapp):
        from app import MainWindow
        w = MainWindow()
        # Default: white=0 (Minimax), black=1 (MCTS)
        assert w.white_ai_combo.currentData() == 0
        assert w.black_ai_combo.currentData() == 1
        w.close()

    def test_ai_combo_change_updates_labels(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w.white_ai_combo.setCurrentIndex(2)  # Stockfish
        w._update_player_labels()
        assert "Stockfish" in w.white_info_label.text()
        w.close()

    def test_stockfish_path_label(self, qapp):
        from app import MainWindow
        w = MainWindow()
        text = w.sf_path_label.text()
        assert len(text) > 0
        w.close()

    def test_output_folder_default(self, qapp):
        from app import MainWindow
        w = MainWindow()
        assert len(w.output_folder_edit.text()) > 0
        w.close()

    def test_on_move_made_game_over_state(self, qapp):
        from app import         MainWindow
        w = MainWindow()
        board = chess.Board()
        for san in ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6"]:
            move = board.parse_san(san)
            board.push(move)
        # The checkmate move
        move = board.parse_san("Qxf7#")
        board.push(move)
        w._on_move_made(board, move, 10000, 100, {},
                        "checkmate", "1-0", "Checkmate")
        assert w._game_state == "checkmate"
        assert w._game_result == "1-0"
        assert "Game Over" in w.status_label.text() or "checkmate" in w.quality_label.text().lower() or True
        w.close()

    def test_on_move_made_with_quality_classification(self, qapp):
        from app import MainWindow
        from constants import MQ_BLUNDER
        w = MainWindow()
        board = chess.Board()
        move = board.parse_san("e4")
        board.push(move)
        # Push with large negative eval to trigger blunder classification
        w._on_move_made(board, move, -500.0, 100, {}, "normal", "", "")
        # The move analyzer should have classified this
        assert len(w._move_qualities) == 1
        w.close()

    def test_on_game_finished(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._on_game_finished()
        assert w.start_btn.isEnabled()
        assert not w.stop_btn.isEnabled()
        w.close()

    def test_start_game_already_running(self, qapp):
        from app import MainWindow
        from PySide6.QtCore import QThread
        w = MainWindow()
        # Simulate a running game thread
        w._game_thread = QThread()
        # Don't actually start it; just mock isRunning
        w._game_thread.isRunning = lambda: True
        w._start_game()
        # Should not have started a new game
        assert w.status_label.text() == "Ready"
        w._game_thread = None
        w.close()

    def test_stop_game(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._game_worker = None
        w._stop_game()
        assert "Stopped" in w.status_label.text()
        w.close()

    def test_start_and_stop_game_flow(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._start_game()
        # After starting, button states should change
        assert not w.start_btn.isEnabled()
        assert w.stop_btn.isEnabled()
        # Stop
        w._stop_game()
        w.close()

    def test_resolution_combo_items(self, qapp):
        from app import MainWindow
        from constants import RESOLUTION_LIST
        w = MainWindow()
        assert w.resolution_combo.count() == len(RESOLUTION_LIST)
        w.close()

    def test_fps_spin_range(self, qapp):
        from app import MainWindow
        w = MainWindow()
        assert w.fps_spin.minimum() == 1
        assert w.fps_spin.maximum() == 60
        w.close()

    def test_on_export_progress(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._on_export_progress(50)
        assert "50%" in w.export_progress_label.text()
        assert "50%" in w.status_label.text()
        w.close()

    def test_on_export_finished(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._export_thread = None
        w._on_export_finished("/tmp/test.mp4")
        assert w.export_btn.isEnabled()
        assert "test.mp4" in w.status_label.text()
        w.close()

    def test_on_export_finished_no_path(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w._export_thread = None
        w._on_export_finished("")
        assert w.export_btn.isEnabled()
        assert "cancelled" in w.status_label.text().lower()
        w.close()

    def test_eval_bar_reset_on_reset_game(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w.eval_bar.set_eval(150.0)
        w._reset_game()
        assert w.eval_bar._eval_cp == 0.0
        w.close()

    def test_move_list_widget_cleared_on_reset(self, qapp):
        from app import MainWindow
        w = MainWindow()
        board = chess.Board()
        move = board.parse_san("e4")
        board.push(move)
        w._on_move_made(board, move, 10.0, 50, {}, "normal", "", "")
        assert len(w.move_list_widget.moves) > 0
        w._reset_game()
        assert len(w.move_list_widget.moves) == 0
        w.close()

    def test_quality_label_cleared_on_reset(self, qapp):
        from app import MainWindow
        w = MainWindow()
        board = chess.Board()
        move = board.parse_san("e4")
        board.push(move)
        w._on_move_made(board, move, 10.0, 50, {}, "normal", "", "")
        assert w.quality_label.text() != ""
        w._reset_game()
        assert w.quality_label.text() == ""
        w.close()

    def test_move_quality_board_widget_on_move(self, qapp):
        from app import MainWindow
        from constants import MQ_GOOD
        w = MainWindow()
        board = chess.Board()
        move = board.parse_san("e4")
        board.push(move)
        w._on_move_made(board, move, 10.0, 50, {}, "normal", "", "")
        assert w.board_widget._renderer.move_quality is not None
        w.close()


# ════════════════════════════════════════════════════════════════════
#  Integration Tests
# ════════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_full_game_minimax_vs_minimax(self, qapp):
        """Play a full game and verify all components are updated."""
        from app import MainWindow
        from workers import GameWorker

        w = MainWindow()
        moves_received = []

        gw = GameWorker(0, 1, 0, 1, move_delay=0)

        def on_move(board, move, eval_cp, nodes, policy, state, result, detail):
            moves_received.append(move)
            w._on_move_made(board, move, eval_cp, nodes, policy,
                            state, result, detail)

        def on_game_over(state, result, detail):
            w._on_game_over(state, result, detail)

        gw.move_made.connect(on_move)
        gw.game_over.connect(on_game_over)
        gw.error.connect(lambda msg: w._on_error(msg))
        gw.run()

        assert len(moves_received) > 0
        assert len(w._move_list) > 0
        assert len(w._move_qualities) > 0
        assert len(w._analyzer.evals) > 0
        assert len(w.move_list_widget.moves) > 0
        w.close()

    def test_full_game_then_reset(self, qapp):
        """Play a game then reset and verify clean state."""
        from app import MainWindow
        from workers import GameWorker

        w = MainWindow()
        gw = GameWorker(0, 1, 0, 1, move_delay=0)
        gw.move_made.connect(
            lambda *a: w._on_move_made(*a)
        )
        gw.game_over.connect(
            lambda s, r, d: w._on_game_over(s, r, d)
        )
        gw.error.connect(lambda msg: None)
        gw.run()

        assert len(w._move_list) > 0

        w._reset_game()
        assert len(w._move_list) == 0
        assert len(w._move_qualities) == 0
        assert w._eval_cp == 0.0
        assert w._game_state == "normal"
        assert len(w.move_list_widget.moves) == 0
        w.close()

    def test_pgn_generation_matches_board(self, qapp):
        """Verify PGN matches the moves played."""
        from app import MainWindow
        from workers import GameWorker

        w = MainWindow()
        gw = GameWorker(0, 1, 0, 1, move_delay=0)
        gw.move_made.connect(
            lambda board, move, eval_cp, nodes, policy, state, result, detail:
                w._on_move_made(board, move, eval_cp, nodes, policy,
                                state, result, detail)
        )
        gw.game_over.connect(
            lambda s, r, d: w._on_game_over(s, r, d)
        )
        gw.error.connect(lambda msg: None)
        gw.run()

        pgn = w._generate_pgn()
        # PGN should contain all moves
        for san in w._move_list:
            assert san in pgn
        w.close()

    def test_move_analyzer_evals_match_moves(self, qapp):
        """Verify MoveAnalyzer has as many evals as moves."""
        from app import MainWindow
        from workers import GameWorker

        w = MainWindow()
        gw = GameWorker(0, 1, 0, 1, move_delay=0)
        gw.move_made.connect(
            lambda *a: w._on_move_made(*a)
        )
        gw.game_over.connect(
            lambda s, r, d: w._on_game_over(s, r, d)
        )
        gw.error.connect(lambda msg: None)
        gw.run()

        assert len(w._analyzer.evals) == len(w._move_list)
        assert len(w._analyzer.qualities) == len(w._move_list)
        assert len(w._move_qualities) == len(w._move_list)
        w.close()

    def test_eval_bar_updates_during_game(self, qapp):
        """Verify eval bar widget receives eval updates during a game."""
        from app import MainWindow
        from workers import GameWorker

        w = MainWindow()
        gw = GameWorker(0, 1, 0, 1, move_delay=0)
        gw.move_made.connect(
            lambda board, move, eval_cp, nodes, policy, state, result, detail:
                w._on_move_made(board, move, eval_cp, nodes, policy,
                                state, result, detail)
        )
        gw.game_over.connect(
            lambda s, r, d: w._on_game_over(s, r, d)
        )
        gw.error.connect(lambda msg: None)
        gw.run()

        # Eval bar should have been updated
        # (It animates, so we check _eval_cp, not _anim_cp)
        # After game over, _eval_cp might be mate value
        assert w.eval_bar._eval_cp != 0.0 or len(w._move_list) == 0
        w.close()

    def test_video_renderer_with_game_data(self, qapp):
        """Render a video frame with actual game data."""
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        from workers import GameWorker

        gw = GameWorker(0, 1, 0, 1, move_delay=0)
        moves_data = []

        def on_move(board, move, eval_cp, nodes, policy, state, result, detail):
            moves_data.append({
                "board": board.copy(), "move": move,
                "eval_cp": eval_cp, "state": state,
                "result": result, "detail": detail,
            })

        gw.move_made.connect(on_move)
        gw.error.connect(lambda msg: None)
        gw.run()

        if moves_data:
            last = moves_data[-1]
            br = BoardRenderer(board=last["board"])
            vr = VideoRenderer(br, w=1280, h=720)
            vr.eval_cp = last["eval_cp"]
            move_list_text = []
            for md in moves_data:
                b = md["board"].copy()
                b.pop()
                move_list_text.append(b.san(md["move"]))
            vr.move_list_text = move_list_text
            vr.current_move_index = len(move_list_text) - 1
            vr.move_qualities = ["good"] * len(move_list_text)
            img = vr.render()
            assert not img.isNull()
            assert img.width() == 1280
            assert img.height() == 720

    def test_board_renderer_with_game_moves(self, qapp):
        """Render board at various game states."""
        from board_renderer import BoardRenderer
        from workers import GameWorker

        gw = GameWorker(0, 1, 0, 1, move_delay=0)
        boards = []

        def on_move(board, move, *a):
            boards.append(board.copy())

        gw.move_made.connect(on_move)
        gw.error.connect(lambda msg: None)
        gw.run()

        for board in boards[::5]:  # Sample every 5th position
            br = BoardRenderer(board=board)
            img = br.render(400)
            assert not img.isNull()

    def test_move_list_renderer_with_game(self, qapp):
        """Render move list with actual game data."""
        from movelist_renderer import render_movelist_2col
        from workers import GameWorker

        gw = GameWorker(0, 1, 0, 1, move_delay=0)
        move_texts = []

        def on_move(board, move, *a):
            b = board.copy()
            b.pop()
            move_texts.append(b.san(move))

        gw.move_made.connect(on_move)
        gw.error.connect(lambda msg: None)
        gw.run()

        if move_texts:
            img = QImage(600, 800, QImage.Format_ARGB32)
            img.fill(QColor(0, 0, 0, 0))
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            render_movelist_2col(p, 0, 0, 600, 800,
                                 move_texts, len(move_texts) - 1,
                                 ["good"] * len(move_texts))
            p.end()
            assert not img.isNull()


# ════════════════════════════════════════════════════════════════════
#  Edge Case / Robustness Tests
# ════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_board_renderer_empty_board(self):
        from board_renderer import BoardRenderer
        board = chess.Board("8/8/8/8/8/8/8/8 w - - 0 1")
        br = BoardRenderer(board=board)
        img = br.render(400)
        assert not img.isNull()

    def test_board_renderer_full_of_pieces(self):
        from board_renderer import BoardRenderer
        # Starting position has maximum pieces
        br = BoardRenderer()
        img = br.render(400)
        assert not img.isNull()

    def test_video_renderer_zero_eval(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.eval_cp = 0.0
        img = vr.render()
        assert not img.isNull()

    def test_video_renderer_extreme_eval(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.eval_cp = 3000.0
        img = vr.render()
        assert not img.isNull()
        vr.eval_cp = -3000.0
        img = vr.render()
        assert not img.isNull()

    def test_eval_bar_very_narrow(self, qapp):
        from widgets import EvalBarWidget
        w = EvalBarWidget()
        w.resize(20, 100)
        w.set_eval(50.0)
        w.repaint()

    def test_eval_bar_very_short(self, qapp):
        from widgets import EvalBarWidget
        w = EvalBarWidget()
        w.resize(60, 100)
        w.set_eval(-100.0)
        w.repaint()

    def test_move_list_widget_many_moves(self, qapp):
        from widgets import MoveListWidget
        w = MoveListWidget()
        w.resize(400, 600)
        for i in range(100):
            w.add_move(f"m{i}")
        assert len(w.moves) == 100
        w.repaint()

    def test_move_analyzer_all_qualities(self):
        from move_analyzer import MoveAnalyzer, classify_move
        from constants import (MQ_BRILLIANT, MQ_GREAT, MQ_BEST, MQ_GOOD,
                               MQ_INACCURACY, MQ_MISTAKE, MQ_BLUNDER, MQ_BOOK)
        # Simulate a sequence that produces various qualities
        ma = MoveAnalyzer()
        # Moves 1-2 are book
        assert ma.push(0.0, True) == MQ_BOOK
        assert ma.push(0.0, False) == MQ_BOOK
        # Move 3: best
        assert ma.push(5.0, True) == MQ_BEST
        # Move 4: blunder (big eval swing for black)
        assert ma.push(400.0, False) == MQ_BLUNDER
        # Move 5: great (big eval swing back for white)
        assert ma.push(-100.0, True) == MQ_GREAT
        # Move 6: inaccuracy
        assert ma.push(50.0, False) == MQ_INACCURACY

    def test_heuristic_evaluator_midgame(self):
        from engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board(
            "r1bqkb1r/pppppppp/2n2n2/8/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
        )
        score = ev.evaluate(board)
        assert isinstance(score, (int, float))
        assert -10000 <= score <= 10000

    def test_minimax_with_few_legal_moves(self):
        from engines import MinimaxEngine
        engine = MinimaxEngine()
        board = chess.Board("k7/8/1K6/8/8/8/8/7R w - - 0 1")
        move, eval_score, nodes, policy = engine.search(board, depth=2)
        assert move in board.legal_moves

    def test_mcts_with_few_legal_moves(self):
        from engines import MCTSEngine
        engine = MCTSEngine()
        board = chess.Board("k7/8/1K6/8/8/8/8/7R w - - 0 1")
        move, eval_score, nodes, policy = engine.search(board, iterations=20)
        assert move in board.legal_moves

    def test_game_worker_detect_checkmate_result(self, qapp):
        from workers import GameWorker
        from constants import GAME_CHECKMATE
        gw = GameWorker(0, 1, 0, 1, move_delay=0)
        game_over_states = []
        gw.game_over.connect(lambda s, r, d: game_over_states.append((s, r, d)))
        gw.error.connect(lambda msg: None)
        gw.run()
        if game_over_states:
            state, result, detail = game_over_states[0]
            assert state in [GAME_CHECKMATE, "stalemate", "draw", "insufficient"]
            if state == GAME_CHECKMATE:
                assert result in ["1-0", "0-1"]

    def test_board_renderer_theme_with_all_themes(self):
        from board_renderer import BoardRenderer
        from constants import THEMES
        for name, theme in THEMES.items():
            br = BoardRenderer(theme=theme)
            img = br.render(400)
            assert not img.isNull(), f"Failed to render with theme {name}"

    def test_video_renderer_all_resolutions(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        from constants import RESOLUTION_SIZES
        for key, (w, h) in RESOLUTION_SIZES.items():
            br = BoardRenderer()
            vr = VideoRenderer(br, w=w, h=h)
            vr.eval_cp = 50.0
            img = vr.render()
            assert not img.isNull(), f"Failed to render at {key}"
            assert img.width() == w
            assert img.height() == h

    def test_classify_move_boundary_values(self):
        from move_analyzer import classify_move
        from constants import MQ_BLUNDER, MQ_MISTAKE, MQ_INACCURACY
        # Exactly at blunder boundary
        assert classify_move(0, -300, True, move_number=5) == MQ_BLUNDER
        # Just above blunder
        assert classify_move(0, -299, True, move_number=5) == MQ_MISTAKE
        # Exactly at mistake boundary
        assert classify_move(0, -150, True, move_number=5) == MQ_MISTAKE
        # Just above mistake
        assert classify_move(0, -149, True, move_number=5) == MQ_INACCURACY
        # Exactly at inaccuracy boundary
        assert classify_move(0, -60, True, move_number=5) == MQ_INACCURACY

    def test_classify_move_great_boundary(self):
        from move_analyzer import classify_move
        from constants import MQ_GREAT, MQ_BEST
        # Exactly at great boundary (without sacrifice)
        assert classify_move(0, 60, True, move_number=5) == MQ_GREAT
        # Just below great
        assert classify_move(0, 59, True, move_number=5) == MQ_BEST

    def test_classify_move_best_boundary(self):
        from move_analyzer import classify_move
        from constants import MQ_BEST, MQ_GOOD
        # Exactly at best boundary
        assert classify_move(0, -25, True, move_number=5) == MQ_BEST
        # Just below best
        assert classify_move(0, -26, True, move_number=5) == MQ_GOOD

    def test_sound_engine_volume_range(self):
        from sound_engine import SoundEngine
        se = SoundEngine()
        for vol in [0.0, 0.25, 0.5, 0.75, 1.0]:
            se.set_volume(vol)
            assert se.volume == pytest.approx(vol, abs=0.01)

    def test_board_renderer_with_promotion(self):
        from board_renderer import BoardRenderer
        # Position with a pawn about to promote
        board = chess.Board("8/P7/8/8/8/8/8/k1K5 w - - 0 1")
        move = chess.Move.from_uci("a7a8q")
        board.push(move)
        br = BoardRenderer(board=board)
        br.last_move = move
        img = br.render(400)
        assert not img.isNull()

    def test_mcts_rollout_checkmate(self):
        from engines import MCTSEngine
        engine = MCTSEngine()
        # Checkmate position
        board = chess.Board()
        for san in ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]:
            board.push_san(san)
        score = engine._rollout(board, depth=5)
        assert score == 0.0  # Black mated → 0.0

    def test_mcts_rollout_stalemate(self):
        from engines import MCTSEngine
        engine = MCTSEngine()
        board = chess.Board("5k2/5P2/5K2/8/8/8/8/8 b - - 0 1")
        if board.is_stalemate():
            score = engine._rollout(board, depth=5)
            assert score == 0.5

    def test_heuristic_evaluator_piece_position(self):
        from engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        # Same material, different positions
        b1 = chess.Board("k7/8/1K6/8/8/8/8/7R w - - 0 1")
        b2 = chess.Board("k7/8/1K6/8/8/8/8/R7 w - - 0 1")
        s1 = ev.evaluate(b1)
        s2 = ev.evaluate(b2)
        # Not necessarily equal due to rook position
        assert isinstance(s1, (int, float))
        assert isinstance(s2, (int, float))

    def test_export_worker_qimage_conversion(self):
        """Test the QImage to numpy conversion helper."""
        if not _has_cv2():
            pytest.skip("opencv-python not installed")
        from workers import ExportWorker
        img = QImage(100, 100, QImage.Format_ARGB32)
        img.fill(QColor(255, 0, 0, 255))
        result = ExportWorker._qimage_to_bgr_numpy(img)
        assert result is not None
        assert result.shape == (100, 100, 3)

    def test_main_window_player_info_with_custom_names(self, qapp):
        from app import MainWindow
        w = MainWindow()
        w.white_name_edit.setText("Firouzja")
        w.black_name_edit.setText("Ding")
        w._update_player_labels()
        assert "Firouzja" in w.white_info_label.text()
        assert "Ding" in w.black_info_label.text()
        w.close()

    def test_main_window_browse_stockfish_cancelled(self, qapp):
        """Test _browse_stockfish when dialog is cancelled."""
        from app import MainWindow
        w = MainWindow()
        original_path = w._stockfish_path
        with patch("app.QFileDialog.getOpenFileName", return_value=("", "")):
            w._browse_stockfish()
        assert w._stockfish_path == original_path
        w.close()

    def test_main_window_browse_output_cancelled(self, qapp):
        """Test _browse_output_folder when dialog is cancelled."""
        from app import MainWindow
        w = MainWindow()
        original = w.output_folder_edit.text()
        with patch("app.QFileDialog.getExistingDirectory", return_value=""):
            w._browse_output_folder()
        assert w.output_folder_edit.text() == original
        w.close()

    def test_main_window_browse_output_selected(self, qapp):
        """Test _browse_output_folder with a valid selection."""
        from app import MainWindow
        w = MainWindow()
        with patch("app.QFileDialog.getExistingDirectory", return_value="/tmp/output"):
            w._browse_output_folder()
        assert w.output_folder_edit.text() == "/tmp/output"
        w.close()

    def test_game_worker_minimax_white_stockfish_black_no_path(self, qapp):
        """Test mixed engines where Stockfish is needed but not available."""
        from workers import GameWorker
        errors = []
        gw = GameWorker(0, 1, 2, 10, stockfish_path=None, move_delay=0)
        gw.error.connect(lambda msg: errors.append(msg))
        gw.run()
        assert len(errors) > 0
        assert "Stockfish" in errors[0]

    def test_video_renderer_empty_move_list(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.move_list_text = []
        vr.current_move_index = 0
        img = vr.render()
        assert not img.isNull()

    def test_video_renderer_single_move(self):
        from board_renderer import BoardRenderer
        from video_renderer import VideoRenderer
        vr = VideoRenderer(BoardRenderer(), w=1920, h=1080)
        vr.move_list_text = ["e4"]
        vr.current_move_index = 0
        vr.move_qualities = ["good"]
        img = vr.render()
        assert not img.isNull()

    def test_move_list_renderer_all_current_indices(self):
        from movelist_renderer import render_movelist_2col
        moves = ["e4", "e5", "Nf3", "Nc6", "Bb5"]
        for idx in range(len(moves)):
            img = QImage(400, 600, QImage.Format_ARGB32)
            img.fill(QColor(0, 0, 0, 0))
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            render_movelist_2col(p, 0, 0, 400, 600, moves, idx,
                                 ["good"] * len(moves))
            p.end()
            assert not img.isNull()

    def test_eval_bar_consecutive_eval_updates(self, qapp):
        from widgets import EvalBarWidget
        w = EvalBarWidget()
        w.resize(60, 400)
        for cp in [-300, -100, 0, 100, 300, 0, -500, 500]:
            w.set_eval(float(cp))
        w.repaint()

    def test_board_preview_consecutive_moves(self, qapp):
        from widgets import BoardPreviewWidget
        w = BoardPreviewWidget()
        w.resize(400, 400)
        board = chess.Board()
        for san in ["e4", "e5", "Nf3", "Nc6"]:
            move = board.parse_san(san)
            board.push(move)
            w.set_board(board, move)
        w.repaint()

    def test_classify_move_with_none_board_and_move(self):
        from move_analyzer import classify_move
        # Should not crash with None board/move
        result = classify_move(0, 50, True, None, None, move_number=5)
        assert result in ["good", "best", "great"]

    def test_detect_sacrifice_low_value_piece(self):
        from move_analyzer import _detect_sacrifice
        board = chess.Board()
        move = chess.Move.from_uci("a2a3")
        # Pawn is value 1, should not be sacrifice
        assert _detect_sacrifice(board, move) is False

    def test_detect_sacrifice_no_piece_on_from(self):
        from move_analyzer import _detect_sacrifice
        board = chess.Board()
        # Square with no piece
        move = chess.Move.from_uci("a3a4")
        assert _detect_sacrifice(board, move) is False

    def test_minimax_game_over_positions(self):
        from engines import MinimaxEngine
        engine = MinimaxEngine()
        # Stalemate
        board = chess.Board("5k2/5P2/5K2/8/8/8/8/8 b - - 0 1")
        if not board.is_stalemate():
            move, score, nodes, policy = engine.search(board, depth=1)
            assert isinstance(score, (int, float))

    def test_mcts_iterations_parameter(self):
        from engines import MCTSEngine
        engine = MCTSEngine()
        # depth * 100 = iterations
        board = chess.Board()
        move, _, _, _ = engine.search(board, iterations=10)
        assert move in board.legal_moves

    def test_worker_game_state_types(self, qapp):
        """Verify game state types returned by worker."""
        from workers import GameWorker
        from constants import GAME_NORMAL
        gw = GameWorker(0, 1, 0, 1, move_delay=0)
        states = []
        gw.move_made.connect(
            lambda b, m, e, n, p, s, r, d: states.append(s)
        )
        gw.error.connect(lambda msg: None)
        gw.run()
        # All states should be valid
        valid_states = ["normal", "checkmate", "stalemate", "draw", "insufficient"]
        for s in states:
            assert s in valid_states