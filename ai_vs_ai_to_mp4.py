#!/usr/bin/env python3
"""
AI vs AI → MP4 — Chess AI battle with live preview, video export, and professional sound design.

Standalone application. No other project files required.

Usage:
    python ai_vs_ai_to_mp4.py

Requirements:
    pip install PySide6 chess opencv-python numpy
"""

import os
import sys
import io
import math
import time
import random
import shutil
import logging
import subprocess
import tempfile
import atexit
import struct
import wave

import chess
import chess.pgn

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
    QGroupBox, QLineEdit, QComboBox,
    QFormLayout, QProgressBar,
    QFileDialog, QSizePolicy, QMessageBox, QSlider, QCheckBox, QScrollArea
)
from PySide6.QtCore import (
    Qt, QObject, QThread, Signal, QRectF, QPointF, QTimer,
    Property, QPropertyAnimation, QEasingCurve, QUrl
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QImage, QLinearGradient,
    QPainterPath, QPen, QRadialGradient, QIcon
)

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
    HAS_NUMPY = True
except ImportError:
    HAS_CV2 = False
    HAS_NUMPY = False

try:
    from PySide6.QtMultimedia import QSoundEffect
    HAS_QTMULTIMEDIA = True
except ImportError:
    HAS_QTMULTIMEDIA = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AIvsAI2MP4")


# ════════════════════════════════════════════════════════════════════
#  Constants
# ════════════════════════════════════════════════════════════════════

PIECE_SYM = {
    (chess.PAWN, chess.WHITE): "♙", (chess.PAWN, chess.BLACK): "♟",
    (chess.KNIGHT, chess.WHITE): "♘", (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.WHITE): "♗", (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK, chess.WHITE): "♖", (chess.ROOK, chess.BLACK): "♜",
    (chess.QUEEN, chess.WHITE): "♕", (chess.QUEEN, chess.BLACK): "♛",
    (chess.KING, chess.WHITE): "♔", (chess.KING, chess.BLACK): "♚",
}

RESOLUTION_SIZES = {
    "1920×1080": (1920, 1080),
    "1280×720": (1280, 720),
    "1080×1920 (Short)": (1080, 1920),
    "720×1280 (Short)": (720, 1280),
}
RESOLUTION_LIST = list(RESOLUTION_SIZES.keys())

GAME_NORMAL = "normal"
GAME_CHECKMATE = "checkmate"
GAME_STALEMATE = "stalemate"
GAME_DRAW = "draw"
GAME_INSUFFICIENT = "insufficient"

AI_MAP = {0: "Minimax (Alpha-Beta)", 1: "MCTS (Monte Carlo)", 2: "Stockfish (UCI)"}

SND_MOVE      = "move"
SND_CAPTURE   = "capture"
SND_CHECK     = "check"
SND_CASTLE    = "castle"
SND_CHECKMATE = "checkmate"
SND_STALEMATE = "stalemate"
SND_DRAW      = "draw"
SND_GAME_START = "game_start"
SND_UI_CLICK  = "ui_click"

SOUND_THEME_LIST = ["Classic", "Digital", "Cinematic", "Retro", "Ambient"]


class BoardTheme:
    def __init__(
        self,
        name="Classic",
        light=(240, 217, 181),
        dark=(181, 136, 99),
        border=(48, 26, 7),
        highlight=(255, 255, 0, 100),
        last_move=(155, 199, 0, 100),
        arrow=(220, 50, 47, 200),
    ):
        self.name = name
        self.light_sq = QColor(*light)
        self.dark_sq = QColor(*dark)
        self.border = QColor(*border)
        self.highlight = QColor(*highlight)
        self.last_move = QColor(*last_move)
        self.arrow_clr = QColor(*arrow)
        self.bg = QColor(32, 32, 36)
        self.coord = QColor(180, 160, 130)


THEMES = {
    "Classic": BoardTheme(),
    "Blue": BoardTheme("Blue", (208, 224, 243), (116, 150, 194), (40, 50, 70)),
    "Green": BoardTheme("Green", (238, 238, 210), (118, 150, 86), (50, 60, 40)),
    "Brown": BoardTheme("Brown", (222, 197, 165), (170, 120, 70), (60, 35, 15)),
}


def find_stockfish():
    for name in ("stockfish", "stockfish.exe"):
        p = shutil.which(name)
        if p: return p
    candidates = [
        "/usr/games/stockfish", "/usr/local/bin/stockfish",
        "/opt/homebrew/bin/stockfish", "/usr/bin/stockfish", "/snap/bin/stockfish",
    ]
    if sys.platform == "win32":
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local_app_data = os.environ.get("LOCALAPPDATA", r"C:\Users")
        candidates.extend([
            r"C:\Stockfish", r"C:\stockfish",
            os.path.join(program_files, "Stockfish"),
            os.path.join(program_files_x86, "Stockfish"),
            os.path.join(local_app_data, "Programs", "Stockfish"),
        ])
    for d in candidates:
        if os.path.isfile(d): return d
        if os.path.isdir(d):
            try:
                for f in os.listdir(d):
                    fl = f.lower()
                    if fl.startswith("stockfish") and fl.endswith(".exe"):
                        return os.path.join(d, f)
            except OSError: pass
    return None


# ════════════════════════════════════════════════════════════════════
#  AI Engines
# ════════════════════════════════════════════════════════════════════

class HeuristicEvaluator:
    PV = {
        chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
        chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 20000,
    }
    PT = [
        0, 0, 0, 0, 0, 0, 0, 0,
        5, 10, 10, -20, -20, 10, 10, 5,
        5, -5, -10, 0, 0, -10, -5, 5,
        0, 0, 0, 20, 20, 0, 0, 0,
        5, 5, 10, 25, 25, 10, 5, 5,
        10, -5, 0, 10, 10, 0, -5, 10,
        -15, -15, -20, -5, -5, -20, -15, -15,
        0, 0, 0, 0, 0, 0, 0, 0,
    ]

    def evaluate(self, board):
        if board.is_checkmate():
            return -10000 if board.turn == chess.WHITE else 10000
        if board.is_stalemate() or board.is_insufficient_material():
            return 0
        score = 0
        for sq in chess.SQUARES:
            pc = board.piece_at(sq)
            if pc:
                v = self.PV[pc.piece_type]
                if pc.piece_type == chess.PAWN:
                    idx = sq if pc.color == chess.WHITE else chess.square_mirror(sq)
                    v += self.PT[idx]
                score += v if pc.color == chess.WHITE else -v
        return score


class MinimaxEngine:
    def __init__(self):
        self.ev = HeuristicEvaluator()
        self.nodes = 0

    def search(self, board, depth):
        self.nodes = 0
        best_move = None
        alpha = -float("inf")
        beta = float("inf")
        best_eval = -float("inf")
        policy = {}
        for move in board.legal_moves:
            board.push(move)
            eval_score = -self._negamax(board, depth - 1, -beta, -alpha)
            board.pop()
            policy[move.uci()] = eval_score
            if eval_score > best_eval:
                best_eval = eval_score
                best_move = move
            alpha = max(alpha, eval_score)
        if policy:
            mn, mx = min(policy.values()), max(policy.values())
            rng = mx - mn if mx != mn else 1
            policy = {k: (v - mn) / rng for k, v in policy.items()}
        final_eval = best_eval if board.turn == chess.WHITE else -best_eval
        return best_move, final_eval, self.nodes, policy

    def _negamax(self, board, depth, alpha, beta):
        self.nodes += 1
        if depth == 0 or board.is_game_over():
            ev = self.ev.evaluate(board)
            return ev if board.turn == chess.WHITE else -ev
        for move in board.legal_moves:
            board.push(move)
            eval_score = -self._negamax(board, depth - 1, -beta, -alpha)
            board.pop()
            if eval_score >= beta: return beta
            if eval_score > alpha: alpha = eval_score
        return alpha


class MCTSNode:
    def __init__(self, board, parent=None, move=None):
        self.board = board
        self.parent = parent
        self.move = move
        self.children = []
        self.wins = 0.0
        self.visits = 0
        self.untried = list(board.legal_moves)

    def ucb1(self, c=1.414):
        if self.visits == 0: return float("inf")
        return (self.wins / self.visits) + c * math.sqrt(math.log(self.parent.visits) / self.visits)

    def best_child(self): return max(self.children, key=lambda x: x.ucb1())

    def expand(self):
        move = self.untried.pop()
        new_board = self.board.copy()
        new_board.push(move)
        child = MCTSNode(new_board, self, move)
        self.children.append(child)
        return child


class MCTSEngine:
    def __init__(self):
        self.ev = HeuristicEvaluator()

    def search(self, board, iterations):
        root = MCTSNode(board)
        for _ in range(iterations):
            node = root
            while not node.untried and node.children:
                node = node.best_child()
            if node.untried:
                node = node.expand()
            score = self._rollout(node.board)
            while node:
                node.visits += 1
                node.wins += score if node.board.turn != board.turn else (1 - score)
                node = node.parent
        best_move = max(root.children, key=lambda c: c.visits).move if root.children else None
        policy = {}
        if root.children:
            total_visits = sum(c.visits for c in root.children)
            policy = {c.move.uci(): c.visits / total_visits if total_visits else 0 for c in root.children}
        return best_move, self.ev.evaluate(board), root.visits, policy

    def _rollout(self, board, depth=10):
        if board.is_checkmate(): return 0.0 if board.turn == chess.WHITE else 1.0
        if board.is_stalemate(): return 0.5
        if depth == 0: return 1.0 / (1.0 + math.exp(-0.004 * self.ev.evaluate(board)))
        move = random.choice(list(board.legal_moves))
        board.push(move)
        score = self._rollout(board, depth - 1)
        board.pop()
        return score


# ════════════════════════════════════════════════════════════════════
#  BoardRenderer
# ════════════════════════════════════════════════════════════════════

