#!/usr/bin/env python3
"""Procedural sound generation and playback via QSoundEffect."""

import os
import math
import wave
import shutil
import tempfile

import numpy as np

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect

from utils import log

# ── Local Dependency Check ──────────────────────────────────────────────────

HAS_NUMBA = False
try:
    import numba
    HAS_NUMBA = True
except ImportError:
    pass

# ── Numba-accelerated audio primitives ──────────────────────────────────────

if HAS_NUMBA:
    from numba import njit

    @njit(cache=True, nogil=True)
    def _nb_sin(freq, n_samples, volume, sr):
        out = np.empty(n_samples, dtype=np.float64)
        two_pi = 2.0 * math.pi
        for i in range(n_samples):
            out[i] = 32767.0 * volume * math.sin(two_pi * freq * i / sr)
        return out

    @njit(cache=True, nogil=True)
    def _nb_sweep(start_freq, end_freq, n_samples, volume, sr):
        out = np.empty(n_samples, dtype=np.float64)
        two_pi = 2.0 * math.pi
        for i in range(n_samples):
            f = start_freq + (end_freq - start_freq) * float(i) / n_samples
            out[i] = 32767.0 * volume * math.sin(two_pi * f * i / sr)
        return out

    @njit(cache=True, nogil=True)
    def _nb_env(samples, attack_s, release_s, sr):
        out = samples.copy()
        n = len(out)
        ai = min(int(sr * attack_s), n)
        ri = min(int(sr * release_s), n)
        for i in range(ai):
            out[i] *= float(i) / float(ai)
        for i in range(ri):
            out[-(i + 1)] *= float(i) / float(ri)
        return out

    @njit(cache=True, nogil=True)
    def _nb_mix(a, b):
        na, nb = len(a), len(b)
        n = max(na, nb)
        out = np.zeros(n, dtype=np.float64)
        for i in range(na):
            out[i] += a[i]
        for i in range(nb):
            out[i] += b[i]
        return out

    @njit(cache=True, nogil=True)
    def _nb_clip_i16(samples):
        n = len(samples)
        out = np.empty(n, dtype=np.int16)
        for i in range(n):
            v = samples[i]
            if v > 32767.0:
                v = 32767.0
            elif v < -32768.0:
                v = -32768.0
            out[i] = np.int16(v)
        return out

    log("Numba JIT audio primitives loaded", "SOUND")
else:
    def _nb_sin(freq, n_samples, volume, sr):
        t = np.arange(n_samples, dtype=np.float64)
        return 32767.0 * volume * np.sin(2.0 * math.pi * freq * t / sr)

    def _nb_sweep(start_freq, end_freq, n_samples, volume, sr):
        i = np.arange(n_samples, dtype=np.float64)
        f = start_freq + (end_freq - start_freq) * i / n_samples
        return 32767.0 * volume * np.sin(2.0 * math.pi * f * i / sr)

    def _nb_env(samples, attack_s, release_s, sr):
        out = samples.copy()
        n = len(out)
        ai = min(int(sr * attack_s), n)
        ri = min(int(sr * release_s), n)
        if ai > 1:
            out[:ai] *= np.linspace(0, 1, ai)
        if ri > 1:
            out[-ri:] *= np.linspace(0, 1, ri)[::-1]
        return out

    def _nb_mix(a, b):
        na, nb = len(a), len(b)
        n = max(na, nb)
        out = np.zeros(n, dtype=np.float64)
        out[:na] += a
        out[:nb] += b
        return out

    def _nb_clip_i16(samples):
        return np.clip(samples, -32768, 32767).astype(np.int16)


# ── Thin wrappers ───────────────────────────────────────────────────────────

def _sin(freq, duration, volume=0.5, sr=44100):
    return _nb_sin(freq, int(sr * duration), volume, sr)

def _sweep(start_freq, end_freq, duration, volume=0.5, sr=44100):
    return _nb_sweep(start_freq, end_freq, int(sr * duration), volume, sr)

def _env(samples, attack=0.01, release=0.02, sr=44100):
    return _nb_env(samples, attack, release, sr)

def _mix(a, b):
    return _nb_mix(a, b)

def _to_i16(samples):
    return _nb_clip_i16(samples)


# ── Sound Manager ───────────────────────────────────────────────────────────

