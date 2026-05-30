"""Tests for board_widget.py — coordinate conversion and static rendering."""

import chess
import numpy as np
import pytest

from PySide6.QtGui import QImage
from PySide6.QtCore import Qt


class TestCoordinateConversion:
    """Test the coordinate conversion helper functions."""

    def test_sq_to_rc_a1_normal(self):
        from board_widget import _sq_to_rc
        r, c = _sq_to_rc(chess.A1, flipped=False)
        assert r == 7
        assert c == 0

    def test_sq_to_rc_a1_flipped(self):
        from board_widget import _sq_to_rc
        r, c = _sq_to_rc(chess.A1, flipped=True)
        assert r == 0
        assert c == 7

    def test_sq_to_rc_h8_normal(self):
        from board_widget import _sq_to_rc
        r, c = _sq_to_rc(chess.H8, flipped=False)
        assert r == 0
        assert c == 7

    def test_sq_to_rc_h8_flipped(self):
        from board_widget import _sq_to_rc
        r, c = _sq_to_rc(chess.H8, flipped=True)
        assert r == 7
        assert c == 0

    def test_rc_to_sq_roundtrip_normal(self):
        from board_widget import _sq_to_rc, _rc_to_sq
        for sq in chess.SQUARES:
            r, c = _sq_to_rc(sq, flipped=False)
            assert _rc_to_sq(r, c, flipped=False) == sq

    def test_rc_to_sq_roundtrip_flipped(self):
        from board_widget import _sq_to_rc, _rc_to_sq
        for sq in chess.SQUARES:
            r, c = _sq_to_rc(sq, flipped=True)
            assert _rc_to_sq(r, c, flipped=True) == sq

    def test_engine_rc_to_screen_rc_consistency(self):
        from board_widget import _engine_rc_to_screen_rc, _screen_rc_to_engine_rc
        for eng_r in range(8):
            for eng_c in range(8):
                for flipped in (False, True):
                    sr, sc = _engine_rc_to_screen_rc(eng_r, eng_c, flipped)
                    er, ec = _screen_rc_to_engine_rc(sr, sc, flipped)
                    assert (er, ec) == (eng_r, eng_c), \
                        f"Roundtrip failed for ({eng_r},{eng_c}) flipped={flipped}"


class TestRenderFrame:
    """Test the static render_frame method."""

    def test_renders_basic_board(self, qapp):
        from board_widget import ChessBoardWidget
        board = chess.Board()
        img = ChessBoardWidget.render_frame(board)
        assert isinstance(img, QImage)
        assert img.width() == 68 * 8
        assert img.height() == 68 * 8

    def test_renders_with_custom_sq_size(self, qapp):
        from board_widget import ChessBoardWidget
        board = chess.Board()
        img = ChessBoardWidget.render_frame(board, sq_size=80)
        assert img.width() == 80 * 8
        assert img.height() == 80 * 8

    def test_renders_with_last_move(self, qapp):
        from board_widget import ChessBoardWidget
        board = chess.Board()
        img = ChessBoardWidget.render_frame(board, last_move=((6, 4), (4, 4)))
        assert isinstance(img, QImage)

    def test_renders_with_selected(self, qapp):
        from board_widget import ChessBoardWidget
        board = chess.Board()
        img = ChessBoardWidget.render_frame(board, selected=(6, 4))
        assert isinstance(img, QImage)

    def test_renders_with_legal_targets(self, qapp):
        from board_widget import ChessBoardWidget
        board = chess.Board()
        img = ChessBoardWidget.render_frame(board, selected=(6, 4), legal_targets={(5, 4), (4, 4)})
        assert isinstance(img, QImage)

    def test_renders_with_check(self, qapp):
        from board_widget import ChessBoardWidget
        board = chess.Board()
        img = ChessBoardWidget.render_frame(board, check_squares=[(7, 4)])
        assert isinstance(img, QImage)

    def test_renders_with_animation(self, qapp):
        from board_widget import ChessBoardWidget
        board = chess.Board()
        anim = {"from": (6, 4), "to": (4, 4), "piece_obj": chess.Piece(chess.PAWN, chess.WHITE), "progress": 0.5, "captured": "."}
        img = ChessBoardWidget.render_frame(board, anim_state=anim)
        assert isinstance(img, QImage)

    def test_renders_with_text_overlay(self, qapp):
        from board_widget import ChessBoardWidget
        board = chess.Board()
        img = ChessBoardWidget.render_frame(board, text_overlay="White to play")
        assert isinstance(img, QImage)

    def test_renders_with_different_themes(self, qapp):
        from board_widget import ChessBoardWidget
        from config import THEMES
        board = chess.Board()
        for theme_name, theme in THEMES.items():
            img = ChessBoardWidget.render_frame(board, theme=theme)
            assert isinstance(img, QImage), f"Failed for theme {theme_name}"

    def test_renders_without_coordinates(self, qapp):
        from board_widget import ChessBoardWidget
        board = chess.Board()
        img = ChessBoardWidget.render_frame(board, show_coords=False)
        assert isinstance(img, QImage)

    def test_renders_without_arrow(self, qapp):
        from board_widget import ChessBoardWidget
        board = chess.Board()
        img = ChessBoardWidget.render_frame(board, last_move=((6, 4), (4, 4)), show_arrow=False)
        assert isinstance(img, QImage)

    def test_animation_with_capture(self, qapp):
        from board_widget import ChessBoardWidget
        board = chess.Board()
        anim = {"from": (3, 4), "to": (3, 3), "piece_obj": chess.Piece(chess.PAWN, chess.WHITE), "progress": 0.3, "captured": "p"}
        img = ChessBoardWidget.render_frame(board, anim_state=anim)
        assert isinstance(img, QImage)


