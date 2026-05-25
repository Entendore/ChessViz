"""MP4 export workers — single puzzle and batch rendering.
Numba JIT for frame normalisation; CuPy GPU for vignette + colour grading.
All workers are QThread subclasses — safe to run from main_window without popups.
"""

import chess, os
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtCore import QThread, Signal
from constants import (
    log, HAS_NUMPY, HAS_IMAGEIO, HAS_NUMBA, HAS_CUPY,
    ExportConfig, THEMES, sanitize_filename
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
#  Shared rendering logic
# ═══════════════════════════════════════════════════════════════════════════════

def _render_puzzle_frames(puzzle, cfg, abort_check=None):
    import chess
    sz = cfg.sq_size; bpx = sz * 8; fps = cfg.fps
    theme = THEMES.get(cfg.theme_name, THEMES["Classic"])
    tasks = []

    title_text = cfg.title_text
    if not title_text:
        title_text = puzzle.get('display_title', puzzle.get('name', ''))

    if cfg.title_enabled and title_text:
        n_frames = int(fps * cfg.title_duration)
        for _ in range(n_frames):
            tasks.append(('card', {'text': title_text, 'bg': cfg.title_bg,
                                   'fg': cfg.title_fg, 'w': bpx, 'h': bpx,
                                   'font_size': cfg.title_font_size}))

    eng = ChessEngine()
    fen = puzzle.get("fen")
    if fen: eng.load_fen(fen)
    else: eng.reset()

    for uci in puzzle["moves"]:
        if abort_check and abort_check(): return None
        uci = uci.strip()
        if not uci: continue

        board_before_move = eng.board.copy()
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            log(f"Skipping invalid UCI format: {uci}", "EXPORT"); continue

        if move not in eng.board.legal_moves:
            log(f"Skipping illegal move {uci} in export", "EXPORT"); continue

        from_sq = move.from_square; to_sq = move.to_square
        fr = 7 - chess.square_rank(from_sq); fc = chess.square_file(from_sq)
        tr = 7 - chess.square_rank(to_sq); tc = chess.square_file(to_sq)

        piece_obj = board_before_move.piece_at(from_sq)
        if piece_obj is None:
            log(f"Skipping invalid move {uci} in export", "EXPORT"); continue

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

        info = eng.make_move_uci(uci)
        last_move = ((fr, fc), (tr, tc)) if info else None

        n_pause = max(1, int(fps * cfg.pause_after_move))
        for _ in range(n_pause):
            tasks.append(('board', {'board': eng.board.copy(), 'sz': sz,
                                    'last_move': last_move, 'theme': theme}))

    if cfg.end_enabled and cfg.end_text:
        n_frames = int(fps * cfg.end_duration)
        for _ in range(n_frames):
            tasks.append(('card', {'text': cfg.end_text, 'bg': cfg.end_bg,
                                   'fg': cfg.end_fg, 'w': bpx, 'h': bpx,
                                   'font_size': cfg.end_font_size}))

    total = len(tasks)
    if total == 0: return []

    frames = [None] * total

    def render_task(idx_task):
        idx, (t_type, t_kwargs) = idx_task
        if t_type == 'card':
            img = ChessBoardWidget.render_card(**t_kwargs)
        else:
            img = ChessBoardWidget.render_frame(
                t_kwargs['board'], last_move=t_kwargs.get('last_move'),
                selected=t_kwargs.get('selected'),
                anim_state=t_kwargs.get('anim_state'),
                sq_size=t_kwargs['sz'], show_arrow=True,
                theme=t_kwargs['theme'])
        return idx, ChessBoardWidget.qimage_to_np(img)

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

    target_h, target_w = cfg.sq_size * 8, cfg.sq_size * 8
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


def _write_mp4(filepath, frames, fps):
    if not HAS_IMAGEIO: return False, "imageio not installed"
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
        self.progress.emit(60)

        frames = _post_process_frames(frames, self.config,
                                      abort_check=lambda: self._abort)
        if frames is None: self.finished.emit("Export cancelled."); return
        self.progress.emit(80)

        ok, msg = _write_mp4(self.file_path, frames, self.config.fps)
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

    def _unique_path(self, base_name, ext=".mp4"):
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
                self.puzzle_progress.emit(i, 50)

                frames = _post_process_frames(frames, self.config,
                                              abort_check=lambda: self._abort)
                if frames is None:
                    self.puzzle_error.emit(i, "Cancelled"); errors += 1; continue
                self.puzzle_progress.emit(i, 80)

                ok, msg = _write_mp4(filepath, frames, self.config.fps)
                if ok:
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