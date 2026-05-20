#!/usr/bin/env python3
"""
Chess Video Maker Pro — Database, Assets, AI Battle & Eval Graph
Create chess YouTube videos with external PGN databases, Image overlays, AI vs AI, and Eval Bars.

Requirements:
    pip install PySide6 python-chess opencv-python numpy
"""

import sys, math, io, os, time, random, glob
from collections import defaultdict

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QSlider, QSpinBox,
    QFileDialog, QDialog, QTextEdit, QGroupBox, QCheckBox, QLineEdit,
    QProgressBar, QMessageBox, QSplitter, QListWidget, QListWidgetItem,
    QSizePolicy, QDialogButtonBox, QFormLayout, QComboBox, QDoubleSpinBox,
    QStackedWidget, QTabWidget, QColorDialog
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QRectF, QPointF, QSize
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QImage,
    QPainterPath, QPolygonF, QFontMetrics, QPalette,
    QKeySequence, QShortcut, QPixmap, QIcon
)

import chess
import chess.pgn
import chess.engine  # Moved import here to prevent UnboundLocalError in QThread run()

try:
    import cv2, numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# ─── Constants & Themes ─────────────────────────────────────────────

PIECE_SYM = {
    (chess.PAWN,   chess.WHITE): "♙", (chess.PAWN,   chess.BLACK): "♟",
    (chess.KNIGHT, chess.WHITE): "♘", (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.WHITE): "♗", (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK,   chess.WHITE): "♖", (chess.ROOK,   chess.BLACK): "♜",
    (chess.QUEEN,  chess.WHITE): "♕", (chess.QUEEN,  chess.BLACK): "♛",
    (chess.KING,   chess.WHITE): "♔", (chess.KING,   chess.BLACK): "♚",
}

AI_MAP = {
    0: "Minimax (Alpha-Beta)",
    1: "MCTS (Monte Carlo)",
    2: "Stockfish (UCI)"
}

SAMPLE_PGN = """\
[Event "World Championship 2023"]
[Site "London ENG"]
[Date "2023.04.09"]
[White "Carlsen, Magnus"]
[Black "Nepomniachtchi, Ian"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5
7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 11. Nbd2 Bb7 12. Bc2 Re8
13. Nf1 Bf8 14. Ng3 g6 15. a4 Bg7 16. Bd3 c6 17. Bg5 Qc7 18. Qd2 Nh5
19. Nxh5 gxh5 20. Bh6 Bxh6 21. Qxh6 Qd8 22. Rab1 Qe7 23. b4 a5 1-0"""


class BoardTheme:
    def __init__(self, name="Classic", light=(240,217,181), dark=(181,136,99),
                 border=(48,26,7), highlight=(255,255,0,100),
                 last_move=(155,199,0,100), arrow=(220,50,47,200)):
        self.name = name; self.light_sq = QColor(*light); self.dark_sq = QColor(*dark)
        self.border = QColor(*border); self.highlight = QColor(*highlight)
        self.last_move = QColor(*last_move); self.arrow_clr = QColor(*arrow)
        self.bg = QColor(32, 32, 36); self.coord = QColor(180, 160, 130)

THEMES = {
    "Classic": BoardTheme(),
    "Blue": BoardTheme("Blue", (208,224,243), (116,150,194), (40,50,70)),
    "Green": BoardTheme("Green", (238,238,210), (118,150,86), (50,60,40)),
    "Brown": BoardTheme("Brown", (222,197,165), (170,120,70), (60,35,15)),
}

# ─── AI Algorithms ──────────────────────────────────────────────────

class HeuristicEvaluator:
    """Evaluates board strictly from White's perspective in centipawns."""
    PIECE_VALUES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330, chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 20000}
    PAWN_TABLE = [
         0,  0,  0,  0,  0,  0,  0,  0,
         5, 10, 10,-20,-20, 10, 10,  5,
         5, -5,-10,  0,  0,-10, -5,  5,
         0,  0,  0, 20, 20,  0,  0,  0,
         5,  5, 10, 25, 25, 10,  5,  5,
        10, -5,  0, 10, 10,  0, -5, 10,
       -15,-15,-20, -5, -5,-20,-15,-15,
         0,  0,  0,  0,  0,  0,  0,  0
    ]

    def evaluate(self, board):
        if board.is_checkmate(): 
            return -99999 if board.turn == chess.WHITE else 99999
        if board.is_stalemate() or board.is_insufficient_material(): 
            return 0
        score = 0
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece:
                value = self.PIECE_VALUES[piece.piece_type]
                if piece.piece_type == chess.PAWN:
                    idx = sq if piece.color == chess.WHITE else chess.square_mirror(sq)
                    value += self.PAWN_TABLE[idx]
                score += value if piece.color == chess.WHITE else -value
        return score


class MinimaxEngine:
    def __init__(self): 
        self.evaluator = HeuristicEvaluator(); self.nodes_searched = 0

    def search(self, board, depth):
        self.nodes_searched = 0
        best_move = None
        alpha = -float('inf'); beta = float('inf')
        best_eval = -float('inf')
        policy = {}

        for move in board.legal_moves:
            board.push(move)
            eval_score = -self._negamax(board, depth - 1, -beta, -alpha)
            board.pop()
            policy[move.uci()] = eval_score
            if eval_score > best_eval:
                best_eval = eval_score; best_move = move
            alpha = max(alpha, eval_score)

        if policy:
            min_p = min(policy.values()); max_p = max(policy.values()); rng = max_p - min_p if max_p != min_p else 1
            policy = {k: (v - min_p) / rng for k, v in policy.items()}
        
        white_eval = best_eval if board.turn == chess.WHITE else -best_eval
        return best_move, white_eval, self.nodes_searched, policy

    def _negamax(self, board, depth, alpha, beta):
        self.nodes_searched += 1
        if depth == 0 or board.is_game_over(): 
            eval_w = self.evaluator.evaluate(board)
            return eval_w if board.turn == chess.WHITE else -eval_w

        for move in board.legal_moves:
            board.push(move)
            eval_score = -self._negamax(board, depth - 1, -beta, -alpha)
            board.pop()
            if eval_score >= beta: return beta
            if eval_score > alpha: alpha = eval_score
        return alpha


class MCTSNode:
    def __init__(self, board, parent=None, move=None):
        self.board = board; self.parent = parent; self.move = move; self.children = []
        self.wins = 0.0; self.visits = 0; self.untried_moves = list(board.legal_moves)
    def ucb1(self, c=1.414): return float('inf') if self.visits == 0 else (self.wins / self.visits) + c * math.sqrt(math.log(self.parent.visits) / self.visits)
    def best_child(self): return max(self.children, key=lambda child: child.ucb1())
    def expand(self):
        move = self.untried_moves.pop(); next_board = self.board.copy(); next_board.push(move)
        child = MCTSNode(next_board, parent=self, move=move); self.children.append(child); return child


class MCTSEngine:
    def __init__(self): self.evaluator = HeuristicEvaluator()
    def search(self, board, iterations):
        root = MCTSNode(board)
        for _ in range(iterations):
            node = root
            while not node.untried_moves and node.children: node = node.best_child()
            if node.untried_moves: node = node.expand()
            score = self._heuristic_rollout(node.board)
            while node is not None:
                node.visits += 1
                node.wins += score if node.board.turn != board.turn else (1 - score)
                node = node.parent
        best_move = max(root.children, key=lambda c: c.visits).move if root.children else None; policy = {}
        if root.children:
            total_visits = sum(c.visits for c in root.children)
            for child in root.children: policy[child.move.uci()] = child.visits / total_visits if total_visits > 0 else 0
        white_eval = self.evaluator.evaluate(board)
        return best_move, white_eval, root.visits, policy

    def _heuristic_rollout(self, board, depth=10):
        if board.is_checkmate(): return 0.0 if board.turn == chess.WHITE else 1.0
        if board.is_stalemate(): return 0.5
        if depth == 0: return 1.0 / (1.0 + math.exp(-0.004 * self.evaluator.evaluate(board)))
        move = random.choice(list(board.legal_moves)); board.push(move); score = self._heuristic_rollout(board, depth - 1); board.pop(); return score