class TestRenderMoveList:
    def test_renders_basic_move_list(self, qapp):
        from board_widget import ChessBoardWidget
        moves = ["e4", "e5", "Nf3", "Nc6"]
        img = ChessBoardWidget.render_move_list(moves)
        assert isinstance(img, QImage)
        assert img.width() == 240
        assert img.height() == 544

    def test_renders_with_current_move_highlight(self, qapp):
        from board_widget import ChessBoardWidget
        moves = ["e4", "e5", "Nf3", "Nc6"]
        img = ChessBoardWidget.render_move_list(moves, current_idx=2)
        assert isinstance(img, QImage)

    def test_renders_with_puzzle_info(self, qapp):
        from board_widget import ChessBoardWidget
        moves = ["e4", "e5"]
        info = {"name": "Test Puzzle", "rating": 1500, "themes": "fork pin"}
        img = ChessBoardWidget.render_move_list(moves, puzzle_info=info)
        assert isinstance(img, QImage)

    def test_renders_with_status(self, qapp):
        from board_widget import ChessBoardWidget
        moves = ["e4"]
        img = ChessBoardWidget.render_move_list(moves, status_text="Playing...")
        assert isinstance(img, QImage)

    def test_renders_empty_moves(self, qapp):
        from board_widget import ChessBoardWidget
        img = ChessBoardWidget.render_move_list([])
        assert isinstance(img, QImage)

    def test_renders_many_moves_overflow(self, qapp):
        from board_widget import ChessBoardWidget
        moves = [f"M{i}" for i in range(100)]
        img = ChessBoardWidget.render_move_list(moves, height=300)
        assert isinstance(img, QImage)

    def test_custom_dimensions(self, qapp):
        from board_widget import ChessBoardWidget
        img = ChessBoardWidget.render_move_list(["e4"], width=300, height=400)
        assert img.width() == 300
        assert img.height() == 400


class TestRenderLayout:
    def test_board_only_layout(self, qapp):
        from board_widget import ChessBoardWidget
        from config import LayoutMode, SQ_SIZE
        board = chess.Board()
        board_img = ChessBoardWidget.render_frame(board)
        result = ChessBoardWidget.render_layout(board_img, ["e4"], 0, LayoutMode.BOARD_ONLY, 544, 544, (26, 27, 46), SQ_SIZE)
        assert isinstance(result, QImage)

    def test_board_moves_right_layout(self, qapp):
        from board_widget import ChessBoardWidget
        from config import LayoutMode, SQ_SIZE
        board = chess.Board()
        board_img = ChessBoardWidget.render_frame(board)
        result = ChessBoardWidget.render_layout(board_img, ["e4", "e5"], 0, LayoutMode.BOARD_MOVES_RIGHT, 800, 544, (26, 27, 46), SQ_SIZE)
        assert isinstance(result, QImage)
        assert result.width() == 800

    def test_board_moves_bottom_layout(self, qapp):
        from board_widget import ChessBoardWidget
        from config import LayoutMode, SQ_SIZE
        board = chess.Board()
        board_img = ChessBoardWidget.render_frame(board)
        result = ChessBoardWidget.render_layout(board_img, ["e4", "e5"], 0, LayoutMode.BOARD_MOVES_BOTTOM, 544, 700, (26, 27, 46), SQ_SIZE)
        assert isinstance(result, QImage)
        assert result.height() == 700

    def test_move_list_visible_false(self, qapp):
        from board_widget import ChessBoardWidget
        from config import LayoutMode, SQ_SIZE
        board = chess.Board()
        board_img = ChessBoardWidget.render_frame(board)
        result = ChessBoardWidget.render_layout(board_img, ["e4"], 0, LayoutMode.BOARD_MOVES_RIGHT, 800, 544, (26, 27, 46), SQ_SIZE, move_list_visible=False)
        assert isinstance(result, QImage)

    def test_too_small_returns_board_only(self, qapp):
        from board_widget import ChessBoardWidget
        from config import LayoutMode, SQ_SIZE
        board = chess.Board()
        board_img = ChessBoardWidget.render_frame(board)
        result = ChessBoardWidget.render_layout(board_img, ["e4"], 0, LayoutMode.BOARD_MOVES_RIGHT, 100, 100, (26, 27, 46), SQ_SIZE)
        assert isinstance(result, QImage)


