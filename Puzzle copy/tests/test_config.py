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
