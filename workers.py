"""Chess Video Maker Pro — Background Workers (QThread subclasses)

YouTube-ready export: always targets H.264 (AVC) in MP4 container.
Stockfish communication: synchronous UCI protocol via subprocess
  (avoids python-chess asyncio ProactorEventLoop crash on Windows).
"""

import os
import sys
import time
import subprocess
import chess
import chess.engine

from PySide6.QtCore import QThread, Signal

from ai_engines import MinimaxEngine, MCTSEngine, HeuristicEvaluator
from constants import HAS_CV2

if HAS_CV2:
    import cv2
    import numpy as np


# ── Synchronous UCI Engine Client ───────────────────────────────────

class _SyncUCIEngine:
    """Synchronous UCI chess engine client using subprocess directly.

    Communicates with the engine via stdin/stdout using the UCI protocol.
    This avoids python-chess's asyncio event loop, which crashes on
    Windows with an access violation in ProactorEventLoop._poll when
    running multiple analyses in sequence inside a QThread.

    Usage:
        engine = _SyncUCIEngine("/path/to/stockfish")
        best_move, score_white_cp = engine.analyse(board.fen(), depth=18)
        engine.close()
    """

    def __init__(self, path):
        self.proc = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._cmd("uci")
        self._read_until("uciok")

    def _cmd(self, text):
        """Send a command to the engine."""
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def _read_until(self, token):
        """Read lines from engine until one contains token."""
        lines = []
        while True:
            line = self.proc.stdout.readline()
            if not line:
                break
            lines.append(line.strip())
            if token in line:
                break
        return lines

    def analyse(self, board_fen, depth=18):
        """Analyse a position. Returns (best_move_uci, score_white_cp).

        Args:
            board_fen: FEN string of the position to analyse.
            depth: Search depth.

        Returns:
            Tuple of (best_move_uci_string, score_in_centipawns_from_white_pov).
            score_white_cp is positive when White is better.
            If no legal moves, returns (None, 0).
        """
        board = chess.Board(board_fen)
        if not board.legal_moves:
            return None, 0

        self._cmd(f"position fen {board_fen}")
        self._cmd(f"go depth {depth}")

        best_move = None
        score_cp = 0
        white_to_move = board.turn == chess.WHITE

        while True:
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()

            # Parse score from info lines
            if line.startswith("info") and " score " in line:
                parts = line.split()
                if "cp" in parts:
                    idx = parts.index("cp")
                    cp = int(parts[idx + 1])
                    # UCI gives score from engine's (side-to-move) perspective
                    # Convert to White's perspective
                    score_cp = cp if white_to_move else -cp
                elif "mate" in parts:
                    idx = parts.index("mate")
                    mate_in = int(parts[idx + 1])
                    if white_to_move:
                        score_cp = 10000 if mate_in > 0 else -10000
                    else:
                        score_cp = -10000 if mate_in > 0 else 10000

            # Best move line signals end of search
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    best_move = parts[1]
                break

        return best_move, score_cp

    def close(self):
        """Shut down the engine process cleanly."""
        try:
            self._cmd("quit")
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
            self.proc.wait(timeout=5)


# ── Codec Selection ─────────────────────────────────────────────────

def _get_youtube_codecs():
    """Return ordered list of (fourcc_string, file_extension) for YouTube.

    YouTube recommends H.264 (AVC) in an MP4 container.  We try fourcc
    codes that produce H.264, falling back to MPEG-4 Part 2 only when
    H.264 is unavailable.

    The mp4v codec is NEVER used on Windows because cv2.VideoWriter
    with mp4v causes an access violation (segfault) — a known OpenCV
    bug on Windows.
    """
    # Primary: H.264 in MP4 — YouTube's preferred format
    h264_codecs = [
        ("avc1", ".mp4"),   # H.264 via OpenCV FFmpeg backend (most reliable)
        ("X264", ".mp4"),   # H.264 via x264 (some OpenCV builds)
    ]

    # Fallback: MPEG-4 Part 2 in MP4 — YouTube accepts this but H.264 is better
    # CRITICAL: mp4v crashes on Windows, so skip it there
    mpeg4_codecs = []
    if sys.platform != "win32":
        mpeg4_codecs.append(("mp4v", ".mp4"))

    # Last resort: XVID in AVI — YouTube can ingest AVI and re-encodes it
    emergency_codecs = [
        ("XVID", ".avi"),
    ]

    return h264_codecs + mpeg4_codecs + emergency_codecs