class BoardRenderer:
    def __init__(self, board=None, theme=None, flipped=False):
        self.board = board or chess.Board()
        self.theme = theme or BoardTheme()
        self.flipped = flipped
        self.show_coords = True
        self.selected_sq = None
        self.legal_targets: list = []
        self.last_move = None
        self.highlighted: set = set()
        self.arrows: list = []
        self.anim_move = None
        self.anim_rook_move = None
        self.anim_progress = 1.0
        self._check_square = None
        self._check_opacity = 0.0
        self.policy_vis: dict = {}

    def render(self, size=1080):
        img = QImage(size, size, QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        m = size * 0.05 if self.show_coords else 0
        sz = (size - 2 * m) / 8
        self._paint(p, size, m, sz)
        p.end()
        return img

    def _sq_rect(self, sq, t, m, sz):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        c = (7 - f) if self.flipped else f
        rw = r if self.flipped else (7 - r)
        return QRectF(m + c * sz, m + rw * sz, sz, sz)

    def _paint(self, p, t, m, sz):
        p.fillRect(QRectF(0, 0, t, t), self.theme.bg)
        p.setPen(Qt.NoPen)
        p.setBrush(self.theme.border)
        p.drawRect(QRectF(0, 0, t, t))

        for s in chess.SQUARES:
            rect = self._sq_rect(s, t, m, sz)
            f, r = chess.square_file(s), chess.square_rank(s)
            base = self.theme.light_sq if (f + r) % 2 == 0 else self.theme.dark_sq
            p.fillRect(rect, base)
            if self.last_move and s in (self.last_move.from_square, self.last_move.to_square):
                p.fillRect(rect, self.theme.last_move)
            if s == self.selected_sq:
                p.fillRect(rect, self.theme.highlight)
            if s in self.highlighted:
                p.fillRect(rect, QColor(0, 130, 255, 80))

        if self._check_square is not None and self._check_opacity > 0:
            p.fillRect(self._sq_rect(self._check_square, t, m, sz), QColor(255, 30, 30, int(self._check_opacity * 130)))

        if self.show_coords:
            fnt = QFont("Arial", max(7, int(sz * 0.14)))
            fnt.setBold(True)
            p.setFont(fnt)
            p.setPen(self.theme.coord)
            for i in range(8):
                fl = chr(ord("h") - i if self.flipped else ord("a") + i)
                rn = str(i + 1 if self.flipped else 8 - i)
                p.drawText(QRectF(m + i * sz + sz / 2 - sz / 2, t - m, sz, m), Qt.AlignCenter, fl)
                p.drawText(QRectF(0, m + i * sz, m, sz), Qt.AlignCenter, rn)

        ats = self.anim_move.to_square if self.anim_move else None
        rts = self.anim_rook_move[1] if self.anim_rook_move else None

        for s in chess.SQUARES:
            pc = self.board.piece_at(s)
            if pc:
                if self.anim_move and s == ats: continue
                if self.anim_rook_move and s == rts: continue
                self._draw_piece(p, pc, self._sq_rect(s, t, m, sz), sz)

        if self.anim_move:
            pc = self.board.piece_at(self.anim_move.to_square)
            if pc:
                pr = self.anim_progress
                lift = 4.0 * pr * (1.0 - pr) * 0.18
                scale = 1.0 + 4.0 * pr * (1.0 - pr) * 0.1
                rf = self._sq_rect(self.anim_move.from_square, t, m, sz)
                rt = self._sq_rect(self.anim_move.to_square, t, m, sz)
                x = rf.x() + (rt.x() - rf.x()) * pr
                y = rf.y() + (rt.y() - rf.y()) * pr - (sz * lift)
                w = sz * scale
                h = sz * scale
                p.setPen(Qt.NoPen)
                shadow_opacity = 30 + int(70 * (lift / 0.18))
                p.setBrush(QColor(0, 0, 0, shadow_opacity))
                shadow_y = rf.y() + (rt.y() - rf.y()) * pr + (sz * 0.85)
                p.drawEllipse(QRectF(x + (w - sz*0.7)/2, shadow_y, sz*0.7, sz*0.15))
                self._draw_piece(p, pc, QRectF(x, y, w, h), sz * scale)

        if self.anim_rook_move:
            rfs, rts_val = self.anim_rook_move
            pc = self.board.piece_at(rts_val)
            if pc:
                pr = self.anim_progress
                lift = 4.0 * pr * (1.0 - pr) * 0.12
                scale = 1.0 + 4.0 * pr * (1.0 - pr) * 0.06
                rf = self._sq_rect(rfs, t, m, sz)
                rt = self._sq_rect(rts_val, t, m, sz)
                x = rf.x() + (rt.x() - rf.x()) * pr
                y = rf.y() + (rt.y() - rf.y()) * pr - (sz * lift)
                w = sz * scale
                h = sz * scale
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 30 + int(50 * (lift / 0.12))))
                shadow_y = rf.y() + (rt.y() - rf.y()) * pr + (sz * 0.85)
                p.drawEllipse(QRectF(x + (w - sz*0.7)/2, shadow_y, sz*0.7, sz*0.15))
                self._draw_piece(p, pc, QRectF(x, y, w, h), sz * scale)

    def _draw_piece(self, p, piece, rect, sz):
        sym = PIECE_SYM.get((piece.piece_type, piece.color), "?")
        fnt = QFont("Segoe UI Symbol", sz * 0.72)
        fnt.setStyleStrategy(QFont.PreferAntialias)
        p.setFont(fnt)
        if piece.color == chess.WHITE:
            p.setPen(QPen(QColor(0, 0, 0, 200), max(1, sz * 0.04)))
            p.drawText(rect, Qt.AlignCenter, sym)
            p.setPen(QColor(255, 255, 255))
            p.drawText(rect, Qt.AlignCenter, sym)
        else:
            p.setPen(QColor(30, 30, 30))
            p.drawText(rect, Qt.AlignCenter, sym)


# ════════════════════════════════════════════════════════════════════
#  Move List Renderer
# ════════════════════════════════════════════════════════════════════

def render_movelist_2col(p, mx, my, mw, mh, move_list_text, current_move_index):
    if mw < 160 or mh < 80: return
    p.setPen(QPen(QColor(52, 52, 60), 1.2))
    p.setBrush(QColor(26, 26, 30))
    p.drawRoundedRect(QRectF(mx, my, mw, mh), 8, 8)

    hh = 34
    hr = QRectF(mx + 1, my + 1, mw - 2, hh)
    hg = QLinearGradient(hr.topLeft(), hr.bottomLeft())
    hg.setColorAt(0.0, QColor(52, 52, 60))
    hg.setColorAt(1.0, QColor(40, 40, 48))
    p.setPen(Qt.NoPen)
    p.setBrush(hg)
    cr = 7
    hp = QPainterPath()
    hp.moveTo(hr.left(), hr.bottom())
    hp.lineTo(hr.left(), hr.top() + cr)
    hp.quadTo(hr.left(), hr.top(), hr.left() + cr, hr.top())
    hp.lineTo(hr.right() - cr, hr.top())
    hp.quadTo(hr.right(), hr.top(), hr.right(), hr.top() + cr)
    hp.lineTo(hr.right(), hr.bottom())
    hp.closeSubpath()
    p.drawPath(hp)

    p.setFont(QFont("Segoe UI", 10, QFont.Bold))
    p.setPen(QColor(175, 175, 192))
    p.drawText(QRectF(mx + 14, my + 1, mw - 28, hh), Qt.AlignVCenter | Qt.AlignLeft, "♟  MOVES")
    p.setPen(QPen(QColor(64, 64, 74), 0.8))
    p.drawLine(QPointF(mx + 8, my + hh + 1), QPointF(mx + mw - 8, my + hh + 1))

    pairs = []
    i = 0
    while i < len(move_list_text):
        num = i // 2 + 1
        wm = move_list_text[i]
        bm = move_list_text[i + 1] if i + 1 < len(move_list_text) else None
        pairs.append((num, wm, bm, i, i + 1 if bm is not None else -1))
        i += 2

    if not pairs:
        p.setFont(QFont("Segoe UI", 9))
        p.setPen(QColor(90, 90, 108))
        p.drawText(QRectF(mx, my + hh, mw, mh - hh), Qt.AlignCenter, "No moves yet")
        return

    pad_x, pad_top = 10, 6
    line_h = 26
    content_y = my + hh + pad_top
    content_h = mh - hh - pad_top * 2
    rows_avail = max(1, int(content_h / line_h))
    col_gap = 16
    min_col_w = 160
    max_cols_by_width = max(1, int((mw - pad_x * 2 + col_gap) / (min_col_w + col_gap)))
    required_cols = 1
    if len(pairs) > rows_avail:
        required_cols = math.ceil(len(pairs) / rows_avail)
    num_cols = min(max_cols_by_width, required_cols)
    pairs_per_col = max(1, math.ceil(len(pairs) / num_cols))
    col_w = (mw - pad_x * 2 - col_gap * (num_cols - 1)) / num_cols

    start_pair = 0
    if current_move_index >= 0:
        current_pair = current_move_index // 2
        if current_pair >= rows_avail:
            start_pair = current_pair - rows_avail + 1
            start_pair = max(0, min(start_pair, len(pairs) - rows_avail))

    for ci in range(num_cols):
        cx = mx + pad_x + ci * (col_w + col_gap)
        start = ci * pairs_per_col + start_pair
        end = min(start + pairs_per_col, len(pairs))
        num_w = 30
        move_w = (col_w - num_w - 12) / 2
        w_x = cx + num_w + 4
        b_x = w_x + move_w + 4

        for row in range(end - start):
            pidx = start + row
            if pidx >= len(pairs): break
            num, wm, bm, widx, bidx = pairs[pidx]
            ry = content_y + row * line_h
            if row % 2 == 0:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(34, 34, 42, 110))
                p.drawRoundedRect(QRectF(cx - 2, ry, col_w + 4, line_h - 1), 3, 3)
            is_cur_row = (widx == current_move_index or bidx == current_move_index)
            if is_cur_row:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(42, 100, 195, 50))
                p.drawRoundedRect(QRectF(cx - 2, ry, col_w + 4, line_h - 1), 3, 3)
            p.setFont(QFont("Consolas", 9))
            p.setPen(QColor(88, 88, 108))
            p.drawText(QRectF(cx, ry, num_w, line_h - 1), Qt.AlignVCenter | Qt.AlignRight, f"{num}.")
            is_wc = (widx == current_move_index)
            if is_wc:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(48, 120, 218, 85))
                p.drawRoundedRect(QRectF(w_x - 3, ry + 2, move_w + 6, line_h - 5), 4, 4)
            p.setFont(QFont("Consolas", 11, QFont.Bold if is_wc else QFont.Normal))
            p.setPen(QColor(90, 172, 255) if is_wc else QColor(212, 212, 222))
            p.drawText(QRectF(w_x, ry, move_w, line_h - 1), Qt.AlignVCenter | Qt.AlignLeft, wm)
            if bm is not None:
                is_bc = (bidx == current_move_index)
                if is_bc:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(48, 120, 218, 85))
                    p.drawRoundedRect(QRectF(b_x - 3, ry + 2, move_w + 6, line_h - 5), 4, 4)
                p.setFont(QFont("Consolas", 11, QFont.Bold if is_bc else QFont.Normal))
                p.setPen(QColor(90, 172, 255) if is_bc else QColor(212, 212, 222))
                p.drawText(QRectF(b_x, ry, move_w, line_h - 1), Qt.AlignVCenter | Qt.AlignLeft, bm)

    if num_cols > 1:
        for ci in range(num_cols - 1):
            sx = mx + pad_x + (ci + 1) * col_w + ci * col_gap + col_gap / 2
            p.setPen(QPen(QColor(58, 58, 68, 160), 1, Qt.DotLine))
            p.drawLine(QPointF(sx, content_y), QPointF(sx, content_y + pairs_per_col * line_h))


# ════════════════════════════════════════════════════════════════════
#  VideoRenderer
# ════════════════════════════════════════════════════════════════════

