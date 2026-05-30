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