# ── Worker Classes ──────────────────────────────────────────────────

class AIWorker(QThread):
    """Background worker for single-position AI engine analysis."""

    eval_ready = Signal(dict)

    def __init__(self, engine_type, board_fen, params):
        super().__init__()
        self.engine_type = engine_type
        self.board_fen = board_fen
        self.params = params

    def run(self):
        board = chess.Board(self.board_fen)
        try:
            if self.engine_type == "Minimax (Alpha-Beta)":
                engine = MinimaxEngine()
                depth = self.params.get("depth", 3)
                best_move, eval_cp_white, nodes, policy = engine.search(board, depth)
                self.eval_ready.emit({
                    "eval": f"{eval_cp_white / 100.0:+.2f}",
                    "eval_cp": eval_cp_white,
                    "nodes": nodes,
                    "policy": policy,
                    "engine_type": self.engine_type,
                    "best_move": best_move.uci() if best_move else None,
                })
            elif self.engine_type == "MCTS (Monte Carlo)":
                engine = MCTSEngine()
                iters = self.params.get("iterations", 500)
                best_move, eval_cp_white, total_visits, policy = engine.search(board, iters)
                self.eval_ready.emit({
                    "eval": f"Visits: {total_visits}",
                    "eval_cp": eval_cp_white,
                    "nodes": total_visits,
                    "policy": policy,
                    "engine_type": self.engine_type,
                    "best_move": best_move.uci() if best_move else None,
                })
            elif self.engine_type == "Stockfish (UCI)":
                engine_path = self.params.get("path", "")
                # Use synchronous UCI client to avoid asyncio crash on Windows
                uci = _SyncUCIEngine(engine_path)
                try:
                    best_uci, score_white = uci.analyse(board.fen(), depth=20)
                    policy = {best_uci: 1.0} if best_uci else {}
                    self.eval_ready.emit({
                        "eval": f"{score_white / 100.0:+.2f}",
                        "eval_cp": float(score_white),
                        "nodes": 0,
                        "policy": policy,
                        "engine_type": self.engine_type,
                        "best_move": best_uci,
                    })
                finally:
                    uci.close()
        except Exception as e:
            self.eval_ready.emit({
                "eval": f"Error: {str(e)[:50]}",
                "eval_cp": 0.0,
                "nodes": 0,
                "policy": {},
                "engine_type": self.engine_type,
                "best_move": None,
            })


class BatchEvalWorker(QThread):
    """Background worker for batch evaluation of all moves in a game."""

    move_evaluated = Signal(int, float, str)
    finished = Signal()

    def __init__(self, move_list, engine_type, params):
        super().__init__()
        self.move_list = move_list
        self.engine_type = engine_type
        self.params = params
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        if self.engine_type == "Stockfish (UCI)":
            try:
                # Use synchronous UCI client to avoid asyncio crash on Windows
                uci = _SyncUCIEngine(self.params["path"])
                try:
                    for i, node in enumerate(self.move_list):
                        if self._cancel:
                            break
                        _, score_white = uci.analyse(node.board().fen(), depth=18)
                        eval_str = (
                            f"M{int(abs(score_white) - 10000)}"
                            if abs(score_white) > 9000
                            else f"{score_white / 100.0:+.2f}"
                        )
                        self.move_evaluated.emit(i, float(score_white), eval_str)
                finally:
                    uci.close()
            except Exception:
                pass
        else:
            evaluator = HeuristicEvaluator()
            for i, node in enumerate(self.move_list):
                if self._cancel:
                    break
                score = evaluator.evaluate(node.board())
                eval_str = (
                    f"M{int(abs(score) - 99999)}"
                    if abs(score) > 9000
                    else f"{score / 100.0:+.2f}"
                )
                self.move_evaluated.emit(i, float(score), eval_str)
                time.sleep(0.01)
        self.finished.emit()


