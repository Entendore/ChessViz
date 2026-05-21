"""Chess Video Maker Pro — Professional Sound Manager (Synthesized)"""
import io
import os
import wave
import math
import tempfile
import shutil
import logging
from PySide6.QtCore import QObject, QUrl
import gc
import time

try:
    from PySide6.QtMultimedia import QSoundEffect
    HAS_MM = True
except ImportError:
    HAS_MM = False

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False

from constants import SOUND_THEMES, SOUND_TYPES, SOUND_DESIGNS

logger = logging.getLogger("ChessVideoMaker.Sound")


# ── WAV helpers ────────────────────────────────────────────────────
def _to_wav(signal, sr=44100):
    signal = np.clip(signal, -1.0, 1.0)
    samples = (signal * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples.tobytes())
    buf.seek(0)
    return buf.getvalue()


def _fade(signal, fade_ms=2, sr=44100):
    f = min(int(sr * fade_ms / 1000), len(signal) // 4)
    if f > 1:
        signal[:f] *= np.linspace(0, 1, f)
        signal[-f:] *= np.linspace(1, 0, f)
    return signal


def _norm(signal):
    p = np.max(np.abs(signal))
    return signal / p * 0.9 if p > 1e-10 else signal


def _add_reverb(signal, amount=0.15, delay_ms=30, decay=0.5, sr=44100):
    """Simulate a simple reverb by adding delayed, attenuated copies."""
    if amount <= 0:
        return signal
    delay_samples = int(sr * delay_ms / 1000)
    out = signal.copy()
    atten = amount
    for _ in range(3):
        delayed = np.zeros_like(out)
        d = min(delay_samples, len(out))
        delayed[d:] = out[:-d] * atten
        out = out + delayed
        atten *= decay
    return _norm(out)


def _bitcrush(signal, bits=8):
    """Reduce bit depth for retro sound."""
    if bits >= 16:
        return signal
    levels = 2 ** bits
    return np.round(signal * levels) / levels


# ── Base synthesizers ──────────────────────────────────────────────
def _synth_move(sr=44100, freq=1800, decay=50, nm=0.4, dur=0.08):
    t = np.linspace(0, dur, int(sr * dur), False)
    noise = np.random.randn(len(t)) * np.exp(-t * decay * 1.6)
    res = np.sin(2 * np.pi * freq * t) * np.exp(-t * decay)
    harm = np.sin(2 * np.pi * freq * 2.4 * t) * np.exp(-t * decay * 1.3) * 0.15
    return _fade(_norm((noise * nm + res * (1 - nm) + harm) * np.exp(-t * decay * 1.2)), sr=sr)


def _synth_capture(sr=44100, freq=600, decay=25, nm=0.5, dur=0.15):
    t = np.linspace(0, dur, int(sr * dur), False)
    noise = np.random.randn(len(t)) * np.exp(-t * decay * 1.2)
    body = np.sin(2 * np.pi * freq * t) * np.exp(-t * decay * 0.8)
    click = np.sin(2 * np.pi * 2500 * t) * np.exp(-t * 80) * 0.25
    return _fade(_norm((noise * nm + body * (1 - nm) + click) * np.exp(-t * decay * 0.9)), sr=sr)


def _synth_check(sr=44100):
    d1, g, d2 = 0.06, 0.02, 0.09
    t1 = np.linspace(0, d1, int(sr * d1), False)
    t2 = np.linspace(0, d2, int(sr * d2), False)
    return _fade(_norm(np.concatenate([
        np.sin(2 * np.pi * 880 * t1) * np.exp(-t1 * 25),
        np.zeros(int(sr * g)),
        np.sin(2 * np.pi * 1320 * t2) * np.exp(-t2 * 20),
    ])), sr=sr)


def _synth_checkmate(sr=44100):
    t = np.linspace(0, 0.45, int(sr * 0.45), False)
    env = np.exp(-t * 4.5)
    chord = (np.sin(2 * np.pi * 523 * t) +
             np.sin(2 * np.pi * 659 * t) +
             np.sin(2 * np.pi * 784 * t)) / 3.0
    return _fade(_norm(chord * env), fade_ms=3, sr=sr)


def _synth_castle(sr=44100):
    t = np.linspace(0, 0.06, int(sr * 0.06), False)
    noise = np.random.randn(len(t)) * np.exp(-t * 65)
    tap = _norm(np.sin(2 * np.pi * 1500 * t) * np.exp(-t * 55) * 0.6 + noise * 0.4)
    return _fade(_norm(np.concatenate([tap, np.zeros(int(sr * 0.06)), tap * 0.85])), sr=sr)


def _synth_illegal(sr=44100):
    t = np.linspace(0, 0.12, int(sr * 0.12), False)
    env = np.exp(-t * 14)
    return _fade(_norm(
        (np.sin(2 * np.pi * 200 * t) +
         np.sin(2 * np.pi * 203 * t) +
         np.random.randn(len(t)) * 0.25) * env), sr=sr)


def _synth_new_game(sr=44100):
    parts = []
    for f in [523, 659, 784]:
        t = np.linspace(0, 0.08, int(sr * 0.08), False)
        parts.append(np.sin(2 * np.pi * f * t) * np.exp(-t * 18))
        parts.append(np.zeros(int(sr * 0.015)))
    return _fade(_norm(np.concatenate(parts)), sr=sr)


def _synth_promotion(sr=44100):
    t = np.linspace(0, 0.22, int(sr * 0.22), False)
    freq = 600 + 800 * (t / 0.22)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    return _fade(_norm(np.sin(phase) * np.exp(-t * 6)), sr=sr)


def _synth_ui_click(sr=44100):
    t = np.linspace(0, 0.025, int(sr * 0.025), False)
    return _fade(_norm(np.sin(2 * np.pi * 3200 * t) * np.exp(-t * 120)),
                 fade_ms=1, sr=sr)


# ── Theme & Design parameter sets ─────────────────────────────────
_THEME_PARAMS = {
    "Classic": {
        "move": {"freq": 1800, "decay": 50, "nm": 0.40, "dur": 0.08},
        "capture": {"freq": 600, "decay": 25, "nm": 0.50, "dur": 0.15},
    },
    "Digital": {
        "move": {"freq": 1000, "decay": 40, "nm": 0.08, "dur": 0.05},
        "capture": {"freq": 500, "decay": 18, "nm": 0.12, "dur": 0.10},
    },
    "Tournament": {
        "move": {"freq": 2200, "decay": 70, "nm": 0.35, "dur": 0.06},
        "capture": {"freq": 700, "decay": 35, "nm": 0.45, "dur": 0.12},
    },
}

# Sound design modifiers applied after theme params
_SOUND_DESIGN_MODS = {
    "Default": {
        "freq_mul": 1.0, "decay_mul": 1.0, "reverb": 0.0,
        "brightness": 1.0, "warmth": 0.0, "bits": 16,
    },
    "Warm": {
        "freq_mul": 0.85, "decay_mul": 0.7, "reverb": 0.18,
        "brightness": 0.65, "warmth": 0.3, "bits": 16,
    },
    "Crisp": {
        "freq_mul": 1.25, "decay_mul": 1.4, "reverb": 0.0,
        "brightness": 1.6, "warmth": -0.15, "bits": 16,
    },
    "Retro": {
        "freq_mul": 0.75, "decay_mul": 0.55, "reverb": 0.0,
        "brightness": 0.45, "warmth": 0.0, "bits": 8,
    },
    "Cinematic": {
        "freq_mul": 0.9, "decay_mul": 0.6, "reverb": 0.28,
        "brightness": 0.85, "warmth": 0.2, "bits": 16,
    },
    "Minimal": {
        "freq_mul": 1.1, "decay_mul": 2.2, "reverb": 0.0,
        "brightness": 0.35, "warmth": 0.0, "bits": 16,
    },
}


class SoundManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = True
        self._volume = 0.7
        self._theme = "Classic"
        self._design = "Default"
        self._sounds = {}
        self._temp_dir = None
        self._type_vol = {t: 1.0 for t in SOUND_TYPES}

        if not HAS_MM or not HAS_NP:
            self.enabled = False
            return
        self._temp_dir = tempfile.mkdtemp(prefix="chess_snd_")
        self._generate_all()

    def _apply_design(self, signal, sr=44100):
        """Apply current sound design post-processing to a synthesized signal."""
        mod = _SOUND_DESIGN_MODS.get(self._design, _SOUND_DESIGN_MODS["Default"])
        # Reverb
        signal = _add_reverb(signal, amount=mod["reverb"], sr=sr)
        # Brightness — boost or cut high harmonics via a simple high-shelf
        if mod["brightness"] != 1.0:
            # Approximate: mix original with a high-pass version
            from scipy.signal import butter, filtfilt
            try:
                b, a = butter(4, 3000 / (sr / 2), btype='high')
                hp = filtfilt(b, a, signal)
                factor = mod["brightness"] - 1.0
                signal = signal + hp * factor
            except Exception:
                # Fallback if scipy not available
                t = np.arange(len(signal))
                hp = np.diff(np.append(signal[0], signal)) * 0.5
                factor = mod["brightness"] - 1.0
                signal = signal + hp * factor
            signal = _norm(signal)
        # Warmth — add subtle low-frequency content
        if mod["warmth"] > 0:
            t = np.linspace(0, len(signal) / sr, len(signal), False)
            warmth = np.sin(2 * np.pi * 120 * t) * mod["warmth"] * 0.15
            signal = _norm(signal + warmth)
        elif mod["warmth"] < 0:
            # Reduce low end slightly
            signal = signal * 0.95
        # Bitcrush for retro
        if mod["bits"] < 16:
            signal = _bitcrush(signal, mod["bits"])
        return _norm(signal)

    def _get_modified_params(self, stype):
        """Get theme params modified by current sound design."""
        params = _THEME_PARAMS.get(self._theme, _THEME_PARAMS["Classic"])
        mod = _SOUND_DESIGN_MODS.get(self._design, _SOUND_DESIGN_MODS["Default"])
        if stype in params:
            p = dict(params[stype])
            p["freq"] = p.get("freq", 1800) * mod["freq_mul"]
            p["decay"] = p.get("decay", 50) * mod["decay_mul"]
            p["nm"] = max(0, min(1, p.get("nm", 0.4) * mod.get("brightness", 1.0)))
            p["dur"] = p.get("dur", 0.08) * (1.0 / max(0.3, mod["decay_mul"]))
            return p
        return {}

    def _generate_all(self):
        for e in self._sounds.values():
            e.stop()
        self._sounds.clear()
        if self._theme == "Silent":
            return

        mod = _SOUND_DESIGN_MODS.get(self._design, _SOUND_DESIGN_MODS["Default"])
        sr = 44100

        # Get modified theme params for move/capture
        move_p = self._get_modified_params("move")
        capture_p = self._get_modified_params("capture")

        # Check design-specific parameter modifications for other sounds
        check_freq = 880 * mod["freq_mul"]
        checkmate_dur = 0.45 / max(0.3, mod["decay_mul"])
        castle_freq = 1500 * mod["freq_mul"]
        illegal_freq = 200 * mod["freq_mul"]
        new_game_base = 523 * mod["freq_mul"]
        promo_base = 600 * mod["freq_mul"]

        synth_map = {
            "move": lambda: self._apply_design(_synth_move(sr, **move_p), sr),
            "capture": lambda: self._apply_design(_synth_capture(sr, **capture_p), sr),
            "check": lambda: self._apply_design(
                _synth_check_design(sr, check_freq), sr),
            "checkmate": lambda: self._apply_design(
                _synth_checkmate_design(sr, checkmate_dur, new_game_base), sr),
            "castle": lambda: self._apply_design(
                _synth_castle_design(sr, castle_freq), sr),
            "illegal": lambda: self._apply_design(
                _synth_illegal_design(sr, illegal_freq), sr),
            "new_game": lambda: self._apply_design(
                _synth_new_game_design(sr, new_game_base), sr),
            "promotion": lambda: self._apply_design(
                _synth_promotion_design(sr, promo_base), sr),
            "ui_click": lambda: self._apply_design(
                _synth_ui_click_design(sr, 3200 * mod["freq_mul"]), sr),
        }

        for stype, fn in synth_map.items():
            try:
                wav = _to_wav(fn(), sr)
                fp = os.path.join(self._temp_dir, f"{stype}_{self._design}.wav")
                with open(fp, 'wb') as f:
                    f.write(wav)
                eff = QSoundEffect(self)
                eff.setSource(QUrl.fromLocalFile(fp))
                eff.setVolume(max(0, min(1,
                    self._volume * self._type_vol.get(stype, 1.0))))
                self._sounds[stype] = eff
            except Exception as e:
                logger.error("Sound gen error %s: %s", stype, e)

    def play(self, stype):
        if not self.enabled or stype not in self._sounds:
            return
        e = self._sounds[stype]
        if e.isPlaying():
            e.stop()
        e.play()

    def set_volume(self, v):
        self._volume = max(0, min(1, v))
        for t, e in self._sounds.items():
            e.setVolume(max(0, min(1,
                self._volume * self._type_vol.get(t, 1.0))))

    def set_type_volume(self, t, v):
        self._type_vol[t] = max(0, min(1, v))
        if t in self._sounds:
            self._sounds[t].setVolume(max(0, min(1, self._volume * v)))

    def set_theme(self, t):
        self._theme = t if t in SOUND_THEMES else "Classic"
        self._generate_all()

    def set_design(self, d):
        """Set the sound design preset."""
        self._design = d if d in SOUND_DESIGNS else "Default"
        self._generate_all()

    def set_enabled(self, e):
        self.enabled = e

    def cleanup(self):
        # Stop and release all QSoundEffect objects — on Windows they
        # hold open file handles inside self._temp_dir.
        for stype, eff in list(self._sounds.items()):
            try:
                if eff.isPlaying():
                    eff.stop()
                eff.setSource(QUrl())
                eff.deleteLater()        # Schedule C++ object deletion
            except RuntimeError:
                pass
        self._sounds.clear()

        # Force Python GC and Qt event processing to release C++ objects
        gc.collect()
        try:
            from PySide6.QtWidgets import QApplication
            if QApplication.instance():
                for _ in range(3):
                    QApplication.processEvents()
        except RuntimeError:
            pass
        gc.collect()

        # Remove temp directory with retries (Windows needs time to
        # release file handles after C++ objects are deleted)
        if self._temp_dir and os.path.isdir(self._temp_dir):
            for attempt in range(8):
                try:
                    shutil.rmtree(self._temp_dir)
                    break
                except OSError:
                    gc.collect()
                    time.sleep(0.15 * (attempt + 1))
                    try:
                        from PySide6.QtWidgets import QApplication
                        if QApplication.instance():
                            QApplication.processEvents()
                    except RuntimeError:
                        pass
        self._temp_dir = None


# ── Design-aware synthesizers for non-theme-param sounds ───────────
def _synth_check_design(sr=44100, freq=880):
    d1, g, d2 = 0.06, 0.02, 0.09
    t1 = np.linspace(0, d1, int(sr * d1), False)
    t2 = np.linspace(0, d2, int(sr * d2), False)
    return _fade(_norm(np.concatenate([
        np.sin(2 * np.pi * freq * t1) * np.exp(-t1 * 25),
        np.zeros(int(sr * g)),
        np.sin(2 * np.pi * freq * 1.5 * t2) * np.exp(-t2 * 20),
    ])), sr=sr)


def _synth_checkmate_design(sr=44100, dur=0.45, base_freq=523):
    t = np.linspace(0, dur, int(sr * dur), False)
    env = np.exp(-t * 4.5)
    chord = (np.sin(2 * np.pi * base_freq * t) +
             np.sin(2 * np.pi * base_freq * 1.26 * t) +
             np.sin(2 * np.pi * base_freq * 1.5 * t)) / 3.0
    return _fade(_norm(chord * env), fade_ms=3, sr=sr)


def _synth_castle_design(sr=44100, freq=1500):
    t = np.linspace(0, 0.06, int(sr * 0.06), False)
    noise = np.random.randn(len(t)) * np.exp(-t * 65)
    tap = _norm(np.sin(2 * np.pi * freq * t) * np.exp(-t * 55) * 0.6 + noise * 0.4)
    return _fade(_norm(np.concatenate([tap, np.zeros(int(sr * 0.06)), tap * 0.85])), sr=sr)


def _synth_illegal_design(sr=44100, freq=200):
    t = np.linspace(0, 0.12, int(sr * 0.12), False)
    env = np.exp(-t * 14)
    return _fade(_norm(
        (np.sin(2 * np.pi * freq * t) +
         np.sin(2 * np.pi * (freq + 3) * t) +
         np.random.randn(len(t)) * 0.25) * env), sr=sr)


def _synth_new_game_design(sr=44100, base_freq=523):
    parts = []
    for ratio in [1.0, 1.26, 1.5]:
        f = base_freq * ratio
        t = np.linspace(0, 0.08, int(sr * 0.08), False)
        parts.append(np.sin(2 * np.pi * f * t) * np.exp(-t * 18))
        parts.append(np.zeros(int(sr * 0.015)))
    return _fade(_norm(np.concatenate(parts)), sr=sr)


def _synth_promotion_design(sr=44100, base_freq=600):
    t = np.linspace(0, 0.22, int(sr * 0.22), False)
    freq = base_freq + 800 * (t / 0.22)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    return _fade(_norm(np.sin(phase) * np.exp(-t * 6)), sr=sr)


def _synth_ui_click_design(sr=44100, freq=3200):
    t = np.linspace(0, 0.025, int(sr * 0.025), False)
    return _fade(_norm(np.sin(2 * np.pi * freq * t) * np.exp(-t * 120)),
                 fade_ms=1, sr=sr)