class VideoRenderer:
    def __init__(self, board_renderer, w=1920, h=1080, bg_color=QColor(30, 30, 32)):
        self.board_renderer = board_renderer
        self.w = w
        self.h = h
        self.bg_color = bg_color
        self.eval_cp = 0.0
        self.move_text = ""
        self.white_name = "White"
        self.black_name = "Black"
        self.overlays = []
        self.move_list_text = []
        self.current_move_index = 0
        self.game_state = GAME_NORMAL
        self.game_result = ""
        self.game_detail = ""

    @staticmethod
    def _cp2r(cp):
        if cp >= 9000: return 1.0
        if cp <= -9000: return 0.0
        return 1.0 / (1.0 + math.exp(-0.004 * max(-10000, min(10000, cp))))

    def render(self):
        img = QImage(self.w, self.h, QImage.Format_ARGB32)
        img.fill(self.bg_color)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if self.h > self.w:
            self._render_portrait(p)
        else:
            self._render_landscape(p)
        for ov in self.overlays:
            if os.path.exists(ov["path"]):
                oi = QImage(ov["path"])
                if not oi.isNull():
                    p.drawImage(QRectF(ov["x"], ov["y"], ov["w"], ov["h"]), oi)
        p.end()
        return img

    def _draw_gameover_pill_v(self, p, ebx, by, ebw, bsz):
        epx, eph = max(40, ebw + 20), 24
        if "1-0" in self.game_result:
            txt, ety = "♔ 1-0", by + eph / 2 + 10
            epbg, epfg = QColor(255, 255, 255, 230), QColor(30, 30, 30)
        elif "0-1" in self.game_result:
            txt, ety = "♚ 0-1", by + bsz - eph / 2 - 10
            epbg, epfg = QColor(30, 30, 30, 240), QColor(230, 230, 230)
        else:
            txt, ety = "½-½", by + bsz / 2
            epbg, epfg = QColor(140, 130, 50, 240), QColor(255, 255, 255)
        epill = QRectF(ebx + (ebw - epx) / 2, ety - eph / 2, epx, eph)
        p.setFont(QFont("Segoe UI", max(8, min(12, int(ebw * 0.3))), QFont.Bold))
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 50)); p.drawRoundedRect(epill.adjusted(1,1,1,1), 10, 10)
        p.setBrush(epbg); p.drawRoundedRect(epill, 10, 10); p.setPen(epfg); p.drawText(epill, Qt.AlignCenter, txt)

    def _draw_gameover_pill_h(self, p, ebx, eby, ebw, ebh):
        pill_w, pill_h = max(50, ebh + 30), 24
        if "1-0" in self.game_result:
            txt, pill_x = "♔ 1-0", ebx + pill_w / 2 + 10
            pbg, pfg = QColor(255, 255, 255, 230), QColor(30, 30, 30)
        elif "0-1" in self.game_result:
            txt, pill_x = "♚ 0-1", ebx + ebw - pill_w / 2 - 10
            pbg, pfg = QColor(30, 30, 30, 240), QColor(230, 230, 230)
        else:
            txt, pill_x = "½-½", ebx + ebw / 2
            pbg, pfg = QColor(140, 130, 50, 240), QColor(255, 255, 255)
        pill = QRectF(pill_x - pill_w / 2, eby + (ebh - pill_h) / 2, pill_w, pill_h)
        p.setFont(QFont("Segoe UI", 12, QFont.Bold))
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 90)); p.drawRoundedRect(pill.adjusted(1,2,1,2), 11, 11)
        p.setBrush(pbg); p.drawRoundedRect(pill, 11, 11); p.setPen(pfg); p.drawText(pill, Qt.AlignCenter, txt)

    def _render_portrait(self, p):
        margin = 20; bsz = self.w - 2 * margin; bx = margin; by = margin + 45
        p.setPen(QColor(200, 200, 200)); p.setFont(QFont("Segoe UI", 22, QFont.Bold))
        p.drawText(QRectF(bx, margin, bsz, 35), Qt.AlignLeft | Qt.AlignVCenter, f"♚ {self.black_name}")
        bimg = self.board_renderer.render(bsz)
        p.drawImage(QRectF(bx, by, bsz, bsz), bimg)
        wy = by + bsz + 10
        p.drawText(QRectF(bx, wy, bsz, 35), Qt.AlignLeft | Qt.AlignVCenter, f"♔ {self.white_name}")
        eby = wy + 45; ebh = 32; ebx = bx; ebw = bsz; cr = 5
        p.setPen(QPen(QColor(55, 55, 62), 1.2)); p.setBrush(QColor(18, 18, 22))
        p.drawRoundedRect(QRectF(ebx - 2, eby - 2, ebw + 4, ebh + 4), cr + 2, cr + 2)
        blk = QLinearGradient(ebx, eby, ebx + ebw, eby)
        blk.setColorAt(0.0, QColor(40, 40, 47)); blk.setColorAt(1.0, QColor(62, 62, 70))
        p.setPen(Qt.NoPen); p.setBrush(blk); p.drawRoundedRect(QRectF(ebx, eby, ebw, ebh), cr, cr)
        ratio = self._cp2r(self.eval_cp); ww = max(0, min(ebw, int(ebw * ratio)))
        if ww > 0:
            wg = QLinearGradient(ebx, eby, ebx + ww, eby)
            wg.setColorAt(0.0, QColor(248, 245, 238)); wg.setColorAt(1.0, QColor(232, 228, 218))
            p.setBrush(wg); path = QPainterPath()
            if ww >= ebw: path.addRoundedRect(QRectF(ebx, eby, ebw, ebh), cr, cr)
            elif ww < cr * 2: path.addRoundedRect(QRectF(ebx, eby, ww, ebh), cr, cr)
            else:
                path.moveTo(ebx + cr, eby); path.lineTo(ebx + ww, eby); path.lineTo(ebx + ww, eby + ebh)
                path.lineTo(ebx + cr, eby + ebh); path.quadTo(ebx, eby + ebh, ebx, eby + ebh - cr)
                path.lineTo(ebx, eby + cr); path.quadTo(ebx, eby, ebx + cr, eby); path.closeSubpath()
            p.drawPath(path)
        xdy = ebx + ww
        if 0 < ww < ebw:
            p.setPen(QPen(QColor(110, 105, 95, 160), 1.5)); p.drawLine(QPointF(xdy, eby + 2), QPointF(xdy, eby + ebh - 2))
        if self.game_state == GAME_NORMAL:
            is_mate = abs(self.eval_cp) > 9000
            txt = f"M{int(abs(self.eval_cp) - 10000)}" if is_mate else f"{self.eval_cp / 100.0:+.1f}"
            p.setFont(QFont("Segoe UI", 12, QFont.Bold)); fm = p.fontMetrics()
            tw = fm.horizontalAdvance(txt) + 16; pill_w, pill_h = max(tw, 32), 22
            pill_x = xdy; pill_x = max(ebx + pill_w / 2 + 4, min(ebx + ebw - pill_w / 2 - 4, pill_x))
            pill = QRectF(pill_x - pill_w / 2, eby + (ebh - pill_h) / 2, pill_w, pill_h)
            on_white = (pill_x <= ebx + ww) if 0 < ww < ebw else (self.eval_cp >= 0)
            if is_mate: pbg, pfg = (QColor(30,170,60,230) if self.eval_cp > 0 else QColor(210,45,45,230)), QColor(255,255,255)
            elif on_white: pbg, pfg = QColor(255,255,255,215), QColor(35,32,28)
            else: pbg, pfg = QColor(22,22,30,220), QColor(238,234,226)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0,0,0,90)); p.drawRoundedRect(pill.adjusted(1,2,1,2), 11, 11)
            p.setBrush(pbg); p.drawRoundedRect(pill, 11, 11); p.setPen(QPen(QColor(255,255,255,40),0.8))
            p.drawRoundedRect(pill, 11, 11); p.setPen(pfg); p.drawText(pill, Qt.AlignCenter, txt)
        else:
            self._draw_gameover_pill_h(p, ebx, eby, ebw, ebh)
        mly = eby + ebh + 20; mlh = self.h - mly - margin
        if mlh > 60: render_movelist_2col(p, bx, mly, bsz, mlh, self.move_list_text, self.current_move_index)
        if self.game_state != GAME_NORMAL:
            banner_h = int(bsz * 0.08); banner_y = by + bsz - banner_h - 30; banner = QRectF(bx, banner_y, bsz, banner_h)
            if self.game_state == GAME_CHECKMATE:
                w_wins = self.eval_cp > 0 or self.game_result == "1-0"
                bg = QColor(25,140,55,210) if w_wins else QColor(190,35,35,210)
                txt = f"♔ CHECKMATE  {self.game_result or '1-0'}" if w_wins else f"♚ CHECKMATE  {self.game_result or '0-1'}"
            else:
                bg = QColor(160,140,40,200); detail = self.game_detail or ""
                txt = f"½-½  {detail}" if detail else "½-½  DRAW"
            p.setPen(Qt.NoPen); p.setBrush(QColor(0,0,0,80)); p.drawRoundedRect(banner.adjusted(2,2,2,2), 6, 6)
            p.setBrush(bg); p.setPen(QPen(QColor(255,255,255,50),1.0)); p.drawRoundedRect(banner, 6, 6)
            p.setFont(QFont("Segoe UI", max(10, int(banner_h*0.45)), QFont.Bold)); p.setPen(QColor(255,255,255,240))
            p.drawText(banner, Qt.AlignCenter, txt)

    def _render_landscape(self, p):
        margin = 40; bsz = int(self.h * 0.85); by = (self.h - bsz) // 2
        ebw = max(32, int(bsz * 0.05)); ebx = margin
        ratio = self._cp2r(self.eval_cp); wh = max(0, min(bsz, int(bsz * ratio)))
        p.setPen(QPen(QColor(55,55,62),1.2)); p.setBrush(QColor(18,18,22))
        p.drawRoundedRect(QRectF(ebx-2,by-2,ebw+4,bsz+4), 7, 7)
        blk = QLinearGradient(ebx,by,ebx,by+bsz)
        blk.setColorAt(0.0, QColor(62,62,70)); blk.setColorAt(0.5, QColor(48,48,55)); blk.setColorAt(1.0, QColor(40,40,47))
        p.setPen(Qt.NoPen); p.setBrush(blk); p.drawRoundedRect(QRectF(ebx,by,ebw,bsz), 5, 5)
        if wh > 0:
            wt = by + bsz - wh
            wg = QLinearGradient(ebx,wt,ebx,by+bsz)
            wg.setColorAt(0.0, QColor(232,228,218)); wg.setColorAt(0.4, QColor(240,237,228)); wg.setColorAt(1.0, QColor(248,245,238))
            p.setBrush(wg)
            if wh >= bsz: p.drawRoundedRect(QRectF(ebx,by,ebw,bsz), 5, 5)
            elif wh < 10: p.drawRoundedRect(QRectF(ebx,wt,ebw,wh), 5, 5)
            else:
                path = QPainterPath(); path.moveTo(ebx,wt); path.lineTo(ebx+ebw,wt)
                path.lineTo(ebx+ebw,by+bsz-5); path.quadTo(ebx+ebw,by+bsz,ebx+ebw-5,by+bsz)
                path.lineTo(ebx+5,by+bsz); path.quadTo(ebx,by+bsz,ebx,by+bsz-5); path.lineTo(ebx,wt); path.closeSubpath()
                p.drawPath(path)
        p.setPen(QPen(QColor(120,180,255,70),1,Qt.DashLine))
        p.drawLine(QPointF(ebx+2,by+bsz/2), QPointF(ebx+ebw-2,by+bsz/2))
        bdy = by + bsz - wh
        if 0 < wh < bsz:
            p.setPen(QPen(QColor(110,105,95,160),1.5)); p.drawLine(QPointF(ebx+2,bdy), QPointF(ebx+ebw-2,bdy))
        if self.game_state == GAME_NORMAL:
            is_mate = abs(self.eval_cp) > 9000
            txt = f"M{int(abs(self.eval_cp)-10000)}" if is_mate else f"{self.eval_cp/100.0:+.1f}"
            efsz = max(9,min(14,int(ebw*0.36))); p.setFont(QFont("Segoe UI",efsz,QFont.Bold))
            efm = p.fontMetrics(); etw = efm.horizontalAdvance(txt)+12; epx,eph = max(etw,30),22
            ety = bdy if 0 < wh < bsz else by+bsz/2
            ety = max(by+eph/2+4, min(by+bsz-eph/2-4, ety))
            epill = QRectF(ebx+(ebw-epx)/2, ety-eph/2, epx, eph)
            on_w = (ety >= by+bsz-wh) if 0 < wh < bsz else (self.eval_cp >= 0)
            if is_mate: epbg,epfg = (QColor(30,170,60,220) if self.eval_cp>0 else QColor(210,45,45,220)), QColor(255,255,255)
            else: epbg,epfg = (QColor(255,255,255,200) if on_w else QColor(22,22,30,210)), (QColor(35,32,28) if on_w else QColor(238,234,226))
            p.setPen(Qt.NoPen); p.setBrush(QColor(0,0,0,50)); p.drawRoundedRect(epill.adjusted(1,1,1,1),10,10)
            p.setBrush(epbg); p.drawRoundedRect(epill,10,10); p.setPen(epfg); p.drawText(epill, Qt.AlignCenter, txt)
        else:
            self._draw_gameover_pill_v(p, ebx, by, ebw, bsz)
        bx_board = ebx + ebw + margin
        bimg = self.board_renderer.render(bsz)
        p.drawImage(QRectF(bx_board, by, bsz, bsz), bimg)
        mx = bx_board + bsz + margin; mw = self.w - mx - margin
        if mw > 160: render_movelist_2col(p, mx, by, mw, bsz, self.move_list_text, self.current_move_index)
        p.setPen(QColor(200,200,200)); p.setFont(QFont("Segoe UI", int(self.h*0.025), QFont.Bold))
        p.drawText(QRectF(bx_board, by+bsz+10, bsz/2, 40), Qt.AlignLeft|Qt.AlignVCenter, self.white_name)
        p.drawText(QRectF(bx_board, by-50, bsz/2, 40), Qt.AlignLeft|Qt.AlignVCenter, self.black_name)
        if self.game_state != GAME_NORMAL:
            banner_h = int(self.h*0.06); banner_y = by+bsz+55; banner = QRectF(bx_board, banner_y, bsz, banner_h)
            if self.game_state == GAME_CHECKMATE:
                w_wins = self.eval_cp > 0 or self.game_result == "1-0"
                bg = QColor(25,140,55,210) if w_wins else QColor(190,35,35,210)
                txt = f"♔ CHECKMATE  {self.game_result or '1-0'}" if w_wins else f"♚ CHECKMATE  {self.game_result or '0-1'}"
            else:
                bg = QColor(160,140,40,200); detail = self.game_detail or ""
                txt = f"½-½  {detail}" if detail else "½-½  DRAW"
            p.setPen(Qt.NoPen); p.setBrush(QColor(0,0,0,80)); p.drawRoundedRect(banner.adjusted(2,2,2,2),6,6)
            p.setBrush(bg); p.setPen(QPen(QColor(255,255,255,50),1.0)); p.drawRoundedRect(banner,6,6)
            p.setFont(QFont("Segoe UI", max(10,int(banner_h*0.45)), QFont.Bold)); p.setPen(QColor(255,255,255,240))
            p.drawText(banner, Qt.AlignCenter, txt)


