import os
import subprocess
import time
import logging
import chess

logger = logging.getLogger("PGN2MP4.Engine")

class _SyncUCI:
    def __init__(self, path):
        if not path or not os.path.isfile(path): raise FileNotFoundError(f"Stockfish not found: {path}")
        self.proc = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._cmd("uci"); self._read("uciok")

    def _cmd(self, t):
        try: self.proc.stdin.write(t + "\n"); self.proc.stdin.flush()
        except BrokenPipeError: pass

    def _read(self, tok, timeout=30):
        lines, deadline = [], time.time() + timeout
        while True:
            if time.time() > deadline: logger.warning("UCI read timeout waiting for '%s'", tok); break
            line = self.proc.stdout.readline()
            if not line: break
            line = line.strip(); lines.append(line)
            if tok in line: break
        return lines

    def analyse(self, fen, depth=18):
        board = chess.Board(fen)
        if not board.legal_moves: return None, 0
        self._cmd(f"position fen {fen}"); self._cmd(f"go depth {depth}")
        bm, sc, wt = None, 0, board.turn == chess.WHITE
        for line in self._read("bestmove"):
            if line.startswith("info") and " score " in line:
                parts = line.split()
                if "cp" in parts:
                    idx = parts.index("cp")
                    try: raw = int(parts[idx + 1]); sc = raw if wt else -raw
                    except (ValueError, IndexError): pass
                elif "mate" in parts:
                    idx = parts.index("mate")
                    try: mi = int(parts[idx + 1]); raw = 10000 if mi > 0 else -10000; sc = raw if wt else -raw
                    except (ValueError, IndexError): pass
            if line.startswith("bestmove"): parts = line.split(); bm = parts[1] if len(parts) >= 2 else None
        return bm, sc

    def close(self):
        try: self._cmd("quit"); self.proc.wait(timeout=5)
        except Exception:
            try: self.proc.kill()
            except Exception: pass