"""Tests for main_window.py — window creation and basic UI interactions."""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

from PySide6.QtWidgets import QSplitter, QTabWidget, QListWidget
from PySide6.QtCore import Qt


@pytest.fixture
def main_window(qapp, process_events, tmp_path):
    """Provide a MainWindow instance for testing with proper Qt setup."""
    import config

    # Patch autosave paths to use temp directory
    original_autosave_dir = config.AUTOSAVE_DIR
    original_autosave_path = config.AUTOSAVE_PATH
    config.AUTOSAVE_DIR = str(tmp_path / "autosave")
    config.AUTOSAVE_PATH = str(tmp_path / "autosave" / "state.json")
    os.makedirs(config.AUTOSAVE_DIR, exist_ok=True)

    # Patch export manifest path
    original_manifest = config.EXPORT_MANIFEST_PATH
    config.EXPORT_MANIFEST_PATH = str(tmp_path / "test_manifest.duckdb")

    try:
        with patch("main_window.MainWindow._auto_load_bundled"):
            with patch("main_window.MainWindow._auto_load_state"):
                from main_window import MainWindow
                window = MainWindow()
                process_events()
                # Stop the auto-save timer during tests
                window._autosave_timer.stop()
                yield window
                # Cleanup
                window.close()
                process_events()
    finally:
        config.AUTOSAVE_DIR = original_autosave_dir
        config.AUTOSAVE_PATH = original_autosave_path
        config.EXPORT_MANIFEST_PATH = original_manifest


class TestWindowCreation:
    def test_window_creates(self, main_window, process_events):
        process_events()
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
    def test_flip_board(self, main_window, process_events):
        initial = main_window.board_widget.flipped
        main_window._flip_board()
        process_events()
        assert main_window.board_widget.flipped != initial

    def test_theme_change(self, main_window, process_events):
        from config import THEMES
        theme_names = list(THEMES.keys())
        if len(theme_names) > 1:
            main_window.theme_combo.setCurrentText(theme_names[1])
            process_events()
            assert main_window.board_widget.current_theme.name == theme_names[1]

    def test_anim_speed_slider(self, main_window, process_events):
        main_window.anim_slider.setValue(100)
        process_events()
        assert main_window.board_widget.anim_speed == 100


class TestAutoSave:
    def test_auto_save_creates_file(self, main_window, tmp_path, process_events):
        import config
        save_dir = str(tmp_path / "autosave2")
        save_path = str(tmp_path / "autosave2" / "state.json")
        os.makedirs(save_dir, exist_ok=True)
        config.AUTOSAVE_DIR = save_dir
        config.AUTOSAVE_PATH = save_path

        main_window._auto_save()
        assert os.path.exists(save_path)

        with open(save_path, "r") as f:
            state = json.load(f)
        assert "version" in state
        assert "board_theme" in state

    def test_auto_save_saves_puzzle_state(self, main_window, tmp_path, process_events):
        import config
        save_dir = str(tmp_path / "autosave3")
        save_path = str(tmp_path / "autosave3" / "state.json")
        os.makedirs(save_dir, exist_ok=True)
        config.AUTOSAVE_DIR = save_dir
        config.AUTOSAVE_PATH = save_path

        main_window.current_puzzle = {"id": "test123"}
        main_window._auto_save()

        with open(save_path, "r") as f:
            state = json.load(f)
        assert state.get("current_puzzle_id") == "test123"


class TestPlaybackControls:
    def test_go_start(self, main_window, process_events):
        main_window.engine.make_move_uci("e2e4")
        process_events()
        main_window._go_start()
        process_events()

    def test_go_end(self, main_window, process_events):
        main_window._go_end()
        process_events()

    def test_go_prev(self, main_window, process_events):
        main_window._go_prev()
        process_events()

    def test_go_next(self, main_window, process_events):
        main_window._go_next()
        process_events()

    def test_toggle_play(self, main_window, process_events):
        main_window._toggle_play()
        process_events()

    def test_stop_auto_play(self, main_window, process_events):
        main_window._stop_auto_play()
        process_events()
        assert main_window._auto_playing is False


class TestFilterActions:
    def test_apply_filters(self, main_window, process_events):
        main_window._apply_filters()
        process_events()

    def test_reset_filters(self, main_window, process_events):
        main_window._reset_filters()
        process_events()
        assert main_window.min_rating_spin.value() == 0
        assert main_window.max_rating_spin.value() == 0


class TestSoundControls:
    def test_volume_change(self, main_window, process_events):
        main_window.vol_slider.setValue(50)
        process_events()
        assert main_window.sound_mgr._volume == pytest.approx(0.5, abs=0.05)

    def test_sound_toggle(self, main_window, process_events):
        main_window.sound_check.setChecked(False)
        process_events()
        assert main_window.sound_mgr._enabled is False
        main_window.sound_check.setChecked(True)
        process_events()
        assert main_window.sound_mgr._enabled is True

    def test_sound_pack_change(self, main_window, process_events):
        main_window.sound_pack_combo.setCurrentText("Digital")
        process_events()
        assert main_window.sound_mgr.pack == "Digital"
        # Reset
        main_window.sound_pack_combo.setCurrentText("Classic")
        process_events()


class TestExportControls:
    def test_preset_change(self, main_window, process_events):
        main_window.preset_combo.setCurrentText("YouTube 720p (1280×720)")
        process_events()
        assert main_window.export_cfg.preset_name == "YouTube 720p (1280×720)"

    def test_title_check(self, main_window, process_events):
        main_window.title_check.setChecked(False)
        process_events()
        assert main_window.title_check.isChecked() is False

    def test_end_check(self, main_window, process_events):
        main_window.end_check.setChecked(False)
        process_events()
        assert main_window.end_check.isChecked() is False


class TestRandomControls:
    def test_random_puzzle_button(self, main_window, process_events):
        main_window._on_random_puzzle()
        process_events()

    def test_generate_position(self, main_window, process_events):
        main_window._on_generate_position()
        process_events()
        assert main_window.engine.board is not None

    def test_load_fen(self, main_window, process_events):
        main_window.engine.load_fen(
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
        assert "4P3" in main_window.engine.board.fen()

    def test_copy_fen(self, main_window, process_events):
        main_window._on_copy_fen()
        process_events()

    def test_streak_labels(self, main_window, process_events):
        main_window._streak = 5
        main_window._best_streak = 10
        main_window.lbl_streak.setText(f"Streak: {main_window._streak}")
        main_window.lbl_streak_val.setText(f"Best: {main_window._best_streak}")
        assert "5" in main_window.lbl_streak.text()
        assert "10" in main_window.lbl_streak_val.text()


class TestPuzzleDisplay:
    def test_display_puzzle_without_data(self, main_window, process_events):
        main_window.current_puzzle = None

    def test_interactive_toggle(self, main_window, process_events):
        main_window.interact_btn.setChecked(True)
        process_events()
        assert main_window._interactive_mode is True
        main_window.interact_btn.setChecked(False)
        process_events()
        assert main_window._interactive_mode is False


class TestCloseEvent:
    def test_close_event(self, main_window, tmp_path, process_events):
        import config
        save_dir = str(tmp_path / "autosave_close")
        save_path = str(tmp_path / "autosave_close" / "state.json")
        os.makedirs(save_dir, exist_ok=True)
        config.AUTOSAVE_DIR = save_dir
        config.AUTOSAVE_PATH = save_path

        from PySide6.QtGui import QCloseEvent
        event = QCloseEvent()
        main_window.closeEvent(event)
        assert event.isAccepted()