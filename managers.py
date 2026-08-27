"""Chess Video Maker Pro — Animation & Sound Managers"""
import io
import os
import wave
import math
import tempfile
import shutil
import logging
import gc
import time

from PySide6.QtCore import QObject, QUrl, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor

from constants import ANIM_EASINGS, SOUND_THEMES, SOUND_TYPES, SOUND_DESIGNS

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

logger = logging.getLogger("ChessVideoMaker.Managers")


# ════════════════════════════════════════════════════════════════════
#  AnimationManager
# ════════════════════════════════════════════════════════════════════
_EASING_MAP = {
    "Linear": QEasingCurve.Linear, "OutCubic": QEasingCurve.OutCubic,
    "InCubic": QEasingCurve.InCubic, "InOutCubic": QEasingCurve.InOutCubic,
    "OutBack": QEasingCurve.OutBack, "OutBounce": QEasingCurve.OutBounce,
}


class AnimationManager(QObject):
    def __init__(self, board_widget, eval_bar_widget, parent=None):
        super().__init__(parent)
        self.bw = board_widget; self.ew = eval_bar_widget
        self.enabled = True; self.piece_anim = True
        self.highlight_anim = True; self.eval_anim = True
        self.duration = 250; self.easing_name = "OutCubic"
        self._active = []

    def _easing(self):
        return _EASING_MAP.get(self.easing_name, QEasingCurve.OutCubic)

    def _reg(self, a):
        self._active.append(a)
        a.finished.connect(lambda checked=False, anim=a: self._unreg(anim))

    def _unreg(self, a):
        if a in self._active: self._active.remove(a)

    def cancel_all(self):
        for a in list(self._active): a.stop()
        self._active.clear()

    def animate_piece_move(self, move, callback=None):
        import chess
        if not self.enabled or not self.piece_anim:
            if callback: callback()
            return
        bw = self.bw; bw.anim_move = move; bw._anim_progress_val = 0.0
        rook_move = None
        pc = bw.board.piece_at(move.to_square)
        if (pc and pc.piece_type == chess.KING and
                abs(chess.square_file(move.from_square) -
                    chess.square_file(move.to_square)) == 2):
            rank = chess.square_rank(move.from_square)
            if chess.square_file(move.to_square) > chess.square_file(move.from_square):
                rook_move = (chess.square(7, rank), chess.square(5, rank))
            else:
                rook_move = (chess.square(0, rank), chess.square(3, rank))
        bw.anim_rook_move = rook_move
        a = QPropertyAnimation(bw, b"animProgress")
        a.setDuration(self.duration); a.setStartValue(0.0); a.setEndValue(1.0)
        a.setEasingCurve(self._easing())
        def done():
            bw.anim_move = None; bw.anim_rook_move = None
            bw._anim_progress_val = 1.0; bw.update()
            if callback: callback()
        a.finished.connect(done); a.start(); self._reg(a)

    def animate_check(self, king_sq):
        if not self.enabled or not self.highlight_anim: return
        self.bw._check_square = king_sq
        a = QPropertyAnimation(self.bw, b"checkOpacity"); a.setDuration(700)
        a.setKeyValueAt(0.0, 0.0); a.setKeyValueAt(0.15, 1.0)
        a.setKeyValueAt(0.35, 0.25); a.setKeyValueAt(0.55, 0.75)
        a.setKeyValueAt(1.0, 0.0)
        def done():
            self.bw._check_square = None; self.bw._check_opacity_val = 0.0; self.bw.update()
        a.finished.connect(done); a.start(); self._reg(a)

    def animate_last_move_flash(self, fr, to):
        if not self.enabled or not self.highlight_anim: return
        self.bw._flash_squares = (fr, to)
        a = QPropertyAnimation(self.bw, b"flashOpacity"); a.setDuration(350)
        a.setKeyValueAt(0.0, 0.0); a.setKeyValueAt(0.2, 0.8); a.setKeyValueAt(1.0, 0.0)
        a.setEasingCurve(QEasingCurve.OutCubic)
        def done():
            self.bw._flash_squares = (); self.bw._flash_opacity_val = 0.0; self.bw.update()
        a.finished.connect(done); a.start(); self._reg(a)

    def configure_eval_bar(self):
        if self.ew:
            self.ew.set_anim_duration(self.duration if self.eval_anim else 0)

    def set_duration(self, ms):
        self.duration = max(50, min(2000, ms)); self.configure_eval_bar()

    def set_easing(self, n):
        self.easing_name = n if n in ANIM_EASINGS else "OutCubic"

    def set_piece_anim(self, e): self.piece_anim = e
    def set_highlight_anim(self, e): self.highlight_anim = e

    def set_eval_anim(self, e):
        self.eval_anim = e; self.configure_eval_bar()


