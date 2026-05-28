#!/usr/bin/env python3
"""FFmpeg-based video and GIF export — no moviepy dependency."""

import os
import shutil
import subprocess
import threading

import chess
import numpy as np

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage

from config import ExportConfig, THEMES, SQ_SIZE
from utils import log, ease_out_cubic, sanitize_filename
from board_widget import ChessBoardWidget
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
    for c in range(3):
        result[:, :, c] *= factor
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
        if config.gpu_contrast != 1.0:
            frame = _apply_contrast(frame, config.gpu_contrast)
        if config.gpu_saturation != 1.0:
            frame = _apply_saturation(frame, config.gpu_saturation)
        if config.gpu_vignette > 0:
            frame = _apply_vignette(frame, config.gpu_vignette)
    return frame


def _composite_frame(board_np, width, height, bg_color):
    bh, bw = board_np.shape[:2]
    if bw == width and bh == height:
        return board_np
    bg = np.full((height, width, 3), bg_color, dtype=np.uint8)
    x = (width - bw) // 2
    y = (height - bh) // 2
    y1, y2 = max(0, y), min(height, y + bh)
    x1, x2 = max(0, x), min(width, x + bw)
    sy1, sy2 = y1 - y, y1 - y + (y2 - y1)
    sx1, sx2 = x1 - x, x1 - x + (x2 - x1)
    bg[y1:y2, x1:x2] = board_np[sy1:sy2, sx1:sx2]
    return bg


# ── FFmpeg Video Exporter ───────────────────────────────────────────────────