# ════════════════════════════════════════════════════════════════════
#  Sync UCI + Helpers
# ════════════════════════════════════════════════════════════════════

class _SyncUCI:
    def __init__(self, path):
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"Stockfish not found: {path}")
        try:
            self.proc = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError as e:
            raise RuntimeError(f"Failed to launch Stockfish: {e}")
        self._cmd("uci"); self._read("uciok")

    def _cmd(self, t):
        try: self.proc.stdin.write(t+"\n"); self.proc.stdin.flush()
        except BrokenPipeError: raise RuntimeError("Broken pipe writing to Stockfish")

    def _read(self, tok):
        lines = []; deadline = time.time() + 30
        while True:
            if time.time() > deadline: break
            line = self.proc.stdout.readline()
            if not line: break
            line = line.strip(); lines.append(line)
            if tok in line: break
        return lines

    def analyse(self, fen, depth=18):
        board = chess.Board(fen)
        if not board.legal_moves: return None, 0
        self._cmd(f"position fen {fen}"); self._cmd(f"go depth {depth}")
        bm = None; sc = 0; wt = board.turn == chess.WHITE
        for line in self._read("bestmove"):
            if line.startswith("info") and " score " in line:
                parts = line.split()
                if "cp" in parts: idx = parts.index("cp"); sc = int(parts[idx+1]) if wt else -int(parts[idx+1])
                elif "mate" in parts: idx = parts.index("mate"); mi = int(parts[idx+1]); sc = (10000 if mi>0 else -10000) if wt else (-10000 if mi>0 else 10000)
            if line.startswith("bestmove"): parts = line.split(); bm = parts[1] if len(parts)>=2 else None
        return bm, sc

    def close(self):
        try: self._cmd("quit"); self.proc.wait(timeout=5)
        except: 
            try: self.proc.kill()
            except: pass


def _detect_game_state(board):
    if board.is_checkmate():
        result = "1-0" if board.turn == chess.BLACK else "0-1"
        return GAME_CHECKMATE, result, "Checkmate"
    if board.is_stalemate(): return GAME_STALEMATE, "½-½", "Stalemate"
    if board.is_insufficient_material(): return GAME_INSUFFICIENT, "½-½", "Insufficient Material"
    if board.is_game_over(): return GAME_DRAW, "½-½", "Draw"
    return GAME_NORMAL, "", ""


def _qimage_to_bgr_numpy(qimg):
    if not HAS_CV2: return None
    img = qimg.convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    ptr = img.bits(); ptr.setsize(h * w * 3)
    arr = np.array(ptr, dtype=np.uint8).reshape((h, w, 3))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


# ════════════════════════════════════════════════════════════════════
#  Eval Bar Widget
# ════════════════════════════════════════════════════════════════════

class EvalBarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._eval_cp = 0.0; self._anim_cp = 0.0
        self._game_state = GAME_NORMAL; self._game_result = ""; self._game_detail = ""
        self.setFixedWidth(48 + 16); self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding); self.setMinimumHeight(200)
        self._animation = QPropertyAnimation(self, b"anim_cp")
        self._animation.setDuration(450); self._animation.setEasingCurve(QEasingCurve.OutQuart)

    def set_game_state(self, state, result="", detail=""):
        self._game_state = state; self._game_result = result; self._game_detail = detail; self.update()
    def reset_game_state(self):
        self._game_state = GAME_NORMAL; self._game_result = ""; self._game_detail = ""; self.update()
    def _get_ac(self): return self._anim_cp
    def _set_ac(self, v): self._anim_cp = v; self.update()
    anim_cp = Property(float, _get_ac, _set_ac)

    def set_eval(self, cp):
        old = self._eval_cp; self._eval_cp = cp
        if self._game_state != GAME_NORMAL or abs(cp) > 9000 or abs(old) > 9000:
            self._anim_cp = float(cp); self.update(); return
        self._animation.stop(); self._animation.setStartValue(self._anim_cp)
        self._animation.setEndValue(float(cp)); self._animation.start()

    @staticmethod
    def _cp2r(cp):
        if cp >= 9000: return 1.0
        if cp <= -9000: return 0.0
        return 1.0 / (1.0 + math.exp(-0.004 * max(-10000.0, min(10000.0, cp))))

    def paintEvent(self, _event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        W, H = self.width(), self.height(); pad, cr = 8, 6; bx, by, bw, bh = pad, pad, W-2*pad, H-2*pad
        p.setPen(QPen(QColor(55,55,62),1.2)); p.setBrush(QColor(18,18,22)); p.drawRoundedRect(QRectF(0,0,W,H), cr+2, cr+2)
        blk = QLinearGradient(bx,by,bx,by+bh)
        blk.setColorAt(0.0,QColor(62,62,70)); blk.setColorAt(0.5,QColor(48,48,55)); blk.setColorAt(1.0,QColor(40,40,47))
        p.setPen(Qt.NoPen); p.setBrush(blk); p.drawRoundedRect(QRectF(bx,by,bw,bh), cr, cr)
        ratio = self._cp2r(self._anim_cp); wh = max(0, min(bh, int(bh*ratio)))
        if wh > 0:
            wt = by + bh - wh; wg = QLinearGradient(bx,wt,bx,by+bh)
            wg.setColorAt(0.0,QColor(232,228,218)); wg.setColorAt(0.4,QColor(240,237,228)); wg.setColorAt(1.0,QColor(248,245,238))
            p.setBrush(wg)
            if wh >= bh: p.drawRoundedRect(QRectF(bx,by,bw,bh), cr, cr)
            elif wh < cr*2: p.drawRoundedRect(QRectF(bx,wt,bw,wh), cr, cr)
            else:
                path=QPainterPath(); path.moveTo(bx,wt); path.lineTo(bx+bw,wt); path.lineTo(bx+bw,by+bh-cr)
                path.quadTo(bx+bw,by+bh,bx+bw-cr,by+bh); path.lineTo(bx+cr,by+bh)
                path.quadTo(bx,by+bh,bx,by+bh-cr); path.lineTo(bx,wt); path.closeSubpath(); p.drawPath(path)
        inner_glow = QLinearGradient(bx,by,bx,by+bh)
        inner_glow.setColorAt(0.0,QColor(0,0,0,60)); inner_glow.setColorAt(0.1,QColor(0,0,0,20))
        inner_glow.setColorAt(0.5,QColor(255,255,255,15)); inner_glow.setColorAt(0.9,QColor(0,0,0,10))
        inner_glow.setColorAt(1.0,QColor(0,0,0,40)); p.setBrush(inner_glow); p.drawRoundedRect(QRectF(bx,by,bw,bh), cr, cr)
        bdy = by + bh - wh
        if 0 < wh < bh:
            p.setPen(Qt.NoPen); p.setBrush(QColor(110,105,95,40)); p.drawRect(QRectF(bx+2,bdy-2,bw-4,5))
            p.setPen(QPen(QColor(110,105,95,160),1.5)); p.drawLine(QPointF(bx+2,bdy), QPointF(bx+bw-2,bdy))
        if self._game_state == GAME_NORMAL:
            is_mate = abs(self._eval_cp) > 9000
            txt = f"M{int(abs(self._eval_cp)-10000)}" if is_mate else f"{self._eval_cp/100.0:+.1f}"
            fnt = QFont("Segoe UI", max(8,min(12,int(bw*0.27))), QFont.Bold); p.setFont(fnt); fm = p.fontMetrics()
            tw = fm.horizontalAdvance(txt)+16; pill_w,pill_h = max(tw,32),22
            ty = bdy if 0<wh<bh else by+bh/2.0
            ty = max(by+pill_h/2+4, min(by+bh-pill_h/2-4, ty))
            pill = QRectF((W-pill_w)/2, ty-pill_h/2, pill_w, pill_h)
            on_white = (ty >= by+bh-wh) if 0<wh<bh else (self._eval_cp >= 0)
            if is_mate: pbg,pfg = (QColor(30,170,60,230) if self._eval_cp>0 else QColor(210,45,45,230)), QColor(255,255,255)
            elif on_white: pbg,pfg = QColor(255,255,255,215), QColor(35,32,28)
            else: pbg,pfg = QColor(22,22,30,220), QColor(238,234,226)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0,0,0,90)); p.drawRoundedRect(pill.adjusted(1,2,1,2),11,11)
            p.setBrush(pbg); p.drawRoundedRect(pill,11,11); p.setPen(QPen(QColor(255,255,255,40),0.8))
            p.drawRoundedRect(pill,11,11); p.setPen(pfg); p.drawText(pill, Qt.AlignCenter, txt)
        else:
            pill_w,pill_h = max(32,int(bw*0.8)),24; pill_x = (W-pill_w)/2
            if "1-0" in self._game_result:
                txt="♔ 1-0"; pill_y=by+15; pbg=QColor(255,255,255,230); pfg=QColor(30,30,30)
            elif "0-1" in self._game_result:
                txt="♚ 0-1"; pill_y=by+bh-pill_h-15; pbg=QColor(30,30,30,240); pfg=QColor(230,230,230)
            else:
                txt="½-½"; pill_y=by+(bh-pill_h)/2; pbg=QColor(140,130,50,240); pfg=QColor(255,255,255)
            pill = QRectF(pill_x,pill_y,pill_w,pill_h)
            p.setFont(QFont("Segoe UI", max(8,min(11,int(bw*0.25))), QFont.Bold))
            p.setPen(Qt.NoPen); p.setBrush(QColor(0,0,0,90)); p.drawRoundedRect(pill.adjusted(1,2,1,2),11,11)
            p.setBrush(pbg); p.drawRoundedRect(pill,11,11); p.setPen(pfg); p.drawText(pill, Qt.AlignCenter, txt)
        p.end()


