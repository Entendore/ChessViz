"""Chess Video Maker Pro — Main Application Window (Logic & Handlers)"""

import io
import os
import glob
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QListWidgetItem,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon

import chess
import chess.pgn

from constants import AI_MAP, THEMES, BoardTheme, HAS_CV2
from ui_builder import build_ui, build_menu
from workers import AIWorker, BatchEvalWorker, ExportWorker
from video_canvas import VideoCanvas

if HAS_CV2:
    import numpy as np


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("♟ Chess Video Maker Pro — AI Battle & Eval")
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
        build_ui(self)
        build_menu(self)
        self.promo_widget.piece_selected.connect(self._on_promo_pick)
        self._new_game()

    # ── Core Navigation & Logic ───────────────────────────

    def _new_game(self):
        self.game = chess.pgn.Game()
        self.node = self.game
        self.move_index = -1
        self.move_list = []
        self.eval_cache = {}
        self._refresh_all()

    def _load_pgn(self):
        """Menu action: switch to the PGN Database tab for inline loading."""
        self.tabs.setCurrentIndex(1)
        self.pgn_text_edit.setFocus()
        self.statusBar().showMessage("Paste PGN text or enter a file path in the Database tab.")

    def _load_pgn_text(self):
        """Load PGN from the inline text area in the Database tab."""
        text = self.pgn_text_edit.toPlainText().strip()
        if not text:
            self.statusBar().showMessage("No PGN text to load.")
            return
        try:
            game = chess.pgn.read_game(io.StringIO(text))
            if game:
                self._load_pgn_data(game)
                self.statusBar().showMessage("PGN loaded successfully.")
            else:
                self.statusBar().showMessage("Error: Invalid PGN.")
        except Exception as e:
            self.statusBar().showMessage(f"Error: {str(e)}")

    def _load_pgn_from_file(self):
        """Load PGN from the file path specified inline in the Database tab."""
        path = self.pgn_file_edit.text().strip()
        if not path or not os.path.isfile(path):
            self.statusBar().showMessage("Error: Invalid file path.")
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                game = chess.pgn.read_game(f)
                if game:
                    self._load_pgn_data(game)
                    self.statusBar().showMessage(f"PGN loaded from {os.path.basename(path)}")
                else:
                    self.statusBar().showMessage("Error: No valid game found in file.")
        except Exception as e:
            self.statusBar().showMessage(f"Error: {str(e)}")

    def _load_pgn_data(self, game):
        self.game = game
        self.node = game
        self.move_index = -1
        self.eval_cache = {}
        self.move_list = list(game.mainline())
        self._refresh_all()
        self._go_last()
        self.eval_bar_widget.set_eval(0.0)

    def _refresh_all(self):
        self.board_widget.set_position(self.node.board() if self.node else chess.Board())
        self.eval_bar_widget.set_eval(self.eval_cache.get(self.node, 0.0))
        self._refresh_move_list()

    def _refresh_move_list(self):
        self.move_listbox.blockSignals(True)
        self.move_listbox.clear()
        for i, node in enumerate(self.move_list):
            b = node.parent.board()
            san = node.san()
            eval_str = ""
            if node in self.eval_cache:
                ev = self.eval_cache[node]
                eval_str = (f" (M{int(abs(ev) - 10000)})" if abs(ev) > 9000
                            else f" ({ev / 100.0:+.2f})")
            text = (f"{b.fullmove_number}. {san}{eval_str}" if b.turn == chess.WHITE
                    else f"{b.fullmove_number}… {san}{eval_str}")
            self.move_listbox.addItem(QListWidgetItem(text))
        if 0 <= self.move_index < self.move_listbox.count():
            self.move_listbox.setCurrentRow(self.move_index)
        self.move_listbox.blockSignals(False)

    def _update_board(self):
        board = self.node.board() if self.node else chess.Board()
        last_move = self.node.move if self.node and self.node.parent else None
        self.board_widget.set_position(board, last_move)
        self.eval_bar_widget.set_eval(self.eval_cache.get(self.node, 0.0))
        if 0 <= self.move_index < self.move_listbox.count():
            self.move_listbox.setCurrentRow(self.move_index)

    def _on_move_row(self, row):
        if 0 <= row < len(self.move_list):
            self.move_index = row
            self.node = self.move_list[row]
            self._update_board()

    def _go_first(self):
        self.node = self.game; self.move_index = -1; self._update_board()

    def _go_prev(self):
        if self.node and self.node.parent:
            self.node = self.node.parent; self.move_index -= 1; self._update_board()

    def _go_next(self):
        if self.node and self.node.variations:
            self.node = self.node.variations[0]; self.move_index += 1; self._update_board()

    def _go_last(self):
        while self.node and self.node.variations:
            self.node = self.node.variations[0]; self.move_index += 1
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
            QTimer.singleShot(int(3000 / self.speed_slider.value()), self._play_step)
        else:
            self._playing = False
            self.btn_play.setText("▶ Play")

    # ── Board Interaction ─────────────────────────────────

    def _on_sq_click(self, sq):
        if self.ai_vs_ai_running:
            return
        board = self.board_widget.board
        if self.board_widget.selected_sq is None:
            if board.piece_at(sq) and board.piece_at(sq).color == board.turn:
                self.board_widget.selected_sq = sq
                self.board_widget.legal_targets = [
                    m.to_square for m in board.legal_moves if m.from_square == sq
                ]
                self.board_widget.update()
        else:
            from_sq = self.board_widget.selected_sq
            move = chess.Move(from_sq, sq)
            promo_ranks = [chess.A8, chess.B8, chess.C8, chess.D8, chess.E8, chess.F8, chess.G8, chess.H8,
                           chess.A1, chess.B1, chess.C1, chess.D1, chess.E1, chess.F1, chess.G1, chess.H1]
            if (board.piece_at(from_sq) and board.piece_at(from_sq).piece_type == chess.PAWN
                    and sq in promo_ranks):
                test_move = chess.Move(from_sq, sq, promotion=chess.QUEEN)
                if test_move in board.legal_moves:
                    self._pending_promo_from = from_sq
                    self._pending_promo_to = sq
                    self.promo_widget.show_for_color(board.turn)
                    self.board_widget.selected_sq = None
                    self.board_widget.legal_targets = []
                    self.board_widget.update()
                    self.statusBar().showMessage("Select promotion piece below the board.")
                    return
            if move in board.legal_moves:
                self.node = self.node.add_variation(move)
                self.move_list = list(self.game.mainline())
                self.move_index += 1
                self.board_widget.selected_sq = None
                self.board_widget.legal_targets = []
                self._update_board(); self._refresh_move_list()
            else:
                self.board_widget.selected_sq = None
                self.board_widget.legal_targets = []
                self.board_widget.update()

    def _on_promo_pick(self, piece_type):
        """Handle promotion piece selection from inline widget."""
        if self._pending_promo_from is not None and self._pending_promo_to is not None:
            board = self.board_widget.board
            move = chess.Move(self._pending_promo_from, self._pending_promo_to, promotion=piece_type)
            if move in board.legal_moves:
                self.node = self.node.add_variation(move)
                self.move_list = list(self.game.mainline())
                self.move_index += 1
                self._update_board()
                self._refresh_move_list()
                self.statusBar().showMessage(f"Promoted to {chess.piece_name(piece_type)}.")
            else:
                self.statusBar().showMessage("Invalid promotion move.")
            self._pending_promo_from = None
            self._pending_promo_to = None
        self.promo_widget.hide()

    # ── Simple Handlers ───────────────────────────────────

    def _flip_board(self):
        self.board_widget.flipped = not self.board_widget.flipped; self.board_widget.update()

    def _theme_changed(self, t):
        self.board_widget.set_theme(THEMES.get(t, BoardTheme()))

    def _apply_comment(self):
        if self.node:
            self.node.comment = self.anno_edit.toPlainText()
            self.statusBar().showMessage("Comment applied.")

    def _pick_bg_color(self, color_name):
        """Handle background color selection from inline combo box."""
        color_map = {
            "Dark Gray": QColor(30, 30, 32),
            "Black": QColor(0, 0, 0),
            "Dark Blue": QColor(15, 20, 40),
            "Dark Green": QColor(15, 35, 15),
            "Dark Red": QColor(40, 15, 15),
            "White": QColor(255, 255, 255),
            "Light Gray": QColor(200, 200, 200),
            "Navy": QColor(0, 0, 80),
        }
        c = color_map.get(color_name, QColor(30, 30, 32))
        self.video_bg_color = c
        self.bg_color_combo.setStyleSheet(
            f"QComboBox {{ background-color: {c.name()}; }}"
        )

    def _update_names(self):
        pass

    def _clear_policy(self):
        self.board_widget.policy_vis = {}
        self.board_widget.update()

    # ── Database & Assets Logic ──────────────────────────

    def _set_pgn_db_folder(self):
        """Set PGN database folder from the inline text input."""
        d = self.db_folder_edit.text().strip()
        if d and os.path.isdir(d):
            self.db_folder = d
            self.db_path_lbl.setText(f"Folder: {d}")
            self._scan_pgn_db()
            self.statusBar().showMessage(f"PGN database folder set: {d}")
        else:
            self.statusBar().showMessage("Error: Invalid folder path.")

    def _scan_pgn_db(self):
        if not self.db_folder:
            return
        self.db_list.clear()
        QApplication.processEvents()
        files = glob.glob(os.path.join(self.db_folder, "**/*.pgn"), recursive=True)
        for f in files:
            self.db_list.addItem(os.path.basename(f))

    def _load_selected_pgn_db(self, item=None):
        if not item and self.db_list.currentItem() is None:
            return
        filename = item.text() if item else self.db_list.currentItem().text()
        filepath = os.path.join(self.db_folder, filename)
        game_idx = self.db_game_idx.value() - 1
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                game = None
                for i in range(game_idx + 1):
                    game = chess.pgn.read_game(f)
                    if game is None:
                        break
                if game:
                    self._load_pgn_data(game)
                    self.statusBar().showMessage(f"Loaded game {game_idx + 1} from {filename}")
                else:
                    self.statusBar().showMessage(f"Error: Game index {game_idx + 1} not found.")
        except Exception as e:
            self.statusBar().showMessage(f"Error: {str(e)}")

    def _set_img_folder(self):
        """Set image assets folder from the inline text input."""
        d = self.img_folder_edit.text().strip()
        if d and os.path.isdir(d):
            self.img_folder = d
            self.img_path_lbl.setText(f"Folder: {d}")
            self._scan_img_db()
            self.statusBar().showMessage(f"Image folder set: {d}")
        else:
            self.statusBar().showMessage("Error: Invalid folder path.")

    def _scan_img_db(self):
        if not self.img_folder:
            return
        self.img_list.clear()
        QApplication.processEvents()
        exts = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif")
        files = []
        for e in exts:
            files.extend(glob.glob(os.path.join(self.img_folder, e)))
            files.extend(glob.glob(os.path.join(self.img_folder, "**", e), recursive=True))
        for f in files:
            item = QListWidgetItem(QIcon(f), os.path.basename(f))
            item.setData(Qt.UserRole, f)
            self.img_list.addItem(item)

    def _add_overlay(self):
        item = self.img_list.currentItem()
        if not item:
            return
        path = item.data(Qt.UserRole)
        pos = self.ov_pos_combo.currentText()
        ov = {"path": path, "w": 150, "h": 150}
        if "White" in pos:
            ov["x"], ov["y"] = 50, 850
        elif "Black" in pos:
            ov["x"], ov["y"] = 50, 50
        elif "Center" in pos or "Logo" in pos:
            ov["x"], ov["y"] = 960 - 75, 540 - 75
        elif "Watermark" in pos:
            ov["x"], ov["y"] = 1750, 1000
        else:
            ov["x"], ov["y"] = 100, 100
        self.canvas_overlays.append(ov)
        self.statusBar().showMessage(f"Added overlay: {os.path.basename(path)} at {pos}")

    def _clear_overlays(self):
        self.canvas_overlays = []
        self.statusBar().showMessage("Cleared all overlays.")

    # ── AI Lab & Battle ──────────────────────────────────

    def _toggle_ai_ui(self, text):
        idx = list(AI_MAP.values()).index(text) if text in AI_MAP.values() else 0
        self.ai_stack.setCurrentIndex(idx)

    def _run_engine(self):
        engine_type = self.ai_combo.currentText()
        params = {}
        if engine_type == "Minimax (Alpha-Beta)":
            params["depth"] = self.mm_depth.value()
        elif engine_type == "MCTS (Monte Carlo)":
            params["iterations"] = self.m_iters.value()
        elif engine_type == "Stockfish (UCI)":
            params["path"] = self.engine_path_edit.text()
        self.engine_worker = AIWorker(engine_type, self.board_widget.board.fen(), params)
        self.engine_worker.eval_ready.connect(self._on_eval_ready)
        self.engine_worker.start()
        self.run_ai_btn.setEnabled(False)
        self.eval_label.setText("Eval: …")

    def _on_eval_ready(self, data):
        self.run_ai_btn.setEnabled(True)
        self.eval_label.setText(f"Eval: {data['eval']}")
        self.pv_label.setText(f"Nodes: {data['nodes']}")
        if self.policy_chk.isChecked() and data.get("policy"):
            self.board_widget.policy_vis = data["policy"]
            self.board_widget.update()
        if data.get("best_move"):
            self.board_widget.arrows = []
            move_obj = chess.Move.from_uci(data["best_move"])
            fr = move_obj.from_square
            to = move_obj.to_square
            self.board_widget.arrows.append((fr, to, QColor(220, 50, 47, 200)))
            self.board_widget.update()

    def _start_batch_eval(self):
        if not self.move_list:
            self.statusBar().showMessage("No moves to evaluate.")
            return
        engine_type = self.ai_combo.currentText()
        params = {}
        if engine_type == "Minimax (Alpha-Beta)":
            params["depth"] = self.mm_depth.value()
        elif engine_type == "MCTS (Monte Carlo)":
            params["iterations"] = self.m_iters.value()
        elif engine_type == "Stockfish (UCI)":
            params["path"] = self.engine_path_edit.text()
        self.batch_worker = BatchEvalWorker(self.move_list, engine_type, params)
        self.batch_worker.move_evaluated.connect(self._on_move_evaluated)
        self.batch_worker.finished.connect(self._on_batch_finished)
        self.eval_game_btn.setEnabled(False)
        self.stop_eval_btn.setEnabled(True)
        self.batch_worker.start()

    def _on_move_evaluated(self, idx, eval_cp, eval_str):
        if 0 <= idx < len(self.move_list):
            self.eval_cache[self.move_list[idx]] = eval_cp
            self._refresh_move_list()
            if self.node == self.move_list[idx]:
                self.eval_bar_widget.set_eval(eval_cp)

    def _on_batch_finished(self):
        self.eval_game_btn.setEnabled(True)
        self.stop_eval_btn.setEnabled(False)
        self.statusBar().showMessage("Batch evaluation complete.")

    def _stop_batch_eval(self):
        if self.batch_worker:
            self.batch_worker.cancel()

    def _start_ai_vs_ai(self):
        if self.ai_vs_ai_running:
            return
        self._new_game()
        self.ai_vs_ai_running = True
        self.start_battle_btn.setEnabled(False)
        self.stop_battle_btn.setEnabled(True)
        self._ai_battle_step()

    def _ai_battle_step(self):
        if not self.ai_vs_ai_running:
            return
        board = self.board_widget.board
        if board.is_game_over():
            self._stop_ai_vs_ai()
            result = board.result()
            self.statusBar().showMessage(f"Game Over: {result}")
            return

        if board.turn == chess.WHITE:
            engine_type = self.white_ai_combo.currentText()
            strength = self.white_ai_str.value()
        else:
            engine_type = self.black_ai_combo.currentText()
            strength = self.black_ai_str.value()

        params = {}
        if engine_type == "Minimax (Alpha-Beta)":
            params["depth"] = strength
        elif engine_type == "MCTS (Monte Carlo)":
            params["iterations"] = strength
        elif engine_type == "Stockfish (UCI)":
            params["path"] = self.engine_path_edit.text()

        self.ai_battle_worker = AIWorker(engine_type, board.fen(), params)
        self.ai_battle_worker.eval_ready.connect(self._on_battle_move)
        self.ai_battle_worker.start()

    def _on_battle_move(self, data):
        if not self.ai_vs_ai_running:
            return
        best_uci = data.get("best_move")
        if best_uci:
            move = chess.Move.from_uci(best_uci)
            if move in self.board_widget.board.legal_moves:
                self.node = self.node.add_variation(move)
                self.move_list = list(self.game.mainline())
                self.move_index += 1
                self._update_board()
                self._refresh_move_list()
                self.eval_cache[self.node] = data.get("eval_cp", 0.0)
                self.eval_bar_widget.set_eval(data.get("eval_cp", 0.0))
        QTimer.singleShot(self.battle_delay.value(), self._ai_battle_step)

    def _stop_ai_vs_ai(self):
        self.ai_vs_ai_running = False
        self.start_battle_btn.setEnabled(True)
        self.stop_battle_btn.setEnabled(False)
        if self.ai_battle_worker and self.ai_battle_worker.isRunning():
            self.ai_battle_worker.quit()

    # ── Video Capture & Export ────────────────────────────

    def _auto_capture(self):
        self.capture_frames.clear()
        if not self.move_list:
            self.statusBar().showMessage("No moves to capture.")
            return
        self._go_first()
        canvas = VideoCanvas(
            self.board_widget, self.eval_bar_widget, bg_color=self.video_bg_color
        )
        canvas.white_name = self.white_name_edit.text()
        canvas.black_name = self.black_name_edit.text()
        canvas.move_list_text = [n.san() for n in self.move_list]
        canvas.overlays = self.canvas_overlays

        fps = self.fps_spin.value()
        hold_frames = int(self.hold_spin.value() * fps)

        canvas.eval_cp = self.eval_cache.get(self.node, 0.0)
        canvas.current_move_index = -1
        for _ in range(hold_frames):
            self.capture_frames.append(canvas.render())

        for i, node in enumerate(self.move_list):
            self.node = node
            self.move_index = i
            self._update_board()
            canvas.eval_cp = self.eval_cache.get(self.node, 0.0)
            if node.parent:
                b = node.parent.board()
                canvas.move_text = (
                    f"{b.fullmove_number}. {node.san()}"
                    if b.turn == chess.WHITE
                    else f"{b.fullmove_number}... {node.san()}"
                )
            canvas.current_move_index = i
            for _ in range(hold_frames):
                self.capture_frames.append(canvas.render())

        self.frame_count_lbl.setText(f"Frames: {len(self.capture_frames)}")
        self.statusBar().showMessage(f"Captured {len(self.capture_frames)} frames.")

    def _clear_frames(self):
        self.capture_frames = []
        self.frame_count_lbl.setText("Frames: 0")
        self.statusBar().showMessage("Cleared all frames.")

    def _start_inline_export(self):
        """Start video export using inline settings (no popup dialog)."""
        if not HAS_CV2:
            self.export_status_lbl.setText("Error: opencv-python and numpy required.")
            self.statusBar().showMessage("Export failed: opencv-python missing.")
            return
        if not self.capture_frames:
            self.export_status_lbl.setText("No frames captured. Use Auto-Capture first.")
            self.statusBar().showMessage("Export failed: no frames.")
            return

        idx = self.export_res_combo.currentIndex()
        w, h = [(1920, 1080), (1280, 720), (3840, 2160)][idx]
        fps = self.export_fps_spin.value()
        out_path = self.export_path_edit.text().strip()
        if not out_path:
            self.export_status_lbl.setText("Error: Specify output file path.")
            self.statusBar().showMessage("Export failed: no output path.")
            return

        np_frames = []
        for f in self.capture_frames:
            ptr = f.constBits()
            ptr.setsize(f.sizeInBytes())
            np_frames.append(np.array(ptr).reshape(f.height(), f.width(), 4).copy())

        self.export_worker = ExportWorker(np_frames, fps, out_path, w, h)
        self.export_worker.progress.connect(self._on_export_progress)
        self.export_worker.finished.connect(self._on_export_finished)
        self.export_start_btn.setEnabled(False)
        self.export_cancel_btn.setEnabled(True)
        self.export_status_lbl.setText("Exporting...")
        self.export_worker.start()

    def _on_export_progress(self, pct, msg):
        self.export_progress_bar.setValue(pct)
        self.export_status_lbl.setText(msg)

    def _on_export_finished(self, msg):
        self.export_start_btn.setEnabled(True)
        self.export_cancel_btn.setEnabled(False)
        self.export_status_lbl.setText(msg)
        self.statusBar().showMessage(msg)

    def _cancel_export(self):
        if self.export_worker:
            self.export_worker.cancel()