class FFmpegVideoExporter(QObject):
    progress = Signal(int, int)
    finished = Signal(str)
    error = Signal(str)
    log_msg = Signal(str)

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
            frames = self._render_all_frames(puzzle)
            if self._cancel:
                self.error.emit("Export cancelled.")
                return
            self._write_video(frames, output_path)
            if self._cancel:
                self.error.emit("Export cancelled.")
                return
            if self.config.audio_path and os.path.isfile(self.config.audio_path):
                final_path = self._merge_audio(output_path, self.config.audio_path)
                if final_path:
                    output_path = final_path
            self.finished.emit(output_path)
        except Exception as e:
            self.error.emit(str(e))

    def export_puzzle_threaded(self, puzzle, output_path):
        t = threading.Thread(target=self.export_puzzle,
                             args=(puzzle, output_path), daemon=True)
        t.start()
        return t

    def export_batch(self, puzzles, output_dir):
        if not HAS_FFMPEG:
            self.error.emit("ffmpeg not found.")
            return
        os.makedirs(output_dir, exist_ok=True)
        for i, puzzle in enumerate(puzzles):
            if self._cancel:
                break
            name = sanitize_filename(puzzle.get('name', f'puzzle_{i+1}'))
            ext = '.gif' if self.config.export_gif else '.mp4'
            path = os.path.join(output_dir, f"{name}{ext}")
            try:
                frames = self._render_all_frames(puzzle)
                if self._cancel:
                    break
                self._write_video(frames, path)
                self.log_msg.emit(f"Exported {i+1}/{len(puzzles)}: {name}")
            except Exception as e:
                self.log_msg.emit(f"Error on {name}: {e}")
        self.finished.emit(output_dir)

    # ── Frame Rendering ─────────────────────────────────────────────────

    def _render_all_frames(self, puzzle):
        cfg = self.config
        engine = ChessEngine()
        fen = puzzle.get('fen', '')
        if fen:
            engine.load_fen(fen)
        else:
            engine.reset()

        sq_size = cfg.effective_sq_size
        theme = THEMES.get(cfg.theme_name, THEMES["Classic"])
        uci_moves = puzzle.get('moves', [])

        frames = []
        total_est = self._estimate_frame_count(len(uci_moves))
        frame_idx = 0

        if cfg.title_enabled and cfg.title_text:
            title_img = ChessBoardWidget.render_card(
                cfg.title_text, cfg.title_bg, cfg.title_fg,
                width=cfg.target_width, height=cfg.target_height,
                font_size=cfg.title_font_size,
                sub_text=puzzle.get('name', ''))
            title_np = self._prepare_frame(title_img)
            n_title = int(cfg.fps * cfg.title_duration)
            for _ in range(n_title):
                if self._cancel: return frames
                frames.append(title_np)
                frame_idx += 1
                self.progress.emit(frame_idx, total_est)

        n_pause = max(1, int(cfg.fps * cfg.pause_after_move))
        init_img = ChessBoardWidget.render_frame(
            engine.board, theme=theme, sq_size=sq_size)
        init_np = self._prepare_frame(init_img)
        for _ in range(n_pause):
            if self._cancel: return frames
            frames.append(init_np)
            frame_idx += 1
            self.progress.emit(frame_idx, total_est)

        for move_idx, move_uci in enumerate(uci_moves):
            if self._cancel: return frames

            move = chess.Move.from_uci(move_uci)
            if move not in engine.board.legal_moves:
                if move.promotion is None:
                    piece = engine.board.piece_at(move.from_square)
                    if piece and piece.piece_type == chess.PAWN:
                        promo_rank = 7 if piece.color == chess.WHITE else 0
                        if chess.square_rank(move.to_square) == promo_rank:
                            move = chess.Move(move.from_square, move.to_square,
                                              promotion=chess.QUEEN)
                if move not in engine.board.legal_moves:
                    self.log_msg.emit(f"Skipping illegal move: {move_uci}")
                    continue

            fr, fc = ChessEngine.sq_to_rc(move.from_square)
            tr, tc = ChessEngine.sq_to_rc(move.to_square)
            promo = chess.piece_symbol(move.promotion) if move.promotion else None

            piece = engine.board.piece_at(move.from_square)
            piece_obj = chess.Piece(piece.piece_type, piece.color)
            cap = engine.board.piece_at(move.to_square)
            captured = cap.symbol() if cap else '.'

            n_anim = max(1, int(cfg.fps * cfg.move_anim_duration))
            for fi in range(n_anim):
                if self._cancel: return frames
                t = fi / n_anim
                t_eased = ease_out_cubic(t)
                anim_state = {
                    'from': (fr, fc), 'to': (tr, tc),
                    'piece_obj': piece_obj, 'progress': t_eased,
                    'captured': captured,
                }
                frame_img = ChessBoardWidget.render_frame(
                    engine.board, anim_state=anim_state,
                    theme=theme, sq_size=sq_size)
                frames.append(self._prepare_frame(frame_img))
                frame_idx += 1
                self.progress.emit(frame_idx, total_est)

            info = engine.make_move(fr, fc, tr, tc, promo)
            last_move = ((fr, fc), (tr, tc))
            check_sqs = engine.check_squares()

            n_pause = max(1, int(cfg.fps * cfg.pause_after_move))
            pause_img = ChessBoardWidget.render_frame(
                engine.board, last_move=last_move,
                check_squares=check_sqs,
                theme=theme, sq_size=sq_size)
            pause_np = self._prepare_frame(pause_img)
            for _ in range(n_pause):
                if self._cancel: return frames
                frames.append(pause_np)
                frame_idx += 1
                self.progress.emit(frame_idx, total_est)

        if cfg.end_enabled and cfg.end_text:
            end_img = ChessBoardWidget.render_card(
                cfg.end_text, cfg.end_bg, cfg.end_fg,
                width=cfg.target_width, height=cfg.target_height,
                font_size=cfg.end_font_size,
                sub_text=puzzle.get('name', ''))
            end_np = self._prepare_frame(end_img)
            n_end = int(cfg.fps * cfg.end_duration)
            for _ in range(n_end):
                if self._cancel: return frames
                frames.append(end_np)
                frame_idx += 1
                self.progress.emit(frame_idx, total_est)

        return frames

    def _prepare_frame(self, qimg):
        np_frame = ChessBoardWidget.qimage_to_np(qimg)
        cfg = self.config
        w, h = cfg.target_width, cfg.target_height
        sq = cfg.effective_sq_size
        bw, bh = sq * 8, sq * 8

        if bw != w or bh != h:
            np_frame = _composite_frame(np_frame, w, h, cfg.background_color)

        np_frame = _apply_post_process(np_frame, cfg)
        return np_frame

    def _estimate_frame_count(self, n_moves):
        cfg = self.config
        total = 0
        if cfg.title_enabled and cfg.title_text:
            total += int(cfg.fps * cfg.title_duration)
        total += int(cfg.fps * cfg.pause_after_move)
        total += n_moves * (max(1, int(cfg.fps * cfg.move_anim_duration))
                            + max(1, int(cfg.fps * cfg.pause_after_move)))
        if cfg.end_enabled and cfg.end_text:
            total += int(cfg.fps * cfg.end_duration)
        return max(1, total)

    # ── FFmpeg Writing ──────────────────────────────────────────────────

    def _write_video(self, frames, output_path):
        if not frames:
            raise ValueError("No frames to write")
        cfg = self.config
        w, h = cfg.target_width, cfg.target_height

        if cfg.export_gif:
            self._write_gif(frames, output_path, w, h)
        else:
            self._write_mp4(frames, output_path, w, h)

    def _write_mp4(self, frames, output_path, w, h):
        cfg = self.config
        cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-s', f'{w}x{h}', '-pix_fmt', 'rgb24',
            '-r', str(cfg.fps), '-i', '-',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-crf', str(cfg.ffmpeg_crf),
            '-preset', cfg.ffmpeg_preset,
            '-movflags', '+faststart',
            output_path,
        ]
        self._run_ffmpeg_pipe(cmd, frames, w, h)

    def _write_gif(self, frames, output_path, w, h):
        cfg = self.config
        gif_fps = cfg.gif_fps if cfg.gif_fps > 0 else 12
        filter_str = (
            f'fps={gif_fps},'
            f'split[s0][s1];'
            f'[s0]palettegen=max_colors=256:stats_mode=diff[p];'
            f'[s1][p]paletteuse=dither=bayer:bayer_scale=3'
        )
        cmd = [
            'ffmpeg', '-y',
            '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-s', f'{w}x{h}', '-pix_fmt', 'rgb24',
            '-r', str(cfg.fps), '-i', '-',
            '-vf', filter_str,
            output_path,
        ]
        self._run_ffmpeg_pipe(cmd, frames, w, h)

    def _run_ffmpeg_pipe(self, cmd, frames, w, h):
        log(f"FFmpeg command: {' '.join(cmd)}", "EXPORT")
        process = subprocess.Popen(
            cmd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for i, frame in enumerate(frames):
            if self._cancel:
                process.kill()
                return
            if frame.shape[0] != h or frame.shape[1] != w:
                qimg = QImage(frame.data, frame.shape[1], frame.shape[0],
                              frame.shape[1] * 3,
                              QImage.Format_RGB888)
                qimg = qimg.scaled(w, h, Qt.IgnoreAspectRatio,
                                   Qt.SmoothTransformation)
                frame = ChessBoardWidget.qimage_to_np(qimg)
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        _, stderr = process.communicate()
        if process.returncode != 0:
            err_msg = stderr.decode('utf-8', errors='replace')[-500:]
            raise RuntimeError(f"FFmpeg error (code {process.returncode}): {err_msg}")
        log(f"FFmpeg wrote {len(frames)} frames successfully", "EXPORT")

    # ── Audio Merging ───────────────────────────────────────────────────

    def _merge_audio(self, video_path, audio_path):
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_with_audio{ext}"
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path, '-i', audio_path,
            '-c:v', 'copy', '-c:a', 'aac',
            '-shortest', '-map', '0:v:0', '-map', '1:a:0',
            output_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                try:
                    os.remove(video_path)
                    os.rename(output_path, video_path)
                except OSError:
                    pass
                return video_path
            else:
                log(f"Audio merge failed: {result.stderr[-300:]}", "EXPORT")
                return None
        except Exception as e:
            log(f"Audio merge error: {e}", "EXPORT")
            return None