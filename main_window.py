"""Chess Video Maker Pro — Main Application Window Logic"""
import io
import os
import glob
import shutil
import tempfile
import logging
from PySide6.QtWidgets import QApplication, QMainWindow, QListWidgetItem, QTableWidgetItem
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap, QImage
import chess
import chess.pgn
from constants import (AI_MAP, THEMES, BoardTheme, HAS_CV2,
                       GAME_NORMAL, GAME_CHECKMATE, GAME_STALEMATE,
                       GAME_DRAW, GAME_INSUFFICIENT,
                       QUALITY_PRESETS, RESOLUTION_SIZES, RESOLUTION_LIST,
                       MAX_FRAMES_IN_MEMORY,
                       get_system_ram_gb, estimate_memory_gb)
from ui_builder import build_ui, build_menu
from workers import AIWorker, BatchEvalWorker, ExportWorker
from widgets import VideoCanvas
from sound_manager import SoundManager
from animation_manager import AnimationManager

if HAS_CV2:
    import numpy as np
    import cv2

logger = logging.getLogger("ChessVideoMaker.MainWindow")

_SOUND_DESIGN_DESC = {
    "Default": "🎵 Default — Standard balanced sound",
    "Warm": "🎸 Warm — Softer tones with reverb and low-frequency warmth",
    "Crisp": "🔔 Crisp — Bright, sharp attack with fast decay",
    "Retro": "🕹️ Retro — 8-bit lo-fi crunch with short punchy sounds",
    "Cinematic": "🎬 Cinematic — Deep, atmospheric with rich reverb",
    "Minimal": "◻️ Minimal — Ultra-subtle, very short and quiet",
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("♟ Chess Video Maker Pro")
        self.setMinimumSize(1350, 850)
        self.resize(1500, 920)

        self.game = None
        self.node = None
        self.move_index = 0
        self.move_list = []
        self._playing = False
        self._anim_timer = QTimer()
        self._anim_timer.setSingleShot(True)
        self._anim_timer.timeout.connect(self._play_step)
        self.engine_worker = None
        self.capture_frames = []       # In-memory QImage list (for preview)
        self._use_disk_cache = False
        self._disk_cache_dir = None    # Temp dir for disk-cached JPEG frames
        self._disk_frame_count = 0
        self.video_bg_color = QColor(30, 30, 32)
        self.db_folder = ""
        self.img_folder = ""
        self.canvas_overlays = []
        self.ai_vs_ai_running = False
        self.ai_battle_worker = None
        self.eval_cache = {}
        self.batch_worker = None
        self.export_worker = None
        self._pending_promo_from = None
        self._pending_promo_to = None
        self._prev_frames = []
        self._prev_idx = 0
        self._prev_playing = False
        self._prev_fps = 30
        self._prev_speed = 1.0
        self._prev_timer = QTimer()
        self._prev_timer.timeout.connect(self._preview_advance)
        self._prev_cap = None
        self._prev_source = None
        self._prev_mp4_count = 0
        self.sound_manager = SoundManager(self)
        self.anim_manager = None
        # Streaming export state
        self._stream_active = False
        self._stream_writer = None
        self._stream_frame_idx = 0
        self._stream_total = 0
        self._stream_batch = 20  # Frames per processEvents() call

        build_ui(self)
        build_menu(self)
        self.promo_widget.piece_selected.connect(self._on_promo_pick)
        self.anim_manager = AnimationManager(
            self.board_widget, self.eval_bar_widget, self)

        self.mp4_output_dir = os.path.join(os.getcwd(), "mp4 files")
        os.makedirs(self.mp4_output_dir, exist_ok=True)
        self.export_path_edit.setText(
            os.path.join(self.mp4_output_dir, "chess_video.mp4"))
        self.output_dir_lbl.setText(f"📁 Output: {self.mp4_output_dir}")

        # Initial memory estimate
        self._update_mem_estimate()
        self._new_game()

    # ── Cleanup ────────────────────────────────────────────────────
    def _cleanup(self):
        self._playing = False
        self._anim_timer.stop()
        self._prev_timer.stop()
        self._prev_playing = False
        self._stream_active = False

        if self.anim_manager:
            self.anim_manager.cancel_all()

        self.ai_vs_ai_running = False
        if self.ai_battle_worker and self.ai_battle_worker.isRunning():
            self.ai_battle_worker.eval_ready.disconnect(self._on_battle_move)
            self.ai_battle_worker.quit()
            self.ai_battle_worker.wait(3000)

        for worker, signal_handler in [
            (self.engine_worker, self._on_eval_ready),
            (self.batch_worker, None),
            (self.export_worker, None),
        ]:
            if worker and worker.isRunning():
                try:
                    if signal_handler:
                        worker.eval_ready.disconnect(signal_handler)
                    elif hasattr(worker, 'move_evaluated'):
                        worker.move_evaluated.disconnect()
                    elif hasattr(worker, 'progress'):
                        worker.progress.disconnect()
                except (RuntimeError, TypeError):
                    pass
                if hasattr(worker, 'cancel'):
                    worker.cancel()
                worker.quit()
                worker.wait(3000)

        self._cleanup_preview()
        self._cleanup_disk_cache()
        self.sound_manager.cleanup()

    # ── Disk Cache Management ──────────────────────────────────────
    def _init_disk_cache(self):
        """Create a temp directory for disk-cached frames."""
        self._cleanup_disk_cache()
        self._disk_cache_dir = tempfile.mkdtemp(prefix="chess_vm_frames_")
        self._disk_frame_count = 0
        self._use_disk_cache = True
        logger.info("Disk cache initialized: %s", self._disk_cache_dir)

    def _cleanup_disk_cache(self):
        """Remove disk cache temp directory."""
        if self._disk_cache_dir and os.path.isdir(self._disk_cache_dir):
            try:
                shutil.rmtree(self._disk_cache_dir, ignore_errors=True)
            except Exception as e:
                logger.warning("Disk cache cleanup error: %s", e)
        self._disk_cache_dir = None
        self._disk_frame_count = 0
        self._use_disk_cache = False

    def _write_frame_to_disk(self, qimage):
        """Write a QImage to disk cache as JPEG. Returns True on success."""
        if not self._disk_cache_dir:
            return False
        try:
            fname = os.path.join(
                self._disk_cache_dir,
                f"frame_{self._disk_frame_count:05d}.jpg")
            qimage.save(fname, "JPEG", 95)
            self._disk_frame_count += 1
            return True
        except Exception as e:
            logger.error("Disk cache write error: %s", e)
            return False

    # ── Memory Estimate ────────────────────────────────────────────
    def _update_mem_estimate(self):
        """Update the memory estimate label based on current settings."""
        try:
            res_str = self.export_res_combo.currentText()
            fps = self.fps_spin.value()
            hold = self.hold_spin.value()
            moves = max(1, len(self.move_list))
            est = estimate_memory_gb(res_str, fps, hold, moves)
            ram = get_system_ram_gb()

            # Determine frame count
            frame_count = max(1, int(hold * fps)) * (moves + 1)

            if est > ram * 0.6:
                color = "#e55"
                note = "⚠️ Exceeds 60% RAM — enable Disk Cache!"
            elif est > ram * 0.3:
                color = "#c90"
                note = "⚠️ Uses >30% RAM — consider Disk Cache"
            else:
                color = "#6b6"
                note = "✅ Comfortable"

            self.mem_estimate_lbl.setText(
                f"~{est:.1f} GB for ~{frame_count} frames  {note}")
            self.mem_estimate_lbl.setStyleSheet(
                f"color:{color};font-size:11px;padding:2px")
        except Exception:
            self.mem_estimate_lbl.setText("Est. memory: —")

    # ── Quality Preset Handler ─────────────────────────────────────
    def _on_quality_preset(self, idx):
        """Apply quality preset settings."""
        if idx < 0:
            return
        preset_name = self.quality_preset_combo.currentData()
        if preset_name not in QUALITY_PRESETS:
            return
        p = QUALITY_PRESETS[preset_name]

        # Block signals while updating to avoid recursion
        self.export_res_combo.blockSignals(True)
        self.export_fps_spin.blockSignals(True)
        self.fps_spin.blockSignals(True)
        self.hold_spin.blockSignals(True)
        self.disk_cache_chk.blockSignals(True)

        self.export_res_combo.setCurrentIndex(p["resolution_index"])
        self.export_fps_spin.setValue(p["fps"])
        self.fps_spin.setValue(p["capture_fps"])
        self.hold_spin.setValue(p["hold"])
        self.disk_cache_chk.setChecked(p["disk_cache"])

        self.export_res_combo.blockSignals(False)
        self.export_fps_spin.blockSignals(False)
        self.fps_spin.blockSignals(False)
        self.hold_spin.blockSignals(False)
        self.disk_cache_chk.blockSignals(False)

        self._use_disk_cache = p["disk_cache"]
        self._update_mem_estimate()

    def _on_disk_cache_toggled(self, checked):
        self._use_disk_cache = checked
        self._update_mem_estimate()

    # ── Core Logic ─────────────────────────────────────────────────
    def _new_game(self):
        self.game = chess.pgn.Game()
        self.node = self.game
        self.move_index = -1
        self.move_list = []
        self.eval_cache = {}
        self.eval_bar_widget.reset_game_state()
        self._refresh_all()
        self.sound_manager.play("new_game")

    def _load_pgn(self):
        self.tabs.setCurrentIndex(1)
        self.pgn_text_edit.setFocus()

    def _load_pgn_text(self):
        t = self.pgn_text_edit.toPlainText().strip()
        if not t:
            return
        try:
            g = chess.pgn.read_game(io.StringIO(t))
            if g:
                self._load_pgn_data(g)
        except Exception as e:
            self.statusBar().showMessage(f"Error: {e}")

    def _load_pgn_from_file(self):
        p = self.pgn_file_edit.text().strip()
        if not p or not os.path.isfile(p):
            return
        try:
            with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                g = chess.pgn.read_game(f)
            if g:
                self._load_pgn_data(g)
        except Exception as e:
            self.statusBar().showMessage(f"Error: {e}")

    def _load_pgn_data(self, g):
        self.game = g
        self.node = g
        self.move_index = -1
        self.eval_cache = {}
        self.move_list = list(g.mainline())
        self._refresh_all()
        self._go_last()
        self.eval_bar_widget.set_eval(0.0)
        self._update_mem_estimate()

    def _refresh_all(self):
        board = self.node.board() if self.node else chess.Board()
        self.board_widget.set_position(board)
        self.eval_bar_widget.set_eval(self.eval_cache.get(self.node, 0.0))
        self._update_game_state(board)
        self._refresh_move_list()

    def _refresh_move_list(self):
        self.move_table.blockSignals(True)
        self.move_table.setRowCount(0)
        for i, n in enumerate(self.move_list):
            b = n.parent.board()
            san = n.san()
            es = ""
            if n in self.eval_cache:
                ev = self.eval_cache[n]
                es = (f" (M{int(abs(ev) - 10000)})" if abs(ev) > 9000
                      else f" ({ev / 100:+.2f})")
            r = i // 2
            is_white = (i % 2 == 0)
            if is_white:
                self.move_table.insertRow(r)
                itn = QTableWidgetItem(str(b.fullmove_number))
                itn.setTextAlignment(Qt.AlignCenter)
                itn.setFlags(itn.flags() & ~Qt.ItemIsEditable)
                self.move_table.setItem(r, 0, itn)
                itw = QTableWidgetItem(f"{san}{es}")
                itw.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                itw.setFlags(itw.flags() & ~Qt.ItemIsEditable)
                self.move_table.setItem(r, 1, itw)
            else:
                itb = QTableWidgetItem(f"{san}{es}")
                itb.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                itb.setFlags(itb.flags() & ~Qt.ItemIsEditable)
                self.move_table.setItem(r, 2, itb)
        if 0 <= self.move_index < len(self.move_list):
            col = 1 if self.move_index % 2 == 0 else 2
            self.move_table.setCurrentCell(self.move_index // 2, col)
        else:
            self.move_table.clearSelection()
        self.move_table.blockSignals(False)

    # ── Game State Detection ───────────────────────────────────────
    def _update_game_state(self, board=None):
        if board is None:
            board = self.node.board() if self.node else chess.Board()

        if board.is_checkmate():
            result = "1-0" if board.turn == chess.BLACK else "0-1"
            ev = self.eval_cache.get(self.node, 0.0)
            if abs(ev) <= 9000:
                ev = 10000.0 if board.turn == chess.BLACK else -10000.0
                self.eval_cache[self.node] = ev
            self.eval_bar_widget.set_eval(ev)
            self.eval_bar_widget.set_game_state(
                GAME_CHECKMATE, result=result, detail="Checkmate")
            self.statusBar().showMessage(
                f"Checkmate! {'White' if board.turn == chess.BLACK else 'Black'} wins — {result}")
            return

        if board.is_stalemate():
            self.eval_bar_widget.set_eval(0.0)
            self.eval_bar_widget.set_game_state(
                GAME_STALEMATE, result="½-½", detail="Stalemate")
            self.statusBar().showMessage("Stalemate — ½-½")
            return

        if board.is_insufficient_material():
            self.eval_bar_widget.set_eval(0.0)
            self.eval_bar_widget.set_game_state(
                GAME_INSUFFICIENT, result="½-½",
                detail="Insufficient Material")
            self.statusBar().showMessage("Draw: Insufficient Material — ½-½")
            return

        if board.is_game_over():
            self.eval_bar_widget.set_eval(0.0)
            self.eval_bar_widget.set_game_state(
                GAME_DRAW, result="½-½", detail="Draw")
            self.statusBar().showMessage("Draw — ½-½")
            return

        self.eval_bar_widget.reset_game_state()

    def _update_board(self, animate=False, move_obj=None):
        board = self.node.board() if self.node else chess.Board()
        lm = self.node.move if self.node and self.node.parent else None
        if animate and move_obj and self.anim_manager.enabled and self.anim_manager.piece_anim:
            self.board_widget.set_position_animated(board, lm)
            self.anim_manager.animate_piece_move(move_obj)
            self.anim_manager.animate_last_move_flash(
                move_obj.from_square, move_obj.to_square)
        else:
            self.board_widget.set_position(board, lm)
        if board.is_check():
            ks = board.king(board.turn)
            if ks is not None and animate:
                self.anim_manager.animate_check(ks)
        self.eval_bar_widget.set_eval(self.eval_cache.get(self.node, 0.0))
        self._update_game_state(board)
        if 0 <= self.move_index < len(self.move_list):
            col = 1 if self.move_index % 2 == 0 else 2
            self.move_table.setCurrentCell(self.move_index // 2, col)

    def _on_move_cell(self, r, c, pr, pc):
        if r < 0:
            return
        mi = r * 2 + (0 if c <= 1 else 1)
        if 0 <= mi < len(self.move_list) and self.move_index != mi:
            self.move_index = mi
            self.node = self.move_list[mi]
            self._update_board()

    def _go_first(self):
        self.node = self.game
        self.move_index = -1
        self._update_board()
        self.sound_manager.play("ui_click")

    def _go_prev(self):
        if self.node and self.node.parent:
            self.node = self.node.parent
            self.move_index = max(-1, self.move_index - 1)
            self._update_board()
            self.sound_manager.play("ui_click")

    def _go_next(self):
        if self.node and self.node.variations:
            mo = self.node.variations[0].move
            self.node = self.node.variations[0]
            self.move_index += 1
            self._update_board(animate=True, move_obj=mo)
            self._play_sound_for_move(self.node)

    def _go_last(self):
        while self.node and self.node.variations:
            self.node = self.node.variations[0]
            self.move_index += 1
        self._update_board()

    def _toggle_play(self):
        self._playing = not self._playing
        self.btn_play.setText("⏸ Pause" if self._playing else "▶ Play")
        if self._playing:
            self._play_step()

    def _play_step(self):
        if not self._playing:
            return
        if self.node and self.node.variations:
            self._go_next()
            QTimer.singleShot(
                int(3000 / self.speed_slider.value()), self._play_step)
        else:
            self._playing = False
            self.btn_play.setText("▶ Play")

    def _play_sound_for_move(self, node):
        if not node or not node.parent:
            return
        b = node.board()
        m = node.move
        pb = node.parent.board()
        if b.is_checkmate():
            self.sound_manager.play("checkmate")
            return
        pc = pb.piece_at(m.from_square)
        if (pc and pc.piece_type == chess.KING and
                abs(chess.square_file(m.from_square) -
                    chess.square_file(m.to_square)) == 2):
            self.sound_manager.play("castle")
            return
        if m.promotion:
            self.sound_manager.play("promotion")
            return
        if pb.is_capture(m):
            self.sound_manager.play("capture")
            if b.is_check():
                QTimer.singleShot(80, lambda: self.sound_manager.play("check"))
            return
        if b.is_check():
            self.sound_manager.play("check")
            return
        self.sound_manager.play("move")

    # ── Board Interaction ──────────────────────────────────────────
    def _on_sq_click(self, sq):
        if self.ai_vs_ai_running:
            return
        b = self.board_widget.board

        if self.board_widget.selected_sq is None:
            if b.piece_at(sq) and b.piece_at(sq).color == b.turn:
                self.board_widget.selected_sq = sq
                self.board_widget.legal_targets = [
                    m.to_square for m in b.legal_moves if m.from_square == sq
                ]
                self.board_widget.update()
                self.sound_manager.play("ui_click")
        else:
            fs = self.board_widget.selected_sq
            mv = chess.Move(fs, sq)

            promo_ranks = {chess.A8, chess.B8, chess.C8, chess.D8,
                           chess.E8, chess.F8, chess.G8, chess.H8,
                           chess.A1, chess.B1, chess.C1, chess.D1,
                           chess.E1, chess.F1, chess.G1, chess.H1}
            if (b.piece_at(fs) and b.piece_at(fs).piece_type == chess.PAWN
                    and sq in promo_ranks):
                tm = chess.Move(fs, sq, promotion=chess.QUEEN)
                if tm in b.legal_moves:
                    self._pending_promo_from = fs
                    self._pending_promo_to = sq
                    self.promo_widget.show_for_color(b.turn)
                    self.board_widget.selected_sq = None
                    self.board_widget.legal_targets = []
                    self.board_widget.update()
                    return

            if mv in b.legal_moves:
                self.node = self.node.add_variation(mv)
                self.move_list = list(self.game.mainline())
                self.move_index += 1
                self.board_widget.selected_sq = None
                self.board_widget.legal_targets = []
                self._update_board(animate=True, move_obj=mv)
                self._refresh_move_list()
                self._play_sound_for_move(self.node)
                self._update_mem_estimate()
            else:
                self.board_widget.selected_sq = None
                self.board_widget.legal_targets = []
                self.board_widget.update()
                self.sound_manager.play("illegal")

    def _on_promo_pick(self, pt):
        if self._pending_promo_from is not None and self._pending_promo_to is not None:
            b = self.board_widget.board
            mv = chess.Move(self._pending_promo_from, self._pending_promo_to,
                            promotion=pt)
            if mv in b.legal_moves:
                self.node = self.node.add_variation(mv)
                self.move_list = list(self.game.mainline())
                self.move_index += 1
                self._update_board(animate=True, move_obj=mv)
                self._refresh_move_list()
                self._play_sound_for_move(self.node)
            else:
                self.sound_manager.play("illegal")
            self._pending_promo_from = None
            self._pending_promo_to = None
        self.promo_widget.hide()

    # ── Handlers ───────────────────────────────────────────────────
    def _flip_board(self):
        self.board_widget.flipped = not self.board_widget.flipped
        self.board_widget.update()
        self.sound_manager.play("ui_click")

    def _theme_changed(self, t):
        self.board_widget.set_theme(THEMES.get(t, BoardTheme()))

    def _apply_comment(self):
        if self.node:
            self.node.comment = self.anno_edit.toPlainText()

    def _pick_bg_color(self, n):
        cm = {
            "Dark Gray": QColor(30, 30, 32), "Black": QColor(0, 0, 0),
            "Dark Blue": QColor(15, 20, 40), "Dark Green": QColor(15, 35, 15),
            "Dark Red": QColor(40, 15, 15), "White": QColor(255, 255, 255),
            "Light Gray": QColor(200, 200, 200), "Navy": QColor(0, 0, 80),
        }
        self.video_bg_color = cm.get(n, QColor(30, 30, 32))

    def _update_names(self):
        pass

    def _clear_policy(self):
        self.board_widget.policy_vis = {}
        self.board_widget.update()

    # ── Settings Handlers ──────────────────────────────────────────
    def _on_sound_enabled(self, e):
        self.sound_manager.set_enabled(e)

    def _on_sound_vol(self, v):
        self.sound_manager.set_volume(v / 100.0)
        self.sound_vol_lbl.setText(f"{v}%")

    def _on_sound_theme(self, t):
        self.sound_manager.set_theme(t)

    def _on_sound_design(self, d):
        self.sound_manager.set_design(d)
        desc = _SOUND_DESIGN_DESC.get(d, f"🎵 {d}")
        self.sound_design_desc.setText(desc)

    def _on_snd_type_vol(self, t, v):
        self.sound_manager.set_type_volume(t, v)

    def _test_sound(self, t):
        self.sound_manager.play(t)

    def _on_anim_enabled(self, e):
        self.anim_manager.enabled = e

    def _on_piece_anim(self, e):
        self.anim_manager.set_piece_anim(e)

    def _on_highlight_anim(self, e):
        self.anim_manager.set_highlight_anim(e)

    def _on_eval_anim(self, e):
        self.anim_manager.set_eval_anim(e)

    def _on_anim_dur(self, ms):
        self.anim_manager.set_duration(ms)

    def _on_anim_ease(self, n):
        self.anim_manager.set_easing(n)

    # ── Preview ────────────────────────────────────────────────────
    def _preview_captured_frames(self):
        if self._use_disk_cache and self._disk_cache_dir:
            self._preview_from_disk()
            return
        if not self.capture_frames:
            return
        self._stop_preview()
        if self._prev_cap:
            self._prev_cap.release()
            self._prev_cap = None
        self._prev_frames = list(self.capture_frames)
        self._prev_fps = self.fps_spin.value()
        self._prev_source = 'frames'
        self._prev_idx = 0
        self.preview_slider.setRange(0, max(0, len(self._prev_frames) - 1))
        self._refresh_prev_ctrl()
        if self._prev_frames:
            self._show_prev_frame(0)

    def _preview_from_disk(self):
        """Preview frames from disk cache — load a sampled subset."""
        if not HAS_CV2 or not self._disk_cache_dir:
            return
        self._stop_preview()
        if self._prev_cap:
            self._prev_cap.release()
            self._prev_cap = None
        # Load sampled frames for preview (every Nth frame, max 300)
        step = max(1, self._disk_frame_count // 300)
        frames = []
        for i in range(0, self._disk_frame_count, step):
            fname = os.path.join(self._disk_cache_dir, f"frame_{i:05d}.jpg")
            if os.path.isfile(fname):
                qimg = QImage(fname)
                if not qimg.isNull():
                    frames.append(qimg)
        if not frames:
            self.statusBar().showMessage("No frames to preview")
            return
        self._prev_frames = frames
        self._prev_fps = self.fps_spin.value()
        self._prev_source = 'frames'
        self._prev_idx = 0
        self.preview_slider.setRange(0, max(0, len(self._prev_frames) - 1))
        self._refresh_prev_ctrl()
        self._show_prev_frame(0)

    def _preview_mp4(self):
        if not HAS_CV2:
            return
        p = (self.preview_mp4_path.text().strip()
             or self.export_path_edit.text().strip())
        if not p or not os.path.isfile(p):
            return
        self._stop_preview()
        if self._prev_cap:
            self._prev_cap.release()
            self._prev_cap = None
        self._prev_cap = cv2.VideoCapture(p)
        if not self._prev_cap.isOpened():
            return
        self._prev_source = 'mp4'
        self._prev_frames = []
        self._prev_mp4_count = (
            int(self._prev_cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1)
        self._prev_fps = max(
            1, int(self._prev_cap.get(cv2.CAP_PROP_FPS)) or 30)
        self._prev_idx = 0
        self.preview_slider.setRange(0, max(0, self._prev_mp4_count - 1))
        self._refresh_prev_ctrl()
        self._show_prev_mp4(0)

    def _stop_preview(self):
        self._prev_playing = False
        self._prev_timer.stop()
        self.preview_play_btn.setText("▶")
        self._prev_idx = 0
        self.preview_slider.setValue(0)
        self._show_cur_prev()
        self._update_prev_lbl()

    def _refresh_prev_ctrl(self):
        t = self._prev_total()
        ok = t > 0
        self.preview_play_btn.setEnabled(ok)
        self.preview_stop_btn.setEnabled(ok)
        self._update_prev_lbl()

    def _prev_total(self):
        if self._prev_source == 'frames':
            return len(self._prev_frames)
        if self._prev_source == 'mp4':
            return self._prev_mp4_count
        return 0

    def _update_prev_lbl(self):
        n = self._prev_total()
        if n > 0:
            s = self._prev_idx / self._prev_fps
            m, ss = divmod(s, 60)
            self.preview_time_lbl.setText(
                f"{self._prev_idx + 1}/{n} {int(m)}:{ss:04.1f}")
        else:
            self.preview_time_lbl.setText("0/0")

    def _update_preview_speed(self, i):
        sp = [0.5, 1.0, 2.0, 4.0]
        self._prev_speed = sp[i] if 0 <= i < len(sp) else 1.0
        if self._prev_playing:
            self._prev_timer.setInterval(
                max(1, int(1000 / (self._prev_fps * self._prev_speed))))

    def _toggle_preview_play(self):
        if self._prev_playing:
            self._prev_playing = False
            self._prev_timer.stop()
            self.preview_play_btn.setText("▶")
        else:
            if self._prev_total() <= 0:
                return
            if self._prev_idx >= self._prev_total() - 1:
                self._prev_idx = 0
                self.preview_slider.setValue(0)
                self._show_cur_prev()
            self._prev_playing = True
            self.preview_play_btn.setText("⏸")
            self._prev_timer.start(
                max(1, int(1000 / (self._prev_fps * self._prev_speed))))

    def _preview_advance(self):
        if self._prev_idx >= self._prev_total() - 1:
            self._prev_playing = False
            self._prev_timer.stop()
            self.preview_play_btn.setText("▶")
            return
        self._prev_idx += 1
        self.preview_slider.setValue(self._prev_idx)
        self._show_cur_prev()
        self._update_prev_lbl()

    def _show_cur_prev(self):
        if self._prev_source == 'frames':
            self._show_prev_frame(self._prev_idx)
        elif self._prev_source == 'mp4':
            self._show_prev_mp4(self._prev_idx)

    def _show_prev_frame(self, idx):
        if 0 <= idx < len(self._prev_frames):
            pm = QPixmap.fromImage(self._prev_frames[idx])
            sz = self.preview_display.size()
            if sz.isValid() and not sz.isEmpty():
                self.preview_display.setPixmap(
                    pm.scaled(sz, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.preview_display.setPixmap(pm)

    def _show_prev_mp4(self, idx):
        if not HAS_CV2 or not self._prev_cap or not self._prev_cap.isOpened():
            return
        self._prev_cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, f = self._prev_cap.read()
        if ret:
            rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
            h, w, c = rgb.shape
            qi = QImage(rgb.data, w, h, c * w,
                        QImage.Format_RGB888).copy()
            pm = QPixmap.fromImage(qi)
            sz = self.preview_display.size()
            if sz.isValid():
                self.preview_display.setPixmap(
                    pm.scaled(sz, Qt.KeepAspectRatio,
                              Qt.SmoothTransformation))
            else:
                self.preview_display.setPixmap(pm)

    def _scrub_preview(self, v):
        self._prev_idx = v
        self._show_cur_prev()
        self._update_prev_lbl()

    def _cleanup_preview(self):
        self._stop_preview()
        if HAS_CV2 and self._prev_cap is not None:
            self._prev_cap.release()
            self._prev_cap = None
        self._prev_frames = []

    # ── DB & Assets ────────────────────────────────────────────────
    def _set_pgn_db_folder(self):
        d = self.db_folder_edit.text().strip()
        if d and os.path.isdir(d):
            self._set_db(d)
        else:
            self.statusBar().showMessage("Invalid path")

    def _set_db(self, d):
        self.db_folder = d
        self.db_path_lbl.setText(f"Folder: {d}")
        self._scan_pgn_db()

    def _scan_pgn_db(self):
        if not self.db_folder:
            return
        self.db_list.clear()
        for f in glob.glob(os.path.join(self.db_folder, "**/*.pgn"),
                           recursive=True):
            self.db_list.addItem(os.path.basename(f))

    def _load_selected_pgn_db(self, item=None):
        if not item and not self.db_list.currentItem():
            return
        fn = (item.text() if item else self.db_list.currentItem().text())
        fp = os.path.join(self.db_folder, fn)
        gi = self.db_game_idx.value() - 1
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                g = None
                for i in range(gi + 1):
                    g = chess.pgn.read_game(f)
                    if g is None:
                        break
                if g:
                    self._load_pgn_data(g)
        except Exception as e:
            self.statusBar().showMessage(f"Error: {e}")

    def _set_img_folder(self):
        d = self.img_folder_edit.text().strip()
        if d and os.path.isdir(d):
            self._set_im(d)
        else:
            self.statusBar().showMessage("Invalid path")

    def _set_im(self, d):
        self.img_folder = d
        self.img_path_lbl.setText(f"Folder: {d}")
        self._scan_img_db()
    
    def _scan_img_db(self):
        if not self.img_folder:
            return
        self.img_list.clear()
        for e in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif"):
            for f in (glob.glob(os.path.join(self.img_folder, e))
                      + glob.glob(os.path.join(self.img_folder, "**", e),
                                  recursive=True)):
                it = QListWidgetItem(QIcon(f), os.path.basename(f))
                it.setData(Qt.UserRole, f)
                self.img_list.addItem(it)

    def _add_overlay(self):
        it = self.img_list.currentItem()
        if not it:
            return
        p = it.data(Qt.UserRole)
        pos = self.ov_pos_combo.currentText()
        ov = {"path": p, "w": 150, "h": 150}
        if "White" in pos:
            ov["x"], ov["y"] = 50, 850
        elif "Black" in pos:
            ov["x"], ov["y"] = 50, 50
        elif "Center" in pos:
            ov["x"], ov["y"] = 960 - 75, 540 - 75
        elif "Watermark" in pos:
            ov["x"], ov["y"] = 1750, 1000
        else:
            ov["x"], ov["y"] = 100, 100
        self.canvas_overlays.append(ov)

    def _clear_overlays(self):
        self.canvas_overlays = []

    # ── AI ─────────────────────────────────────────────────────────
    def _toggle_ai_ui(self, t):
        idx = list(AI_MAP.values()).index(t) if t in AI_MAP.values() else 0
        self.ai_stack.setCurrentIndex(idx)

    def _run_engine(self):
        et = self.ai_combo.currentText()
        pa = {}
        if et == "Minimax (Alpha-Beta)":
            pa["depth"] = self.mm_depth.value()
        elif et == "MCTS (Monte Carlo)":
            pa["iterations"] = self.m_iters.value()
        elif et == "Stockfish (UCI)":
            pa["path"] = self.engine_path_edit.text()
        self.engine_worker = AIWorker(et, self.board_widget.board.fen(), pa)
        self.engine_worker.eval_ready.connect(self._on_eval_ready)
        self.engine_worker.start()
        self.run_ai_btn.setEnabled(False)
        self.eval_label.setText("Eval: …")

    def _on_eval_ready(self, d):
        self.run_ai_btn.setEnabled(True)
        self.eval_label.setText(f"Eval: {d['eval']}")
        self.pv_label.setText(f"Nodes: {d['nodes']}")

        if self.policy_chk.isChecked() and d.get("policy"):
            self.board_widget.policy_vis = d["policy"]
            self.board_widget.update()

        if d.get("best_move"):
            try:
                mv = chess.Move.from_uci(d["best_move"])
                new_arrow = (mv.from_square, mv.to_square,
                             QColor(220, 50, 47, 200))
                if self.board_widget.arrows:
                    self.board_widget.arrows[0] = new_arrow
                else:
                    self.board_widget.arrows.append(new_arrow)
                self.board_widget.update()
            except Exception:
                pass

    def _start_batch_eval(self):
        if not self.move_list:
            return
        et = self.ai_combo.currentText()
        pa = {}
        if et == "Minimax (Alpha-Beta)":
            pa["depth"] = self.mm_depth.value()
        elif et == "MCTS (Monte Carlo)":
            pa["iterations"] = self.m_iters.value()
        elif et == "Stockfish (UCI)":
            pa["path"] = self.engine_path_edit.text()
        self.batch_worker = BatchEvalWorker(self.move_list, et, pa)
        self.batch_worker.move_evaluated.connect(self._on_move_eval)
        self.batch_worker.batch_finished.connect(self._on_batch_finished)
        self.eval_game_btn.setEnabled(False)
        self.stop_eval_btn.setEnabled(True)
        self.batch_worker.start()

    def _on_move_eval(self, i, ev, es):
        if 0 <= i < len(self.move_list):
            self.eval_cache[self.move_list[i]] = ev
        self._refresh_move_list()
        if self.node == self.move_list[i]:
            self.eval_bar_widget.set_eval(ev)

    def _on_batch_finished(self):
        self.eval_game_btn.setEnabled(True)
        self.stop_eval_btn.setEnabled(False)

    def _stop_batch_eval(self):
        if self.batch_worker:
            self.batch_worker.cancel()

    # ── AI Battle ──────────────────────────────────────────────────
    def _start_ai_vs_ai(self):
        if self.ai_vs_ai_running:
            return
        self._new_game()
        self.ai_vs_ai_running = True
        self.start_battle_btn.setEnabled(False)
        self.stop_battle_btn.setEnabled(True)
        self.auto_mp4_chk.setEnabled(False)
        self.save_png_chk.setEnabled(False)
        self._ai_battle_step()

    def _ai_battle_step(self):
        if not self.ai_vs_ai_running:
            return
        b = self.board_widget.board
        if b.is_game_over():
            self._stop_ai_vs_ai()
            self.statusBar().showMessage(f"Game Over: {b.result()}")
            return

        et = (self.white_ai_combo.currentText() if b.turn == chess.WHITE
              else self.black_ai_combo.currentText())
        st = (self.white_ai_str.value() if b.turn == chess.WHITE
              else self.black_ai_str.value())
        pa = {}
        if et == "Minimax (Alpha-Beta)":
            pa["depth"] = st
        elif et == "MCTS (Monte Carlo)":
            pa["iterations"] = st
        elif et == "Stockfish (UCI)":
            pa["path"] = self.engine_path_edit.text()
        self.ai_battle_worker = AIWorker(et, b.fen(), pa)
        self.ai_battle_worker.eval_ready.connect(self._on_battle_move)
        self.ai_battle_worker.start()

    def _on_battle_move(self, d):
        if not self.ai_vs_ai_running:
            return
        bu = d.get("best_move")
        if bu:
            try:
                mv = chess.Move.from_uci(bu)
                if mv in self.board_widget.board.legal_moves:
                    self.node = self.node.add_variation(mv)
                    self.move_list = list(self.game.mainline())
                    self.move_index += 1
                    self._update_board(animate=True, move_obj=mv)
                    self._refresh_move_list()
                    self.eval_cache[self.node] = d.get("eval_cp", 0.0)
                    self.eval_bar_widget.set_eval(d.get("eval_cp", 0.0))
                    self._play_sound_for_move(self.node)
            except Exception:
                logger.warning("Invalid battle move: %s", bu)

        QTimer.singleShot(self.battle_delay.value(), self._ai_battle_step)

    def _stop_ai_vs_ai(self):
        self.ai_vs_ai_running = False
        self.start_battle_btn.setEnabled(True)
        self.stop_battle_btn.setEnabled(False)
        self.auto_mp4_chk.setEnabled(True)
        self.save_png_chk.setEnabled(True)
        if self.ai_battle_worker and self.ai_battle_worker.isRunning():
            self.ai_battle_worker.quit()
        self._update_game_state()
        if self.auto_mp4_chk.isChecked() or self.save_png_chk.isChecked():
            self._auto_export()

    def _auto_export(self):
        dm = self.auto_mp4_chk.isChecked()
        dp = self.save_png_chk.isChecked()
        if not dm and not dp:
            return
        self.statusBar().showMessage("🎬 Rendering…")
        QApplication.processEvents()
        self._auto_capture()
        if dp:
            self._save_png()
        if dm and HAS_CV2 and (self.capture_frames or self._disk_frame_count > 0):
            self.export_path_edit.setText(
                os.path.join(self.mp4_output_dir, "chess_battle.mp4"))
            self._start_inline_export()

    def _save_png(self):
        if self._use_disk_cache:
            self._save_png_from_disk()
            return
        if not self.capture_frames:
            return
        pd = os.path.join(self.mp4_output_dir, "png_frames")
        os.makedirs(pd, exist_ok=True)
        fps = self.fps_spin.value()
        hf = max(1, int(self.hold_spin.value() * fps))
        tot = len(self.capture_frames)
        sv = 0
        idx = min(hf - 1, tot - 1)
        self.capture_frames[idx].save(
            os.path.join(pd, "move_000_start.png"))
        sv += 1
        mn = 1
        pos = hf
        while pos < tot:
            idx = min(pos + hf - 1, tot - 1)
            self.capture_frames[idx].save(
                os.path.join(pd, f"move_{mn:03d}.png"))
            sv += 1
            mn += 1
            pos += hf
        self.statusBar().showMessage(f"🖼 Saved {sv} PNGs")

    def _save_png_from_disk(self):
        """Save sampled PNGs from disk cache."""
        if self._disk_frame_count == 0 or not self._disk_cache_dir:
            return
        pd = os.path.join(self.mp4_output_dir, "png_frames")
        os.makedirs(pd, exist_ok=True)
        fps = self.fps_spin.value()
        hf = max(1, int(self.hold_spin.value() * fps))
        sv = 0
        idx = min(hf - 1, self._disk_frame_count - 1)
        src = os.path.join(self._disk_cache_dir, f"frame_{idx:05d}.jpg")
        if os.path.isfile(src):
            QImage(src).save(os.path.join(pd, "move_000_start.png"))
            sv += 1
        mn = 1
        pos = hf
        while pos < self._disk_frame_count:
            idx = min(pos + hf - 1, self._disk_frame_count - 1)
            src = os.path.join(self._disk_cache_dir, f"frame_{idx:05d}.jpg")
            if os.path.isfile(src):
                QImage(src).save(os.path.join(pd, f"move_{mn:03d}.png"))
                sv += 1
            mn += 1
            pos += hf
        self.statusBar().showMessage(f"🖼 Saved {sv} PNGs")

    # ── Capture & Export ───────────────────────────────────────────
    def _should_use_disk_cache(self, estimated_frames):
        """Determine whether to use disk cache based on settings & memory."""
        if self._use_disk_cache:
            return True
        # Auto-enable if frame count exceeds threshold
        if estimated_frames > MAX_FRAMES_IN_MEMORY:
            logger.info("Auto-enabling disk cache: %d frames > %d threshold",
                        estimated_frames, MAX_FRAMES_IN_MEMORY)
            return True
        return False

    def _auto_capture(self):
        """Capture all frames for the game — either in memory or on disk."""
        self.capture_frames.clear()
        self._cleanup_disk_cache()

        if not self.move_list:
            return

        # Estimate frame count
        fps = self.fps_spin.value()
        hf = int(self.hold_spin.value() * fps)
        estimated = hf * (len(self.move_list) + 1)
        use_disk = self._should_use_disk_cache(estimated)

        if use_disk:
            self._init_disk_cache()
            self.statusBar().showMessage(
                f"🎬 Capturing {estimated} frames → disk cache (low RAM mode)…")
        else:
            self.statusBar().showMessage(
                f"🎬 Capturing {estimated} frames → memory…")
        QApplication.processEvents()

        saved_node = self.node
        saved_index = self.move_index

        self._go_first()
        cv = VideoCanvas(self.board_widget, self.eval_bar_widget,
                         bg_color=self.video_bg_color)
        cv.white_name = self.white_name_edit.text()
        cv.black_name = self.black_name_edit.text()
        cv.move_list_text = [n.san() for n in self.move_list]
        cv.overlays = self.canvas_overlays

        cv.eval_cp = self.eval_cache.get(self.node, 0.0)
        cv.current_move_index = -1
        cv.game_state = GAME_NORMAL

        # Starting position frames
        for _ in range(hf):
            img = cv.render()
            if use_disk:
                self._write_frame_to_disk(img)
            else:
                self.capture_frames.append(img)

        # Per-move frames
        for i, n in enumerate(self.move_list):
            self.node = n
            self.move_index = i
            self._update_board()
            cv.eval_cp = self.eval_cache.get(self.node, 0.0)

            board = self.node.board() if self.node else chess.Board()
            if board.is_checkmate():
                result = "1-0" if board.turn == chess.BLACK else "0-1"
                cv.game_state = GAME_CHECKMATE
                cv.game_result = result
                cv.game_detail = "Checkmate"
            elif board.is_stalemate():
                cv.game_state = GAME_STALEMATE
                cv.game_result = "½-½"
                cv.game_detail = "Stalemate"
            elif board.is_insufficient_material():
                cv.game_state = GAME_INSUFFICIENT
                cv.game_result = "½-½"
                cv.game_detail = "Insufficient Material"
            elif board.is_game_over():
                cv.game_state = GAME_DRAW
                cv.game_result = "½-½"
                cv.game_detail = "Draw"
            else:
                cv.game_state = GAME_NORMAL
                cv.game_result = ""
                cv.game_detail = ""

            if n.parent:
                b = n.parent.board()
                cv.move_text = (
                    f"{b.fullmove_number}. {n.san()}"
                    if b.turn == chess.WHITE
                    else f"{b.fullmove_number}... {n.san()}")
            cv.current_move_index = i

            extra = hf * 3 if cv.game_state != GAME_NORMAL else 0
            total_hold = hf + extra
            for _ in range(total_hold):
                img = cv.render()
                if use_disk:
                    self._write_frame_to_disk(img)
                else:
                    self.capture_frames.append(img)

            # Update progress periodically
            if i % 10 == 0:
                QApplication.processEvents()

        total = self._disk_frame_count if use_disk else len(self.capture_frames)
        self.frame_count_lbl.setText(f"Frames: {total}")

        # Restore the user's original position
        self.node = saved_node
        self.move_index = saved_index
        self._update_board()

        if use_disk:
            self._preview_from_disk()
        else:
            self._preview_captured_frames()

    def _clear_frames(self):
        self.capture_frames = []
        self._cleanup_disk_cache()
        self.frame_count_lbl.setText("Frames: 0")
        self._cleanup_preview()

    def _start_inline_export(self):
        """Standard export — uses in-memory frames or disk cache."""
        try:
            if not HAS_CV2:
                self.export_status_lbl.setText("ERROR: OpenCV not available")
                return

            # Determine source
            has_memory = bool(self.capture_frames)
            has_disk = (self._disk_cache_dir is not None and
                        self._disk_frame_count > 0)

            if not has_memory and not has_disk:
                self.export_status_lbl.setText("ERROR: No frames to export")
                return

            res_str = self.export_res_combo.currentText()
            w, h = RESOLUTION_SIZES.get(res_str, (1920, 1080))
            fps = self.export_fps_spin.value()
            out = self.export_path_edit.text().strip()
            if not out:
                self.export_status_lbl.setText("ERROR: No output path")
                return
            dirname = os.path.dirname(out)
            if dirname:
                os.makedirs(dirname, exist_ok=True)

            # Prepare numpy frames (only if in-memory)
            npf = []
            if has_memory:
                for fi, f in enumerate(self.capture_frames):
                    try:
                        if f.isNull():
                            logger.warning("Skipping null frame %d", fi)
                            continue
                        arr = self._qimage_to_numpy(f)
                        if arr is not None:
                            npf.append(arr)
                        else:
                            logger.warning("Skipping frame %d: conversion None", fi)
                    except Exception as e:
                        logger.error("Frame %d conversion error: %s", fi, e)
                        continue

                if not npf and not has_disk:
                    self.export_status_lbl.setText(
                        f"ERROR: No valid frames (out of {len(self.capture_frames)})")
                    self.export_start_btn.setEnabled(True)
                    self.export_cancel_btn.setEnabled(False)
                    return

            self.export_worker = ExportWorker(
                npf, fps, out, w, h,
                frame_dir=self._disk_cache_dir if has_disk else None)
            self.export_worker.progress.connect(self._on_export_prog)
            self.export_worker.export_finished.connect(self._on_export_done)
            self.export_start_btn.setEnabled(False)
            self.export_cancel_btn.setEnabled(True)
            self.export_status_lbl.setText("Exporting...")
            self.export_worker.start()

        except Exception as e:
            logger.error("Export error: %s", e)
            self.export_status_lbl.setText(f"ERROR: {e}")
            self.export_start_btn.setEnabled(True)
            self.export_cancel_btn.setEnabled(False)

    # ── Streaming Export (Constant Memory) ─────────────────────────
    def _start_streaming_export(self):
        """Render and export in a single pass with constant memory.

        No preview needed — frames are rendered one at a time and
        written directly to the video file. Ideal for low-RAM systems.
        """
        if not HAS_CV2:
            self.export_status_lbl.setText("ERROR: OpenCV not available")
            return
        if not self.move_list:
            self.export_status_lbl.setText("ERROR: No moves to export")
            return

        res_str = self.export_res_combo.currentText()
        w, h = RESOLUTION_SIZES.get(res_str, (1920, 1080))
        fps = self.export_fps_spin.value()
        out = self.export_path_edit.text().strip()
        if not out:
            self.export_status_lbl.setText("ERROR: No output path")
            return
        dirname = os.path.dirname(out)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        # Try codecs
        cs = [("avc1", ".mp4"), ("X264", ".mp4"), ("mp4v", ".mp4"),
              ("XVID", ".avi")]
        wr = None
        uc = None
        for fc, ext in cs:
            if not out.lower().endswith(ext):
                out = os.path.splitext(out)[0] + ext
            wr = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*fc),
                                 fps, (w, h))
            if wr.isOpened():
                uc = fc
                break
            wr.release()
            wr = None

        if not wr:
            self.export_status_lbl.setText("ERROR: Codec not found")
            return

        self._stream_writer = wr
        self._stream_output = out
        self._stream_codec = uc
        self._stream_w = w
        self._stream_h = h
        self._stream_fps = fps
        self._stream_active = True
        self._stream_frame_idx = 0

        self.export_start_btn.setEnabled(False)
        self.stream_export_btn.setEnabled(False)
        self.export_cancel_btn.setEnabled(True)
        self.export_status_lbl.setText("🚀 Streaming export…")

        # Save state
        self._stream_saved_node = self.node
        self._stream_saved_index = self.move_index

        self._go_first()
        self._stream_cv = VideoCanvas(
            self.board_widget, self.eval_bar_widget,
            w=w, h=h, bg_color=self.video_bg_color)
        self._stream_cv.white_name = self.white_name_edit.text()
        self._stream_cv.black_name = self.black_name_edit.text()
        self._stream_cv.move_list_text = [n.san() for n in self.move_list]
        self._stream_cv.overlays = self.canvas_overlays
        self._stream_cv.eval_cp = self.eval_cache.get(self.node, 0.0)
        self._stream_cv.current_move_index = -1
        self._stream_cv.game_state = GAME_NORMAL

        # Calculate total frames for progress
        hold_fps = self.fps_spin.value()
        hf = int(self.hold_spin.value() * hold_fps)
        self._stream_total = hf * (len(self.move_list) + 1)
        # Account for extra game-end frames (rough estimate)
        self._stream_total += hf * 3  # At most one game-end

        self._stream_hold_fps = hold_fps
        self._stream_hf = hf
        self._stream_move_idx = -1  # -1 = starting position, 0+ = moves

        # Start rendering
        self._stream_render_step()

    def _stream_render_step(self):
        """Render a batch of frames and write them to the video writer.
        Uses QTimer to yield to the event loop periodically."""
        if not self._stream_active:
            self._finish_streaming_export(cancelled=True)
            return

        wr = self._stream_writer
        cv = self._stream_cv
        batch = self._stream_batch
        written = 0

        for _ in range(batch):
            if not self._stream_active:
                break

            # Determine what to render
            if self._stream_move_idx == -1:
                # Still rendering starting position frames
                img = cv.render()
                self._stream_write_frame(img)
                self._stream_frame_idx += 1
                written += 1

                if self._stream_frame_idx >= self._stream_hf:
                    # Move to first move
                    if self.move_list:
                        self._stream_move_idx = 0
                        n = self.move_list[0]
                        self.node = n
                        self.move_index = 0
                        self._update_board()
                        self._stream_update_canvas(cv, 0)
                        self._stream_frame_in_move = 0
                        # Check game state for extra hold
                        board = self.node.board()
                        extra = self._stream_hf * 3 if self._is_game_end(board) else 0
                        self._stream_move_total = self._stream_hf + extra
                    else:
                        self._finish_streaming_export()
                        return
            else:
                # Rendering frames for current move
                img = cv.render()
                self._stream_write_frame(img)
                self._stream_frame_idx += 1
                self._stream_frame_in_move += 1
                written += 1

                if self._stream_frame_in_move >= self._stream_move_total:
                    # Move to next move
                    self._stream_move_idx += 1
                    if self._stream_move_idx >= len(self.move_list):
                        self._finish_streaming_export()
                        return
                    n = self.move_list[self._stream_move_idx]
                    self.node = n
                    self.move_index = self._stream_move_idx
                    self._update_board()
                    self._stream_update_canvas(
                        cv, self._stream_move_idx)
                    self._stream_frame_in_move = 0
                    board = self.node.board()
                    extra = self._stream_hf * 3 if self._is_game_end(board) else 0
                    self._stream_move_total = self._stream_hf + extra

        # Update progress
        if self._stream_total > 0:
            pct = min(99, int(self._stream_frame_idx / self._stream_total * 100))
            self.export_progress_bar.setValue(pct)
            self.export_status_lbl.setText(
                f"🚀 Frame {self._stream_frame_idx}/{self._stream_total}")

        # Yield to event loop, then continue
        if self._stream_active:
            QTimer.singleShot(0, self._stream_render_step)

    def _stream_update_canvas(self, cv, move_idx):
        """Update the VideoCanvas state for streaming export."""
        n = self.move_list[move_idx]
        cv.eval_cp = self.eval_cache.get(self.node, 0.0)

        board = self.node.board()
        if board.is_checkmate():
            result = "1-0" if board.turn == chess.BLACK else "0-1"
            cv.game_state = GAME_CHECKMATE
            cv.game_result = result
            cv.game_detail = "Checkmate"
        elif board.is_stalemate():
            cv.game_state = GAME_STALEMATE
            cv.game_result = "½-½"
            cv.game_detail = "Stalemate"
        elif board.is_insufficient_material():
            cv.game_state = GAME_INSUFFICIENT
            cv.game_result = "½-½"
            cv.game_detail = "Insufficient Material"
        elif board.is_game_over():
            cv.game_state = GAME_DRAW
            cv.game_result = "½-½"
            cv.game_detail = "Draw"
        else:
            cv.game_state = GAME_NORMAL
            cv.game_result = ""
            cv.game_detail = ""

        if n.parent:
            b = n.parent.board()
            cv.move_text = (
                f"{b.fullmove_number}. {n.san()}"
                if b.turn == chess.WHITE
                else f"{b.fullmove_number}... {n.san()}")
        cv.current_move_index = move_idx

    @staticmethod
    def _is_game_end(board):
        return (board.is_checkmate() or board.is_stalemate() or
                board.is_insufficient_material() or board.is_game_over())

    def _stream_write_frame(self, qimage):
        """Convert QImage to BGR numpy and write to the streaming writer."""
        if not HAS_CV2 or self._stream_writer is None:
            return
        try:
            arr = self._qimage_to_numpy(qimage)
            if arr is None:
                return
            # Resize if needed
            if arr.shape[:2] != (self._stream_h, self._stream_w):
                arr = cv2.resize(arr, (self._stream_w, self._stream_h))
            # Convert RGBA → BGR
            if arr.ndim == 3 and arr.shape[2] == 4:
                bgr = arr[:, :, :3]
                a = arr[:, :, 3:]
                bg = np.full_like(bgr, 32)
                al = a.astype(np.float32) / 255.0
                bgr = (bgr.astype(np.float32) * al +
                       bg.astype(np.float32) * (1 - al)).astype(np.uint8)
                arr = bgr
            self._stream_writer.write(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
        except Exception as e:
            logger.error("Stream frame write error: %s", e)

    def _finish_streaming_export(self, cancelled=False):
        """Finalize the streaming export."""
        self._stream_active = False
        if self._stream_writer is not None:
            self._stream_writer.release()
            self._stream_writer = None

        # Restore game state
        self.node = self._stream_saved_node
        self.move_index = self._stream_saved_index
        self._update_board()

        self.export_start_btn.setEnabled(True)
        self.stream_export_btn.setEnabled(True)
        self.export_cancel_btn.setEnabled(False)

        if cancelled:
            self.export_progress_bar.setValue(0)
            self.export_status_lbl.setText("Cancelled")
            # Remove partial file
            if hasattr(self, '_stream_output') and os.path.exists(self._stream_output):
                try:
                    os.remove(self._stream_output)
                except Exception:
                    pass
        else:
            self.export_progress_bar.setValue(100)
            total = self._stream_frame_idx
            self.export_status_lbl.setText(
                f"Done!\nCodec:{self._stream_codec}\n"
                f"Saved:{self._stream_output}\n"
                f"{self._stream_w}x{self._stream_h} @ {self._stream_fps}fps\n"
                f"Frames:{total}")
            if hasattr(self, '_stream_output'):
                self.preview_mp4_path.setText(self._stream_output)
            self.sound_manager.play("ui_click")

    @staticmethod
    def _qimage_to_numpy(f):
        """Convert a QImage to a numpy RGBA array (H, W, 4)."""
        import cv2 as _cv2
        from PySide6.QtCore import QBuffer, QIODevice, QByteArray

        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        ok = f.save(buf, "PNG")
        buf.close()
        if not ok or ba.isEmpty():
            return None

        data = np.frombuffer(bytes(ba), dtype=np.uint8)
        arr = _cv2.imdecode(data, _cv2.IMREAD_UNCHANGED)
        if arr is None:
            return None

        if arr.ndim == 2:
            arr = _cv2.cvtColor(arr, _cv2.COLOR_GRAY2RGBA)
        elif arr.shape[2] == 3:
            arr = _cv2.cvtColor(arr, _cv2.COLOR_BGR2RGBA)
        elif arr.shape[2] == 4:
            arr = _cv2.cvtColor(arr, _cv2.COLOR_BGRA2RGBA)
        return arr

    def _on_export_prog(self, p, m):
        self.export_progress_bar.setValue(p)
        self.export_status_lbl.setText(m)

    def _on_export_done(self, m):
        self.export_start_btn.setEnabled(True)
        self.stream_export_btn.setEnabled(True)
        self.export_cancel_btn.setEnabled(False)
        self.export_status_lbl.setText(m)
        self.statusBar().showMessage(m)
        if m.startswith("Done") and self.export_path_edit.text().strip():
            self.preview_mp4_path.setText(
                self.export_path_edit.text().strip())
        self.sound_manager.play("ui_click")

    def _cancel_export(self):
        if self.export_worker:
            self.export_worker.cancel()
        if self._stream_active:
            self._stream_active = False

    def closeEvent(self, e):
        self._cleanup()
        super().closeEvent(e)