class TestRenderCard:
    def test_basic_card(self, qapp):
        from board_widget import ChessBoardWidget
        img = ChessBoardWidget.render_card("Hello World")
        assert isinstance(img, QImage)
        assert img.width() == 544
        assert img.height() == 544

    def test_card_with_sub_text(self, qapp):
        from board_widget import ChessBoardWidget
        img = ChessBoardWidget.render_card("Title", sub_text="Subtitle")
        assert isinstance(img, QImage)

    def test_card_custom_colors(self, qapp):
        from board_widget import ChessBoardWidget
        img = ChessBoardWidget.render_card("Test", bg_color="#000000", fg_color="#ffffff")
        assert isinstance(img, QImage)

    def test_card_custom_size(self, qapp):
        from board_widget import ChessBoardWidget
        img = ChessBoardWidget.render_card("Test", width=800, height=600)
        assert img.width() == 800
        assert img.height() == 600


class TestQImageConversion:
    def test_qimage_to_np_basic(self, qapp):
        from board_widget import ChessBoardWidget
        img = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.red)
        arr = ChessBoardWidget.qimage_to_np(img)
        assert arr.shape == (64, 64, 3)
        assert arr.dtype == np.uint8

    def test_qimage_to_np_preserves_colors(self, qapp):
        from board_widget import ChessBoardWidget
        img = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.red)
        arr = ChessBoardWidget.qimage_to_np(img)
        assert arr[0, 0, 0] > 200  # R
        assert arr[0, 0, 1] < 50   # G
        assert arr[0, 0, 2] < 50   # B

    def test_qimage_to_np_batch(self, qapp):
        from board_widget import ChessBoardWidget
        imgs = []
        for _ in range(3):
            img = QImage(32, 32, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.blue)
            imgs.append(img)
        batch = ChessBoardWidget.qimage_to_np_batch(imgs)
        assert batch.shape == (3, 32, 32, 3)

    def test_qimage_to_np_batch_empty(self, qapp):
        from board_widget import ChessBoardWidget
        batch = ChessBoardWidget.qimage_to_np_batch([])
        assert batch.shape == (0, 0, 0, 3)


class TestChessBoardWidget:
    def test_widget_creation(self, qapp):
        from board_widget import ChessBoardWidget
        from chess_engine import ChessEngine
        from sound_manager import SoundManager
        engine = ChessEngine()
        snd = SoundManager()
        widget = ChessBoardWidget(engine, snd)
        assert widget.flipped is False
        assert widget.auto_playing is False
        assert widget.animating is False
        snd.cleanup()

    def test_flip(self, qapp):
        from board_widget import ChessBoardWidget
        from chess_engine import ChessEngine
        from sound_manager import SoundManager
        engine = ChessEngine()
        snd = SoundManager()
        widget = ChessBoardWidget(engine, snd)
        assert widget.flipped is False
        widget.flip()
        assert widget.flipped is True
        widget.flip()
        assert widget.flipped is False
        snd.cleanup()

    def test_set_legal_targets(self, qapp):
        from board_widget import ChessBoardWidget
        from chess_engine import ChessEngine
        from sound_manager import SoundManager
        engine = ChessEngine()
        snd = SoundManager()
        widget = ChessBoardWidget(engine, snd)
        widget._set_legal_targets([(5, 4), (4, 4)])
        assert widget.legal_targets == [(5, 4), (4, 4)]
        assert widget.legal_targets_set == {(5, 4), (4, 4)}
        snd.cleanup()
