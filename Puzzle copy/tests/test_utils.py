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
