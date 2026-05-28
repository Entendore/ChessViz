# workers.py
"""
Background worker threads for game play and video export.
Performance improvements:
  - Batch QImage → numpy conversion
  - CuPy GPU-accelerated RGB→BGR batch conversion
  - Frame caching for duplicate states (pause/settle frames)
  - Buffer reuse to reduce allocations
  - Audio mixing and muxing for video export
"""

import time
import shutil
import logging
import subprocess
import os
import wave
from io import StringIO

import chess
import chess.pgn

from PySide6.QtCore import QObject, Signal

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from constants import (
    RESOLUTION_SIZES, GAME_NORMAL, GAME_CHECKMATE,
    GAME_STALEMATE, GAME_DRAW, GAME_INSUFFICIENT, MQ_GOOD,
    DEFAULT_VIDEO_FPS, DEFAULT_MOVE_DURATION,
    DEFAULT_ANIM_DURATION, DEFAULT_TITLE_DURATION,
    DEFAULT_RESULT_DURATION,
    SND_MOVE, SND_CAPTURE, SND_CHECK, SND_CASTLE,
    SND_CHECKMATE, SND_STALEMATE, SND_DRAW, SND_GAME_START,
)
from engines import MinimaxEngine, MCTSEngine, SyncUCI, rgb_to_bgr_batch
from board_renderer import BoardRenderer
from video_renderer import VideoRenderer

logger = logging.getLogger("AIvsAI2MP4")


def _ease_out_quint(t):
    return 1.0 - (1.0 - t) ** 5


class GameWorker(QObject):
    move_made = Signal(chess.Board, chess.Move, float, int, dict, str, str, str)
    game_over = Signal(str, str, str)
    error = Signal(str)
    finished = Signal()

    def __init__(self, white_type, white_depth, black_type, black_depth,
                 stockfish_path=None, move_delay=100):
        super().__init__()
        self.white_type = white_type
        self.white_depth = white_depth
        self.black_type = black_type
        self.black_depth = black_depth
        self.stockfish_path = stockfish_path
        self._move_delay = move_delay
        self._stop = False
        self.board = chess.Board()

    def stop(self):
        self._stop = True

    def run(self):
        engines = {}
        sf_instance = None
        try:
            for color, (etype, depth) in enumerate([
                (self.white_type, self.white_depth),
                (self.black_type, self.black_depth),
            ]):
                if etype == 0:
                    engines[color] = ("minimax", MinimaxEngine(), depth)
                elif etype == 1:
                    engines[color] = ("mcts", MCTSEngine(), depth)
                elif etype == 2:
                    if sf_instance is None:
                        if not self.stockfish_path:
                            self.error.emit("Stockfish path not configured.")
                            return
                        try:
                            sf_instance = SyncUCI(self.stockfish_path)
                        except Exception as e:
                            self.error.emit(f"Failed to start Stockfish: {e}")
                            return
                    engines[color] = ("stockfish", sf_instance, depth)

            self.board.reset()

            while not self.board.is_game_over() and not self._stop:
                current_color = self.board.turn
                color_key = 0 if current_color == chess.WHITE else 1
                engine_type, engine, depth = engines[color_key]

                if engine_type == "stockfish":
                    bm, sc = engine.analyse(self.board.fen(), depth=depth)
                    if bm:
                        move = chess.Move.from_uci(bm)
                    else:
                        self.error.emit("Stockfish returned no move.")
                        break
                    eval_cp, nodes, policy = sc, 0, {}
                elif engine_type == "minimax":
                    move, eval_score, nodes, policy = engine.search(self.board, depth)
                    eval_cp = eval_score
                elif engine_type == "mcts":
                    move, eval_score, nodes, policy = engine.search(
                        self.board, iterations=depth * 100)
                    eval_cp = eval_score
                else:
                    break

                if move is None or move not in self.board.legal_moves:
                    logger.warning("Engine returned illegal/None move, stopping.")
                    break

                self.board.push(move)
                game_state, result, detail = self._detect_game_state()

                self.move_made.emit(
                    self.board.copy(), move, eval_cp, nodes, policy,
                    game_state, result, detail,
                )

                if game_state != GAME_NORMAL:
                    self.game_over.emit(game_state, result, detail)
                    break

                time.sleep(self._move_delay / 1000.0)

        except Exception as e:
            logger.exception("Game thread error")
            self.error.emit(str(e))
        finally:
            if sf_instance:
                try:
                    sf_instance.close()
                except Exception:
                    pass
            self.finished.emit()

    def _detect_game_state(self):
        if self.board.is_checkmate():
            r = "1-0" if self.board.turn == chess.BLACK else "0-1"
            return GAME_CHECKMATE, r, "Checkmate"
        if self.board.is_stalemate():
            return GAME_STALEMATE, "½-½", "Stalemate"
        if self.board.is_insufficient_material():
            return GAME_INSUFFICIENT, "½-½", "Insufficient Material"
        if self.board.is_repetition(3):
            return GAME_DRAW, "½-½", "Threefold Repetition"
        if self.board.is_fifty_moves():
            return GAME_DRAW, "½-½", "50-Move Rule"
        if self.board.is_game_over():
            return GAME_DRAW, "½-½", "Draw"
        return GAME_NORMAL, "", ""


