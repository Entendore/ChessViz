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
