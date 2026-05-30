#!/usr/bin/env python3
"""FFmpeg-based video export — YouTube-optimized, no background audio, batch support."""

import os
import shutil
import subprocess
import wave

import chess
import numpy as np

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage, QPainter, QColor

from config import (ExportConfig, THEMES, SQ_SIZE, LayoutMode, MOVE_LIST_COLORS,
                    YOUTUBE_FFMPEG_PRESET, YOUTUBE_AUDIO_BITRATE)
from utils import log, ease_out_cubic, sanitize_filename
from board_widget import ChessBoardWidget, _sq_to_rc
from chess_engine import ChessEngine

# ── Local Dependency Check ──────────────────────────────────────────────────

HAS_FFMPEG = shutil.which('ffmpeg') is not None
HAS_CUPY = False
try:
    import cupy as cp
    HAS_CUPY = True
except Exception:
    pass


# ── Post-processing helpers ─────────────────────────────────────────────────

def _apply_vignette(frame, strength=0.25):
    h, w = frame.shape[:2]
    Y, X = np.ogrid[:h, :w]
    cy, cx = h / 2.0, w / 2.0
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    max_dist = np.sqrt(cy ** 2 + cx ** 2)
    factor = 1.0 - strength * (dist / max_dist) ** 2
    result = frame.astype(np.float32)
    for c in range(3): result[:, :, c] *= factor
    return np.clip(result, 0, 255).astype(np.uint8)

def _apply_contrast(frame, contrast=1.02):
    mid = 128.0
    result = mid + contrast * (frame.astype(np.float32) - mid)
    return np.clip(result, 0, 255).astype(np.uint8)

def _apply_saturation(frame, saturation=1.05):
    gray = np.dot(frame.astype(np.float32), [0.114, 0.587, 0.299])
    gray = gray[:, :, np.newaxis]
    result = gray + saturation * (frame.astype(np.float32) - gray)
    return np.clip(result, 0, 255).astype(np.uint8)

def _apply_post_process(frame, config):
    if config.gpu_post_process:
        if config.gpu_contrast != 1.0: frame = _apply_contrast(frame, config.gpu_contrast)
        if config.gpu_saturation != 1.0: frame = _apply_saturation(frame, config.gpu_saturation)
        if config.gpu_vignette > 0: frame = _apply_vignette(frame, config.gpu_vignette)
    return frame


# ── Silent Audio Generator (for YouTube compatibility) ───────────────────────

