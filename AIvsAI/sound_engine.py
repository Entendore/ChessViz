"""Procedural sound engine — generates WAV at runtime, no external assets."""

import os
import wave          # ← THIS WAS MISSING — caused all theme generation to fail
import shutil
import tempfile
import atexit
import logging

import chess
from PySide6.QtCore import QObject, Signal, QUrl

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from PySide6.QtMultimedia import QSoundEffect
    HAS_QTMULTIMEDIA = True
except ImportError:
    HAS_QTMULTIMEDIA = False

from constants import (
    SND_MOVE, SND_CAPTURE, SND_CHECK, SND_CASTLE,
    SND_CHECKMATE, SND_STALEMATE, SND_DRAW,
    SND_GAME_START, SND_UI_CLICK, SOUND_THEME_LIST,
)

logger = logging.getLogger("AIvsAI2MP4")


class SoundEngine(QObject):
    sound_played = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_name = "Classic"
        self._volume = 0.70
        self._muted = False
        self._enabled = True
        self._effects = {}
        self._sound_files = {}
        self._temp_dir = tempfile.mkdtemp(prefix="chess_snd_")
        self._sr = 44100

        if not HAS_NUMPY or not HAS_QTMULTIMEDIA:
            self._enabled = False
            return
        try:
            self._generate_all_themes()
            self._apply_theme(self._theme_name)
            atexit.register(self.cleanup)
        except Exception as e:
            logger.warning(f"Sound engine init failed: {e}")
            self._enabled = False

    # ── Public API ────────────────────────────────────────────
    def play(self, event):
        if not self._enabled or self._muted:
            return
        fx = self._effects.get(event)
        if fx:
            if fx.isPlaying():
                fx.stop()
            fx.play()
            self.sound_played.emit(event)

    def play_move_sound(self, board, move):
        if not self._enabled or self._muted:
            return
        piece = board.piece_at(move.from_square)
        is_cap = board.is_capture(move)
        is_castle = (piece and piece.piece_type == chess.KING and
                     abs(chess.square_file(move.from_square) -
                         chess.square_file(move.to_square)) == 2)
        gives_check = board.gives_check(move)
        board.push(move)
        is_mate = board.is_checkmate()
        is_stale = board.is_stalemate()
        is_draw = board.is_game_over() and not is_mate and not is_stale
        board.pop()
        if is_mate:       self.play(SND_CHECKMATE)
        elif is_stale:    self.play(SND_STALEMATE)
        elif is_draw:     self.play(SND_DRAW)
        elif gives_check: self.play(SND_CHECK)
        elif is_castle:   self.play(SND_CASTLE)
        elif is_cap:      self.play(SND_CAPTURE)
        else:             self.play(SND_MOVE)

    def play_game_end(self, result_type):
        m = {"checkmate": SND_CHECKMATE, "stalemate": SND_STALEMATE, "draw": SND_DRAW}
        self.play(m.get(result_type, SND_DRAW))

    def set_theme(self, name):
        if name == self._theme_name or not self._enabled:
            return
        self._theme_name = name
        self._apply_theme(name)

    def set_volume(self, vol):
        self._volume = max(0.0, min(1.0, vol))
        for fx in self._effects.values():
            fx.setVolume(self._volume)

    def set_muted(self, m):
        self._muted = m

    @property
    def enabled(self):
        return self._enabled

    @property
    def theme(self):
        return self._theme_name

    @property
    def volume(self):
        return self._volume

    @property
    def muted(self):
        return self._muted

    @property
    def available_themes(self):
        return SOUND_THEME_LIST if self._enabled else []

    def get_sound_path(self, event, theme=None):
        if not self._enabled:
            return None
        t = theme or self._theme_name
        return self._sound_files.get(t, {}).get(event)

    def cleanup(self):
        try:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        except Exception:
            pass

    # ── Internal ──────────────────────────────────────────────
    def _apply_theme(self, name):
        if name not in self._sound_files:
            return
        for fx in self._effects.values():
            if fx.isPlaying():
                fx.stop()
        self._effects.clear()
        for event, fp in self._sound_files[name].items():
            fx = QSoundEffect(self)
            fx.setSource(QUrl.fromLocalFile(os.path.abspath(fp)))
            fx.setVolume(self._volume)
            self._effects[event] = fx

    def _generate_all_themes(self):
        gens = {
            "Classic": self._gen_classic,
            "Digital": self._gen_digital,
            "Cinematic": self._gen_cinematic,
            "Retro": self._gen_retro,
            "Ambient": self._gen_ambient,
        }
        for tn, gen in gens.items():
            try:
                samples = gen()
                self._sound_files[tn] = {}
                for event, arr in samples.items():
                    fp = self._write_wav(f"{tn.lower()}_{event}.wav", arr)
                    self._sound_files[tn][event] = fp
                logger.info("Sound theme '%s' generated (%d sounds)", tn, len(samples))
            except Exception as e:
                logger.warning("Theme '%s' failed: %s", tn, e)

    def _write_wav(self, fn, s16):
        fp = os.path.join(self._temp_dir, fn)
        with wave.open(fp, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sr)
            wf.writeframes(s16.tobytes())
        return fp

    @staticmethod
    def _to_int16(a):
        a = np.clip(a, -1.0, 1.0)
        return (a * 32767).astype(np.int16)

    # ── Theme generators ──────────────────────────────────────
    def _gen_classic(self):
        sr = self._sr
        s = {}
        t = np.linspace(0, .08, int(sr * .08), False)
        e = np.exp(-t * 60)
        s[SND_MOVE] = self._to_int16(
            (np.random.randn(len(t)) * .3 * e +
             np.sin(2 * np.pi * 800 * t) * e * .2) * .5
        )
        t = np.linspace(0, .12, int(sr * .12), False)
        e = np.exp(-t * 40)
        s[SND_CAPTURE] = self._to_int16(
            (np.random.randn(len(t)) * .5 * e +
             np.sin(2 * np.pi * 400 * t) * e * .4) * .6
        )
        t = np.linspace(0, .2, int(sr * .2), False)
        e = np.exp(-t * 15)
        s[SND_CHECK] = self._to_int16(
            (np.sin(2 * np.pi * 1200 * t) * e * .4 +
             np.sin(2 * np.pi * 900 * t) * e * .3) * .5
        )
        t1 = np.linspace(0, .06, int(sr * .06), False)
        g = np.zeros(int(sr * .04))
        t2 = np.linspace(0, .06, int(sr * .06), False)
        s[SND_CASTLE] = self._to_int16(
            np.concatenate([
                np.random.randn(len(t1)) * np.exp(-t1 * 50) * .3,
                g,
                np.random.randn(len(t2)) * np.exp(-t2 * 50) * .3
            ]) * .5
        )
        t = np.linspace(0, .6, int(sr * .6), False)
        e = np.exp(-t * 4)
        s[SND_CHECKMATE] = self._to_int16(
            (np.sin(2 * np.pi * 523 * t) * e * .2 +
             np.sin(2 * np.pi * 659 * t) * e * .2 +
             np.sin(2 * np.pi * 784 * t) * e * .2) * .5
        )
        t = np.linspace(0, .3, int(sr * .3), False)
        e = np.exp(-t * 8)
        s[SND_STALEMATE] = self._to_int16(np.sin(2 * np.pi * 440 * t) * e * .3)
        s[SND_DRAW] = s[SND_STALEMATE]
        t = np.linspace(0, .4, int(sr * .4), False)
        e = np.exp(-t * 6)
        s[SND_GAME_START] = self._to_int16(
            (np.sin(2 * np.pi * 660 * t) * e * .25 +
             np.sin(2 * np.pi * 880 * t) * e * .15) * .5
        )
        t = np.linspace(0, .03, int(sr * .03), False)
        e = np.exp(-t * 100)
        s[SND_UI_CLICK] = self._to_int16(np.sin(2 * np.pi * 1000 * t) * e * .2)
        return s

    def _gen_digital(self):
        sr = self._sr
        s = {}
        t = np.linspace(0, .06, int(sr * .06), False)
        e = np.exp(-t * 50)
        s[SND_MOVE] = self._to_int16(np.sin(2 * np.pi * 1000 * t) * e * .4)
        t = np.linspace(0, .08, int(sr * .08), False)
        e = np.exp(-t * 35)
        s[SND_CAPTURE] = self._to_int16(np.sin(2 * np.pi * 600 * t) * e * .5)
        t1 = np.linspace(0, .04, int(sr * .04), False)
        g = np.zeros(int(sr * .02))
        t2 = np.linspace(0, .04, int(sr * .04), False)
        s[SND_CHECK] = self._to_int16(
            np.concatenate([
                np.sin(2 * np.pi * 1400 * t1) * np.exp(-t1 * 40) * .4,
                g,
                np.sin(2 * np.pi * 1400 * t2) * np.exp(-t2 * 40) * .4
            ]) * .5
        )
        t = np.linspace(0, .1, int(sr * .1), False)
        e = np.exp(-t * 25)
        s[SND_CASTLE] = self._to_int16(
            (np.sin(2 * np.pi * 800 * t) + np.sin(2 * np.pi * 1200 * t)) * e * .2
        )
        t = np.linspace(0, .5, int(sr * .5), False)
        e = np.exp(-t * 5)
        f = 1200 - 800 * t / .5
        s[SND_CHECKMATE] = self._to_int16(np.sin(2 * np.pi * f * t) * e * .4)
        t = np.linspace(0, .2, int(sr * .2), False)
        e = np.exp(-t * 12)
        s[SND_STALEMATE] = self._to_int16(np.sin(2 * np.pi * 500 * t) * e * .3)
        s[SND_DRAW] = s[SND_STALEMATE]
        t = np.linspace(0, .15, int(sr * .15), False)
        e = np.exp(-t * 15)
        s[SND_GAME_START] = self._to_int16(
            (np.sin(2 * np.pi * 800 * t) * e * .3 +
             np.sin(2 * np.pi * 1200 * t) * e * .2) * .5
        )
        t = np.linspace(0, .02, int(sr * .02), False)
        e = np.exp(-t * 120)
        s[SND_UI_CLICK] = self._to_int16(np.sin(2 * np.pi * 1500 * t) * e * .2)
        return s

    def _gen_cinematic(self):
        sr = self._sr
        s = {}
        t = np.linspace(0, .15, int(sr * .15), False)
        e = np.exp(-t * 25)
        s[SND_MOVE] = self._to_int16(
            (np.sin(2 * np.pi * 150 * t) * e * .4 +
             np.random.randn(len(t)) * e * .15) * .6
        )
        t = np.linspace(0, .2, int(sr * .2), False)
        e = np.exp(-t * 18)
        s[SND_CAPTURE] = self._to_int16(
            (np.sin(2 * np.pi * 100 * t) * e * .5 +
             np.sin(2 * np.pi * 200 * t) * e * .3 +
             np.random.randn(len(t)) * e * .2) * .6
        )
        t = np.linspace(0, .25, int(sr * .25), False)
        e = np.exp(-t * 12)
        s[SND_CHECK] = self._to_int16(
            (np.sin(2 * np.pi * 880 * t) * e * .3 +
             np.sin(2 * np.pi * 1320 * t) * e * .2) * .5
        )
        t = np.linspace(0, .18, int(sr * .18), False)
        e = np.exp(-t * 20)
        s[SND_CASTLE] = self._to_int16(
            (np.sin(2 * np.pi * 180 * t) * e * .35 +
             np.random.randn(len(t)) * e * .15) * .55
        )
        t = np.linspace(0, 1., int(sr * 1.), False)
        e = np.exp(-t * 2.5)
        s[SND_CHECKMATE] = self._to_int16(
            (np.sin(2 * np.pi * 261 * t) * e * .15 +
             np.sin(2 * np.pi * 329 * t) * e * .15 +
             np.sin(2 * np.pi * 392 * t) * e * .15 +
             np.sin(2 * np.pi * 523 * t) * e * .1) * .6
        )
        t = np.linspace(0, .5, int(sr * .5), False)
        e = np.exp(-t * 5)
        s[SND_STALEMATE] = self._to_int16(np.sin(2 * np.pi * 330 * t) * e * .25)
        s[SND_DRAW] = s[SND_STALEMATE]
        t = np.linspace(0, .6, int(sr * .6), False)
        e = np.exp(-t * 3)
        s[SND_GAME_START] = self._to_int16(
            (np.sin(2 * np.pi * 220 * t) * e * .2 +
             np.sin(2 * np.pi * 440 * t) * e * .15) * .5
        )
        t = np.linspace(0, .04, int(sr * .04), False)
        e = np.exp(-t * 60)
        s[SND_UI_CLICK] = self._to_int16(np.sin(2 * np.pi * 600 * t) * e * .15)
        return s

    def _gen_retro(self):
        sr = self._sr
        s = {}
        t = np.linspace(0, .05, int(sr * .05), False)
        e = (t < .025).astype(float) * .8 + .2
        s[SND_MOVE] = self._to_int16(
            np.sign(np.sin(2 * np.pi * 800 * t)) * e * .3
        )
        t = np.linspace(0, .08, int(sr * .08), False)
        e = np.exp(-t * 40)
        s[SND_CAPTURE] = self._to_int16(
            np.sign(np.random.randn(len(t))) * e * .3
        )
        t = np.linspace(0, .1, int(sr * .1), False)
        e = np.exp(-t * 25)
        s[SND_CHECK] = self._to_int16(
            np.sign(np.sin(2 * np.pi * 1200 * t)) * e * .35
        )
        t = np.linspace(0, .07, int(sr * .07), False)
        e = np.exp(-t * 30)
        s[SND_CASTLE] = self._to_int16(
            np.sign(np.sin(2 * np.pi * 500 * t)) * e * .3
        )
        pts = []
        for f in [523, 659, 784, 1047]:
            t = np.linspace(0, .12, int(sr * .12), False)
            e = np.exp(-t * 12)
            pts.append(np.sign(np.sin(2 * np.pi * f * t)) * e * .25)
        s[SND_CHECKMATE] = self._to_int16(np.concatenate(pts) * .5)
        t = np.linspace(0, .15, int(sr * .15), False)
        e = np.exp(-t * 15)
        s[SND_STALEMATE] = self._to_int16(
            np.sign(np.sin(2 * np.pi * 350 * t)) * e * .25
        )
        s[SND_DRAW] = s[SND_STALEMATE]
        t = np.linspace(0, .2, int(sr * .2), False)
        e = np.exp(-t * 10)
        s[SND_GAME_START] = self._to_int16(
            np.sign(np.sin(2 * np.pi * 660 * t)) * e * .25
        )
        t = np.linspace(0, .02, int(sr * .02), False)
        s[SND_UI_CLICK] = self._to_int16(
            np.sign(np.sin(2 * np.pi * 2000 * t)) * .15
        )
        return s

    def _gen_ambient(self):
        sr = self._sr
        s = {}
        t = np.linspace(0, .3, int(sr * .3), False)
        e = np.exp(-t * 8)
        s[SND_MOVE] = self._to_int16(
            (np.sin(2 * np.pi * 440 * t) * e * .15 +
             np.sin(2 * np.pi * 442 * t) * e * .15) * .5
        )
        t = np.linspace(0, .4, int(sr * .4), False)
        e = np.exp(-t * 6)
        s[SND_CAPTURE] = self._to_int16(
            (np.sin(2 * np.pi * 330 * t) * e * .2 +
             np.sin(2 * np.pi * 332 * t) * e * .2) * .5
        )
        t = np.linspace(0, .35, int(sr * .35), False)
        e = np.exp(-t * 7)
        s[SND_CHECK] = self._to_int16(
            (np.sin(2 * np.pi * 660 * t) * e * .2 +
             np.sin(2 * np.pi * 662 * t) * e * .2) * .5
        )
        t = np.linspace(0, .35, int(sr * .35), False)
        e = np.exp(-t * 6)
        s[SND_CASTLE] = self._to_int16(
            (np.sin(2 * np.pi * 392 * t) * e * .18 +
             np.sin(2 * np.pi * 394 * t) * e * .18) * .5
        )
        t = np.linspace(0, 1.2, int(sr * 1.2), False)
        e = np.exp(-t * 1.8)
        s[SND_CHECKMATE] = self._to_int16(
            (np.sin(2 * np.pi * 261 * t) * e * .1 +
             np.sin(2 * np.pi * 261.5 * t) * e * .1 +
             np.sin(2 * np.pi * 329 * t) * e * .1 +
             np.sin(2 * np.pi * 329.5 * t) * e * .1 +
             np.sin(2 * np.pi * 392 * t) * e * .08) * .6
        )
        t = np.linspace(0, .6, int(sr * .6), False)
        e = np.exp(-t * 3)
        s[SND_STALEMATE] = self._to_int16(
            (np.sin(2 * np.pi * 350 * t) * e * .15 +
             np.sin(2 * np.pi * 352 * t) * e * .15) * .4
        )
        s[SND_DRAW] = s[SND_STALEMATE]
        t = np.linspace(0, .8, int(sr * .8), False)
        e = np.exp(-t * 2.5)
        s[SND_GAME_START] = self._to_int16(
            (np.sin(2 * np.pi * 440 * t) * e * .12 +
             np.sin(2 * np.pi * 442 * t) * e * .12 +
             np.sin(2 * np.pi * 550 * t) * e * .08) * .5
        )
        t = np.linspace(0, .05, int(sr * .05), False)
        e = np.exp(-t * 40)
        s[SND_UI_CLICK] = self._to_int16(np.sin(2 * np.pi * 700 * t) * e * .1)
        return s