class ExportWorker(QThread):
    """Background worker for rendering frames to a YouTube-ready MP4 video.

    Codec selection strategy (in order):
      1. avc1  → H.264 in MP4  (YouTube's preferred format, safe on Windows)
      2. X264  → H.264 in MP4  (alternative H.264 fourcc)
      3. mp4v  → MPEG-4 in MP4 (Linux/macOS only — crashes on Windows)
      4. XVID  → MPEG-4 in AVI (emergency fallback, YouTube re-encodes)

    The writer checks isOpened() after each codec attempt.  If no codec
    opens successfully, an error is reported instead of crashing.
    """

    progress = Signal(int, str)
    finished = Signal(str)

    def __init__(self, frames, fps, out_path, res_w, res_h):
        super().__init__()
        self.frames = frames
        self.fps = fps
        self.out_path = out_path
        self.res_w = res_w
        self.res_h = res_h
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        if not HAS_CV2:
            self.finished.emit("ERROR: opencv-python missing.")
            return

        if not self.frames:
            self.finished.emit("ERROR: No frames to export.")
            return

        writer = None
        try:
            codecs = _get_youtube_codecs()
            used_path = self.out_path
            used_codec = None

            for fourcc_str, ext in codecs:
                # Adjust file extension to match the container format
                if not used_path.lower().endswith(ext):
                    base = os.path.splitext(used_path)[0]
                    used_path = base + ext
                fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
                writer = cv2.VideoWriter(
                    used_path, fourcc, self.fps, (self.res_w, self.res_h)
                )
                if writer.isOpened():
                    used_codec = fourcc_str
                    break
                # Codec not available — release and try next
                writer.release()
                writer = None

            if writer is None or not writer.isOpened():
                self.finished.emit(
                    "ERROR: Could not open VideoWriter with any codec.\n"
                    "Install opencv-python with FFmpeg support for H.264 export."
                )
                return

            total = len(self.frames)
            for i, frame in enumerate(self.frames):
                if self._cancel:
                    writer.release()
                    if os.path.exists(used_path):
                        os.remove(used_path)
                    self.finished.emit("Cancelled.")
                    return

                # Resize if frame dimensions don't match target
                if frame.shape[:2] != (self.res_h, self.res_w):
                    frame = cv2.resize(frame, (self.res_w, self.res_h))

                # Handle RGBA frames — composite onto dark background
                if frame.shape[2] == 4:
                    bgr = frame[:, :, :3]
                    a = frame[:, :, 3:]
                    bg = np.full_like(bgr, 32)
                    alpha = a.astype(np.float32) / 255.0
                    frame = (
                        bgr.astype(np.float32) * alpha
                        + bg.astype(np.float32) * (1 - alpha)
                    ).astype(np.uint8)

                # OpenCV expects BGR, our frames are RGB
                writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

                pct = int((i + 1) / total * 100)
                self.progress.emit(pct, f"Frame {i + 1}/{total}")

            writer.release()
            writer = None
            self.finished.emit(
                f"Done!\n"
                f"Codec: {used_codec}\n"
                f"Saved to: {used_path}\n"
                f"Resolution: {self.res_w}x{self.res_h} @ {self.fps}fps\n"
                f"Frames: {total}"
            )
        except Exception as ex:
            if writer is not None:
                writer.release()
            self.finished.emit(f"Error: {ex}")