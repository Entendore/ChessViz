"""Chess Video Maker Pro — Background Workers

Includes:
- AIWorker: single position analysis
- BatchEvalWorker: full game evaluation
- AIBattleWorker: AI vs AI game (runs entirely in thread, persistent Stockfish)
- CaptureWorker: off-GUI-thread frame capture (PGN pipeline)
- StreamingExportWorker: render+export in one pass (constant memory)
- ExportWorker: frames → MP4/AVI
- BatchPGNExportWorker: batch render entire folders of PGN to MP4
"""
import os
import sys
import time
import subprocess
import logging
import tempfile
import shutil
import chess
import chess.pgn
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor, QImage

from ai_engines import MinimaxEngine, MCTSEngine, HeuristicEvaluator
from constants import (HAS_CV2, find_stockfish, MAX_FRAMES_IN_MEMORY,
                       RESOLUTION_SIZES,
                       GAME_NORMAL, GAME_CHECKMATE, GAME_STALEMATE,
                       GAME_DRAW, GAME_INSUFFICIENT)

if HAS_CV2:
    import cv2
    import numpy as np

from board_renderer import BoardRenderer
from widgets import VideoRenderer

logger = logging.getLogger("ChessVideoMaker.Workers")


# ── Synchronous UCI wrapper ────────────────────────────────────────
class _SyncUCI:
    def __init__(self, path):
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"Stockfish not found: {path}")
        self.proc = subprocess.Popen(
            [path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._cmd("uci"); self._read("uciok")

    def _cmd(self, t):
        self.proc.stdin.write(t + "\n"); self.proc.stdin.flush()

    def _read(self, tok):
        lines = []
        while True:
            l = self.proc.stdout.readline()
            if not l: break
            l = l.strip(); lines.append(l)
            if tok in l: break
        return lines

    def analyse(self, fen, depth=18):
        b = chess.Board(fen)
        if not b.legal_moves: return None, 0
        self._cmd(f"position fen {fen}"); self._cmd(f"go depth {depth}")
        bm = None; sc = 0; wt = b.turn == chess.WHITE
        for l in self._read("bestmove"):
            if l.startswith("info") and " score " in l:
                parts = l.split()
                if "cp" in parts:
                    i = parts.index("cp")
                    sc = int(parts[i+1]) if wt else -int(parts[i+1])
                elif "mate" in parts:
                    i = parts.index("mate"); mi = int(parts[i+1])
                    sc = (10000 if mi > 0 else -10000) if wt else (-10000 if mi > 0 else 10000)
            if l.startswith("bestmove"):
                parts = l.split(); bm = parts[1] if len(parts) >= 2 else None
        return bm, sc

    def close(self):
        try: self._cmd("quit"); self.proc.wait(timeout=5)
        except Exception:
            try: self.proc.kill()
            except Exception: pass


def _resolve_sf(p):
    return p.strip() if p and p.strip() else find_stockfish()


def _qimage_to_bgr_numpy(qimg):
    """Convert QImage to BGR numpy array for OpenCV."""
    if not HAS_CV2: return None
    img = qimg.convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    ptr = img.bits()
    ptr.setsize(h * w * 3)
    arr = np.array(ptr, dtype=np.uint8).reshape((h, w, 3))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _detect_game_state(board):
    """Return (state, result, detail) for a chess.Board."""
    if board.is_checkmate():
        result = "1-0" if board.turn == chess.BLACK else "0-1"
        return GAME_CHECKMATE, result, "Checkmate"
    if board.is_stalemate():
        return GAME_STALEMATE, "½-½", "Stalemate"
    if board.is_insufficient_material():
        return GAME_INSUFFICIENT, "½-½", "Insufficient Material"
    if board.is_game_over():
        return GAME_DRAW, "½-½", "Draw"
    return GAME_NORMAL, "", ""


# ════════════════════════════════════════════════════════════════════
#  AIWorker — single position analysis
# ════════════════════════════════════════════════════════════════════
class AIWorker(QThread):
    eval_ready = Signal(dict)

    def __init__(self, et, fen, par):
        super().__init__()
        self.et = et; self.fen = fen; self.par = par

    def run(self):
        b = chess.Board(self.fen)
        try:
            if self.et == "Minimax (Alpha-Beta)":
                e = MinimaxEngine(); d = self.par.get("depth", 3)
                bm, ev, n, pol = e.search(b, d)
                self.eval_ready.emit({"eval":f"{ev/100:+.2f}","eval_cp":ev,
                    "nodes":n,"policy":pol,"engine_type":self.et,
                    "best_move":bm.uci() if bm else None})
            elif self.et == "MCTS (Monte Carlo)":
                e = MCTSEngine(); i = self.par.get("iterations", 500)
                bm, ev, v, pol = e.search(b, i)
                self.eval_ready.emit({"eval":f"Visits:{v}","eval_cp":ev,
                    "nodes":v,"policy":pol,"engine_type":self.et,
                    "best_move":bm.uci() if bm else None})
            elif self.et == "Stockfish (UCI)":
                r = _resolve_sf(self.par.get("path", ""))
                if not r: raise ValueError("Stockfish not found")
                u = _SyncUCI(r)
                try:
                    bu, sw = u.analyse(b.fen(), 20)
                    self.eval_ready.emit({"eval":f"{sw/100:+.2f}","eval_cp":float(sw),
                        "nodes":0,"policy":{bu:1.0} if bu else {},
                        "engine_type":self.et,"best_move":bu,"resolved_path":r})
                finally: u.close()
        except Exception as e:
            self.eval_ready.emit({"eval":f"Err:{e}","eval_cp":0,"nodes":0,
                "policy":{},"engine_type":self.et,"best_move":None,"error":True})


# ════════════════════════════════════════════════════════════════════
#  BatchEvalWorker — full game evaluation
# ════════════════════════════════════════════════════════════════════
class BatchEvalWorker(QThread):
    move_evaluated = Signal(int, float, str)
    batch_finished = Signal()

    def __init__(self, ml, et, par):
        super().__init__()
        self.ml = ml; self.et = et; self.par = par; self._c = False

    def cancel(self): self._c = True

    def run(self):
        if self.et == "Stockfish (UCI)":
            r = _resolve_sf(self.par.get("path", ""))
            if not r: self.batch_finished.emit(); return
            u = _SyncUCI(r)
            try:
                for i, n in enumerate(self.ml):
                    if self._c: break
                    _, sw = u.analyse(n.board().fen(), 18)
                    es = (f"M{int(abs(sw)-10000)}" if abs(sw) > 9000 else f"{sw/100:+.2f}")
                    self.move_evaluated.emit(i, float(sw), es)
            except Exception as e: logger.error("Batch eval error: %s", e)
            finally: u.close()
        else:
            ev = HeuristicEvaluator()
            for i, n in enumerate(self.ml):
                if self._c: break
                s = ev.evaluate(n.board())
                es = (f"M{int(abs(s)-10000)}" if abs(s) > 9000 else f"{s/100:+.2f}")
                self.move_evaluated.emit(i, float(s), es)
                time.sleep(0.01)
        self.batch_finished.emit()


# ════════════════════════════════════════════════════════════════════
#  AIBattleWorker — runs entire AI game in background thread
#  IMPROVED: Persistent Stockfish process, better progress, game-over evals
# ════════════════════════════════════════════════════════════════════
class AIBattleWorker(QThread):
    move_made = Signal(str, float)          # uci, eval_cp
    battle_progress = Signal(int, int, str) # move_num, max_moves, phase
    game_finished = Signal(str, str)        # pgn_text, result

    def __init__(self, w_engine_type, w_params, b_engine_type, b_params,
                 max_moves=80, delay_ms=10):
        super().__init__()
        self.w_et = w_engine_type; self.w_par = w_params
        self.b_et = b_engine_type; self.b_par = b_params
        self.max_moves = max_moves; self.delay_ms = delay_ms
        self._c = False
        self._w_sf = None; self._b_sf = None

    def cancel(self): self._c = True

    def _open_sf(self, par):
        r = _resolve_sf(par.get("path", ""))
        if not r: return None
        try: return _SyncUCI(r)
        except: return None

    def run(self):
        # Open persistent Stockfish instances if needed
        if self.w_et == "Stockfish (UCI)":
            self._w_sf = self._open_sf(self.w_par)
        if self.b_et == "Stockfish (UCI)":
            if self.b_et == self.w_et and self._w_sf:
                self._b_sf = self._w_sf  # Share instance for same engine
            else:
                self._b_sf = self._open_sf(self.b_par)

        try:
            self._run_battle()
        except Exception as e:
            logger.error("AIBattleWorker error: %s", e)
            result = "*"
            self.game_finished.emit("", result)
        finally:
            # Close Stockfish instances (only once if shared)
            closed = set()
            for sf in (self._w_sf, self._b_sf):
                if sf and id(sf) not in closed:
                    try: sf.close()
                    except: pass
                    closed.add(id(sf))
            self._w_sf = self._b_sf = None

    def _run_battle(self):
        game = chess.pgn.Game()
        # Set player names from engine types
        game.headers["White"] = self.w_et.split("(")[0].strip()
        game.headers["Black"] = self.b_et.split("(")[0].strip()
        node = game
        board = game.board()
        move_count = 0
        last_eval = 0.0

        self.battle_progress.emit(0, self.max_moves, "starting")

        while not self._c and move_count < self.max_moves:
            if board.is_game_over():
                break

            is_white = board.turn == chess.WHITE
            et = self.w_et if is_white else self.b_et
            par = self.w_par if is_white else self.b_par

            self.battle_progress.emit(
                move_count, self.max_moves,
                f"{'White' if is_white else 'Black'} thinking…")

            mv, ev = self._get_move(board, et, par)

            if mv is None:
                logger.warning("AI returned no move at ply %d", move_count)
                break

            if mv not in board.legal_moves:
                logger.warning("AI returned illegal move %s at ply %d", mv.uci(), move_count)
                break

            node = node.add_variation(mv)
            board.push(mv)
            move_count += 1
            last_eval = ev

            # Flip eval so positive = white advantage
            if not is_white:
                ev = -ev

            self.move_made.emit(mv.uci(), ev)
            self.battle_progress.emit(move_count, self.max_moves, f"Move {move_count}")

            if self.delay_ms > 0:
                time.sleep(self.delay_ms / 1000.0)

        # Detect final game state and set proper eval
        if board.is_checkmate():
            last_eval = 10000.0 if board.turn == chess.BLACK else -10000.0
        elif board.is_game_over():
            last_eval = 0.0

        exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
        pgn_text = game.accept(exporter)
        result = board.result() if board.is_game_over() else "*"
        self.game_finished.emit(pgn_text, result)

    def _get_move(self, board, et, par):
        if et == "Minimax (Alpha-Beta)":
            e = MinimaxEngine(); d = par.get("depth", 3)
            bm, ev, n, pol = e.search(board, d)
            return bm, ev
        elif et == "MCTS (Monte Carlo)":
            e = MCTSEngine(); iters = par.get("iterations", 500)
            bm, ev, v, pol = e.search(board, iters)
            return bm, ev
        elif et == "Stockfish (UCI)":
            sf = self._w_sf if board.turn == chess.WHITE else self._b_sf
            if not sf:
                # Fallback: open temporary instance
                sf = self._open_sf(par)
                if not sf: return None, 0.0
                try:
                    bu, sw = sf.analyse(board.fen(), 18)
                finally:
                    try: sf.close()
                    except: pass
            else:
                bu, sw = sf.analyse(board.fen(), 18)
            if bu:
                try:
                    mv = chess.Move.from_uci(bu)
                    return mv, float(sw)
                except ValueError:
                    return None, float(sw)
            return None, float(sw)
        return None, 0.0


# ════════════════════════════════════════════════════════════════════
#  CaptureWorker — captures frames off the GUI thread
# ════════════════════════════════════════════════════════════════════
class CaptureWorker(QThread):
    progress = Signal(int, str)
    frame_captured = Signal(int)
    capture_finished = Signal(bool)

    def __init__(self, game, move_list, eval_cache, board_renderer,
                 video_bg_color, white_name, black_name, overlays,
                 fps=30, hold=1.5, res_str="1920×1080",
                 use_disk_cache=False, disk_cache_dir=None,
                 eval_during_capture=False, stockfish_path=""):
        super().__init__()
        self.game = game
        self.move_list = move_list
        self.eval_cache = dict(eval_cache)
        self.board_renderer = board_renderer
        self.video_bg_color = video_bg_color
        self.white_name = white_name
        self.black_name = black_name
        self.overlays = overlays
        self.fps = fps
        self.hold = hold
        self.res_str = res_str
        self.use_disk_cache = use_disk_cache
        self.disk_cache_dir = disk_cache_dir
        self.eval_during_capture = eval_during_capture
        self.stockfish_path = stockfish_path
        self._c = False
        self.captured_images = []
        self.disk_frame_count = 0
        self._own_disk_dir = False

    def cancel(self): self._c = True

    def run(self):
        try:
            self._do_capture()
            self.capture_finished.emit(True)
        except Exception as e:
            logger.error("Capture error: %s", e)
            self.capture_finished.emit(False)

    def _do_capture(self):
        ml = self.move_list
        if not ml:
            return

        hf = max(1, int(self.hold * self.fps))
        total_estimated = hf * (len(ml) + 1)

        if self.use_disk_cache:
            if not self.disk_cache_dir:
                self.disk_cache_dir = tempfile.mkdtemp(prefix="chess_vm_frames_")
                self._own_disk_dir = True
        else:
            self.captured_images = []

        uci_engine = None
        if self.eval_during_capture and self.stockfish_path:
            try:
                uci_engine = _SyncUCI(self.stockfish_path)
            except Exception as e:
                logger.warning("Cannot open Stockfish for eval: %s", e)

        res = RESOLUTION_SIZES.get(self.res_str, (1920, 1080))
        vr = VideoRenderer(self.board_renderer, res[0], res[1], self.video_bg_color)
        vr.white_name = self.white_name
        vr.black_name = self.black_name
        vr.overlays = list(self.overlays)
        vr.move_list_text = [n.san() for n in ml]

        start_board = self.game.board()
        self.board_renderer.board = start_board
        self.board_renderer.last_move = None
        self.board_renderer.anim_move = None
        self.board_renderer.anim_rook_move = None
        self.board_renderer.anim_progress = 1.0

        vr.eval_cp = self.eval_cache.get(None, 0.0)
        vr.current_move_index = -1
        vr.game_state = GAME_NORMAL

        if uci_engine and not self.eval_cache.get(None):
            _, ev = uci_engine.analyse(start_board.fen(), 14)
            if start_board.turn == chess.BLACK: ev = -ev
            vr.eval_cp = float(ev)
        else:
            vr.eval_cp = self.eval_cache.get(None, 0.0)

        for _ in range(hf):
            if self._c: return
            self._save_frame(vr.render())

        for i, n in enumerate(ml):
            if self._c: return

            board = n.board()
            self.board_renderer.board = board
            self.board_renderer.last_move = n.move

            if uci_engine:
                _, ev = uci_engine.analyse(board.fen(), 14)
                if board.turn == chess.BLACK: ev = -ev
                vr.eval_cp = float(ev)
            else:
                vr.eval_cp = self.eval_cache.get(n, 0.0)

            state, result, detail = _detect_game_state(board)
            vr.game_state = state; vr.game_result = result; vr.game_detail = detail

            if n.parent:
                pb = n.parent.board()
                vr.move_text = (f"{pb.fullmove_number}. {n.san()}"
                                if pb.turn == chess.WHITE
                                else f"{pb.fullmove_number}... {n.san()}")
            vr.current_move_index = i

            extra = hf * 3 if state != GAME_NORMAL else 0
            total_hold = hf + extra
            for _ in range(total_hold):
                if self._c: return
                self._save_frame(vr.render())

            pct = int((i + 1) / len(ml) * 100)
            self.progress.emit(pct, f"Capturing move {i+1}/{len(ml)}")
            self.frame_captured.emit(self.disk_frame_count if self.use_disk_cache
                                     else len(self.captured_images))

        if uci_engine:
            try: uci_engine.close()
            except: pass

        total = self.disk_frame_count if self.use_disk_cache else len(self.captured_images)
        self.progress.emit(100, f"Done: {total} frames captured")

    def _save_frame(self, qimage):
        if self.use_disk_cache:
            fname = os.path.join(self.disk_cache_dir,
                                 f"frame_{self.disk_frame_count:05d}.jpg")
            qimage.save(fname, "JPEG", 95)
            self.disk_frame_count += 1
        else:
            self.captured_images.append(qimage)

    def cleanup_disk(self):
        if self._own_disk_dir and self.disk_cache_dir:
            try: shutil.rmtree(self.disk_cache_dir, ignore_errors=True)
            except: pass


# ════════════════════════════════════════════════════════════════════
#  StreamingExportWorker — render + export in one pass (constant memory)
# ════════════════════════════════════════════════════════════════════
class StreamingExportWorker(QThread):
    progress = Signal(int, str)
    export_finished = Signal(str)

    def __init__(self, game, move_list, eval_cache, board_renderer,
                 video_bg_color, white_name, black_name, overlays,
                 fps=30, hold=1.5, res_str="1920×1080",
                 output_path="chess_video.mp4",
                 stockfish_path="", eval_during_export=False):
        super().__init__()
        self.game = game
        self.move_list = move_list
        self.eval_cache = dict(eval_cache)
        self.board_renderer = board_renderer
        self.video_bg_color = video_bg_color
        self.white_name = white_name
        self.black_name = black_name
        self.overlays = overlays
        self.fps = fps
        self.hold = hold
        self.res_str = res_str
        self.output_path = output_path
        self.stockfish_path = stockfish_path
        self.eval_during_export = eval_during_export
        self._c = False

    def cancel(self): self._c = True

    def run(self):
        if not HAS_CV2:
            self.export_finished.emit("ERROR: opencv-python missing"); return
        if not self.move_list:
            self.export_finished.emit("ERROR: No moves to export"); return

        res = RESOLUTION_SIZES.get(self.res_str, (1920, 1080))
        w, h = res

        cs = [("avc1", ".mp4"), ("X264", ".mp4"), ("mp4v", ".mp4"), ("XVID", ".avi")]
        wr = None; up = self.output_path; uc = None
        for fc, ext in cs:
            if not up.lower().endswith(ext):
                up = os.path.splitext(up)[0] + ext
            wr = cv2.VideoWriter(up, cv2.VideoWriter_fourcc(*fc), self.fps, (w, h))
            if wr.isOpened(): uc = fc; break
            wr.release(); wr = None

        if not wr:
            self.export_finished.emit("ERROR: Codec not found"); return

        try:
            self._stream(wr, w, h, up, uc)
        except Exception as e:
            wr.release()
            if os.path.exists(up): os.remove(up)
            self.export_finished.emit(f"ERROR: {e}")

    def _stream(self, wr, w, h, up, uc):
        ml = self.move_list
        hf = max(1, int(self.hold * self.fps))

        uci_engine = None
        if self.eval_during_export and self.stockfish_path:
            try: uci_engine = _SyncUCI(self.stockfish_path)
            except: pass

        vr = VideoRenderer(self.board_renderer, w, h, self.video_bg_color)
        vr.white_name = self.white_name; vr.black_name = self.black_name
        vr.overlays = list(self.overlays)
        vr.move_list_text = [n.san() for n in ml]

        written = 0
        total_frames_est = hf * (len(ml) + 1)
        frames_done = 0

        start_board = self.game.board()
        self.board_renderer.board = start_board
        self.board_renderer.last_move = None
        self.board_renderer.anim_move = None
        self.board_renderer.anim_rook_move = None
        self.board_renderer.anim_progress = 1.0

        if uci_engine:
            _, ev = uci_engine.analyse(start_board.fen(), 14)
            if start_board.turn == chess.BLACK: ev = -ev
            vr.eval_cp = float(ev)
        else:
            vr.eval_cp = self.eval_cache.get(None, 0.0)
        vr.current_move_index = -1; vr.game_state = GAME_NORMAL

        for _ in range(hf):
            if self._c: wr.release(); os.remove(up); self.export_finished.emit("Cancelled"); return
            bgr = _qimage_to_bgr_numpy(vr.render())
            if bgr is not None:
                if bgr.shape[:2] != (h, w): bgr = cv2.resize(bgr, (w, h))
                wr.write(bgr); written += 1
            frames_done += 1

        for i, n in enumerate(ml):
            if self._c: wr.release(); os.remove(up); self.export_finished.emit("Cancelled"); return

            board = n.board()
            self.board_renderer.board = board
            self.board_renderer.last_move = n.move

            if uci_engine:
                _, ev = uci_engine.analyse(board.fen(), 14)
                if board.turn == chess.BLACK: ev = -ev
                vr.eval_cp = float(ev)
            else:
                vr.eval_cp = self.eval_cache.get(n, 0.0)

            state, result, detail = _detect_game_state(board)
            vr.game_state = state; vr.game_result = result; vr.game_detail = detail

            if n.parent:
                pb = n.parent.board()
                vr.move_text = (f"{pb.fullmove_number}. {n.san()}"
                                if pb.turn == chess.WHITE
                                else f"{pb.fullmove_number}... {n.san()}")
            vr.current_move_index = i

            extra = hf * 3 if state != GAME_NORMAL else 0
            total_hold = hf + extra
            for _ in range(total_hold):
                if self._c: wr.release(); os.remove(up); self.export_finished.emit("Cancelled"); return
                bgr = _qimage_to_bgr_numpy(vr.render())
                if bgr is not None:
                    if bgr.shape[:2] != (h, w): bgr = cv2.resize(bgr, (w, h))
                    wr.write(bgr); written += 1
                frames_done += 1

            pct = int((i + 1) / len(ml) * 100)
            self.progress.emit(pct, f"Rendering move {i+1}/{len(ml)} — {written} frames")

        if uci_engine:
            try: uci_engine.close()
            except: pass

        wr.release()
        self.export_finished.emit(
            f"Done!\nCodec:{uc}\nSaved:{up}\n{w}x{h} @ {self.fps}fps\nFrames:{written}")


# ════════════════════════════════════════════════════════════════════
#  ExportWorker — frames → video
# ════════════════════════════════════════════════════════════════════
class ExportWorker(QThread):
    progress = Signal(int, str)
    export_finished = Signal(str)

    def __init__(self, fr, fps, out, w, h, frame_dir=None, chunk_size=200):
        super().__init__()
        self.fr = fr; self.fps = fps; self.out = out
        self.w = w; self.h = h; self.frame_dir = frame_dir
        self.chunk_size = chunk_size; self._c = False

    def cancel(self): self._c = True

    def run(self):
        if not HAS_CV2:
            self.export_finished.emit("ERROR: opencv-python missing"); return
        if self.frame_dir and os.path.isdir(self.frame_dir):
            total = len([f for f in os.listdir(self.frame_dir)
                         if f.startswith("frame_") and f.endswith(".jpg")])
        elif self.fr:
            total = len(self.fr)
        else:
            self.export_finished.emit("ERROR: No frames"); return
        if total == 0:
            self.export_finished.emit("ERROR: No frames to export"); return

        cs = [("avc1", ".mp4"), ("X264", ".mp4"), ("mp4v", ".mp4"), ("XVID", ".avi")]
        wr = None; up = self.out; uc = None
        for fc, ext in cs:
            if not up.lower().endswith(ext): up = os.path.splitext(up)[0] + ext
            wr = cv2.VideoWriter(up, cv2.VideoWriter_fourcc(*fc), self.fps, (self.w, self.h))
            if wr.isOpened(): uc = fc; break
            wr.release(); wr = None
        if not wr:
            self.export_finished.emit("ERROR: Codec not found"); return

        if self.frame_dir and os.path.isdir(self.frame_dir):
            self._export_disk(wr, up, uc, total)
        else:
            self._export_memory(wr, up, uc, total)

    def _export_disk(self, wr, up, uc, total):
        chunk = self.chunk_size; written = 0
        for start in range(0, total, chunk):
            if self._c: wr.release(); os.remove(up); self.export_finished.emit("Cancelled"); return
            for i in range(start, min(start + chunk, total)):
                fname = os.path.join(self.frame_dir, f"frame_{i:05d}.jpg")
                if not os.path.isfile(fname): continue
                f = cv2.imread(fname, cv2.IMREAD_COLOR)
                if f is None: continue
                if f.shape[:2] != (self.h, self.w): f = cv2.resize(f, (self.w, self.h))
                wr.write(f); written += 1
            self.progress.emit(int(written/total*100), f"Frame {written}/{total} (disk)")
        wr.release()
        self.export_finished.emit(f"Done!\nCodec:{uc}\nSaved:{up}\n{self.w}x{self.h} @ {self.fps}fps\nFrames:{written}")

    def _export_memory(self, wr, up, uc, total):
        chunk = self.chunk_size; written = 0
        for start in range(0, total, chunk):
            if self._c: wr.release(); os.remove(up); self.export_finished.emit("Cancelled"); return
            for i in range(start, min(start + chunk, total)):
                f = self.fr[i]
                if f is None: continue
                if f.shape[:2] != (self.h, self.w): f = cv2.resize(f, (self.w, self.h))
                if f.ndim == 3 and f.shape[2] == 4:
                    bgr = f[:,:,:3]; a = f[:,:,3:]
                    bg = np.full_like(bgr, 32); al = a.astype(np.float32)/255.0
                    f = (bgr.astype(np.float32)*al + bg.astype(np.float32)*(1-al)).astype(np.uint8)
                wr.write(cv2.cvtColor(f, cv2.COLOR_RGB2BGR)); written += 1
            for i in range(start, min(start + chunk, total)):
                self.fr[i] = None
            self.progress.emit(int(written/total*100), f"Frame {written}/{total}")
        wr.release()
        self.export_finished.emit(f"Done!\nCodec:{uc}\nSaved:{up}\n{self.w}x{self.h} @ {self.fps}fps\nFrames:{written}")


# ════════════════════════════════════════════════════════════════════
#  BatchPGNExportWorker — batch render entire folders of PGN to MP4
# ════════════════════════════════════════════════════════════════════
class BatchPGNExportWorker(QThread):
    batch_progress = Signal(int, int, str)
    game_exported = Signal(str)
    batch_finished = Signal(int, int)

    def __init__(self, pgn_files, output_dir, settings):
        super().__init__()
        self.pgn_files = pgn_files
        self.output_dir = output_dir
        self.settings = settings
        self._c = False

    def cancel(self): self._c = True

    def run(self):
        if not HAS_CV2:
            self.batch_finished.emit(0, 0); return

        total_games = 0
        file_game_counts = []
        for pgn_file in self.pgn_files:
            count = 0
            try:
                with open(pgn_file, 'r', encoding='utf-8', errors='ignore') as f:
                    while chess.pgn.read_game(f) is not None:
                        count += 1
            except Exception: pass
            file_game_counts.append(count)
            total_games += count

        if total_games == 0:
            self.batch_finished.emit(0, 0); return

        success = 0; fail = 0; current_game = 0
        os.makedirs(self.output_dir, exist_ok=True)

        for file_idx, pgn_file in enumerate(self.pgn_files):
            if self._c: break
            basename = os.path.splitext(os.path.basename(pgn_file))[0]

            try:
                with open(pgn_file, 'r', encoding='utf-8', errors='ignore') as f:
                    game_idx = 0
                    while not self._c:
                        game = chess.pgn.read_game(f)
                        if game is None: break

                        game_idx += 1
                        current_game += 1
                        output_path = os.path.join(self.output_dir, f"{basename}_game_{game_idx}.mp4")

                        self.batch_progress.emit(current_game, total_games, os.path.basename(pgn_file))

                        if self._export_game(game, output_path):
                            success += 1
                            self.game_exported.emit(output_path)
                        else:
                            fail += 1
            except Exception as e:
                logger.error("Batch PGN error reading %s: %s", pgn_file, e)
                fail += file_game_counts[file_idx] - (current_game - sum(file_game_counts[:file_idx]))

        self.batch_finished.emit(success, fail)

    def _export_game(self, game, output_path):
        ml = list(game.mainline())
        if not ml: return False

        s = self.settings
        res = RESOLUTION_SIZES.get(s.get("res_str", "1920×1080"), (1920, 1080))
        w, h = res; fps = s.get("fps", 30); hold = s.get("hold", 1.5)
        hf = max(1, int(hold * fps))

        cs = [("avc1", ".mp4"), ("X264", ".mp4"), ("mp4v", ".mp4"), ("XVID", ".avi")]
        wr = None; uc = None
        for fc, ext in cs:
            out = output_path if output_path.lower().endswith(ext) else os.path.splitext(output_path)[0] + ext
            wr = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*fc), fps, (w, h))
            if wr.isOpened(): uc = fc; break
            wr.release(); wr = None

        if not wr: return False

        br = BoardRenderer(theme=s.get("theme"), flipped=s.get("flipped", False))
        vr = VideoRenderer(br, w, h, s.get("bg_color", QColor(30,30,32)))
        vr.white_name = s.get("white_name", "White")
        vr.black_name = s.get("black_name", "Black")
        vr.overlays = s.get("overlays", [])
        vr.move_list_text = [n.san() for n in ml]

        uci_engine = None
        if s.get("eval_during", False) and s.get("stockfish_path"):
            try: uci_engine = _SyncUCI(s["stockfish_path"])
            except: pass

        written = 0
        try:
            start_board = game.board()
            br.board = start_board; br.last_move = None
            br.anim_move = None; br.anim_rook_move = None; br.anim_progress = 1.0

            if uci_engine:
                _, ev = uci_engine.analyse(start_board.fen(), 14)
                if start_board.turn == chess.BLACK: ev = -ev
                vr.eval_cp = float(ev)
            else: vr.eval_cp = 0.0

            vr.current_move_index = -1; vr.game_state = GAME_NORMAL

            for _ in range(hf):
                if self._c: return False
                bgr = _qimage_to_bgr_numpy(vr.render())
                if bgr is not None:
                    if bgr.shape[:2] != (h, w): bgr = cv2.resize(bgr, (w, h))
                    wr.write(bgr); written += 1

            for i, n in enumerate(ml):
                if self._c: return False
                board = n.board()
                br.board = board; br.last_move = n.move

                if uci_engine:
                    _, ev = uci_engine.analyse(board.fen(), 14)
                    if board.turn == chess.BLACK: ev = -ev
                    vr.eval_cp = float(ev)
                else: vr.eval_cp = 0.0

                state, result, detail = _detect_game_state(board)
                vr.game_state = state; vr.game_result = result; vr.game_detail = detail

                if n.parent:
                    pb = n.parent.board()
                    vr.move_text = (f"{pb.fullmove_number}. {n.san()}" if pb.turn == chess.WHITE
                                    else f"{pb.fullmove_number}... {n.san()}")
                vr.current_move_index = i

                extra = hf * 3 if state != GAME_NORMAL else 0
                for _ in range(hf + extra):
                    if self._c: return False
                    bgr = _qimage_to_bgr_numpy(vr.render())
                    if bgr is not None:
                        if bgr.shape[:2] != (h, w): bgr = cv2.resize(bgr, (w, h))
                        wr.write(bgr); written += 1

            return written > 0
        except Exception as e:
            logger.error("Batch game export error: %s", e)
            return False
        finally:
            wr.release()
            if uci_engine:
                try: uci_engine.close()
                except: pass