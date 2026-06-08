"""Tests for sound_manager.py — audio generation and management."""

import os
import wave
import tempfile

import numpy as np
import pytest


class TestAudioPrimitives:
    """Test the low-level audio signal generation functions.

    These do NOT require QApplication — pure NumPy math.
    """

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
        # First sample should be near zero (attack)
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
    """Tests that require QApplication for QSoundEffect."""

    def test_initialization(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()
        assert sm.pack == "Classic"
        assert sm._enabled is True
        assert sm._volume == 0.7
        sm.cleanup()

    def test_set_volume(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()
        sm.set_volume(0.5)
        assert sm._volume == 0.5
        sm.set_volume(1.5)
        assert sm._volume == 1.0  # Clamped
        sm.set_volume(-0.5)
        assert sm._volume == 0.0  # Clamped
        sm.cleanup()

    def test_set_enabled(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()
        sm.set_enabled(False)
        assert sm._enabled is False
        sm.set_enabled(True)
        assert sm._enabled is True
        sm.cleanup()

    def test_set_effect_enabled(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()
        sm.set_effect_enabled("move", False)
        assert sm._effect_enabled["move"] is False
        sm.set_effect_enabled("move", True)
        assert sm._effect_enabled["move"] is True
        sm.cleanup()

    def test_switch_pack(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()

        sm.switch_pack("Digital")
        process_events()
        assert sm.pack == "Digital"

        sm.switch_pack("Wooden")
        process_events()
        assert sm.pack == "Wooden"

        sm.switch_pack("Arcade")
        process_events()
        assert sm.pack == "Arcade"

        sm.switch_pack("Classic")
        process_events()
        assert sm.pack == "Classic"
        sm.cleanup()

    def test_switch_pack_same_does_nothing(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()
        original_pack = sm.pack
        sm.switch_pack("Classic")  # Already Classic
        assert sm.pack == original_pack
        sm.cleanup()

    def test_switch_pack_unknown_defaults_classic(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()
        sm.switch_pack("NonExistentPack")
        process_events()
        # Should fall back to Classic
        assert sm.pack == "Classic"
        sm.cleanup()

    def test_play_when_disabled(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()
        sm.set_enabled(False)
        # Should not raise
        sm.play("move")
        process_events()
        sm.cleanup()

    def test_play_with_effect_disabled(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()
        sm.set_effect_enabled("move", False)
        sm.play("move")
        process_events()
        sm.cleanup()

    def test_play_nonexistent_effect(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()
        sm.play("nonexistent_effect")
        process_events()
        sm.cleanup()

    def test_all_packs_generate_files(self, qapp, process_events):
        from sound_manager import SoundManager, SOUND_EFFECTS
        for pack in SoundManager.PACKS:
            sm = SoundManager(pack=pack)
            process_events()
            for effect in SOUND_EFFECTS:
                path = os.path.join(sm.tmpdir, f"{effect}.wav")
                assert os.path.exists(path), f"{effect}.wav missing for pack {pack}"
            sm.cleanup()

    def test_cleanup_removes_temp_dir(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()
        tmpdir = sm.tmpdir
        assert os.path.exists(tmpdir)
        sm.cleanup()
        assert not os.path.exists(tmpdir)

    def test_pack_property(self, qapp, process_events):
        from sound_manager import SoundManager
        sm = SoundManager(pack="Digital")
        process_events()
        assert sm.pack == "Digital"
        sm.switch_pack("Arcade")
        process_events()
        assert sm.pack == "Arcade"
        sm.cleanup()

    def test_effect_checks_dict_populated(self, qapp, process_events):
        from sound_manager import SoundManager, SOUND_EFFECTS
        sm = SoundManager()
        process_events()
        for effect in SOUND_EFFECTS:
            assert effect in sm._effect_enabled
            assert sm._effect_enabled[effect] is True
        sm.cleanup()

    def test_play_sound_no_crash(self, qapp, process_events):
        """Verify that calling play() doesn't crash even if audio backend fails."""
        from sound_manager import SoundManager
        sm = SoundManager()
        process_events()
        for effect_name in SoundManager.EFFECTS:
            sm.play(effect_name)
            process_events()
        sm.cleanup()