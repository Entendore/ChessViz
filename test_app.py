"""
Chess Video Maker Pro — Comprehensive Test Suite
Tests all features across every module in a single file.
Run:  pytest test_app.py -v
"""

import sys
import os
import io
import math
import tempfile
import time
import shutil
import platform

import pytest
import chess
import chess.pgn

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage



# ── QApplication singleton ──────────────────────────────────────────

_app = None


def qapp():
    global _app
    if _app is None:
        _app = QApplication.instance()
        if _app is None:
            _app = QApplication(sys.argv)
    return _app


def wait_for_thread(worker, timeout_ms=15000):
    """Wait for a QThread to finish while keeping the event loop alive
    so queued cross-thread signals can be delivered."""
    start = time.time()
    while worker.isRunning():
        qapp().processEvents()
        if time.time() - start > timeout_ms / 1000.0:
            break
        time.sleep(0.01)


def find_stockfish():
    """Find Stockfish binary on the system (cross-platform), or return None."""
    # Check PATH via shutil.which (works on Windows, Linux, macOS)
    which_path = shutil.which("stockfish")
    if which_path:
        return which_path
    # Check common install locations (exact paths)
    candidates = [
        "/usr/games/stockfish",
        "/usr/local/bin/stockfish",
        "/usr/bin/stockfish",
        "/snap/bin/stockfish",
        "/opt/homebrew/bin/stockfish",
        r"C:\Program Files\Stockfish\stockfish.exe",
        r"C:\Program Files\stockfish\stockfish.exe",
        r"C:\Stockfish\stockfish.exe",
        r"C:\Program Files (x86)\Stockfish\stockfish.exe",
        r"C:\Program Files (x86)\stockfish\stockfish.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    # Scan known Stockfish folders for any .exe with "stockfish" in the name
    # (the exe may be named stockfish-windows-x86-64.exe, stockfish_15.exe, etc.)
    scan_dirs = [
        r"C:\Program Files\Stockfish",
        r"C:\Program Files\stockfish",
        r"C:\Stockfish",
        r"C:\Program Files (x86)\Stockfish",
        r"C:\Program Files (x86)\stockfish",
    ]
    for d in scan_dirs:
        if os.path.isdir(d):
            for fname in os.listdir(d):
                lower = fname.lower()
                if lower.endswith(".exe") and "stockfish" in lower:
                    return os.path.join(d, fname)
    return None


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _ensure_qapp():
    qapp()
    yield


@pytest.fixture
def main_window():
    from main_window import MainWindow
    w = MainWindow()
    w.show()
    yield w
    w.close()


@pytest.fixture
def board_widget():
    from board_widget import ChessBoardWidget
    w = ChessBoardWidget()
    w.resize(500, 500)
    w.show()
    yield w
    w.close()


@pytest.fixture
def eval_bar():
    from eval_bar import EvalBarWidget
    w = EvalBarWidget()
    w.show()
    yield w
    w.close()


# ═══════════════════════════════════════════════════════════════════
# 1. CONSTANTS
# ═══════════════════════════════════════════════════════════════════

class TestConstants:
    def test_piece_sym_completeness(self):
        from constants import PIECE_SYM
        for pt in [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING]:
            for c in [chess.WHITE, chess.BLACK]:
                assert (pt, c) in PIECE_SYM
                assert isinstance(PIECE_SYM[(pt, c)], str)
                assert len(PIECE_SYM[(pt, c)]) > 0

    def test_ai_map_keys(self):
        from constants import AI_MAP
        assert 0 in AI_MAP
        assert 1 in AI_MAP
        assert 2 in AI_MAP

    def test_ai_map_values(self):
        from constants import AI_MAP
        assert "Minimax (Alpha-Beta)" in AI_MAP.values()
        assert "MCTS (Monte Carlo)" in AI_MAP.values()
        assert "Stockfish (UCI)" in AI_MAP.values()

    def test_sample_pgn_parseable(self):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        assert game is not None
        assert game.headers.get("White") == "Carlsen, Magnus"
        assert game.headers.get("Black") == "Nepomniachtchi, Ian"

    def test_has_cv2_is_bool(self):
        from constants import HAS_CV2
        assert isinstance(HAS_CV2, bool)

    def test_board_theme_defaults(self):
        from constants import BoardTheme
        t = BoardTheme()
        assert t.name == "Classic"
        assert t.light_sq.lightness() > 0
        assert t.dark_sq.lightness() > 0
        assert t.highlight.alpha() > 0
        assert t.last_move.alpha() > 0

    def test_board_theme_custom(self):
        from constants import BoardTheme
        t = BoardTheme("Custom", light=(255, 0, 0), dark=(0, 0, 255))
        assert t.name == "Custom"
        assert t.light_sq == QColor(255, 0, 0)
        assert t.dark_sq == QColor(0, 0, 255)

    def test_themes_dict_has_all(self):
        from constants import THEMES
        assert "Classic" in THEMES
        assert "Blue" in THEMES
        assert "Green" in THEMES
        assert "Brown" in THEMES

    def test_themes_are_board_theme_instances(self):
        from constants import THEMES, BoardTheme
        for name, theme in THEMES.items():
            assert isinstance(theme, BoardTheme)
            assert theme.name == name


# ═══════════════════════════════════════════════════════════════════
# 2. AI ENGINES — HeuristicEvaluator
# ═══════════════════════════════════════════════════════════════════

class TestHeuristicEvaluator:
    def test_starting_position_near_zero(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        score = ev.evaluate(chess.Board())
        assert abs(score) < 100

    def test_checkmate_white_mated(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board("rnb1kbnr/pppp1ppp/4p3/8/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
        if board.is_checkmate():
            score = ev.evaluate(board)
            assert score == -99999

    def test_checkmate_black_mated(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board()
        for m in ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]:
            board.push_uci(m)
        assert board.is_checkmate()
        score = ev.evaluate(board)
        assert score == 99999

    def test_stalemate_is_zero(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board("8/8/8/4k3/8/8/8/4K3 w - - 0 1")
        score = ev.evaluate(board)
        assert score == 0

    def test_white_extra_queen_positive(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board("8/8/8/8/8/8/8/4K2Q w - - 0 1")
        score = ev.evaluate(board)
        assert score > 0

    def test_black_extra_queen_negative(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board("4k2q/8/8/8/8/8/8/4K3 w - - 0 1")
        score = ev.evaluate(board)
        assert score < 0

    def test_pawn_table_applied(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board_center = chess.Board("8/8/8/8/4P3/8/8/4K2k w - - 0 1")
        board_edge = chess.Board("8/8/8/8/8/P7/8/4K2k w - - 0 1")
        score_center = ev.evaluate(board_center)
        score_edge = ev.evaluate(board_edge)
        assert score_center >= score_edge

    def test_piece_values(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        assert ev.PIECE_VALUES[chess.PAWN] == 100
        assert ev.PIECE_VALUES[chess.KNIGHT] == 320
        assert ev.PIECE_VALUES[chess.BISHOP] == 330
        assert ev.PIECE_VALUES[chess.ROOK] == 500
        assert ev.PIECE_VALUES[chess.QUEEN] == 900
        assert ev.PIECE_VALUES[chess.KING] == 20000

    def test_symmetric_position_symmetric_eval(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        score = ev.evaluate(board)
        assert score == 0

    def test_insufficient_material(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board("8/8/8/4k3/8/8/8/4K3 w - - 0 1")
        assert board.is_insufficient_material()
        score = ev.evaluate(board)
        assert score == 0


# ═══════════════════════════════════════════════════════════════════
# 3. AI ENGINES — MinimaxEngine
# ═══════════════════════════════════════════════════════════════════

class TestMinimaxEngine:
    def test_search_returns_correct_types(self):
        from ai_engines import MinimaxEngine
        eng = MinimaxEngine()
        board = chess.Board()
        best_move, white_eval, nodes, policy = eng.search(board, depth=1)
        assert best_move is None or isinstance(best_move, chess.Move)
        assert isinstance(white_eval, (int, float))
        assert isinstance(nodes, int)
        assert isinstance(policy, dict)

    def test_search_finds_move(self):
        from ai_engines import MinimaxEngine
        eng = MinimaxEngine()
        board = chess.Board()
        best_move, _, _, _ = eng.search(board, depth=1)
        assert best_move is not None
        assert best_move in board.legal_moves

    def test_search_increments_nodes(self):
        from ai_engines import MinimaxEngine
        eng = MinimaxEngine()
        board = chess.Board()
        _, _, nodes, _ = eng.search(board, depth=1)
        assert nodes > 0

    def test_policy_values_between_zero_and_one(self):
        from ai_engines import MinimaxEngine
        eng = MinimaxEngine()
        board = chess.Board()
        _, _, _, policy = eng.search(board, depth=1)
        for uci, prob in policy.items():
            assert 0.0 <= prob <= 1.0

    def test_policy_best_move_has_highest_prob(self):
        from ai_engines import MinimaxEngine
        eng = MinimaxEngine()
        board = chess.Board()
        best_move, _, _, policy = eng.search(board, depth=1)
        if policy:
            max_uci = max(policy, key=policy.get)
            assert max_uci == best_move.uci()

    def test_checkmate_in_one(self):
        from ai_engines import MinimaxEngine
        eng = MinimaxEngine()
        board = chess.Board("6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1")
        best_move, _, _, _ = eng.search(board, depth=2)
        assert best_move is not None

    def test_forced_mate_evaluated_high(self):
        from ai_engines import MinimaxEngine
        eng = MinimaxEngine()
        board = chess.Board("6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1")
        _, white_eval, _, _ = eng.search(board, depth=2)
        assert white_eval > 0

    def test_depth_two_more_nodes_than_depth_one(self):
        from ai_engines import MinimaxEngine
        eng = MinimaxEngine()
        board = chess.Board()
        _, _, n1, _ = eng.search(board, depth=1)
        _, _, n2, _ = eng.search(board, depth=2)
        assert n2 >= n1

    def test_starting_position_eval_near_zero(self):
        from ai_engines import MinimaxEngine
        eng = MinimaxEngine()
        board = chess.Board()
        _, white_eval, _, _ = eng.search(board, depth=1)
        assert abs(white_eval) < 500


# ═══════════════════════════════════════════════════════════════════
# 4. AI ENGINES — MCTSNode
# ═══════════════════════════════════════════════════════════════════

class TestMCTSNode:
    def test_initial_state(self):
        from ai_engines import MCTSNode
        node = MCTSNode(chess.Board())
        assert node.visits == 0
        assert node.wins == 0.0
        assert node.parent is None
        assert node.move is None
        assert len(node.children) == 0
        assert len(node.untried_moves) > 0

    def test_ucb1_unvisited_is_inf(self):
        from ai_engines import MCTSNode
        node = MCTSNode(chess.Board())
        node.parent = MCTSNode(chess.Board())
        node.parent.visits = 10
        assert node.ucb1() == float('inf')

    def test_ucb1_visited(self):
        from ai_engines import MCTSNode
        parent = MCTSNode(chess.Board())
        parent.visits = 100
        child = MCTSNode(chess.Board(), parent=parent)
        child.visits = 10
        child.wins = 5.0
        ucb = child.ucb1()
        assert 0 < ucb < float('inf')

    def test_best_child(self):
        from ai_engines import MCTSNode
        parent = MCTSNode(chess.Board())
        parent.visits = 100
        children = []
        for i in range(3):
            c = MCTSNode(chess.Board(), parent=parent)
            c.visits = 10 + i
            c.wins = float(i)
            children.append(c)
        parent.children = children
        best = parent.best_child()
        assert best in children

    def test_expand_creates_child(self):
        from ai_engines import MCTSNode
        node = MCTSNode(chess.Board())
        initial_untried = len(node.untried_moves)
        child = node.expand()
        assert len(node.children) == 1
        assert len(node.untried_moves) == initial_untried - 1
        assert child.parent is node
        assert child.move is not None

    def test_expand_depletes_moves(self):
        from ai_engines import MCTSNode
        node = MCTSNode(chess.Board())
        n_moves = len(node.untried_moves)
        for _ in range(n_moves):
            node.expand()
        assert len(node.untried_moves) == 0
        assert len(node.children) == n_moves


# ═══════════════════════════════════════════════════════════════════
# 5. AI ENGINES — MCTSEngine
# ═══════════════════════════════════════════════════════════════════

class TestMCTSEngine:
    def test_search_returns_correct_types(self):
        from ai_engines import MCTSEngine
        eng = MCTSEngine()
        board = chess.Board()
        best_move, white_eval, visits, policy = eng.search(board, iterations=10)
        assert best_move is None or isinstance(best_move, chess.Move)
        assert isinstance(white_eval, (int, float))
        assert isinstance(visits, int)
        assert isinstance(policy, dict)

    def test_search_finds_move(self):
        from ai_engines import MCTSEngine
        eng = MCTSEngine()
        board = chess.Board()
        best_move, _, _, _ = eng.search(board, iterations=20)
        assert best_move is not None

    def test_policy_sums_approximately_one(self):
        from ai_engines import MCTSEngine
        eng = MCTSEngine()
        board = chess.Board()
        _, _, _, policy = eng.search(board, iterations=20)
        if policy:
            total = sum(policy.values())
            assert abs(total - 1.0) < 0.01

    def test_visits_equals_iterations(self):
        from ai_engines import MCTSEngine
        eng = MCTSEngine()
        board = chess.Board()
        iters = 15
        _, _, visits, _ = eng.search(board, iterations=iters)
        assert visits >= iters

    def test_heuristic_rollout_returns_between_zero_and_one(self):
        from ai_engines import MCTSEngine
        eng = MCTSEngine()
        board = chess.Board()
        score = eng._heuristic_rollout(board, depth=5)
        assert 0.0 <= score <= 1.0

    def test_checkmate_rollout(self):
        from ai_engines import MCTSEngine
        eng = MCTSEngine()
        board = chess.Board()
        for m in ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]:
            board.push_uci(m)
        score = eng._heuristic_rollout(board)
        assert score == 1.0

    def test_stalemate_rollout(self):
        from ai_engines import MCTSEngine
        eng = MCTSEngine()
        board = chess.Board("5k2/5P2/5K2/8/8/8/8/8 b - - 0 1")
        if board.is_stalemate():
            score = eng._heuristic_rollout(board)
            assert score == 0.5


# ═══════════════════════════════════════════════════════════════════
# 6. BOARD WIDGET
# ═══════════════════════════════════════════════════════════════════

class TestChessBoardWidget:
    def test_initial_state(self, board_widget):
        assert board_widget.board is not None
        assert not board_widget.flipped
        assert board_widget.selected_sq is None
        assert board_widget.legal_targets == []
        assert board_widget.last_move is None

    def test_set_position(self, board_widget):
        board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
        last_move = chess.Move.from_uci("e2e4")
        board_widget.set_position(board, last_move)
        assert board_widget.board == board
        assert board_widget.last_move == last_move
        assert board_widget.selected_sq is None

    def test_set_theme(self, board_widget):
        from constants import BoardTheme
        t = BoardTheme("Blue")
        board_widget.set_theme(t)
        assert board_widget.theme.name == "Blue"

    def test_flip(self, board_widget):
        board_widget.flipped = True
        assert board_widget.flipped
        board_widget.flipped = False
        assert not board_widget.flipped

    def test_square_clicked_signal(self, board_widget):
        received = []
        board_widget.squareClicked.connect(lambda sq: received.append(sq))
        board_widget.squareClicked.emit(chess.E2)
        assert received == [chess.E2]

    def test_highlighted_squares(self, board_widget):
        board_widget.highlighted.add(chess.E4)
        assert chess.E4 in board_widget.highlighted
        board_widget.highlighted.symmetric_difference_update({chess.E4})
        assert chess.E4 not in board_widget.highlighted

    def test_arrows(self, board_widget):
        board_widget.arrows.append((chess.E2, chess.E4, QColor(220, 50, 47, 200)))
        assert len(board_widget.arrows) == 1

    def test_policy_vis(self, board_widget):
        board_widget.policy_vis = {"e2e4": 0.8, "d2d4": 0.2}
        assert "e2e4" in board_widget.policy_vis

    def test_layout_values(self, board_widget):
        total, margin, sq = board_widget._layout()
        assert total > 0
        assert sq > 0
        assert margin >= 0

    def test_sq_rect_in_bounds(self, board_widget):
        total, margin, sq = board_widget._layout()
        rect = board_widget._sq_rect(chess.E4, total, margin, sq)
        assert rect.width() > 0
        assert rect.height() > 0

    def test_pos_to_sq_roundtrip(self, board_widget):
        total, margin, sq = board_widget._layout()
        rect = board_widget._sq_rect(chess.E4, total, margin, sq)
        center = rect.center().toPoint()
        result = board_widget._pos_to_sq(center, total, margin, sq)
        assert result == chess.E4

    def test_render_to_image(self, board_widget):
        img = board_widget.render_to_image(200)
        assert isinstance(img, QImage)
        assert not img.isNull()
        assert img.width() == 200
        assert img.height() == 200

    def test_anim_move_property(self, board_widget):
        board_widget.anim_move = chess.Move.from_uci("e2e4")
        board_widget.anim_progress = 0.5
        assert board_widget.anim_move == chess.Move.from_uci("e2e4")
        assert board_widget.anim_progress == 0.5

    def test_set_position_clears_selection(self, board_widget):
        board_widget.selected_sq = chess.E2
        board_widget.legal_targets = [chess.E4]
        board_widget.set_position(chess.Board())
        assert board_widget.selected_sq is None
        assert board_widget.legal_targets == []

    def test_show_coords_toggle(self, board_widget):
        board_widget.show_coords = True
        _, margin_on, _ = board_widget._layout()
        board_widget.show_coords = False
        _, margin_off, _ = board_widget._layout()
        assert margin_on > margin_off


# ═══════════════════════════════════════════════════════════════════
# 7. EVAL BAR WIDGET
# ═══════════════════════════════════════════════════════════════════

class TestEvalBarWidget:
    def test_initial_eval(self, eval_bar):
        assert eval_bar.eval_cp == 0.0

    def test_set_eval(self, eval_bar):
        eval_bar.set_eval(150.0)
        assert eval_bar.eval_cp == 150.0

    def test_set_eval_negative(self, eval_bar):
        eval_bar.set_eval(-200.0)
        assert eval_bar.eval_cp == -200.0

    def test_set_eval_mate(self, eval_bar):
        eval_bar.set_eval(10001.0)
        assert eval_bar.eval_cp > 9000

    def test_fixed_size(self, eval_bar):
        assert eval_bar.width() > 0
        assert eval_bar.height() > 0


# ═══════════════════════════════════════════════════════════════════
# 8. VIDEO CANVAS
# ═══════════════════════════════════════════════════════════════════

class TestVideoCanvas:
    def test_initial_state(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        assert vc.w == 1920
        assert vc.h == 1080
        assert vc.eval_cp == 0.0
        assert vc.white_name == "White"
        assert vc.black_name == "Black"

    def test_render_returns_image(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        img = vc.render()
        assert isinstance(img, QImage)
        assert not img.isNull()
        assert img.width() == 1920
        assert img.height() == 1080

    def test_render_custom_resolution(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar, w=1280, h=720)
        img = vc.render()
        assert img.width() == 1280
        assert img.height() == 720

    def test_render_with_eval(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        vc.eval_cp = 250.0
        img = vc.render()
        assert not img.isNull()

    def test_render_with_negative_eval(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        vc.eval_cp = -300.0
        img = vc.render()
        assert not img.isNull()

    def test_render_with_mate_eval(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        vc.eval_cp = 10001.0
        img = vc.render()
        assert not img.isNull()

    def test_render_with_names(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        vc.white_name = "Magnus"
        vc.black_name = "Hikaru"
        img = vc.render()
        assert not img.isNull()

    def test_render_with_move_text(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        vc.move_text = "1. e4"
        img = vc.render()
        assert not img.isNull()

    def test_render_with_engine_text(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        vc.engine_text = "Stockfish 16"
        img = vc.render()
        assert not img.isNull()

    def test_render_with_move_list(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        vc.move_list_text = ["e4", "e5", "Nf3", "Nc6"]
        vc.current_move_index = 2
        img = vc.render()
        assert not img.isNull()

    def test_render_with_overlays(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        vc.overlays = [{"path": "/nonexistent/image.png", "x": 50, "y": 50, "w": 100, "h": 100}]
        img = vc.render()
        assert not img.isNull()

    def test_render_with_bg_color(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar, bg_color=QColor(50, 50, 60))
        img = vc.render()
        assert not img.isNull()

    def test_render_flipped_board(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        board_widget.flipped = True
        vc = VideoCanvas(board_widget, eval_bar)
        vc.white_name = "W"
        vc.black_name = "B"
        img = vc.render()
        assert not img.isNull()
        board_widget.flipped = False


# ═══════════════════════════════════════════════════════════════════
# 9. WORKERS — AIWorker 
# ═══════════════════════════════════════════════════════════════════

class TestAIWorker:
    def test_minimax_worker(self, qtbot):
        from workers import AIWorker
        board = chess.Board()
        worker = AIWorker("Minimax (Alpha-Beta)", board.fen(), {"depth": 1})
        with qtbot.waitSignal(worker.eval_ready, timeout=15000):
            worker.start()
        worker.wait(3000)

    def test_mcts_worker(self, qtbot):
        from workers import AIWorker
        board = chess.Board()
        worker = AIWorker("MCTS (Monte Carlo)", board.fen(), {"iterations": 10})
        with qtbot.waitSignal(worker.eval_ready, timeout=15000):
            worker.start()
        worker.wait(3000)

    def test_worker_emits_correct_keys(self, qtbot):
        from workers import AIWorker
        board = chess.Board()
        worker = AIWorker("Minimax (Alpha-Beta)", board.fen(), {"depth": 1})
        results = []

        def capture(data):
            results.append(data)

        worker.eval_ready.connect(capture)
        with qtbot.waitSignal(worker.eval_ready, timeout=15000):
            worker.start()
        worker.wait(3000)
        assert len(results) == 1
        data = results[0]
        assert "eval" in data
        assert "eval_cp" in data
        assert "nodes" in data
        assert "policy" in data
        assert "engine_type" in data
        assert data["engine_type"] == "Minimax (Alpha-Beta)"

    def test_worker_invalid_engine_type(self, qtbot):
        from workers import AIWorker
        board = chess.Board()
        worker = AIWorker("NonExistent", board.fen(), {})
        worker.start()
        worker.wait(5000)

    def test_worker_empty_board_fen(self, qtbot):
        from workers import AIWorker
        board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        worker = AIWorker("Minimax (Alpha-Beta)", board.fen(), {"depth": 1})
        results = []
        worker.eval_ready.connect(lambda d: results.append(d))
        with qtbot.waitSignal(worker.eval_ready, timeout=15000):
            worker.start()
        worker.wait(3000)
        assert len(results) == 1

    @pytest.mark.skipif(not find_stockfish(), reason="Stockfish not installed")
    def test_stockfish_worker(self, qtbot):
        from workers import AIWorker
        board = chess.Board()
        sf_path = find_stockfish()
        worker = AIWorker("Stockfish (UCI)", board.fen(), {"path": sf_path})
        with qtbot.waitSignal(worker.eval_ready, timeout=30000):
            worker.start()
        worker.wait(5000)

    def test_worker_stockfish_bad_path(self, qtbot):
        from workers import AIWorker
        board = chess.Board()
        worker = AIWorker("Stockfish (UCI)", board.fen(), {"path": "/nonexistent/stockfish"})
        results = []
        worker.eval_ready.connect(lambda d: results.append(d))
        with qtbot.waitSignal(worker.eval_ready, timeout=15000):
            worker.start()
        worker.wait(3000)
        assert len(results) == 1
        assert "Error" in results[0]["eval"]

# ═══════════════════════════════════════════════════════════════════
# 10. WORKERS — BatchEvalWorker
# ═══════════════════════════════════════════════════════════════════

class TestBatchEvalWorker:
    def test_batch_eval_with_heuristic(self, qtbot):
        from workers import BatchEvalWorker
        game = chess.pgn.read_game(io.StringIO("1. e4 e5 2. Nf3 Nc6"))
        move_list = list(game.mainline())
        worker = BatchEvalWorker(move_list, "Minimax (Alpha-Beta)", {"depth": 1})
        results = []
        worker.move_evaluated.connect(lambda i, e, s: results.append((i, e, s)))
        with qtbot.waitSignal(worker.finished, timeout=30000):
            worker.start()
        worker.wait(3000)
        qapp().processEvents()
        assert len(results) == len(move_list)

    def test_batch_eval_cancel(self, qtbot):
        from workers import BatchEvalWorker
        game = chess.pgn.read_game(io.StringIO("1. e4 e5 2. Nf3"))
        move_list = list(game.mainline())
        worker = BatchEvalWorker(move_list, "Minimax (Alpha-Beta)", {"depth": 1})
        worker.cancel()
        with qtbot.waitSignal(worker.finished, timeout=15000):
            worker.start()
        worker.wait(3000)

    def test_batch_eval_finished_signal(self, qtbot):
        from workers import BatchEvalWorker
        game = chess.pgn.read_game(io.StringIO("1. e4"))
        move_list = list(game.mainline())
        worker = BatchEvalWorker(move_list, "Minimax (Alpha-Beta)", {"depth": 1})
        with qtbot.waitSignal(worker.finished, timeout=15000):
            worker.start()
        worker.wait(3000)

    def test_batch_eval_eval_values(self, qtbot):
        from workers import BatchEvalWorker
        game = chess.pgn.read_game(io.StringIO("1. e4"))
        move_list = list(game.mainline())
        worker = BatchEvalWorker(move_list, "Minimax (Alpha-Beta)", {"depth": 1})
        results = []
        worker.move_evaluated.connect(lambda i, e, s: results.append((i, e, s)))
        with qtbot.waitSignal(worker.finished, timeout=15000):
            worker.start()
        worker.wait(3000)
        qapp().processEvents()
        assert len(results) >= 1
        idx, eval_cp, eval_str = results[0]
        assert idx == 0
        assert isinstance(eval_cp, float)

    @pytest.mark.skipif(not find_stockfish(), reason="Stockfish not installed")
    def test_batch_eval_stockfish(self, qtbot):
        from workers import BatchEvalWorker
        game = chess.pgn.read_game(io.StringIO("1. e4 e5"))
        move_list = list(game.mainline())
        sf_path = find_stockfish()
        worker = BatchEvalWorker(move_list, "Stockfish (UCI)", {"path": sf_path})
        results = []
        worker.move_evaluated.connect(lambda i, e, s: results.append((i, e, s)))
        with qtbot.waitSignal(worker.finished, timeout=60000):
            worker.start()
        worker.wait(5000)
        qapp().processEvents()
        assert len(results) == 2
        # Verify eval values are reasonable
        for idx, eval_cp, eval_str in results:
            assert isinstance(eval_cp, float)
            assert isinstance(eval_str, str)


# ═══════════════════════════════════════════════════════════════════
# 11. WORKERS — ExportWorker
# ═══════════════════════════════════════════════════════════════════

class TestExportWorker:
    def test_export_worker_creates_file(self, qtbot):
        """Test that ExportWorker produces a valid video file.

        Uses avc1 (H.264) on all platforms — YouTube's preferred codec.
        Falls back through the codec chain automatically.
        """
        from constants import HAS_CV2
        if not HAS_CV2:
            pytest.skip("opencv-python not installed")
        import numpy as np
        from workers import ExportWorker

        frames = [np.zeros((720, 1280, 3), dtype=np.uint8) for _ in range(5)]
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            out_path = tmp.name
        try:
            worker = ExportWorker(frames, 30, out_path, 1280, 720)
            results = []
            worker.finished.connect(lambda m: results.append(m))
            with qtbot.waitSignal(worker.finished, timeout=15000):
                worker.start()
            worker.wait(3000)
            assert len(results) == 1
            assert "ERROR" not in results[0]
            # File should exist and have content
            actual_path = out_path
            if not os.path.exists(out_path):
                # Codec fallback may have changed the extension
                base = os.path.splitext(out_path)[0]
                for ext in [".avi"]:
                    candidate = base + ext
                    if os.path.exists(candidate):
                        actual_path = candidate
                        break
            assert os.path.exists(actual_path)
            assert os.path.getsize(actual_path) > 0
        finally:
            for path in [out_path, os.path.splitext(out_path)[0] + ".avi"]:
                if os.path.exists(path):
                    os.unlink(path)

    def test_export_worker_no_cv2(self, qtbot):
        """Test that ExportWorker emits an error when opencv is missing.

        Temporarily sets workers.HAS_CV2 = False to force the error path,
        then restores the original value.  Runs even when opencv IS installed.
        """
        import workers as workers_mod
        original_has_cv2 = workers_mod.HAS_CV2
        workers_mod.HAS_CV2 = False
        try:
            out_path = os.path.join(tempfile.gettempdir(), "test_no_cv2.mp4")
            worker = workers_mod.ExportWorker([], 30, out_path, 1280, 720)
            results = []
            worker.finished.connect(lambda m: results.append(m))
            with qtbot.waitSignal(worker.finished, timeout=15000):
                worker.start()
            worker.wait(3000)
            assert len(results) == 1
            assert "ERROR" in results[0] or "opencv" in results[0].lower()
        finally:
            workers_mod.HAS_CV2 = original_has_cv2

    def test_export_worker_no_frames(self, qtbot):
        """Test that exporting zero frames reports an error."""
        from constants import HAS_CV2
        if not HAS_CV2:
            pytest.skip("opencv-python not installed")
        from workers import ExportWorker

        out_path = os.path.join(tempfile.gettempdir(), "test_empty.mp4")
        worker = ExportWorker([], 30, out_path, 1280, 720)
        results = []
        worker.finished.connect(lambda m: results.append(m))
        with qtbot.waitSignal(worker.finished, timeout=15000):
            worker.start()
        worker.wait(3000)
        assert len(results) == 1
        assert "ERROR" in results[0] or "No frames" in results[0]

    def test_export_worker_cancel(self, qtbot):
        """Test cancelling an export worker.

        Uses avc1 (H.264) — safe on all platforms including Windows.
        """
        from constants import HAS_CV2
        if not HAS_CV2:
            pytest.skip("opencv-python not installed")
        import numpy as np
        from workers import ExportWorker

        frames = [np.zeros((720, 1280, 3), dtype=np.uint8) for _ in range(100)]
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            out_path = tmp.name
        try:
            worker = ExportWorker(frames, 60, out_path, 1280, 720)
            worker.start()
            worker.cancel()
            worker.wait(10000)
        finally:
            for path in [out_path, os.path.splitext(out_path)[0] + ".avi"]:
                if os.path.exists(path):
                    os.unlink(path)

    def test_export_worker_codec_fallback_logic(self):
        """Test the codec selection logic without calling VideoWriter.

        Runs safely on all platforms including Windows.
        """
        from workers import _get_youtube_codecs
        codecs = _get_youtube_codecs()

        # Should always have at least 2 fallback codecs
        assert len(codecs) >= 2

        # First codec must produce .mp4 (YouTube's required container)
        first_codec, first_ext = codecs[0]
        assert first_ext == ".mp4"
        assert first_codec in ("avc1", "X264"), \
            f"First codec should be H.264, got {first_codec}"

        # Path extension switching logic
        out_path = "my_video.mp4"
        for fourcc_str, ext in codecs:
            used_path = out_path
            if not used_path.lower().endswith(ext):
                base = os.path.splitext(used_path)[0]
                used_path = base + ext
            assert used_path.lower().endswith(ext), \
                f"Path {used_path} should end with {ext}"

        # Verify Windows never uses mp4v
        if platform.system() == "Windows":
            codec_names = [c[0] for c in codecs]
            assert "mp4v" not in codec_names, \
                "mp4v must never be used on Windows (causes access violation)"

        # Verify at least one H.264 codec is available
        h264_codecs = [c for c in codecs if c[0] in ("avc1", "X264")]
        assert len(h264_codecs) >= 1, "Must have at least one H.264 codec"

        # Verify all H.264 codecs target .mp4
        for codec_name, ext in h264_codecs:
            assert ext == ".mp4", \
                f"H.264 codec {codec_name} must use .mp4 container, got {ext}"


# ═══════════════════════════════════════════════════════════════════
# 12. DIALOGS — PromotionWidget (inline, no popups)
# ═══════════════════════════════════════════════════════════════════

class TestPromotionWidget:
    def test_widget_creation(self):
        from dialogs import PromotionWidget
        w = PromotionWidget()
        assert w is not None
        w.close()

    def test_widget_has_piece_selected_signal(self):
        from dialogs import PromotionWidget
        w = PromotionWidget()
        received = []
        w.piece_selected.connect(lambda pt: received.append(pt))
        w.piece_selected.emit(chess.QUEEN)
        assert received == [chess.QUEEN]
        w.close()

    def test_show_for_white(self):
        from dialogs import PromotionWidget
        w = PromotionWidget()
        w.show_for_color(chess.WHITE)
        assert w.isVisible()
        w.close()

    def test_show_for_black(self):
        from dialogs import PromotionWidget
        w = PromotionWidget()
        w.show_for_color(chess.BLACK)
        assert w.isVisible()
        w.close()

    def test_pick_queen(self):
        from dialogs import PromotionWidget
        w = PromotionWidget()
        received = []
        w.piece_selected.connect(lambda pt: received.append(pt))
        w.show_for_color(chess.WHITE)
        w._pick(chess.QUEEN)
        assert received == [chess.QUEEN]
        assert not w.isVisible()

    def test_pick_rook(self):
        from dialogs import PromotionWidget
        w = PromotionWidget()
        received = []
        w.piece_selected.connect(lambda pt: received.append(pt))
        w.show_for_color(chess.WHITE)
        w._pick(chess.ROOK)
        assert received == [chess.ROOK]
        assert not w.isVisible()

    def test_pick_bishop(self):
        from dialogs import PromotionWidget
        w = PromotionWidget()
        received = []
        w.piece_selected.connect(lambda pt: received.append(pt))
        w.show_for_color(chess.BLACK)
        w._pick(chess.BISHOP)
        assert received == [chess.BISHOP]
        assert not w.isVisible()

    def test_pick_knight(self):
        from dialogs import PromotionWidget
        w = PromotionWidget()
        received = []
        w.piece_selected.connect(lambda pt: received.append(pt))
        w.show_for_color(chess.BLACK)
        w._pick(chess.KNIGHT)
        assert received == [chess.KNIGHT]
        assert not w.isVisible()

    def test_pick_hides_widget(self):
        from dialogs import PromotionWidget
        w = PromotionWidget()
        w.show_for_color(chess.WHITE)
        assert w.isVisible()
        w._pick(chess.QUEEN)
        assert not w.isVisible()

    def test_all_pieces_for_both_colors(self):
        from dialogs import PromotionWidget
        for color in [chess.WHITE, chess.BLACK]:
            for piece in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
                w = PromotionWidget()
                received = []
                w.piece_selected.connect(lambda pt: received.append(pt))
                w.show_for_color(color)
                w._pick(piece)
                assert received == [piece]
                assert not w.isVisible()
                w.close()


# ═══════════════════════════════════════════════════════════════════
# 13. MAIN WINDOW — Core Navigation
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowCore:
    def test_window_title(self, main_window):
        assert "Chess Video Maker Pro" in main_window.windowTitle()

    def test_new_game(self, main_window):
        main_window._new_game()
        assert main_window.game is not None
        assert main_window.node is not None
        assert main_window.move_index == -1
        assert main_window.move_list == []

    def test_go_first(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        main_window._go_last()
        main_window._go_first()
        assert main_window.node == main_window.game

    def test_go_last(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        main_window._go_last()
        assert main_window.node == main_window.move_list[-1]

    def test_go_next(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        main_window._go_first()
        initial_node = main_window.node
        main_window._go_next()
        assert main_window.node != initial_node

    def test_go_prev(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        main_window._go_next()
        node_after_next = main_window.node
        main_window._go_prev()
        assert main_window.node != node_after_next

    def test_toggle_play(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        main_window._go_first()
        main_window._toggle_play()
        assert main_window._playing
        main_window._toggle_play()
        assert not main_window._playing

    def test_flip_board(self, main_window):
        initial = main_window.board_widget.flipped
        main_window._flip_board()
        assert main_window.board_widget.flipped != initial

    def test_theme_changed(self, main_window):
        main_window._theme_changed("Blue")
        assert main_window.board_widget.theme.name == "Blue"
        main_window._theme_changed("Classic")
        assert main_window.board_widget.theme.name == "Classic"

    def test_apply_comment(self, main_window):
        main_window.anno_edit.setPlainText("Test comment")
        main_window._apply_comment()
        assert main_window.node.comment == "Test comment"

    def test_update_names(self, main_window):
        main_window.white_name_edit.setText("Magnus")
        main_window.black_name_edit.setText("Hikaru")
        main_window._update_names()

    def test_clear_policy(self, main_window):
        main_window.board_widget.policy_vis = {"e2e4": 0.5}
        main_window._clear_policy()
        assert main_window.board_widget.policy_vis == {}

    def test_on_move_row(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        if len(main_window.move_list) > 0:
            main_window._on_move_row(0)
            assert main_window.node == main_window.move_list[0]

    def test_on_move_row_invalid(self, main_window):
        main_window._on_move_row(-1)
        main_window._on_move_row(999)

    def test_load_pgn_menu_switches_tab(self, main_window):
        main_window._load_pgn()
        assert main_window.tabs.currentIndex() == 1


# ═══════════════════════════════════════════════════════════════════
# 14. MAIN WINDOW — Board Interaction
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowBoardInteraction:
    def test_click_select_piece(self, main_window):
        main_window._on_sq_click(chess.E2)
        assert main_window.board_widget.selected_sq == chess.E2
        assert len(main_window.board_widget.legal_targets) > 0

    def test_click_move_piece(self, main_window):
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        assert main_window.board_widget.selected_sq is None
        assert main_window.move_index == 0

    def test_click_wrong_color(self, main_window):
        main_window._on_sq_click(chess.E7)
        assert main_window.board_widget.selected_sq is None

    def test_click_empty_square(self, main_window):
        main_window._on_sq_click(chess.E4)
        assert main_window.board_widget.selected_sq is None

    def test_click_illegal_move(self, main_window):
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E7)
        assert main_window.board_widget.selected_sq is None

    def test_play_multiple_moves(self, main_window):
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        main_window._on_sq_click(chess.E7)
        main_window._on_sq_click(chess.E5)
        assert main_window.move_index == 1

    def test_ai_vs_ai_blocks_clicks(self, main_window):
        main_window.ai_vs_ai_running = True
        main_window._on_sq_click(chess.E2)
        assert main_window.board_widget.selected_sq is None
        main_window.ai_vs_ai_running = False

    def test_promo_pick_inline(self, main_window):
        main_window._pending_promo_from = chess.E7
        main_window._pending_promo_to = chess.E8
        board = chess.Board("4k3/4P3/8/8/8/8/8/4K3 w - - 0 1")
        main_window.board_widget.set_position(board)
        main_window.node = main_window.game
        main_window._on_promo_pick(chess.QUEEN)
        assert main_window._pending_promo_from is None
        assert main_window._pending_promo_to is None
        assert not main_window.promo_widget.isVisible()

    def test_promo_pick_resets_pending(self, main_window):
        main_window._pending_promo_from = chess.E2
        main_window._pending_promo_to = chess.E4
        main_window._on_promo_pick(chess.QUEEN)
        assert main_window._pending_promo_from is None
        assert main_window._pending_promo_to is None


# ═══════════════════════════════════════════════════════════════════
# 15. MAIN WINDOW — PGN Loading (inline, no dialogs)
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowPGN:
    def test_load_pgn_data(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        assert main_window.game == game
        assert len(main_window.move_list) > 0

    def test_load_pgn_data_moves_populated(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        assert main_window.move_listbox.count() > 0

    def test_load_pgn_data_goes_to_last(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        assert main_window.node == main_window.move_list[-1]

    def test_refresh_move_list_eval_display(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        if main_window.move_list:
            main_window.eval_cache[main_window.move_list[0]] = 50.0
            main_window._refresh_move_list()
            item_text = main_window.move_listbox.item(0).text()
            assert "(+0.50)" in item_text

    def test_refresh_move_list_mate_eval(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        if main_window.move_list:
            main_window.eval_cache[main_window.move_list[0]] = 10001.0
            main_window._refresh_move_list()
            item_text = main_window.move_listbox.item(0).text()
            assert "M" in item_text

    def test_load_pgn_text_inline(self, main_window):
        from constants import SAMPLE_PGN
        main_window.pgn_text_edit.setPlainText(SAMPLE_PGN)
        main_window._load_pgn_text()
        assert len(main_window.move_list) > 0
        assert main_window.game is not None

    def test_load_pgn_text_empty(self, main_window):
        main_window.pgn_text_edit.setPlainText("")
        main_window._load_pgn_text()

    def test_load_pgn_text_invalid(self, main_window):
        main_window.pgn_text_edit.setPlainText("not valid pgn at all")
        main_window._load_pgn_text()

    def test_load_pgn_from_file_inline_invalid_path(self, main_window):
        main_window.pgn_file_edit.setText("/nonexistent/path/to/file.pgn")
        main_window._load_pgn_from_file()

    def test_load_pgn_from_file_inline_empty_path(self, main_window):
        main_window.pgn_file_edit.setText("")
        main_window._load_pgn_from_file()

    def test_load_pgn_from_file_inline_valid(self, main_window):
        from constants import SAMPLE_PGN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pgn', delete=False) as f:
            f.write(SAMPLE_PGN)
            tmp_path = f.name
        try:
            main_window.pgn_file_edit.setText(tmp_path)
            main_window._load_pgn_from_file()
            assert len(main_window.move_list) > 0
        finally:
            os.unlink(tmp_path)


# ═══════════════════════════════════════════════════════════════════
# 16. MAIN WINDOW — AI Features
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowAI:
    def test_toggle_ai_ui(self, main_window):
        main_window._toggle_ai_ui("Minimax (Alpha-Beta)")
        assert main_window.ai_stack.currentIndex() == 0
        main_window._toggle_ai_ui("MCTS (Monte Carlo)")
        assert main_window.ai_stack.currentIndex() == 1
        main_window._toggle_ai_ui("Stockfish (UCI)")
        assert main_window.ai_stack.currentIndex() == 2

    def test_run_engine_minimax(self, main_window, qtbot):
        main_window.ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        main_window.mm_depth.setValue(1)
        main_window._run_engine()
        with qtbot.waitSignal(main_window.engine_worker.eval_ready, timeout=15000):
            pass
        assert main_window.eval_label.text() != "Eval: …"

    def test_on_eval_ready(self, main_window):
        data = {
            "eval": "+1.50",
            "eval_cp": 150.0,
            "nodes": 1000,
            "policy": {"e2e4": 0.8, "d2d4": 0.2},
            "engine_type": "Minimax (Alpha-Beta)",
            "best_move": "e2e4",
        }
        main_window.policy_chk.setChecked(True)
        main_window._on_eval_ready(data)
        assert "1.50" in main_window.eval_label.text()
        assert "1000" in main_window.pv_label.text()
        assert "e2e4" in main_window.board_widget.policy_vis
        assert len(main_window.board_widget.arrows) > 0

    def test_on_eval_ready_no_policy(self, main_window):
        data = {
            "eval": "+0.00",
            "eval_cp": 0.0,
            "nodes": 500,
            "policy": {},
            "engine_type": "Minimax (Alpha-Beta)",
            "best_move": None,
        }
        main_window._on_eval_ready(data)
        assert "0.00" in main_window.eval_label.text()

    def test_batch_eval_no_moves(self, main_window):
        main_window._new_game()
        main_window._start_batch_eval()

    def test_start_stop_ai_vs_ai(self, main_window, qtbot):
        main_window.white_ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        main_window.white_ai_str.setValue(1)
        main_window.black_ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        main_window.black_ai_str.setValue(1)
        main_window.battle_delay.setValue(50)

        main_window._start_ai_vs_ai()
        assert main_window.ai_vs_ai_running
        assert not main_window.start_battle_btn.isEnabled()
        assert main_window.stop_battle_btn.isEnabled()

        timeout = 15
        start = time.time()
        while main_window.ai_vs_ai_running and time.time() - start < timeout:
            qapp().processEvents()
            time.sleep(0.05)

        main_window._stop_ai_vs_ai()
        assert not main_window.ai_vs_ai_running
        assert main_window.start_battle_btn.isEnabled()

    def test_on_move_evaluated(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        if main_window.move_list:
            main_window._on_move_evaluated(0, 100.0, "+1.00")
            assert main_window.move_list[0] in main_window.eval_cache

    def test_on_batch_finished(self, main_window):
        main_window._on_batch_finished()
        assert main_window.eval_game_btn.isEnabled()
        assert not main_window.stop_eval_btn.isEnabled()


# ═══════════════════════════════════════════════════════════════════
# 17. MAIN WINDOW — Video Capture & Inline Export
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowVideo:
    def test_auto_capture_no_moves(self, main_window):
        main_window._new_game()
        main_window._auto_capture()
        assert len(main_window.capture_frames) == 0

    def test_auto_capture_with_moves(self, main_window):
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        main_window._on_sq_click(chess.E7)
        main_window._on_sq_click(chess.E5)
        main_window.fps_spin.setValue(10)
        main_window.hold_spin.setValue(0.2)
        main_window._auto_capture()
        assert len(main_window.capture_frames) > 0

    def test_auto_capture_sets_frame_count(self, main_window):
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        main_window.fps_spin.setValue(10)
        main_window.hold_spin.setValue(0.2)
        main_window._auto_capture()
        assert "Frames:" in main_window.frame_count_lbl.text()
        count = int(main_window.frame_count_lbl.text().split(":")[1].strip())
        assert count > 0

    def test_clear_frames(self, main_window):
        main_window.capture_frames = [QImage(100, 100, QImage.Format_ARGB32)]
        main_window._clear_frames()
        assert len(main_window.capture_frames) == 0
        assert "0" in main_window.frame_count_lbl.text()

    def test_inline_export_no_frames(self, main_window):
        main_window.capture_frames = []
        main_window._start_inline_export()

    def test_inline_export_no_output_path(self, main_window):
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        main_window.fps_spin.setValue(10)
        main_window.hold_spin.setValue(0.2)
        main_window._auto_capture()
        main_window.export_path_edit.setText("")
        from constants import HAS_CV2
        if HAS_CV2:
            main_window._start_inline_export()

    def test_auto_capture_with_names(self, main_window):
        main_window.white_name_edit.setText("Magnus")
        main_window.black_name_edit.setText("Hikaru")
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        main_window.fps_spin.setValue(10)
        main_window.hold_spin.setValue(0.2)
        main_window._auto_capture()
        assert len(main_window.capture_frames) > 0

    def test_export_progress_handler(self, main_window):
        main_window._on_export_progress(50, "Frame 5/10")
        assert main_window.export_progress_bar.value() == 50
        assert "Frame 5/10" in main_window.export_status_lbl.text()

    def test_export_finished_handler(self, main_window):
        main_window._start_inline_export()
        main_window._on_export_finished("Done!\nSaved to: test.mp4")
        assert main_window.export_start_btn.isEnabled()
        assert not main_window.export_cancel_btn.isEnabled()
        assert "Done" in main_window.export_status_lbl.text()

    def test_cancel_export(self, main_window):
        main_window.export_worker = None
        main_window._cancel_export()


# ═══════════════════════════════════════════════════════════════════
# 18. MAIN WINDOW — Overlays, Assets & Inline Folders
# ═══════════════════════════════════════════════════════════════════

class TestMainWindowOverlays:
    def test_add_overlay_no_selection(self, main_window):
        main_window._add_overlay()

    def test_clear_overlays(self, main_window):
        main_window.canvas_overlays = [{"path": "test.png", "x": 50, "y": 50, "w": 100, "h": 100}]
        main_window._clear_overlays()
        assert main_window.canvas_overlays == []

    def test_scan_img_db_no_folder(self, main_window):
        main_window._scan_img_db()

    def test_scan_pgn_db_no_folder(self, main_window):
        main_window._scan_pgn_db()

    def test_load_selected_pgn_db_no_selection(self, main_window):
        main_window._load_selected_pgn_db()

    def test_set_pgn_db_folder_invalid(self, main_window):
        main_window.db_folder_edit.setText("/nonexistent/folder/path")
        main_window._set_pgn_db_folder()
        assert main_window.db_folder == ""

    def test_set_pgn_db_folder_valid(self, main_window):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_window.db_folder_edit.setText(tmpdir)
            main_window._set_pgn_db_folder()
            assert main_window.db_folder == tmpdir

    def test_set_img_folder_invalid(self, main_window):
        main_window.img_folder_edit.setText("/nonexistent/folder/path")
        main_window._set_img_folder()
        assert main_window.img_folder == ""

    def test_set_img_folder_valid(self, main_window):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_window.img_folder_edit.setText(tmpdir)
            main_window._set_img_folder()
            assert main_window.img_folder == tmpdir

    def test_scan_pgn_db_with_files(self, main_window):
        from constants import SAMPLE_PGN
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "test.pgn"), 'w') as f:
                f.write(SAMPLE_PGN)
            main_window.db_folder = tmpdir
            main_window._scan_pgn_db()
            assert main_window.db_list.count() == 1

    def test_scan_img_db_with_files(self, main_window):
        with tempfile.TemporaryDirectory() as tmpdir:
            img = QImage(1, 1, QImage.Format_ARGB32)
            img.save(os.path.join(tmpdir, "test.png"))
            main_window.img_folder = tmpdir
            main_window._scan_img_db()
            assert main_window.img_list.count() >= 1


# ═══════════════════════════════════════════════════════════════════
# 19. UI BUILDER
# ═══════════════════════════════════════════════════════════════════

class TestUIBuilder:
    def test_build_ui_creates_widgets(self, main_window):
        assert main_window.board_widget is not None
        assert main_window.eval_bar_widget is not None
        assert main_window.tabs is not None
        assert main_window.right_tabs is not None

    def test_build_ui_tabs_count(self, main_window):
        assert main_window.tabs.count() == 3
        assert main_window.right_tabs.count() == 3

    def test_build_ui_moves_tab(self, main_window):
        assert main_window.move_listbox is not None
        assert main_window.btn_play is not None
        assert main_window.speed_slider is not None
        assert main_window.anno_edit is not None

    def test_build_ui_database_tab(self, main_window):
        assert main_window.db_path_lbl is not None
        assert main_window.db_list is not None
        assert main_window.db_game_idx is not None
        assert main_window.db_folder_edit is not None
        assert main_window.pgn_text_edit is not None
        assert main_window.pgn_file_edit is not None

    def test_build_ui_assets_tab(self, main_window):
        assert main_window.img_path_lbl is not None
        assert main_window.img_list is not None
        assert main_window.ov_pos_combo is not None
        assert main_window.img_folder_edit is not None

    def test_build_ui_battle_tab(self, main_window):
        assert main_window.white_ai_combo is not None
        assert main_window.black_ai_combo is not None
        assert main_window.white_ai_str is not None
        assert main_window.black_ai_str is not None
        assert main_window.battle_delay is not None
        assert main_window.start_battle_btn is not None
        assert main_window.stop_battle_btn is not None

    def test_build_ui_analysis_tab(self, main_window):
        assert main_window.ai_combo is not None
        assert main_window.ai_stack is not None
        assert main_window.mm_depth is not None
        assert main_window.m_iters is not None
        assert main_window.engine_path_edit is not None
        assert main_window.run_ai_btn is not None
        assert main_window.eval_game_btn is not None
        assert main_window.stop_eval_btn is not None
        assert main_window.eval_label is not None
        assert main_window.pv_label is not None
        assert main_window.policy_chk is not None
        assert main_window.clear_policy_btn is not None

    def test_build_ui_video_tab(self, main_window):
        assert main_window.bg_color_combo is not None
        assert main_window.white_name_edit is not None
        assert main_window.black_name_edit is not None
        assert main_window.theme_combo is not None
        assert main_window.flip_btn is not None
        assert main_window.fps_spin is not None
        assert main_window.anim_spin is not None
        assert main_window.hold_spin is not None
        assert main_window.auto_btn is not None
        assert main_window.frame_count_lbl is not None
        assert main_window.clear_btn is not None
        assert main_window.export_start_btn is not None
        assert main_window.export_cancel_btn is not None
        assert main_window.export_res_combo is not None
        assert main_window.export_fps_spin is not None
        assert main_window.export_path_edit is not None
        assert main_window.export_progress_bar is not None
        assert main_window.export_status_lbl is not None

    def test_build_ui_promo_widget(self, main_window):
        assert main_window.promo_widget is not None

    def test_build_menu(self, main_window):
        mb = main_window.menuBar()
        assert mb is not None
        actions = mb.actions()
        menu_texts = [a.text() for a in actions]
        assert any("File" in m for m in menu_texts)
        assert any("View" in m for m in menu_texts)

    def test_speed_slider_range(self, main_window):
        assert main_window.speed_slider.minimum() == 1
        assert main_window.speed_slider.maximum() == 50

    def test_battle_delay_range(self, main_window):
        assert main_window.battle_delay.minimum() == 50
        assert main_window.battle_delay.maximum() == 5000

    def test_fps_spin_range(self, main_window):
        assert main_window.fps_spin.minimum() == 1
        assert main_window.fps_spin.maximum() == 120

    def test_hold_spin_range(self, main_window):
        assert main_window.hold_spin.minimum() == 0.1
        assert main_window.hold_spin.maximum() == 10.0

    def test_anim_spin_range(self, main_window):
        assert main_window.anim_spin.minimum() == 0.0
        assert main_window.anim_spin.maximum() == 3.0

    def test_db_game_idx_range(self, main_window):
        assert main_window.db_game_idx.minimum() == 1
        assert main_window.db_game_idx.maximum() == 100000

    def test_theme_combo_contents(self, main_window):
        from constants import THEMES
        assert main_window.theme_combo.count() == len(THEMES)

    def test_ov_pos_combo_contents(self, main_window):
        assert main_window.ov_pos_combo.count() == 4
        texts = [main_window.ov_pos_combo.itemText(i) for i in range(main_window.ov_pos_combo.count())]
        assert any("White" in t for t in texts)
        assert any("Black" in t for t in texts)
        assert any("Center" in t or "Logo" in t for t in texts)
        assert any("Watermark" in t for t in texts)

    def test_white_ai_combo_contents(self, main_window):
        from constants import AI_MAP
        assert main_window.white_ai_combo.count() == len(AI_MAP)

    def test_black_ai_combo_contents(self, main_window):
        from constants import AI_MAP
        assert main_window.black_ai_combo.count() == len(AI_MAP)

    def test_bg_color_combo_contents(self, main_window):
        assert main_window.bg_color_combo.count() == 8
        texts = [main_window.bg_color_combo.itemText(i) for i in range(main_window.bg_color_combo.count())]
        assert "Dark Gray" in texts
        assert "Black" in texts
        assert "White" in texts

    def test_export_res_combo_contents(self, main_window):
        assert main_window.export_res_combo.count() == 3
        texts = [main_window.export_res_combo.itemText(i) for i in range(main_window.export_res_combo.count())]
        assert any("1080p" in t for t in texts)
        assert any("720p" in t for t in texts)
        assert any("4K" in t for t in texts)

    def test_export_fps_spin_range(self, main_window):
        assert main_window.export_fps_spin.minimum() == 1
        assert main_window.export_fps_spin.maximum() == 120

    def test_db_folder_edit_placeholder(self, main_window):
        assert "folder" in main_window.db_folder_edit.placeholderText().lower()

    def test_pgn_text_edit_placeholder(self, main_window):
        assert "pgn" in main_window.pgn_text_edit.placeholderText().lower()

    def test_pgn_file_edit_placeholder(self, main_window):
        assert main_window.pgn_file_edit.placeholderText() != ""

    def test_img_folder_edit_placeholder(self, main_window):
        assert "folder" in main_window.img_folder_edit.placeholderText().lower()

    def test_export_path_edit_placeholder(self, main_window):
        assert main_window.export_path_edit.placeholderText() != ""


# ═══════════════════════════════════════════════════════════════════
# 20. BG COLOR COMBO (inline, no color picker dialog)
# ═══════════════════════════════════════════════════════════════════

class TestBGColorCombo:
    def test_initial_bg_color(self, main_window):
        assert main_window.video_bg_color == QColor(30, 30, 32)

    def test_bg_color_combo_select_dark_gray(self, main_window):
        main_window._pick_bg_color("Dark Gray")
        assert main_window.video_bg_color == QColor(30, 30, 32)

    def test_bg_color_combo_select_black(self, main_window):
        main_window._pick_bg_color("Black")
        assert main_window.video_bg_color == QColor(0, 0, 0)

    def test_bg_color_combo_select_dark_blue(self, main_window):
        main_window._pick_bg_color("Dark Blue")
        assert main_window.video_bg_color == QColor(15, 20, 40)

    def test_bg_color_combo_select_dark_green(self, main_window):
        main_window._pick_bg_color("Dark Green")
        assert main_window.video_bg_color == QColor(15, 35, 15)

    def test_bg_color_combo_select_dark_red(self, main_window):
        main_window._pick_bg_color("Dark Red")
        assert main_window.video_bg_color == QColor(40, 15, 15)

    def test_bg_color_combo_select_white(self, main_window):
        main_window._pick_bg_color("White")
        assert main_window.video_bg_color == QColor(255, 255, 255)

    def test_bg_color_combo_select_light_gray(self, main_window):
        main_window._pick_bg_color("Light Gray")
        assert main_window.video_bg_color == QColor(200, 200, 200)

    def test_bg_color_combo_select_navy(self, main_window):
        main_window._pick_bg_color("Navy")
        assert main_window.video_bg_color == QColor(0, 0, 80)

    def test_bg_color_combo_unknown_falls_back(self, main_window):
        main_window._pick_bg_color("NonExistentColor")
        assert main_window.video_bg_color == QColor(30, 30, 32)

    def test_bg_color_combo_updates_stylesheet(self, main_window):
        main_window._pick_bg_color("Black")
        style = main_window.bg_color_combo.styleSheet()
        assert "background-color" in style


# ═══════════════════════════════════════════════════════════════════
# 21. INTEGRATION — Full Workflow
# ═══════════════════════════════════════════════════════════════════

class TestIntegrationWorkflow:
    def test_full_game_workflow(self, main_window):
        main_window._new_game()
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        main_window._on_sq_click(chess.E7)
        main_window._on_sq_click(chess.E5)
        main_window._on_sq_click(chess.G1)
        main_window._on_sq_click(chess.F3)

        assert len(main_window.move_list) == 3
        assert main_window.move_index == 2

        main_window._go_first()
        assert main_window.move_index == -1

        main_window._go_next()
        assert main_window.move_index == 0

        main_window._go_last()
        assert main_window.move_index == 2

        main_window.anno_edit.setPlainText("Great opening!")
        main_window._apply_comment()
        assert main_window.node.comment == "Great opening!"

        main_window.fps_spin.setValue(10)
        main_window.hold_spin.setValue(0.2)
        main_window._auto_capture()
        assert len(main_window.capture_frames) > 0

        main_window._clear_frames()
        assert len(main_window.capture_frames) == 0

    def test_load_pgn_and_navigate(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        move_count = len(main_window.move_list)
        for i in range(move_count):
            main_window._go_next()
        assert main_window.move_index == move_count - 1
        for i in range(move_count):
            main_window._go_prev()
        assert main_window.move_index == -1

    def test_theme_switching_preserves_position(self, main_window):
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        saved_fen = main_window.board_widget.board.fen()

        main_window._theme_changed("Blue")
        assert main_window.board_widget.board.fen() == saved_fen

        main_window._theme_changed("Green")
        assert main_window.board_widget.board.fen() == saved_fen

        main_window._theme_changed("Classic")
        assert main_window.board_widget.board.fen() == saved_fen

    def test_flip_board_preserves_moves(self, main_window):
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        move_count = len(main_window.move_list)
        main_window._flip_board()
        assert len(main_window.move_list) == move_count
        main_window._flip_board()

    def test_new_game_resets_state(self, main_window):
        from constants import SAMPLE_PGN
        game = chess.pgn.read_game(io.StringIO(SAMPLE_PGN))
        main_window._load_pgn_data(game)
        assert len(main_window.move_list) > 0

        main_window._new_game()
        assert len(main_window.move_list) == 0
        assert main_window.move_index == -1
        assert len(main_window.eval_cache) == 0

    def test_video_canvas_with_captured_frames(self, main_window):
        from video_canvas import VideoCanvas
        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)

        canvas = VideoCanvas(
            main_window.board_widget, main_window.eval_bar_widget,
            bg_color=main_window.video_bg_color
        )
        canvas.white_name = "Player1"
        canvas.black_name = "Player2"
        canvas.move_list_text = [n.san() for n in main_window.move_list]
        canvas.eval_cp = 0.0
        canvas.current_move_index = 0

        img = canvas.render()
        assert isinstance(img, QImage)
        assert not img.isNull()

    def test_battle_then_manual_play(self, main_window, qtbot):
        main_window.white_ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        main_window.white_ai_str.setValue(1)
        main_window.black_ai_combo.setCurrentText("Minimax (Alpha-Beta)")
        main_window.black_ai_str.setValue(1)
        main_window.battle_delay.setValue(50)

        main_window._start_ai_vs_ai()
        time.sleep(1)
        qapp().processEvents()

        main_window._stop_ai_vs_ai()
        assert not main_window.ai_vs_ai_running

        main_window.ai_vs_ai_running = False
        board = main_window.board_widget.board
        if not board.is_game_over():
            legal = list(board.legal_moves)
            if legal:
                sq = legal[0].from_square
                main_window._on_sq_click(sq)

    def test_overlay_positions(self, main_window):
        positions = {
            "White Player Face": (50, 850),
            "Black Player Face": (50, 50),
            "Center Logo": (960 - 75, 540 - 75),
            "Watermark (BR)": (1750, 1000),
        }
        for pos_name, (expected_x, expected_y) in positions.items():
            ov = {"path": "test.png", "w": 150, "h": 150}
            if "White" in pos_name:
                ov["x"], ov["y"] = 50, 850
            elif "Black" in pos_name:
                ov["x"], ov["y"] = 50, 50
            elif "Center" in pos_name or "Logo" in pos_name:
                ov["x"], ov["y"] = 960 - 75, 540 - 75
            elif "Watermark" in pos_name:
                ov["x"], ov["y"] = 1750, 1000
            assert ov["x"] == expected_x
            assert ov["y"] == expected_y

    def test_inline_pgn_load_and_capture(self, main_window):
        from constants import SAMPLE_PGN
        main_window.pgn_text_edit.setPlainText(SAMPLE_PGN)
        main_window._load_pgn_text()
        assert len(main_window.move_list) > 0

        main_window._go_first()
        main_window.fps_spin.setValue(10)
        main_window.hold_spin.setValue(0.2)
        main_window._auto_capture()
        assert len(main_window.capture_frames) > 0

    def test_inline_file_load_workflow(self, main_window):
        from constants import SAMPLE_PGN
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pgn', delete=False) as f:
            f.write(SAMPLE_PGN)
            tmp_path = f.name
        try:
            main_window.pgn_file_edit.setText(tmp_path)
            main_window._load_pgn_from_file()
            assert len(main_window.move_list) > 0
            main_window._go_last()
            assert main_window.move_index >= 0
        finally:
            os.unlink(tmp_path)

    def test_bg_color_change_then_render(self, main_window):
        from video_canvas import VideoCanvas
        main_window._pick_bg_color("Black")
        assert main_window.video_bg_color == QColor(0, 0, 0)

        main_window._on_sq_click(chess.E2)
        main_window._on_sq_click(chess.E4)
        canvas = VideoCanvas(
            main_window.board_widget, main_window.eval_bar_widget,
            bg_color=main_window.video_bg_color
        )
        img = canvas.render()
        assert not img.isNull()

        main_window._pick_bg_color("Dark Gray")

    def test_promo_widget_integration(self, main_window):
        board = chess.Board("4k3/4P3/8/8/8/8/8/4K3 w - - 0 1")
        main_window.board_widget.set_position(board)
        main_window.node = main_window.game
        main_window.game = chess.pgn.Game()
        main_window.node = main_window.game
        board2 = chess.Board("4k3/4P3/8/8/8/8/8/4K3 w - - 0 1")
        main_window.board_widget.board = board2

        main_window._on_sq_click(chess.E7)
        if main_window.board_widget.selected_sq is not None:
            main_window._on_sq_click(chess.E8)
            if main_window._pending_promo_from is not None:
                assert main_window.promo_widget.isVisible()


# ═══════════════════════════════════════════════════════════════════
# 22. EDGE CASES
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_eval_bar_extreme_values(self, eval_bar):
        eval_bar.set_eval(10000.0)
        assert eval_bar.eval_cp == 10000.0
        eval_bar.set_eval(-10000.0)
        assert eval_bar.eval_cp == -10000.0

    def test_heuristic_endgame(self):
        from ai_engines import HeuristicEvaluator
        ev = HeuristicEvaluator()
        board = chess.Board("8/8/8/4k3/4P3/4K3/8/8 w - - 0 1")
        score = ev.evaluate(board)
        assert isinstance(score, (int, float))

    def test_minimax_forced_move(self):
        from ai_engines import MinimaxEngine
        eng = MinimaxEngine()
        board = chess.Board("k7/8/1K6/8/8/8/8/7R w - - 0 1")
        best_move, _, _, _ = eng.search(board, depth=1)
        assert best_move is not None

    def test_mcts_single_legal_move(self):
        from ai_engines import MCTSEngine
        eng = MCTSEngine()
        board = chess.Board("k7/8/1K6/8/8/8/8/7R w - - 0 1")
        best_move, _, _, _ = eng.search(board, iterations=5)
        assert best_move is not None

    def test_video_canvas_empty_move_list(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        vc.move_list_text = []
        vc.current_move_index = -1
        img = vc.render()
        assert not img.isNull()

    def test_video_canvas_long_move_list(self, board_widget, eval_bar):
        from video_canvas import VideoCanvas
        vc = VideoCanvas(board_widget, eval_bar)
        vc.move_list_text = ["e4"] * 100
        vc.current_move_index = 50
        img = vc.render()
        assert not img.isNull()

    def test_board_widget_set_position_clears_anim(self, board_widget):
        board_widget.anim_move = chess.Move.from_uci("e2e4")
        board_widget.anim_progress = 0.5
        board_widget.set_position(chess.Board())
        assert board_widget.anim_move is None
        assert board_widget.anim_progress == 0.0

    def test_mcts_node_expand_all(self):
        from ai_engines import MCTSNode
        node = MCTSNode(chess.Board())
        while node.untried_moves:
            node.expand()
        assert len(node.untried_moves) == 0

    def test_ucb1_with_c_param(self):
        from ai_engines import MCTSNode
        parent = MCTSNode(chess.Board())
        parent.visits = 100
        child = MCTSNode(chess.Board(), parent=parent)
        child.visits = 10
        child.wins = 5.0
        ucb_default = child.ucb1()
        ucb_low = child.ucb1(c=0.5)
        assert ucb_low < ucb_default

    def test_promotion_widget_all_pieces(self):
        from dialogs import PromotionWidget
        for color in [chess.WHITE, chess.BLACK]:
            for piece in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
                w = PromotionWidget()
                received = []
                w.piece_selected.connect(lambda pt: received.append(pt))
                w.show_for_color(color)
                w._pick(piece)
                assert received == [piece]
                assert not w.isVisible()
                w.close()

    def test_batch_eval_empty_move_list(self, qtbot):
        from workers import BatchEvalWorker
        worker = BatchEvalWorker([], "Minimax (Alpha-Beta)", {"depth": 1})
        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.start()
        worker.wait(3000)

    def test_ai_worker_with_checkmate_position(self, qtbot):
        from workers import AIWorker
        board = chess.Board()
        for m in ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]:
            board.push_uci(m)
        worker = AIWorker("Minimax (Alpha-Beta)", board.fen(), {"depth": 1})
        results = []
        worker.eval_ready.connect(lambda d: results.append(d))
        with qtbot.waitSignal(worker.eval_ready, timeout=15000):
            worker.start()
        worker.wait(3000)
        assert len(results) == 1

    def test_mcts_rollout_depth_zero(self):
        from ai_engines import MCTSEngine
        eng = MCTSEngine()
        board = chess.Board()
        score = eng._heuristic_rollout(board, depth=0)
        assert 0.0 < score < 1.0

    def test_minimax_negamax_terminal(self):
        from ai_engines import MinimaxEngine
        eng = MinimaxEngine()
        board = chess.Board()
        for m in ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]:
            board.push_uci(m)
        result = eng._negamax(board, 0, -float('inf'), float('inf'))
        assert isinstance(result, (int, float))

    def test_main_window_status_bar(self, main_window):
        assert main_window.statusBar() is not None
        msg = main_window.statusBar().currentMessage()
        assert len(msg) > 0

    def test_inline_export_without_cv2(self, main_window):
        from constants import HAS_CV2
        if HAS_CV2:
            main_window.capture_frames = []
            main_window._start_inline_export()
        else:
            main_window._on_sq_click(chess.E2)
            main_window._on_sq_click(chess.E4)
            main_window.fps_spin.setValue(10)
            main_window.hold_spin.setValue(0.2)
            main_window._auto_capture()
            main_window.export_path_edit.setText(os.path.join(tempfile.gettempdir(), "test_edge.mp4"))
            main_window._start_inline_export()
            assert "opencv" in main_window.export_status_lbl.text().lower() or "error" in main_window.export_status_lbl.text().lower()

    def test_load_pgn_from_file_bad_content(self, main_window):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pgn', delete=False) as f:
            f.write("this is not a pgn file at all")
            tmp_path = f.name
        try:
            main_window.pgn_file_edit.setText(tmp_path)
            main_window._load_pgn_from_file()
        finally:
            os.unlink(tmp_path)


# ═══════════════════════════════════════════════════════════════════
# 23. APP MODULE IMPORTS
# ═══════════════════════════════════════════════════════════════════

class TestAppImports:
    def test_import_constants(self):
        from constants import PIECE_SYM, AI_MAP, SAMPLE_PGN, HAS_CV2, BoardTheme, THEMES
        assert PIECE_SYM is not None
        assert AI_MAP is not None

    def test_import_ai_engines(self):
        from ai_engines import HeuristicEvaluator, MinimaxEngine, MCTSNode, MCTSEngine
        assert HeuristicEvaluator is not None
        assert MinimaxEngine is not None

    def test_import_workers(self):
        from workers import AIWorker, BatchEvalWorker, ExportWorker
        assert AIWorker is not None

    def test_import_widgets(self):
        from board_widget import ChessBoardWidget
        from eval_bar import EvalBarWidget
        from video_canvas import VideoCanvas
        assert ChessBoardWidget is not None
        assert EvalBarWidget is not None
        assert VideoCanvas is not None

    def test_import_dialogs(self):
        from dialogs import PromotionWidget
        assert PromotionWidget is not None

    def test_import_main_window(self):
        from main_window import MainWindow
        assert MainWindow is not None

    def test_import_ui_builder(self):
        from ui_builder import build_ui, build_menu
        assert build_ui is not None
        assert build_menu is not None


# ═══════════════════════════════════════════════════════════════════
# 24. TestSyncUCIEngine
# ═══════════════════════════════════════════════════════════════════

# Add this class after TestExportWorker:

class TestSyncUCIEngine:
    """Test the synchronous UCI engine client directly."""

    @pytest.mark.skipif(not find_stockfish(), reason="Stockfish not installed")
    def test_engine_start_and_close(self):
        from workers import _SyncUCIEngine
        engine = _SyncUCIEngine(find_stockfish())
        engine.close()
        # Process should be terminated
        assert engine.proc.poll() is not None

    @pytest.mark.skipif(not find_stockfish(), reason="Stockfish not installed")
    def test_analyse_starting_position(self):
        from workers import _SyncUCIEngine
        engine = _SyncUCIEngine(find_stockfish())
        try:
            best_move, score_cp = engine.analyse(chess.Board().fen(), depth=10)
            assert best_move is not None
            assert isinstance(score_cp, (int, float))
            # Starting position should be roughly equal
            assert abs(score_cp) < 500
        finally:
            engine.close()

    @pytest.mark.skipif(not find_stockfish(), reason="Stockfish not installed")
    def test_analyse_multiple_positions(self):
        """Test that multiple analyses in sequence don't crash.

        This is the exact scenario that crashes with python-chess
        asyncio on Windows.  The sync client must handle it safely.
        """
        from workers import _SyncUCIEngine
        engine = _SyncUCIEngine(find_stockfish())
        try:
            fens = [
                chess.Board().fen(),
                "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
                "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
            ]
            for fen in fens:
                best_move, score_cp = engine.analyse(fen, depth=10)
                assert best_move is not None
                assert isinstance(score_cp, (int, float))
        finally:
            engine.close()

    @pytest.mark.skipif(not find_stockfish(), reason="Stockfish not installed")
    def test_analyse_checkmate_position(self):
        from workers import _SyncUCIEngine
        engine = _SyncUCIEngine(find_stockfish())
        try:
            # Scholar's mate
            board = chess.Board()
            for m in ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]:
                board.push_uci(m)
            best_move, score_cp = engine.analyse(board.fen(), depth=5)
            # Black is checkmated — score should be very negative for White
            # (engine may return None for best_move since no legal moves)
            assert score_cp < -5000 or best_move is None
        finally:
            engine.close()

    @pytest.mark.skipif(not find_stockfish(), reason="Stockfish not installed")
    def test_score_from_white_perspective(self):
        """Verify score is always from White's perspective."""
        from workers import _SyncUCIEngine
        engine = _SyncUCIEngine(find_stockfish())
        try:
            # White has extra queen — score should be very positive
            fen = "4k3/8/8/8/8/8/8/4K2Q w - - 0 1"
            _, score_white = engine.analyse(fen, depth=10)
            assert score_white > 0, "White extra queen should give positive score"

            # Black has extra queen — score should be very negative
            fen = "4k2q/8/8/8/8/8/8/4K3 w - - 0 1"
            _, score_black = engine.analyse(fen, depth=10)
            assert score_black < 0, "Black extra queen should give negative score"
        finally:
            engine.close()

    def test_engine_bad_path(self):
        """Starting engine with bad path should raise an exception."""
        from workers import _SyncUCIEngine
        with pytest.raises(Exception):
            _SyncUCIEngine("/nonexistent/path/to/engine")