class AIWorker(QThread):
    eval_ready = Signal(dict)
    def __init__(self, engine_type, board_fen, params):
        super().__init__(); self.engine_type = engine_type; self.board_fen = board_fen; self.params = params

    def run(self):
        board = chess.Board(self.board_fen)
        try:
            if self.engine_type == "Minimax (Alpha-Beta)":
                engine = MinimaxEngine(); depth = self.params.get("depth", 3)
                best_move, eval_cp_white, nodes, policy = engine.search(board, depth)
                self.eval_ready.emit({"eval": f"{eval_cp_white/100.0:+.2f}", "eval_cp": eval_cp_white, "nodes": nodes, "policy": policy, "engine_type": self.engine_type, "best_move": best_move.uci() if best_move else None})
            elif self.engine_type == "MCTS (Monte Carlo)":
                engine = MCTSEngine(); iters = self.params.get("iterations", 500)
                best_move, eval_cp_white, total_visits, policy = engine.search(board, iters)
                self.eval_ready.emit({"eval": f"Visits: {total_visits}", "eval_cp": eval_cp_white, "nodes": total_visits, "policy": policy, "engine_type": self.engine_type, "best_move": best_move.uci() if best_move else None})
            elif self.engine_type == "Stockfish (UCI)":
                engine_path = self.params.get("path", "")
                with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
                    result = engine.analyse(board, chess.engine.Limit(depth=20))
                    score = result["score"].white().score(mate_score=10000)
                    policy = {result["pv"][0].uci(): 1.0} if result.get("pv") else {}
                    self.eval_ready.emit({"eval": f"{score/100.0:+.2f}", "eval_cp": float(score), "nodes": 0, "policy": policy, "engine_type": self.engine_type, "best_move": result["pv"][0].uci() if result.get("pv") else None})
        except Exception as e:
            self.eval_ready.emit({"eval": f"Error: {str(e)[:50]}", "eval_cp": 0.0, "nodes": 0, "policy": {}, "engine_type": self.engine_type, "best_move": None})


class BatchEvalWorker(QThread):
    move_evaluated = Signal(int, float, str)
    finished = Signal()
    def __init__(self, move_list, engine_type, params):
        super().__init__()
        self.move_list = move_list; self.engine_type = engine_type; self.params = params; self._cancel = False
    def cancel(self): self._cancel = True

    def run(self):
        if self.engine_type == "Stockfish (UCI)":
            try:
                with chess.engine.SimpleEngine.popen_uci(self.params["path"]) as engine:
                    for i, node in enumerate(self.move_list):
                        if self._cancel: break
                        result = engine.analyse(node.board(), chess.engine.Limit(depth=18))
                        score = result["score"].white().score(mate_score=10000)
                        eval_str = f"M{int(abs(score)-10000)}" if abs(score) > 9000 else f"{score/100.0:+.2f}"
                        self.move_evaluated.emit(i, float(score), eval_str)
            except Exception: pass
        else:
            evaluator = HeuristicEvaluator()
            for i, node in enumerate(self.move_list):
                if self._cancel: break
                score = evaluator.evaluate(node.board())
                eval_str = f"M{int(abs(score)-99999)}" if abs(score) > 9000 else f"{score/100.0:+.2f}"
                self.move_evaluated.emit(i, float(score), eval_str)
                time.sleep(0.01)
        self.finished.emit()


# ─── Chess Board Widget ────────────────────────────────────────────

