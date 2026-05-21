"""Chess Video Maker Pro — Main Application Window Logic"""
import io
import os
import glob
import logging
from PySide6.QtWidgets import QApplication, QMainWindow, QListWidgetItem, QTableWidgetItem
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap, QImage
import chess
import chess.pgn
from constants import AI_MAP, THEMES, BoardTheme, HAS_CV2
from ui_builder import build_ui, build_menu
from workers import AIWorker, BatchEvalWorker, ExportWorker
from widgets import VideoCanvas
from sound_manager import SoundManager
from animation_manager import AnimationManager

if HAS_CV2:
    import numpy as np
    import cv2

logger = logging.getLogger("ChessVideoMaker.MainWindow")


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
        self.capture_frames = []
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
        self._new_game()

    def _cleanup(self):
        self._cleanup_preview()
        self.sound_manager.cleanup()
        # FIX: cancel any running workers
        for worker in (self.engine_worker, self.batch_worker,
                       self.export_worker, self.ai_battle_worker):
            if worker and worker.isRunning():
                worker.quit()
                worker.wait(2000)

    # ── Core Logic ─────────────────────────────────────────────────
    def _new_game(self):
        self.game = chess.pgn.Game()
        self.node = self.game
        self.move_index = -1
        self.move_list = []
        self.eval_cache = {}
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

    def _refresh_all(self):
        board = self.node.board() if self.node else chess.Board()
        self.board_widget.set_position(board)
        self.eval_bar_widget.set_eval(self.eval_cache.get(self.node, 0.0))
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
            self.move_index = max(-1, self.move_index - 1)  # FIX: clamp
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

            # Check for pawn promotion
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
        pass  # Names are read directly from edits during capture

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
        """FIX: Unified cleanup — no more fragile conditional method override."""
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
                        break  # FIX: `break` in ternary was a SyntaxError
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

        # FIX: properly handle policy display and arrows without crashes
        if self.policy_chk.isChecked() and d.get("policy"):
            self.board_widget.policy_vis = d["policy"]
            self.board_widget.update()

        if d.get("best_move"):
            try:
                mv = chess.Move.from_uci(d["best_move"])
                new_arrow = (mv.from_square, mv.to_square,
                             QColor(220, 50, 47, 200))
                # FIX: Don't crash on empty arrows list with __setitem__(0,...)
                if self.board_widget.arrows:
                    self.board_widget.arrows[0] = new_arrow
                else:
                    self.board_widget.arrows.append(new_arrow)
                self.board_widget.update()
            except Exception:
                pass  # Invalid UCI string

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
        # FIX: use renamed signal `batch_finished`
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
        # FIX: null-check best_move before trying to parse it
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
        if dm and HAS_CV2 and self.capture_frames:
            self.export_path_edit.setText(
                os.path.join(self.mp4_output_dir, "chess_battle.mp4"))
            self._start_inline_export()

    def _save_png(self):
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

    # ── Capture & Export ───────────────────────────────────────────
    def _auto_capture(self):
        self.capture_frames.clear()
        if not self.move_list:
            return

        # FIX: Save state so we can restore the user's position after capture
        saved_node = self.node
        saved_index = self.move_index

        self._go_first()
        cv = VideoCanvas(self.board_widget, self.eval_bar_widget,
                         bg_color=self.video_bg_color)
        cv.white_name = self.white_name_edit.text()
        cv.black_name = self.black_name_edit.text()
        cv.move_list_text = [n.san() for n in self.move_list]
        cv.overlays = self.canvas_overlays

        fps = self.fps_spin.value()
        hf = int(self.hold_spin.value() * fps)
        cv.eval_cp = self.eval_cache.get(self.node, 0.0)
        cv.current_move_index = -1

        # Starting position frames
        for _ in range(hf):
            self.capture_frames.append(cv.render())

        # Per-move frames
        for i, n in enumerate(self.move_list):
            self.node = n
            self.move_index = i
            self._update_board()
            cv.eval_cp = self.eval_cache.get(self.node, 0.0)
            if n.parent:
                b = n.parent.board()
                cv.move_text = (
                    f"{b.fullmove_number}. {n.san()}"
                    if b.turn == chess.WHITE
                    else f"{b.fullmove_number}... {n.san()}")
            cv.current_move_index = i
            for _ in range(hf):
                self.capture_frames.append(cv.render())

        self.frame_count_lbl.setText(f"Frames: {len(self.capture_frames)}")

        # FIX: Restore the user's original position
        self.node = saved_node
        self.move_index = saved_index
        self._update_board()

        self._preview_captured_frames()

    def _clear_frames(self):
        self.capture_frames = []
        self.frame_count_lbl.setText("Frames: 0")
        self._cleanup_preview()

    def _start_inline_export(self):
        if not HAS_CV2 or not self.capture_frames:
            return
        idx = self.export_res_combo.currentIndex()
        w, h = [(1920, 1080), (1280, 720), (3840, 2160)][idx]
        fps = self.export_fps_spin.value()
        out = self.export_path_edit.text().strip()
        if not out:
            return
        dirname = os.path.dirname(out)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        npf = []
        for f in self.capture_frames:
            # Ensure consistent format for byte counting
            f2 = f.convertToFormat(QImage.Format_RGBA8888)
            width = f2.width()
            height = f2.height()
            ptr = f2.constBits()
            ptr.setsize(height * width * 4)
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape(
                (height, width, 4)).copy()
            npf.append(arr)

        self.export_worker = ExportWorker(npf, fps, out, w, h)
        self.export_worker.progress.connect(self._on_export_prog)
        # FIX: use renamed signal `export_finished`
        self.export_worker.export_finished.connect(self._on_export_done)
        self.export_start_btn.setEnabled(False)
        self.export_cancel_btn.setEnabled(True)
        self.export_status_lbl.setText("Exporting...")
        self.export_worker.start()

    def _on_export_prog(self, p, m):
        self.export_progress_bar.setValue(p)
        self.export_status_lbl.setText(m)

    def _on_export_done(self, m):
        self.export_start_btn.setEnabled(True)
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

    def closeEvent(self, e):
        self._cleanup()
        super().closeEvent(e)