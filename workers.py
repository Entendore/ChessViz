"""Chess Video Maker Pro — Background Workers"""
import os
import sys
import time
import subprocess
import logging
import chess
from PySide6.QtCore import QThread, Signal
from ai_engines import MinimaxEngine, MCTSEngine, HeuristicEvaluator
from constants import HAS_CV2, find_stockfish

if HAS_CV2:
    import cv2
    import numpy as np

logger = logging.getLogger("ChessVideoMaker.Workers")


class _SyncUCI:
    """Synchronous UCI engine wrapper."""

    def __init__(self, path):
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"Stockfish not found: {path}")
        self.proc = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._cmd("uci")
        self._read("uciok")

    def _cmd(self, t):
        self.proc.stdin.write(t + "\n")
        self.proc.stdin.flush()

    def _read(self, tok):
        """Read lines until *tok* appears.
        Note: Runs inside a QThread, so blocking readline() is safe and
        doesn't freeze the UI. Avoids using `select` which breaks on Windows pipes."""
        lines = []
        while True:
            l = self.proc.stdout.readline()
            if not l:
                break
            l = l.strip()
            lines.append(l)
            if tok in l:
                break
        return lines

    def analyse(self, fen, depth=18):
        b = chess.Board(fen)
        if not b.legal_moves:
            return None, 0
        self._cmd(f"position fen {fen}")
        self._cmd(f"go depth {depth}")
        bm = None
        sc = 0
        wt = b.turn == chess.WHITE
        
        lines = self._read("bestmove")
        for l in lines:
            if l.startswith("info") and " score " in l:
                parts = l.split()
                if "cp" in parts:
                    i = parts.index("cp")
                    sc = int(parts[i + 1]) if wt else -int(parts[i + 1])
                elif "mate" in parts:
                    i = parts.index("mate")
                    mi = int(parts[i + 1])
                    sc = (10000 if mi > 0 else -10000) if wt else (-10000 if mi > 0 else 10000)
            if l.startswith("bestmove"):
                parts = l.split()
                bm = parts[1] if len(parts) >= 2 else None
        return bm, sc

    def close(self):
        try:
            self._cmd("quit")
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def _resolve_sf(p):
    return p.strip() if p and p.strip() else find_stockfish()


class AIWorker(QThread):
    eval_ready = Signal(dict)

    def __init__(self, et, fen, par):
        super().__init__()
        self.et = et
        self.fen = fen
        self.par = par

    def run(self):
        b = chess.Board(self.fen)
        try:
            if self.et == "Minimax (Alpha-Beta)":
                e = MinimaxEngine()
                d = self.par.get("depth", 3)
                bm, ev, n, pol = e.search(b, d)
                self.eval_ready.emit({
                    "eval": f"{ev / 100:+.2f}", "eval_cp": ev,
                    "nodes": n, "policy": pol,
                    "engine_type": self.et,
                    "best_move": bm.uci() if bm else None,
                })
            elif self.et == "MCTS (Monte Carlo)":
                e = MCTSEngine()
                i = self.par.get("iterations", 500)
                bm, ev, v, pol = e.search(b, i)
                self.eval_ready.emit({
                    "eval": f"Visits:{v}", "eval_cp": ev,
                    "nodes": v, "policy": pol,
                    "engine_type": self.et,
                    "best_move": bm.uci() if bm else None,
                })
            elif self.et == "Stockfish (UCI)":
                r = _resolve_sf(self.par.get("path", ""))
                if not r:
                    raise ValueError("Stockfish not found")
                u = _SyncUCI(r)
                try:
                    bu, sw = u.analyse(b.fen(), 20)
                    self.eval_ready.emit({
                        "eval": f"{sw / 100:+.2f}", "eval_cp": float(sw),
                        "nodes": 0,
                        "policy": {bu: 1.0} if bu else {},
                        "engine_type": self.et,
                        "best_move": bu,
                        "resolved_path": r,
                    })
                finally:
                    u.close()
        except Exception as e:
            self.eval_ready.emit({
                "eval": f"Err:{e}", "eval_cp": 0, "nodes": 0,
                "policy": {}, "engine_type": self.et,
                "best_move": None, "error": True,
            })


