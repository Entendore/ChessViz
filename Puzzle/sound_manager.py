#!/usr/bin/env python3
"""Procedural sound generation and playback — multiple sound packs, no background audio."""

import os
import math
import wave
import shutil

import numpy as np

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect

from config import SOUND_PACKS, SOUND_EFFECTS
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
    def _nb_square(freq, n_samples, volume, sr):
        out = np.empty(n_samples, dtype=np.float64)
        two_pi = 2.0 * math.pi
        for i in range(n_samples):
            val = math.sin(two_pi * freq * i / sr)
            out[i] = 32767.0 * volume * (1.0 if val >= 0 else -1.0)
        return out

    @njit(cache=True, nogil=True)
    def _nb_triangle(freq, n_samples, volume, sr):
        out = np.empty(n_samples, dtype=np.float64)
        for i in range(n_samples):
            t = (freq * float(i) / sr) % 1.0
            out[i] = 32767.0 * volume * (4.0 * abs(t - 0.5) - 1.0)
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

    def _nb_square(freq, n_samples, volume, sr):
        t = np.arange(n_samples, dtype=np.float64)
        return 32767.0 * volume * np.sign(np.sin(2.0 * math.pi * freq * t / sr))

    def _nb_triangle(freq, n_samples, volume, sr):
        t = np.arange(n_samples, dtype=np.float64)
        phase = (freq * t / sr) % 1.0
        return 32767.0 * volume * (4.0 * np.abs(phase - 0.5) - 1.0)

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

def _square(freq, duration, volume=0.5, sr=44100):
    return _nb_square(freq, int(sr * duration), volume, sr)

def _triangle(freq, duration, volume=0.5, sr=44100):
    return _nb_triangle(freq, int(sr * duration), volume, sr)

def _env(samples, attack=0.01, release=0.02, sr=44100):
    return _nb_env(samples, attack, release, sr)

def _mix(a, b):
    return _nb_mix(a, b)

def _to_i16(samples):
    return _nb_clip_i16(samples)


# ── Sound Pack Definitions ──────────────────────────────────────────────────
# Each pack defines a _gen_pack_X method that writes WAVs for all effects.