class ChessBoardWidget(QWidget):
    squareClicked = Signal(int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.board = chess.Board(); self.theme = BoardTheme(); self.flipped = False; self.show_coords = True
        self.selected_sq = None; self.legal_targets = []; self.last_move = None; self.highlighted = set(); self.arrows = []
        self._arrow_start = self._arrow_end = None; self._drawing_arrow = False
        self.anim_move = None; self.anim_progress = 0.0; self.policy_vis = {}
        self.setMinimumSize(400, 400); self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding); self.setMouseTracking(True)

    def _layout(self): 
        total = min(self.width(), self.height()); margin = total * 0.05 if self.show_coords else 0; sq = (total - 2 * margin) / 8; return total, margin, sq
    def _sq_rect(self, sq, total, margin, sq_sz):
        f, r = chess.square_file(sq), chess.square_rank(sq); col = (7 - f) if self.flipped else f; row = r if self.flipped else (7 - r)
        return QRectF(margin + col * sq_sz, margin + row * sq_sz, sq_sz, sq_sz)
    def _pos_to_sq(self, pos, total, margin, sq_sz):
        col = int((pos.x() - margin) / sq_sz); row = int((pos.y() - margin) / sq_sz)
        if not (0 <= col < 8 and 0 <= row < 8): return None
        return chess.square(7 - col, row) if self.flipped else chess.square(col, 7 - row)
    def set_theme(self, t): self.theme = t; self.update()
    def set_position(self, board, last_move=None): self.board = board; self.last_move = last_move; self.selected_sq = None; self.legal_targets = []; self.anim_move = None; self.anim_progress = 0.0; self.update()

    def mousePressEvent(self, e):
        total, margin, sq_sz = self._layout(); sq = self._pos_to_sq(e.position().toPoint(), total, margin, sq_sz)
        if sq is None: return
        if e.button() == Qt.LeftButton:
            if e.modifiers() & Qt.ShiftModifier: self._arrow_start = sq; self._drawing_arrow = True; self._arrow_end = sq
            else: self.squareClicked.emit(sq)
        elif e.button() == Qt.RightButton: self.highlighted.symmetric_difference_update({sq}); self.update()
    def mouseMoveEvent(self, e):
        if self._drawing_arrow:
            total, margin, sq_sz = self._layout(); sq = self._pos_to_sq(e.position().toPoint(), total, margin, sq_sz)
            if sq is not None: self._arrow_end = sq; self.update()
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drawing_arrow:
            total, margin, sq_sz = self._layout(); sq = self._pos_to_sq(e.position().toPoint(), total, margin, sq_sz)
            if sq and self._arrow_start is not None and sq != self._arrow_start:
                self.arrows.append((self._arrow_start, sq, QColor(self.theme.arrow_clr))); self.update()
            self._drawing_arrow = False; self._arrow_start = self._arrow_end = None

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        total, margin, sq = self._layout(); p.fillRect(self.rect(), self.theme.bg); p.setPen(Qt.NoPen); p.setBrush(self.theme.border); p.drawRect(QRectF(0, 0, total, total))
        for s in chess.SQUARES:
            rect = self._sq_rect(s, total, margin, sq); f, r = chess.square_file(s), chess.square_rank(s)
            base = self.theme.light_sq if (f + r) % 2 == 0 else self.theme.dark_sq; p.fillRect(rect, base)
            if self.last_move and s in (self.last_move.from_square, self.last_move.to_square): p.fillRect(rect, self.theme.last_move)
            if s == self.selected_sq: p.fillRect(rect, self.theme.highlight)
            if s in self.highlighted: p.fillRect(rect, QColor(0, 130, 255, 80))
        if self.show_coords:
            fnt = QFont("Arial", max(7, int(sq * 0.14))); fnt.setBold(True); p.setFont(fnt); p.setPen(self.theme.coord)
            for i in range(8):
                fl = chr(ord('h') - i if self.flipped else ord('a') + i); rn = str(i + 1 if self.flipped else 8 - i); x = margin + i * sq + sq / 2
                p.drawText(QRectF(x - sq / 2, total - margin, sq, margin), Qt.AlignCenter, fl); p.drawText(QRectF(0, margin + i * sq, margin, sq), Qt.AlignCenter, rn)
        for mv in self.legal_targets:
            rect = self._sq_rect(mv, total, margin, sq); p.setPen(Qt.NoPen)
            if self.board.piece_at(mv): p.setBrush(QColor(0, 0, 0, 60)); p.drawEllipse(rect.adjusted(sq * 0.1, sq * 0.1, -sq * 0.1, -sq * 0.1))
            else: p.setBrush(QColor(0, 0, 0, 40)); p.drawEllipse(rect.center(), sq * 0.15, sq * 0.15)
        if self.policy_vis:
            p.setPen(Qt.NoPen)
            for uci, prob in self.policy_vis.items():
                try:
                    move = chess.Move.from_uci(uci)
                    if move in self.board.legal_moves:
                        to_sq = move.to_square; rect = self._sq_rect(to_sq, total, margin, sq); color = QColor.fromHsvF(0.33 * prob, 0.9, 0.9, 0.6 * prob + 0.1); p.setBrush(color)
                        p.drawEllipse(rect.center(), sq * 0.4 * prob + sq * 0.1, sq * 0.4 * prob + sq * 0.1)
                except: pass
        for (fr, to, clr) in self.arrows: self._draw_arrow(p, fr, to, clr, margin, sq)
        if self._drawing_arrow and self._arrow_start and self._arrow_end: self._draw_arrow(p, self._arrow_start, self._arrow_end, QColor(self.theme.arrow_clr), margin, sq)
        for s in chess.SQUARES:
            pc = self.board.piece_at(s)
            if pc:
                if self.anim_move and s == self.anim_move.from_square: continue
                self._draw_piece(p, pc, self._sq_rect(s, total, margin, sq), sq)
        if self.anim_move:
            pc = self.board.piece_at(self.anim_move.from_square)
            if pc:
                r_from = self._sq_rect(self.anim_move.from_square, total, margin, sq); r_to = self._sq_rect(self.anim_move.to_square, total, margin, sq)
                x = r_from.x() + (r_to.x() - r_from.x()) * self.anim_progress; y = r_from.y() + (r_to.y() - r_from.y()) * self.anim_progress
                self._draw_piece(p, pc, QRectF(x, y, sq, sq), sq)
        p.end()

    def _draw_piece(self, p, piece, rect, sq_sz):
        sym = PIECE_SYM.get((piece.piece_type, piece.color), "?"); fnt = QFont("Segoe UI Symbol", sq_sz * 0.72); fnt.setStyleStrategy(QFont.PreferAntialias)
        p.setFont(fnt); p.setPen(QPen(QColor(0, 0, 0, 180), max(1, sq_sz * 0.03)))
        if piece.color == chess.WHITE: p.drawText(rect, Qt.AlignCenter, sym); p.setPen(Qt.NoPen); p.drawText(rect.adjusted(0, -1, 0, -1), Qt.AlignCenter, sym)
        else: p.drawText(rect, Qt.AlignCenter, sym)

    def _draw_arrow(self, p, fr, to, color, margin, sq_sz):
        r1 = self._sq_rect(fr, margin, margin, sq_sz); r2 = self._sq_rect(to, margin, margin, sq_sz); c1, c2 = r1.center(), r2.center(); dx, dy = c2.x() - c1.x(), c2.y() - c1.y()
        length = math.hypot(dx, dy)
        if length < 1: return
        ux, uy = dx / length, dy / length; start = QPointF(c1.x() + ux * sq_sz * 0.35, c1.y() + uy * sq_sz * 0.35); end = QPointF(c2.x() - ux * sq_sz * 0.35, c2.y() - uy * sq_sz * 0.35)
        pw = sq_sz * 0.13; p.setPen(Qt.NoPen); p.setBrush(color); p.save(); p.setOpacity(color.alphaF())
        shaft = QPainterPath(); perp_x, perp_y = -uy, ux
        shaft.moveTo(start.x() + perp_x * pw / 2, start.y() + perp_y * pw / 2); shaft.lineTo(end.x() + perp_x * pw / 2, end.y() + perp_y * pw / 2)
        shaft.lineTo(end.x() - perp_x * pw / 2, end.y() - perp_y * pw / 2); shaft.lineTo(start.x() - perp_x * pw / 2, start.y() - perp_y * pw / 2)
        shaft.closeSubpath(); p.drawPath(shaft)
        hw = pw * 2.0; hl = pw * 1.8; tip = QPointF(end.x() + ux * hl, end.y() + uy * hl)
        tri = QPolygonF([end, QPointF(end.x() + perp_x * hw / 2, end.y() + perp_y * hw / 2), tip, QPointF(end.x() - perp_x * hw / 2, end.y() - perp_y * hw / 2)])
        p.drawPolygon(tri); p.restore()

    def render_to_image(self, size=1080):
        img = QImage(size, size, QImage.Format_ARGB32); img.fill(QColor(0, 0, 0, 0))
        old_w, old_h = self.width(), self.height(); self.resize(size, size)
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing); self.render(p); p.end()
        self.resize(old_w, old_h); return img


# ─── Eval Bar Widget (For Main UI) ─────────────────────────────────

class EvalBarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.eval_cp = 0.0; self.setFixedSize(40, 400)
    def set_eval(self, cp): self.eval_cp = cp; self.update()
    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(40,40,40))
        eval_ratio = max(0.0, min(1.0, 0.5 + (self.eval_cp / 2000.0)))
        w, h = self.width(), self.height(); white_h = int(h * eval_ratio)
        p.setBrush(QColor(240,240,240)); p.drawRect(0, h - white_h, w, white_h)
        p.setPen(QColor(150,150,150)); p.setFont(QFont("Arial", 8, QFont.Bold))
        txt = f"M{int(abs(self.eval_cp)-10000)}" if abs(self.eval_cp) > 9000 else f"{self.eval_cp/100.0:+.1f}"
        p.drawText(QRectF(0, h//2 - 15, w, 30), Qt.AlignCenter, txt)
        p.end()


# ─── Video Canvas ───────────────────────────────────────────────────

class VideoCanvas:
    def __init__(self, board_widget, eval_bar_widget, w=1920, h=1080, bg_color=QColor(30, 30, 32)):
        self.bw = board_widget; self.ew = eval_bar_widget; self.w = w; self.h = h; self.bg_color = bg_color
        self.eval_cp = 0.0; self.move_text = ""; self.white_name = "White"; self.black_name = "Black"
        self.engine_text = ""; self.overlays = []; self.move_list_text = []; self.current_move_index = 0

    def render(self):
        img = QImage(self.w, self.h, QImage.Format_ARGB32); img.fill(self.bg_color)
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)

        margin = 40; board_size = int(self.h * 0.85)
        
        # 1. Eval Bar
        bar_w = int(board_size * 0.04); bar_h = board_size
        bar_x = margin; bar_y = (self.h - board_size) // 2
        p.setPen(Qt.NoPen); p.setBrush(QColor(40,40,40)); p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 4, 4)
        eval_ratio = max(0.0, min(1.0, 0.5 + (self.eval_cp / 2000.0))); white_h = int(bar_h * eval_ratio)
        p.setBrush(QColor(240,240,240)); p.drawRoundedRect(bar_x, bar_y + bar_h - white_h, bar_w, white_h, 4, 4)
        p.setPen(QColor(30,30,30)); p.setFont(QFont("Arial", max(8, int(bar_w*0.8)), QFont.Bold))
        txt = f"M{int(abs(self.eval_cp)-10000)}" if abs(self.eval_cp) > 9000 else f"{self.eval_cp/100.0:+.1f}"
        p.drawText(QRectF(bar_x - 5, bar_y + bar_h//2 - 15, bar_w + 10, 30), Qt.AlignCenter, txt)

        # 2. Board
        board_x = bar_x + bar_w + margin; board_y = bar_y
        board_img = self.bw.render_to_image(board_size); p.drawImage(QRectF(board_x, board_y, board_size, board_size), board_img)

        # 3. Move List Panel
        ml_x = board_x + board_size + margin; ml_y = board_y; ml_w = self.w - ml_x - margin; ml_h = board_size
        p.setPen(Qt.NoPen); p.setBrush(QColor(40,40,40)); p.drawRoundedRect(ml_x, ml_y, ml_w, ml_h, 8, 8)
        p.setPen(QColor(200,200,200)); p.setFont(QFont("Consolas", 14))
        
        # Draw Moves
        x_off = 10; y_off = 15; line_h = 25; move_num_w = 40; san_w = 70
        for i, san in enumerate(self.move_list_text):
            is_curr = (i == self.current_move_index)
            if is_curr:
                p.setPen(Qt.NoPen); p.setBrush(QColor(80,120,200,150))
                p.drawRoundedRect(ml_x + x_off - 2, ml_y + y_off - 2, san_w + 4, line_h, 3, 3)
                p.setPen(QColor(255,255,255))
            else:
                p.setPen(QColor(180,180,180))

            if i % 2 == 0: # White move
                p.drawText(QRectF(ml_x + x_off, ml_y + y_off, move_num_w, line_h), Qt.AlignLeft, f"{i//2 + 1}.")
                p.drawText(QRectF(ml_x + x_off + move_num_w, ml_y + y_off, san_w, line_h), Qt.AlignLeft, san)
            else: # Black move
                p.drawText(QRectF(ml_x + x_off + move_num_w + san_w + 10, ml_y + y_off, san_w, line_h), Qt.AlignLeft, san)
            
            if i % 2 == 1:
                y_off += line_h; x_off = 10
                if y_off > ml_h - 20: break
            else:
                x_off = 0

        # 4. Names
        p.setPen(QColor(200,200,200)); p.setFont(QFont("Segoe UI", int(self.h * 0.025), QFont.Bold))
        top_name = self.black_name if not self.bw.flipped else self.white_name
        bot_name = self.white_name if not self.bw.flipped else self.black_name
        p.drawText(QRectF(board_x, board_y + board_size + 10, board_size/2, 40), Qt.AlignLeft | Qt.AlignVCenter, bot_name)
        p.drawText(QRectF(board_x, board_y - 50, board_size/2, 40), Qt.AlignLeft | Qt.AlignVCenter, top_name)

        if self.move_text:
            p.setFont(QFont("Segoe UI", int(self.h * 0.022))); p.setPen(QColor(170,170,170))
            p.drawText(QRectF(board_x + board_size/2, board_y + board_size + 10, board_size/2, 40), Qt.AlignRight | Qt.AlignVCenter, self.move_text)

        if self.engine_text:
            p.setFont(QFont("Segoe UI", int(self.h * 0.018))); p.setPen(QColor(100,170,255))
            p.drawText(QRectF(board_x + board_size/2, board_y - 45, board_size/2, 40), Qt.AlignRight | Qt.AlignVCenter, self.engine_text)

        for ov in self.overlays:
            if os.path.exists(ov['path']):
                ov_img = QImage(ov['path'])
                if not ov_img.isNull(): p.drawImage(QRectF(ov['x'], ov['y'], ov['w'], ov['h']), ov_img)
        p.end(); return img


class PGNLoadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("Load PGN"); self.setMinimumSize(600, 450)
        lay = QVBoxLayout(self); lay.addWidget(QLabel("Paste PGN below or load from file:"))
        self.text = QTextEdit(); self.text.setPlaceholderText("Paste PGN here…"); lay.addWidget(self.text)
        hb = QHBoxLayout(); fb = QPushButton("Load from File"); fb.clicked.connect(self._load_file)
        sb = QPushButton("Load Sample"); sb.clicked.connect(lambda: self.text.setPlainText(SAMPLE_PGN))
        hb.addWidget(fb); hb.addWidget(sb); lay.addLayout(hb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); lay.addWidget(bb)
    def _load_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open PGN", "", "PGN (*.pgn);;All (*)")
        if fn:
            with open(fn, 'r', encoding='utf-8', errors='ignore') as f: self.text.setPlainText(f.read())


class PromotionDialog(QDialog):
    def __init__(self, color, parent=None):
        super().__init__(parent); self.setWindowTitle("Promote Pawn"); self.setModal(True); self.result_piece = chess.QUEEN
        lay = QHBoxLayout(self); syms = {chess.QUEEN: "♛" if color == chess.BLACK else "♕", chess.ROOK: "♜" if color == chess.BLACK else "♖", chess.BISHOP: "♝" if color == chess.BLACK else "♗", chess.KNIGHT: "♞" if color == chess.BLACK else "♘"}
        for pt, sym in syms.items():
            b = QPushButton(sym); b.setFont(QFont("Segoe UI Symbol", 36)); b.setFixedSize(80, 80); b.clicked.connect(lambda _, p=pt: self._pick(p)); lay.addWidget(b)
    def _pick(self, pt): self.result_piece = pt; self.accept()


class ExportWorker(QThread):
    progress = Signal(int, str); finished = Signal(str)
    def __init__(self, frames, fps, out_path, res_w, res_h): 
        super().__init__(); self.frames = frames; self.fps = fps; self.out_path = out_path; self.res_w = res_w; self.res_h = res_h; self._cancel = False
    def cancel(self): self._cancel = True
    def run(self):
        if not HAS_CV2: self.finished.emit("ERROR: opencv-python missing."); return
        try:
            writer = cv2.VideoWriter(self.out_path, cv2.VideoWriter_fourcc(*'mp4v'), self.fps, (self.res_w, self.res_h))
            for i, frame in enumerate(self.frames):
                if self._cancel: writer.release(); os.remove(self.out_path); self.finished.emit("Cancelled."); return
                if frame.shape[:2] != (self.res_h, self.res_w): frame = cv2.resize(frame, (self.res_w, self.res_h))
                if frame.shape[2] == 4:
                    bgr = frame[:, :, :3]; a = frame[:, :, 3:]; bg = np.full_like(bgr, 32); alpha = a.astype(np.float32) / 255.0
                    frame = (bgr.astype(np.float32) * alpha + bg.astype(np.float32) * (1 - alpha)).astype(np.uint8)
                writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)); self.progress.emit(int((i + 1) / len(self.frames) * 100), f"Frame {i + 1}/{len(self.frames)}")
            writer.release(); self.finished.emit(f"Done!\nSaved to: {self.out_path}")
        except Exception as ex: self.finished.emit(f"Error: {ex}")


