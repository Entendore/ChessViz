"""Chess Video Maker Pro — Main Application Window Logic"""
import io
import os
import glob
import shutil
import tempfile
import logging
from PySide6.QtWidgets import (QApplication, QMainWindow, QListWidgetItem,
                                QTableWidgetItem, QFileDialog)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap, QImage
import chess
import chess.pgn
from constants import (AI_MAP, THEMES, BoardTheme, HAS_CV2,
                       GAME_NORMAL, GAME_CHECKMATE, GAME_STALEMATE,
                       GAME_DRAW, GAME_INSUFFICIENT,
                       RESOLUTION_SIZES, RESOLUTION_LIST,
                       MAX_FRAMES_IN_MEMORY,
                       DEFAULT_FPS, DEFAULT_HOLD, DEFAULT_RESOLUTION_INDEX,
                       find_stockfish)
from ui_builder import build_ui, build_menu
from workers import (AIWorker, BatchEvalWorker, AIBattleWorker,
                     CaptureWorker, StreamingExportWorker, ExportWorker,
                     _qimage_to_bgr_numpy)
from board_renderer import BoardRenderer
from widgets import VideoRenderer
from managers import AnimationManager, SoundManager

if HAS_CV2:
    import numpy as np
    import cv2

logger = logging.getLogger("ChessVideoMaker.MainWindow")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("♟ Chess Video Maker Pro")
        self.setMinimumSize(1350, 850); self.resize(1500, 920)

        self.game = None; self.node = None; self.move_index = 0
        self.move_list = []; self._playing = False
        self._anim_timer = QTimer(); self._anim_timer.setSingleShot(True)
        self._anim_timer.timeout.connect(self._play_step)
        self.engine_worker = None
        self.capture_frames = []
        self._use_disk_cache = False
        self._disk_cache_dir = None; self._disk_frame_count = 0
        self.video_bg_color = QColor(30, 30, 32)
        self.db_folder = ""; self.img_folder = ""
        self.canvas_overlays = []
        self.ai_vs_ai_running = False
        self.ai_battle_worker = None
        self.eval_cache = {}
        self.batch_worker = None; self.export_worker = None
        self._pending_promo_from = None; self._pending_promo_to = None
        self._prev_frames = []; self._prev_idx = 0
        self._prev_playing = False; self._prev_fps = 30
        self._prev_speed = 1.0
        self._prev_timer = QTimer(); self._prev_timer.timeout.connect(self._preview_advance)
        self._prev_cap = None; self._prev_source = None; self._prev_mp4_count = 0
        self.sound_manager = SoundManager(self)
        self.anim_manager = None
        # Pipeline workers
        self._capture_worker = None
        self._streaming_worker = None
        self._pipeline_battle_worker = None
        self._batch_worker = None
        # Pipeline state tracking
        self._pipeline_battle_eval_cache = {}
        self._pipeline_phase = "idle"  # "idle", "battle", "export"
        # Auto-export flags
        self._auto_export_after_capture = False
        self._auto_save_png_after_capture = False

        build_ui(self); build_menu(self)
        self.promo_widget.piece_selected.connect(self._on_promo_pick)
        self.anim_manager = AnimationManager(
            self.board_widget, self.eval_bar_widget, self)

        self.mp4_output_dir = os.path.join(os.getcwd(), "mp4 files")
        os.makedirs(self.mp4_output_dir, exist_ok=True)
        self.export_path_edit.setText(
            os.path.join(self.mp4_output_dir, "chess_video.mp4"))
        self.output_dir_lbl.setText(f"📁 Output: {self.mp4_output_dir}")

        # Try auto-detect Stockfish on startup
        sf = find_stockfish()
        if sf:
            self.engine_path_edit.setText(sf)
            if hasattr(self, 'settings_engine_path'):
                self.settings_engine_path.setText(sf)
                self.settings_engine_status.setText(f"✅ Auto-detected: {os.path.basename(sf)}")
                self.settings_engine_status.setStyleSheet("color:#6b6;font-size:10px")

        self._new_game()

    # ── Cleanup ────────────────────────────────────────────────────
    def _cleanup(self):
        self._playing = False; self._anim_timer.stop()
        self._prev_timer.stop(); self._prev_playing = False
        if self.anim_manager: self.anim_manager.cancel_all()
        self.ai_vs_ai_running = False
        self._cancel_all_workers()
        self._cleanup_preview(); self._cleanup_disk_cache()
        self.sound_manager.cleanup()

    def _cancel_all_workers(self):
        """Safely cancel and wait for all background workers."""
        workers = [
            (self.engine_worker, 'eval_ready'),
            (self.batch_worker, None),
            (self.export_worker, None),
            (self.ai_battle_worker, None),
            (self._capture_worker, None),
            (self._streaming_worker, None),
            (self._pipeline_battle_worker, None),
            (self._batch_worker, None),
        ]
        for worker, sig_name in workers:
            if worker and worker.isRunning():
                try:
                    if sig_name and hasattr(worker, sig_name):
                        getattr(worker, sig_name).disconnect()
                except (RuntimeError, TypeError): pass
                if hasattr(worker, 'cancel'): worker.cancel()
                worker.quit(); worker.wait(3000)

    # ── Disk Cache ─────────────────────────────────────────────────
    def _init_disk_cache(self):
        self._cleanup_disk_cache()
        self._disk_cache_dir = tempfile.mkdtemp(prefix="chess_vm_frames_")
        self._disk_frame_count = 0; self._use_disk_cache = True

    def _cleanup_disk_cache(self):
        if self._disk_cache_dir and os.path.isdir(self._disk_cache_dir):
            try: shutil.rmtree(self._disk_cache_dir, ignore_errors=True)
            except: pass
        self._disk_cache_dir = None; self._disk_frame_count = 0
        self._use_disk_cache = False

    def _write_frame_to_disk(self, qimage):
        if not self._disk_cache_dir: return False
        try:
            fname = os.path.join(self._disk_cache_dir,
                                 f"frame_{self._disk_frame_count:05d}.jpg")
            qimage.save(fname, "JPEG", 95); self._disk_frame_count += 1
            return True
        except: return False

    # ── Core Logic ─────────────────────────────────────────────────
    def _new_game(self):
        self.game = chess.pgn.Game(); self.node = self.game
        self.move_index = -1; self.move_list = []; self.eval_cache = {}
        self.eval_bar_widget.reset_game_state()
        self._refresh_all(); self.sound_manager.play("new_game")

    def _load_pgn(self):
        self.tabs.setCurrentIndex(1); self.pgn_text_edit.setFocus()

    def _load_pgn_text(self):
        t = self.pgn_text_edit.toPlainText().strip()
        if not t: return
        try:
            g = chess.pgn.read_game(io.StringIO(t))
            if g: self._load_pgn_data(g)
        except Exception as e: self.statusBar().showMessage(f"Error: {e}")

    def _load_pgn_from_file(self):
        p = self.pgn_file_edit.text().strip()
        if not p or not os.path.isfile(p): return
        try:
            with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                g = chess.pgn.read_game(f)
            if g: self._load_pgn_data(g)
        except Exception as e: self.statusBar().showMessage(f"Error: {e}")

    def _load_pgn_data(self, g):
        self.game = g; self.node = g; self.move_index = -1
        self.eval_cache = {}; self.move_list = list(g.mainline())
        self._refresh_all(); self._go_last()
        self.eval_bar_widget.set_eval(0.0)
        # Update pipeline status
        self.quick_pgn_status.setText(
            f"✅ {len(self.move_list)} moves loaded")
        self.quick_pgn_status.setStyleSheet("color:#6b6;font-size:11px")

    def _refresh_all(self):
        board = self.node.board() if self.node else chess.Board()
        self.board_widget.set_position(board)
        self.eval_bar_widget.set_eval(self.eval_cache.get(self.node, 0.0))
        self._update_game_state(board); self._refresh_move_list()

    def _refresh_move_list(self):
        self.move_table.blockSignals(True); self.move_table.setRowCount(0)
        for i, n in enumerate(self.move_list):
            b = n.parent.board(); san = n.san(); es = ""
            if n in self.eval_cache:
                ev = self.eval_cache[n]
                es = (f" (M{int(abs(ev)-10000)})" if abs(ev) > 9000 else f" ({ev/100:+.2f})")
            r = i // 2; is_white = (i % 2 == 0)
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
        else: self.move_table.clearSelection()
        self.move_table.blockSignals(False)

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
            self.eval_bar_widget.set_game_state(GAME_CHECKMATE, result, "Checkmate")
            self.statusBar().showMessage(f"Checkmate! {result}"); return
        if board.is_stalemate():
            self.eval_bar_widget.set_eval(0.0)
            self.eval_bar_widget.set_game_state(GAME_STALEMATE, "½-½", "Stalemate")
            self.statusBar().showMessage("Stalemate — ½-½"); return
        if board.is_insufficient_material():
            self.eval_bar_widget.set_eval(0.0)
            self.eval_bar_widget.set_game_state(GAME_INSUFFICIENT, "½-½", "Insufficient Material")
            self.statusBar().showMessage("Draw: Insufficient Material — ½-½"); return
        if board.is_game_over():
            self.eval_bar_widget.set_eval(0.0)
            self.eval_bar_widget.set_game_state(GAME_DRAW, "½-½", "Draw")
            self.statusBar().showMessage("Draw — ½-½"); return
        self.eval_bar_widget.reset_game_state()

    def _update_board(self, animate=False, move_obj=None):
        board = self.node.board() if self.node else chess.Board()
        lm = self.node.move if self.node and self.node.parent else None
        if animate and move_obj and self.anim_manager.enabled:
            self.board_widget.set_position_animated(board, lm)
            self.anim_manager.animate_piece_move(move_obj)
            self.anim_manager.animate_last_move_flash(move_obj.from_square, move_obj.to_square)
        else:
            self.board_widget.set_position(board, lm)
        if board.is_check():
            ks = board.king(board.turn)
            if ks is not None and animate: self.anim_manager.animate_check(ks)
        self.eval_bar_widget.set_eval(self.eval_cache.get(self.node, 0.0))
        self._update_game_state(board)
        if 0 <= self.move_index < len(self.move_list):
            col = 1 if self.move_index % 2 == 0 else 2
            self.move_table.setCurrentCell(self.move_index // 2, col)

    def _on_move_cell(self, r, c, pr, pc):
        if r < 0: return
        mi = r * 2 + (0 if c <= 1 else 1)
        if 0 <= mi < len(self.move_list) and self.move_index != mi:
            self.move_index = mi; self.node = self.move_list[mi]; self._update_board()

    def _go_first(self):
        self.node = self.game; self.move_index = -1
        self._update_board(); self.sound_manager.play("ui_click")

    def _go_prev(self):
        if self.node and self.node.parent:
            self.node = self.node.parent; self.move_index = max(-1, self.move_index - 1)
            self._update_board(); self.sound_manager.play("ui_click")

    def _go_next(self):
        if self.node and self.node.variations:
            mo = self.node.variations[0].move
            self.node = self.node.variations[0]; self.move_index += 1
            self._update_board(animate=True, move_obj=mo)
            self._play_sound_for_move(self.node)

    def _go_last(self):
        while self.node and self.node.variations:
            self.node = self.node.variations[0]; self.move_index += 1
        self._update_board()

    def _toggle_play(self):
        self._playing = not self._playing
        self.btn_play.setText("⏸ Pause" if self._playing else "▶ Play")
        if self._playing: self._play_step()

    def _play_step(self):
        if not self._playing: return
        if self.node and self.node.variations:
            self._go_next()
            QTimer.singleShot(int(3000 / self.speed_slider.value()), self._play_step)
        else: self._playing = False; self.btn_play.setText("▶ Play")

    def _play_sound_for_move(self, node):
        if not node or not node.parent: return
        b = node.board(); m = node.move; pb = node.parent.board()
        if b.is_checkmate(): self.sound_manager.play("checkmate"); return
        pc = pb.piece_at(m.from_square)
        if (pc and pc.piece_type == chess.KING and
                abs(chess.square_file(m.from_square) - chess.square_file(m.to_square)) == 2):
            self.sound_manager.play("castle"); return
        if m.promotion: self.sound_manager.play("promotion"); return
        if pb.is_capture(m):
            self.sound_manager.play("capture")
            if b.is_check(): QTimer.singleShot(80, lambda: self.sound_manager.play("check"))
            return
        if b.is_check(): self.sound_manager.play("check"); return
        self.sound_manager.play("move")

    # ── Board Interaction ──────────────────────────────────────────
    def _on_sq_click(self, sq):
        if self.ai_vs_ai_running: return
        b = self.board_widget.board
        if self.board_widget.selected_sq is None:
            if b.piece_at(sq) and b.piece_at(sq).color == b.turn:
                self.board_widget.selected_sq = sq
                self.board_widget.legal_targets = [
                    m.to_square for m in b.legal_moves if m.from_square == sq]
                self.board_widget.update(); self.sound_manager.play("ui_click")
        else:
            fs = self.board_widget.selected_sq; mv = chess.Move(fs, sq)
            promo_ranks = {chess.A8,chess.B8,chess.C8,chess.D8,chess.E8,chess.F8,chess.G8,chess.H8,
                           chess.A1,chess.B1,chess.C1,chess.D1,chess.E1,chess.F1,chess.G1,chess.H1}
            if (b.piece_at(fs) and b.piece_at(fs).piece_type == chess.PAWN and sq in promo_ranks):
                tm = chess.Move(fs, sq, promotion=chess.QUEEN)
                if tm in b.legal_moves:
                    self._pending_promo_from = fs; self._pending_promo_to = sq
                    self.promo_widget.show_for_color(b.turn)
                    self.board_widget.selected_sq = None
                    self.board_widget.legal_targets = []
                    self.board_widget.update(); return
            if mv in b.legal_moves:
                self.node = self.node.add_variation(mv)
                self.move_list = list(self.game.mainline())
                self.move_index += 1
                self.board_widget.selected_sq = None
                self.board_widget.legal_targets = []
                self._update_board(animate=True, move_obj=mv)
                self._refresh_move_list()
                self._play_sound_for_move(self.node)
            else:
                self.board_widget.selected_sq = None
                self.board_widget.legal_targets = []
                self.board_widget.update(); self.sound_manager.play("illegal")

    def _on_promo_pick(self, pt):
        if self._pending_promo_from is not None and self._pending_promo_to is not None:
            b = self.board_widget.board
            mv = chess.Move(self._pending_promo_from, self._pending_promo_to, promotion=pt)
            if mv in b.legal_moves:
                self.node = self.node.add_variation(mv)
                self.move_list = list(self.game.mainline())
                self.move_index += 1
                self._update_board(animate=True, move_obj=mv)
                self._refresh_move_list(); self._play_sound_for_move(self.node)
            else: self.sound_manager.play("illegal")
            self._pending_promo_from = None; self._pending_promo_to = None
        self.promo_widget.hide()

    # ── Batch PGN Pipeline ─────────────────────────────────────────
    def _browse_batch_pgn_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select PGN Folder")
        if d:
            self.batch_pgn_folder_edit.setText(d)
            if not self.batch_output_folder_edit.text():
                self.batch_output_folder_edit.setText(os.path.join(d, "mp4_output"))

    def _browse_batch_output_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if d: self.batch_output_folder_edit.setText(d)

    def _start_batch_pgn_export(self):
        pgn_dir = self.batch_pgn_folder_edit.text().strip()
        out_dir = self.batch_output_folder_edit.text().strip()
        if not pgn_dir or not os.path.isdir(pgn_dir):
            self.batch_status_lbl.setText("❌ Invalid PGN folder!")
            self.batch_status_lbl.setStyleSheet("color:#e55;font-size:11px"); return
        if not out_dir:
            self.batch_status_lbl.setText("❌ Invalid Output folder!")
            self.batch_status_lbl.setStyleSheet("color:#e55;font-size:11px"); return

        pgn_files = glob.glob(os.path.join(pgn_dir, "*.pgn"))
        if not pgn_files:
            self.batch_status_lbl.setText("❌ No .pgn files found in folder!")
            self.batch_status_lbl.setStyleSheet("color:#e55;font-size:11px"); return

        settings = {
            "fps": self.batch_fps_spin.value(),
            "hold": self.batch_hold_spin.value(),
            "res_str": self.batch_res_combo.currentText(),
            "bg_color": self.video_bg_color,
            "theme": self.board_widget.theme,
            "flipped": self.board_widget.flipped,
            "white_name": self.white_name_edit.text(),
            "black_name": self.black_name_edit.text(),
            "overlays": list(self.canvas_overlays),
            "eval_during": self.batch_eval_chk.isChecked(),
            "stockfish_path": self._get_engine_path()
        }

        self._batch_worker = BatchPGNExportWorker(pgn_files, out_dir, settings)
        self._batch_worker.batch_progress.connect(self._on_batch_progress)
        self._batch_worker.game_exported.connect(self._on_batch_game_exported)
        self._batch_worker.batch_finished.connect(self._on_batch_finished)
        self.batch_start_btn.setEnabled(False)
        self.batch_cancel_btn.setEnabled(True)
        self.batch_progress_bar.setValue(0)
        self.batch_status_lbl.setText(f"🔄 Scanning {len(pgn_files)} PGN file(s)…")
        self.batch_status_lbl.setStyleSheet("color:#cc0;font-size:11px")
        self._batch_worker.start()

    def _cancel_batch(self):
        if self._batch_worker and self._batch_worker.isRunning():
            self._batch_worker.cancel()
            self.batch_status_lbl.setText("⏹ Cancelling…")
            self.batch_status_lbl.setStyleSheet("color:#c90;font-size:11px")

    def _on_batch_progress(self, current, total, filename):
        pct = int(current / total * 100) if total > 0 else 0
        self.batch_progress_bar.setValue(pct)
        self.batch_status_lbl.setText(f"🎬 [{current}/{total}] Rendering: {filename}")

    def _on_batch_game_exported(self, output_path):
        logger.info("Batch exported: %s", output_path)

    def _on_batch_finished(self, success, fail):
        self.batch_start_btn.setEnabled(True)
        self.batch_cancel_btn.setEnabled(False)
        self.batch_progress_bar.setValue(100)
        msg = f"✅ Batch Complete! Success: {success}, Failed: {fail}"
        self.batch_status_lbl.setText(msg)
        self.batch_status_lbl.setStyleSheet("color:#6b6;font-size:11px")
        self.statusBar().showMessage(msg)

    # ── Handlers ───────────────────────────────────────────────────
    def _flip_board(self):
        self.board_widget.flipped = not self.board_widget.flipped
        self.board_widget.update(); self.sound_manager.play("ui_click")

    def _theme_changed(self, t):
        self.board_widget.set_theme(THEMES.get(t, BoardTheme()))

    def _apply_comment(self):
        if self.node: self.node.comment = self.anno_edit.toPlainText()

    def _pick_bg_color(self, n):
        cm = {"Dark Gray":QColor(30,30,32),"Black":QColor(0,0,0),
              "Dark Blue":QColor(15,20,40),"Dark Green":QColor(15,35,15),
              "Dark Red":QColor(40,15,15),"White":QColor(255,255,255),
              "Light Gray":QColor(200,200,200),"Navy":QColor(0,0,80)}
        self.video_bg_color = cm.get(n, QColor(30,30,32))

    def _update_names(self): pass

    def _clear_policy(self):
        self.board_widget.policy_vis = {}; self.board_widget.update()

    # ── Settings ───────────────────────────────────────────────────
    def _on_sound_enabled(self, e): self.sound_manager.set_enabled(e)
    def _on_sound_vol(self, v):
        self.sound_manager.set_volume(v/100.0); self.sound_vol_lbl.setText(f"{v}%")
    def _on_sound_theme(self, t): self.sound_manager.set_theme(t)

    def _on_sound_design(self, d):
        self.sound_manager.set_design(d)
        descs = {
            "Default": "🎵 Default — Standard balanced sound",
            "Warm": "🎸 Warm — Softer tones with reverb and low-frequency warmth",
            "Crisp": "🔔 Crisp — Bright, sharp attack with fast decay",
            "Retro": "🕹️ Retro — 8-bit lo-fi crunch with short punchy sounds",
            "Cinematic": "🎬 Cinematic — Deep, atmospheric with rich reverb",
            "Minimal": "◻️ Minimal — Ultra-subtle, very short and quiet",
        }
        if hasattr(self, 'sound_design_desc'):
            self.sound_design_desc.setText(descs.get(d, ""))

    def _on_anim_enabled(self, e): self.anim_manager.enabled = e
    def _on_anim_dur(self, ms): self.anim_manager.set_duration(ms)
    def _on_anim_easing(self, n): self.anim_manager.set_easing(n)
    def _on_anim_piece(self, e): self.anim_manager.set_piece_anim(e)
    def _on_anim_highlight(self, e): self.anim_manager.set_highlight_anim(e)
    def _on_anim_eval(self, e): self.anim_manager.set_eval_anim(e)
    def _on_disk_cache_toggled(self, checked): self._use_disk_cache = checked

    def _get_engine_path(self):
        """Get engine path from settings tab or analysis tab."""
        p = getattr(self, 'settings_engine_path', None)
        if p:
            txt = p.text().strip()
            if txt: return txt
        return self.engine_path_edit.text().strip()

    def _browse_engine_path(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select Stockfish Executable")
        if p:
            self.settings_engine_path.setText(p)
            self.engine_path_edit.setText(p)
            self.settings_engine_status.setText(f"✅ Set: {os.path.basename(p)}")
            self.settings_engine_status.setStyleSheet("color:#6b6;font-size:10px")

    def _auto_detect_engine(self):
        p = find_stockfish()
        if p:
            self.settings_engine_path.setText(p)
            self.engine_path_edit.setText(p)
            self.settings_engine_status.setText(f"✅ Found: {p}")
            self.settings_engine_status.setStyleSheet("color:#6b6;font-size:10px")
        else:
            self.settings_engine_status.setText("❌ Stockfish not found on system")
            self.settings_engine_status.setStyleSheet("color:#e55;font-size:10px")

    # ════════════════════════════════════════════════════════════════
    #  Pipeline — Quick PGN → MP4
    # ════════════════════════════════════════════════════════════════
    def _quick_load_pgn(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PGN File", "", "PGN Files (*.pgn);;All Files (*)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    g = chess.pgn.read_game(f)
                if g:
                    self._load_pgn_data(g)
                    self.statusBar().showMessage(f"Loaded PGN: {os.path.basename(path)}")
                else:
                    self.statusBar().showMessage("No valid game found in PGN")
            except Exception as e:
                self.statusBar().showMessage(f"Error loading PGN: {e}")

    def _quick_pgn_to_mp4(self):
        if not self.move_list:
            self.quick_status_lbl.setText("❌ No game loaded! Load a PGN first.")
            self.quick_status_lbl.setStyleSheet("color:#e55;font-size:11px")
            return

        res_str = self.quick_res_combo.currentText()
        fps = self.quick_fps_spin.value()
        hold = self.quick_hold_spin.value()
        output = os.path.join(self.mp4_output_dir,
                              self.quick_output_edit.text().strip() or "chess_pgn_video.mp4")

        br = BoardRenderer.from_widget(self.board_widget)
        sf_path = self._get_engine_path() if self.quick_eval_chk.isChecked() else ""

        self._streaming_worker = StreamingExportWorker(
            game=self.game, move_list=self.move_list,
            eval_cache=self.eval_cache, board_renderer=br,
            video_bg_color=self.video_bg_color,
            white_name=self.white_name_edit.text(),
            black_name=self.black_name_edit.text(),
            overlays=list(self.canvas_overlays),
            fps=fps, hold=hold, res_str=res_str,
            output_path=output,
            stockfish_path=sf_path,
            eval_during_export=self.quick_eval_chk.isChecked())
        self._streaming_worker.progress.connect(self._on_quick_pgn_progress)
        self._streaming_worker.export_finished.connect(self._on_quick_pgn_done)
        self.quick_pgn_btn.setEnabled(False)
        self.quick_pgn_cancel_btn.setEnabled(True)
        self.quick_progress_bar.setValue(0)
        self.quick_status_lbl.setText("🎬 Rendering…")
        self.quick_status_lbl.setStyleSheet("color:#cc0;font-size:11px")
        self._pipeline_phase = "pgn_export"
        self._streaming_worker.start()

    def _cancel_quick_pgn(self):
        if self._streaming_worker and self._streaming_worker.isRunning():
            self._streaming_worker.cancel()
            self.quick_status_lbl.setText("⏹ Cancelling…")
            self.quick_status_lbl.setStyleSheet("color:#c90;font-size:11px")

    def _on_quick_pgn_progress(self, pct, txt):
        self.quick_progress_bar.setValue(pct)
        self.quick_status_lbl.setText(txt)

    def _on_quick_pgn_done(self, msg):
        self.quick_pgn_btn.setEnabled(True)
        self.quick_pgn_cancel_btn.setEnabled(False)
        self._pipeline_phase = "idle"
        if msg.startswith("Done"):
            self.quick_status_lbl.setText("✅ " + msg.replace("\n", "  "))
            self.quick_status_lbl.setStyleSheet("color:#6b6;font-size:11px")
            self.quick_progress_bar.setValue(100)
        elif msg == "Cancelled":
            self.quick_status_lbl.setText("⏹ Cancelled")
            self.quick_status_lbl.setStyleSheet("color:#c90;font-size:11px")
        else:
            self.quick_status_lbl.setText("❌ " + msg)
            self.quick_status_lbl.setStyleSheet("color:#e55;font-size:11px")

    # ════════════════════════════════════════════════════════════════
    #  Pipeline — Quick AI → MP4  (FIXED: eval cache preserved)
    # ════════════════════════════════════════════════════════════════
    def _quick_ai_to_mp4(self):
        w_et = self.quick_w_ai_combo.currentText()
        w_str = self.quick_w_ai_str.value()
        b_et = self.quick_b_ai_combo.currentText()
        b_str = self.quick_b_ai_str.value()
        max_moves = self.quick_max_moves_spin.value()
        delay = self.quick_battle_delay.value()

        w_par = self._ai_params(w_et, w_str)
        b_par = self._ai_params(b_et, b_str)

        # Start fresh game for the battle
        self._new_game()
        self._pipeline_battle_eval_cache = {}
        self._pipeline_phase = "battle"

        self._pipeline_battle_worker = AIBattleWorker(
            w_engine_type=w_et, w_params=w_par,
            b_engine_type=b_et, b_params=b_par,
            max_moves=max_moves, delay_ms=delay)
        self._pipeline_battle_worker.move_made.connect(self._on_pipeline_battle_move)
        self._pipeline_battle_worker.battle_progress.connect(self._on_pipeline_battle_progress)
        self._pipeline_battle_worker.game_finished.connect(self._on_pipeline_battle_done)
        self.quick_ai_btn.setEnabled(False)
        self.quick_ai_cancel_btn.setEnabled(True)
        self.quick_ai_progress_bar.setValue(0)
        self.quick_ai_phase_lbl.setText("Phase: Battle ⚔️")
        self.quick_ai_status_lbl.setText("⚔️ Battle starting…")
        self.quick_ai_status_lbl.setStyleSheet("color:#cc0;font-size:11px")
        self._pipeline_battle_worker.start()

    def _cancel_quick_ai(self):
        """Cancel the current AI pipeline operation (battle or export)."""
        if self._pipeline_phase == "battle" and self._pipeline_battle_worker and self._pipeline_battle_worker.isRunning():
            self._pipeline_battle_worker.cancel()
            self.quick_ai_status_lbl.setText("⏹ Cancelling battle…")
            self.quick_ai_status_lbl.setStyleSheet("color:#c90;font-size:11px")
        elif self._pipeline_phase == "export" and self._streaming_worker and self._streaming_worker.isRunning():
            self._streaming_worker.cancel()
            self.quick_ai_status_lbl.setText("⏹ Cancelling export…")
            self.quick_ai_status_lbl.setStyleSheet("color:#c90;font-size:11px")

    def _ai_params(self, et, strength):
        par = {}
        if et == "Minimax (Alpha-Beta)":
            par["depth"] = max(1, min(4, strength))
        elif et == "MCTS (Monte Carlo)":
            par["iterations"] = max(100, min(5000, strength * 5))
        elif et == "Stockfish (UCI)":
            par["path"] = self._get_engine_path()
        return par

    def _on_pipeline_battle_move(self, uci, eval_cp):
        """Handle each move from the AI battle — update board and store eval."""
        try:
            mv = chess.Move.from_uci(uci)
            board = self.board_widget.board
            if mv in board.legal_moves:
                self.node = self.node.add_variation(mv)
                self.move_list = list(self.game.mainline())
                self.move_index += 1
                self._update_board(animate=False, move_obj=mv)
                self._refresh_move_list()
                # Store eval in both caches
                self.eval_cache[self.node] = eval_cp
                self._pipeline_battle_eval_cache[self.node] = eval_cp
                # Update eval bar if checkbox enabled
                if hasattr(self, 'quick_ai_show_eval_chk') and self.quick_ai_show_eval_chk.isChecked():
                    self.eval_bar_widget.set_eval(eval_cp)
                self._play_sound_for_move(self.node)
            else:
                logger.warning("Pipeline battle: illegal move %s", uci)
        except Exception as e:
            logger.warning("Pipeline battle move error: %s", e)

    def _on_pipeline_battle_progress(self, move_num, max_moves, phase):
        pct = int(move_num / max_moves * 50) if max_moves > 0 else 0
        self.quick_ai_progress_bar.setValue(pct)
        self.quick_ai_phase_lbl.setText(f"Phase: Battle ⚔️ ({phase})")
        self.quick_ai_status_lbl.setText(f"⚔️ Move {move_num}/{max_moves} — {phase}")

    def _on_pipeline_battle_done(self, pgn_text, result):
        """Battle finished — now export to MP4. CRITICAL: preserve eval_cache."""
        self._pipeline_phase = "export"
        self.quick_ai_phase_lbl.setText("Phase: Export 🎬")
        self.quick_ai_status_lbl.setText("🎬 Battle done — rendering MP4…")
        self.quick_ai_progress_bar.setValue(50)

        # Go to last move to ensure board is in final state
        self._go_last()
        self._update_game_state()

        # Update the pipeline status for the PGN section too
        self.quick_pgn_status.setText(
            f"✅ {len(self.move_list)} moves (AI battle)")
        self.quick_pgn_status.setStyleSheet("color:#6b6;font-size:11px")

        # Start streaming export — use self.eval_cache which has battle evals preserved
        res_str = self.quick_ai_res_combo.currentText()
        fps = self.quick_ai_fps_spin.value()
        hold = self.quick_ai_hold_spin.value()
        output = os.path.join(self.mp4_output_dir,
                              self.quick_ai_output_edit.text().strip() or "chess_battle.mp4")

        br = BoardRenderer.from_widget(self.board_widget)

        self._streaming_worker = StreamingExportWorker(
            game=self.game, move_list=self.move_list,
            eval_cache=self.eval_cache,  # Preserved eval cache with battle evals!
            board_renderer=br,
            video_bg_color=self.video_bg_color,
            white_name=self.white_name_edit.text(),
            black_name=self.black_name_edit.text(),
            overlays=list(self.canvas_overlays),
            fps=fps, hold=hold, res_str=res_str,
            output_path=output)
        self._streaming_worker.progress.connect(self._on_quick_ai_export_progress)
        self._streaming_worker.export_finished.connect(self._on_quick_ai_done)
        self._streaming_worker.start()

    def _on_quick_ai_export_progress(self, pct, txt):
        self.quick_ai_progress_bar.setValue(50 + pct // 2)
        self.quick_ai_status_lbl.setText(f"🎬 {txt}")

    def _on_quick_ai_done(self, msg):
        self.quick_ai_btn.setEnabled(True)
        self.quick_ai_cancel_btn.setEnabled(False)
        self._pipeline_phase = "idle"
        if msg.startswith("Done"):
            self.quick_ai_status_lbl.setText("✅ " + msg.replace("\n", "  "))
            self.quick_ai_status_lbl.setStyleSheet("color:#6b6;font-size:11px")
            self.quick_ai_progress_bar.setValue(100)
            self.quick_ai_phase_lbl.setText("Phase: Complete ✅")
        elif msg == "Cancelled":
            self.quick_ai_status_lbl.setText("⏹ Cancelled")
            self.quick_ai_status_lbl.setStyleSheet("color:#c90;font-size:11px")
            self.quick_ai_phase_lbl.setText("Phase: Cancelled")
        else:
            self.quick_ai_status_lbl.setText("❌ " + msg)
            self.quick_ai_status_lbl.setStyleSheet("color:#e55;font-size:11px")
            self.quick_ai_phase_lbl.setText("Phase: Error ❌")

    # ── Preview ────────────────────────────────────────────────────
    def _preview_captured_frames(self):
        if self._use_disk_cache and self._disk_cache_dir:
            self._preview_from_disk(); return
        if not self.capture_frames: return
        self._stop_preview()
        if self._prev_cap: self._prev_cap.release(); self._prev_cap = None
        self._prev_frames = list(self.capture_frames)
        self._prev_fps = self.fps_spin.value()
        self._prev_source = 'frames'; self._prev_idx = 0
        self.preview_slider.setRange(0, max(0, len(self._prev_frames)-1))
        self._refresh_prev_ctrl()
        if self._prev_frames: self._show_prev_frame(0)

    def _preview_from_disk(self):
        if not HAS_CV2 or not self._disk_cache_dir: return
        self._stop_preview()
        if self._prev_cap: self._prev_cap.release(); self._prev_cap = None
        step = max(1, self._disk_frame_count // 300); frames = []
        for i in range(0, self._disk_frame_count, step):
            fname = os.path.join(self._disk_cache_dir, f"frame_{i:05d}.jpg")
            if os.path.isfile(fname):
                qimg = QImage(fname)
                if not qimg.isNull(): frames.append(qimg)
        if not frames:
            self.statusBar().showMessage("No frames to preview"); return
        self._prev_frames = frames; self._prev_fps = self.fps_spin.value()
        self._prev_source = 'frames'; self._prev_idx = 0
        self.preview_slider.setRange(0, max(0, len(self._prev_frames)-1))
        self._refresh_prev_ctrl(); self._show_prev_frame(0)

    def _preview_mp4(self):
        if not HAS_CV2: return
        p = (self.preview_mp4_path.text().strip() or self.export_path_edit.text().strip())
        if not p or not os.path.isfile(p): return
        self._stop_preview()
        if self._prev_cap: self._prev_cap.release(); self._prev_cap = None
        self._prev_cap = cv2.VideoCapture(p)
        if not self._prev_cap.isOpened(): return
        self._prev_source = 'mp4'; self._prev_frames = []
        self._prev_mp4_count = int(self._prev_cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        self._prev_fps = max(1, int(self._prev_cap.get(cv2.CAP_PROP_FPS)) or 30)
        self._prev_idx = 0
        self.preview_slider.setRange(0, max(0, self._prev_mp4_count-1))
        self._refresh_prev_ctrl(); self._show_prev_mp4(0)

    def _stop_preview(self):
        self._prev_playing = False; self._prev_timer.stop()
        self.preview_play_btn.setText("▶"); self._prev_idx = 0
        self.preview_slider.setValue(0); self._show_cur_prev(); self._update_prev_lbl()

    def _refresh_prev_ctrl(self):
        t = self._prev_total()
        ok = t > 0; self.preview_play_btn.setEnabled(ok)
        self.preview_stop_btn.setEnabled(ok); self._update_prev_lbl()

    def _prev_total(self):
        if self._prev_source == 'frames': return len(self._prev_frames)
        if self._prev_source == 'mp4': return self._prev_mp4_count
        return 0

    def _update_prev_lbl(self):
        n = self._prev_total()
        if n > 0:
            s = self._prev_idx / self._prev_fps; m, ss = divmod(s, 60)
            self.preview_time_lbl.setText(f"{self._prev_idx+1}/{n} {int(m)}:{ss:04.1f}")
        else: self.preview_time_lbl.setText("0/0")

    def _update_preview_speed(self, i):
        sp = [0.5, 1.0, 2.0, 4.0]
        self._prev_speed = sp[i] if 0 <= i < len(sp) else 1.0
        if self._prev_playing:
            self._prev_timer.setInterval(max(1, int(1000/(self._prev_fps*self._prev_speed))))

    def _toggle_preview_play(self):
        if self._prev_playing:
            self._prev_playing = False; self._prev_timer.stop()
            self.preview_play_btn.setText("▶")
        else:
            if self._prev_total() <= 0: return
            if self._prev_idx >= self._prev_total()-1:
                self._prev_idx = 0; self.preview_slider.setValue(0); self._show_cur_prev()
            self._prev_playing = True; self.preview_play_btn.setText("⏸")
            self._prev_timer.start(max(1, int(1000/(self._prev_fps*self._prev_speed))))

    def _preview_advance(self):
        if self._prev_idx >= self._prev_total()-1:
            self._prev_playing = False; self._prev_timer.stop()
            self.preview_play_btn.setText("▶"); return
        self._prev_idx += 1; self.preview_slider.setValue(self._prev_idx)
        self._show_cur_prev(); self._update_prev_lbl()

    def _show_cur_prev(self):
        if self._prev_source == 'frames': self._show_prev_frame(self._prev_idx)
        elif self._prev_source == 'mp4': self._show_prev_mp4(self._prev_idx)

    def _show_prev_frame(self, idx):
        if 0 <= idx < len(self._prev_frames):
            pm = QPixmap.fromImage(self._prev_frames[idx])
            sz = self.preview_display.size()
            if sz.isValid() and not sz.isEmpty():
                self.preview_display.setPixmap(pm.scaled(sz, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else: self.preview_display.setPixmap(pm)

    def _show_prev_mp4(self, idx):
        if not HAS_CV2 or not self._prev_cap or not self._prev_cap.isOpened(): return
        self._prev_cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, f = self._prev_cap.read()
        if ret:
            rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
            h, w, c = rgb.shape
            qi = QImage(rgb.data, w, h, c*w, QImage.Format_RGB888).copy()
            pm = QPixmap.fromImage(qi); sz = self.preview_display.size()
            if sz.isValid():
                self.preview_display.setPixmap(pm.scaled(sz, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else: self.preview_display.setPixmap(pm)

    def _scrub_preview(self, v):
        self._prev_idx = v; self._show_cur_prev(); self._update_prev_lbl()

    def _cleanup_preview(self):
        self._stop_preview()
        if HAS_CV2 and self._prev_cap is not None:
            self._prev_cap.release(); self._prev_cap = None
        self._prev_frames = []

    # ── DB & Assets ────────────────────────────────────────────────
    def _set_pgn_db_folder(self):
        d = self.db_folder_edit.text().strip()
        if d and os.path.isdir(d): self._set_db(d)
        else: self.statusBar().showMessage("Invalid path")

    def _set_db(self, d):
        self.db_folder = d; self.db_path_lbl.setText(f"Folder: {d}"); self._scan_pgn_db()

    def _scan_pgn_db(self):
        if not self.db_folder: return
        self.db_list.clear()
        for f in glob.glob(os.path.join(self.db_folder, "**/*.pgn"), recursive=True):
            self.db_list.addItem(os.path.basename(f))

    def _load_selected_pgn_db(self, item=None):
        if not item and not self.db_list.currentItem(): return
        fn = (item.text() if item else self.db_list.currentItem().text())
        fp = os.path.join(self.db_folder, fn)
        gi = self.db_game_idx.value() - 1
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                g = None
                for i in range(gi + 1):
                    g = chess.pgn.read_game(f)
                    if g is None: break
                if g: self._load_pgn_data(g)
        except Exception as e: self.statusBar().showMessage(f"Error: {e}")

    def _set_img_folder(self):
        d = self.img_folder_edit.text().strip()
        if d and os.path.isdir(d): self._set_im(d)
        else: self.statusBar().showMessage("Invalid path")

    def _set_im(self, d):
        self.img_folder = d; self.img_path_lbl.setText(f"Folder: {d}"); self._scan_img_db()

    def _scan_img_db(self):
        if not self.img_folder: return
        self.img_list.clear()
        for e in ("*.png","*.jpg","*.jpeg","*.bmp","*.gif"):
            for f in (glob.glob(os.path.join(self.img_folder, e))
                      + glob.glob(os.path.join(self.img_folder, "**", e), recursive=True)):
                it = QListWidgetItem(QIcon(f), os.path.basename(f))
                it.setData(Qt.UserRole, f); self.img_list.addItem(it)

    def _add_overlay(self):
        it = self.img_list.currentItem()
        if not it: return
        p = it.data(Qt.UserRole); pos = self.ov_pos_combo.currentText()
        ov = {"path":p,"w":150,"h":150}
        if "White" in pos: ov["x"], ov["y"] = 50, 850
        elif "Black" in pos: ov["x"], ov["y"] = 50, 50
        elif "Center" in pos: ov["x"], ov["y"] = 960-75, 540-75
        elif "Watermark" in pos: ov["x"], ov["y"] = 1750, 1000
        else: ov["x"], ov["y"] = 100, 100
        self.canvas_overlays.append(ov)

    def _clear_overlays(self): self.canvas_overlays = []

    # ── AI Analysis ────────────────────────────────────────────────
    def _toggle_ai_ui(self, t):
        idx = list(AI_MAP.values()).index(t) if t in AI_MAP.values() else 0
        self.ai_stack.setCurrentIndex(idx)

    def _run_engine(self):
        et = self.ai_combo.currentText(); pa = {}
        if et == "Minimax (Alpha-Beta)": pa["depth"] = self.mm_depth.value()
        elif et == "MCTS (Monte Carlo)": pa["iterations"] = self.m_iters.value()
        elif et == "Stockfish (UCI)": pa["path"] = self._get_engine_path()
        self.engine_worker = AIWorker(et, self.board_widget.board.fen(), pa)
        self.engine_worker.eval_ready.connect(self._on_eval_ready)
        self.engine_worker.start(); self.run_ai_btn.setEnabled(False)
        self.eval_label.setText("Eval: …")

    def _on_eval_ready(self, d):
        self.run_ai_btn.setEnabled(True)
        self.eval_label.setText(f"Eval: {d['eval']}")
        self.pv_label.setText(f"Nodes: {d['nodes']}")
        if self.policy_chk.isChecked() and d.get("policy"):
            self.board_widget.policy_vis = d["policy"]; self.board_widget.update()
        if d.get("best_move"):
            try:
                mv = chess.Move.from_uci(d["best_move"])
                new_arrow = (mv.from_square, mv.to_square, QColor(220,50,47,200))
                if self.board_widget.arrows: self.board_widget.arrows[0] = new_arrow
                else: self.board_widget.arrows.append(new_arrow)
                self.board_widget.update()
            except: pass

    def _start_batch_eval(self):
        if not self.move_list: return
        et = self.ai_combo.currentText(); pa = {}
        if et == "Minimax (Alpha-Beta)": pa["depth"] = self.mm_depth.value()
        elif et == "MCTS (Monte Carlo)": pa["iterations"] = self.m_iters.value()
        elif et == "Stockfish (UCI)": pa["path"] = self._get_engine_path()
        self.batch_worker = BatchEvalWorker(self.move_list, et, pa)
        self.batch_worker.move_evaluated.connect(self._on_move_eval)
        self.batch_worker.batch_finished.connect(self._on_eval_batch_finished)
        self.eval_game_btn.setEnabled(False); self.stop_eval_btn.setEnabled(True)
        self.batch_worker.start()

    def _on_move_eval(self, i, ev, es):
        if 0 <= i < len(self.move_list): self.eval_cache[self.move_list[i]] = ev
        self._refresh_move_list()
        if self.node == self.move_list[i]: self.eval_bar_widget.set_eval(ev)

    def _on_eval_batch_finished(self):
        self.eval_game_btn.setEnabled(True); self.stop_eval_btn.setEnabled(False)

    def _stop_batch_eval(self):
        if self.batch_worker: self.batch_worker.cancel()

    # ── AI Battle (Interactive) ────────────────────────────────────
    def _start_ai_vs_ai(self):
        if self.ai_vs_ai_running: return
        self._new_game(); self.ai_vs_ai_running = True
        self.start_battle_btn.setEnabled(False); self.stop_battle_btn.setEnabled(True)
        self.auto_mp4_chk.setEnabled(False); self.save_png_chk.setEnabled(False)
        self._ai_battle_step()

    def _ai_battle_step(self):
        if not self.ai_vs_ai_running: return
        b = self.board_widget.board
        if b.is_game_over():
            self._stop_ai_vs_ai()
            self.statusBar().showMessage(f"Game Over: {b.result()}"); return
        et = (self.white_ai_combo.currentText() if b.turn == chess.WHITE
              else self.black_ai_combo.currentText())
        st = (self.white_ai_str.value() if b.turn == chess.WHITE
              else self.black_ai_str.value())
        pa = self._ai_params(et, st)
        self.ai_battle_worker = AIWorker(et, b.fen(), pa)
        self.ai_battle_worker.eval_ready.connect(self._on_battle_move)
        self.ai_battle_worker.start()

    def _on_battle_move(self, d):
        if not self.ai_vs_ai_running: return
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
            except: logger.warning("Invalid battle move: %s", bu)
        QTimer.singleShot(self.battle_delay.value(), self._ai_battle_step)

    def _stop_ai_vs_ai(self):
        self.ai_vs_ai_running = False
        self.start_battle_btn.setEnabled(True); self.stop_battle_btn.setEnabled(False)
        self.auto_mp4_chk.setEnabled(True); self.save_png_chk.setEnabled(True)
        if self.ai_battle_worker and self.ai_battle_worker.isRunning():
            self.ai_battle_worker.quit()
        self._update_game_state()
        if self.auto_mp4_chk.isChecked() or self.save_png_chk.isChecked():
            self._auto_export()

    def _auto_export(self):
        dm = self.auto_mp4_chk.isChecked(); dp = self.save_png_chk.isChecked()
        if not dm and not dp: return

        self._auto_export_after_capture = dm
        self._auto_save_png_after_capture = dp
        self.statusBar().showMessage("🎬 Auto-capturing…"); QApplication.processEvents()
        self._auto_capture()

    def _save_png(self):
        if self._use_disk_cache: self._save_png_from_disk(); return
        if not self.capture_frames: return
        pd = os.path.join(self.mp4_output_dir, "png_frames"); os.makedirs(pd, exist_ok=True)
        fps = self.fps_spin.value(); hf = max(1, int(self.hold_spin.value()*fps))
        tot = len(self.capture_frames); sv = 0; mn = 1; pos = hf
        idx = min(hf-1, tot-1)
        self.capture_frames[idx].save(os.path.join(pd, "move_000_start.png")); sv += 1
        while pos < tot:
            idx = min(pos+hf-1, tot-1)
            self.capture_frames[idx].save(os.path.join(pd, f"move_{mn:03d}.png"))
            sv += 1; mn += 1; pos += hf
        self.statusBar().showMessage(f"🖼 Saved {sv} PNGs")

    def _save_png_from_disk(self):
        if self._disk_frame_count == 0 or not self._disk_cache_dir: return
        pd = os.path.join(self.mp4_output_dir, "png_frames"); os.makedirs(pd, exist_ok=True)
        fps = self.fps_spin.value(); hf = max(1, int(self.hold_spin.value()*fps)); sv = 0
        idx = min(hf-1, self._disk_frame_count-1)
        src = os.path.join(self._disk_cache_dir, f"frame_{idx:05d}.jpg")
        if os.path.isfile(src): QImage(src).save(os.path.join(pd, "move_000_start.png")); sv += 1
        mn = 1; pos = hf
        while pos < self._disk_frame_count:
            idx = min(pos+hf-1, self._disk_frame_count-1)
            src = os.path.join(self._disk_cache_dir, f"frame_{idx:05d}.jpg")
            if os.path.isfile(src): QImage(src).save(os.path.join(pd, f"move_{mn:03d}.png")); sv += 1
            mn += 1; pos += hf
        self.statusBar().showMessage(f"🖼 Saved {sv} PNGs")

    # ── Capture & Export ───────────────────────────────────────────
    def _should_use_disk_cache(self, estimated_frames):
        if self._use_disk_cache: return True
        if estimated_frames > MAX_FRAMES_IN_MEMORY: return True
        return False

    def _auto_capture(self):
        """Capture all frames — uses CaptureWorker in background thread."""
        self.capture_frames.clear(); self._cleanup_disk_cache()
        if not self.move_list: return

        fps = self.fps_spin.value(); hf = int(self.hold_spin.value() * fps)
        estimated = hf * (len(self.move_list) + 1)
        use_disk = self._should_use_disk_cache(estimated)

        if use_disk: self._init_disk_cache()

        br = BoardRenderer.from_widget(self.board_widget)
        res_str = self.export_res_combo.currentText()

        self._capture_worker = CaptureWorker(
            game=self.game, move_list=self.move_list,
            eval_cache=self.eval_cache, board_renderer=br,
            video_bg_color=self.video_bg_color,
            white_name=self.white_name_edit.text(),
            black_name=self.black_name_edit.text(),
            overlays=list(self.canvas_overlays),
            fps=fps, hold=self.hold_spin.value(), res_str=res_str,
            use_disk_cache=use_disk,
            disk_cache_dir=self._disk_cache_dir if use_disk else None,
            eval_during_capture=False, stockfish_path=""
        )
        self._capture_worker.progress.connect(self._on_capture_progress)
        self._capture_worker.frame_captured.connect(self._on_frame_captured)
        self._capture_worker.capture_finished.connect(self._on_capture_finished)
        self.auto_btn.setEnabled(False)
        self._capture_worker.start()

    def _on_capture_progress(self, pct, txt):
        self.frame_count_lbl.setText(txt)

    def _on_frame_captured(self, total):
        if self._use_disk_cache:
            self.frame_count_lbl.setText(f"Frames: {self._disk_frame_count}")
        else:
            self.frame_count_lbl.setText(f"Frames: {len(self.capture_frames)}")

    def _on_capture_finished(self, success):
        self.auto_btn.setEnabled(True)
        if success:
            total = self._disk_frame_count if self._use_disk_cache else len(self.capture_frames)
            self.frame_count_lbl.setText(f"Frames: {total}")
            self.statusBar().showMessage(f"✅ Capture complete: {total} frames")

            # Chain auto-export if flagged
            if getattr(self, '_auto_save_png_after_capture', False):
                self._save_png()
                self._auto_save_png_after_capture = False
            if getattr(self, '_auto_export_after_capture', False):
                self.export_path_edit.setText(os.path.join(self.mp4_output_dir, "chess_battle.mp4"))
                self._start_inline_export()
                self._auto_export_after_capture = False
        else:
            self.statusBar().showMessage("❌ Capture failed")

    def _clear_frames(self):
        self.capture_frames.clear(); self._cleanup_disk_cache()
        self.frame_count_lbl.setText("Frames: 0")

    def _start_inline_export(self):
        if not HAS_CV2: return
        if not self.capture_frames and self._disk_frame_count == 0: return

        res_str = self.export_res_combo.currentText()
        w, h = RESOLUTION_SIZES.get(res_str, (1920, 1080))
        fps = self.fps_spin.value()
        out = self.export_path_edit.text().strip()
        if not out: return

        self.export_start_btn.setEnabled(False); self.export_cancel_btn.setEnabled(True)
        self.export_worker = ExportWorker(
            self.capture_frames, fps, out, w, h,
            frame_dir=self._disk_cache_dir if self._use_disk_cache else None)
        self.export_worker.progress.connect(self._on_export_progress)
        self.export_worker.export_finished.connect(self._on_export_done)
        self.export_worker.start()

    def _on_export_progress(self, pct, txt):
        self.export_progress_bar.setValue(pct); self.export_status_lbl.setText(txt)

    def _on_export_done(self, msg):
        self.export_start_btn.setEnabled(True); self.export_cancel_btn.setEnabled(False)
        if msg.startswith("Done"):
            self.export_progress_bar.setValue(100)
            self.export_status_lbl.setText("✅ " + msg.replace("\n", "  "))
            self.statusBar().showMessage("✅ Export complete!")
        elif msg == "Cancelled":
            self.export_status_lbl.setText("⏹ Cancelled")
        else:
            self.export_status_lbl.setText("❌ " + msg)

    def _cancel_export(self):
        if self.export_worker: self.export_worker.cancel()

    def _start_streaming_export(self):
        if not self.move_list: return

        res_str = self.export_res_combo.currentText()
        w, h = RESOLUTION_SIZES.get(res_str, (1920, 1080))
        fps = self.fps_spin.value()
        hold = self.hold_spin.value()
        out = self.export_path_edit.text().strip()
        if not out: return

        br = BoardRenderer.from_widget(self.board_widget)

        self._streaming_worker = StreamingExportWorker(
            game=self.game, move_list=self.move_list,
            eval_cache=self.eval_cache, board_renderer=br,
            video_bg_color=self.video_bg_color,
            white_name=self.white_name_edit.text(),
            black_name=self.black_name_edit.text(),
            overlays=list(self.canvas_overlays),
            fps=fps, hold=hold, res_str=res_str,
            output_path=out,
            stockfish_path="", eval_during_export=False)
        self._streaming_worker.progress.connect(self._on_stream_progress)
        self._streaming_worker.export_finished.connect(self._on_stream_done)
        self.export_start_btn.setEnabled(False); self.export_cancel_btn.setEnabled(True)
        self._streaming_worker.start()

    def _on_stream_progress(self, pct, txt):
        self.export_progress_bar.setValue(pct); self.export_status_lbl.setText(txt)

    def _on_stream_done(self, msg):
        self.export_start_btn.setEnabled(True); self.export_cancel_btn.setEnabled(False)
        if msg.startswith("Done"):
            self.export_progress_bar.setValue(100)
            self.export_status_lbl.setText("✅ " + msg.replace("\n", "  "))
            self.statusBar().showMessage("✅ Stream export complete!")
        elif msg == "Cancelled":
            self.export_status_lbl.setText("⏹ Cancelled")
        else:
            self.export_status_lbl.setText("❌ " + msg)