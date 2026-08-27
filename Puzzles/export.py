"""MP4 export workers — single puzzle and batch rendering.
Supports YouTube/Shorts presets, frame compositing, audio overlay, GIF.
Numba JIT for frame normalisation; CuPy GPU for vignette + colour grading.
All workers are QThread subclasses — safe to run from main_window without popups.
"""

import chess, os, tempfile, shutil
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtCore import QThread, Signal
from constants import (
    log, HAS_NUMPY, HAS_IMAGEIO, HAS_NUMBA, HAS_CUPY, HAS_FFMPEG,
    ExportConfig, THEMES, EXPORT_PRESETS, sanitize_filename
)
from engine import ChessEngine
from board_widget import ChessBoardWidget

# ── Numba JIT frame helpers ──────────────────────────────────────────────────
if HAS_NUMBA:
    from numba import njit, prange

    @njit(cache=True, parallel=True, nogil=True)
    def _normalize_frames_nb(frame_ptrs, target_h, target_w):
        n = frame_ptrs.shape[0]
        out = np.empty((n, target_h, target_w, 3), dtype=np.uint8)
        for idx in prange(n):
            src = frame_ptrs[idx]
            sh, sw = src.shape[0], src.shape[1]
            for y in range(target_h):
                sy = min(int(y * sh / target_h), sh - 1)
                for x in range(target_w):
                    sx = min(int(x * sw / target_w), sw - 1)
                    for c in range(3):
                        out[idx, y, x, c] = src[sy, sx, c]
        return out

    log("Numba JIT frame normaliser loaded", "EXPORT")