class ExportDialog(QDialog):
    def __init__(self, frames, parent=None):
        super().__init__(parent); self.setWindowTitle("Export Video"); self.setMinimumWidth(450); self.frames = frames; self.worker = None
        lay = QFormLayout(self); self.res_combo = QComboBox(); self.res_combo.addItems(["1920×1080 (1080p)", "1280×720 (720p)", "3840×2160 (4K)"]); lay.addRow("Resolution:", self.res_combo)
        self.fps_spin = QSpinBox(); self.fps_spin.setRange(1, 120); self.fps_spin.setValue(60); lay.addRow("Frame Rate:", self.fps_spin)
        self.path_edit = QLineEdit(); self.path_edit.setText(os.path.expanduser("~/chess_video.mp4"))
        brow = QHBoxLayout(); brow.addWidget(self.path_edit); bb = QPushButton("Browse…"); bb.clicked.connect(self._browse); brow.addWidget(bb); lay.addRow("Output:", brow)
        self.progress_bar = QProgressBar(); lay.addRow(self.progress_bar); self.status_label = QLabel(""); lay.addRow(self.status_label)
        self.export_btn = QPushButton("🎬  Export Video"); self.export_btn.clicked.connect(self._start_export); lay.addRow(self.export_btn)
        self.cancel_btn = QPushButton("Cancel"); self.cancel_btn.clicked.connect(self._cancel); self.cancel_btn.setEnabled(False); lay.addRow(self.cancel_btn)
    def _browse(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Save Video", self.path_edit.text(), "MP4 (*.mp4);;All (*)")
        if fn: self.path_edit.setText(fn)
    def _start_export(self):
        idx = self.res_combo.currentIndex(); w, h = [(1920, 1080), (1280, 720), (3840, 2160)][idx]; np_frames = []
        for f in self.frames: 
            ptr = f.constBits(); ptr.setsize(f.sizeInBytes()); np_frames.append(np.array(ptr).reshape(f.height(), f.width(), 4).copy())
        self.worker = ExportWorker(np_frames, self.fps_spin.value(), self.path_edit.text(), w, h)
        self.worker.progress.connect(lambda p, m: (self.progress_bar.setValue(p), self.status_label.setText(m)))
        self.worker.finished.connect(self._on_export_finished)
        self.export_btn.setEnabled(False); self.cancel_btn.setEnabled(True); self.worker.start()
    def _on_export_finished(self, m):
        self.status_label.setText(m); self.export_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        if "Done" in m: QMessageBox.information(self, "Export", m)
    def _cancel(self): 
        if self.worker: self.worker.cancel()


# ─── Main Window ────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("♟ Chess Video Maker Pro — AI Battle & Eval")
        self.setMinimumSize(1350, 850); self.resize(1500, 920)
        self.game = None; self.node = None; self.move_index = 0; self.move_list = []
        self._playing = False; self._anim_timer = QTimer(); self._anim_timer.setSingleShot(True); self._anim_timer.timeout.connect(self._play_step)
        self.engine_worker = None; self.capture_frames = []; self.video_bg_color = QColor(30, 30, 32)
        self.db_folder = ""; self.img_folder = ""; self.canvas_overlays = []
        self.ai_vs_ai_running = False; self.ai_battle_worker = None
        self.eval_cache = {}; self.batch_worker = None
        self._build_ui(); self._build_menu(); self._new_game()

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central); main_h = QHBoxLayout(central); main_h.setContentsMargins(6, 6, 6, 6)

        # LEFT: board + eval bar
        left = QHBoxLayout() 
        self.eval_bar_widget = EvalBarWidget()
        self.board_widget = ChessBoardWidget(); self.board_widget.squareClicked.connect(self._on_sq_click)
        left.addWidget(self.eval_bar_widget); left.addWidget(self.board_widget, stretch=1)

        # CENTER: Tabs
        center = QVBoxLayout(); self.tabs = QTabWidget()
        moves_w = QWidget(); moves_l = QVBoxLayout(moves_w)
        self.move_listbox = QListWidget(); self.move_listbox.currentRowChanged.connect(self._on_move_row); self.move_listbox.setFont(QFont("Consolas", 11)); moves_l.addWidget(self.move_listbox, stretch=1)
        nav = QGridLayout()
        for i, (t, fn) in enumerate([("⏮", self._go_first), ("◀", self._go_prev), ("▶", self._go_next), ("⏭", self._go_last)]):
            b = QPushButton(t); b.setFixedSize(52, 36); b.clicked.connect(fn); nav.addWidget(b, 0, i)
        self.btn_play = QPushButton("▶ Play"); self.btn_play.clicked.connect(self._toggle_play); nav.addWidget(self.btn_play, 0, 4, 1, 2)
        self.speed_slider = QSlider(Qt.Horizontal); self.speed_slider.setRange(1, 50); self.speed_slider.setValue(8); nav.addWidget(QLabel("Speed:"), 1, 0, 1, 2); nav.addWidget(self.speed_slider, 1, 2, 1, 4); moves_l.addLayout(nav)
        cg = QGroupBox("Annotation"); cl = QVBoxLayout(cg); self.anno_edit = QTextEdit(); self.anno_edit.setMaximumHeight(60); self.anno_edit.setPlaceholderText("Comment for YouTube overlay…"); cl.addWidget(self.anno_edit)
        ab = QPushButton("Apply Comment"); ab.clicked.connect(self._apply_comment); cl.addWidget(ab); moves_l.addWidget(cg); self.tabs.addTab(moves_w, "♜ Moves")

        db_w = QWidget(); db_l = QVBoxLayout(db_w); h_db = QHBoxLayout(); self.db_path_lbl = QLabel("Folder: None"); h_db.addWidget(self.db_path_lbl, stretch=1)
        db_browse = QPushButton("Browse PGN Folder"); db_browse.clicked.connect(self._browse_pgn_db); h_db.addWidget(db_browse); db_scan = QPushButton("Scan"); db_scan.clicked.connect(self._scan_pgn_db); h_db.addWidget(db_scan); db_l.addLayout(h_db)
        self.db_list = QListWidget(); self.db_list.itemDoubleClicked.connect(self._load_selected_pgn_db); db_l.addWidget(self.db_list, stretch=1)
        h_load = QHBoxLayout(); self.db_game_idx = QSpinBox(); self.db_game_idx.setRange(1, 100000); self.db_game_idx.setValue(1); h_load.addWidget(QLabel("Game # (In File):")); h_load.addWidget(self.db_game_idx)
        load_btn = QPushButton("Load Selected File"); load_btn.clicked.connect(self._load_selected_pgn_db); h_load.addWidget(load_btn); db_l.addLayout(h_load); self.tabs.addTab(db_w, "📂 PGN Database")

        img_w = QWidget(); img_l = QVBoxLayout(img_w); h_img = QHBoxLayout(); self.img_path_lbl = QLabel("Folder: None"); h_img.addWidget(self.img_path_lbl, stretch=1)
        img_browse = QPushButton("Browse Images"); img_browse.clicked.connect(self._browse_img_db); h_img.addWidget(img_browse); img_scan = QPushButton("Scan"); img_scan.clicked.connect(self._scan_img_db); h_img.addWidget(img_scan); img_l.addLayout(h_img)
        self.img_list = QListWidget(); self.img_list.setViewMode(QListWidget.IconMode); self.img_list.setIconSize(QSize(80, 80)); self.img_list.setResizeMode(QListWidget.Adjust); img_l.addWidget(self.img_list, stretch=1)
        ov_grp = QGroupBox("Add to Video Canvas"); ov_l = QFormLayout(ov_grp); self.ov_pos_combo = QComboBox(); self.ov_pos_combo.addItems(["White Player Face", "Black Player Face", "Center Logo", "Watermark (BR)"]); ov_l.addRow("Position:", self.ov_pos_combo)
        add_ov_btn = QPushButton("➕ Add Image Overlay"); add_ov_btn.clicked.connect(self._add_overlay); ov_l.addRow(add_ov_btn); rem_ov_btn = QPushButton("🗑 Clear All Overlays"); rem_ov_btn.clicked.connect(self._clear_overlays); ov_l.addRow(rem_ov_btn); img_l.addWidget(ov_grp); self.tabs.addTab(img_w, "🖼 Image Assets")
        center.addWidget(self.tabs)

        # RIGHT: settings & AI
        right = QVBoxLayout()
        vs_g = QGroupBox("⚔️ AI vs AI Battle"); vs_l = QFormLayout(vs_g)
        self.white_ai_combo = QComboBox(); self.white_ai_combo.addItems(AI_MAP.values()); vs_l.addRow("White AI:", self.white_ai_combo)
        self.white_ai_str = QSpinBox(); self.white_ai_str.setRange(1, 5000); self.white_ai_str.setValue(3); vs_l.addRow("W. Depth/Sims:", self.white_ai_str)
        self.black_ai_combo = QComboBox(); self.black_ai_combo.addItems(AI_MAP.values()); self.black_ai_combo.setCurrentIndex(1); vs_l.addRow("Black AI:", self.black_ai_combo)
        self.black_ai_str = QSpinBox(); self.black_ai_str.setRange(1, 5000); self.black_ai_str.setValue(100); vs_l.addRow("B. Depth/Sims:", self.black_ai_str)
        self.battle_delay = QSpinBox(); self.battle_delay.setRange(50, 5000); self.battle_delay.setValue(500); self.battle_delay.setSuffix("ms"); vs_l.addRow("Move Delay:", self.battle_delay)
        self.start_battle_btn = QPushButton("⚔️ Start Battle"); self.start_battle_btn.clicked.connect(self._start_ai_vs_ai); vs_l.addRow(self.start_battle_btn)
        self.stop_battle_btn = QPushButton("⏹ Stop Battle"); self.stop_battle_btn.clicked.connect(self._stop_ai_vs_ai); self.stop_battle_btn.setEnabled(False); vs_l.addRow(self.stop_battle_btn)
        right.addWidget(vs_g)

        ai_g = QGroupBox("🧠 AI Engine Lab (Analysis)"); ai_l = QVBoxLayout(ai_g)
        self.ai_combo = QComboBox(); self.ai_combo.addItems(AI_MAP.values()); self.ai_combo.currentTextChanged.connect(self._toggle_ai_ui); ai_l.addWidget(self.ai_combo)
        self.ai_stack = QStackedWidget()
        mm_w = QWidget(); mm_l = QFormLayout(mm_w); self.mm_depth = QSpinBox(); self.mm_depth.setRange(1, 4); self.mm_depth.setValue(3); mm_l.addRow("Depth:", self.mm_depth); self.ai_stack.addWidget(mm_w)
        mcts_w = QWidget(); mcts_l = QFormLayout(mcts_w); self.m_iters = QSpinBox(); self.m_iters.setRange(100, 5000); self.m_iters.setValue(500); self.m_iters.setSingleStep(100); mcts_l.addRow("Sims:", self.m_iters); self.ai_stack.addWidget(mcts_w)
        sf_w = QWidget(); sf_l = QFormLayout(sf_w); self.engine_path_edit = QLineEdit(); self.engine_path_edit.setPlaceholderText("Path to stockfish..."); sf_l.addRow("Path:", self.engine_path_edit); eb = QPushButton("Browse Engine"); eb.clicked.connect(self._browse_engine); sf_l.addRow(eb); self.ai_stack.addWidget(sf_w)
        ai_l.addWidget(self.ai_stack)
        self.run_ai_btn = QPushButton("🔬 Run Analysis"); self.run_ai_btn.clicked.connect(self._run_engine); ai_l.addWidget(self.run_ai_btn)
        self.eval_game_btn = QPushButton("📊 Eval Game (Fill Bar)"); self.eval_game_btn.clicked.connect(self._start_batch_eval); ai_l.addWidget(self.eval_game_btn)
        self.stop_eval_btn = QPushButton("⏹ Stop Eval"); self.stop_eval_btn.clicked.connect(self._stop_batch_eval); self.stop_eval_btn.setEnabled(False); ai_l.addWidget(self.stop_eval_btn)
        self.eval_label = QLabel("Eval: -"); self.pv_label = QLabel("Nodes: -"); self.policy_chk = QCheckBox("Show AI Policy"); self.policy_chk.setChecked(True)
        ai_l.addWidget(self.eval_label); ai_l.addWidget(self.pv_label); ai_l.addWidget(self.policy_chk)
        self.clear_policy_btn = QPushButton("Clear Policy Visuals"); self.clear_policy_btn.clicked.connect(self._clear_policy); ai_l.addWidget(self.clear_policy_btn); right.addWidget(ai_g)

        vg = QGroupBox("Video Canvas"); vgl = QFormLayout(vg)
        self.bg_color_btn = QPushButton("  "); self.bg_color_btn.setStyleSheet(f"background-color: {self.video_bg_color.name()};"); self.bg_color_btn.clicked.connect(self._pick_bg_color); vgl.addRow("Background:", self.bg_color_btn)
        self.white_name_edit = QLineEdit("White"); self.black_name_edit = QLineEdit("Black"); 
        self.white_name_edit.textChanged.connect(self._update_names); self.black_name_edit.textChanged.connect(self._update_names)
        vgl.addRow("White:", self.white_name_edit); vgl.addRow("Black:", self.black_name_edit); right.addWidget(vg)

        sg = QGroupBox("Capture Settings"); sl = QFormLayout(sg)
        self.theme_combo = QComboBox(); self.theme_combo.addItems(THEMES.keys()); self.theme_combo.currentTextChanged.connect(self._theme_changed); sl.addRow("Theme:", self.theme_combo)
        self.flip_btn = QPushButton("Flip Board"); self.flip_btn.clicked.connect(self._flip_board); sl.addRow(self.flip_btn)
        self.fps_spin = QSpinBox(); self.fps_spin.setRange(1, 120); self.fps_spin.setValue(60); sl.addRow("Export FPS:", self.fps_spin)
        self.anim_spin = QDoubleSpinBox(); self.anim_spin.setRange(0.0, 3.0); self.anim_spin.setValue(0.3); self.anim_spin.setSingleStep(0.1); self.anim_spin.setSuffix("s"); sl.addRow("Anim:", self.anim_spin)
        self.hold_spin = QDoubleSpinBox(); self.hold_spin.setRange(0.1, 10.0); self.hold_spin.setValue(1.5); self.hold_spin.setSingleStep(0.1); self.hold_spin.setSuffix("s"); sl.addRow("Hold:", self.hold_spin); right.addWidget(sg)

        capg = QGroupBox("Capture"); capl = QVBoxLayout(capg)
        self.auto_btn = QPushButton("🎬 Auto-Capture All"); self.auto_btn.clicked.connect(self._auto_capture); capl.addWidget(self.auto_btn)
        self.frame_count_lbl = QLabel("Frames: 0"); capl.addWidget(self.frame_count_lbl); self.clear_btn = QPushButton("Clear All Frames"); self.clear_btn.clicked.connect(self._clear_frames); capl.addWidget(self.clear_btn); right.addWidget(capg)
        self.export_btn = QPushButton("💾  Export Video"); self.export_btn.clicked.connect(self._export_video); self.export_btn.setStyleSheet("font-size:15px; padding:8px;"); right.addWidget(self.export_btn); right.addStretch()

        splitter = QSplitter(Qt.Horizontal); wl, wc, wr = QWidget(), QWidget(), QWidget(); wl.setLayout(left); wc.setLayout(center); wr.setLayout(right)
        splitter.addWidget(wl); splitter.addWidget(wc); splitter.addWidget(wr); splitter.setStretchFactor(0, 5); splitter.setStretchFactor(1, 3); splitter.setStretchFactor(2, 2); main_h.addWidget(splitter)
        self.statusBar().showMessage("Ready — Click '📊 Eval Game' to fill the Eval Bar for all moves!")

    def _build_menu(self):
        mb = self.menuBar(); fm = mb.addMenu("&File"); fm.addAction("New Game", QKeySequence("Ctrl+N"), self._new_game); fm.addAction("Load PGN…", QKeySequence("Ctrl+O"), self._load_pgn); fm.addSeparator(); fm.addAction("Exit", QKeySequence("Ctrl+Q"), self.close)
        vm = mb.addMenu("&View"); vm.addAction("Flip Board", QKeySequence("F"), self._flip_board)
        QShortcut(QKeySequence(Qt.Key_Left), self, self._go_prev); QShortcut(QKeySequence(Qt.Key_Right), self, self._go_next); QShortcut(QKeySequence(Qt.Key_Home), self, self._go_first); QShortcut(QKeySequence(Qt.Key_End), self, self._go_last); QShortcut(QKeySequence(Qt.Key_Space), self, self._toggle_play)

    # ── Core Navigation & Logic ───────────────────────────
    def _new_game(self):
        self.game = chess.pgn.Game(); self.node = self.game; self.move_index = -1; self.move_list = []; self.eval_cache = {}
        self._refresh_all()

    def _load_pgn(self):
        dlg = PGNLoadDialog(self)
        if dlg.exec() == QDialog.Accepted:
            try:
                game = chess.pgn.read_game(io.StringIO(dlg.text.toPlainText()))
                if game: self._load_pgn_data(game)
                else: QMessageBox.warning(self, "Error", "Invalid PGN.")
            except Exception as e: QMessageBox.warning(self, "Error", str(e))

    def _load_pgn_data(self, game):
        self.game = game; self.node = game; self.move_index = -1; self.eval_cache = {}
        self.move_list = list(game.mainline()); self._refresh_all(); self._go_last()
        self.eval_bar_widget.set_eval(0.0)

    def _refresh_all(self):
        self.board_widget.set_position(self.node.board() if self.node else chess.Board())
        self.eval_bar_widget.set_eval(self.eval_cache.get(self.node, 0.0))
        self._refresh_move_list()

    def _refresh_move_list(self):
        self.move_listbox.blockSignals(True); self.move_listbox.clear()
        for i, node in enumerate(self.move_list):
            b = node.parent.board(); san = node.san()
            eval_str = ""
            if node in self.eval_cache:
                ev = self.eval_cache[node]
                eval_str = f" ({f'M{int(abs(ev)-10000)}' if abs(ev) > 9000 else f'{ev/100.0:+.2f}'})"
            text = f"{b.fullmove_number}. {san}{eval_str}" if b.turn == chess.WHITE else f"{b.fullmove_number}… {san}{eval_str}"
            item = QListWidgetItem(text); self.move_listbox.addItem(item)
        if 0 <= self.move_index < self.move_listbox.count(): self.move_listbox.setCurrentRow(self.move_index)
        self.move_listbox.blockSignals(False)

    def _update_board(self):
        if self.node and self.node.parent:
            self.board_widget.set_position(self.node.parent.board(), self.node.move)
        else:
            self.board_widget.set_position(self.node.board() if self.node else chess.Board())
        self.eval_bar_widget.set_eval(self.eval_cache.get(self.node, 0.0))
        if 0 <= self.move_index < self.move_listbox.count(): 
            self.move_listbox.setCurrentRow(self.move_index)

    def _on_move_row(self, row):
        if 0 <= row < len(self.move_list):
            self.move_index = row; self.node = self.move_list[row]; self._update_board()

    def _go_first(self): self.node = self.game; self.move_index = -1; self._update_board()
    def _go_prev(self):
        if self.node and self.node.parent: self.node = self.node.parent; self.move_index -= 1; self._update_board()
    def _go_next(self):
        if self.node and self.node.variations: self.node = self.node.variations[0]; self.move_index += 1; self._update_board()
    def _go_last(self):
        while self.node and self.node.variations: self.node = self.node.variations[0]; self.move_index += 1
        self._update_board()

    def _toggle_play(self):
        self._playing = not self._playing
        self.btn_play.setText("⏸ Pause" if self._playing else "▶ Play")
        if self._playing: self._play_step()

    def _play_step(self):
        if not self._playing: return
        if self.node and self.node.variations:
            self._go_next(); QTimer.singleShot(int(3000 / self.speed_slider.value()), self._play_step)
        else: self._playing = False; self.btn_play.setText("▶ Play")

    def _on_sq_click(self, sq):
        if self.ai_vs_ai_running: return
        board = self.board_widget.board
        if self.board_widget.selected_sq is None:
            if board.piece_at(sq) and board.piece_at(sq).color == board.turn:
                self.board_widget.selected_sq = sq; self.board_widget.legal_targets = [m.to_square for m in board.legal_moves if m.from_square == sq]; self.board_widget.update()
        else:
            from_sq = self.board_widget.selected_sq; move = chess.Move(from_sq, sq)
            if board.piece_at(from_sq).piece_type == chess.PAWN and sq in [chess.A8, chess.B8, chess.C8, chess.D8, chess.E8, chess.F8, chess.G8, chess.H8, chess.A1, chess.B1, chess.C1, chess.D1, chess.E1, chess.F1, chess.G1, chess.H1]:
                dlg = PromotionDialog(board.turn, self); dlg.exec(); move.promotion = dlg.result_piece
            if move in board.legal_moves:
                self.node = self.node.add_variation(move); self.move_list = list(self.game.mainline()); self.move_index += 1
                self.board_widget.selected_sq = None; self.board_widget.legal_targets = []
                self._update_board(); self._refresh_move_list()
            else:
                self.board_widget.selected_sq = None; self.board_widget.legal_targets = []; self.board_widget.update()

    def _flip_board(self): self.board_widget.flipped = not self.board_widget.flipped; self.board_widget.update()
    def _theme_changed(self, t): self.board_widget.set_theme(THEMES.get(t, BoardTheme()))
    def _apply_comment(self): 
        if self.node: self.node.comment = self.anno_edit.toPlainText(); self.statusBar().showMessage("Comment applied.")
    def _pick_bg_color(self):
        c = QColorDialog.getColor(self.video_bg_color, self)
        if c.isValid(): self.video_bg_color = c; self.bg_color_btn.setStyleSheet(f"background-color: {c.name()};")
    def _update_names(self): pass
    def _clear_policy(self): self.board_widget.policy_vis = {}; self.board_widget.update()

    # ── Database & Assets Logic ──────────────────────────
    def _browse_pgn_db(self):
        d = QFileDialog.getExistingDirectory(self, "Select PGN Database Folder")
        if d: self.db_folder = d; self.db_path_lbl.setText(f"Folder: {d}"); self._scan_pgn_db()
    def _scan_pgn_db(self):
        if not self.db_folder: return
        self.db_list.clear(); QApplication.processEvents()
        files = glob.glob(os.path.join(self.db_folder, "**/*.pgn"), recursive=True)
        for f in files: self.db_list.addItem(os.path.basename(f))
    def _load_selected_pgn_db(self, item=None):
        if not item and self.db_list.currentItem() is None: return
        filename = item.text() if item else self.db_list.currentItem().text(); filepath = os.path.join(self.db_folder, filename); game_idx = self.db_game_idx.value() - 1
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                game = None
                for i in range(game_idx + 1):
                    game = chess.pgn.read_game(f)
                    if game is None: break
                if game: self._load_pgn_data(game)
                else: QMessageBox.warning(self, "Error", f"Game index {game_idx+1} not found.")
        except Exception as e: QMessageBox.warning(self, "Error", str(e))
    def _browse_img_db(self):
        d = QFileDialog.getExistingDirectory(self, "Select Image Assets Folder")
        if d: self.img_folder = d; self.img_path_lbl.setText(f"Folder: {d}"); self._scan_img_db()
    def _scan_img_db(self):
        if not self.img_folder: return
        self.img_list.clear(); QApplication.processEvents()
        files = glob.glob(os.path.join(self.img_folder, "**/*.*"), recursive=True); valid_ext = ['.png', '.jpg', '.jpeg', '.bmp']; count = 0
        for f in files:
            if os.path.splitext(f)[1].lower() in valid_ext:
                pixmap = QPixmap(f)
                if not pixmap.isNull(): icon = QIcon(pixmap); item = QListWidgetItem(icon, os.path.basename(f)); item.setData(Qt.UserRole, f); self.img_list.addItem(item); count += 1
    def _add_overlay(self):
        item = self.img_list.currentItem()
        if not item: return
        path = item.data(Qt.UserRole); pos = self.ov_pos_combo.currentText(); size = 100
        if pos == "White Player Face": x, y = 50, 980
        elif pos == "Black Player Face": x, y = 50, 30
        elif pos == "Center Logo": x, y = 860, 440; size = 200
        else: x, y = 1800, 960
        self.canvas_overlays.append({'path': path, 'x': x, 'y': y, 'w': size, 'h': size})
    def _clear_overlays(self): self.canvas_overlays.clear()

    # ── AI vs AI Logic ──────────────────────────────────
    def _start_ai_vs_ai(self):
        self.ai_vs_ai_running = True; self.start_battle_btn.setEnabled(False); self.stop_battle_btn.setEnabled(True)
        self._make_ai_vs_ai_move()
    def _stop_ai_vs_ai(self):
        self.ai_vs_ai_running = False; self.start_battle_btn.setEnabled(True); self.stop_battle_btn.setEnabled(False)
        if self.ai_battle_worker and self.ai_battle_worker.isRunning(): self.ai_battle_worker.terminate(); self.ai_battle_worker = None
    def _make_ai_vs_ai_move(self):
        if not self.ai_vs_ai_running or self.board_widget.board.is_game_over(): self._stop_ai_vs_ai(); return
        is_white_turn = self.board_widget.board.turn == chess.WHITE
        engine_type = self.white_ai_combo.currentText() if is_white_turn else self.black_ai_combo.currentText()
        strength = self.white_ai_str.value() if is_white_turn else self.black_ai_str.value()
        params = {}
        if "Minimax" in engine_type: params["depth"] = strength
        elif "MCTS" in engine_type: params["iterations"] = strength
        else: 
            params["path"] = self.engine_path_edit.text()
            if not os.path.exists(params["path"]): self.statusBar().showMessage("Stockfish path invalid."); self._stop_ai_vs_ai(); return
        self.statusBar().showMessage(f"AI Battle: {engine_type} thinking...")
        self.ai_battle_worker = AIWorker(engine_type, self.board_widget.board.fen(), params)
        self.ai_battle_worker.eval_ready.connect(self._on_ai_vs_ai_move); self.ai_battle_worker.start()
    def _on_ai_vs_ai_move(self, result):
        if not self.ai_vs_ai_running: return
        best_move_uci = result.get("best_move"); eval_cp = result.get("eval_cp", 0.0)
        if best_move_uci:
            move = chess.Move.from_uci(best_move_uci)
            if move in self.board_widget.board.legal_moves:
                self.node = self.node.add_variation(move); self.move_list = list(self.game.mainline()); self.move_index += 1
                self.eval_cache[self.node] = eval_cp; self._update_board(); self._refresh_move_list()
                if self.ai_vs_ai_running: QTimer.singleShot(self.battle_delay.value(), self._make_ai_vs_ai_move)
                return
        self._stop_ai_vs_ai()

    # ── Batch Eval Logic ──────────────────────────────────
    def _start_batch_eval(self):
        if not self.move_list: return
        engine_type = self.ai_combo.currentText(); params = {}
        if "Minimax" in engine_type: params["depth"] = self.mm_depth.value()
        elif "MCTS" in engine_type: params["iterations"] = self.m_iters.value()
        else: 
            params["path"] = self.engine_path_edit.text()
            if not os.path.exists(params["path"]): QMessageBox.warning(self, "Error", "Stockfish path invalid."); return
        self.eval_game_btn.setEnabled(False); self.stop_eval_btn.setEnabled(True)
        self.batch_worker = BatchEvalWorker(self.move_list, engine_type, params)
        self.batch_worker.move_evaluated.connect(self._on_move_evaluated)
        self.batch_worker.finished.connect(self._batch_eval_finished); self.batch_worker.start()
    def _stop_batch_eval(self):
        if self.batch_worker and self.batch_worker.isRunning(): self.batch_worker.cancel()
        self.eval_game_btn.setEnabled(True); self.stop_eval_btn.setEnabled(False)
    def _on_move_evaluated(self, index, eval_cp, eval_str):
        if 0 <= index < len(self.move_list):
            self.eval_cache[self.move_list[index]] = eval_cp; self._refresh_move_list()
        if self.move_index == index: self._update_board()
    def _batch_eval_finished(self):
        self.eval_game_btn.setEnabled(True); self.stop_eval_btn.setEnabled(False); self.statusBar().showMessage("✅ Eval Done!")

    # ── Analysis AI Logic ────────────────────────────────
    def _toggle_ai_ui(self, text):
        if "Minimax" in text: self.ai_stack.setCurrentIndex(0)
        elif "MCTS" in text: self.ai_stack.setCurrentIndex(1)
        else: self.ai_stack.setCurrentIndex(2)
    def _browse_engine(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Select Stockfish Binary")
        if fn: self.engine_path_edit.setText(fn)
    def _run_engine(self):
        if self.engine_worker and self.engine_worker.isRunning(): return
        engine_type = self.ai_combo.currentText(); params = {}
        if "Minimax" in engine_type: params["depth"] = self.mm_depth.value()
        elif "MCTS" in engine_type: params["iterations"] = self.m_iters.value()
        else: params["path"] = self.engine_path_edit.text()
        if "Stockfish" in engine_type and not os.path.exists(params["path"]): QMessageBox.warning(self, "Error", "Invalid Path."); return
        self.run_ai_btn.setEnabled(False); self.statusBar().showMessage("Running Analysis...")
        self.engine_worker = AIWorker(engine_type, self.board_widget.board.fen(), params); self.engine_worker.eval_ready.connect(self._on_ai_done); self.engine_worker.start()
    def _on_ai_done(self, result):
        self.run_ai_btn.setEnabled(True); self.eval_label.setText(f"Eval: {result.get('eval', '-')}")
        self.pv_label.setText(f"Nodes: {result.get('nodes', 0)}")
        if self.policy_chk.isChecked(): self.board_widget.policy_vis = result.get("policy", {}); self.board_widget.update()
        self.eval_cache[self.node] = result.get("eval_cp", 0.0); self.eval_bar_widget.set_eval(result.get("eval_cp", 0.0))
        self.statusBar().showMessage("Analysis complete.")

    # ── Capture & Export Logic ───────────────────────────
    def _auto_capture(self):
        self.capture_frames.clear(); self.statusBar().showMessage("Capturing frames..."); QApplication.processEvents()
        canvas = VideoCanvas(self.board_widget, self.eval_bar_widget, bg_color=self.video_bg_color)
        canvas.white_name = self.white_name_edit.text(); canvas.black_name = self.black_name_edit.text()
        canvas.overlays = self.canvas_overlays
        node = self.game; move_idx = -1; san_list = []
        
        # Initial Position Frame
        self.board_widget.set_position(node.board()); canvas.eval_cp = self.eval_cache.get(node, 0.0)
        canvas.move_list_text = []; canvas.current_move_index = -1
        for _ in range(int(self.hold_spin.value() * 60)): self.capture_frames.append(canvas.render())
        
        while node.variations:
            node = node.variations[0]; move_idx += 1; san_list.append(node.san())
            self.board_widget.set_position(node.parent.board(), node.move)
            canvas.eval_cp = self.eval_cache.get(node, 0.0); canvas.move_list_text = san_list; canvas.current_move_index = move_idx
            canvas.move_text = node.san()
            for _ in range(int(self.hold_spin.value() * 60)): self.capture_frames.append(canvas.render())

        self._update_board(); self.frame_count_lbl.setText(f"Frames: {len(self.capture_frames)}")
        self.statusBar().showMessage(f"Captured {len(self.capture_frames)} frames.")

    def _clear_frames(self): self.capture_frames.clear(); self.frame_count_lbl.setText("Frames: 0")
    def _export_video(self):
        if not self.capture_frames: QMessageBox.warning(self, "Error", "No frames. Auto-Capture first."); return
        dlg = ExportDialog(self.capture_frames, self); dlg.exec()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())