class ExportWorker(QObject):
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, pgn_text, save_path, resolution_key, fps,
                 board_theme, white_name, black_name,
                 white_engine_info, black_engine_info,
                 eval_history, move_qualities,
                 move_duration=DEFAULT_MOVE_DURATION,
                 anim_duration=DEFAULT_ANIM_DURATION,
                 title_duration=DEFAULT_TITLE_DURATION,
                 result_duration=DEFAULT_RESULT_DURATION,
                 show_title=True, show_result=True,
                 sound_engine=None):
        super().__init__()
        self.pgn_text = pgn_text
        self.save_path = save_path
        self.resolution_key = resolution_key
        self.fps = fps
        self.board_theme = board_theme
        self.white_name = white_name
        self.black_name = black_name
        self.white_engine_info = white_engine_info
        self.black_engine_info = black_engine_info
        self.eval_history = eval_history
        self.move_qualities = move_qualities
        self.move_duration = move_duration
        self.anim_duration = anim_duration
        self.title_duration = title_duration
        self.result_duration = result_duration
        self.show_title = show_title
        self.show_result = show_result
        self.sound_engine = sound_engine
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        if not HAS_CV2:
            self.error.emit("opencv-python is required.\npip install opencv-python")
            return
        try:
            game = None
            if hasattr(chess.pgn, 'read_gameFromString'):
                try:
                    game = chess.pgn.read_gameFromString(self.pgn_text)
                except Exception:
                    pass
            if game is None:
                io = StringIO(self.pgn_text)
                game = chess.pgn.read_game(io)
            if game is None:
                self.error.emit("Invalid PGN.")
                return

            w, h = RESOLUTION_SIZES.get(self.resolution_key, (1920, 1080))
            fps = max(1, self.fps)

            moves = list(game.mainline_moves())
            total_moves = len(moves)
            if total_moves == 0:
                self.error.emit("No moves found in PGN.")
                return
            logger.info("Export starting: %dx%d @ %d fps, %d moves",
                        w, h, fps, total_moves)

            anim_frames = max(1, int(fps * self.anim_duration))
            total_move_frames = max(anim_frames + 1,
                                    int(fps * self.move_duration))
            pause_before = max(0, (total_move_frames - anim_frames) // 2)
            pause_after = total_move_frames - anim_frames - pause_before

            title_frames = int(fps * self.title_duration) if self.show_title else 0
            result_frames = int(fps * self.result_duration) if self.show_result else 0
            total_frames = (title_frames
                            + total_moves * total_move_frames
                            + result_frames)
            if total_frames <= 0:
                total_frames = 1
            frames_done = 0

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            tmp_path = self.save_path.replace(".mp4", "_tmp.mp4")
            out = cv2.VideoWriter(tmp_path, fourcc, fps, (w, h))
            if not out.isOpened():
                self.error.emit("Failed to create video writer.")
                return

            board = chess.Board()
            renderer = BoardRenderer(board=board, theme=self.board_theme)
            video = VideoRenderer(renderer, w=w, h=h)
            video.white_name = self.white_name
            video.black_name = self.black_name
            video.white_engine_info = self.white_engine_info
            video.black_engine_info = self.black_engine_info

            frame_buf = np.empty((h, w * 3), dtype=np.uint8)

            # Audio setup
            audio_data = {}
            sr = 44100
            mix = None
            if self.sound_engine and self.sound_engine.enabled:
                sr = self.sound_engine._sr
                for event in [SND_MOVE, SND_CAPTURE, SND_CHECK, SND_CASTLE,
                              SND_CHECKMATE, SND_STALEMATE, SND_DRAW, SND_GAME_START]:
                    fp = self.sound_engine.get_sound_path(event)
                    if fp and os.path.exists(fp):
                        try:
                            with wave.open(fp, 'rb') as wf:
                                n = wf.getnframes()
                                raw = wf.readframes(n)
                                audio_data[event] = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32767.0
                        except Exception:
                            pass

                if audio_data:
                    total_samples = int(sr * (total_frames / fps)) + sr * 2
                    mix = np.zeros(total_samples, dtype=np.float64)
                    if SND_GAME_START in audio_data and title_frames > 0:
                        self._add_audio(mix, 0, audio_data[SND_GAME_START], sr, fps)

            # Title screen
            if self.show_title and title_frames > 0:
                title_img = video.render_title_screen()
                title_bgr = self._qimage_to_bgr_numpy(title_img, frame_buf)
                if title_bgr is not None:
                    for _ in range(title_frames):
                        if self._stop:
                            break
                        out.write(title_bgr)
                        frames_done += 1
                    self.progress.emit(int(frames_done / total_frames * 100))

            # Game frames
            move_list_text = []

            for i, move in enumerate(moves):
                if self._stop:
                    logger.info("Export stopped at move %d/%d", i + 1, total_moves)
                    break

                san = board.san(move)
                move_list_text.append(san)

                quality = (self.move_qualities[i]
                           if i < len(self.move_qualities) else MQ_GOOD)
                eval_cp = (self.eval_history[i]
                           if i < len(self.eval_history) else 0.0)

                video.move_list_text = list(move_list_text)
                video.current_move_index = i
                video.move_qualities = self.move_qualities[:i + 1]
                video.eval_cp = eval_cp
                video.eval_history = self.eval_history[:i + 1]

                rook_move = None
                piece = board.piece_at(move.from_square)
                if (piece and piece.piece_type == chess.KING and
                        abs(chess.square_file(move.from_square) -
                            chess.square_file(move.to_square)) == 2):
                    rank = chess.square_rank(move.from_square)
                    if chess.square_file(move.to_square) > chess.square_file(move.from_square):
                        rook_move = (chess.square(7, rank), chess.square(5, rank))
                    else:
                        rook_move = (chess.square(0, rank), chess.square(3, rank))

                is_cap = board.is_capture(move)
                is_castle = rook_move is not None
                gives_check = board.gives_check(move)

                # Pre-move pause
                renderer.board = board
                renderer.last_move = (moves[i - 1] if i > 0 else None)
                renderer.move_quality = (self.move_qualities[i - 1]
                                         if i > 0 and i - 1 < len(self.move_qualities)
                                         else MQ_GOOD)
                renderer.anim_move = None
                renderer.anim_rook_move = None
                renderer.anim_progress = 1.0

                if pause_before > 0:
                    pause_img = video.render()
                    pause_bgr = self._qimage_to_bgr_numpy(pause_img, frame_buf)
                    if pause_bgr is not None:
                        for _ in range(pause_before):
                            if self._stop:
                                break
                            out.write(pause_bgr)
                            frames_done += 1

                # Animation frames
                board.push(move)

                if mix is not None:
                    is_mate = board.is_checkmate()
                    is_stale = board.is_stalemate()
                    is_draw = board.is_game_over() and not is_mate and not is_stale

                    if is_mate:       snd_event = SND_CHECKMATE
                    elif is_stale:    snd_event = SND_STALEMATE
                    elif is_draw:     snd_event = SND_DRAW
                    elif gives_check: snd_event = SND_CHECK
                    elif is_castle:   snd_event = SND_CASTLE
                    elif is_cap:      snd_event = SND_CAPTURE
                    else:             snd_event = SND_MOVE

                    if snd_event in audio_data:
                        self._add_audio(mix, frames_done, audio_data[snd_event], sr, fps)

                renderer.board = board
                renderer.last_move = move
                renderer.move_quality = quality
                renderer.anim_move = move
                renderer.anim_rook_move = rook_move

                anim_rgb_frames = []
                for f_idx in range(anim_frames):
                    if self._stop:
                        break
                    t = f_idx / max(1, anim_frames - 1)
                    renderer.anim_progress = _ease_out_quint(t)
                    img = video.render()
                    rgb = self._qimage_to_rgb_numpy(img, frame_buf)
                    if rgb is not None:
                        anim_rgb_frames.append(rgb)
                    frames_done += 1

                if anim_rgb_frames:
                    anim_bgr_frames = rgb_to_bgr_batch(anim_rgb_frames)
                    for bgr in anim_bgr_frames:
                        out.write(bgr)

                # Post-move settle
                renderer.anim_move = None
                renderer.anim_rook_move = None
                renderer.anim_progress = 1.0

                game_state, result, detail = self._detect_game_state(board)
                if game_state != GAME_NORMAL:
                    video.game_state = game_state
                    video.game_result = result
                    video.game_detail = detail

                if pause_after > 0:
                    settle_img = video.render()
                    settle_bgr = self._qimage_to_bgr_numpy(settle_img, frame_buf)
                    if settle_bgr is not None:
                        for _ in range(pause_after):
                            if self._stop:
                                break
                            out.write(settle_bgr)
                            frames_done += 1

                pct = int(frames_done / max(1, total_frames) * 100)
                self.progress.emit(min(95, pct))

            # Result screen
            if self.show_result and result_frames > 0 and not self._stop:
                result_img = video.render_result_screen()
                result_bgr = self._qimage_to_bgr_numpy(result_img, frame_buf)
                if result_bgr is not None:
                    for _ in range(result_frames):
                        if self._stop:
                            break
                        out.write(result_bgr)
                        frames_done += 1

            out.release()
            logger.info("Raw video written: %s", tmp_path)

            # Export Audio
            audio_tmp_path = None
            if mix is not None:
                actual_samples = int(sr * (frames_done / fps)) + sr
                mix = mix[:actual_samples]
                max_val = np.max(np.abs(mix))
                if max_val > 0:
                    mix = mix / max(max_val * 1.1, 1.0)
                mix_int16 = (mix * 32767).astype(np.int16)

                audio_tmp_path = tmp_path.replace(".mp4", "_audio.wav")
                try:
                    with wave.open(audio_tmp_path, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sr)
                        wf.writeframes(mix_int16.tobytes())
                    logger.info("Audio track generated: %s", audio_tmp_path)
                except Exception as e:
                    logger.warning("Failed to write audio track: %s", e)
                    audio_tmp_path = None

            # H.264 re-encode
            final_path = self._reencode_h264(tmp_path, self.save_path, audio_tmp_path)
            if final_path:
                logger.info("Export complete: %s", final_path)
                self.progress.emit(100)
                self.finished.emit(final_path)
            else:
                if os.path.exists(tmp_path):
                    os.replace(tmp_path, self.save_path)
                    logger.info("Export complete (no re-encode): %s", self.save_path)
                    self.progress.emit(100)
                    self.finished.emit(self.save_path)
                else:
                    self.finished.emit("")

                if audio_tmp_path and os.path.exists(audio_tmp_path):
                    try:
                        os.remove(audio_tmp_path)
                    except OSError:
                        pass

        except Exception as e:
            logger.exception("Export failed")
            self.error.emit(str(e))

    @staticmethod
    def _add_audio(mix, frame_idx, sound_arr, sr, fps):
        if sound_arr is None or len(mix) == 0:
            return
        start_sample = int(sr * frame_idx / fps)
        end_sample = start_sample + len(sound_arr)
        if end_sample > len(mix):
            end_sample = len(mix)
            sound_arr = sound_arr[:end_sample - start_sample]
        if start_sample < len(mix):
            mix[start_sample:end_sample] += sound_arr

    @staticmethod
    def _detect_game_state(board):
        if board.is_checkmate():
            r = "1-0" if board.turn == chess.BLACK else "0-1"
            return GAME_CHECKMATE, r, "Checkmate"
        if board.is_stalemate():
            return GAME_STALEMATE, "½-½", "Stalemate"
        if board.is_insufficient_material():
            return GAME_INSUFFICIENT, "½-½", "Insufficient Material"
        if board.is_repetition(3):
            return GAME_DRAW, "½-½", "Threefold Repetition"
        if board.is_fifty_moves():
            return GAME_DRAW, "½-½", "50-Move Rule"
        if board.is_game_over():
            return GAME_DRAW, "½-½", "Draw"
        return GAME_NORMAL, "", ""

    @staticmethod
    def _reencode_h264(tmp_path, final_path, audio_path=None):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            logger.info("ffmpeg not found — skipping H.264 re-encode")
            return None

        if not os.path.exists(tmp_path):
            return None

        cmd = [ffmpeg, "-y", "-i", tmp_path]

        if audio_path and os.path.exists(audio_path):
            cmd.extend(["-i", audio_path])
            cmd.extend([
                "-map", "0:v", "-map", "1:a",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
            ])
        else:
            cmd.extend([
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p",
            ])

        cmd.extend(["-movflags", "+faststart", final_path])

        logger.info("Re-encoding to H.264: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600
            )
            if result.returncode == 0:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                if audio_path:
                    try:
                        os.remove(audio_path)
                    except OSError:
                        pass
                logger.info("H.264 re-encode successful")
                return final_path
            else:
                logger.warning("ffmpeg failed (rc=%d): %s",
                               result.returncode, result.stderr[:500])
                return None
        except FileNotFoundError:
            logger.warning("ffmpeg not found at runtime")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg timed out")
            return None
        except Exception as e:
            logger.warning("ffmpeg error: %s", e)
            return None

    @staticmethod
    def _qimage_to_bgr_numpy(qimg, buf=None):
        from PySide6.QtGui import QImage
        img = qimg.convertToFormat(QImage.Format_RGB888)
        w, h = img.width(), img.height()
        if w == 0 or h == 0:
            return None
        bpl = img.bytesPerLine()
        ptr = img.bits()

        if hasattr(ptr, 'setsize'):
            ptr.setsize(bpl * h)
            if buf is not None and buf.shape == (h, bpl):
                np.copyto(buf, np.frombuffer(ptr, dtype=np.uint8)[:h * bpl].reshape(h, bpl))
                arr = buf
            else:
                arr = np.array(ptr, dtype=np.uint8).reshape((h, bpl))
        else:
            raw = np.frombuffer(ptr, dtype=np.uint8)
            arr = raw[:h * bpl].reshape((h, bpl))
            if buf is not None and buf.shape == (h, bpl):
                np.copyto(buf, arr)
                arr = buf

        if bpl != w * 3:
            arr = arr[:, :w * 3]

        arr3 = arr[:, :w * 3].reshape((h, w, 3))
        return cv2.cvtColor(arr3, cv2.COLOR_RGB2BGR)

    @staticmethod
    def _qimage_to_rgb_numpy(qimg, buf=None):
        from PySide6.QtGui import QImage
        img = qimg.convertToFormat(QImage.Format_RGB888)
        w, h = img.width(), img.height()
        if w == 0 or h == 0:
            return None
        bpl = img.bytesPerLine()
        ptr = img.bits()

        if hasattr(ptr, 'setsize'):
            ptr.setsize(bpl * h)
            arr = np.array(ptr, dtype=np.uint8).reshape((h, bpl))
        else:
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl))

        if bpl != w * 3:
            arr = arr[:, :w * 3]

        return arr.reshape((h, w, 3)).copy()