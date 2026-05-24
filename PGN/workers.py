import os
import time
import math
import logging
import chess
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor
from constants import RESOLUTION_SIZES, DEFAULT_ANIM_DURATION, GAME_NORMAL, HAS_NUMBA
from board_renderer import BoardRenderer
from video_renderer import VideoRenderer
from engine import _SyncUCI
from helpers import _detect_game_state, _get_castling_rook_move, _create_video_writer

if HAS_NUMBA: from helpers import _ease_in_out_numba
logger = logging.getLogger("PGN2MP4.Workers")

class StreamingExportWorker(QThread):
    progress = Signal(int, str)
    export_finished = Signal(str)

    def __init__(self, game, move_list, eval_cache, board_renderer, video_bg_color, white_name, black_name, overlays, fps=30, hold=1.5, res_str="1920×1080", output_path="chess_video.mp4", stockfish_path="", eval_during_export=False, anim_duration=DEFAULT_ANIM_DURATION):
        super().__init__()
        self.game, self.move_list, self.eval_cache = game, move_list, dict(eval_cache)
        self.board_renderer, self.video_bg_color = board_renderer, video_bg_color
        self.white_name, self.black_name, self.overlays = white_name, black_name, overlays
        self.fps, self.hold, self.res_str, self.output_path = fps, hold, res_str, output_path
        self.stockfish_path, self.eval_during_export, self.anim_duration = stockfish_path, eval_during_export, anim_duration
        self._c = False

    def cancel(self): self._c = True

    def run(self):
        if not self.move_list: self.export_finished.emit("ERROR: No moves to export"); return
        res = RESOLUTION_SIZES.get(self.res_str, (1920, 1080)); w, h = res
        writer, used_path, used_codec = _create_video_writer(self.output_path, self.fps, w, h)
        if not writer: self.export_finished.emit("ERROR: No video codec found (Install FFmpeg for H.264)"); return
        try: self._stream(writer, w, h, used_path, used_codec)
        except Exception as e:
            logger.exception("Export failed"); writer.release()
            if os.path.exists(used_path):
                try: os.remove(used_path)
                except OSError: pass
            self.export_finished.emit(f"ERROR: {e}")

    def _stream(self, writer, w, h, used_path, used_codec):
        ml, hf = self.move_list, max(1, int(self.hold * self.fps))
        anim_frames = max(1, int(self.anim_duration * self.fps))
        uci_engine = None
        if self.eval_during_export and self.stockfish_path:
            try: uci_engine = _SyncUCI(self.stockfish_path)
            except Exception as e: logger.warning("Cannot open Stockfish for eval: %s", e)
        vr = VideoRenderer(self.board_renderer, w, h, self.video_bg_color)
        vr.white_name, vr.black_name, vr.overlays = self.white_name, self.black_name, list(self.overlays)
        vr.move_list_text = [n.san() for n in ml]; vr.opening_name = self.game.headers.get("Opening", "")
        written, start_time = 0, time.time()
        start_board = self.game.board(); self.board_renderer.board, self.board_renderer.last_move = start_board, None
        self.board_renderer.anim_move, self.board_renderer.anim_rook_move, self.board_renderer.anim_progress = None, None, 1.0
        if uci_engine: _, ev = uci_engine.analyse(start_board.fen(), 14); vr.eval_cp = float(ev)
        else: vr.eval_cp = self.eval_cache.get(None, 0.0)
        vr.current_move_index = -1; vr.game_state = GAME_NORMAL; vr.captured_by_white, vr.captured_by_black = VideoRenderer.compute_captures(start_board)
        for _ in range(hf):
            if self._c: writer.release(); self._cleanup(used_path, "Cancelled"); return
            writer.write(vr.render()); written += 1
        for i, node in enumerate(ml):
            if self._c: writer.release(); self._cleanup(used_path, "Cancelled"); return
            move, board = node.move, node.board(); self.board_renderer.board, self.board_renderer.last_move = board, None
            self.board_renderer.anim_move, self.board_renderer.anim_rook_move = move, _get_castling_rook_move(move)
            if uci_engine: _, ev = uci_engine.analyse(board.fen(), 14); vr.eval_cp = float(ev)
            else: vr.eval_cp = self.eval_cache.get(node, 0.0)
            vr.current_move_index = i; vr.captured_by_white, vr.captured_by_black = VideoRenderer.compute_captures(board)
            for f_idx in range(anim_frames):
                if self._c: writer.release(); self._cleanup(used_path, "Cancelled"); return
                progress = _ease_in_out_numba((f_idx + 1) / anim_frames) if HAS_NUMBA else 0.5 - 0.5 * math.cos(math.pi * (f_idx + 1) / anim_frames)
                self.board_renderer.anim_progress = progress; writer.write(vr.render()); written += 1
            self.board_renderer.anim_move, self.board_renderer.anim_rook_move, self.board_renderer.anim_progress = None, None, 1.0; self.board_renderer.last_move = move
            state, result, detail = _detect_game_state(board); vr.game_state, vr.game_result, vr.game_detail = state, result, detail
            if node.parent: pb = node.parent.board(); vr.move_text = f"{pb.fullmove_number}. {node.san()}" if pb.turn == chess.WHITE else f"{pb.fullmove_number}... {node.san()}"
            extra = hf * 3 if state != GAME_NORMAL else 0
            for _ in range(hf + extra):
                if self._c: writer.release(); self._cleanup(used_path, "Cancelled"); return
                writer.write(vr.render()); written += 1
            elapsed = time.time() - start_time; pct = int((i + 1) / len(ml) * 100)
            eta_str = f"ETA: {int(elapsed / (i + 1) * (len(ml) - i - 1))}s" if i > 0 else ""
            self.progress.emit(pct, f"Move {i + 1}/{len(ml)} — {written} frames — {eta_str}")
        if uci_engine:
            try: uci_engine.close()
            except Exception: pass
        writer.release(); elapsed = time.time() - start_time
        self.export_finished.emit(f"Done!\nCodec: {used_codec}\nSaved: {used_path}\n{w}x{h} @ {self.fps}fps\nFrames: {written}\nDuration: {elapsed:.1f}s")

    def _cleanup(self, path, msg):
        try: os.remove(path)
        except OSError: pass
        self.export_finished.emit(msg)


