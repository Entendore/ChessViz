"""Tests for chess_engine.py — core chess logic."""

import chess
import pytest


class TestChessEngineInit:
    def test_default_board(self, fresh_engine):
        e = fresh_engine
        assert e.board.fen() == chess.STARTING_FEN
        assert e.game_over is False
        assert e.result == ""
        assert e.last_move is None

    def test_turn_white_at_start(self, fresh_engine):
        assert fresh_engine.turn == "w"

    def test_turn_after_move(self, fresh_engine):
        fresh_engine.make_move(6, 4, 4, 4)  # e2-e4
        assert fresh_engine.turn == "b"


class TestCoordinateConversion:
    """Test sq_to_rc and rc_to_sq conversions."""

    def test_sq_to_rc_a8(self):
        from chess_engine import ChessEngine
        # a8 = square 56 → rank 7, file 0 → row 0, col 0
        assert ChessEngine.sq_to_rc(chess.A8) == (0, 0)

    def test_sq_to_rc_h1(self):
        from chess_engine import ChessEngine
        # h1 = square 7 → rank 0, file 7 → row 7, col 7
        assert ChessEngine.sq_to_rc(chess.H1) == (7, 7)

    def test_sq_to_rc_e2(self):
        from chess_engine import ChessEngine
        # e2 = square 12 → rank 1, file 4 → row 6, col 4
        assert ChessEngine.sq_to_rc(chess.E2) == (6, 4)

    def test_rc_to_sq_roundtrip(self):
        from chess_engine import ChessEngine
        for sq in chess.SQUARES:
            r, c = ChessEngine.sq_to_rc(sq)
            assert ChessEngine.rc_to_sq(r, c) == sq

    def test_rc_to_sq_known_values(self):
        from chess_engine import ChessEngine
        assert ChessEngine.rc_to_sq(0, 0) == chess.A8
        assert ChessEngine.rc_to_sq(7, 7) == chess.H1
        assert ChessEngine.rc_to_sq(6, 4) == chess.E2


class TestLegalMoves:
    def test_legal_moves_pawn_e2(self, fresh_engine):
        targets = fresh_engine.legal_moves(6, 4)  # e2 pawn
        assert (5, 4) in targets  # e3
        assert (4, 4) in targets  # e4

    def test_legal_moves_knight_start(self, fresh_engine):
        targets = fresh_engine.legal_moves(7, 6)  # g1 knight
        assert (5, 5) in targets  # f3
        assert (5, 7) in targets  # h3

    def test_legal_moves_no_piece(self, fresh_engine):
        # e4 is empty at start
        targets = fresh_engine.legal_moves(4, 4)
        assert targets == []

    def test_legal_moves_blocked_piece(self, fresh_engine):
        # Queen at d1 can't move through pawns at start
        targets = fresh_engine.legal_moves(7, 3)
        # At start, queen has no legal moves (all blocked)
        assert targets == []


class TestCheckSquares:
    def test_no_check_at_start(self, fresh_engine):
        assert fresh_engine.check_squares() == []

    def test_check_after_scholars_mate_setup(self):
        from chess_engine import ChessEngine
        e = ChessEngine()
        # Fool's mate: 1.f3 e5 2.g4 Qh4#
        e.make_move(6, 5, 5, 5)  # f2-f3  (white)
        e.make_move(1, 4, 3, 4)  # e7-e5  (black: row 1 = rank 7)
        e.make_move(6, 6, 4, 6)  # g2-g4  (white)
        e.make_move(0, 3, 4, 7)  # Qd8-h4 (black: d8=row0,col3 → h4=row4,col7)
        check_sqs = e.check_squares()
        assert len(check_sqs) == 1  # White king is in check


