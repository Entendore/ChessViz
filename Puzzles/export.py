"""MP4 export worker — renders a puzzle as a video file using batch rendering, parallelism, and themes."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtCore import QThread, Signal
from constants import log, HAS_NUMPY, HAS_IMAGEIO, ExportConfig, THEMES
from engine import ChessEngine
from board_widget import ChessBoardWidget


class ExportWorker(QThread):
    progress = Signal(int)
    finished = Signal(str)

    def __init__(self, puzzle, file_path, config=None):
        super().__init__()
        self.puzzle = puzzle
        self.file_path = file_path
        self.config = config or ExportConfig()

    def run(self):
        if not HAS_NUMPY or not HAS_IMAGEIO:
            msg = "ERROR: Missing numpy or imageio. pip install numpy imageio[ffmpeg]"
            log(msg, "EXPORT"); self.finished.emit(msg); return

        import numpy as np
        import imageio.v3 as iio

        log(f"Starting MP4 export for puzzle '{self.puzzle['name']}' -> {self.file_path}", "EXPORT")
        cfg = self.config; sz = cfg.sq_size; bpx = sz * 8; fps = cfg.fps
        theme = THEMES.get(cfg.theme_name, THEMES["Classic"])
        tasks = []

        if cfg.title_enabled and cfg.title_text:
            n_frames = int(fps * cfg.title_duration)
            for i in range(n_frames):
                tasks.append(('card', {'text': cfg.title_text, 'bg': cfg.title_bg, 'fg': cfg.title_fg, 'w': bpx, 'h': bpx, 'font_size': cfg.title_font_size}))

        eng = ChessEngine()
        fen = self.puzzle.get("fen")
        if fen: eng.load_fen(fen)
        else: eng.reset()

        for uci in self.puzzle["moves"]:
            move, promo = eng.parse_uci(uci)
            if not move: continue
            (fr, fc), (tr, tc) = move
            piece = eng.board[fr][fc]; captured = eng.board[tr][tc]

            n_highlight = max(1, int(fps * cfg.highlight_duration))
            for i in range(n_highlight):
                tasks.append(('board', {'board': eng.copy_board(), 'sz': sz, 'selected': (fr, fc), 'last_move': None, 'theme': theme, 'mq': None}))

            n_anim = max(1, int(fps * cfg.move_anim_duration))
            for i in range(n_anim):
                prog = i / n_anim
                tasks.append(('board', {'board': eng.copy_board(), 'sz': sz, 'anim_state': {'from': (fr, fc), 'to': (tr, tc), 'piece': piece, 'progress': prog}, 'theme': theme, 'mq': None}))

            info = eng.make_move(fr, fc, tr, tc, promo)
            last_move = ((fr, fc), (tr, tc)) if info else None

            n_pause = max(1, int(fps * cfg.pause_after_move))
            for i in range(n_pause):
                tasks.append(('board', {'board': eng.copy_board(), 'sz': sz, 'last_move': last_move, 'theme': theme, 'mq': cfg.move_quality}))

        if cfg.end_enabled and cfg.end_text:
            n_frames = int(fps * cfg.end_duration)
            for i in range(n_frames):
                tasks.append(('card', {'text': cfg.end_text, 'bg': cfg.end_bg, 'fg': cfg.end_fg, 'w': bpx, 'h': bpx, 'font_size': cfg.end_font_size}))

        total = len(tasks)
        if total == 0: self.finished.emit("No frames to render."); return

        log(f"Rendering {total} frames using up to {cfg.max_workers} workers...", "EXPORT")
        frames = [None] * total

        def render_task(idx_task):
            idx, (t_type, t_kwargs) = idx_task
            if t_type == 'card':
                img = ChessBoardWidget.render_card(**t_kwargs)
            else:
                img = ChessBoardWidget.render_frame(
                    t_kwargs['board'], last_move=t_kwargs.get('last_move'),
                    selected=t_kwargs.get('selected'), anim_state=t_kwargs.get('anim_state'),
                    sq_size=t_kwargs['sz'], show_arrow=True, theme=t_kwargs['theme'], move_quality=t_kwargs['mq'])
            return idx, ChessBoardWidget.qimage_to_np(img)

        completed = 0
        with ThreadPoolExecutor(max_workers=cfg.max_workers) as executor:
            futures = {executor.submit(render_task, (i, t)): i for i, t in enumerate(tasks)}
            for future in as_completed(futures):
                try:
                    idx, np_arr = future.result(); frames[idx] = np_arr
                    completed += 1
                    if completed % max(1, total // 20) == 0 or completed == total:
                        pct = int(90 * completed / total); self.progress.emit(pct)
                except Exception as e:
                    log(f"Frame render error: {e}", "EXPORT")

        log(f"Writing {total} frames to {self.file_path}...", "EXPORT")
        try: iio.write(self.file_path, fps, frames)
        except Exception as e:
            msg = f"Error writing MP4: {e}"; log(msg, "EXPORT"); self.finished.emit(msg); return

        self.progress.emit(100)
        msg = f"MP4 successfully saved to: {self.file_path}"
        log(msg, "EXPORT"); self.finished.emit(msg)