class BatchPGNExportWorker(QThread):
    batch_progress = Signal(int, int, str)
    game_exported = Signal(str)
    batch_finished = Signal(int, int)

    def __init__(self, pgn_files, output_dir, settings):
        super().__init__()
        self.pgn_files, self.output_dir, self.settings = pgn_files, output_dir, settings
        self._c = False

    def cancel(self): self._c = True

    def run(self):
        total_games = 0
        for pgn_file in self.pgn_files:
            try:
                with open(pgn_file, "r", encoding="utf-8", errors="ignore") as f:
                    while chess.pgn.read_game(f) is not None: total_games += 1
            except Exception: pass
        if total_games == 0: self.batch_finished.emit(0, 0); return
        success, fail, current_game = 0, 0, 0; os.makedirs(self.output_dir, exist_ok=True)
        for pgn_file in self.pgn_files:
            if self._c: break
            basename = os.path.splitext(os.path.basename(pgn_file))[0]
            try:
                with open(pgn_file, "r", encoding="utf-8", errors="ignore") as f:
                    game_idx = 0
                    while not self._c:
                        game = chess.pgn.read_game(f)
                        if game is None: break
                        game_idx += 1; current_game += 1; output_path = os.path.join(self.output_dir, f"{basename}_game_{game_idx}.mp4")
                        self.batch_progress.emit(current_game, total_games, os.path.basename(pgn_file))
                        if self._export_game(game, output_path): success += 1; self.game_exported.emit(output_path)
                        else: fail += 1
            except Exception as e: logger.error("Batch PGN error reading %s: %s", pgn_file, e)
        self.batch_finished.emit(success, fail)

    def _export_game(self, game, output_path):
        ml = list(game.mainline())
        if not ml: return False
        s = self.settings; res = RESOLUTION_SIZES.get(s.get("res_str", "1920×1080"), (1920, 1080)); w, h = res
        fps, hold = s.get("fps", 30), s.get("hold", 1.5); hf = max(1, int(hold * fps))
        anim_frames = max(1, int(s.get("anim_duration", DEFAULT_ANIM_DURATION) * fps))
        writer, used_path, _ = _create_video_writer(output_path, fps, w, h)
        if not writer: return False
        br = BoardRenderer(theme=s.get("theme"), flipped=s.get("flipped", False))
        vr = VideoRenderer(br, w, h, s.get("bg_color", QColor(30, 30, 32)))
        vr.white_name, vr.black_name, vr.overlays = s.get("white_name", "White"), s.get("black_name", "Black"), s.get("overlays", [])
        vr.move_list_text = [n.san() for n in ml]; vr.opening_name = game.headers.get("Opening", "")
        uci_engine = None
        if s.get("eval_during", False) and s.get("stockfish_path"):
            try: uci_engine = _SyncUCI(s["stockfish_path"])
            except Exception: pass
        written = 0
        try:
            start_board = game.board(); br.board = start_board; br.last_move = None; br.anim_move = None; br.anim_rook_move = None; br.anim_progress = 1.0
            if uci_engine: _, ev = uci_engine.analyse(start_board.fen(), 14); vr.eval_cp = float(ev)
            else: vr.eval_cp = 0.0
            vr.current_move_index = -1; vr.game_state = GAME_NORMAL; vr.captured_by_white, vr.captured_by_black = VideoRenderer.compute_captures(start_board)
            for _ in range(hf):
                if self._c: return False
                writer.write(vr.render()); written += 1
            for i, node in enumerate(ml):
                if self._c: return False
                move, board = node.move, node.board(); br.board = board; br.last_move = None; br.anim_move, br.anim_rook_move = move, _get_castling_rook_move(move)
                for f_idx in range(anim_frames):
                    if self._c: return False
                    progress = _ease_in_out_numba((f_idx + 1) / anim_frames) if HAS_NUMBA else 0.5 - 0.5 * math.cos(math.pi * (f_idx + 1) / anim_frames)
                    br.anim_progress = progress; writer.write(vr.render()); written += 1
                br.anim_move, br.anim_rook_move, br.anim_progress = None, None, 1.0; br.last_move = move
                if uci_engine: _, ev = uci_engine.analyse(board.fen(), 14); vr.eval_cp = float(ev)
                else: vr.eval_cp = 0.0
                state, result, detail = _detect_game_state(board); vr.game_state, vr.game_result, vr.game_detail, vr.current_move_index = state, result, detail, i
                vr.captured_by_white, vr.captured_by_black = VideoRenderer.compute_captures(board)
                if node.parent: pb = node.parent.board(); vr.move_text = f"{pb.fullmove_number}. {node.san()}" if pb.turn == chess.WHITE else f"{pb.fullmove_number}... {node.san()}"
                extra = hf * 3 if state != GAME_NORMAL else 0
                for _ in range(hf + extra):
                    if self._c: return False
                    writer.write(vr.render()); written += 1
            return written > 0
        except Exception as e: logger.error("Batch game export error: %s", e); return False
        finally:
            writer.release()
            if uci_engine:
                try: uci_engine.close()
                except Exception: pass