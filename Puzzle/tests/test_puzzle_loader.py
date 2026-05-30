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