else:
    def _normalize_frames_nb(frame_ptrs, target_h, target_w):
        out = np.empty((len(frame_ptrs), target_h, target_w, 3), dtype=np.uint8)
        for idx, src in enumerate(frame_ptrs):
            sh, sw = src.shape[0], src.shape[1]
            iy = (np.arange(target_h) * sh // target_h).clip(0, sh - 1)
            ix = (np.arange(target_w) * sw // target_w).clip(0, sw - 1)
            out[idx] = src[np.ix_(iy, ix)]
        return out


# ── CuPy GPU post-processing ─────────────────────────────────────────────────
if HAS_CUPY:
    import cupy as _cp

    def _gpu_vignette(frames_gpu, strength=0.25):
        _n, h, w, _c = frames_gpu.shape
        yy, xx = _cp.meshgrid(
            _cp.linspace(-1, 1, h, dtype=_cp.float32),
            _cp.linspace(-1, 1, w, dtype=_cp.float32),
            indexing='ij',
        )
        dist = _cp.sqrt(xx ** 2 + yy ** 2)
        vignette = 1.0 - strength * _cp.clip(dist / 1.414, 0, 1)
        vignette = vignette[_cp.newaxis, :, :, _cp.newaxis]
        out = frames_gpu.astype(_cp.float32) * vignette
        return _cp.clip(out, 0, 255).astype(_cp.uint8)

    def _gpu_color_grade(frames_gpu, contrast=1.02, brightness=0.0, saturation=1.05):
        f = frames_gpu.astype(_cp.float32)
        f = _cp.clip(f * contrast + brightness, 0, 255)
        if saturation != 1.0:
            gray = _cp.mean(f, axis=3, keepdims=True)
            f = _cp.clip(gray + saturation * (f - gray), 0, 255)
        return f.astype(_cp.uint8)

    log("CuPy GPU post-processing helpers loaded", "EXPORT")
else:
    _cp = None


# ═══════════════════════════════════════════════════════════════════════════════
#  Shared rendering logic (with compositing support)
# ═══════════════════════════════════════════════════════════════════════════════

def _render_puzzle_frames(puzzle, cfg, abort_check=None):
    """Render all frames for a puzzle, including compositing for YouTube/Shorts."""
    import chess
    sz = cfg.effective_sq_size
    bpx = sz * 8
    fps = cfg.fps
    theme = THEMES.get(cfg.theme_name, THEMES["Classic"])
    tasks = []

    tw, th = cfg.target_width, cfg.target_height
    needs_composite = (tw != bpx or th != bpx)
    bg = cfg.background_color

    title_text = cfg.title_text
    if not title_text:
        title_text = puzzle.get('display_title', puzzle.get('name', ''))

    if cfg.title_enabled and title_text:
        n_frames = int(fps * cfg.title_duration)
        card_font_size = max(24, int(sz * 0.55))
        if needs_composite:
            card_font_size = max(28, int(min(tw, th) * 0.05))
        for _ in range(n_frames):
            tasks.append(('card', {'text': title_text, 'bg': cfg.title_bg,
                                   'fg': cfg.title_fg, 'w': tw if needs_composite else bpx,
                                   'h': th if needs_composite else bpx,
                                   'font_size': card_font_size,
                                   'sub_text': cfg.subtitle_text}))

    eng = ChessEngine()
    fen = puzzle.get("fen")
    if fen: eng.load_fen(fen)
    else: eng.reset()

    for move_str in puzzle["moves"]:
        if abort_check and abort_check(): return None
        move_str = move_str.strip()
        if not move_str: continue

        board_before_move = eng.board.copy()

        # ═══════════════════════════════════════════════════════════════════
        # FIX: try UCI first, then SAN as fallback.
        #
        # Lichess puzzle DB:  Moves column is UCI  →  first try succeeds
        # Lichess opening DB: uci column is UCI    →  first try succeeds
        # Other DBs:          'moves' may be SAN   →  first try fails,
        #                      SAN fallback converts correctly
        # ═══════════════════════════════════════════════════════════════════
        move = None

        # 1) Try UCI (standard for Lichess puzzle & opening databases)
        try:
            m = chess.Move.from_uci(move_str)
            if m in eng.board.legal_moves:
                move = m
        except ValueError:
            pass

        # 2) Fallback: try SAN (handles databases where 'moves' is PGN/SAN
        #    that wasn't converted at import time, or edge cases)
        if move is None:
            try:
                move = eng.board.parse_san(move_str)
            except (ValueError, chess.InvalidMoveError,
                    chess.IllegalMoveError, chess.AmbiguousMoveError):
                pass

        if move is None:
            log(f"Skipping illegal move {move_str} in export "
                f"(not valid UCI or SAN from this position)", "EXPORT")
            continue
        # ═══════════════════════════════════════════════════════════════════

        from_sq = move.from_square; to_sq = move.to_square
        fr = 7 - chess.square_rank(from_sq); fc = chess.square_file(from_sq)
        tr = 7 - chess.square_rank(to_sq); tc = chess.square_file(to_sq)

        piece_obj = board_before_move.piece_at(from_sq)
        if piece_obj is None:
            log(f"Skipping invalid move {move_str} in export "
                f"(no piece on source square)", "EXPORT"); continue

        n_highlight = max(1, int(fps * cfg.highlight_duration))
        for _ in range(n_highlight):
            tasks.append(('board', {'board': board_before_move, 'sz': sz,
                                    'selected': (fr, fc), 'last_move': None,
                                    'theme': theme}))

        n_anim = max(1, int(fps * cfg.move_anim_duration))
        for i in range(n_anim):
            prog = i / n_anim
            tasks.append(('board', {'board': board_before_move, 'sz': sz,
                                    'anim_state': {'from': (fr, fc), 'to': (tr, tc),
                                                   'piece_obj': piece_obj, 'progress': prog},
                                    'theme': theme}))

        # FIX: use move.uci() instead of raw move_str, because the move
        # may have been parsed from SAN and the raw string isn't UCI
        info = eng.make_move_uci(move.uci())
        last_move = ((fr, fc), (tr, tc)) if info else None

        n_pause = max(1, int(fps * cfg.pause_after_move))
        for _ in range(n_pause):
            tasks.append(('board', {'board': eng.board.copy(), 'sz': sz,
                                    'last_move': last_move, 'theme': theme}))

    if cfg.end_enabled and cfg.end_text:
        n_frames = int(fps * cfg.end_duration)
        end_font_size = max(28, int(sz * 0.65))
        if needs_composite:
            end_font_size = max(32, int(min(tw, th) * 0.058))
        for _ in range(n_frames):
            tasks.append(('card', {'text': cfg.end_text, 'bg': cfg.end_bg,
                                   'fg': cfg.end_fg, 'w': tw if needs_composite else bpx,
                                   'h': th if needs_composite else bpx,
                                   'font_size': end_font_size}))

    total = len(tasks)
    if total == 0: return []

    frames = [None] * total

    def render_task(idx_task):
        idx, (t_type, t_kwargs) = idx_task
        if t_type == 'card':
            img = ChessBoardWidget.render_card(**t_kwargs)
            np_arr = ChessBoardWidget.qimage_to_np(img)
            if needs_composite:
                np_arr = composite_card_frame(np_arr, tw, th, bg)
        else:
            img = ChessBoardWidget.render_frame(
                t_kwargs['board'], last_move=t_kwargs.get('last_move'),
                selected=t_kwargs.get('selected'),
                anim_state=t_kwargs.get('anim_state'),
                sq_size=t_kwargs['sz'], show_arrow=True,
                theme=t_kwargs['theme'])
            np_arr = ChessBoardWidget.qimage_to_np(img)
            if needs_composite:
                np_arr = composite_frame(
                    np_arr, tw, th, bg,
                    title_overlay=cfg.title_overlay_text if cfg.show_title_overlay else "",
                    subtitle_overlay=cfg.subtitle_text if cfg.show_title_overlay else "",
                )
        return idx, np_arr

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
        futures = {executor.submit(render_task, (i, t)): i for i, t in enumerate(tasks)}
        for future in as_completed(futures):
            if abort_check and abort_check():
                executor.shutdown(wait=False, cancel_futures=True); return None
            try:
                idx, np_arr = future.result(); frames[idx] = np_arr
            except Exception as e:
                log(f"Frame render error: {e}", "EXPORT")

    frames = [f for f in frames if f is not None]
    if not frames:
        log("All frames failed to render", "EXPORT"); return None
    return frames

    def render_task(idx_task):
        idx, (t_type, t_kwargs) = idx_task
        if t_type == 'card':
            img = ChessBoardWidget.render_card(**t_kwargs)
            np_arr = ChessBoardWidget.qimage_to_np(img)
            if needs_composite:
                np_arr = composite_card_frame(np_arr, tw, th, bg)
        else:
            img = ChessBoardWidget.render_frame(
                t_kwargs['board'], last_move=t_kwargs.get('last_move'),
                selected=t_kwargs.get('selected'),
                anim_state=t_kwargs.get('anim_state'),
                sq_size=t_kwargs['sz'], show_arrow=True,
                theme=t_kwargs['theme'])
            np_arr = ChessBoardWidget.qimage_to_np(img)
            if needs_composite:
                np_arr = composite_frame(
                    np_arr, tw, th, bg,
                    title_overlay=cfg.title_overlay_text if cfg.show_title_overlay else "",
                    subtitle_overlay=cfg.subtitle_text if cfg.show_title_overlay else "",
                )
        return idx, np_arr

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
        futures = {executor.submit(render_task, (i, t)): i for i, t in enumerate(tasks)}
        for future in as_completed(futures):
            if abort_check and abort_check():
                executor.shutdown(wait=False, cancel_futures=True); return None
            try:
                idx, np_arr = future.result(); frames[idx] = np_arr
            except Exception as e:
                log(f"Frame render error: {e}", "EXPORT")

    frames = [f for f in frames if f is not None]
    if not frames:
        log("All frames failed to render", "EXPORT"); return None
    return frames


def _post_process_frames(frames, cfg, abort_check=None):
    if not frames: return frames

    target_h, target_w = cfg.target_height, cfg.target_width
    needs_resize = any(f.shape[0] != target_h or f.shape[1] != target_w
                       for f in frames if f is not None)
    if needs_resize:
        frame_ptrs = np.empty(len(frames), dtype=object)
        for i, f in enumerate(frames): frame_ptrs[i] = f
        frames_np = _normalize_frames_nb(frame_ptrs, target_h, target_w)
        frames = [frames_np[i] for i in range(len(frames))]

    use_gpu = (HAS_CUPY and cfg.gpu_post_process and
               (cfg.gpu_vignette > 0 or cfg.gpu_contrast != 1.0 or cfg.gpu_saturation != 1.0))
    if use_gpu:
        try: frames = _gpu_post_process(frames, cfg)
        except Exception as e:
            log(f"CuPy GPU post-processing failed ({e}), skipping", "EXPORT")
    return frames


def _gpu_post_process(frames, cfg):
    n = len(frames)
    if n == 0: return frames
    h, w, c = frames[0].shape
    frame_bytes = h * w * c
    chunk = max(1, min(200, (1 << 30) // frame_bytes))
    result = [None] * n

    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        stack_np = np.stack(frames[start:end])
        gpu = _cp.asarray(stack_np)
        if cfg.gpu_contrast != 1.0 or cfg.gpu_saturation != 1.0:
            gpu = _gpu_color_grade(gpu, contrast=cfg.gpu_contrast,
                                   saturation=cfg.gpu_saturation)
        if cfg.gpu_vignette > 0.0:
            gpu = _gpu_vignette(gpu, strength=cfg.gpu_vignette)
        cpu = _cp.asnumpy(gpu)
        for i in range(end - start): result[start + i] = cpu[i]
        del gpu, stack_np, cpu
        _cp.get_default_memory_pool().free_all_blocks()
    return result


def _write_mp4(filepath, frames, fps, cfg=None):
    """Write frames to MP4. Uses FFmpeg if available and configured, else imageio."""
    if not HAS_NUMPY or not HAS_IMAGEIO:
        return False, "ERROR: Missing numpy or imageio. pip install numpy imageio[ffmpeg]"

    use_ffmpeg = HAS_FFMPEG and (cfg.use_ffmpeg if cfg else True)
    
    if use_ffmpeg and cfg and len(frames) > 0:
        h, w = frames[0].shape[:2]
        try:
            tmp_dir = tempfile.mkdtemp(prefix="chess_frames_")
            write_frames_to_disk(frames, tmp_dir)
            crf = cfg.ffmpeg_crf if cfg else 20
            preset = cfg.ffmpeg_preset if cfg else "medium"
            ok, msg = write_mp4_ffmpeg(tmp_dir, filepath, fps, w, h, crf, preset)
            try: shutil.rmtree(tmp_dir)
            except OSError: pass
            if ok: return True, msg
            log(f"FFmpeg encode failed ({msg}), falling back to imageio", "EXPORT")
        except Exception as e:
            log(f"FFmpeg encode error ({e}), falling back to imageio", "EXPORT")

    try:
        import imageio.v3 as iio
        iio.imwrite(filepath, frames, fps=fps)
        return True, f"Saved: {filepath}"
    except AttributeError:
        try:
            import imageio
            imageio.mimwrite(filepath, frames, fps=fps)
            return True, f"Saved: {filepath}"
        except Exception as e2:
            msg = f"Error writing {filepath}: {e2}"; log(msg, "EXPORT"); return False, msg
    except Exception as e:
        msg = f"Error writing {filepath}: {e}"; log(msg, "EXPORT"); return False, msg


def _write_gif(filepath, frames, fps, cfg=None):
    """Write frames as GIF."""
    if HAS_FFMPEG and len(frames) > 0:
        h, w = frames[0].shape[:2]
        try:
            tmp_dir = tempfile.mkdtemp(prefix="chess_gif_")
            write_frames_to_disk(frames, tmp_dir)
            ok, msg = write_gif_ffmpeg(tmp_dir, filepath, fps, w, h)
            try: shutil.rmtree(tmp_dir)
            except OSError: pass
            if ok: return True, msg
        except Exception as e:
            log(f"FFmpeg GIF failed ({e}), trying imageio", "EXPORT")

    try:
        import imageio.v3 as iio
        iio.imwrite(filepath, frames, fps=fps, loop=0)
        return True, f"Saved GIF: {filepath}"
    except Exception as e:
        return False, f"GIF error: {e}"


def _add_audio(video_path, cfg):
    """Add background audio if configured."""
    audio_path = cfg.audio_path
    if not audio_path or not os.path.exists(audio_path):
        return video_path, ""

    base, ext = os.path.splitext(video_path)
    audio_out = base + "_audio" + ext
    
    ok, msg = mix_audio_ffmpeg(video_path, audio_path, audio_out,
                               volume=cfg.audio_volume)
    if ok:
        try:
            os.replace(audio_out, video_path)
            return video_path, msg
        except OSError:
            return audio_out, msg
    else:
        log(f"Audio mixing failed: {msg}", "EXPORT")
        return video_path, msg


# ═══════════════════════════════════════════════════════════════════════════════
#  Single-puzzle export worker
# ═══════════════════════════════════════════════════════════════════════════════

class ExportWorker(QThread):
    progress = Signal(int)
    finished = Signal(str)

    def __init__(self, puzzle, file_path, config=None):
        super().__init__()
        self.puzzle = puzzle; self.file_path = file_path
        self.config = config or ExportConfig(); self._abort = False

    def abort(self): self._abort = True

    def run(self):
        if not HAS_NUMPY or not HAS_IMAGEIO:
            msg = "ERROR: Missing numpy or imageio. pip install numpy imageio[ffmpeg]"
            log(msg, "EXPORT"); self.finished.emit(msg); return

        log(f"Exporting '{self.puzzle['name']}' -> {self.file_path}", "EXPORT")
        self.progress.emit(5)

        frames = _render_puzzle_frames(self.puzzle, self.config,
                                       abort_check=lambda: self._abort)
        if frames is None: self.finished.emit("Export cancelled."); return
        self.progress.emit(50)

        frames = _post_process_frames(frames, self.config,
                                      abort_check=lambda: self._abort)
        if frames is None: self.finished.emit("Export cancelled."); return
        self.progress.emit(70)

        if self.config.export_gif:
            ok, msg = _write_gif(self.file_path, frames, self.config.gif_fps, self.config)
            if ok and not self.file_path.endswith('.gif'):
                gif_path = os.path.splitext(self.file_path)[0] + '.gif'
                ok, msg = _write_gif(gif_path, frames, self.config.gif_fps, self.config)
        else:
            ok, msg = _write_mp4(self.file_path, frames, self.config.fps, self.config)
        self.progress.emit(85)

        if ok and self.config.audio_path:
            final_path, audio_msg = _add_audio(self.file_path, self.config)
            if audio_msg:
                msg = msg + " | " + audio_msg

        self.progress.emit(100 if ok else 0)
        self.finished.emit(msg)


# ═══════════════════════════════════════════════════════════════════════════════
#  Batch export worker
# ═══════════════════════════════════════════════════════════════════════════════

class BatchExportWorker(QThread):
    batch_progress  = Signal(int, int, str)
    puzzle_progress = Signal(int, int)
    puzzle_done     = Signal(int, str)
    puzzle_error    = Signal(int, str)
    all_done        = Signal(int, int, str)

    def __init__(self, puzzles, output_dir, config=None):
        super().__init__()
        self.puzzles = puzzles; self.output_dir = output_dir
        self.config = config or ExportConfig(); self._abort = False

    def abort(self): self._abort = True

    def _unique_path(self, base_name, ext=None):
        if ext is None:
            ext = ".gif" if self.config.export_gif else ".mp4"
        safe = sanitize_filename(base_name)
        path = os.path.join(self.output_dir, safe + ext)
        if not os.path.exists(path): return path
        i = 2
        while True:
            path = os.path.join(self.output_dir, f"{safe}_{i}{ext}")
            if not os.path.exists(path): return path
            i += 1

    def run(self):
        if not HAS_NUMPY or not HAS_IMAGEIO:
            msg = "ERROR: Missing numpy or imageio. pip install numpy imageio[ffmpeg]"
            log(msg, "EXPORT"); self.all_done.emit(0, len(self.puzzles), self.output_dir); return

        os.makedirs(self.output_dir, exist_ok=True)
        total = len(self.puzzles); exported = 0; errors = 0
        log(f"Batch export: {total} puzzles -> {self.output_dir}", "EXPORT")

        for i, puzzle in enumerate(self.puzzles):
            if self._abort: log("Batch export cancelled", "EXPORT"); break
            name = puzzle.get('name', f'puzzle_{i+1}')
            self.batch_progress.emit(i, total, name)
            self.puzzle_progress.emit(i, 0)
            filepath = self._unique_path(name)

            try:
                frames = _render_puzzle_frames(puzzle, self.config,
                                               abort_check=lambda: self._abort)
                if frames is None:
                    self.puzzle_error.emit(i, "Cancelled"); errors += 1; continue
                self.puzzle_progress.emit(i, 40)

                frames = _post_process_frames(frames, self.config,
                                              abort_check=lambda: self._abort)
                if frames is None:
                    self.puzzle_error.emit(i, "Cancelled"); errors += 1; continue
                self.puzzle_progress.emit(i, 70)

                if self.config.export_gif:
                    ok, msg = _write_gif(filepath, frames, self.config.gif_fps, self.config)
                else:
                    ok, msg = _write_mp4(filepath, frames, self.config.fps, self.config)

                if ok:
                    if self.config.audio_path and not self.config.export_gif:
                        final_path, audio_msg = _add_audio(filepath, self.config)
                        if audio_msg:
                            msg = msg + " | " + audio_msg
                    
                    exported += 1; self.puzzle_done.emit(i, filepath)
                    self.puzzle_progress.emit(i, 100)
                    log(f"Batch [{i+1}/{total}] saved: {filepath}", "EXPORT")
                else:
                    errors += 1; self.puzzle_error.emit(i, msg)

            except Exception as e:
                err_msg = f"Error exporting '{name}': {e}"
                log(err_msg, "EXPORT"); self.puzzle_error.emit(i, err_msg); errors += 1

        log(f"Batch export complete: {exported}/{total} exported, {errors} errors", "EXPORT")
        self.all_done.emit(exported, errors, self.output_dir)




# ═══════════════════════════════════════════════════════════════════════════════
#  Frame compositing
# ═══════════════════════════════════════════════════════════════════════════════

def composite_frame(board_np, target_w, target_h, bg,
                    title_overlay="", subtitle_overlay=""):
    """Composite a board numpy frame onto a target canvas with background."""
    canvas = np.full((target_h, target_w, 3), bg, dtype=np.uint8)
    bh, bw = board_np.shape[:2]
    x = (target_w - bw) // 2
    y = (target_h - bh) // 2
    # Clip to canvas bounds
    y1, y2 = max(0, y), min(target_h, y + bh)
    x1, x2 = max(0, x), min(target_w, x + bw)
    by1, by2 = y1 - y, y2 - y
    bx1, bx2 = x1 - x, x2 - x
    canvas[y1:y2, x1:x2] = board_np[by1:by2, bx1:bx2]

    # Render text overlays via QImage (safe on background threads for QImage targets)
    if title_overlay or subtitle_overlay:
        canvas = _render_overlays(canvas, title_overlay, subtitle_overlay)
    return canvas


def composite_card_frame(card_np, target_w, target_h, bg):
    """Composite a title/end-card numpy frame onto a target canvas."""
    canvas = np.full((target_h, target_w, 3), bg, dtype=np.uint8)
    ch, cw = card_np.shape[:2]
    x = (target_w - cw) // 2
    y = (target_h - ch) // 2
    y1, y2 = max(0, y), min(target_h, y + ch)
    x1, x2 = max(0, x), min(target_w, x + cw)
    by1, by2 = y1 - y, y2 - y
    bx1, bx2 = x1 - x, x2 - x
    canvas[y1:y2, x1:x2] = card_np[by1:by2, bx1:bx2]
    return canvas


def _render_overlays(canvas, title_text, subtitle_text):
    """Render title/subtitle text overlays onto a numpy canvas using QImage."""
    h, w = canvas.shape[:2]
    img = QImage(canvas.data, w, h, w * 3, QImage.Format_RGB888).copy()
    p = QPainter(img)
    p.setRenderHint(QPainter.TextAntialiasing)

    if title_text:
        font_size = max(16, int(min(w, h) * 0.04))
        p.setFont(QFont("Sans", font_size, QFont.Bold))
        p.setPen(QColor(220, 220, 220, 200))
        margin = int(h * 0.02)
        p.drawText(QRect(margin, margin, w - 2 * margin, font_size + 10),
                   Qt.AlignLeft | Qt.AlignTop, title_text)

    if subtitle_text:
        font_size = max(12, int(min(w, h) * 0.025))
        p.setFont(QFont("Sans", font_size))
        p.setPen(QColor(180, 180, 180, 180))
        margin = int(h * 0.02)
        top = h - font_size - margin - 10
        p.drawText(QRect(margin, top, w - 2 * margin, font_size + 10),
                   Qt.AlignLeft | Qt.AlignBottom, subtitle_text)

    p.end()
    # Convert back to numpy
    ptr = img.constBits()
    if hasattr(ptr, 'setsize'):
        ptr.setsize(img.sizeInBytes())
    raw = np.frombuffer(ptr, dtype=np.uint8).reshape(h, w * 3).copy()
    return raw.reshape(h, w, 3)


# ═══════════════════════════════════════════════════════════════════════════════
#  Frame I/O
# ═══════════════════════════════════════════════════════════════════════════════

def write_frames_to_disk(frames, output_dir):
    """Write a list of numpy (H×W×3 uint8) frames as PNG files."""
    os.makedirs(output_dir, exist_ok=True)
    if HAS_IMAGEIO:
        import imageio.v3 as iio
        for i, frame in enumerate(frames):
            iio.imwrite(os.path.join(output_dir, f"frame_{i:06d}.png"), frame)
    else:
        for i, frame in enumerate(frames):
            h, w = frame.shape[:2]
            img = QImage(frame.copy().data, w, h, w * 3, QImage.Format_RGB888).copy()
            img.save(os.path.join(output_dir, f"frame_{i:06d}.png"))
    log(f"Wrote {len(frames)} frames to {output_dir}", "VIDEO")


# ═══════════════════════════════════════════════════════════════════════════════
#  FFmpeg encoding
# ═══════════════════════════════════════════════════════════════════════════════

def write_mp4_ffmpeg(frame_dir, output_path, fps, width, height,
                     crf=20, preset="medium"):
    """Encode frames in *frame_dir* to MP4 via FFmpeg."""
    if not HAS_FFMPEG:
        return False, "FFmpeg not found on PATH"
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frame_dir, "frame_%06d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", str(crf),
        "-preset", preset,
        "-movflags", "+faststart",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            return True, f"Saved MP4: {output_path}"
        return False, f"FFmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return False, "FFmpeg binary not found"
    except subprocess.TimeoutExpired:
        return False, "FFmpeg encode timed out"


def write_gif_ffmpeg(frame_dir, output_path, fps, width, height):
    """Encode frames in *frame_dir* to GIF via FFmpeg."""
    if not HAS_FFMPEG:
        return False, "FFmpeg not found on PATH"
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frame_dir, "frame_%06d.png"),
        "-filter_complex", f"[0:v] fps={fps},split [a][b];[a] palettegen [p];[b][p] paletteuse",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            return True, f"Saved GIF: {output_path}"
        return False, f"FFmpeg GIF error: {result.stderr[:300]}"
    except FileNotFoundError:
        return False, "FFmpeg binary not found"
    except subprocess.TimeoutExpired:
        return False, "FFmpeg GIF encode timed out"


def mix_audio_ffmpeg(video_path, audio_path, output_path, volume=0.25):
    """Mix background audio into a video file using FFmpeg."""
    if not HAS_FFMPEG:
        return False, "FFmpeg not found on PATH"
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex", f"[1:a]volume={volume}[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            return True, "Audio mixed successfully"
        return False, f"FFmpeg audio error: {result.stderr[:300]}"
    except FileNotFoundError:
        return False, "FFmpeg binary not found"
    except subprocess.TimeoutExpired:
        return False, "FFmpeg audio mix timed out"