# ════════════════════════════════════════════════════════════════════
#  SoundManager — Professional Synthesized Sound
# ════════════════════════════════════════════════════════════════════
def _to_wav(signal, sr=44100):
    signal = np.clip(signal, -1.0, 1.0)
    samples = (signal * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes(samples.tobytes())
    buf.seek(0); return buf.getvalue()

def _fade(signal, fade_ms=2, sr=44100):
    f = min(int(sr * fade_ms / 1000), len(signal) // 4)
    if f > 1:
        signal[:f] *= np.linspace(0, 1, f); signal[-f:] *= np.linspace(1, 0, f)
    return signal

def _norm(signal):
    p = np.max(np.abs(signal))
    return signal / p * 0.9 if p > 1e-10 else signal

def _add_reverb(signal, amount=0.15, delay_ms=30, decay=0.5, sr=44100):
    if amount <= 0: return signal
    delay_samples = int(sr * delay_ms / 1000)
    out = signal.copy(); atten = amount
    for _ in range(3):
        delayed = np.zeros_like(out); d = min(delay_samples, len(out))
        delayed[d:] = out[:-d] * atten; out = out + delayed; atten *= decay
    return _norm(out)

def _bitcrush(signal, bits=8):
    if bits >= 16: return signal
    levels = 2 ** bits; return np.round(signal * levels) / levels

def _synth_move(sr=44100, freq=1800, decay=50, nm=0.4, dur=0.08):
    t = np.linspace(0, dur, int(sr*dur), False)
    noise = np.random.randn(len(t)) * np.exp(-t*decay*1.6)
    res = np.sin(2*np.pi*freq*t) * np.exp(-t*decay)
    harm = np.sin(2*np.pi*freq*2.4*t) * np.exp(-t*decay*1.3) * 0.15
    return _fade(_norm((noise*nm + res*(1-nm) + harm) * np.exp(-t*decay*1.2)), sr=sr)

def _synth_capture(sr=44100, freq=600, decay=25, nm=0.5, dur=0.15):
    t = np.linspace(0, dur, int(sr*dur), False)
    noise = np.random.randn(len(t)) * np.exp(-t*decay*1.2)
    body = np.sin(2*np.pi*freq*t) * np.exp(-t*decay*0.8)
    click = np.sin(2*np.pi*2500*t) * np.exp(-t*80) * 0.25
    return _fade(_norm((noise*nm + body*(1-nm) + click) * np.exp(-t*decay*0.9)), sr=sr)

def _synth_check(sr=44100, freq=880):
    d1, g, d2 = 0.06, 0.02, 0.09
    t1 = np.linspace(0, d1, int(sr*d1), False)
    t2 = np.linspace(0, d2, int(sr*d2), False)
    return _fade(_norm(np.concatenate([
        np.sin(2*np.pi*freq*t1)*np.exp(-t1*25), np.zeros(int(sr*g)),
        np.sin(2*np.pi*freq*1.5*t2)*np.exp(-t2*20)])), sr=sr)

def _synth_checkmate(sr=44100, dur=0.45, base_freq=523):
    t = np.linspace(0, dur, int(sr*dur), False)
    env = np.exp(-t*4.5)
    chord = (np.sin(2*np.pi*base_freq*t) + np.sin(2*np.pi*base_freq*1.26*t) +
             np.sin(2*np.pi*base_freq*1.5*t)) / 3.0
    return _fade(_norm(chord * env), fade_ms=3, sr=sr)

def _synth_castle(sr=44100, freq=1500):
    t = np.linspace(0, 0.06, int(sr*0.06), False)
    noise = np.random.randn(len(t)) * np.exp(-t*65)
    tap = _norm(np.sin(2*np.pi*freq*t)*np.exp(-t*55)*0.6 + noise*0.4)
    return _fade(_norm(np.concatenate([tap, np.zeros(int(sr*0.06)), tap*0.85])), sr=sr)

def _synth_illegal(sr=44100, freq=200):
    t = np.linspace(0, 0.12, int(sr*0.12), False)
    env = np.exp(-t*14)
    return _fade(_norm((np.sin(2*np.pi*freq*t) + np.sin(2*np.pi*(freq+3)*t) +
                        np.random.randn(len(t))*0.25) * env), sr=sr)

def _synth_new_game(sr=44100, base_freq=523):
    parts = []
    for ratio in [1.0, 1.26, 1.5]:
        f = base_freq * ratio; t = np.linspace(0, 0.08, int(sr*0.08), False)
        parts.append(np.sin(2*np.pi*f*t)*np.exp(-t*18))
        parts.append(np.zeros(int(sr*0.015)))
    return _fade(_norm(np.concatenate(parts)), sr=sr)

def _synth_promotion(sr=44100, base_freq=600):
    t = np.linspace(0, 0.22, int(sr*0.22), False)
    freq = base_freq + 800*(t/0.22); phase = 2*np.pi*np.cumsum(freq)/sr
    return _fade(_norm(np.sin(phase)*np.exp(-t*6)), sr=sr)

def _synth_ui_click(sr=44100, freq=3200):
    t = np.linspace(0, 0.025, int(sr*0.025), False)
    return _fade(_norm(np.sin(2*np.pi*freq*t)*np.exp(-t*120)), fade_ms=1, sr=sr)

_THEME_PARAMS = {
    "Classic": {"move":{"freq":1800,"decay":50,"nm":0.40,"dur":0.08},
                "capture":{"freq":600,"decay":25,"nm":0.50,"dur":0.15}},
    "Digital": {"move":{"freq":1000,"decay":40,"nm":0.08,"dur":0.05},
                "capture":{"freq":500,"decay":18,"nm":0.12,"dur":0.10}},
    "Tournament": {"move":{"freq":2200,"decay":70,"nm":0.35,"dur":0.06},
                   "capture":{"freq":700,"decay":35,"nm":0.45,"dur":0.12}},
}

_SOUND_DESIGN_MODS = {
    "Default": {"freq_mul":1.0,"decay_mul":1.0,"reverb":0.0,"brightness":1.0,"warmth":0.0,"bits":16},
    "Warm": {"freq_mul":0.85,"decay_mul":0.7,"reverb":0.18,"brightness":0.65,"warmth":0.3,"bits":16},
    "Crisp": {"freq_mul":1.25,"decay_mul":1.4,"reverb":0.0,"brightness":1.6,"warmth":-0.15,"bits":16},
    "Retro": {"freq_mul":0.75,"decay_mul":0.55,"reverb":0.0,"brightness":0.45,"warmth":0.0,"bits":8},
    "Cinematic": {"freq_mul":0.9,"decay_mul":0.6,"reverb":0.28,"brightness":0.85,"warmth":0.2,"bits":16},
    "Minimal": {"freq_mul":1.1,"decay_mul":2.2,"reverb":0.0,"brightness":0.35,"warmth":0.0,"bits":16},
}

_SOUND_DESIGN_DESC = {
    "Default": "🎵 Default — Standard balanced sound",
    "Warm": "🎸 Warm — Softer tones with reverb and low-frequency warmth",
    "Crisp": "🔔 Crisp — Bright, sharp attack with fast decay",
    "Retro": "🕹️ Retro — 8-bit lo-fi crunch with short punchy sounds",
    "Cinematic": "🎬 Cinematic — Deep, atmospheric with rich reverb",
    "Minimal": "◻️ Minimal — Ultra-subtle, very short and quiet",
}


class SoundManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = True; self._volume = 0.7
        self._theme = "Classic"; self._design = "Default"
        self._sounds = {}; self._temp_dir = None
        self._type_vol = {t: 1.0 for t in SOUND_TYPES}
        if not HAS_MM or not HAS_NP:
            self.enabled = False; return
        self._temp_dir = tempfile.mkdtemp(prefix="chess_snd_")
        self._generate_all()

    def _apply_design(self, signal, sr=44100):
        mod = _SOUND_DESIGN_MODS.get(self._design, _SOUND_DESIGN_MODS["Default"])
        signal = _add_reverb(signal, amount=mod["reverb"], sr=sr)
        if mod["brightness"] != 1.0:
            try:
                from scipy.signal import butter, filtfilt
                b, a = butter(4, 3000/(sr/2), btype='high')
                hp = filtfilt(b, a, signal)
                signal = signal + hp * (mod["brightness"] - 1.0)
            except Exception:
                hp = np.diff(np.append(signal[0], signal)) * 0.5
                signal = signal + hp * (mod["brightness"] - 1.0)
            signal = _norm(signal)
        if mod["warmth"] > 0:
            t = np.linspace(0, len(signal)/sr, len(signal), False)
            signal = _norm(signal + np.sin(2*np.pi*120*t) * mod["warmth"] * 0.15)
        elif mod["warmth"] < 0:
            signal = signal * 0.95
        if mod["bits"] < 16:
            signal = _bitcrush(signal, mod["bits"])
        return _norm(signal)

    def _get_modified_params(self, stype):
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
        for e in self._sounds.values(): e.stop()
        self._sounds.clear()
        if self._theme == "Silent": return
        mod = _SOUND_DESIGN_MODS.get(self._design, _SOUND_DESIGN_MODS["Default"])
        sr = 44100
        move_p = self._get_modified_params("move")
        capture_p = self._get_modified_params("capture")
        check_freq = 880 * mod["freq_mul"]
        checkmate_dur = 0.45 / max(0.3, mod["decay_mul"])
        castle_freq = 1500 * mod["freq_mul"]
        illegal_freq = 200 * mod["freq_mul"]
        new_game_base = 523 * mod["freq_mul"]
        promo_base = 600 * mod["freq_mul"]

        synth_map = {
            "move": lambda: self._apply_design(_synth_move(sr, **move_p), sr),
            "capture": lambda: self._apply_design(_synth_capture(sr, **capture_p), sr),
            "check": lambda: self._apply_design(_synth_check(sr, check_freq), sr),
            "checkmate": lambda: self._apply_design(_synth_checkmate(sr, checkmate_dur, new_game_base), sr),
            "castle": lambda: self._apply_design(_synth_castle(sr, castle_freq), sr),
            "illegal": lambda: self._apply_design(_synth_illegal(sr, illegal_freq), sr),
            "new_game": lambda: self._apply_design(_synth_new_game(sr, new_game_base), sr),
            "promotion": lambda: self._apply_design(_synth_promotion(sr, promo_base), sr),
            "ui_click": lambda: self._apply_design(_synth_ui_click(sr, 3200*mod["freq_mul"]), sr),
        }
        for stype, fn in synth_map.items():
            try:
                wav = _to_wav(fn(), sr)
                fp = os.path.join(self._temp_dir, f"{stype}_{self._design}.wav")
                with open(fp, 'wb') as f: f.write(wav)
                eff = QSoundEffect(self)
                eff.setSource(QUrl.fromLocalFile(fp))
                eff.setVolume(max(0, min(1, self._volume * self._type_vol.get(stype, 1.0))))
                self._sounds[stype] = eff
            except Exception as e:
                logger.error("Sound gen error %s: %s", stype, e)

    def play(self, stype):
        if not self.enabled or stype not in self._sounds: return
        e = self._sounds[stype]
        if e.isPlaying(): e.stop()
        e.play()

    def set_volume(self, v):
        self._volume = max(0, min(1, v))
        for t, e in self._sounds.items():
            e.setVolume(max(0, min(1, self._volume * self._type_vol.get(t, 1.0))))

    def set_type_volume(self, t, v):
        self._type_vol[t] = max(0, min(1, v))
        if t in self._sounds:
            self._sounds[t].setVolume(max(0, min(1, self._volume * v)))

    def set_theme(self, t):
        self._theme = t if t in SOUND_THEMES else "Classic"; self._generate_all()

    def set_design(self, d):
        self._design = d if d in SOUND_DESIGNS else "Default"; self._generate_all()

    def set_enabled(self, e): self.enabled = e

    def cleanup(self):
        for stype, eff in list(self._sounds.items()):
            try:
                if eff.isPlaying(): eff.stop()
                eff.setSource(QUrl()); eff.deleteLater()
            except RuntimeError: pass
        self._sounds.clear(); gc.collect()
        try:
            from PySide6.QtWidgets import QApplication
            if QApplication.instance():
                for _ in range(3): QApplication.processEvents()
        except RuntimeError: pass
        gc.collect()
        if self._temp_dir and os.path.isdir(self._temp_dir):
            for attempt in range(8):
                try: shutil.rmtree(self._temp_dir); break
                except OSError:
                    gc.collect(); time.sleep(0.15 * (attempt + 1))
                    try:
                        from PySide6.QtWidgets import QApplication
                        if QApplication.instance(): QApplication.processEvents()
                    except RuntimeError: pass
        self._temp_dir = None