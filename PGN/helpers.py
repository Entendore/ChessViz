import os
import math
import subprocess
import chess
from PySide6.QtGui import QImage
from constants import HAS_CV2, HAS_NUMBA, HAS_CUPY, GAME_CHECKMATE, GAME_STALEMATE, GAME_INSUFFICIENT, GAME_DRAW, find_ffmpeg

# --- Numba JIT Compilations ---
if HAS_NUMBA:
    import numba
    import numpy as np

    @numba.njit(cache=True)
    def _rgb_to_bgr_numba(src, dst):
        for y in range(src.shape[0]):
            for x in range(src.shape[1]):
                dst[y, x, 0] = src[y, x, 2]
                dst[y, x, 1] = src[y, x, 1]
                dst[y, x, 2] = src[y, x, 0]

    @numba.njit(cache=True)
    def _cp2r_numba(cp):
        if cp >= 10000.0: return 1.0
        if cp <= -10000.0: return 0.0
        return 1.0 / (1.0 + math.exp(-0.004 * max(-10000.0, min(10000.0, cp))))

    @numba.njit(cache=True)
    def _ease_in_out_numba(progress):
        return 0.5 - 0.5 * math.cos(math.pi * progress)

def _detect_game_state(board):
    if board.is_checkmate(): return GAME_CHECKMATE, "1-0" if board.turn == chess.BLACK else "0-1", "Checkmate"
    if board.is_stalemate(): return GAME_STALEMATE, "½-½", "Stalemate"
    if board.is_insufficient_material(): return GAME_INSUFFICIENT, "½-½", "Insufficient Material"
    if board.is_game_over():
        if board.is_fifty_moves(): return GAME_DRAW, "½-½", "50-Move Rule"
        if board.is_repetition(): return GAME_DRAW, "½-½", "Repetition"
        return GAME_DRAW, "½-½", "Draw"
    return "normal", "", ""

def _get_castling_rook_move(move):
    from_file, to_file = chess.square_file(move.from_square), chess.square_file(move.to_square)
    if from_file == 4 and abs(to_file - from_file) == 2:
        rank = chess.square_rank(move.from_square)
        if to_file == 6: return (chess.square(7, rank), chess.square(5, rank))
        else: return (chess.square(0, rank), chess.square(3, rank))
    return None

def _qimage_to_bgr_numpy(qimg, target_w=None, target_h=None):
    if not HAS_CV2: return None
    import cv2
    import numpy as np
    
    img = qimg.convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 3)).copy()
    
    needs_resize = target_w is not None and target_h is not None and (w != target_w or h != target_h)

    if HAS_CUPY:
        import cupy as cp
        import cupyx.scipy.ndimage
        gpu_rgb = cp.asarray(arr)
        gpu_bgr = gpu_rgb[:, :, ::-1].copy()
        if needs_resize:
            fy, fx = target_h / h, target_w / w
            gpu_bgr = cupyx.scipy.ndimage.zoom(gpu_bgr, (fy, fx, 1), order=1)
            if gpu_bgr.dtype != np.uint8: gpu_bgr = cp.clip(gpu_bgr, 0, 255).astype(cp.uint8)
        return cp.asnumpy(gpu_bgr)

    if HAS_NUMBA:
        bgr = np.empty_like(arr)
        _rgb_to_bgr_numba(arr, bgr)
        if needs_resize: bgr = cv2.resize(bgr, (target_w, target_h))
        return bgr

    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    if needs_resize: bgr = cv2.resize(bgr, (target_w, target_h))
    return bgr

class VideoWriter:
    def __init__(self, output_path, fps, w, h, ffmpeg_path=None):
        self.w, self.h = w, h
        self.proc, self.cv_writer, self.used_path, self.used_codec = None, None, output_path, None
        
        if ffmpeg_path:
            cmd = [ffmpeg_path, '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo', '-s', f'{w}x{h}', '-pix_fmt', 'rgb24', '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', output_path]
            try:
                self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.used_codec = "h264"
            except Exception: self.proc = None
                
        if not self.proc and HAS_CV2:
            import cv2
            for fc, ext in [("avc1", ".mp4"), ("X264", ".mp4"), ("mp4v", ".mp4"), ("XVID", ".avi")]:
                path = output_path if output_path.lower().endswith(ext) else os.path.splitext(output_path)[0] + ext
                self.cv_writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*fc), fps, (w, h))
                if self.cv_writer.isOpened(): self.used_path, self.used_codec = path, fc; break
                self.cv_writer.release(); self.cv_writer = None

    def is_open(self): return self.proc is not None or (self.cv_writer is not None and self.cv_writer.isOpened())

    def write(self, qimg):
        if self.proc:
            img = qimg.convertToFormat(QImage.Format_RGB888)
            ptr = img.constBits(); ptr.setsize(img.sizeInBytes())
            try: self.proc.stdin.write(bytes(ptr))
            except BrokenPipeError: pass
        elif self.cv_writer:
            bgr = _qimage_to_bgr_numpy(qimg, target_w=self.w, target_h=self.h)
            if bgr is not None: self.cv_writer.write(bgr)

    def release(self):
        if self.proc:
            try: self.proc.stdin.close(); self.proc.wait(timeout=10)
            except Exception:
                try: self.proc.kill()
                except Exception: pass
        if self.cv_writer: self.cv_writer.release()

def _create_video_writer(output_path, fps, w, h):
    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path:
        w_obj = VideoWriter(output_path, fps, w, h, ffmpeg_path=ffmpeg_path)
        if w_obj.is_open(): return w_obj, output_path, "h264 (FFmpeg)"
        w_obj.release()
    if HAS_CV2:
        w_obj = VideoWriter(output_path, fps, w, h, ffmpeg_path=None)
        if w_obj.is_open(): return w_obj, w_obj.used_path, f"{w_obj.used_codec} (OpenCV)"
        w_obj.release()
    return None, None, None