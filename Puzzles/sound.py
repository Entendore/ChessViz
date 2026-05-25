"""Sound manager — generates and plays chess sound effects via QSoundEffect.
Numba JIT-accelerated when available; pure-NumPy fallback otherwise.
"""

import os, wave, math, tempfile
import numpy as np
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect
from constants import log, HAS_NUMBA

if HAS_NUMBA:
    from numba import njit

    @njit(cache=True, nogil=True)
    def _nb_sin(freq, n_samples, volume, sr):
        out = np.empty(n_samples, dtype=np.float64)
        two_pi = 2.0 * np.pi
        for i in range(n_samples):
            out[i] = 32767.0 * volume * math.sin(two_pi * freq * i / sr)
        return out

    @njit(cache=True, nogil=True)
    def _nb_sweep(start_freq, end_freq, n_samples, volume, sr):
        out = np.empty(n_samples, dtype=np.float64)
        two_pi = 2.0 * np.pi
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
            if v > 32767.0:   v = 32767.0
            elif v < -32768.0: v = -32768.0
            out[i] = np.int16(v)
        return out

    log("Numba JIT audio primitives loaded", "SOUND")

else:
    def _nb_sin(freq, n_samples, volume, sr):
        t = np.arange(n_samples, dtype=np.float64)
        return 32767.0 * volume * np.sin(2.0 * np.pi * freq * t / sr)

    def _nb_sweep(start_freq, end_freq, n_samples, volume, sr):
        i = np.arange(n_samples, dtype=np.float64)
        f = start_freq + (end_freq - start_freq) * i / n_samples
        return 32767.0 * volume * np.sin(2.0 * np.pi * f * i / sr)

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
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(int_samples.tobytes())

    def _gen_all(self):
        sr = 44100; d = self.tmpdir

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

        start_tone = np.concatenate([_sin(523, 0.12, 0.4),
                                     np.zeros(int(sr * 0.03), dtype=np.float64),
                                     _sin(659, 0.18, 0.4)])
        self._wav(os.path.join(d, "start.wav"), _env(start_tone, 0.005, 0.04))

    def _load_all(self):
        for n in ("move", "capture", "check", "checkmate",
                   "castle", "error", "promote", "start"):
            e = QSoundEffect()
            e.setSource(QUrl.fromLocalFile(os.path.join(self.tmpdir, f"{n}.wav")))
            e.setVolume(self._volume); self.sounds[n] = e

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
        if s: s.stop(); s.play()