class SoundManager:
    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="chess_sfx_")
        self.sounds = {}
        self._enabled = True
        self._volume = 0.7
        self._gen_all()
        self._load_all()

    @staticmethod
    def _wav(path, samples, sr=44100):
        int_samples = _to_i16(samples)
        with wave.open(path, 'w') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(int_samples.tobytes())

    def _gen_all(self):
        sr = 44100
        d = self.tmpdir
        self._wav(os.path.join(d, "move.wav"),
                  _env(_sin(800, 0.06, 0.4), 0.005, 0.03))
        self._wav(os.path.join(d, "capture.wav"),
                  _env(_mix(_sin(300, 0.10, 0.5), _sin(600, 0.08, 0.3)), 0.005, 0.04))
        self._wav(os.path.join(d, "check.wav"),
                  _env(_mix(_sin(1000, 0.12, 0.5), _sin(1250, 0.10, 0.3)), 0.005, 0.04))
        cm = np.concatenate([_sin(800, 0.15, 0.5),
                             _sin(600, 0.15, 0.5),
                             _sin(400, 0.25, 0.5)])
        self._wav(os.path.join(d, "checkmate.wav"), _env(cm, 0.01, 0.08))
        self._wav(os.path.join(d, "castle.wav"),
                  _env(_sweep(400, 800, 0.15, 0.4), 0.005, 0.03))
        self._wav(os.path.join(d, "error.wav"),
                  _env(_sin(200, 0.10, 0.4), 0.005, 0.03))
        self._wav(os.path.join(d, "promote.wav"),
                  _env(_sweep(400, 800, 0.2, 0.4), 0.01, 0.05))
        start_tone = np.concatenate([
            _sin(523, 0.12, 0.4),
            np.zeros(int(sr * 0.03), dtype=np.float64),
            _sin(659, 0.18, 0.4),
        ])
        self._wav(os.path.join(d, "start.wav"), _env(start_tone, 0.005, 0.04))

    def _load_all(self):
        for n in ("move", "capture", "check", "checkmate",
                  "castle", "error", "promote", "start"):
            e = QSoundEffect()
            e.setSource(QUrl.fromLocalFile(os.path.join(self.tmpdir, f"{n}.wav")))
            e.setVolume(self._volume)
            self.sounds[n] = e

    def set_volume(self, vol):
        self._volume = max(0.0, min(1.0, vol))
        for s in self.sounds.values():
            s.setVolume(self._volume)

    def set_enabled(self, enabled):
        self._enabled = enabled

    def play(self, name):
        if not self._enabled:
            return
        s = self.sounds.get(name)
        if s:
            s.stop()
            s.play()

    # ── Background Audio Generation for Export ──────────────────────────

    def generate_background_audio(self, preset_name, duration_s, output_path):
        """Generate a procedural background audio track based on a sound design preset.
        Returns output_path on success, None on failure."""
        from config import SOUND_PRESETS
        if preset_name not in SOUND_PRESETS or preset_name == "None":
            return None

        preset = SOUND_PRESETS[preset_name]
        sr = 44100
        n_samples = max(1, int(sr * duration_s))

        base_freq = preset.get('base_freq', 220)
        harmonics = preset.get('harmonics', [1.0])
        beat_period = preset.get('beat_period', 2.0)
        vol = preset.get('volume', 0.15)
        use_square = preset.get('square_wave', False)

        t = np.arange(n_samples, dtype=np.float64)
        samples = np.zeros(n_samples, dtype=np.float64)

        for h_idx, h_amp in enumerate(harmonics):
            freq = base_freq * (h_idx + 1)
            if use_square:
                # Square wave via sign of sine
                wave = np.sign(np.sin(2.0 * np.pi * freq * t / sr)) * h_amp
            else:
                wave = h_amp * np.sin(2.0 * np.pi * freq * t / sr)

            # Gentle amplitude modulation for movement / breathing
            mod_freq = 0.08 + h_idx * 0.04
            mod = 0.6 + 0.4 * np.sin(2.0 * np.pi * mod_freq * t / sr)
            wave *= mod

            # Subtle beat pulse
            if beat_period > 0:
                beat_env = 0.85 + 0.15 * np.sin(2.0 * np.pi / beat_period * t / sr)
                wave *= beat_env

            samples += wave

        # Normalize to target volume
        peak = np.max(np.abs(samples))
        if peak > 0:
            samples = samples / peak * (32767.0 * vol)

        # Fade in / fade out (1 second each, or shorter for short clips)
        fade_len = min(int(sr * 1.0), n_samples // 4)
        if fade_len > 1:
            samples[:fade_len] *= np.linspace(0, 1, fade_len)
            samples[-fade_len:] *= np.linspace(1, 0, fade_len)

        # Write WAV
        try:
            int_samples = _to_i16(samples)
            with wave.open(output_path, 'w') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes(int_samples.tobytes())
            log(f"Generated background audio: {preset_name} ({duration_s:.1f}s)", "SOUND")
            return output_path
        except Exception as e:
            log(f"Audio generation failed: {e}", "SOUND")
            return None

    def cleanup(self):
        try:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            log("Sound temp directory cleaned up", "SOUND")
        except Exception as e:
            log(f"Sound cleanup error: {e}", "SOUND")