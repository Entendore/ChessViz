#!/bin/bash
# Script to generate the complete pytest folder for Chess Puzzle Studio

# Create the tests directory
mkdir -p tests
cd tests

# --------------------------------------------------------
# pytest.ini
# --------------------------------------------------------
cat << 'EOF' > pytest.ini
[pytest]
testpaths = .
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
EOF

# --------------------------------------------------------
# conftest.py
# --------------------------------------------------------
cat << 'EOF' > conftest.py
"""Shared fixtures, path setup, and QApplication for all tests."""

import sys
import os
import json
import tempfile

import pytest

# ── Add source directory to sys.path ────────────────────────────────────────
SOURCE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SOURCE_DIR not in sys.path:
    sys.path.insert(0, SOURCE_DIR)


# ── Session-scoped QApplication ─────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    """Provide a single QApplication for the entire test session."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


# ── Sample puzzle data fixtures ─────────────────────────────────────────────

@pytest.fixture
def sample_lichess_puzzle():
    """A single Lichess-format puzzle dict."""
    return {
        "PuzzleId": "testPuzzle001",
        "FEN": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "Moves": "e7e5 d2d4 e5d4",
        "Rating": 1500,
        "RatingDeviation": 80,
        "Popularity": 90,
        "NbPlays": 5000,
        "Themes": "opening fork",
        "GameUrl": "https://lichess.org/test",
        "OpeningTags": "Kings Pawn",
    }