# ════════════════════════════════════════════════════════════════════
#  MoveListWidget
# ════════════════════════════════════════════════════════════════════

class MoveListWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._moves: list = []; self._current: int = -1
        self.setMinimumWidth(280); self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_moves(self, moves, current=-1): self._moves = list(moves); self._current = current; self.update()
    def add_move(self, san): self._moves.append(san); self._current = len(self._moves)-1; self.update()
    def set_current(self, idx): self._current = idx; self.update()
    def clear(self): self._moves.clear(); self._current = -1; self.update()

    @property
    def moves(self): return list(self._moves)
    @property
    def current_index(self): return self._current

    def paintEvent(self, _event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        render_movelist_2col(p, 0, 0, self.width(), self.height(), self._moves, self._current); p.end()


# ════════════════════════════════════════════════════════════════════
#  Board Preview Widget
# ════════════════════════════════════════════════════════════════════

class BoardPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._renderer = BoardRenderer(); self._anim_progress_val = 1.0; self._active_anim = None
        self.setMinimumSize(360, 360); self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _get_ap(self): return self._anim_progress_val
    def _set_ap(self, v): self._anim_progress_val = v; self._renderer.anim_progress = v; self.update()
    animProgress = Property(float, _get_ap, _set_ap)

    @property
    def flipped(self): return self._renderer.flipped

    def set_board(self, board, last_move=None):
        self._renderer.board = board; self._renderer.last_move = last_move
        self._renderer.anim_move = None; self._renderer.anim_rook_move = None
        self._renderer.anim_progress = 1.0; self._anim_progress_val = 1.0; self.update()

    def set_theme(self, theme): self._renderer.theme = theme; self.update()
    def set_flipped(self, f): self._renderer.flipped = f; self.update()

    def animate_move(self, move):
        self._renderer.anim_move = move; self._renderer.anim_progress = 0.0; self._anim_progress_val = 0.0
        rook_move = None
        pc = self._renderer.board.piece_at(move.to_square)
        if pc and pc.piece_type == chess.KING and abs(chess.square_file(move.from_square)-chess.square_file(move.to_square)) == 2:
            rank = chess.square_rank(move.from_square)
            if chess.square_file(move.to_square) > chess.square_file(move.from_square):
                rook_move = (chess.square(7,rank), chess.square(5,rank))
            else:
                rook_move = (chess.square(0,rank), chess.square(3,rank))
        self._renderer.anim_rook_move = rook_move
        anim = QPropertyAnimation(self, b"animProgress")
        anim.setDuration(300); anim.setStartValue(0.0); anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutQuint)
        def cleanup():
            self._renderer.anim_move = None; self._renderer.anim_rook_move = None
            self._renderer.anim_progress = 1.0; self._anim_progress_val = 1.0; self.update()
        anim.finished.connect(cleanup); anim.start(); self._active_anim = anim

    def paintEvent(self, _event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        t = min(self.width(), self.height()); m = t*0.05; sz = (t-2*m)/8
        self._renderer._paint(p, t, m, sz); p.end()


# ════════════════════════════════════════════════════════════════════
#  Professional Sound Engine
# ════════════════════════════════════════════════════════════════════

class SoundEngine(QObject):
    sound_played = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_name = "Classic"; self._volume = 0.70; self._muted = False
        self._enabled = True; self._effects = {}; self._sound_files = {}
        self._temp_dir = tempfile.mkdtemp(prefix="chess_snd_"); self._sr = 44100

        if not HAS_NUMPY:
            logger.info("NumPy not available — sound disabled"); self._enabled = False; return
        if not HAS_QTMULTIMEDIA:
            logger.info("QtMultimedia not available — sound disabled"); self._enabled = False; return

        try:
            self._generate_all_themes(); self._apply_theme(self._theme_name)
            atexit.register(self.cleanup)
        except Exception as e:
            logger.warning(f"Sound engine init failed: {e}"); self._enabled = False

    def play(self, event):
        if not self._enabled or self._muted: return
        fx = self._effects.get(event)
        if fx:
            if fx.isPlaying(): fx.stop()
            fx.play(); self.sound_played.emit(event)

    def play_move_sound(self, board, move):
        if not self._enabled or self._muted: return
        piece = board.piece_at(move.from_square)
        is_capture = board.is_capture(move)
        is_castle = (piece and piece.piece_type == chess.KING and
                     abs(chess.square_file(move.from_square)-chess.square_file(move.to_square)) == 2)
        gives_check = board.gives_check(move)
        board.push(move)
        is_checkmate = board.is_checkmate(); is_stalemate = board.is_stalemate()
        is_draw = board.is_game_over() and not is_checkmate and not is_stalemate
        board.pop()
        if is_checkmate: self.play(SND_CHECKMATE)
        elif is_stalemate: self.play(SND_STALEMATE)
        elif is_draw: self.play(SND_DRAW)
        elif gives_check: self.play(SND_CHECK)
        elif is_castle: self.play(SND_CASTLE)
        elif is_capture: self.play(SND_CAPTURE)
        else: self.play(SND_MOVE)

    def play_game_end(self, result_type):
        mapping = {"checkmate": SND_CHECKMATE, "stalemate": SND_STALEMATE, "draw": SND_DRAW}
        self.play(mapping.get(result_type, SND_DRAW))

    def set_theme(self, name):
        if name == self._theme_name or not self._enabled: return
        self._theme_name = name; self._apply_theme(name)

    def set_volume(self, vol):
        self._volume = max(0.0, min(1.0, vol))
        for fx in self._effects.values(): fx.setVolume(self._volume)

    def set_muted(self, muted): self._muted = muted

    @property
    def enabled(self): return self._enabled
    @property
    def theme(self): return self._theme_name
    @property
    def volume(self): return self._volume
    @property
    def muted(self): return self._muted
    @property
    def available_themes(self): return SOUND_THEME_LIST if self._enabled else []

    def cleanup(self):
        try: shutil.rmtree(self._temp_dir, ignore_errors=True)
        except: pass

    def _apply_theme(self, name):
        if name not in self._sound_files: return
        for fx in self._effects.values():
            if fx.isPlaying(): fx.stop()
        self._effects.clear()
        for event, filepath in self._sound_files[name].items():
            fx = QSoundEffect(self); fx.setSource(QUrl.fromLocalFile(os.path.abspath(filepath)))
            fx.setVolume(self._volume); self._effects[event] = fx

    def _generate_all_themes(self):
        generators = {
            "Classic": self._gen_classic, "Digital": self._gen_digital,
            "Cinematic": self._gen_cinematic, "Retro": self._gen_retro, "Ambient": self._gen_ambient,
        }
        for tname, gen in generators.items():
            try:
                samples = gen(); self._sound_files[tname] = {}
                for event, arr in samples.items():
                    fp = self._write_wav(f"{tname.lower()}_{event}.wav", arr); self._sound_files[tname][event] = fp
            except Exception as e:
                logger.warning(f"Failed to generate '{tname}' sounds: {e}")

    def _write_wav(self, filename, samples):
        path = os.path.join(self._temp_dir, filename)
        arr = np.clip(samples, -1.0, 1.0); pcm = (arr * 32767).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(self._sr)
            wf.writeframes(pcm.tobytes())
        return path

    @staticmethod
    def _norm(sig, peak=0.88):
        mx = np.max(np.abs(sig)); return sig * (peak / mx) if mx > 0 else sig

    def _t(self, dur): return np.linspace(0, dur, int(dur * self._sr), endpoint=False)

    def _reverb(self, sig, delays=(0.028, 0.060, 0.105, 0.155), decay=0.35):
        out_len = len(sig) + int(max(delays) * self._sr) + self._sr // 15
        out = np.zeros(out_len); out[: len(sig)] = sig
        for i, d in enumerate(delays):
            ds = int(d * self._sr); a = decay ** (i + 1); end = min(ds + len(sig), out_len)
            out[ds:end] += sig[: end - ds] * a
        tail_len = min(self._sr // 8, len(out) - len(sig))
        if tail_len > 0:
            fade = np.linspace(1, 0, tail_len); out[len(sig): len(sig) + tail_len] *= fade
        return out

    def _sweep(self, f0, f1, dur):
        n = int(dur * self._sr); freq = np.linspace(f0, f1, n)
        phase = 2 * np.pi * np.cumsum(freq) / self._sr; t = np.arange(n) / self._sr
        return np.sin(phase), t

    @staticmethod
    def _square(freq, t, duty=0.5): return np.where((freq * t) % 1.0 < duty, 1.0, -1.0)
    @staticmethod
    def _triangle(freq, t): p = (freq * t) % 1.0; return 2.0 * np.abs(2.0 * p - 1.0) - 1.0

    def _gen_classic(self):
        sr=self._sr; t=self._t(0.08); n=np.random.randn(len(t))*np.exp(-t*100)
        m=self._norm(n*0.30+np.sin(2*np.pi*180*t)*np.exp(-t*55)*0.40+np.sin(2*np.pi*900*t)*np.exp(-t*220)*0.30)*0.65
        t=self._t(0.15); n=np.random.randn(len(t))*np.exp(-t*45)
        c=self._norm(n*0.30+np.sin(2*np.pi*120*t)*np.exp(-t*25)*0.35+np.sin(2*np.pi*250*t)*np.exp(-t*35)*0.20+np.random.randn(len(t))*np.sin(2*np.pi*500*t+1)*np.exp(-t*55)*0.15)*0.72
        t=self._t(0.30); k=self._norm(np.sin(2*np.pi*1100*t)*np.exp(-t*10)*0.40+np.sin(2*np.pi*1650*t)*np.exp(-t*12)*0.35+np.sin(2*np.pi*2200*t)*np.exp(-t*14)*0.25)*0.55
        h=m[:int(len(m)*0.55)]; g=np.zeros(int(sr*0.035)); ca=self._norm(np.concatenate([h,g,m*0.88]))*0.65
        t=self._t(1.0); cm=self._norm(np.sin(2*np.pi*55*t)*np.exp(-t*3)*0.35+np.sin(2*np.pi*110*t)*np.exp(-t*5)*0.30+np.random.randn(len(t))*np.exp(-t*3.5)*0.25+np.sin(2*np.pi*880*t)*np.exp(-t*4)*0.15)*0.80
        t=self._t(0.55); sm=self._norm(np.sin(2*np.pi*220*t)*0.30+np.sin(2*np.pi*277*t)*0.22+np.sin(2*np.pi*233*t)*0.18)*np.exp(-t*5)*0.55
        t=self._t(0.50); dr=self._norm(np.sin(2*np.pi*220*t)*0.35+np.sin(2*np.pi*165*t)*0.25)*np.exp(-t*5)*0.55
        sw,t=self._sweep(350,700,0.30); gs=self._norm(sw*np.exp(-((t-0.12)/0.12)**2))*0.45
        t=self._t(0.03); ui=np.sin(2*np.pi*1000*t)*np.exp(-t*150)*0.30
        return {SND_MOVE:m,SND_CAPTURE:c,SND_CHECK:k,SND_CASTLE:ca,SND_CHECKMATE:cm,SND_STALEMATE:sm,SND_DRAW:dr,SND_GAME_START:gs,SND_UI_CLICK:ui}

    def _gen_digital(self):
        sr=self._sr; t=self._t(0.06); m=self._norm(np.sin(2*np.pi*880*t)*np.exp(-t*80))*0.50
        t=self._t(0.10); c=self._norm(np.sin(2*np.pi*440*t)*np.exp(-t*40)*0.40+np.sin(2*np.pi*880*t)*np.exp(-t*55)*0.35+np.sin(2*np.pi*220*t)*np.exp(-t*30)*0.25)*0.60
        sw,t=self._sweep(600,1200,0.14); k=self._norm(sw*np.exp(-t*12))*0.50
        t1=self._t(0.04); b1=np.sin(2*np.pi*660*t1)*np.exp(-t1*80)*0.40; gap=np.zeros(int(sr*0.025)); t2=self._t(0.05); b2=np.sin(2*np.pi*880*t2)*np.exp(-t2*70)*0.45; ca=self._norm(np.concatenate([b1,gap,b2]))*0.55
        t=self._t(0.55); f=np.linspace(880,220,len(t)); cm=self._norm(np.sin(2*np.pi*np.cumsum(f)/sr)*np.exp(-t*4)*0.35+np.sin(2*np.pi*80*t)*np.exp(-t*5)*0.35+np.sin(2*np.pi*55*t)*np.exp(-t*3)*0.30)*0.75
        t=self._t(0.35); sm=self._norm(np.sin(2*np.pi*330*t)*np.exp(-t*7)*0.35+np.sin(2*np.pi*350*t)*np.exp(-t*7)*0.25)*0.50
        t=self._t(0.40); dr=self._norm(np.sin(2*np.pi*330*t)*0.30+np.sin(2*np.pi*440*t)*0.20)*np.exp(-t*7)*0.50
        pts=[]
        for n in [523,659,784]: nt=self._t(0.08); pts.append(np.sin(2*np.pi*n*nt)*np.exp(-nt*25)*0.40); pts.append(np.zeros(int(sr*0.02)))
        gs=self._norm(np.concatenate(pts[:-1]))*0.50
        t=self._t(0.025); ui=np.sin(2*np.pi*1200*t)*np.exp(-t*180)*0.25
        return {SND_MOVE:m,SND_CAPTURE:c,SND_CHECK:k,SND_CASTLE:ca,SND_CHECKMATE:cm,SND_STALEMATE:sm,SND_DRAW:dr,SND_GAME_START:gs,SND_UI_CLICK:ui}

    def _gen_cinematic(self):
        sr=self._sr; t=self._t(0.10)
        mr=self._norm(np.sin(2*np.pi*60*t)*np.exp(-t*20)*0.45+np.sin(2*np.pi*200*t)*np.exp(-t*35)*0.35+np.random.randn(len(t))*np.exp(-t*60)*0.12)*0.60; m=self._norm(self._reverb(mr,decay=0.38))*0.65
        t=self._t(0.14); cr=self._norm(np.sin(2*np.pi*80*t)*np.exp(-t*15)*0.40+np.sin(2*np.pi*160*t)*np.exp(-t*22)*0.30+np.random.randn(len(t))*np.exp(-t*35)*0.18+np.sin(2*np.pi*700*t)*np.exp(-t*50)*0.08)*0.70; c=self._norm(self._reverb(cr,decay=0.40))*0.72
        sw,t=self._sweep(200,1400,0.25); kr=self._norm(sw*np.exp(-t*5)*0.45+np.sin(2*np.pi*55*t)*np.exp(-t*5)*0.20)*0.58; k=self._norm(self._reverb(kr,decay=0.42))*0.60
        h=m[:int(len(m)*0.45)]; g=np.zeros(int(sr*0.05)); car=np.concatenate([h,g,m*0.80]); ca=self._norm(self._reverb(car,decay=0.35))*0.68
        t=self._t(0.35); cmr=self._norm(np.sin(2*np.pi*40*t)*np.exp(-t*4)*0.30+np.sin(2*np.pi*80*t)*np.exp(-t*5)*0.25+np.sin(2*np.pi*160*t)*np.exp(-t*6)*0.20+np.random.randn(len(t))*np.exp(-t*4)*0.22+np.sin(2*np.pi*1200*t)*np.exp(-t*5)*0.08)*0.82; cm=self._norm(self._reverb(cmr,decay=0.50))*0.85
        t=self._t(0.60); smr=self._norm(np.sin(2*np.pi*185*t)*np.exp(-t*4)*0.25+np.sin(2*np.pi*233*t)*np.exp(-t*4.5)*0.20+np.sin(2*np.pi*311*t)*np.exp(-t*5)*0.15)*0.55; sm=self._norm(self._reverb(smr,decay=0.45))*0.58
        t=self._t(0.70); drr=self._norm(np.sin(2*np.pi*220*t)*np.exp(-t*3.5)*0.25+np.sin(2*np.pi*330*t)*np.exp(-t*4)*0.18+np.sin(2*np.pi*440*t)*np.exp(-t*5)*0.10)*0.50; dr=self._norm(self._reverb(drr,decay=0.40))*0.55
        sw,t=self._sweep(80,500,0.45); gsr=self._norm(sw*np.exp(-((t-0.35)/0.15)**2)*0.45+np.sin(2*np.pi*55*t)*(t/0.45)*0.20)*0.55; gs=self._norm(self._reverb(gsr,decay=0.35))*0.58
        t=self._t(0.04); ui=np.sin(2*np.pi*400*t)*np.exp(-t*80)*0.25
        return {SND_MOVE:m,SND_CAPTURE:c,SND_CHECK:k,SND_CASTLE:ca,SND_CHECKMATE:cm,SND_STALEMATE:sm,SND_DRAW:dr,SND_GAME_START:gs,SND_UI_CLICK:ui}

    def _gen_retro(self):
        sr=self._sr; t=self._t(0.06); m=self._norm(self._square(440,t)*np.exp(-t*60))*0.40
        t=self._t(0.09); c=self._norm(self._square(330,t)*np.exp(-t*35)*0.60+np.random.randn(len(t))*np.exp(-t*50)*0.20)*0.50
        t1=self._t(0.05); b1=self._square(660,t1)*np.exp(-t1*40)*0.40; gap=np.zeros(int(sr*0.025)); t2=self._t(0.06); b2=self._square(990,t2)*np.exp(-t2*35)*0.45; k=self._norm(np.concatenate([b1,gap,b2]))*0.50
        pts=[]
        for f in [440,550,660]: nt=self._t(0.04); pts.append(self._square(f,nt)*np.exp(-nt*50)*0.38); pts.append(np.zeros(int(sr*0.02)))
        ca=self._norm(np.concatenate(pts))*0.48
        pts=[]
        for f in [880,660,523,330]: nt=self._t(0.10); pts.append(self._square(f,nt)*np.exp(-nt*8)*0.40)
        ft=self._t(0.15); pts.append(self._triangle(110,ft)*np.exp(-ft*10)*0.35); cm=self._norm(np.concatenate(pts))*0.65
        pts=[]
        for f in [440,392,349,330]: nt=self._t(0.08); pts.append(self._triangle(f,nt)*np.exp(-nt*10)*0.30)
        sm=self._norm(np.concatenate(pts))*0.48
        t=self._t(0.35); dr=self._norm(self._triangle(262,t)*np.exp(-t*6)*0.30+self._triangle(330,t)*np.exp(-t*7)*0.20)*0.45
        pts=[]
        for f in [523,659,784,1047]: nt=self._t(0.06); pts.append(self._square(f,nt)*np.exp(-nt*18)*0.38); pts.append(np.zeros(int(sr*0.015)))
        gs=self._norm(np.concatenate(pts[:-1]))*0.48
        t=self._t(0.02); ui=self._square(1000,t)*np.exp(-t*120)*0.22
        return {SND_MOVE:m,SND_CAPTURE:c,SND_CHECK:k,SND_CASTLE:ca,SND_CHECKMATE:cm,SND_STALEMATE:sm,SND_DRAW:dr,SND_GAME_START:gs,SND_UI_CLICK:ui}

    def _gen_ambient(self):
        sr=self._sr; t=self._t(0.12); m=self._norm(np.sin(2*np.pi*200*t)*np.exp(-t*25)*0.30+np.random.randn(len(t))*np.exp(-t*45)*0.04)*0.40
        t=self._t(0.18); c=self._norm(np.sin(2*np.pi*150*t)*np.exp(-t*18)*0.30+np.sin(2*np.pi*300*t)*np.exp(-t*22)*0.15+np.random.randn(len(t))*np.exp(-t*40)*0.05)*0.45
        t=self._t(0.45); k=self._norm(np.sin(2*np.pi*660*t)*np.exp(-t*5)*0.22+np.sin(2*np.pi*990*t)*np.exp(-t*7)*0.12+np.sin(2*np.pi*1320*t)*np.exp(-t*9)*0.06)*0.42
        t1=self._t(0.08); a1=np.sin(2*np.pi*260*t1)*np.exp(-t1*20)*0.25; gap=np.zeros(int(sr*0.04)); t2=self._t(0.10); a2=np.sin(2*np.pi*330*t2)*np.exp(-t2*18)*0.28; ca=self._norm(np.concatenate([a1,gap,a2]))*0.42
        t=self._t(1.2); cm=self._norm(np.sin(2*np.pi*110*t)*np.exp(-t*2.5)*0.25+np.sin(2*np.pi*220*t)*np.exp(-t*3)*0.15+np.sin(2*np.pi*440*t)*np.exp(-t*4)*0.08+np.sin(2*np.pi*55*t)*np.exp(-t*2)*0.18)*0.60
        t=self._t(0.65); sm=self._norm(np.sin(2*np.pi*220*t)*np.exp(-t*3.5)*0.20+np.sin(2*np.pi*262*t)*np.exp(-t*4)*0.15+np.random.randn(len(t))*np.exp(-t*5)*0.02)*0.45
        t=self._t(0.60); dr=self._norm(np.sin(2*np.pi*262*t)*np.exp(-t*4)*0.22+np.sin(2*np.pi*330*t)*np.exp(-t*5)*0.15+np.sin(2*np.pi*392*t)*np.exp(-t*6)*0.08)*0.45
        sw,t=self._sweep(200,400,0.45); gs=self._norm(sw*np.exp(-t*4)*0.25+np.sin(2*np.pi*262*t)*np.exp(-t*3)*0.15)*0.42
        t=self._t(0.03); ui=np.sin(2*np.pi*600*t)*np.exp(-t*100)*0.15
        return {SND_MOVE:m,SND_CAPTURE:c,SND_CHECK:k,SND_CASTLE:ca,SND_CHECKMATE:cm,SND_STALEMATE:sm,SND_DRAW:dr,SND_GAME_START:gs,SND_UI_CLICK:ui}


# ════════════════════════════════════════════════════════════════════
#  Sound Settings Widget
# ════════════════════════════════════════════════════════════════════

class SoundSettingsWidget(QGroupBox):
    theme_changed = Signal(str)
    volume_changed = Signal(float)
    mute_toggled = Signal(bool)
    test_requested = Signal()

    def __init__(self, sound_engine, parent=None):
        super().__init__("🔊  Sound Design", parent)
        self._engine = sound_engine; self._building = True; self._setup_ui(); self._building = False

    def _setup_ui(self):
        self.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 11pt; color: #c8c8d0; border: 1px solid #444450; border-radius: 8px; margin-top: 12px; padding-top: 18px; }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; }
            QLabel { color: #b0b0bc; font-size: 9pt; }
            QComboBox { background: #2a2a32; color: #d0d0d8; border: 1px solid #505058; border-radius: 4px; padding: 4px 8px; min-height: 22px; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background: #2a2a32; color: #d0d0d8; selection-background-color: #3a6cc8; }
            QSlider::groove:horizontal { height: 6px; background: #3a3a44; border-radius: 3px; }
            QSlider::handle:horizontal { background: #5a9af0; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; }
            QSlider::sub-page:horizontal { background: #4478c0; border-radius: 3px; }
            QPushButton { background: #363640; color: #c8c8d0; border: 1px solid #505058; border-radius: 5px; padding: 5px 12px; font-size: 9pt; }
            QPushButton:hover { background: #42424e; }
            QPushButton:pressed { background: #2a2a34; }
            QPushButton:checked { background: #c83030; color: white; border-color: #a02020; }
        """)
        layout = QVBoxLayout(self); layout.setSpacing(8); layout.setContentsMargins(12,8,12,10)
        enabled = self._engine.enabled

        theme_row = QHBoxLayout(); theme_lbl = QLabel("Theme:"); theme_lbl.setFixedWidth(55)
        self._theme_combo = QComboBox()
        if enabled: self._theme_combo.addItems(self._engine.available_themes); self._theme_combo.setCurrentText(self._engine.theme)
        else: self._theme_combo.addItem("Unavailable"); self._theme_combo.setEnabled(False)
        self._theme_combo.currentTextChanged.connect(self._on_theme)
        theme_row.addWidget(theme_lbl); theme_row.addWidget(self._theme_combo, 1); layout.addLayout(theme_row)

        self._desc_lbl = QLabel(); self._desc_lbl.setWordWrap(True)
        self._desc_lbl.setStyleSheet("color: #808090; font-size: 8pt; font-style: italic;")
        self._update_desc(self._engine.theme if enabled else ""); layout.addWidget(self._desc_lbl)

        vol_row = QHBoxLayout(); vol_lbl = QLabel("Volume:"); vol_lbl.setFixedWidth(55)
        self._vol_slider = QSlider(Qt.Horizontal); self._vol_slider.setRange(0,100)
        self._vol_slider.setValue(int(self._engine.volume*100) if enabled else 70); self._vol_slider.setEnabled(enabled)
        self._vol_label = QLabel(f"{self._vol_slider.value()}%"); self._vol_label.setFixedWidth(36)
        self._vol_label.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        self._vol_slider.valueChanged.connect(self._on_volume)
        vol_row.addWidget(vol_lbl); vol_row.addWidget(self._vol_slider,1); vol_row.addWidget(self._vol_label); layout.addLayout(vol_row)

        btn_row = QHBoxLayout()
        self._mute_btn = QPushButton("🔇 Mute"); self._mute_btn.setCheckable(True)
        self._mute_btn.setChecked(self._engine.muted); self._mute_btn.setEnabled(enabled); self._mute_btn.toggled.connect(self._on_mute)
        btn_row.addWidget(self._mute_btn)
        self._test_btn = QPushButton("▶  Test"); self._test_btn.setEnabled(enabled)
        self._test_btn.clicked.connect(self._on_test); btn_row.addWidget(self._test_btn)
        layout.addLayout(btn_row)

        if not enabled:
            note = QLabel("⚠ Sound requires NumPy + QtMultimedia")
            note.setStyleSheet("color: #907040; font-size: 8pt;"); note.setWordWrap(True); layout.addWidget(note)

    _THEME_DESCS = {
        "Classic": "Realistic wooden chess-piece sounds — traditional and timeless.",
        "Digital": "Clean electronic tones — modern and precise interface sounds.",
        "Cinematic": "Deep atmospheric impacts with reverb — dramatic and immersive.",
        "Retro": "8-bit chiptune blips and beeps — nostalgic and playful.",
        "Ambient": "Soft, non-intrusive tones — calm and meditative atmosphere.",
    }
    def _update_desc(self, theme): self._desc_lbl.setText(self._THEME_DESCS.get(theme, ""))
    def _on_theme(self, name):
        if self._building or not name: return
        self._update_desc(name); self.theme_changed.emit(name)
    def _on_volume(self, val):
        if self._building: return
        self._vol_label.setText(f"{val}%"); self.volume_changed.emit(val/100.0)
    def _on_mute(self, checked):
        if self._building: return
        self._mute_btn.setText("🔊 Unmute" if checked else "🔇 Mute"); self.mute_toggled.emit(checked)
    def _on_test(self): self.test_requested.emit()
    def set_theme(self, name): self._building=True; self._theme_combo.setCurrentText(name); self._update_desc(name); self._building=False
    def set_volume_display(self, vol): self._building=True; self._vol_slider.setValue(int(vol*100)); self._vol_label.setText(f"{int(vol*100)}%"); self._building=False


# ════════════════════════════════════════════════════════════════════
#  Game Worker Thread
# ════════════════════════════════════════════════════════════════════

class GameWorker(QThread):
    board_updated = Signal(str, str, float)
    game_over = Signal(str, str, str)
    move_count_updated = Signal(int)

    def __init__(self, white_type=0, black_type=0, depth=3, iterations=500, stockfish_path=None, delay_ms=300, parent=None):
        super().__init__(parent)
        self._white_type=white_type; self._black_type=black_type; self._depth=depth
        self._iterations=iterations; self._stockfish_path=stockfish_path; self._delay_ms=delay_ms
        self._abort=False; self._engines={}; self._sf=None

    def abort(self): self._abort = True

    def run(self):
        self._abort = False; board = chess.Board()
        try:
            if self._white_type == 2 or self._black_type == 2:
                if self._stockfish_path: self._sf = _SyncUCI(self._stockfish_path)
            self._engines[0] = MinimaxEngine(); self._engines[1] = MCTSEngine()
            move_count = 0
            while not board.is_game_over() and not self._abort and move_count < 300:
                side_type = self._white_type if board.turn == chess.WHITE else self._black_type
                move, eval_cp = self._get_move(board, side_type)
                if move is None or self._abort: break
                self.board_updated.emit(board.fen(), move.uci(), eval_cp)
                board.push(move); move_count += 1; self.move_count_updated.emit(move_count)
                if self._delay_ms > 0: self.msleep(self._delay_ms)
            if not self._abort:
                state, result, detail = _detect_game_state(board)
                self.game_over.emit(state, result, detail)
        finally:
            if self._sf: self._sf.close(); self._sf = None

    def _get_move(self, board, engine_type):
        if engine_type == 0: m,e,_,_ = self._engines[0].search(board, self._depth); return m,e
        elif engine_type == 1: m,e,_,_ = self._engines[1].search(board, self._iterations); return m,e
        elif engine_type == 2 and self._sf:
            bm,sc = self._sf.analyse(board.fen(), self._depth)
            if bm: return chess.Move.from_uci(bm), sc
        return random.choice(list(board.legal_moves)), 0


# ════════════════════════════════════════════════════════════════════
#  Video Export Worker Thread
# ════════════════════════════════════════════════════════════════════

class ExportWorker(QThread):
    progress_updated = Signal(int, int)
    export_finished = Signal(str)
    export_error = Signal(str)

    def __init__(self, pgn_text, w, h, fps, theme, white_name, black_name, filepath, parent=None):
        super().__init__(parent)
        self._pgn=pgn_text; self._w=w; self._h=h; self._fps=fps; self._theme=theme
        self._white_name=white_name; self._black_name=black_name; self._filepath=filepath; self._abort=False

    def abort(self): self._abort = True

    def run(self):
        if not HAS_CV2: self.export_error.emit("OpenCV (cv2) is required for video export."); return
        try:
            game = chess.pgn.read_game(io.StringIO(self._pgn))
            if game is None: self.export_error.emit("Invalid PGN data."); return
            board = game.board(); moves = list(game.mainline_moves()); total = len(moves)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(self._filepath, fourcc, self._fps, (self._w, self._h))
            if not out.isOpened(): self.export_error.emit("Failed to open video writer."); return

            renderer_board = BoardRenderer(board=board, theme=self._theme)
            vid_renderer = VideoRenderer(renderer_board, self._w, self._h)
            vid_renderer.white_name = self._white_name; vid_renderer.black_name = self._black_name
            move_list = []; vid_renderer.move_list_text = move_list
            eval_cp = 0.0; vid_renderer.eval_cp = eval_cp

            for i, move in enumerate(moves):
                if self._abort: break
                san = board.san(move); move_list.append(san); vid_renderer.current_move_index = len(move_list)-1
                renderer_board.board = board; renderer_board.last_move = move; vid_renderer.eval_cp = eval_cp
                qimg = vid_renderer.render(); frame = _qimage_to_bgr_numpy(qimg)
                if frame is not None: out.write(frame)
                board.push(move)
                ev = HeuristicEvaluator(); eval_cp = ev.evaluate(board); vid_renderer.eval_cp = eval_cp
                self.progress_updated.emit(i+1, total)

            state, result, detail = _detect_game_state(board)
            vid_renderer.game_state=state; vid_renderer.game_result=result; vid_renderer.game_detail=detail
            renderer_board.board=board; renderer_board.last_move=None
            qimg = vid_renderer.render(); frame = _qimage_to_bgr_numpy(qimg)
            if frame is not None:
                for _ in range(int(self._fps*3)):
                    if self._abort: break
                    out.write(frame)
            out.release()
            if not self._abort: self.export_finished.emit(self._filepath)
        except Exception as e:
            self.export_error.emit(str(e))


# ════════════════════════════════════════════════════════════════════
#  Main Window
# ════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI vs AI Chess — Battle & Export")
        self.setMinimumSize(1100, 750); self.resize(1300, 850)
        self._board = chess.Board(); self._move_list = []; self._eval_cp = 0.0
        self._game_state = GAME_NORMAL; self._game_result = ""; self._game_detail = ""
        self._game_worker = None; self._export_worker = None; self._current_theme_name = "Classic"
        self._sound_engine = SoundEngine(self)
        self._init_ui(); self._connect_signals(); self._update_board_display()

    def _init_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        main_layout = QHBoxLayout(central); main_layout.setContentsMargins(10,10,10,10); main_layout.setSpacing(10)

        left_widget = QWidget(); left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0,0,0,0); left_layout.setSpacing(6)

        self._black_label = QLabel("♚ Black")
        self._black_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self._black_label.setStyleSheet("color: #d0d0d8;")
        left_layout.addWidget(self._black_label, alignment=Qt.AlignLeft)

        board_row = QHBoxLayout(); board_row.setSpacing(6)
        self._eval_bar = EvalBarWidget(); board_row.addWidget(self._eval_bar)
        self._board_widget = BoardPreviewWidget(); board_row.addWidget(self._board_widget, 1)
        left_layout.addLayout(board_row, 1)

        self._white_label = QLabel("♔ White")
        self._white_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self._white_label.setStyleSheet("color: #d0d0d8;")
        left_layout.addWidget(self._white_label, alignment=Qt.AlignLeft)

        self._status_label = QLabel("Ready to play")
        self._status_label.setFont(QFont("Segoe UI", 11))
        self._status_label.setStyleSheet("color: #88aacc; padding: 4px;")
        left_layout.addWidget(self._status_label)
        main_layout.addWidget(left_widget, 3)

        right_widget = QWidget(); right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0,0,0,0); right_layout.setSpacing(8)
        self._move_list_widget = MoveListWidget(); right_layout.addWidget(self._move_list_widget, 2)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        settings_widget = QWidget(); settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(0,0,0,0); settings_layout.setSpacing(8)

        game_group = QGroupBox("⚙  Game Settings")
        game_group.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 11pt; color: #c8c8d0; border: 1px solid #444450; border-radius: 8px; margin-top: 12px; padding-top: 18px; }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; }
            QLabel { color: #b0b0bc; font-size: 9pt; }
            QComboBox { background: #2a2a32; color: #d0d0d8; border: 1px solid #505058; border-radius: 4px; padding: 4px 8px; min-height: 22px; }
            QSpinBox { background: #2a2a32; color: #d0d0d8; border: 1px solid #505058; border-radius: 4px; padding: 4px 8px; min-height: 22px; }
        """)
        game_form = QFormLayout(game_group)
        self._white_ai_combo = QComboBox(); self._white_ai_combo.addItems(AI_MAP.values()); self._white_ai_combo.setCurrentIndex(0)
        game_form.addRow("White AI:", self._white_ai_combo)
        self._black_ai_combo = QComboBox(); self._black_ai_combo.addItems(AI_MAP.values()); self._black_ai_combo.setCurrentIndex(0)
        game_form.addRow("Black AI:", self._black_ai_combo)
        self._depth_spin = QSpinBox(); self._depth_spin.setRange(1,20); self._depth_spin.setValue(3)
        game_form.addRow("Depth/Iter:", self._depth_spin)
        self._delay_spin = QSpinBox(); self._delay_spin.setRange(0,5000); self._delay_spin.setValue(300); self._delay_spin.setSuffix(" ms")
        game_form.addRow("Move Delay:", self._delay_spin)
        self._theme_combo = QComboBox(); self._theme_combo.addItems(THEMES.keys()); self._theme_combo.setCurrentText("Classic")
        game_form.addRow("Board Theme:", self._theme_combo)
        settings_layout.addWidget(game_group)

        self._sound_settings = SoundSettingsWidget(self._sound_engine)
        settings_layout.addWidget(self._sound_settings)

        export_group = QGroupBox("🎬  Video Export")
        export_group.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 11pt; color: #c8c8d0; border: 1px solid #444450; border-radius: 8px; margin-top: 12px; padding-top: 18px; }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; }
            QLabel { color: #b0b0bc; font-size: 9pt; }
            QComboBox { background: #2a2a32; color: #d0d0d8; border: 1px solid #505058; border-radius: 4px; padding: 4px 8px; min-height: 22px; }
            QSpinBox { background: #2a2a32; color: #d0d0d8; border: 1px solid #505058; border-radius: 4px; padding: 4px 8px; min-height: 22px; }
        """)
        export_form = QFormLayout(export_group)
        self._res_combo = QComboBox(); self._res_combo.addItems(RESOLUTION_LIST); self._res_combo.setCurrentIndex(0)
        export_form.addRow("Resolution:", self._res_combo)
        self._fps_spin = QSpinBox(); self._fps_spin.setRange(1,120); self._fps_spin.setValue(30)
        export_form.addRow("FPS:", self._fps_spin)
        settings_layout.addWidget(export_group)

        self._progress_bar = QProgressBar(); self._progress_bar.setRange(0,100); self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        self._progress_bar.setStyleSheet("""
            QProgressBar { background: #2a2a32; border: 1px solid #444450; border-radius: 4px; text-align: center; color: #d0d0d8; height: 20px; }
            QProgressBar::chunk { background: #4478c0; border-radius: 3px; }
        """)
        settings_layout.addWidget(self._progress_bar)
        settings_layout.addStretch(1)
        scroll.setWidget(settings_widget); right_layout.addWidget(scroll, 1)

        btn_layout = QHBoxLayout(); btn_layout.setSpacing(8)
        self._play_btn = QPushButton("▶  Start Game")
        self._play_btn.setStyleSheet("QPushButton { background: #2d6a2d; color: white; border: 1px solid #3a8a3a; border-radius: 6px; padding: 10px 18px; font-weight: bold; font-size: 11pt; } QPushButton:hover { background: #3a8a3a; } QPushButton:pressed { background: #1f4f1f; }")
        btn_layout.addWidget(self._play_btn)
        self._stop_btn = QPushButton("■  Stop"); self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet("QPushButton { background: #6a2d2d; color: white; border: 1px solid #8a3a3a; border-radius: 6px; padding: 10px 18px; font-weight: bold; font-size: 11pt; } QPushButton:hover { background: #8a3a3a; } QPushButton:pressed { background: #4f1f1f; } QPushButton:disabled { background: #3a3a3a; color: #666; border-color: #555; }")
        btn_layout.addWidget(self._stop_btn)
        self._export_btn = QPushButton("💾  Export MP4")
        self._export_btn.setStyleSheet("QPushButton { background: #2d4a6a; color: white; border: 1px solid #3a6a8a; border-radius: 6px; padding: 10px 18px; font-weight: bold; font-size: 11pt; } QPushButton:hover { background: #3a6a8a; } QPushButton:pressed { background: #1f3f5f; }")
        btn_layout.addWidget(self._export_btn)
        right_layout.addLayout(btn_layout)
        main_layout.addWidget(right_widget, 2)

        self.setStyleSheet("QMainWindow { background: #1e1e22; } QWidget { background: transparent; } QGroupBox { background: #262630; }")

    def _connect_signals(self):
        self._play_btn.clicked.connect(self._start_game)
        self._stop_btn.clicked.connect(self._stop_game)
        self._export_btn.clicked.connect(self._export_video)
        self._theme_combo.currentTextChanged.connect(self._change_theme)
        self._sound_settings.theme_changed.connect(self._sound_engine.set_theme)
        self._sound_settings.volume_changed.connect(self._sound_engine.set_volume)
        self._sound_settings.mute_toggled.connect(self._sound_engine.set_muted)
        self._sound_settings.test_requested.connect(self._play_test_sound)

    def _change_theme(self, name):
        self._current_theme_name = name; theme = THEMES.get(name, BoardTheme())
        self._board_widget.set_theme(theme); self._sound_engine.play(SND_UI_CLICK)

    def _update_board_display(self):
        self._board_widget.set_board(self._board)

    def _start_game(self):
        if self._game_worker and self._game_worker.isRunning(): return
        self._board = chess.Board(); self._move_list.clear(); self._eval_cp = 0.0
        self._game_state = GAME_NORMAL; self._game_result = ""; self._game_detail = ""
        self._move_list_widget.clear(); self._eval_bar.set_eval(0); self._eval_bar.reset_game_state()
        self._update_board_display()

        white_type = self._white_ai_combo.currentIndex(); black_type = self._black_ai_combo.currentIndex()
        depth = self._depth_spin.value(); delay = self._delay_spin.value(); sf_path = find_stockfish()
        if (white_type == 2 or black_type == 2) and not sf_path:
            QMessageBox.warning(self, "Stockfish Not Found", "Stockfish engine not found. Please install it or choose a different AI."); return

        self._game_worker = GameWorker(white_type, black_type, depth, depth*150, sf_path, delay)
        self._game_worker.board_updated.connect(self._on_board_updated)
        self._game_worker.game_over.connect(self._on_game_over)
        self._game_worker.start()
        self._play_btn.setEnabled(False); self._stop_btn.setEnabled(True)
        self._status_label.setText("Game in progress..."); self._sound_engine.play(SND_GAME_START)

    def _stop_game(self):
        if self._game_worker and self._game_worker.isRunning():
            self._game_worker.abort(); self._game_worker.wait(2000)
        self._play_btn.setEnabled(True); self._stop_btn.setEnabled(False); self._status_label.setText("Game stopped")

    def _on_board_updated(self, fen, uci_move, eval_cp):
        board = chess.Board(fen); move = chess.Move.from_uci(uci_move)
        self._sound_engine.play_move_sound(board, move)
        san = board.san(move); board.push(move)
        self._board = board; self._move_list.append(san); self._eval_cp = eval_cp
        self._move_list_widget.add_move(san); self._eval_bar.set_eval(eval_cp)
        self._board_widget.set_board(board, move); self._board_widget.animate_move(move)
        move_num = len(self._move_list); side = "White" if board.turn == chess.WHITE else "Black"
        self._status_label.setText(f"Move {math.ceil(move_num/2)}: {san} ({side} to move)")

    def _on_game_over(self, state, result, detail):
        self._game_state=state; self._game_result=result; self._game_detail=detail
        self._eval_bar.set_game_state(state, result, detail)
        self._play_btn.setEnabled(True); self._stop_btn.setEnabled(False)
        if state == GAME_CHECKMATE:
            winner = "White" if result=="1-0" else "Black"
            self._status_label.setText(f"Checkmate! {winner} wins. {result}"); self._sound_engine.play(SND_CHECKMATE)
        elif state == GAME_STALEMATE:
            self._status_label.setText("Stalemate! Draw."); self._sound_engine.play(SND_STALEMATE)
        else:
            self._status_label.setText(f"Draw! {detail}"); self._sound_engine.play(SND_DRAW)

    def _export_video(self):
        if not self._move_list:
            QMessageBox.information(self, "No Game", "Play a game first before exporting."); return
        if not HAS_CV2:
            QMessageBox.warning(self, "Missing Dependency", "OpenCV (cv2) is required for video export.\npip install opencv-python"); return
        filepath, _ = QFileDialog.getSaveFileName(self, "Export MP4", "chess_game.mp4", "MP4 Files (*.mp4)")
        if not filepath: return
        pgn_text = self._generate_pgn()
        res_key = self._res_combo.currentText(); w,h = RESOLUTION_SIZES.get(res_key, (1920,1080))
        fps = self._fps_spin.value(); theme = THEMES.get(self._current_theme_name, BoardTheme())
        self._export_worker = ExportWorker(pgn_text, w, h, fps, theme, "White", "Black", filepath)
        self._export_worker.progress_updated.connect(self._on_export_progress)
        self._export_worker.export_finished.connect(self._on_export_finished)
        self._export_worker.export_error.connect(self._on_export_error)
        self._export_worker.start()
        self._export_btn.setEnabled(False); self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0); self._status_label.setText("Exporting video...")
        self._sound_engine.play(SND_UI_CLICK)

    def _generate_pgn(self):
        board = chess.Board(); game = chess.pgn.Game(); node = game
        for san in self._move_list:
            move = board.parse_san(san); node = node.add_variation(move); board.push(move)
        game.headers["Result"] = self._game_result if self._game_result else "*"
        return str(game)

    def _on_export_progress(self, current, total):
        pct = int(100*current/total) if total > 0 else 0; self._progress_bar.setValue(pct)

    def _on_export_finished(self, filepath):
        self._export_btn.setEnabled(True); self._progress_bar.setVisible(False)
        self._status_label.setText(f"Export complete: {filepath}"); self._sound_engine.play(SND_GAME_START)

    def _on_export_error(self, error):
        self._export_btn.setEnabled(True); self._progress_bar.setVisible(False)
        self._status_label.setText("Export failed"); QMessageBox.warning(self, "Export Error", error)

    def _play_test_sound(self):
        if not self._sound_engine.enabled: return
        sounds = [SND_GAME_START, SND_MOVE, SND_CAPTURE, SND_CHECK, SND_CASTLE, SND_CHECKMATE]
        delays = [0, 400, 900, 1500, 2100, 2800]
        for snd, delay in zip(sounds, delays):
            QTimer.singleShot(delay, lambda s=snd: self._sound_engine.play(s))

    def closeEvent(self, event):
        if self._game_worker and self._game_worker.isRunning():
            self._game_worker.abort(); self._game_worker.wait(1000)
        if self._export_worker and self._export_worker.isRunning():
            self._export_worker.abort(); self._export_worker.wait(1000)
        self._sound_engine.cleanup()
        super().closeEvent(event)


# ════════════════════════════════════════════════════════════════════
#  Entry Point
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor(30, 30, 32))
    palette.setColor(palette.ColorRole.WindowText, QColor(200, 200, 210))
    palette.setColor(palette.ColorRole.Base, QColor(26, 26, 30))
    palette.setColor(palette.ColorRole.AlternateBase, QColor(38, 38, 42))
    palette.setColor(palette.ColorRole.ToolTipBase, QColor(42, 42, 48))
    palette.setColor(palette.ColorRole.ToolTipText, QColor(200, 200, 210))
    palette.setColor(palette.ColorRole.Text, QColor(200, 200, 210))
    palette.setColor(palette.ColorRole.Button, QColor(42, 42, 48))
    palette.setColor(palette.ColorRole.ButtonText, QColor(200, 200, 210))
    palette.setColor(palette.ColorRole.BrightText, QColor(255, 50, 50))
    palette.setColor(palette.ColorRole.Highlight, QColor(42, 100, 195))
    palette.setColor(palette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())