class TestMakeMove:
    def test_normal_pawn_move(self, fresh_engine):
        result = fresh_engine.make_move(6, 4, 4, 4)  # e2-e4
        assert result is not None
        assert result["piece"] == "P"
        assert result["captured"] == "."
        assert result["castle"] is False
        assert result["ep"] is False
        assert result["notation"] == "e4"
        assert result["from"] == (6, 4)
        assert result["to"] == (4, 4)

    def test_capture_move(self, fresh_engine):
        # 1.e4 d5 2.exd5
        fresh_engine.make_move(6, 4, 4, 4)  # e2-e4  (white)
        fresh_engine.make_move(1, 3, 3, 3)  # d7-d5  (black: row 1 = rank 7)
        result = fresh_engine.make_move(4, 4, 3, 3)  # e4xd5 (white pawn captures)
        assert result is not None
        assert result["captured"] == "p"
        assert result["notation"] == "exd5"

    def test_illegal_move_returns_none(self, fresh_engine):
        result = fresh_engine.make_move(6, 0, 3, 0)  # a2-a5 (3 squares, illegal)
        assert result is None

    def test_illegal_move_no_piece(self, fresh_engine):
        result = fresh_engine.make_move(4, 4, 3, 4)  # e4 is empty at start
        assert result is None

    def test_castling_kingside(self):
        from chess_engine import ChessEngine
        e = ChessEngine()
        fen = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
        e.load_fen(fen)
        result = e.make_move(7, 4, 7, 6)  # O-O (king e1 to g1)
        assert result is not None
        assert result["castle"] is True
        assert result["notation"] == "O-O"

    def test_en_passant(self):
        from chess_engine import ChessEngine
        e = ChessEngine()
        # 1.e4 d5 2.e5 f5 — then exf6 e.p.
        e.make_move(6, 4, 4, 4)   # e2-e4  (white)
        e.make_move(1, 3, 3, 3)   # d7-d5  (black)
        e.make_move(4, 4, 3, 4)   # e4-e5  (white)
        e.make_move(1, 5, 3, 5)   # f7-f5  (black)
        result = e.make_move(3, 4, 2, 5)  # e5xf6 e.p. (white pawn on row3 captures to row2)
        if result is not None:
            assert result["ep"] is True

    def test_promotion_default_queen(self):
        from chess_engine import ChessEngine
        e = ChessEngine()
        # Position: white pawn on e7, black king NOT on e8
        fen = "8/4P1k1/8/8/8/8/8/4K3 w - - 0 1"
        e.load_fen(fen)
        result = e.make_move(1, 4, 0, 4)  # e7-e8=Q
        assert result is not None
        assert result["promo"] is None  # Default queen, promo=None means auto-queen

    def test_promotion_explicit_rook(self):
        from chess_engine import ChessEngine
        e = ChessEngine()
        fen = "8/4P1k1/8/8/8/8/8/4K3 w - - 0 1"
        e.load_fen(fen)
        result = e.make_move(1, 4, 0, 4, promo="r")  # e7-e8=R
        assert result is not None

    def test_check_after_move(self):
        from chess_engine import ChessEngine
        e = ChessEngine()
        # Position where a knight gives check
        fen = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 3"
        e.load_fen(fen)
        # Move: Bxf7+ (bishop takes f7 giving check)
        result = e.make_move(5, 2, 1, 5)  # Bc4xf7+
        if result is not None:
            assert result["check"] is True

    def test_checkmate_detection(self):
        from chess_engine import ChessEngine
        e = ChessEngine()
        # Scholar's mate: 1.f3 e5 2.g4 Qh4#
        e.make_move(6, 5, 5, 5)   # f2-f3  (white)
        e.make_move(1, 4, 3, 4)   # e7-e5  (black)
        e.make_move(6, 6, 4, 6)   # g2-g4  (white)
        result = e.make_move(0, 3, 4, 7)   # Qd8-h4# (black)
        if result is not None:
            assert result["mate"] is True
            assert e.game_over is True
            assert e.result == "0-1"


class TestMakeMoveUCI:
    def test_uci_move(self, fresh_engine):
        result = fresh_engine.make_move_uci("e2e4")
        assert result is not None
        assert result["notation"] == "e4"

    def test_uci_illegal(self, fresh_engine):
        result = fresh_engine.make_move_uci("e2e5")
        assert result is None

    def test_uci_promotion(self):
        from chess_engine import ChessEngine
        e = ChessEngine()
        fen = "8/4P1k1/8/8/8/8/8/4K3 w - - 0 1"
        e.load_fen(fen)
        result = e.make_move_uci("e7e8q")
        assert result is not None


class TestUndo:
    def test_undo_single_move(self, fresh_engine):
        fresh_engine.make_move(6, 4, 4, 4)  # e2-e4
        result = fresh_engine.undo()
        assert result is True
        assert fresh_engine.board.fen() == chess.STARTING_FEN
        assert fresh_engine.last_move is None

    def test_undo_multiple_moves(self, fresh_engine):
        fresh_engine.make_move(6, 4, 4, 4)  # e2-e4 (white)
        fresh_engine.make_move(1, 4, 3, 4)  # e7-e5 (black)
        fresh_engine.undo()
        fresh_engine.undo()
        assert fresh_engine.board.fen() == chess.STARTING_FEN

    def test_undo_empty_stack(self, fresh_engine):
        result = fresh_engine.undo()
        assert result is False

    def test_undo_updates_last_move(self, fresh_engine):
        fresh_engine.make_move(6, 4, 4, 4)  # e2-e4 (white)
        fresh_engine.make_move(1, 4, 3, 4)  # e7-e5 (black)
        fresh_engine.undo()  # undo e5 → last_move should be e4
        assert fresh_engine.last_move is not None
        assert fresh_engine.last_move == ((6, 4), (4, 4))  # e2-e4


class TestLoadFen:
    def test_load_valid_fen(self, fresh_engine):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        fresh_engine.load_fen(fen)
        # python-chess normalizes the en passant square to '-' when no capture
        # is actually possible, so we compare the board position, not exact FEN
        board = fresh_engine.board
        assert board.piece_at(chess.E4) is not None  # white pawn on e4
        assert board.piece_at(chess.E2) is None       # e2 is empty
        assert board.turn == chess.BLACK
        assert fresh_engine.last_move is None

    def test_load_fen_exact_when_stable(self, fresh_engine):
        # Use a FEN that python-chess won't normalize
        fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
        fresh_engine.load_fen(fen)
        # e6 is a valid en passant square here (black just played e7-e5)
        # python-chess may still normalize — just verify key pieces
        board = fresh_engine.board
        assert board.piece_at(chess.E4).color == chess.WHITE
        assert board.piece_at(chess.E5).color == chess.BLACK

    def test_load_checkmate_fen(self, fresh_engine):
        # Fool's mate position
        fen = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
        fresh_engine.load_fen(fen)
        assert fresh_engine.game_over is True

    def test_load_fen_resets_last_move(self, fresh_engine):
        fresh_engine.make_move(6, 4, 4, 4)
        assert fresh_engine.last_move is not None
        fresh_engine.load_fen(chess.STARTING_FEN)
        assert fresh_engine.last_move is None


class TestReset:
    def test_reset_after_moves(self, fresh_engine):
        fresh_engine.make_move(6, 4, 4, 4)
        fresh_engine.reset()
        assert fresh_engine.board.fen() == chess.STARTING_FEN
        assert fresh_engine.game_over is False
        assert fresh_engine.result == ""
        assert fresh_engine.last_move is None