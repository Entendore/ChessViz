"""Sound manager — generates and plays chess sound effects via QSoundEffect."""

import os, wave, struct, math, tempfile
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect
from constants import log


class SoundManager:
    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="chess_sfx_")
        self.sounds = {}
        self._gen_all(); self._load_all()

    @staticmethod
    def _wav(path, samples, sr=44100):
        with wave.open(path, 'w') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(b''.join(struct.pack('<h', max(-32768, min(32767, int(s)))) for s in samples))

    @staticmethod
    def _sin(f, d, v=.5, sr=44100): return [32767*v*math.sin(2*math.pi*f*i/sr) for i in range(int(sr*d))]

    @staticmethod
    def _env(s, a=.01, r=.02, sr=44100):
        o = list(s); ai=int(sr*a); ri=int(sr*r)
        for i in range(min(ai,len(o))): o[i]*=i/ai
        for i in range(min(ri,len(o))): o[-(i+1)]*=i/ri
        return o

    def _mix(self, *ls):
        m = max(len(l) for l in ls); o = [0.0]*m
        for l in ls:
            for i,v in enumerate(l): o[i]+=v
        return o

    def _gen_all(self):
        sr=44100; d=self.tmpdir
        self._wav(os.path.join(d,"move.wav"), self._env(self._sin(800,.06,.4),.005,.03))
        self._wav(os.path.join(d,"capture.wav"), self._env(self._mix(self._sin(300,.10,.5),self._sin(600,.08,.3)),.005,.04))
        self._wav(os.path.join(d,"check.wav"), self._env(self._mix(self._sin(1000,.12,.5),self._sin(1250,.10,.3)),.005,.04))
        self._wav(os.path.join(d,"checkmate.wav"), self._env(self._sin(800,.15,.5)+self._sin(600,.15,.5)+self._sin(400,.25,.5),.01,.08))
        n=int(sr*.15); sw=[32767*.4*math.sin(2*math.pi*(400+400*i/n)*i/sr) for i in range(n)]
        self._wav(os.path.join(d,"castle.wav"), self._env(sw,.005,.03))
        self._wav(os.path.join(d,"error.wav"), self._env(self._sin(200,.10,.4),.005,.03))
        n2=int(sr*.2); ri2=[32767*.4*math.sin(2*math.pi*(400+400*i/n2)*i/sr) for i in range(n2)]
        self._wav(os.path.join(d,"promote.wav"), self._env(ri2,.01,.05))
        gs=self._sin(523,.12,.4)+[0]*int(sr*.03)+self._sin(659,.18,.4)
        self._wav(os.path.join(d,"start.wav"), self._env(gs,.005,.04))

    def _load_all(self):
        for n in ("move","capture","check","checkmate","castle","error","promote","start"):
            e = QSoundEffect(); e.setSource(QUrl.fromLocalFile(os.path.join(self.tmpdir, f"{n}.wav")))
            e.setVolume(.7); self.sounds[n] = e

    def play(self, name):
        s = self.sounds.get(name)
        if s: s.stop(); s.play()