class SoundManager:
    PACKS = SOUND_PACKS
    EFFECTS = SOUND_EFFECTS

    def __init__(self, pack="Classic"):
        self.tmpdir = os.path.join(os.getcwd(), ".chess_sfx_tmp")
        os.makedirs(self.tmpdir, exist_ok=True)
        self.sounds = {}
        self._enabled = True
        self._volume = 0.7
        self._pack = pack
        self._effect_enabled = {name: True for name in self.EFFECTS}
        self._switch_pack(pack)

    @staticmethod
    def _wav(path, samples, sr=44100):
        int_samples = _to_i16(samples)
        with wave.open(path, 'w') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(int_samples.tobytes())

    # ── Pack switching ──────────────────────────────────────────────────

    def _switch_pack(self, pack_name):
        self._pack = pack_name
        gen = {
            "Classic": self._gen_pack_classic,
            "Digital": self._gen_pack_digital,
            "Wooden":  self._gen_pack_wooden,
            "Arcade":  self._gen_pack_arcade,
        }.get(pack_name, self._gen_pack_classic)
        gen()
        self._load_all()

    def switch_pack(self, pack_name):
        if pack_name != self._pack:
            self._switch_pack(pack_name)

    # ── Classic Pack ────────────────────────────────────────────────────

    def _gen_pack_classic(self):
        sr = 44100; d = self.tmpdir
        self._wav(os.path.join(d, "move.wav"),
                  _env(_sin(800, 0.06, 0.35), 0.005, 0.03))
        self._wav(os.path.join(d, "capture.wav"),
                  _env(_mix(_sin(300, 0.12, 0.50), _sin(650, 0.10, 0.35)), 0.003, 0.05))
        self._wav(os.path.join(d, "check.wav"),
                  _env(_mix(_sin(1000, 0.15, 0.50), _sin(1250, 0.12, 0.30)), 0.005, 0.05))
        cm = np.concatenate([_sin(800, 0.12, 0.50),
                             _sin(600, 0.12, 0.50),
                             _sin(400, 0.25, 0.50)])
        self._wav(os.path.join(d, "checkmate.wav"), _env(cm, 0.01, 0.08))
        self._wav(os.path.join(d, "castle.wav"),
                  _env(_sweep(400, 800, 0.15, 0.40), 0.005, 0.03))
        self._wav(os.path.join(d, "error.wav"),
                  _env(_sin(200, 0.10, 0.35), 0.005, 0.03))
        self._wav(os.path.join(d, "promote.wav"),
                  _env(_sweep(500, 1000, 0.20, 0.40), 0.01, 0.05))
        start_tone = np.concatenate([
            _sin(523, 0.10, 0.40),
            np.zeros(int(sr * 0.03), dtype=np.float64),
            _sin(659, 0.15, 0.40),
        ])
        self._wav(os.path.join(d, "start.wav"), _env(start_tone, 0.005, 0.04))
        solved_tone = np.concatenate([
            _sin(523, 0.08, 0.45),
            np.zeros(int(sr * 0.02), dtype=np.float64),
            _sin(659, 0.08, 0.45),
            np.zeros(int(sr * 0.02), dtype=np.float64),
            _sin(784, 0.18, 0.45),
        ])
        self._wav(os.path.join(d, "solved.wav"), _env(solved_tone, 0.005, 0.05))

    # ── Digital Pack ────────────────────────────────────────────────────

    def _gen_pack_digital(self):
        sr = 44100; d = self.tmpdir
        self._wav(os.path.join(d, "move.wav"),
                  _env(_triangle(1200, 0.04, 0.30), 0.002, 0.02))
        self._wav(os.path.join(d, "capture.wav"),
                  _env(_mix(_square(440, 0.08, 0.30), _triangle(880, 0.06, 0.20)), 0.002, 0.04))
        self._wav(os.path.join(d, "check.wav"),
                  _env(_mix(_square(880, 0.10, 0.35), _square(1100, 0.08, 0.25)), 0.002, 0.04))
        cm = np.concatenate([_square(660, 0.08, 0.35),
                             _square(440, 0.08, 0.35),
                             _square(330, 0.20, 0.35)])
        self._wav(os.path.join(d, "checkmate.wav"), _env(cm, 0.005, 0.06))
        self._wav(os.path.join(d, "castle.wav"),
                  _env(_sweep(600, 1200, 0.10, 0.30), 0.002, 0.02))
        self._wav(os.path.join(d, "error.wav"),
                  _env(_square(150, 0.12, 0.30), 0.002, 0.04))
        self._wav(os.path.join(d, "promote.wav"),
                  _env(_sweep(800, 1600, 0.15, 0.35), 0.005, 0.03))
        start_tone = np.concatenate([
            _triangle(880, 0.06, 0.35),
            np.zeros(int(sr * 0.02), dtype=np.float64),
            _triangle(1320, 0.10, 0.35),
        ])
        self._wav(os.path.join(d, "start.wav"), _env(start_tone, 0.002, 0.03))
        solved_tone = np.concatenate([
            _triangle(880, 0.06, 0.40),
            np.zeros(int(sr * 0.015), dtype=np.float64),
            _triangle(1100, 0.06, 0.40),
            np.zeros(int(sr * 0.015), dtype=np.float64),
            _triangle(1320, 0.14, 0.40),
        ])
        self._wav(os.path.join(d, "solved.wav"), _env(solved_tone, 0.002, 0.04))

    # ── Wooden Pack ─────────────────────────────────────────────────────

    def _gen_pack_wooden(self):
        sr = 44100; d = self.tmpdir
        # Warm thock sound — low freq + fast decay
        self._wav(os.path.join(d, "move.wav"),
                  _env(_sin(220, 0.08, 0.40), 0.002, 0.05))
        self._wav(os.path.join(d, "capture.wav"),
                  _env(_mix(_sin(180, 0.15, 0.50), _sin(360, 0.10, 0.25)), 0.002, 0.07))
        self._wav(os.path.join(d, "check.wav"),
                  _env(_mix(_sin(440, 0.18, 0.45), _sin(550, 0.14, 0.25)), 0.003, 0.06))
        cm = np.concatenate([_sin(350, 0.15, 0.45),
                             _sin(280, 0.15, 0.45),
                             _sin(200, 0.30, 0.45)])
        self._wav(os.path.join(d, "checkmate.wav"), _env(cm, 0.008, 0.10))
        self._wav(os.path.join(d, "castle.wav"),
                  _env(_sweep(200, 400, 0.18, 0.35), 0.003, 0.05))
        self._wav(os.path.join(d, "error.wav"),
                  _env(_sin(120, 0.12, 0.30), 0.003, 0.04))
        self._wav(os.path.join(d, "promote.wav"),
                  _env(_sweep(300, 600, 0.22, 0.35), 0.005, 0.06))
        start_tone = np.concatenate([
            _sin(330, 0.12, 0.35),
            np.zeros(int(sr * 0.04), dtype=np.float64),
            _sin(440, 0.18, 0.35),
        ])
        self._wav(os.path.join(d, "start.wav"), _env(start_tone, 0.003, 0.05))
        solved_tone = np.concatenate([
            _sin(330, 0.10, 0.40),
            np.zeros(int(sr * 0.03), dtype=np.float64),
            _sin(440, 0.10, 0.40),
            np.zeros(int(sr * 0.03), dtype=np.float64),
            _sin(550, 0.22, 0.40),
        ])
        self._wav(os.path.join(d, "solved.wav"), _env(solved_tone, 0.003, 0.06))

    # ── Arcade Pack ─────────────────────────────────────────────────────

    def _gen_pack_arcade(self):
        sr = 44100; d = self.tmpdir
        self._wav(os.path.join(d, "move.wav"),
                  _env(_square(660, 0.05, 0.25), 0.001, 0.02))
        self._wav(os.path.join(d, "capture.wav"),
                  _env(_mix(_square(220, 0.08, 0.30), _square(440, 0.06, 0.25)), 0.001, 0.03))
        self._wav(os.path.join(d, "check.wav"),
                  _env(_mix(_square(880, 0.08, 0.30), _triangle(1200, 0.06, 0.25)), 0.001, 0.03))
        cm = np.concatenate([_square(440, 0.06, 0.30),
                             _square(550, 0.06, 0.30),
                             _square(660, 0.06, 0.30),
                             _square(880, 0.15, 0.30)])
        self._wav(os.path.join(d, "checkmate.wav"), _env(cm, 0.001, 0.05))
        self._wav(os.path.join(d, "castle.wav"),
                  _env(_sweep(330, 660, 0.08, 0.25), 0.001, 0.02))
        self._wav(os.path.join(d, "error.wav"),
                  _env(_square(110, 0.10, 0.25), 0.001, 0.03))
        self._wav(os.path.join(d, "promote.wav"),
                  _env(_sweep(440, 880, 0.12, 0.30), 0.002, 0.03))
        start_tone = np.concatenate([
            _square(523, 0.06, 0.30),
            np.zeros(int(sr * 0.02), dtype=np.float64),
            _square(784, 0.10, 0.30),
        ])
        self._wav(os.path.join(d, "start.wav"), _env(start_tone, 0.001, 0.02))
        solved_tone = np.concatenate([
            _square(523, 0.05, 0.35),
            np.zeros(int(sr * 0.01), dtype=np.float64),
            _square(659, 0.05, 0.35),
            np.zeros(int(sr * 0.01), dtype=np.float64),
            _square(784, 0.05, 0.35),
            np.zeros(int(sr * 0.01), dtype=np.float64),
            _square(1047, 0.12, 0.35),
        ])
        self._wav(os.path.join(d, "solved.wav"), _env(solved_tone, 0.001, 0.03))

    # ── Load / Play ─────────────────────────────────────────────────────

    def _load_all(self):
        # Stop and clear old effects
        for s in self.sounds.values():
            s.stop()
        self.sounds.clear()
        for n in self.EFFECTS:
            path = os.path.join(self.tmpdir, f"{n}.wav")
            if os.path.exists(path):
                e = QSoundEffect()
                e.setSource(QUrl.fromLocalFile(path))
                e.setVolume(self._volume)
                self.sounds[n] = e

    def set_volume(self, vol):
        self._volume = max(0.0, min(1.0, vol))
        for s in self.sounds.values():
            s.setVolume(self._volume)

    def set_enabled(self, enabled):
        self._enabled = enabled

    def set_effect_enabled(self, effect_name, enabled):
        if effect_name in self._effect_enabled:
            self._effect_enabled[effect_name] = enabled

    def play(self, name):
        if not self._enabled:
            return
        if not self._effect_enabled.get(name, True):
            return
        s = self.sounds.get(name)
        if s:
            s.stop()
            s.play()

    @property
    def pack(self):
        return self._pack

    def cleanup(self):
        try:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            log("Sound temp directory cleaned up", "SOUND")
        except Exception as e:
            log(f"Sound cleanup error: {e}", "SOUND")