def _generate_silent_wav(path, duration_s, sr=44100):
    n_samples = max(1, int(sr * duration_s))
    with wave.open(path, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        chunk = b'\x00\x00' * min(n_samples, 44100)
        written = 0
        while written < n_samples:
            frames_to_write = min(len(chunk) // 2, n_samples - written)
            w.writeframes(chunk[:frames_to_write * 2])
            written += frames_to_write


# ── FFmpeg Video Exporter ───────────────────────────────────────────────────

class FFmpegVideoExporter(QObject):
    progress = Signal(int, int)          # (frame_idx, total_frames)
    finished = Signal(str)               # output_path
    error = Signal(str)                  # error_message
    log_msg = Signal(str)
    batch_puzzle_done = Signal(int, int, str)  # (completed, total, puzzle_name)

    def __init__(self, config: ExportConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._cancel = False

    def cancel(self):
        self._cancel = True

    # ── Public API ──────────────────────────────────────────────────────

    def export_puzzle(self, puzzle, output_path):
        if not HAS_FFMPEG:
            self.error.emit("ffmpeg not found. Install ffmpeg and add to PATH.")
            return
        self._cancel = False
        try:
            actual_frames = self._export_streaming(puzzle, output_path)
            if self._cancel:
                self.error.emit("Export cancelled."); return
            self._add_silent_audio(output_path, actual_frames)
            if not self._cancel: self.finished.emit(output_path)
        except Exception as e:
            self.error.emit(str(e))

    def export_puzzle_threaded(self, puzzle, output_path):
        import threading
        t = threading.Thread(target=self.export_puzzle, args=(puzzle, output_path), daemon=True)
        t.start(); return t

    def export_batch(self, puzzles, output_dir):
        """Export a list of puzzles sequentially, emitting batch_puzzle_done per puzzle."""
        import threading
        if not HAS_FFMPEG:
            self.error.emit("ffmpeg not found."); return
        os.makedirs(output_dir, exist_ok=True)
        total = len(puzzles)

        def _run():
            self._cancel = False
            for i, puzzle in enumerate(puzzles):
                if self._cancel: break
                name = sanitize_filename(puzzle.get('name', f'puzzle_{i+1}'))
                ext = '.gif' if self.config.export_gif else '.mp4'
                path = os.path.join(output_dir, f"{name}{ext}")
                try:
                    actual_frames = self._export_streaming(puzzle, path)
                    if self._cancel: break
                    self._add_silent_audio(path, actual_frames)
                    self.batch_puzzle_done.emit(i + 1, total, name)
                    self.log_msg.emit(f"Batch: exported {i+1}/{total}: {name}")
                except Exception as e:
                    self.log_msg.emit(f"Batch error on {name}: {e}")
                    self.batch_puzzle_done.emit(i + 1, total, f"{name} (error)")
            if not self._cancel:
                self.finished.emit(output_dir)
            else:
                self.error.emit("Batch export cancelled.")

        threading.Thread(target=_run, daemon=True).start()

    # ── Audio: silent track for YouTube compatibility ───────────────────

    def _add_silent_audio(self, video_path, actual_frames):
        """Add a silent audio track so YouTube doesn't complain."""
        duration = actual_frames / self.config.fps if self.config.fps > 0 else 1.0
        silent_path = video_path + ".silent.wav"
        try:
            _generate_silent_wav(silent_path, duration)
            self._merge_audio(video_path, silent_path)
        except Exception as e:
            log(f"Silent audio generation failed: {e}", "EXPORT")
        finally:
            try: os.remove(silent_path)
            except OSError: pass

    # ── Streaming Core Logic ────────────────────────────────────────────

    def _export_streaming(self, puzzle, output_path):
        cfg = self.config
        w, h = cfg.target_width, cfg.target_height

        cmd = self._build_ffmpeg_cmd(output_path, w, h)
        log(f"FFmpeg command: {' '.join(cmd)}", "EXPORT")
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        engine = ChessEngine()
        fen = puzzle.get('fen', '')
        if fen: engine.load_fen(fen)
        else: engine.reset()

        sq_size = cfg.effective_sq_size
        theme = THEMES.get(cfg.theme_name, THEMES["Midnight"])
        uci_moves = puzzle.get('moves', [])
        setup_count = puzzle.get('setup_count', 0)
        san_moves = self._precalc_san_moves(fen, uci_moves)

        frame_idx = 0
        total_est = self._estimate_frame_count(len(uci_moves))

        try:
            # 1. Title Screen Phase
            if cfg.title_enabled and cfg.title_text:
                title_img = ChessBoardWidget.render_card(
                    cfg.title_text, cfg.title_bg, cfg.title_fg, width=w, height=h,
                    font_size=cfg.title_font_size, sub_text=puzzle.get('name', ''))
                n_title = int(cfg.fps * cfg.title_duration)
                for _ in range(n_title):
                    if self._cancel: raise InterruptedError("Cancelled")
                    self._write_qimage_to_pipe(process, title_img, w, h)
                    frame_idx += 1; self.progress.emit(frame_idx, total_est)

            # 2. Setup Moves
            for i in range(setup_count):
                if i >= len(uci_moves): break
                frame_idx = self._execute_move_streaming(
                    process, engine, uci_moves[i], san_moves, i, frame_idx, total_est,
                    sq_size, w, h, cfg, theme, puzzle, "Setting up...", is_setup=True)

            # 3. Starting Position Hold Phase
            if cfg.position_hold_enabled:
                n_hold = max(1, int(cfg.fps * cfg.position_hold_duration))
                hold_img = self._render_composited_frame(
                    engine.board, theme, sq_size, w, h, cfg, san_moves,
                    setup_count - 1, puzzle, "Find the best move",
                    text_overlay=cfg.position_overlay_text)
                for _ in range(n_hold):
                    if self._cancel: raise InterruptedError("Cancelled")
                    self._write_qimage_to_pipe(process, hold_img, w, h)
                    frame_idx += 1; self.progress.emit(frame_idx, total_est)

            # 4. Puzzle Animation Phase (Supports Loops)
            loops = max(1, cfg.loop_count)
            for loop_idx in range(loops):
                if loop_idx > 0:
                    engine.load_fen(fen) if fen else engine.reset()
                    for i in range(setup_count):
                        if i < len(uci_moves): engine.make_move_uci(uci_moves[i])

                status = f"Playing... (Loop {loop_idx+1})" if loops > 1 else "▶ Playing..."
                for move_i in range(setup_count, len(uci_moves)):
                    if self._cancel: raise InterruptedError("Cancelled")
                    is_key_move = self._is_key_move(engine, uci_moves[move_i])
                    frame_idx = self._execute_move_streaming(
                        process, engine, uci_moves[move_i], san_moves, move_i,
                        frame_idx, total_est, sq_size, w, h, cfg, theme, puzzle,
                        status, is_key_move=is_key_move)

            # 5. End Card Phase
            if cfg.end_enabled and cfg.end_text:
                end_img = ChessBoardWidget.render_card(
                    cfg.end_text, cfg.end_bg, cfg.end_fg, width=w, height=h,
                    font_size=cfg.end_font_size, sub_text=puzzle.get('name', ''))
                n_end = int(cfg.fps * cfg.end_duration)
                for _ in range(n_end):
                    if self._cancel: raise InterruptedError("Cancelled")
                    self._write_qimage_to_pipe(process, end_img, w, h)
                    frame_idx += 1; self.progress.emit(frame_idx, total_est)

        except InterruptedError:
            process.kill(); return frame_idx
        except Exception as e:
            process.kill(); raise e

        process.stdin.close()
        _, stderr = process.communicate()
        if process.returncode != 0:
            err_msg = stderr.decode('utf-8', errors='replace')[-500:]
            raise RuntimeError(f"FFmpeg error (code {process.returncode}): {err_msg}")
        log(f"FFmpeg wrote video successfully", "EXPORT")
        return frame_idx

    def _execute_move_streaming(self, process, engine, move_uci, san_moves, move_idx,
                                frame_idx, total_est, sq_size, w, h, cfg, theme,
                                puzzle_info, status_text, is_setup=False, is_key_move=False):
        move = chess.Move.from_uci(move_uci)
        if move not in engine.board.legal_moves:
            if move.promotion is None:
                piece = engine.board.piece_at(move.from_square)
                if piece and piece.piece_type == chess.PAWN:
                    to_rank = chess.square_rank(move.to_square)
                    if (piece.color == chess.WHITE and to_rank == 7) or \
                       (piece.color == chess.BLACK and to_rank == 0):
                        move = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
            if move not in engine.board.legal_moves:
                self.log_msg.emit(f"Skipping illegal move: {move_uci}")
                return frame_idx

        fr, fc = ChessEngine.sq_to_rc(move.from_square)
        tr, tc = ChessEngine.sq_to_rc(move.to_square)
        promo = chess.piece_symbol(move.promotion) if move.promotion else None

        is_ep = engine.board.is_en_passant(move)
        if is_ep:
            ep_cap_sq = chess.square(chess.square_file(move.to_square),
                                     chess.square_rank(move.from_square))
            cap = engine.board.piece_at(ep_cap_sq)
        else:
            cap = engine.board.piece_at(move.to_square)
        captured = cap.symbol() if cap else '.'

        n_anim = max(1, int(cfg.fps * cfg.move_anim_duration))
        piece_obj = chess.Piece(engine.board.piece_at(move.from_square).piece_type, engine.board.turn)

        for fi in range(n_anim):
            if self._cancel: raise InterruptedError("Cancelled")
            t = fi / n_anim
            anim_state = {
                'from': (fr, fc), 'to': (tr, tc),
                'piece_obj': piece_obj, 'progress': ease_out_cubic(t),
                'captured': captured,
            }
            frame_img = self._render_composited_frame(
                engine.board, theme, sq_size, w, h, cfg, san_moves, move_idx,
                puzzle_info, status_text, anim_state=anim_state)
            self._write_qimage_to_pipe(process, frame_img, w, h)
            frame_idx += 1; self.progress.emit(frame_idx, total_est)

        info = engine.make_move(fr, fc, tr, tc, promo)

        pause_duration = cfg.pause_after_move
        if is_key_move and cfg.pause_on_key_moves:
            pause_duration *= cfg.key_move_pause_multiplier

        n_pause = max(1, int(cfg.fps * pause_duration))
        pause_img = self._render_composited_frame(
            engine.board, theme, sq_size, w, h, cfg, san_moves, move_idx,
            puzzle_info, status_text, last_move=((fr, fc), (tr, tc)))
        for _ in range(n_pause):
            if self._cancel: raise InterruptedError("Cancelled")
            self._write_qimage_to_pipe(process, pause_img, w, h)
            frame_idx += 1; self.progress.emit(frame_idx, total_est)

        return frame_idx

    def _is_key_move(self, engine, uci_str):
        try:
            move = chess.Move.from_uci(uci_str)
            if engine.board.is_capture(move): return True
            if engine.board.gives_check(move): return True
            if move.promotion is not None: return True
        except Exception:
            pass
        return False

    def _render_composited_frame(self, board, theme, sq_size, w, h, cfg,
                                  san_moves, current_move_idx, puzzle_info, status_text,
                                  anim_state=None, last_move=None, text_overlay=""):
        check_sqs = []
        if board.is_check():
            king_sq = board.king(board.turn)
            check_sqs = [ChessEngine.sq_to_rc(king_sq)]

        board_img = ChessBoardWidget.render_frame(
            board, last_move=last_move, check_squares=check_sqs,
            anim_state=anim_state, theme=theme, sq_size=sq_size,
            highlight_last_move=cfg.highlight_last_move,
            show_coords=cfg.coordinate_visible,
            show_arrow=cfg.show_arrow,
            text_overlay=text_overlay)

        final_img = ChessBoardWidget.render_layout(
            board_img, san_moves, current_move_idx,
            cfg.layout_mode, w, h, cfg.background_color, sq_size, puzzle_info,
            status_text, cfg.move_list_visible)
        return final_img

    def _write_qimage_to_pipe(self, process, qimg, w, h):
        np_frame = ChessBoardWidget.qimage_to_np(qimg)
        np_frame = _apply_post_process(np_frame, self.config)
        if np_frame.shape[0] != h or np_frame.shape[1] != w:
            qimg2 = QImage(np_frame.data, np_frame.shape[1], np_frame.shape[0],
                           np_frame.shape[1] * 3, QImage.Format_RGB888)
            qimg2 = qimg2.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            np_frame = ChessBoardWidget.qimage_to_np(qimg2)
        process.stdin.write(np_frame.tobytes())

    def _precalc_san_moves(self, fen, uci_moves):
        board = chess.Board(fen) if fen else chess.Board()
        sans = []
        for uci in uci_moves:
            try:
                move = chess.Move.from_uci(uci)
                if move in board.legal_moves:
                    sans.append(board.san(move))
                    board.push(move)
                else:
                    sans.append(uci)
            except Exception:
                sans.append(uci)
        return sans

    # ── YouTube-Optimized FFmpeg Command (hardcoded quality) ────────────

    def _build_ffmpeg_cmd(self, output_path, w, h):
        cfg = self.config
        fps = cfg.fps
        bitrate_k = cfg.effective_bitrate
        maxrate_k = int(bitrate_k * 1.5)
        bufsize_k = bitrate_k * 2

        if w >= 3840 or h >= 2160:
            level = '5.1'
        elif w >= 2560 or h >= 1440:
            level = '5.0'
        else:
            level = '4.2'

        gop = fps * 2

        if cfg.export_gif:
            gif_fps = cfg.gif_fps if cfg.gif_fps > 0 else 12
            filter_str = (
                f'fps={gif_fps},'
                f'split[s0][s1];'
                f'[s0]palettegen=max_colors=256:stats_mode=diff[p];'
                f'[s1][p]paletteuse=dither=bayer:bayer_scale=3'
            )
            return [
                'ffmpeg', '-y',
                '-f', 'rawvideo', '-vcodec', 'rawvideo',
                '-s', f'{w}x{h}', '-pix_fmt', 'rgb24',
                '-r', str(fps), '-i', '-',
                '-vf', filter_str,
                output_path,
            ]
        else:
            return [
                'ffmpeg', '-y',
                '-f', 'rawvideo', '-vcodec', 'rawvideo',
                '-s', f'{w}x{h}', '-pix_fmt', 'rgb24',
                '-r', str(fps), '-i', '-',
                '-c:v', 'libx264',
                '-profile:v', 'high',
                '-level', level,
                '-pix_fmt', 'yuv420p',
                '-b:v', f'{bitrate_k}k',
                '-maxrate', f'{maxrate_k}k',
                '-bufsize', f'{bufsize_k}k',
                '-preset', YOUTUBE_FFMPEG_PRESET,
                '-tune', 'stillimage',
                '-refs', '4',
                '-g', str(gop),
                '-keyint_min', str(gop),
                '-movflags', '+faststart',
                output_path,
            ]

    def _estimate_frame_count(self, n_moves):
        cfg = self.config
        total = 0
        if cfg.title_enabled and cfg.title_text: total += int(cfg.fps * cfg.title_duration)
        if cfg.position_hold_enabled: total += int(cfg.fps * cfg.position_hold_duration)
        loops = max(1, cfg.loop_count)
        total += loops * n_moves * (max(1, int(cfg.fps * cfg.move_anim_duration)) + max(1, int(cfg.fps * cfg.pause_after_move)))
        if cfg.end_enabled and cfg.end_text: total += int(cfg.fps * cfg.end_duration)
        return max(1, total)

    # ── Audio Merging ───────────────────────────────────────────────────

    def _merge_audio(self, video_path, audio_path):
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_with_audio{ext}"
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', YOUTUBE_AUDIO_BITRATE,
            '-ac', '2',
            '-ar', '44100',
            '-shortest',
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-movflags', '+faststart',
            output_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                try: os.remove(video_path); os.rename(output_path, video_path)
                except OSError: pass
                return video_path
            else: log(f"Audio merge failed: {result.stderr[-300:]}", "EXPORT"); return None
        except Exception as e: log(f"Audio merge error: {e}", "EXPORT"); return None