class BatchEvalWorker(QThread):
    move_evaluated = Signal(int, float, str)
    batch_finished = Signal()

    def __init__(self, ml, et, par):
        super().__init__()
        self.ml = ml
        self.et = et
        self.par = par
        self._c = False

    def cancel(self):
        self._c = True

    def run(self):
        if self.et == "Stockfish (UCI)":
            r = _resolve_sf(self.par.get("path", ""))
            if not r:
                self.batch_finished.emit()
                return
            u = _SyncUCI(r)
            try:
                for i, n in enumerate(self.ml):
                    if self._c:
                        break
                    _, sw = u.analyse(n.board().fen(), 18)
                    es = (f"M{int(abs(sw) - 10000)}" if abs(sw) > 9000
                          else f"{sw / 100:+.2f}")
                    self.move_evaluated.emit(i, float(sw), es)
            except Exception as e:
                logger.error("Batch eval error: %s", e)
            finally:
                u.close()
        else:
            ev = HeuristicEvaluator()
            for i, n in enumerate(self.ml):
                if self._c:
                    break
                s = ev.evaluate(n.board())
                es = (f"M{int(abs(s) - 10000)}" if abs(s) > 9000
                      else f"{s / 100:+.2f}")
                self.move_evaluated.emit(i, float(s), es)
                time.sleep(0.01)
        self.batch_finished.emit()


class ExportWorker(QThread):
    progress = Signal(int, str)
    export_finished = Signal(str)

    def __init__(self, fr, fps, out, w, h):
        super().__init__()
        self.fr = fr
        self.fps = fps
        self.out = out
        self.w = w
        self.h = h
        self._c = False

    def cancel(self):
        self._c = True

    def run(self):
        if not HAS_CV2:
            self.export_finished.emit("ERROR: opencv-python missing")
            return
        if not self.fr:
            self.export_finished.emit("ERROR: No frames")
            return

        cs = [("avc1", ".mp4"), ("X264", ".mp4")]
        if sys.platform != "win32":
            cs.append(("mp4v", ".mp4"))
        cs.append(("XVID", ".avi"))

        wr = None
        up = self.out
        uc = None
        for fc, ext in cs:
            if not up.lower().endswith(ext):
                up = os.path.splitext(up)[0] + ext
            wr = cv2.VideoWriter(up, cv2.VideoWriter_fourcc(*fc),
                                 self.fps, (self.w, self.h))
            if wr.isOpened():
                uc = fc
                break
            wr.release()
            wr = None

        if not wr:
            self.export_finished.emit("ERROR: Codec not found")
            return

        tot = len(self.fr)
        for i, f in enumerate(self.fr):
            if self._c:
                wr.release()
                if os.path.exists(up):
                    os.remove(up)
                self.export_finished.emit("Cancelled")
                return
            if f.shape[:2] != (self.h, self.w):
                f = cv2.resize(f, (self.w, self.h))
            if f.ndim == 3 and f.shape[2] == 4:
                bgr = f[:, :, :3]
                a = f[:, :, 3:]
                bg = np.full_like(bgr, 32)
                al = a.astype(np.float32) / 255.0
                f = (bgr.astype(np.float32) * al +
                     bg.astype(np.float32) * (1 - al)).astype(np.uint8)
            wr.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR))
            self.progress.emit(int((i + 1) / tot * 100),
                               f"Frame {i + 1}/{tot}")
        wr.release()
        self.export_finished.emit(
            f"Done!\nCodec:{uc}\nSaved:{up}\n"
            f"{self.w}x{self.h} @ {self.fps}fps\nFrames:{tot}"
        )