@pytest.fixture
def sample_puzzles_csv(tmp_path):
    """Create a small CSV file with Lichess-format puzzle data."""
    csv_content = (
        "PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags\n"
        "puz001,rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1,e7e5 d2d4,1200,50,85,3000,opening,https://lichess.org/1,Sicilian\n"
        "puz002,r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3,d2d4 e5d4 e4e5,900,40,70,1500,mateIn2 fork,https://lichess.org/2,Qh4\n"
        "puz003,rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1,e2e4 e7e5 g1f3,600,30,60,800,endgame,https://lichess.org/3,Italian\n"
        "puz004,8/5k2/8/8/8/8/4K3/4R3 w - - 0 1,e1e7 f7f6 e7f7,2000,100,95,10000,rookEndgame,https://lichess.org/4,,\n"
    )
    path = tmp_path / "test_puzzles.csv"
    path.write_text(csv_content, encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_puzzles_json(tmp_path):
    """Create a small JSON file with puzzle data."""
    data = [
        {
            "id": "json001",
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            "moves": "e7e5",
            "rating": 1100,
            "themes": "opening",
        },
        {
            "id": "json002",
            "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
            "moves": "d2d4 e5d4",
            "rating": 1400,
            "themes": "fork",
        },
    ]
    path = tmp_path / "test_puzzles.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_pgn(tmp_path):
    """Create a small PGN file."""
    pgn_content = (
        '[Event "Test Game"]\n'
        '[Site "Test"]\n'
        '[Date "2024.01.01"]\n'
        '[White "Player1"]\n'
        '[Black "Player2"]\n'
        '[Result "1-0"]\n'
        '[Opening "Kings Pawn"]\n\n'
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 1-0\n\n"
    )
    path = tmp_path / "test_game.pgn"
    path.write_text(pgn_content, encoding="utf-8")
    return str(path)


@pytest.fixture
def temp_export_dir(tmp_path):
    """Provide a temporary directory for export outputs."""
    d = tmp_path / "exports"
    d.mkdir()
    return str(d)


@pytest.fixture
def fresh_engine():
    """Provide a fresh ChessEngine for each test."""
    from chess_engine import ChessEngine
    return ChessEngine()


@pytest.fixture
def autosave_dir(tmp_path):
    """Provide a temporary autosave directory and patch config."""
    import config
    original_dir = config.AUTOSAVE_DIR
    original_path = config.AUTOSAVE_PATH
    config.AUTOSAVE_DIR = str(tmp_path / ".chess_puzzle_studio")
    config.AUTOSAVE_PATH = str(tmp_path / ".chess_puzzle_studio" / "state.json")
    os.makedirs(config.AUTOSAVE_DIR, exist_ok=True)
    yield config.AUTOSAVE_PATH
    config.AUTOSAVE_DIR = original_dir
    config.AUTOSAVE_PATH = original_path
EOF

# --------------------------------------------------------
# test_chess_engine.py
# --------------------------------------------------------
cat << 'EOF' > test_chess_engine.py
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
        e.make_move(6, 5, 5, 5)  # f3
        e.make_move(6, 4, 4, 4)  # e5
        e.make_move(6, 6, 4, 6)  # g4
        e.make_move(7, 3, 3, 7)  # Qh4
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
        fresh_engine.make_move(6, 4, 4, 4)  # e4
        fresh_engine.make_move(6, 3, 4, 3)  # d5
        result = fresh_engine.make_move(4, 4, 4, 3)  # exd5
        assert result is not None
        assert result["captured"] == "p"
        assert result["notation"] == "exd5"

    def test_illegal_move_returns_none(self, fresh_engine):
        result = fresh_engine.make_move(6, 0, 3, 0)  # a2-a5 (3 squares)
        assert result is None

    def test_illegal_move_no_piece(self, fresh_engine):
        result = fresh_engine.make_move(4, 4, 3, 4)  # e4 is empty
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
        e.make_move(6, 4, 4, 4)   # e4
        e.make_move(6, 3, 4, 3)   # d5
        e.make_move(4, 4, 3, 4)   # e5
        e.make_move(6, 5, 4, 5)   # f5
        result = e.make_move(3, 4, 3, 5)  # exf6 e.p.
        if result is not None:
            assert result["ep"] is True

    def test_promotion_default_queen(self):
        from chess_engine import ChessEngine
        e = ChessEngine()
        fen = "4k3/4P3/8/8/8/8/8/4K3 w - - 0 1"
        e.load_fen(fen)
        result = e.make_move(1, 4, 0, 4)  # e7-e8
        assert result is not None
        assert result["promo"] is None  # Default queen, promo=None means auto-queen

    def test_promotion_explicit_rook(self):
        from chess_engine import ChessEngine
        e = ChessEngine()
        fen = "4k3/4P3/8/8/8/8/8/4K3 w - - 0 1"
        e.load_fen(fen)
        result = e.make_move(1, 4, 0, 4, promo="r")  # e7-e8=R
        assert result is not None

    def test_check_after_move(self, fresh_engine):
        from chess_engine import ChessEngine
        e = ChessEngine()
        fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
        e.load_fen(fen)
        # Qh5 gives check
        result = e.make_move(7, 3, 3, 7)  # Qd1-h5
        if result is not None:
            assert result["check"] is True

    def test_checkmate_detection(self):
        from chess_engine import ChessEngine
        e = ChessEngine()
        # Scholar's mate: 1.f3 e5 2.g4 Qh4#
        e.make_move(6, 5, 5, 5)   # f3
        e.make_move(6, 4, 4, 4)   # e5
        e.make_move(6, 6, 4, 6)   # g4
        result = e.make_move(7, 3, 3, 7)   # Qh4#
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
        fen = "4k3/4P3/8/8/8/8/8/4K3 w - - 0 1"
        e.load_fen(fen)
        result = e.make_move_uci("e7e8q")
        assert result is not None


class TestUndo:
    def test_undo_single_move(self, fresh_engine):
        fresh_engine.make_move(6, 4, 4, 4)  # e4
        result = fresh_engine.undo()
        assert result is True
        assert fresh_engine.board.fen() == chess.STARTING_FEN
        assert fresh_engine.last_move is None

    def test_undo_multiple_moves(self, fresh_engine):
        fresh_engine.make_move(6, 4, 4, 4)  # e4
        fresh_engine.make_move(6, 4, 4, 4)  # e5
        fresh_engine.undo()
        fresh_engine.undo()
        assert fresh_engine.board.fen() == chess.STARTING_FEN

    def test_undo_empty_stack(self, fresh_engine):
        result = fresh_engine.undo()
        assert result is False

    def test_undo_updates_last_move(self, fresh_engine):
        fresh_engine.make_move(6, 4, 4, 4)  # e4
        fresh_engine.make_move(6, 4, 4, 4)  # e5
        fresh_engine.undo()
        assert fresh_engine.last_move is not None  # Should be e4


class TestLoadFen:
    def test_load_valid_fen(self, fresh_engine):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        fresh_engine.load_fen(fen)
        assert fresh_engine.board.fen() == fen
        assert fresh_engine.last_move is None

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
EOF

# --------------------------------------------------------
# test_puzzle_utils.py
# --------------------------------------------------------
cat << 'EOF' > test_puzzle_utils.py
"""Tests for puzzle_utils.py — parsing, conversion, batch helpers."""

import pytest
import numpy as np
import chess


class TestCleanMoveTokens:
    def test_removes_move_numbers(self):
        from puzzle_utils import _clean_move_tokens
        assert _clean_move_tokens(["1.", "e4", "2.", "e5"]) == ["e4", "e5"]

    def test_removes_result_strings(self):
        from puzzle_utils import _clean_move_tokens
        assert _clean_move_tokens(["e4", "e5", "1-0"]) == ["e4", "e5"]

    def test_removes_trailing_dots(self):
        from puzzle_utils import _clean_move_tokens
        assert _clean_move_tokens(["1...", "e4"]) == ["e4"]

    def test_handles_empty(self):
        from puzzle_utils import _clean_move_tokens
        assert _clean_move_tokens([]) == []
        assert _clean_move_tokens(["", "  "]) == []

    def test_handles_all_results(self):
        from puzzle_utils import _clean_move_tokens
        for r in ("1-0", "0-1", "1/2-1/2", "*"):
            assert _clean_move_tokens([r]) == []


class TestDetectMoveFormat:
    def test_detects_uci(self):
        from puzzle_utils import _detect_move_format
        assert _detect_move_format(["e2e4", "e7e5"]) == "uci"

    def test_detects_san(self):
        from puzzle_utils import _detect_move_format
        assert _detect_move_format(["e4", "Nf3"]) == "san"

    def test_detects_san_with_capture(self):
        from puzzle_utils import _detect_move_format
        assert _detect_move_format(["exd5"]) == "san"

    def test_detects_san_with_check(self):
        from puzzle_utils import _detect_move_format
        assert _detect_move_format(["Qh5+"]) == "san"

    def test_empty_returns_uci(self):
        from puzzle_utils import _detect_move_format
        assert _detect_move_format([]) == "uci"

    def test_uci_with_promotion(self):
        from puzzle_utils import _detect_move_format
        assert _detect_move_format(["e7e8q"]) == "uci"


class TestSanToUci:
    def test_basic_conversion(self):
        from puzzle_utils import _san_to_uci
        result = _san_to_uci(["e4", "e5", "Nf3"], "")
        assert result == ["e2e4", "e7e5", "g1f3"]

    def test_with_fen(self):
        from puzzle_utils import _san_to_uci
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        result = _san_to_uci(["e5"], fen)
        assert result == ["e7e5"]

    def test_handles_invalid_san(self):
        from puzzle_utils import _san_to_uci
        result = _san_to_uci(["Zz9"], "")
        assert result == []


class TestParseUciValue:
    def test_string_value(self):
        from puzzle_utils import _parse_uci_value
        result = _parse_uci_value("e2e4 e7e5 g1f3")
        assert result == ["e2e4", "e7e5", "g1f3"]

    def test_list_value(self):
        from puzzle_utils import _parse_uci_value
        result = _parse_uci_value(["e2e4", "e7e5"])
        assert result == ["e2e4", "e7e5"]

    def test_comma_separated(self):
        from puzzle_utils import _parse_uci_value
        result = _parse_uci_value("e2e4, e7e5")
        assert result == ["e2e4", "e7e5"]

    def test_empty_string(self):
        from puzzle_utils import _parse_uci_value
        result = _parse_uci_value("")
        assert result == []

    def test_none_in_list(self):
        from puzzle_utils import _parse_uci_value
        result = _parse_uci_value(["e2e4", None, "e7e5"])
        assert "e2e4" in result
        assert "e7e5" in result


class TestExtractUciMoves:
    def test_extracts_from_moves_column(self):
        from puzzle_utils import _extract_uci_moves
        row = {"moves": "e2e4 e7e5 g1f3", "fen": chess.STARTING_FEN}
        result = _extract_uci_moves(row)
        assert result == ["e2e4", "e7e5", "g1f3"]

    def test_extracts_from_uci_column(self):
        from puzzle_utils import _extract_uci_moves
        row = {"uci": "e2e4 e7e5", "fen": ""}
        result = _extract_uci_moves(row)
        assert result == ["e2e4", "e7e5"]

    def test_empty_moves(self):
        from puzzle_utils import _extract_uci_moves
        row = {"moves": "", "fen": ""}
        result = _extract_uci_moves(row)
        assert result == []

    def test_san_auto_conversion(self):
        from puzzle_utils import _extract_uci_moves
        row = {"moves": "1. e4 e5 2. Nf3", "fen": chess.STARTING_FEN}
        result = _extract_uci_moves(row)
        assert result == ["e2e4", "e7e5", "g1f3"]


class TestIsLichessFormat:
    def test_true_with_lichess_columns(self):
        from puzzle_utils import _is_lichess_format
        cols = ["PuzzleId", "FEN", "Moves", "Rating", "Themes", "GameUrl"]
        assert _is_lichess_format(cols) is True

    def test_false_with_generic_columns(self):
        from puzzle_utils import _is_lichess_format
        cols = ["name", "fen", "moves", "description"]
        assert _is_lichess_format(cols) is False

    def test_case_insensitive(self):
        from puzzle_utils import _is_lichess_format
        cols = ["puzzleid", "fen", "moves", "rating", "themes"]
        assert _is_lichess_format(cols) is True


class TestNormalizeLichessRow:
    def test_basic_normalization(self, sample_lichess_puzzle):
        from puzzle_utils import _normalize_lichess_row
        result = _normalize_lichess_row(sample_lichess_puzzle, 0)
        assert "fen" in result
        assert "moves" in result
        assert result["moves"] == ["e7e5", "d2d4", "e5d4"]
        assert result["id"] == "testPuzzle001"
        assert result["rating"] == 1500
        assert result["setup_count"] == 1  # Lichess convention

    def test_name_generation(self, sample_lichess_puzzle):
        from puzzle_utils import _normalize_lichess_row
        result = _normalize_lichess_row(sample_lichess_puzzle, 0)
        assert "Puzzle #1" in result["name"]

    def test_difficulty_is_float(self, sample_lichess_puzzle):
        from puzzle_utils import _normalize_lichess_row
        result = _normalize_lichess_row(sample_lichess_puzzle, 0)
        assert isinstance(result["difficulty"], float)
        assert 0.0 <= result["difficulty"] <= 1.0


class TestRatingCategory:
    def test_beginner(self):
        from puzzle_utils import _rating_category
        assert _rating_category(500) == "Beginner"

    def test_easy(self):
        from puzzle_utils import _rating_category
        assert _rating_category(1000) == "Easy"

    def test_medium(self):
        from puzzle_utils import _rating_category
        assert _rating_category(1400) == "Medium"

    def test_hard(self):
        from puzzle_utils import _rating_category
        assert _rating_category(1800) == "Hard"

    def test_expert(self):
        from puzzle_utils import _rating_category
        assert _rating_category(2200) == "Expert"

    def test_invalid_rating(self):
        from puzzle_utils import _rating_category
        assert _rating_category("invalid") == "Unknown"


class TestGenerateName:
    def test_with_opening_and_themes(self):
        from puzzle_utils import _generate_name
        row = {"opening": "Sicilian", "themes": "fork pin", "rating": 1500}
        name = _generate_name(row, ["e2e4"], 0)
        assert "Puzzle #1" in name
        assert "Sicilian" in name

    def test_with_name_field(self):
        from puzzle_utils import _generate_name
        row = {"name": "My Puzzle", "rating": 1000}
        name = _generate_name(row, ["e2e4"], 5)
        assert "My Puzzle" in name

    def test_fallback_with_moves(self):
        from puzzle_utils import _generate_name
        row = {}
        name = _generate_name(row, ["e2e4"], 0)
        assert "Puzzle #1" in name


class TestGenerateNameFallback:
    def test_with_extra_fields(self):
        from puzzle_utils import _generate_name_fallback
        row = {"color": "blue", "source": "test"}
        name = _generate_name_fallback(row, [], 0)
        assert "Puzzle #1" in name

    def test_with_no_data(self):
        from puzzle_utils import _generate_name_fallback
        name = _generate_name_fallback({}, [], 42)
        assert "Puzzle #43" in name

    def test_with_moves(self):
        from puzzle_utils import _generate_name_fallback
        name = _generate_name_fallback({}, ["e2e4", "e7e5"], 0)
        assert "e2e4" in name


class TestBatchCountMoves:
    def test_basic(self):
        from puzzle_utils import batch_count_moves
        result = batch_count_moves(["e2e4 e7e5", "g1f3", ""])
        np.testing.assert_array_equal(result, [2, 1, 0])

    def test_empty_list(self):
        from puzzle_utils import batch_count_moves
        result = batch_count_moves([])
        assert len(result) == 0


class TestBatchValidateUci:
    def test_valid_uci(self):
        from puzzle_utils import batch_validate_uci
        result = batch_validate_uci(["e2e4", "e7e8q"])
        assert result[0] is np.True_
        assert result[1] is np.True_

    def test_invalid_uci(self):
        from puzzle_utils import batch_validate_uci
        result = batch_validate_uci(["", "ab"])
        assert result[0] is np.False_

    def test_empty_list(self):
        from puzzle_utils import batch_validate_uci
        result = batch_validate_uci([])
        assert len(result) == 0


class TestGpuDifficultyScores:
    def test_fallback_produces_valid_scores(self):
        from puzzle_utils import gpu_difficulty_scores
        mc = np.array([1, 5, 10], dtype=np.int64)
        hf = np.array([True, False, True], dtype=np.bool_)
        hr = np.array([True, True, False], dtype=np.bool_)
        rv = np.array([1000.0, 2000.0, 0.0], dtype=np.float64)
        result = gpu_difficulty_scores(mc, hf, hr, rv)
        assert len(result) == 3
        assert all(0.0 <= v <= 1.0 for v in result)
        # Higher rating → higher difficulty
        assert result[1] > result[0]  # 2000 > 1000

    def test_empty_input(self):
        from puzzle_utils import gpu_difficulty_scores
        mc = np.array([], dtype=np.int64)
        hf = np.array([], dtype=np.bool_)
        hr = np.array([], dtype=np.bool_)
        rv = np.array([], dtype=np.float64)
        result = gpu_difficulty_scores(mc, hf, hr, rv)
        assert len(result) == 0


class TestComputeIterativeDifficulty:
    def test_basic(self):
        from puzzle_utils import _compute_iterative_difficulty
        row = {"rating": 1500, "fen": "some_fen"}
        result = _compute_iterative_difficulty(row, ["e2e4", "e7e5"])
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_no_rating(self):
        from puzzle_utils import _compute_iterative_difficulty
        row = {"fen": "some_fen"}
        result = _compute_iterative_difficulty(row, ["e2e4"])
        assert isinstance(result, float)

    def test_empty_moves(self):
        from puzzle_utils import _compute_iterative_difficulty
        row = {"rating": 1000, "fen": ""}
        result = _compute_iterative_difficulty(row, [])
        assert isinstance(result, float)
EOF

# --------------------------------------------------------
# test_puzzle_loader.py
# --------------------------------------------------------
cat << 'EOF' > test_puzzle_loader.py
"""Tests for puzzle_loader.py — loading, filtering, pagination."""

import json
import pytest

from puzzle_loader import PuzzleLoader, SORT_OPTIONS, SORT_DEFAULT


class TestLoadCSV:
    def test_load_csv_file(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        result = loader.load_csv(sample_puzzles_csv)
        assert len(result) == 4
        assert loader.total_count == 4

    def test_csv_puzzle_has_required_fields(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        for p in loader.puzzles:
            assert "fen" in p
            assert "moves" in p
            assert "name" in p
            assert "difficulty" in p


class TestLoadJSON:
    def test_load_json_list(self, sample_puzzles_json):
        loader = PuzzleLoader(use_vectorized=False)
        result = loader.load_json(sample_puzzles_json)
        assert len(result) == 2
        assert loader.total_count == 2

    def test_load_json_with_puzzles_key(self, tmp_path):
        data = {"puzzles": [
            {"fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
             "moves": "e2e4", "name": "Test"}
        ]}
        path = tmp_path / "test.json"
        path.write_text(json.dumps(data))
        loader = PuzzleLoader(use_vectorized=False)
        result = loader.load_json(str(path))
        assert len(result) == 1

    def test_load_json_single_puzzle(self, tmp_path):
        data = {"fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "moves": "e2e4", "name": "Single"}
        path = tmp_path / "single.json"
        path.write_text(json.dumps(data))
        loader = PuzzleLoader(use_vectorized=False)
        result = loader.load_json(str(path))
        assert len(result) == 1


class TestLoadPGN:
    def test_load_pgn_file(self, sample_pgn):
        loader = PuzzleLoader(use_vectorized=False)
        result = loader.load_pgn(sample_pgn)
        assert len(result) == 1
        assert len(result[0]["moves"]) > 0


class TestLoadFile:
    def test_auto_detect_csv(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        result = loader.load_file(sample_puzzles_csv)
        assert len(result) == 4

    def test_auto_detect_json(self, sample_puzzles_json):
        loader = PuzzleLoader(use_vectorized=False)
        result = loader.load_file(sample_puzzles_json)
        assert len(result) == 2


class TestFiltering:
    def test_filter_by_min_rating(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.set_filters({"min_rating": 1000})
        assert loader.filtered_count < loader.total_count

    def test_filter_by_max_rating(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.set_filters({"max_rating": 1100})
        assert loader.filtered_count < loader.total_count

    def test_filter_by_theme(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.set_filters({"theme": "fork"})
        assert loader.filtered_count < loader.total_count

    def test_filter_by_search(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.set_filters({"search": "Sicilian"})
        assert loader.filtered_count >= 1

    def test_clear_filters(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.set_filters({"min_rating": 5000})
        loader.clear_filters()
        assert loader.filtered_count == loader.total_count

    def test_empty_filters(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.set_filters({})
        assert loader.filtered_count == loader.total_count


class TestPagination:
    def test_default_page(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        assert loader.current_page == 0
        assert len(loader.puzzles) > 0

    def test_total_pages(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        assert loader.total_pages >= 1

    def test_page_size_change(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.page_size = 2
        assert loader.page_size == 2
        assert loader.current_page == 0  # Reset to page 0

    def test_go_to_page(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.page_size = 2
        if loader.total_pages > 1:
            loader.go_to_page(1)
            assert loader.current_page == 1

    def test_go_to_invalid_page(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.go_to_page(999)
        assert loader.current_page == loader.total_pages - 1

    def test_next_page(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.page_size = 2
        if loader.total_pages > 1:
            result = loader.next_page()
            assert result is True
            assert loader.current_page == 1

    def test_next_page_at_end(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.go_to_page(loader.total_pages - 1)
        result = loader.next_page()
        assert result is False

    def test_prev_page(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.page_size = 2
        if loader.total_pages > 1:
            loader.go_to_page(1)
            result = loader.prev_page()
            assert result is True
            assert loader.current_page == 0

    def test_prev_page_at_start(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        result = loader.prev_page()
        assert result is False

    def test_first_and_last_page(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.page_size = 2
        loader.last_page()
        assert loader.current_page == loader.total_pages - 1
        loader.first_page()
        assert loader.current_page == 0


class TestSorting:
    def test_sort_by_rating_desc(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.sort_by = "rating_desc"
        assert loader.sort_by == "rating_desc"

    def test_sort_random(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.sort_by = "random"
        assert loader.sort_by == "random"

    def test_invalid_sort_defaults(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.sort_by = "invalid_key"
        assert loader.sort_by == SORT_DEFAULT


class TestRandomPuzzle:
    def test_get_random_puzzle(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        puzzle = loader.get_random_puzzle()
        assert puzzle is not None
        assert "fen" in puzzle

    def test_get_random_with_no_puzzles(self):
        loader = PuzzleLoader(use_vectorized=False)
        puzzle = loader.get_random_puzzle()
        assert puzzle is None


class TestGetPuzzleById:
    def test_find_existing_puzzle(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        if loader.puzzles:
            pid = loader.puzzles[0].get("id", "")
            if pid:
                found = loader.get_puzzle_by_id(pid)
                assert found is not None

    def test_find_nonexistent_puzzle(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        found = loader.get_puzzle_by_id("nonexistent_id_xyz")
        assert found is None


class TestHasPuzzles:
    def test_no_puzzles_initially(self):
        loader = PuzzleLoader(use_vectorized=False)
        assert loader.has_puzzles is False

    def test_has_puzzles_after_load(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        assert loader.has_puzzles is True


class TestClose:
    def test_close_without_lazy_store(self, sample_puzzles_csv):
        loader = PuzzleLoader(use_vectorized=False)
        loader.load_csv(sample_puzzles_csv)
        loader.close()

    def test_close_with_lazy_store(self):
        loader = PuzzleLoader(use_vectorized=False)
        loader.close()
EOF

# --------------------------------------------------------
# test_sound_manager.py
# --------------------------------------------------------
cat << 'EOF' > test_sound_manager.py
"""Tests for sound_manager.py — audio generation and management."""

import os
import wave
import tempfile

import numpy as np
import pytest


class TestAudioPrimitives:
    """Test the low-level audio signal generation functions."""

    def test_sin_produces_correct_length(self):
        from sound_manager import _sin
        sr = 44100
        samples = _sin(440, 0.1, 0.5, sr)
        assert len(samples) == int(sr * 0.1)

    def test_sin_amplitude_within_range(self):
        from sound_manager import _sin
        samples = _sin(440, 0.1, 0.5, 44100)
        assert np.max(np.abs(samples)) <= 32768

    def test_sweep_produces_correct_length(self):
        from sound_manager import _sweep
        sr = 44100
        samples = _sweep(200, 800, 0.1, 0.5, sr)
        assert len(samples) == int(sr * 0.1)

    def test_square_produces_correct_length(self):
        from sound_manager import _square
        samples = _square(440, 0.1, 0.5, 44100)
        assert len(samples) == int(44100 * 0.1)

    def test_triangle_produces_correct_length(self):
        from sound_manager import _triangle
        samples = _triangle(440, 0.1, 0.5, 44100)
        assert len(samples) == int(44100 * 0.1)

    def test_env_applies_attack(self):
        from sound_manager import _sin, _env
        samples = _sin(440, 0.1, 0.5, 44100)
        env_samples = _env(samples, 0.01, 0.02, 44100)
        assert abs(env_samples[0]) < abs(samples[0]) + 1

    def test_env_doesnt_change_length(self):
        from sound_manager import _sin, _env
        samples = _sin(440, 0.1, 0.5, 44100)
        env_samples = _env(samples, 0.01, 0.02, 44100)
        assert len(env_samples) == len(samples)

    def test_mix_combines_signals(self):
        from sound_manager import _sin, _mix
        a = _sin(440, 0.05, 0.3, 44100)
        b = _sin(880, 0.05, 0.3, 44100)
        mixed = _mix(a, b)
        assert len(mixed) == max(len(a), len(b))

    def test_mix_different_lengths(self):
        from sound_manager import _sin, _mix
        a = _sin(440, 0.05, 0.3, 44100)
        b = _sin(880, 0.10, 0.3, 44100)
        mixed = _mix(a, b)
        assert len(mixed) == max(len(a), len(b))

    def test_to_i16_clips_values(self):
        from sound_manager import _to_i16
        large = np.array([40000.0, -40000.0, 0.0, 1000.0])
        result = _to_i16(large)
        assert result[0] == 32767  # Clipped
        assert result[1] == -32768  # Clipped
        assert result[2] == 0
        assert result.dtype == np.int16

    def test_to_i16_output_type(self):
        from sound_manager import _to_i16
        samples = np.array([0.0, 100.0, -100.0])
        result = _to_i16(samples)
        assert result.dtype == np.int16


class TestWavWriting:
    def test_wav_file_creation(self, tmp_path):
        from sound_manager import SoundManager, _sin, _env
        samples = _env(_sin(440, 0.1, 0.5), 0.01, 0.02)
        path = str(tmp_path / "test.wav")
        SoundManager._wav(path, samples)
        assert os.path.exists(path)

    def test_wav_file_is_valid(self, tmp_path):
        from sound_manager import SoundManager, _sin, _env
        samples = _env(_sin(440, 0.1, 0.5), 0.01, 0.02)
        path = str(tmp_path / "test.wav")
        SoundManager._wav(path, samples)
        with wave.open(path, "r") as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == 44100
            assert w.getnframes() > 0


class TestSoundManager:
    def test_initialization(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager()
        assert sm.pack == "Classic"
        assert sm._enabled is True
        assert sm._volume == 0.7

    def test_set_volume(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager()
        sm.set_volume(0.5)
        assert sm._volume == 0.5
        sm.set_volume(1.5)
        assert sm._volume == 1.0  # Clamped
        sm.set_volume(-0.5)
        assert sm._volume == 0.0  # Clamped

    def test_set_enabled(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager()
        sm.set_enabled(False)
        assert sm._enabled is False
        sm.set_enabled(True)
        assert sm._enabled is True

    def test_set_effect_enabled(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager()
        sm.set_effect_enabled("move", False)
        assert sm._effect_enabled["move"] is False
        sm.set_effect_enabled("move", True)
        assert sm._effect_enabled["move"] is True

    def test_switch_pack(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager()
        sm.switch_pack("Digital")
        assert sm.pack == "Digital"
        sm.switch_pack("Wooden")
        assert sm.pack == "Wooden"
        sm.switch_pack("Arcade")
        assert sm.pack == "Arcade"
        sm.switch_pack("Classic")
        assert sm.pack == "Classic"

    def test_switch_pack_same_does_nothing(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager()
        original_pack = sm.pack
        sm.switch_pack("Classic")  # Already Classic
        assert sm.pack == original_pack

    def test_switch_pack_unknown_defaults_classic(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager()
        sm.switch_pack("NonExistentPack")
        assert sm.pack == "Classic"

    def test_play_when_disabled(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager()
        sm.set_enabled(False)
        sm.play("move")  # Should not raise

    def test_play_with_effect_disabled(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager()
        sm.set_effect_enabled("move", False)
        sm.play("move")  # Should not raise

    def test_play_nonexistent_effect(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager()
        sm.play("nonexistent_effect")  # Should not raise

    def test_all_packs_generate_files(self, qapp):
        from sound_manager import SoundManager, SOUND_EFFECTS
        for pack in SoundManager.PACKS:
            sm = SoundManager(pack=pack)
            for effect in SOUND_EFFECTS:
                path = os.path.join(sm.tmpdir, f"{effect}.wav")
                assert os.path.exists(path), f"{effect}.wav missing for pack {pack}"
            sm.cleanup()

    def test_cleanup_removes_temp_dir(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager()
        tmpdir = sm.tmpdir
        assert os.path.exists(tmpdir)
        sm.cleanup()
        assert not os.path.exists(tmpdir)

    def test_pack_property(self, qapp):
        from sound_manager import SoundManager
        sm = SoundManager(pack="Digital")
        assert sm.pack == "Digital"
        sm.switch_pack("Arcade")
        assert sm.pack == "Arcade"
        sm.cleanup()

    def test_effect_checks_dict_populated(self, qapp):
        from sound_manager import SoundManager, SOUND_EFFECTS
        sm = SoundManager()
        for effect in SOUND_EFFECTS:
            assert effect in sm._effect_enabled
            assert sm._effect_enabled[effect] is True
        sm.cleanup()
EOF

# --------------------------------------------------------
# test_board_widget.py
# --------------------------------------------------------
cat << 'EOF' > test_board_widget.py
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
EOF

# --------------------------------------------------------
# test_config.py
# --------------------------------------------------------
cat << 'EOF' > test_config.py
"""Tests for config.py — configuration objects, presets, manifest."""

import os
import json
import tempfile

import pytest


class TestBoardTheme:
    def test_default_theme(self):
        from config import BoardTheme
        theme = BoardTheme()
        assert theme.name == "Classic"
        assert theme.light_sq is not None
        assert theme.dark_sq is not None

    def test_custom_theme(self):
        from config import BoardTheme
        theme = BoardTheme("Test", (255, 255, 255), (0, 0, 0))
        assert theme.name == "Test"


class TestThemes:
    def test_all_themes_present(self):
        from config import THEMES
        expected = {"Classic", "Blue", "Green", "Brown", "Purple", "Ice", "Midnight"}
        assert set(THEMES.keys()) == expected

    def test_themes_have_required_attributes(self):
        from config import THEMES
        for name, theme in THEMES.items():
            assert theme.name
            assert theme.light_sq is not None
            assert theme.dark_sq is not None
            assert theme.highlight is not None
            assert theme.last_move is not None
            assert theme.arrow_clr is not None


class TestLayoutMode:
    def test_constants(self):
        from config import LayoutMode
        assert LayoutMode.BOARD_ONLY == "board_only"
        assert LayoutMode.BOARD_MOVES_RIGHT == "board_moves_right"
        assert LayoutMode.BOARD_MOVES_BOTTOM == "board_moves_bottom"


class TestExportPreset:
    def test_preset_properties(self):
        from config import ExportPreset, LayoutMode
        p = ExportPreset("Test", 1920, 1080, 30, 0.75, (26, 27, 46), "Test preset")
        assert p.name == "Test"
        assert p.width == 1920
        assert p.height == 1080
        assert p.fps == 30
        assert p.bitrate == 10000
        assert p.aspect_ratio == (16, 9)
        assert p.is_vertical is False
        assert p.is_square is False

    def test_square_preset(self):
        from config import ExportPreset
        p = ExportPreset("Square", 544, 544)
        assert p.is_square is True
        assert p.is_vertical is False

    def test_vertical_preset(self):
        from config import ExportPreset
        p = ExportPreset("Vertical", 1080, 1920)
        assert p.is_vertical is True

    def test_calc_sq_size_board_only(self):
        from config import ExportPreset, LayoutMode
        p = ExportPreset("Test", 544, 544, layout=LayoutMode.BOARD_ONLY)
        sq = p.calc_sq_size()
        assert sq > 0
        assert sq * 8 <= 544

    def test_calc_sq_size_moves_right(self):
        from config import ExportPreset, LayoutMode
        p = ExportPreset("Test", 1920, 1080, layout=LayoutMode.BOARD_MOVES_RIGHT)
        sq = p.calc_sq_size()
        assert sq > 0

    def test_calc_sq_size_moves_bottom(self):
        from config import ExportPreset, LayoutMode
        p = ExportPreset("Test", 1080, 1920, layout=LayoutMode.BOARD_MOVES_BOTTOM)
        sq = p.calc_sq_size()
        assert sq > 0


class TestExportPresets:
    def test_all_presets_present(self):
        from config import EXPORT_PRESETS
        assert "YouTube 1080p (1920×1080)" in EXPORT_PRESETS
        assert "Board Only (544×544)" in EXPORT_PRESETS
        assert "Custom" in EXPORT_PRESETS

    def test_preset_bitrates(self):
        from config import EXPORT_PRESETS
        for name, preset in EXPORT_PRESETS.items():
            assert preset.bitrate > 0, f"Preset {name} has no bitrate"


class TestExportConfig:
    def test_defaults(self):
        from config import ExportConfig
        cfg = ExportConfig()
        assert cfg.fps == 30
        assert cfg.title_enabled is True
        assert cfg.move_speed == 1.0
        assert cfg.pause_after_move == 0.5
        assert cfg.loop_count == 1
        assert cfg.sq_size == 68

    def test_apply_preset(self):
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.apply_preset("YouTube 1080p (1920×1080)")
        assert cfg.target_width == 1920
        assert cfg.target_height == 1080
        assert cfg.preset_name == "YouTube 1080p (1920×1080)"

    def test_apply_custom_preset(self):
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.apply_preset("Custom")
        assert cfg.preset_name == "Custom"

    def test_to_dict_load_dict_roundtrip(self):
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.title_text = "My Puzzle"
        cfg.move_speed = 2.0
        d = cfg.to_dict()
        assert d["title_text"] == "My Puzzle"
        assert d["move_speed"] == 2.0
        cfg2 = ExportConfig()
        cfg2.load_dict(d)
        assert cfg2.title_text == "My Puzzle"
        assert cfg2.move_speed == 2.0

    def test_load_dict_with_invalid_data(self):
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.load_dict(None)
        cfg.load_dict({})
        cfg.load_dict("invalid")

    def test_load_dict_background_color(self):
        from config import ExportConfig
        cfg = ExportConfig()
        d = {"background_color": [100, 100, 100]}
        cfg.load_dict(d)
        assert cfg.background_color == (100, 100, 100)

    def test_effective_sq_size(self):
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.apply_preset("YouTube 1080p (1920×1080)")
        sq = cfg.effective_sq_size
        assert sq > 0

    def test_is_vertical(self):
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.target_width = 1080
        cfg.target_height = 1920
        assert cfg.is_vertical is True

    def test_effective_bitrate(self):
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.apply_preset("YouTube 1080p (1920×1080)")
        assert cfg.effective_bitrate == 10000

    def test_move_anim_duration(self):
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.move_speed = 2.5
        assert cfg.move_anim_duration == 2.5

    def test_move_panel_width(self):
        from config import ExportConfig, LayoutMode
        cfg = ExportConfig()
        cfg.layout_mode = LayoutMode.BOARD_MOVES_RIGHT
        cfg.apply_preset("YouTube 1080p (1920×1080)")
        pw = cfg.move_panel_width
        assert pw > 0

    def test_move_panel_height(self):
        from config import ExportConfig, LayoutMode
        cfg = ExportConfig()
        cfg.layout_mode = LayoutMode.BOARD_MOVES_BOTTOM
        cfg.apply_preset("Shorts 1080p (1080×1920)")
        ph = cfg.move_panel_height
        assert ph > 0

    def test_move_panel_width_board_only(self):
        from config import ExportConfig, LayoutMode
        cfg = ExportConfig()
        cfg.layout_mode = LayoutMode.BOARD_ONLY
        assert cfg.move_panel_width == 0

    def test_estimate_duration(self):
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.title_text = "Test"
        cfg.end_text = "Solved!"
        duration = cfg.estimate_duration(5)
        assert duration > 0
        expected_min = cfg.title_duration + cfg.position_hold_duration + 5 * (cfg.move_anim_duration + cfg.pause_after_move) + cfg.end_duration
        assert duration >= expected_min


class TestExportManifest:
    def test_mark_and_check_exported(self, tmp_path):
        from config import ExportManifest
        db_path = str(tmp_path / "test_manifest.duckdb")
        manifest = ExportManifest(db_path)
        manifest.mark_exported("puzzle_001", "/output/video.mp4", "1080p", "Test Puzzle")
        assert manifest.is_exported("puzzle_001") is True
        assert manifest.is_exported("puzzle_002") is False
        manifest.close()

    def test_get_exported_ids(self, tmp_path):
        from config import ExportManifest
        db_path = str(tmp_path / "test_manifest2.duckdb")
        manifest = ExportManifest(db_path)
        manifest.mark_exported("p1")
        manifest.mark_exported("p2")
        manifest.mark_exported("p3")
        ids = manifest.get_exported_ids(["p1", "p2", "p4"])
        assert "p1" in ids
        assert "p2" in ids
        assert "p4" not in ids
        manifest.close()

    def test_get_exported_ids_empty(self, tmp_path):
        from config import ExportManifest
        db_path = str(tmp_path / "test_manifest3.duckdb")
        manifest = ExportManifest(db_path)
        ids = manifest.get_exported_ids([])
        assert ids == set()
        manifest.close()

    def test_get_info(self, tmp_path):
        from config import ExportManifest
        db_path = str(tmp_path / "test_manifest4.duckdb")
        manifest = ExportManifest(db_path)
        manifest.mark_exported("p1", "/out/video.mp4", "1080p", "My Puzzle")
        info = manifest.get_info("p1")
        assert info is not None
        assert info["path"] == "/out/video.mp4"
        assert info["preset_name"] == "1080p"
        manifest.close()

    def test_get_info_nonexistent(self, tmp_path):
        from config import ExportManifest
        db_path = str(tmp_path / "test_manifest5.duckdb")
        manifest = ExportManifest(db_path)
        info = manifest.get_info("nonexistent")
        assert info is None
        manifest.close()

    def test_overwrite_export(self, tmp_path):
        from config import ExportManifest
        db_path = str(tmp_path / "test_manifest6.duckdb")
        manifest = ExportManifest(db_path)
        manifest.mark_exported("p1", "/old.mp4")
        manifest.mark_exported("p1", "/new.mp4")
        info = manifest.get_info("p1")
        assert info["path"] == "/new.mp4"
        manifest.close()


class TestGetPuzzleId:
    def test_with_valid_id(self):
        from config import _get_puzzle_id
        puzzle = {"id": "abc123", "fen": "some_fen", "moves": ["e2e4"]}
        pid = _get_puzzle_id(puzzle)
        assert pid == "abc123"

    def test_with_empty_id(self):
        from config import _get_puzzle_id
        puzzle = {"id": "", "fen": "some_fen", "moves": ["e2e4"]}
        pid = _get_puzzle_id(puzzle)
        assert len(pid) == 16

    def test_with_nan_id(self):
        from config import _get_puzzle_id
        puzzle = {"id": "nan", "fen": "some_fen", "moves": ["e2e4"]}
        pid = _get_puzzle_id(puzzle)
        assert len(pid) == 16

    def test_with_no_id(self):
        from config import _get_puzzle_id
        puzzle = {"fen": "some_fen", "moves": ["e2e4"]}
        pid = _get_puzzle_id(puzzle)
        assert len(pid) == 16

    def test_deterministic_for_same_data(self):
        from config import _get_puzzle_id
        puzzle = {"fen": "same_fen", "moves": ["e2e4"]}
        pid1 = _get_puzzle_id(puzzle)
        pid2 = _get_puzzle_id(puzzle)
        assert pid1 == pid2


class TestMoveListColors:
    def test_has_required_keys(self):
        from config import MOVE_LIST_COLORS
        required = {"bg", "text", "dim", "accent", "border"}
        assert required.issubset(set(MOVE_LIST_COLORS.keys()))


class TestResolutionBitrates:
    def test_known_resolutions(self):
        from config import RESOLUTION_BITRATES
        assert (1920, 1080) in RESOLUTION_BITRATES
        assert (3840, 2160) in RESOLUTION_BITRATES

    def test_bitrate_values_reasonable(self):
        from config import RESOLUTION_BITRATES
        for res, bitrate in RESOLUTION_BITRATES.items():
            assert bitrate > 0
            assert bitrate < 100000
EOF

# --------------------------------------------------------
# test_utils.py
# --------------------------------------------------------
cat << 'EOF' > test_utils.py
"""Tests for utils.py — utility functions, difficulty, easing."""

import numpy as np
import pytest


class TestSanitizeFilename:
    def test_normal_string(self):
        from utils import sanitize_filename
        assert sanitize_filename("hello world") == "hello world"

    def test_special_characters(self):
        from utils import sanitize_filename
        result = sanitize_filename('file*name?.txt')
        assert "*" not in result
        assert "?" not in result

    def test_empty_string(self):
        from utils import sanitize_filename
        assert sanitize_filename("") == "untitled"

    def test_long_string_truncated(self):
        from utils import sanitize_filename
        long_name = "a" * 200
        result = sanitize_filename(long_name, max_len=50)
        assert len(result) <= 50

    def test_dots_and_spaces_stripped(self):
        from utils import sanitize_filename
        result = sanitize_filename("  .test.  ")
        assert not result.startswith(".")
        assert not result.startswith(" ")

    def test_path_separators(self):
        from utils import sanitize_filename
        result = sanitize_filename("path/to\\file")
        assert "/" not in result
        assert "\\" not in result


class TestEaseOutCubic:
    def test_at_zero(self):
        from utils import ease_out_cubic
        assert ease_out_cubic(0.0) == 0.0

    def test_at_one(self):
        from utils import ease_out_cubic
        assert ease_out_cubic(1.0) == 1.0

    def test_monotonically_increasing(self):
        from utils import ease_out_cubic
        prev = 0.0
        for t in [i / 100 for i in range(1, 101)]:
            val = ease_out_cubic(t)
            assert val >= prev
            prev = val

    def test_midpoint_greater_than_linear(self):
        from utils import ease_out_cubic
        assert ease_out_cubic(0.25) > 0.25


class TestComputeDifficulty:
    def test_zero_moves_no_fen_no_rating(self):
        from utils import compute_difficulty
        result = compute_difficulty(0, False, False, 0)
        assert result == 0.5

    def test_many_moves(self):
        from utils import compute_difficulty
        result = compute_difficulty(10, True, True, 3000)
        assert result > 0.8

    def test_with_fen_bonus(self):
        from utils import compute_difficulty
        without = compute_difficulty(1, False, False, 0)
        with_fen = compute_difficulty(1, True, False, 0)
        assert with_fen > without

    def test_with_rating_bonus(self):
        from utils import compute_difficulty
        low = compute_difficulty(1, False, True, 500)
        high = compute_difficulty(1, False, True, 2500)
        assert high > low

    def test_result_in_range(self):
        from utils import compute_difficulty
        for mc in [0, 1, 5, 10, 100]:
            for hf in [True, False]:
                for hr in [True, False]:
                    for rv in [0, 500, 1500, 3000]:
                        result = compute_difficulty(mc, hf, hr, rv)
                        assert 0.0 <= result <= 1.0, \
                            f"Out of range: mc={mc}, hf={hf}, hr={hr}, rv={rv}"


class TestFixStride:
    def test_no_padding(self):
        from utils import fix_stride
        h, w = 4, 4
        raw = np.arange(h * w * 3, dtype=np.uint8).reshape(h, w * 3)
        result = fix_stride(raw, w, h, w * 3)
        assert result.shape == (h, w, 3)

    def test_with_padding(self):
        from utils import fix_stride
        h, w = 4, 4
        bpl = w * 3 + 8
        raw = np.zeros((h, bpl), dtype=np.uint8)
        for row in range(h):
            for col in range(w * 3):
                raw[row, col] = (row * w * 3 + col) % 256
        result = fix_stride(raw, w, h, bpl)
        assert result.shape == (h, w, 3)

    def test_preserves_data(self):
        from utils import fix_stride
        h, w = 2, 3
        raw = np.arange(h * w * 3, dtype=np.uint8).reshape(h, w * 3)
        result = fix_stride(raw, w, h, w * 3)
        np.testing.assert_array_equal(result.reshape(h, w * 3), raw)


class TestLog:
    def test_log_does_not_raise(self):
        from utils import log
        log("Test message", "TEST")
        log("Another message")


class TestParseOpeningImage:
    def test_none_input(self):
        from utils import parse_opening_image
        assert parse_opening_image(None) is None

    def test_invalid_string(self):
        from utils import parse_opening_image
        assert parse_opening_image("not a dict") is None

    def test_dict_without_bytes(self):
        from utils import parse_opening_image
        assert parse_opening_image({"other_key": "value"}) is None

    def test_dict_with_invalid_bytes(self):
        from utils import parse_opening_image
        assert parse_opening_image({"bytes": "not_valid_base64!!!"}) is None


class TestGetRenderAssets:
    def test_returns_tuple(self, qapp):
        from utils import get_render_assets
        assets = get_render_assets(68)
        assert isinstance(assets, tuple)
        assert len(assets) == 5

    def test_caching(self, qapp):
        from utils import get_render_assets
        a1 = get_render_assets(68)
        a2 = get_render_assets(68)
        assert a1 is a2

    def test_different_size_different_assets(self, qapp):
        from utils import get_render_assets
        a1 = get_render_assets(68)
        a2 = get_render_assets(80)
        assert a1 is not a2


class TestDependencyChecks:
    def test_has_numba_is_bool(self):
        from utils import HAS_NUMBA
        assert isinstance(HAS_NUMBA, bool)

    def test_has_cupy_is_bool(self):
        from utils import HAS_CUPY
        assert isinstance(HAS_CUPY, bool)

    def test_has_pandas_is_bool(self):
        from utils import HAS_PANDAS
        assert isinstance(HAS_PANDAS, bool)

    def test_has_pyarrow_is_bool(self):
        from utils import HAS_PYARROW
        assert isinstance(HAS_PYARROW, bool)

    def test_has_duckdb_is_bool(self):
        from utils import HAS_DUCKDB
        assert isinstance(HAS_DUCKDB, bool)

    def test_has_ffmpeg_is_bool(self):
        from utils import HAS_FFMPEG
        assert isinstance(HAS_FFMPEG, bool)
EOF

# --------------------------------------------------------
# test_video_exporter.py
# --------------------------------------------------------
cat << 'EOF' > test_video_exporter.py
"""Tests for video_exporter.py — post-processing, FFmpeg commands, frame estimation."""

import os
import wave

import numpy as np
import pytest
import chess

from utils import HAS_FFMPEG


class TestPostProcessing:
    def test_apply_vignette(self):
        from video_exporter import _apply_vignette
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        result = _apply_vignette(frame, strength=0.25)
        assert result.shape == frame.shape
        assert result.dtype == np.uint8
        center_val = int(result[50, 50, 0])
        corner_val = int(result[0, 0, 0])
        assert center_val >= corner_val

    def test_apply_vignette_zero_strength(self):
        from video_exporter import _apply_vignette
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        result = _apply_vignette(frame, strength=0.0)
        np.testing.assert_array_equal(result, frame)

    def test_apply_contrast(self):
        from video_exporter import _apply_contrast
        frame = np.full((10, 10, 3), 128, dtype=np.uint8)
        result = _apply_contrast(frame, contrast=1.5)
        assert result.shape == frame.shape
        assert result.dtype == np.uint8

    def test_apply_contrast_identity(self):
        from video_exporter import _apply_contrast
        frame = np.full((10, 10, 3), 128, dtype=np.uint8)
        result = _apply_contrast(frame, contrast=1.0)
        np.testing.assert_array_equal(result, frame)

    def test_apply_saturation(self):
        from video_exporter import _apply_saturation
        frame = np.full((10, 10, 3), 128, dtype=np.uint8)
        result = _apply_saturation(frame, saturation=1.5)
        assert result.shape == frame.shape
        assert result.dtype == np.uint8

    def test_apply_saturation_identity(self):
        from video_exporter import _apply_saturation
        frame = np.full((10, 10, 3), 128, dtype=np.uint8)
        result = _apply_saturation(frame, saturation=1.0)
        np.testing.assert_array_equal(result, frame)

    def test_apply_post_process_disabled(self):
        from video_exporter import _apply_post_process
        from config import ExportConfig
        frame = np.full((10, 10, 3), 128, dtype=np.uint8)
        cfg = ExportConfig()
        cfg.gpu_post_process = False
        result = _apply_post_process(frame, cfg)
        np.testing.assert_array_equal(result, frame)

    def test_apply_post_process_enabled(self):
        from video_exporter import _apply_post_process
        from config import ExportConfig
        frame = np.full((10, 10, 3), 100, dtype=np.uint8)
        cfg = ExportConfig()
        cfg.gpu_post_process = True
        cfg.gpu_contrast = 1.1
        cfg.gpu_saturation = 1.1
        cfg.gpu_vignette = 0.1
        result = _apply_post_process(frame, cfg)
        assert result.shape == frame.shape

    def test_apply_post_process_no_changes(self):
        from video_exporter import _apply_post_process
        from config import ExportConfig
        frame = np.full((10, 10, 3), 128, dtype=np.uint8)
        cfg = ExportConfig()
        cfg.gpu_post_process = True
        cfg.gpu_contrast = 1.0
        cfg.gpu_saturation = 1.0
        cfg.gpu_vignette = 0.0
        result = _apply_post_process(frame, cfg)
        np.testing.assert_array_equal(result, frame)


class TestSilentWav:
    def test_generate_silent_wav(self, tmp_path):
        from video_exporter import _generate_silent_wav
        path = str(tmp_path / "silent.wav")
        _generate_silent_wav(path, 2.0)
        assert os.path.exists(path)
        with wave.open(path, "r") as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == 44100
            duration = w.getnframes() / w.getframerate()
            assert abs(duration - 2.0) < 0.1

    def test_generate_silent_wav_short(self, tmp_path):
        from video_exporter import _generate_silent_wav
        path = str(tmp_path / "short.wav")
        _generate_silent_wav(path, 0.1)
        assert os.path.exists(path)


class TestFFmpegCommand:
    def test_build_ffmpeg_cmd(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.apply_preset("YouTube 1080p (1920×1080)")
        exporter = FFmpegVideoExporter(cfg)
        cmd = exporter._build_ffmpeg_cmd("output.mp4", 1920, 1080)
        assert cmd[0] == "ffmpeg"
        assert "-y" in cmd
        assert "libx264" in cmd
        assert "output.mp4" in cmd

    def test_build_ffmpeg_cmd_includes_resolution(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.apply_preset("YouTube 1080p (1920×1080)")
        exporter = FFmpegVideoExporter(cfg)
        cmd = exporter._build_ffmpeg_cmd("out.mp4", 1920, 1080)
        assert "1920x1080" in cmd

    def test_build_ffmpeg_cmd_includes_bitrate(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.apply_preset("YouTube 1080p (1920×1080)")
        exporter = FFmpegVideoExporter(cfg)
        cmd = exporter._build_ffmpeg_cmd("out.mp4", 1920, 1080)
        assert any("10000k" in arg for arg in cmd)

    def test_build_ffmpeg_cmd_4k_level(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.apply_preset("YouTube 4K (3840×2160)")
        exporter = FFmpegVideoExporter(cfg)
        cmd = exporter._build_ffmpeg_cmd("out.mp4", 3840, 2160)
        assert "5.1" in cmd

    def test_build_ffmpeg_cmd_1080p_level(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.apply_preset("YouTube 1080p (1920×1080)")
        exporter = FFmpegVideoExporter(cfg)
        cmd = exporter._build_ffmpeg_cmd("out.mp4", 1920, 1080)
        assert "4.2" in cmd


class TestEstimateFrameCount:
    def test_basic_estimate(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        exporter = FFmpegVideoExporter(cfg)
        est = exporter._estimate_frame_count(5)
        assert est > 0

    def test_estimate_includes_title(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.title_enabled = True
        cfg.title_text = "Test"
        cfg.title_duration = 3.0
        exporter = FFmpegVideoExporter(cfg)
        with_title = exporter._estimate_frame_count(5)

        cfg2 = ExportConfig()
        cfg2.title_enabled = False
        exporter2 = FFmpegVideoExporter(cfg2)
        without_title = exporter2._estimate_frame_count(5)

        assert with_title > without_title

    def test_estimate_includes_end(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        cfg.end_enabled = True
        cfg.end_text = "Solved!"
        exporter = FFmpegVideoExporter(cfg)
        with_end = exporter._estimate_frame_count(5)

        cfg2 = ExportConfig()
        cfg2.end_enabled = False
        exporter2 = FFmpegVideoExporter(cfg2)
        without_end = exporter2._estimate_frame_count(5)

        assert with_end > without_end

    def test_estimate_zero_moves(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        exporter = FFmpegVideoExporter(cfg)
        est = exporter._estimate_frame_count(0)
        assert est >= 1


class TestPrecalcSanMoves:
    def test_basic_conversion(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        exporter = FFmpegVideoExporter(cfg)
        sans = exporter._precalc_san_moves(chess.STARTING_FEN, ["e2e4", "e7e5", "g1f3"])
        assert sans == ["e4", "e5", "Nf3"]

    def test_empty_moves(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        exporter = FFmpegVideoExporter(cfg)
        sans = exporter._precalc_san_moves(chess.STARTING_FEN, [])
        assert sans == []

    def test_invalid_move(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        exporter = FFmpegVideoExporter(cfg)
        sans = exporter._precalc_san_moves(chess.STARTING_FEN, ["e2e5"])
        assert sans == ["e2e5"]


class TestIsKeyMove:
    def test_capture_is_key(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        from chess_engine import ChessEngine
        cfg = ExportConfig()
        exporter = FFmpegVideoExporter(cfg)
        engine = ChessEngine()
        engine.make_move_uci("e2e4")
        engine.make_move_uci("d7d5")
        assert exporter._is_key_move(engine, "e4d5") is True

    def test_normal_move_not_key(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        from chess_engine import ChessEngine
        cfg = ExportConfig()
        exporter = FFmpegVideoExporter(cfg)
        engine = ChessEngine()
        assert exporter._is_key_move(engine, "e2e4") is False


class TestExporterCancel:
    def test_cancel(self):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        exporter = FFmpegVideoExporter(cfg)
        assert exporter._cancel is False
        exporter.cancel()
        assert exporter._cancel is True


@pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg not installed")
class TestExporterWithFFmpeg:
    def test_export_puzzle_no_ffmpeg_error(self, qapp):
        from video_exporter import FFmpegVideoExporter
        from config import ExportConfig
        cfg = ExportConfig()
        exporter = FFmpegVideoExporter(cfg)
        puzzle = {
            "fen": chess.STARTING_FEN,
            "moves": ["e2e4", "e7e5"],
            "name": "Test Puzzle",
            "setup_count": 0,
        }
        assert exporter._estimate_frame_count(2) > 0
EOF

# --------------------------------------------------------
# test_main_window.py
# --------------------------------------------------------
cat << 'EOF' > test_main_window.py
"""Tests for main_window.py — window creation and basic UI interactions."""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

from PySide6.QtWidgets import QSplitter, QTabWidget, QListWidget
from PySide6.QtCore import Qt


def _create_window(qapp, tmp_path):
    """Helper to create MainWindow with auto-save/load mocked."""
    import config
    original_autosave_dir = config.AUTOSAVE_DIR
    original_autosave_path = config.AUTOSAVE_PATH
    config.AUTOSAVE_DIR = str(tmp_path / "autosave")
    config.AUTOSAVE_PATH = str(tmp_path / "autosave" / "state.json")
    os.makedirs(config.AUTOSAVE_DIR, exist_ok=True)

    original_manifest = config.EXPORT_MANIFEST_PATH
    config.EXPORT_MANIFEST_PATH = str(tmp_path / "test_manifest.duckdb")

    try:
        with patch("main_window.MainWindow._auto_load_bundled"):
            with patch("main_window.MainWindow._auto_load_state"):
                from main_window import MainWindow
                window = MainWindow()
                window._autosave_timer.stop()
                yield window
                window.close()
    finally:
        config.AUTOSAVE_DIR = original_autosave_dir
        config.AUTOSAVE_PATH = original_autosave_path
        config.EXPORT_MANIFEST_PATH = original_manifest


@pytest.fixture
def main_window(qapp, tmp_path):
    """Provide a MainWindow instance for testing."""
    yield from _create_window(qapp, tmp_path)


class TestWindowCreation:
    def test_window_creates(self, main_window):
        assert main_window is not None
        assert main_window.windowTitle() == "♟ Chess Puzzle Studio"

    def test_has_board_widget(self, main_window):
        assert main_window.board_widget is not None

    def test_has_engine(self, main_window):
        assert main_window.engine is not None

    def test_has_sound_manager(self, main_window):
        assert main_window.sound_mgr is not None

    def test_has_puzzle_loader(self, main_window):
        assert main_window.puzzle_loader is not None

    def test_has_export_config(self, main_window):
        assert main_window.export_cfg is not None

    def test_has_export_manifest(self, main_window):
        assert main_window.export_manifest is not None


class TestUIElements:
    def test_has_tab_widget(self, main_window):
        assert main_window.tab_widget is not None
        assert main_window.tab_widget.count() == 3

    def test_tab_names(self, main_window):
        tabs = [main_window.tab_widget.tabText(i) for i in range(3)]
        assert any("Settings" in t for t in tabs)
        assert any("Random" in t for t in tabs)
        assert any("Export" in t for t in tabs)

    def test_has_puzzle_list(self, main_window):
        assert main_window.puzzle_list is not None
        assert isinstance(main_window.puzzle_list, QListWidget)

    def test_has_search_edit(self, main_window):
        assert main_window.search_edit is not None

    def test_has_theme_combo(self, main_window):
        assert main_window.theme_combo is not None

    def test_has_preset_combo(self, main_window):
        assert main_window.preset_combo is not None

    def test_has_play_button(self, main_window):
        assert main_window.play_btn is not None

    def test_has_loop_button(self, main_window):
        assert main_window.loop_btn is not None

    def test_has_anim_slider(self, main_window):
        assert main_window.anim_slider is not None

    def test_has_gap_slider(self, main_window):
        assert main_window.gap_slider is not None

    def test_has_move_scrubber(self, main_window):
        assert main_window.move_scrubber is not None

    def test_has_export_button(self, main_window):
        assert main_window.export_btn is not None

    def test_has_batch_buttons(self, main_window):
        assert main_window.batch_selected_btn is not None
        assert main_window.batch_page_btn is not None

    def test_has_filter_controls(self, main_window):
        assert main_window.min_rating_spin is not None
        assert main_window.max_rating_spin is not None
        assert main_window.theme_filter_combo is not None
        assert main_window.sort_combo is not None

    def test_has_pagination_controls(self, main_window):
        assert main_window.first_page_btn is not None
        assert main_window.prev_page_btn is not None
        assert main_window.next_page_btn is not None
        assert main_window.last_page_btn is not None
        assert main_window.page_label is not None


class TestBoardInteractions:
    def test_flip_board(self, main_window):
        initial = main_window.board_widget.flipped
        main_window._flip_board()
        assert main_window.board_widget.flipped != initial

    def test_theme_change(self, main_window):
        from config import THEMES
        theme_names = list(THEMES.keys())
        if len(theme_names) > 1:
            main_window.theme_combo.setCurrentText(theme_names[1])
            assert main_window.board_widget.current_theme.name == theme_names[1]

    def test_anim_speed_slider(self, main_window):
        main_window.anim_slider.setValue(100)
        assert main_window.board_widget.anim_speed == 100


class TestAutoSave:
    def test_auto_save_creates_file(self, main_window, tmp_path):
        import config
        config.AUTOSAVE_DIR = str(tmp_path / "autosave2")
        config.AUTOSAVE_PATH = str(tmp_path / "autosave2" / "state.json")
        os.makedirs(config.AUTOSAVE_DIR, exist_ok=True)

        main_window._auto_save()
        assert os.path.exists(config.AUTOSAVE_PATH)

        with open(config.AUTOSAVE_PATH, "r") as f:
            state = json.load(f)
        assert "version" in state
        assert "board_theme" in state

    def test_auto_save_saves_puzzle_state(self, main_window, tmp_path):
        import config
        config.AUTOSAVE_DIR = str(tmp_path / "autosave3")
        config.AUTOSAVE_PATH = str(tmp_path / "autosave3" / "state.json")
        os.makedirs(config.AUTOSAVE_DIR, exist_ok=True)

        main_window.current_puzzle = {"id": "test123"}
        main_window._auto_save()

        with open(config.AUTOSAVE_PATH, "r") as f:
            state = json.load(f)
        assert state.get("current_puzzle_id") == "test123"


class TestPlaybackControls:
    def test_go_start(self, main_window):
        main_window.engine.make_move_uci("e2e4")
        main_window._go_start()

    def test_go_end(self, main_window):
        main_window._go_end()

    def test_go_prev(self, main_window):
        main_window._go_prev()

    def test_go_next(self, main_window):
        main_window._go_next()

    def test_toggle_play(self, main_window):
        main_window._toggle_play()

    def test_stop_auto_play(self, main_window):
        main_window._stop_auto_play()
        assert main_window._auto_playing is False


class TestFilterActions:
    def test_apply_filters(self, main_window):
        main_window._apply_filters()

    def test_reset_filters(self, main_window):
        main_window._reset_filters()
        assert main_window.min_rating_spin.value() == 0
        assert main_window.max_rating_spin.value() == 0


class TestSoundControls:
    def test_volume_change(self, main_window):
        main_window.vol_slider.setValue(50)
        assert main_window.sound_mgr._volume == pytest.approx(0.5, abs=0.05)

    def test_sound_toggle(self, main_window):
        main_window.sound_check.setChecked(False)
        assert main_window.sound_mgr._enabled is False
        main_window.sound_check.setChecked(True)
        assert main_window.sound_mgr._enabled is True

    def test_sound_pack_change(self, main_window):
        main_window.sound_pack_combo.setCurrentText("Digital")
        assert main_window.sound_mgr.pack == "Digital"
        main_window.sound_pack_combo.setCurrentText("Classic")


class TestExportControls:
    def test_preset_change(self, main_window):
        main_window.preset_combo.setCurrentText("YouTube 720p (1280×720)")
        assert main_window.export_cfg.preset_name == "YouTube 720p (1280×720)"

    def test_title_check(self, main_window):
        main_window.title_check.setChecked(False)
        assert main_window.title_check.isChecked() is False

    def test_end_check(self, main_window):
        main_window.end_check.setChecked(False)
        assert main_window.end_check.isChecked() is False


class TestRandomControls:
    def test_random_puzzle_button(self, main_window):
        main_window._on_random_puzzle()

    def test_generate_position(self, main_window):
        main_window._on_generate_position()
        assert main_window.engine.board is not None

    def test_load_fen(self, main_window):
        main_window.engine.load_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
        assert "e3" in main_window.engine.board.fen()

    def test_copy_fen(self, main_window):
        main_window._on_copy_fen()

    def test_streak_labels(self, main_window):
        main_window._streak = 5
        main_window._best_streak = 10
        main_window.lbl_streak.setText(f"Streak: {main_window._streak}")
        main_window.lbl_streak_val.setText(f"Best: {main_window._best_streak}")
        assert "5" in main_window.lbl_streak.text()
        assert "10" in main_window.lbl_streak_val.text()


class TestPuzzleDisplay:
    def test_display_puzzle_without_data(self, main_window):
        main_window.current_puzzle = None

    def test_interactive_toggle(self, main_window):
        main_window.interact_btn.setChecked(True)
        assert main_window._interactive_mode is True
        main_window.interact_btn.setChecked(False)
        assert main_window._interactive_mode is False


class TestCloseEvent:
    def test_close_event(self, main_window, tmp_path):
        import config
        config.AUTOSAVE_DIR = str(tmp_path / "autosave_close")
        config.AUTOSAVE_PATH = str(tmp_path / "autosave_close" / "state.json")
        os.makedirs(config.AUTOSAVE_DIR, exist_ok=True)

        from PySide6.QtGui import QCloseEvent
        event = QCloseEvent()
        main_window.closeEvent(event)
        assert event.isAccepted()
EOF

echo "Tests folder successfully generated!"