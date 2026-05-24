#!/usr/bin/env python3
"""
PGN → MP4 Converter — Single & Batch PGN file to video export with PySide6 GUI.

Standalone application. No other project files required.

Usage:
    python pgn_to_mp4.py

Requirements:
    pip install PySide6 chess opencv-python numpy
"""

import os
import sys
import io
import glob
import math
import time
import shutil
import logging
import subprocess
import tempfile

import chess
import chess.pgn

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QSpinBox, QDoubleSpinBox,
    QTextEdit, QGroupBox, QCheckBox, QLineEdit, QComboBox,
    QFormLayout, QTabWidget, QScrollArea, QProgressBar,
    QFileDialog, QSizePolicy, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QSplitter,
)
from PySide6.QtCore import Qt, QThread, Signal, QRectF, QPointF, QMimeData
from PySide6.QtGui import (
    QPainter, QColor, QFont, QImage, QLinearGradient,
    QPainterPath, QPen, QKeySequence, QShortcut, QDragEnterEvent,
    QDropEvent,
)

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PGN2MP4")


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

# IMPROVED: Piece values for material balance display
PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}

RESOLUTION_SIZES = {
    "1920×1080": (1920, 1080),
    "1280×720": (1280, 720),
    "3840×2160": (3840, 2160),  # NEW: 4K support
}
RESOLUTION_LIST = list(RESOLUTION_SIZES.keys())

GAME_NORMAL = "normal"
GAME_CHECKMATE = "checkmate"
GAME_STALEMATE = "stalemate"
GAME_DRAW = "draw"
GAME_INSUFFICIENT = "insufficient"

DEFAULT_ANIM_DURATION = 0.3  # NEW: seconds for move animation


class BoardTheme:
    """Visual theme for chess board rendering."""

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
    """Try to find Stockfish on the system."""
    p = shutil.which("stockfish")
    if p:
        return p
    candidates = [
        "/usr/games/stockfish",
        "/usr/local/bin/stockfish",
        r"C:\Stockfish\stockfish.exe",
        r"C:\Program Files\Stockfish\stockfish.exe",
        r"C:\Program Files (x86)\Stockfish\stockfish.exe",
        # NEW: macOS Homebrew paths
        "/opt/homebrew/bin/stockfish",
        "/usr/local/Cellar/stockfish",
    ]
    for d in candidates:
        if os.path.isfile(d):
            return d
        # IMPROVED: Search in directories for macOS Cellar
        if os.path.isdir(d):
            for root, dirs, files in os.walk(d):
                for f in files:
                    if "stockfish" in f.lower():
                        return os.path.join(root, f)
    return None


# ════════════════════════════════════════════════════════════════════
#  BoardRenderer — thread-safe chess board → QImage
# ════════════════════════════════════════════════════════════════════

class BoardRenderer:
    """Renders a chess board to QImage — no QWidget dependency.

    Safe to call from any thread (QPainter on QImage is explicitly
    supported by Qt in non-GUI threads).
    """

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
        self._flash_squares = ()
        self._flash_opacity = 0.0
        self.policy_vis: dict = {}

    # ── Render entry point ─────────────────────────────────────────

    def render(self, size=1080):
        """Render board to QImage at *size*×*size* pixels."""
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

    # ── Internal helpers ───────────────────────────────────────────

    def _sq_rect(self, sq, t, m, sz):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        c = (7 - f) if self.flipped else f
        rw = r if self.flipped else (7 - r)
        return QRectF(m + c * sz, m + rw * sz, sz, sz)

    def _paint(self, p, t, m, sz):
        # Background & border
        p.fillRect(QRectF(0, 0, t, t), self.theme.bg)
        p.setPen(Qt.NoPen)
        p.setBrush(self.theme.border)
        p.drawRect(QRectF(0, 0, t, t))

        # Squares
        for s in chess.SQUARES:
            rect = self._sq_rect(s, t, m, sz)
            f, r = chess.square_file(s), chess.square_rank(s)
            base = self.theme.light_sq if (f + r) % 2 == 0 else self.theme.dark_sq
            p.fillRect(rect, base)
            if self.last_move and s in (
                self.last_move.from_square,
                self.last_move.to_square,
            ):
                p.fillRect(rect, self.theme.last_move)
            if s == self.selected_sq:
                p.fillRect(rect, self.theme.highlight)
            if s in self.highlighted:
                p.fillRect(rect, QColor(0, 130, 255, 80))

        # Flash
        if self._flash_squares and self._flash_opacity > 0:
            for fsq in self._flash_squares:
                p.fillRect(
                    self._sq_rect(fsq, t, m, sz),
                    QColor(255, 255, 180, int(self._flash_opacity * 140)),
                )

        # Check
        if self._check_square is not None and self._check_opacity > 0:
            p.fillRect(
                self._sq_rect(self._check_square, t, m, sz),
                QColor(255, 30, 30, int(self._check_opacity * 130)),
            )

        # Coordinates
        if self.show_coords:
            fnt = QFont("Arial", max(7, int(sz * 0.14)))
            fnt.setBold(True)
            p.setFont(fnt)
            p.setPen(self.theme.coord)
            for i in range(8):
                fl = chr(ord("h") - i if self.flipped else ord("a") + i)
                rn = str(i + 1 if self.flipped else 8 - i)
                p.drawText(
                    QRectF(m + i * sz + sz / 2 - sz / 2, t - m, sz, m),
                    Qt.AlignCenter,
                    fl,
                )
                p.drawText(
                    QRectF(0, m + i * sz, m, sz), Qt.AlignCenter, rn
                )

        # Legal-move dots
        for mv in self.legal_targets:
            rect = self._sq_rect(mv, t, m, sz)
            p.setPen(Qt.NoPen)
            if self.board.piece_at(mv):
                p.setBrush(QColor(0, 0, 0, 60))
                p.drawEllipse(
                    rect.adjusted(sz * 0.1, sz * 0.1, -sz * 0.1, -sz * 0.1)
                )
            else:
                p.setBrush(QColor(0, 0, 0, 40))
                p.drawEllipse(rect.center(), sz * 0.15, sz * 0.15)

        # Pieces — skip animated squares
        ats = self.anim_move.to_square if self.anim_move else None
        rts = self.anim_rook_move[1] if self.anim_rook_move else None
        for s in chess.SQUARES:
            pc = self.board.piece_at(s)
            if pc:
                if self.anim_move and s == ats:
                    continue
                if self.anim_rook_move and s == rts:
                    continue
                self._draw_piece(p, pc, self._sq_rect(s, t, m, sz), sz)

        # Animated main piece
        if self.anim_move:
            pc = self.board.piece_at(self.anim_move.to_square)
            if pc:
                pr = self.anim_progress
                rf = self._sq_rect(self.anim_move.from_square, t, m, sz)
                rt = self._sq_rect(self.anim_move.to_square, t, m, sz)
                self._draw_piece(
                    p,
                    pc,
                    QRectF(
                        rf.x() + (rt.x() - rf.x()) * pr,
                        rf.y() + (rt.y() - rf.y()) * pr,
                        sz,
                        sz,
                    ),
                    sz,
                )

        # Animated rook (castling)
        if self.anim_rook_move:
            rfs, rts_val = self.anim_rook_move
            pc = self.board.piece_at(rts_val)
            if pc:
                pr = self.anim_progress
                rf = self._sq_rect(rfs, t, m, sz)
                rt = self._sq_rect(rts_val, t, m, sz)
                self._draw_piece(
                    p,
                    pc,
                    QRectF(
                        rf.x() + (rt.x() - rf.x()) * pr,
                        rf.y() + (rt.y() - rf.y()) * pr,
                        sz,
                        sz,
                    ),
                    sz,
                )

    def _draw_piece(self, p, piece, rect, sz):
        sym = PIECE_SYM.get((piece.piece_type, piece.color), "?")
        # IMPROVED: Try multiple fonts for better cross-platform support
        font_families = ["Segoe UI Symbol", "Arial Unicode MS", "DejaVu Sans", "Noto Sans", "Arial"]
        for family in font_families:
            fnt = QFont(family, sz * 0.72)
            fnt.setStyleStrategy(QFont.PreferAntialias)
            fm = QFontMetrics(fnt)
            if fm.inFont(sym) or family == font_families[-1]:
                p.setFont(fnt)
                break
        if piece.color == chess.WHITE:
            p.setPen(QPen(QColor(0, 0, 0, 200), max(1, sz * 0.04)))
            p.drawText(rect, Qt.AlignCenter, sym)
            p.setPen(QColor(255, 255, 255))
            p.drawText(rect, Qt.AlignCenter, sym)
        else:
            p.setPen(QColor(30, 30, 30))
            p.drawText(rect, Qt.AlignCenter, sym)


# ════════════════════════════════════════════════════════════════════
#  VideoRenderer — full video frame (board + eval + move list)
# ════════════════════════════════════════════════════════════════════

class VideoRenderer:
    """Renders a full video frame (board + eval bar + move list + overlays).

    Uses BoardRenderer, so it is safe to call from any thread.
    """

    def __init__(
        self, board_renderer, w=1920, h=1080, bg_color=QColor(30, 30, 32)
    ):
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
        # NEW: Captured pieces tracking
        self.captured_by_white = []  # black pieces captured by white
        self.captured_by_black = []  # white pieces captured by black
        # NEW: Opening name
        self.opening_name = ""

    @staticmethod
    def _cp2r(cp):
        if cp >= 9000:
            return 1.0
        if cp <= -9000:
            return 0.0
        return 1.0 / (1.0 + math.exp(-0.004 * max(-10000, min(10000, cp))))

    # NEW: Compute captured pieces from a board position
    @staticmethod
    def compute_captures(board):
        """Return (captured_by_white, captured_by_black) as lists of (piece_type, color)."""
        start_pieces = {
            (chess.PAWN, chess.WHITE): 8, (chess.KNIGHT, chess.WHITE): 2,
            (chess.BISHOP, chess.WHITE): 2, (chess.ROOK, chess.WHITE): 2,
            (chess.QUEEN, chess.WHITE): 1,
            (chess.PAWN, chess.BLACK): 8, (chess.KNIGHT, chess.BLACK): 2,
            (chess.BISHOP, chess.BLACK): 2, (chess.ROOK, chess.BLACK): 2,
            (chess.QUEEN, chess.BLACK): 1,
        }
        current = {}
        for pt in chess.PIECE_TYPES[:-1]:  # exclude king
            for color in (chess.WHITE, chess.BLACK):
                current[(pt, color)] = len(board.pieces(pt, color))

        captured_by_white = []  # black pieces taken
        captured_by_black = []  # white pieces taken
        for pt in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]:
            diff_b = start_pieces.get((pt, chess.BLACK), 0) - current.get((pt, chess.BLACK), 0)
            diff_w = start_pieces.get((pt, chess.WHITE), 0) - current.get((pt, chess.WHITE), 0)
            for _ in range(diff_b):
                captured_by_white.append((pt, chess.BLACK))
            for _ in range(diff_w):
                captured_by_black.append((pt, chess.WHITE))

        return captured_by_white, captured_by_black

    # NEW: Draw captured pieces
    def _draw_captured(self, p, x, y, width, captures, color, sz):
        """Draw captured piece symbols and material advantage."""
        if not captures:
            return 0
        font_sz = max(8, int(sz * 0.04))
        fnt = QFont("Segoe UI Symbol", font_sz)
        p.setFont(fnt)
        p.setPen(QColor(200, 200, 200) if color == chess.WHITE else QColor(160, 160, 160))

        symbols = ""
        for pt, _ in captures:
            symbols += PIECE_SYM.get((pt, color), "")

        # Truncate if too long
        max_chars = max(1, int(width / (font_sz * 0.6)))
        if len(symbols) > max_chars:
            symbols = symbols[:max_chars]

        p.drawText(QRectF(x, y, width, font_sz + 6), Qt.AlignLeft | Qt.AlignVCenter, symbols)

        # Material advantage
        mat_adv = sum(PIECE_VALUES.get(pt, 0) for pt, _ in captures)
        return mat_adv

    def render(self):
        img = QImage(self.w, self.h, QImage.Format_ARGB32)
        img.fill(self.bg_color)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        margin = 40
        bsz = int(self.h * 0.85)
        by = (self.h - bsz) // 2

        # ── Eval bar ───────────────────────────────────────────────
        ebw = max(32, int(bsz * 0.05))
        ebx = margin
        ratio = self._cp2r(self.eval_cp)
        wh = max(0, min(bsz, int(bsz * ratio)))

        p.setPen(QPen(QColor(55, 55, 62), 1.2))
        p.setBrush(QColor(18, 18, 22))
        p.drawRoundedRect(QRectF(ebx - 2, by - 2, ebw + 4, bsz + 4), 7, 7)

        blk = QLinearGradient(ebx, by, ebx, by + bsz)
        blk.setColorAt(0.0, QColor(62, 62, 70))
        blk.setColorAt(0.5, QColor(48, 48, 55))
        blk.setColorAt(1.0, QColor(40, 40, 47))
        p.setPen(Qt.NoPen)
        p.setBrush(blk)
        p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5)

        if wh > 0:
            wt = by + bsz - wh
            wg = QLinearGradient(ebx, wt, ebx, by + bsz)
            wg.setColorAt(0.0, QColor(232, 228, 218))
            wg.setColorAt(0.4, QColor(240, 237, 228))
            wg.setColorAt(1.0, QColor(248, 245, 238))
            p.setBrush(wg)
            if wh >= bsz:
                p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5)
            elif wh < 10:
                p.drawRoundedRect(QRectF(ebx, wt, ebw, wh), 5, 5)
            else:
                path = QPainterPath()
                path.moveTo(ebx, wt)
                path.lineTo(ebx + ebw, wt)
                path.lineTo(ebx + ebw, by + bsz - 5)
                path.quadTo(ebx + ebw, by + bsz, ebx + ebw - 5, by + bsz)
                path.lineTo(ebx + 5, by + bsz)
                path.quadTo(ebx, by + bsz, ebx, by + bsz - 5)
                path.lineTo(ebx, wt)
                path.closeSubpath()
                p.drawPath(path)

        # Centre line
        p.setPen(QPen(QColor(120, 180, 255, 70), 1, Qt.DashLine))
        p.drawLine(QPointF(ebx + 2, by + bsz / 2), QPointF(ebx + ebw - 2, by + bsz / 2))

        # Divider
        bdy = by + bsz - wh
        if 0 < wh < bsz:
            p.setPen(QPen(QColor(110, 105, 95, 160), 1.5))
            p.drawLine(QPointF(ebx + 2, bdy), QPointF(ebx + ebw - 2, bdy))

        # Tick marks
        p.setPen(Qt.NoPen)
        for cp_val in range(-900, 901, 100):
            r = self._cp2r(cp_val)
            y = by + bsz - r * bsz
            if by + 4 > y or y > by + bsz - 4:
                continue
            is_major = cp_val % 200 == 0
            tw = 6 if is_major else 3
            p.setBrush(QColor(255, 255, 255, 60 if is_major else 30))
            p.drawRect(QRectF(ebx + ebw - tw, y - 0.5, tw, 1.0))
            if is_major and cp_val % 400 == 0 and cp_val != 0:
                fnt = QFont("Segoe UI", max(7, int(ebw * 0.18)))
                p.setFont(fnt)
                p.setPen(QColor(170, 170, 190, 130))
                p.drawText(
                    QRectF(ebx + 1, y - 7, ebw - 7, 12),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    f"{cp_val // 100:+d}",
                )
                p.setPen(Qt.NoPen)

        # Eval pill or game-state overlay
        if self.game_state == GAME_NORMAL:
            is_mate = abs(self.eval_cp) > 9000
            txt = (
                f"M{int(abs(self.eval_cp) - 10000)}"
                if is_mate
                else f"{self.eval_cp / 100.0:+.1f}"
            )
            efsz = max(9, min(14, int(ebw * 0.36)))
            efnt = QFont("Segoe UI", efsz, QFont.Bold)
            p.setFont(efnt)
            efm = p.fontMetrics()
            etw = efm.horizontalAdvance(txt) + 12
            epx, eph = max(etw, 30), 22
            ety = bdy if 0 < wh < bsz else by + bsz / 2
            ety = max(by + eph / 2 + 4, min(by + bsz - eph / 2 - 4, ety))
            epill = QRectF(ebx + (ebw - epx) / 2, ety - eph / 2, epx, eph)
            on_w = (ety >= by + bsz - wh) if 0 < wh < bsz else (self.eval_cp >= 0)
            if is_mate:
                epbg = (
                    QColor(30, 170, 60, 220)
                    if self.eval_cp > 0
                    else QColor(210, 45, 45, 220)
                )
                epfg = QColor(255, 255, 255)
            else:
                epbg = (
                    QColor(255, 255, 255, 200) if on_w else QColor(22, 22, 30, 210)
                )
                epfg = QColor(35, 32, 28) if on_w else QColor(238, 234, 226)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 50))
            p.drawRoundedRect(epill.adjusted(1, 1, 1, 1), 10, 10)
            p.setBrush(epbg)
            p.drawRoundedRect(epill, 10, 10)
            p.setPen(epfg)
            p.drawText(epill, Qt.AlignCenter, txt)
        else:
            self._draw_video_eval_game_state(p, ebx, by, ebw, bsz, wh)

        # ── Board ──────────────────────────────────────────────────
        bx_board = ebx + ebw + margin
        bimg = self.board_renderer.render(bsz)
        p.drawImage(QRectF(bx_board, by, bsz, bsz), bimg)

        # ── Move list ──────────────────────────────────────────────
        mx = bx_board + bsz + margin
        mw = self.w - mx - margin
        if mw > 60:
            # IMPROVED: Better move list panel
            p.setBrush(QColor(38, 38, 42))
            p.setPen(QPen(QColor(55, 55, 62), 1))
            p.drawRoundedRect(QRectF(mx, by, mw, bsz), 8, 8)

            # NEW: Opening name at top
            list_y = by + 10
            if self.opening_name:
                p.setFont(QFont("Segoe UI", max(10, int(self.h * 0.014)), QFont.Bold))
                p.setPen(QColor(140, 180, 220))
                p.drawText(QRectF(mx + 10, list_y, mw - 20, 22), Qt.AlignLeft, self.opening_name)
                list_y += 24

            # Column headers
            p.setFont(QFont("Consolas", max(9, int(self.h * 0.012))))
            p.setPen(QColor(90, 90, 100))
            p.drawText(QRectF(mx + 10, list_y, 35, 20), Qt.AlignLeft, "#")
            p.drawText(QRectF(mx + 40, list_y, 65, 20), Qt.AlignLeft, "White")
            p.drawText(QRectF(mx + 115, list_y, 65, 20), Qt.AlignLeft, "Black")
            list_y += 22

            # Separator line
            p.setPen(QPen(QColor(55, 55, 62), 1))
            p.drawLine(QPointF(mx + 8, list_y), QPointF(mx + mw - 8, list_y))
            list_y += 4

            lh = max(20, int(self.h * 0.024))
            for i, san in enumerate(self.move_list_text):
                if list_y + lh > by + bsz - 10:
                    # IMPROVED: Show "..." when truncated
                    p.setFont(QFont("Segoe UI", 9))
                    p.setPen(QColor(100, 100, 120))
                    p.drawText(QRectF(mx + 10, list_y, mw - 20, lh), Qt.AlignCenter, "…")
                    break

                is_current = (i == self.current_move_index)

                # IMPROVED: Highlight current move row
                if is_current:
                    row = i // 2
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(70, 130, 200, 40))
                    p.drawRoundedRect(QRectF(mx + 5, list_y - 1, mw - 10, lh + 2), 3, 3)

                p.setFont(QFont("Consolas", max(10, int(self.h * 0.013))))
                if i % 2 == 0:
                    move_num = f"{i // 2 + 1}."
                    p.setPen(QColor(100, 100, 120))
                    p.drawText(QRectF(mx + 10, list_y, 35, lh), Qt.AlignLeft, move_num)
                    p.setPen(
                        QColor(130, 200, 255) if is_current else QColor(210, 210, 210)
                    )
                    p.drawText(QRectF(mx + 40, list_y, 70, lh), Qt.AlignLeft, san)
                else:
                    p.setPen(
                        QColor(130, 200, 255) if is_current else QColor(210, 210, 210)
                    )
                    p.drawText(QRectF(mx + 115, list_y, 70, lh), Qt.AlignLeft, san)
                    list_y += lh

            # IMPROVED: Handle odd number of moves (last move on white's line)
            if len(self.move_list_text) % 2 == 1:
                list_y += lh

        # ── Player names + captured pieces ─────────────────────────
        name_font_sz = int(self.h * 0.022)
        p.setFont(QFont("Segoe UI", name_font_sz, QFont.Bold))

        # Black player (top)
        p.setPen(QColor(180, 180, 180))
        p.drawText(
            QRectF(bx_board, by - 52, bsz / 2, 22),
            Qt.AlignLeft | Qt.AlignVCenter,
            self.black_name,
        )
        # Captured pieces near black name (pieces black lost)
        if self.captured_by_white:
            cap_str = "".join(PIECE_SYM.get((pt, clr), "") for pt, clr in self.captured_by_white)
            p.setFont(QFont("Segoe UI Symbol", max(9, int(self.h * 0.016))))
            p.setPen(QColor(150, 150, 150))
            p.drawText(
                QRectF(bx_board + bsz / 2, by - 52, bsz / 2, 22),
                Qt.AlignRight | Qt.AlignVCenter,
                cap_str,
            )

        # White player (bottom)
        p.setFont(QFont("Segoe UI", name_font_sz, QFont.Bold))
        p.setPen(QColor(200, 200, 200))
        p.drawText(
            QRectF(bx_board, by + bsz + 8, bsz / 2, 22),
            Qt.AlignLeft | Qt.AlignVCenter,
            self.white_name,
        )
        # Captured pieces near white name (pieces white lost)
        if self.captured_by_black:
            cap_str = "".join(PIECE_SYM.get((pt, clr), "") for pt, clr in self.captured_by_black)
            p.setFont(QFont("Segoe UI Symbol", max(9, int(self.h * 0.016))))
            p.setPen(QColor(150, 150, 150))
            p.drawText(
                QRectF(bx_board + bsz / 2, by + bsz + 8, bsz / 2, 22),
                Qt.AlignRight | Qt.AlignVCenter,
                cap_str,
            )

        # ── Game result banner ─────────────────────────────────────
        if self.game_state != GAME_NORMAL:
            self._draw_video_result_banner(p, bx_board, by, bsz)

        # ── Image overlays ─────────────────────────────────────────
        for ov in self.overlays:
            if os.path.exists(ov["path"]):
                oi = QImage(ov["path"])
                if not oi.isNull():
                    p.drawImage(QRectF(ov["x"], ov["y"], ov["w"], ov["h"]), oi)

        p.end()
        return img

    # ── Video eval bar game-state overlays ─────────────────────────

    def _draw_video_eval_game_state(self, p, ebx, by, ebw, bsz, wh):
        if self.game_state == GAME_CHECKMATE:
            white_wins = self.eval_cp > 0 or self.game_result == "1-0"
            p.setPen(Qt.NoPen)
            tint = (
                QColor(25, 160, 55, 40) if white_wins else QColor(190, 35, 35, 40)
            )
            p.setBrush(tint)
            p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5)
            center_y = by + bsz / 2
            bh_b = max(40, int(bsz * 0.10))
            banner = QRectF(ebx - 4, center_y - bh_b / 2, ebw + 8, bh_b)
            bg = QColor(25, 140, 55, 220) if white_wins else QColor(190, 35, 35, 220)
            p.setBrush(QColor(0, 0, 0, 70))
            p.drawRoundedRect(banner.adjusted(2, 2, 2, 2), 6, 6)
            p.setBrush(bg)
            p.setPen(QPen(QColor(255, 255, 255, 50), 0.8))
            p.drawRoundedRect(banner, 6, 6)
            fsz = max(8, int(bh_b * 0.4))
            p.setFont(QFont("Segoe UI", fsz, QFont.Bold))
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                banner, Qt.AlignCenter,
                self.game_result or ("1-0" if white_wins else "0-1"),
            )
        elif self.game_state in (GAME_STALEMATE, GAME_DRAW, GAME_INSUFFICIENT):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(180, 150, 40, 20))
            p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5)
            center_y = by + bsz / 2
            p.setPen(QPen(QColor(220, 190, 60, 130), 2.0))
            p.drawLine(QPointF(ebx + 2, center_y), QPointF(ebx + ebw - 2, center_y))
            bh_b = max(50, int(bsz * 0.12))
            banner = QRectF(ebx - 4, center_y - bh_b / 2, ebw + 8, bh_b)
            bg = (
                QColor(180, 150, 40, 210)
                if self.game_state == GAME_STALEMATE
                else QColor(100, 100, 110, 200)
            )
            p.setBrush(QColor(0, 0, 0, 60))
            p.drawRoundedRect(banner.adjusted(2, 2, 2, 2), 6, 6)
            p.setBrush(bg)
            p.setPen(QPen(QColor(255, 255, 255, 45), 0.8))
            p.drawRoundedRect(banner, 6, 6)
            fsz = max(8, int(bh_b * 0.35))
            p.setFont(QFont("Segoe UI", fsz, QFont.Bold))
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                QRectF(banner.x(), banner.y(), banner.width(), banner.height() * 0.55),
                Qt.AlignCenter,
                self.game_result or "½-½",
            )
            detail_map = {
                GAME_STALEMATE: "STALEMATE",
                GAME_INSUFFICIENT: "INSUFF.",
                GAME_DRAW: "DRAW",
            }
            p.setFont(QFont("Segoe UI", max(6, int(bh_b * 0.2))))
            p.setPen(QColor(255, 255, 255, 180))
            p.drawText(
                QRectF(
                    banner.x(), banner.y() + banner.height() * 0.5,
                    banner.width(), banner.height() * 0.5,
                ),
                Qt.AlignCenter,
                self.game_detail or detail_map.get(self.game_state, "DRAW"),
            )

    def _draw_video_result_banner(self, p, bx, by, bsz):
        banner_h = int(self.h * 0.06)
        banner_y = by + bsz + 35
        banner = QRectF(bx, banner_y, bsz, banner_h)
        if self.game_state == GAME_CHECKMATE:
            white_wins = self.eval_cp > 0 or self.game_result == "1-0"
            bg = QColor(25, 140, 55, 210) if white_wins else QColor(190, 35, 35, 210)
            txt = (
                f"♔ CHECKMATE  {self.game_result or '1-0'}"
                if white_wins
                else f"♚ CHECKMATE  {self.game_result or '0-1'}"
            )
        else:
            bg = QColor(160, 140, 40, 200)
            detail = self.game_detail or ""
            txt = f"½-½  {detail}" if detail else "½-½  DRAW"
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawRoundedRect(banner.adjusted(2, 2, 2, 2), 6, 6)
        p.setBrush(bg)
        p.setPen(QPen(QColor(255, 255, 255, 50), 1.0))
        p.drawRoundedRect(banner, 6, 6)
        fsz = max(10, int(banner_h * 0.45))
        p.setFont(QFont("Segoe UI", fsz, QFont.Bold))
        p.setPen(QColor(255, 255, 255, 240))
        p.drawText(banner, Qt.AlignCenter, txt)


# ════════════════════════════════════════════════════════════════════
#  Synchronous UCI wrapper
# ════════════════════════════════════════════════════════════════════

class _SyncUCI:
    """Minimal synchronous UCI client for Stockfish."""

    def __init__(self, path):
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"Stockfish not found: {path}")
        self.proc = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._cmd("uci")
        self._read("uciok")

    def _cmd(self, t):
        try:
            self.proc.stdin.write(t + "\n")
            self.proc.stdin.flush()
        except BrokenPipeError:
            pass

    def _read(self, tok, timeout=30):
        lines = []
        deadline = time.time() + timeout
        while True:
            if time.time() > deadline:
                logger.warning("UCI read timeout waiting for '%s'", tok)
                break
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            lines.append(line)
            if tok in line:
                break
        return lines

    def analyse(self, fen, depth=18):
        board = chess.Board(fen)
        if not board.legal_moves:
            return None, 0
        self._cmd(f"position fen {fen}")
        self._cmd(f"go depth {depth}")
        bm = None
        sc = 0
        wt = board.turn == chess.WHITE
        for line in self._read("bestmove"):
            if line.startswith("info") and " score " in line:
                parts = line.split()
                if "cp" in parts:
                    idx = parts.index("cp")
                    try:
                        raw = int(parts[idx + 1])
                        # Convert to white's perspective
                        sc = raw if wt else -raw
                    except (ValueError, IndexError):
                        pass
                elif "mate" in parts:
                    idx = parts.index("mate")
                    try:
                        mi = int(parts[idx + 1])
                        raw = 10000 if mi > 0 else -10000
                        sc = raw if wt else -raw
                    except (ValueError, IndexError):
                        pass
            if line.startswith("bestmove"):
                parts = line.split()
                bm = parts[1] if len(parts) >= 2 else None
        return bm, sc

    def close(self):
        try:
            self._cmd("quit")
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════════
#  Helper functions
# ════════════════════════════════════════════════════════════════════

def _detect_game_state(board):
    """Return (state, result, detail) for a chess.Board."""
    if board.is_checkmate():
        result = "1-0" if board.turn == chess.BLACK else "0-1"
        return GAME_CHECKMATE, result, "Checkmate"
    if board.is_stalemate():
        return GAME_STALEMATE, "½-½", "Stalemate"
    if board.is_insufficient_material():
        return GAME_INSUFFICIENT, "½-½", "Insufficient Material"
    if board.is_game_over():
        # IMPROVED: More specific draw reasons
        if board.is_fifty_moves():
            return GAME_DRAW, "½-½", "50-Move Rule"
        if board.is_repetition():
            return GAME_DRAW, "½-½", "Repetition"
        return GAME_DRAW, "½-½", "Draw"
    return GAME_NORMAL, "", ""


# NEW: Helper to detect castling and return rook move info
def _get_castling_rook_move(move):
    """Return (rook_from, rook_to) if move is castling, else None."""
    from_file = chess.square_file(move.from_square)
    to_file = chess.square_file(move.to_square)
    if from_file == 4 and abs(to_file - from_file) == 2:
        rank = chess.square_rank(move.from_square)
        if to_file == 6:  # kingside
            return (chess.square(7, rank), chess.square(5, rank))
        else:  # queenside
            return (chess.square(0, rank), chess.square(3, rank))
    return None


def _qimage_to_bgr_numpy(qimg):
    """Convert QImage to BGR numpy array for OpenCV."""
    if not HAS_CV2:
        return None
    img = qimg.convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    ptr = img.bits()
    ptr.setsize(h * w * 3)
    arr = np.array(ptr, dtype=np.uint8).reshape((h, w, 3))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


# NEW: Try to find a working video codec
def _create_video_writer(output_path, fps, w, h):
    """Try to create a VideoWriter with the best available codec.

    Returns (writer, used_path, used_codec) or (None, None, None).
    """
    codecs = [
        ("avc1", ".mp4"),
        ("X264", ".mp4"),
        ("mp4v", ".mp4"),
        ("XVID", ".avi"),
        ("MJPG", ".avi"),
    ]
    for fc, ext in codecs:
        used_path = output_path
        if not used_path.lower().endswith(ext):
            used_path = os.path.splitext(used_path)[0] + ext
        writer = cv2.VideoWriter(
            used_path, cv2.VideoWriter_fourcc(*fc), fps, (w, h)
        )
        if writer.isOpened():
            return writer, used_path, fc
        writer.release()
    return None, None, None


# ════════════════════════════════════════════════════════════════════
#  Worker Threads
# ════════════════════════════════════════════════════════════════════

class StreamingExportWorker(QThread):
    """Render + export in one pass (constant memory)."""

    progress = Signal(int, str)
    export_finished = Signal(str)

    def __init__(
        self,
        game,
        move_list,
        eval_cache,
        board_renderer,
        video_bg_color,
        white_name,
        black_name,
        overlays,
        fps=30,
        hold=1.5,
        res_str="1920×1080",
        output_path="chess_video.mp4",
        stockfish_path="",
        eval_during_export=False,
        anim_duration=DEFAULT_ANIM_DURATION,  # NEW
    ):
        super().__init__()
        self.game = game
        self.move_list = move_list
        self.eval_cache = dict(eval_cache)
        self.board_renderer = board_renderer
        self.video_bg_color = video_bg_color
        self.white_name = white_name
        self.black_name = black_name
        self.overlays = overlays
        self.fps = fps
        self.hold = hold
        self.res_str = res_str
        self.output_path = output_path
        self.stockfish_path = stockfish_path
        self.eval_during_export = eval_during_export
        self.anim_duration = anim_duration  # NEW
        self._c = False

    def cancel(self):
        self._c = True

    def run(self):
        if not HAS_CV2:
            self.export_finished.emit("ERROR: opencv-python is not installed")
            return
        if not self.move_list:
            self.export_finished.emit("ERROR: No moves to export")
            return

        res = RESOLUTION_SIZES.get(self.res_str, (1920, 1080))
        w, h = res

        writer, used_path, used_codec = _create_video_writer(
            self.output_path, self.fps, w, h
        )
        if not writer:
            self.export_finished.emit("ERROR: No video codec found")
            return

        try:
            self._stream(writer, w, h, used_path, used_codec)
        except Exception as e:
            logger.exception("Export failed")
            writer.release()
            if os.path.exists(used_path):
                try:
                    os.remove(used_path)
                except OSError:
                    pass
            self.export_finished.emit(f"ERROR: {e}")

    def _write_frame(self, writer, vr, w, h):
        """Render and write a single frame. Returns True if written."""
        bgr = _qimage_to_bgr_numpy(vr.render())
        if bgr is not None:
            if bgr.shape[:2] != (h, w):
                bgr = cv2.resize(bgr, (w, h))
            writer.write(bgr)
            return True
        return False

    def _stream(self, writer, w, h, used_path, used_codec):
        ml = self.move_list
        hf = max(1, int(self.hold * self.fps))
        # NEW: Animation frames
        anim_frames = max(1, int(self.anim_duration * self.fps))

        # Open Stockfish if eval is requested
        uci_engine = None
        if self.eval_during_export and self.stockfish_path:
            try:
                uci_engine = _SyncUCI(self.stockfish_path)
            except Exception as e:
                logger.warning("Cannot open Stockfish for eval: %s", e)

        vr = VideoRenderer(self.board_renderer, w, h, self.video_bg_color)
        vr.white_name = self.white_name
        vr.black_name = self.black_name
        vr.overlays = list(self.overlays)
        vr.move_list_text = [n.san() for n in ml]
        # NEW: Opening name from PGN headers
        vr.opening_name = self.game.headers.get("Opening", "")

        written = 0
        start_time = time.time()

        # Starting position
        start_board = self.game.board()
        self.board_renderer.board = start_board
        self.board_renderer.last_move = None
        self.board_renderer.anim_move = None
        self.board_renderer.anim_rook_move = None
        self.board_renderer.anim_progress = 1.0

        if uci_engine:
            _, ev = uci_engine.analyse(start_board.fen(), 14)
            # FIX: analyse already returns white-perspective score
            vr.eval_cp = float(ev)
        else:
            vr.eval_cp = self.eval_cache.get(None, 0.0)
        vr.current_move_index = -1
        vr.game_state = GAME_NORMAL
        # NEW: Captured pieces
        vr.captured_by_white, vr.captured_by_black = VideoRenderer.compute_captures(start_board)

        # Hold on starting position
        for _ in range(hf):
            if self._c:
                writer.release()
                try:
                    os.remove(used_path)
                except OSError:
                    pass
                self.export_finished.emit("Cancelled")
                return
            if self._write_frame(writer, vr, w, h):
                written += 1

        # Render each move
        for i, node in enumerate(ml):
            if self._c:
                writer.release()
                try:
                    os.remove(used_path)
                except OSError:
                    pass
                self.export_finished.emit("Cancelled")
                return

            move = node.move
            board = node.board()

            # ── NEW: Animation frames ──────────────────────────────
            # Use post-move board with anim_move for interpolation
            self.board_renderer.board = board
            self.board_renderer.last_move = None  # hide last-move highlight during animation
            self.board_renderer.anim_move = move
            rook_move = _get_castling_rook_move(move)
            self.board_renderer.anim_rook_move = rook_move

            # Eval for this position
            if uci_engine:
                _, ev = uci_engine.analyse(board.fen(), 14)
                # FIX: analyse already returns white-perspective score
                vr.eval_cp = float(ev)
            else:
                vr.eval_cp = self.eval_cache.get(node, 0.0)

            vr.current_move_index = i
            vr.captured_by_white, vr.captured_by_black = VideoRenderer.compute_captures(board)

            # Animate from progress 0 → 1
            for f_idx in range(anim_frames):
                if self._c:
                    writer.release()
                    try:
                        os.remove(used_path)
                    except OSError:
                        pass
                    self.export_finished.emit("Cancelled")
                    return
                progress = (f_idx + 1) / anim_frames
                # IMPROVED: Ease-in-out curve for smoother animation
                progress = 0.5 - 0.5 * math.cos(math.pi * progress)
                self.board_renderer.anim_progress = progress
                if self._write_frame(writer, vr, w, h):
                    written += 1

            # ── Hold on final position ─────────────────────────────
            self.board_renderer.anim_move = None
            self.board_renderer.anim_rook_move = None
            self.board_renderer.anim_progress = 1.0
            self.board_renderer.last_move = move

            state, result, detail = _detect_game_state(board)
            vr.game_state = state
            vr.game_result = result
            vr.game_detail = detail

            if node.parent:
                pb = node.parent.board()
                vr.move_text = (
                    f"{pb.fullmove_number}. {node.san()}"
                    if pb.turn == chess.WHITE
                    else f"{pb.fullmove_number}... {node.san()}"
                )

            extra = hf * 3 if state != GAME_NORMAL else 0
            total_hold = hf + extra
            for _ in range(total_hold):
                if self._c:
                    writer.release()
                    try:
                        os.remove(used_path)
                    except OSError:
                        pass
                    self.export_finished.emit("Cancelled")
                    return
                if self._write_frame(writer, vr, w, h):
                    written += 1

            # IMPROVED: Progress with ETA
            elapsed = time.time() - start_time
            pct = int((i + 1) / len(ml) * 100)
            if i > 0:
                eta = elapsed / (i + 1) * (len(ml) - i - 1)
                eta_str = f"ETA: {int(eta)}s" if eta < 60 else f"ETA: {int(eta/60)}m{int(eta%60)}s"
            else:
                eta_str = ""
            self.progress.emit(
                pct,
                f"Move {i + 1}/{len(ml)} — {written} frames — {eta_str}",
            )

        if uci_engine:
            try:
                uci_engine.close()
            except Exception:
                pass

        writer.release()
        elapsed = time.time() - start_time
        self.export_finished.emit(
            f"Done!\nCodec: {used_codec}\n"
            f"Saved: {used_path}\n"
            f"{w}x{h} @ {self.fps}fps\n"
            f"Frames: {written}\n"
            f"Duration: {elapsed:.1f}s"
        )


class BatchPGNExportWorker(QThread):
    """Batch render entire folders of PGN to MP4."""

    batch_progress = Signal(int, int, str)
    game_exported = Signal(str)
    batch_finished = Signal(int, int)

    def __init__(self, pgn_files, output_dir, settings):
        super().__init__()
        self.pgn_files = pgn_files
        self.output_dir = output_dir
        self.settings = settings
        self._c = False

    def cancel(self):
        self._c = True

    def run(self):
        if not HAS_CV2:
            self.batch_finished.emit(0, 0)
            return

        # Count total games
        total_games = 0
        for pgn_file in self.pgn_files:
            try:
                with open(pgn_file, "r", encoding="utf-8", errors="ignore") as f:
                    while chess.pgn.read_game(f) is not None:
                        total_games += 1
            except Exception:
                pass

        if total_games == 0:
            self.batch_finished.emit(0, 0)
            return

        success = 0
        fail = 0
        current_game = 0
        os.makedirs(self.output_dir, exist_ok=True)

        for pgn_file in self.pgn_files:
            if self._c:
                break
            basename = os.path.splitext(os.path.basename(pgn_file))[0]

            try:
                with open(pgn_file, "r", encoding="utf-8", errors="ignore") as f:
                    game_idx = 0
                    while not self._c:
                        game = chess.pgn.read_game(f)
                        if game is None:
                            break

                        game_idx += 1
                        current_game += 1
                        output_path = os.path.join(
                            self.output_dir,
                            f"{basename}_game_{game_idx}.mp4",
                        )
                        self.batch_progress.emit(
                            current_game, total_games, os.path.basename(pgn_file)
                        )

                        if self._export_game(game, output_path):
                            success += 1
                            self.game_exported.emit(output_path)
                        else:
                            fail += 1
            except Exception as e:
                logger.error("Batch PGN error reading %s: %s", pgn_file, e)

        self.batch_finished.emit(success, fail)

    def _export_game(self, game, output_path):
        ml = list(game.mainline())
        if not ml:
            return False

        s = self.settings
        res = RESOLUTION_SIZES.get(s.get("res_str", "1920×1080"), (1920, 1080))
        w, h = res
        fps = s.get("fps", 30)
        hold = s.get("hold", 1.5)
        hf = max(1, int(hold * fps))
        anim_duration = s.get("anim_duration", DEFAULT_ANIM_DURATION)  # NEW
        anim_frames = max(1, int(anim_duration * fps))  # NEW

        writer, used_path, used_codec = _create_video_writer(output_path, fps, w, h)
        if not writer:
            return False

        br = BoardRenderer(theme=s.get("theme"), flipped=s.get("flipped", False))
        vr = VideoRenderer(br, w, h, s.get("bg_color", QColor(30, 30, 32)))
        vr.white_name = s.get("white_name", "White")
        vr.black_name = s.get("black_name", "Black")
        vr.overlays = s.get("overlays", [])
        vr.move_list_text = [n.san() for n in ml]
        vr.opening_name = game.headers.get("Opening", "")  # NEW

        uci_engine = None
        if s.get("eval_during", False) and s.get("stockfish_path"):
            try:
                uci_engine = _SyncUCI(s["stockfish_path"])
            except Exception:
                pass

        written = 0
        try:
            start_board = game.board()
            br.board = start_board
            br.last_move = None
            br.anim_move = None
            br.anim_rook_move = None
            br.anim_progress = 1.0

            if uci_engine:
                _, ev = uci_engine.analyse(start_board.fen(), 14)
                # FIX: already white-perspective
                vr.eval_cp = float(ev)
            else:
                vr.eval_cp = 0.0

            vr.current_move_index = -1
            vr.game_state = GAME_NORMAL
            vr.captured_by_white, vr.captured_by_black = VideoRenderer.compute_captures(start_board)

            # Starting position hold
            for _ in range(hf):
                if self._c:
                    return False
                bgr = _qimage_to_bgr_numpy(vr.render())
                if bgr is not None:
                    if bgr.shape[:2] != (h, w):
                        bgr = cv2.resize(bgr, (w, h))
                    writer.write(bgr)
                    written += 1

            # Each move
            for i, node in enumerate(ml):
                if self._c:
                    return False

                move = node.move
                board = node.board()
                br.board = board
                br.last_move = None  # hide during animation

                # NEW: Animation frames
                br.anim_move = move
                br.anim_rook_move = _get_castling_rook_move(move)
                for f_idx in range(anim_frames):
                    if self._c:
                        return False
                    progress = (f_idx + 1) / anim_frames
                    progress = 0.5 - 0.5 * math.cos(math.pi * progress)
                    br.anim_progress = progress
                    bgr = _qimage_to_bgr_numpy(vr.render())
                    if bgr is not None:
                        if bgr.shape[:2] != (h, w):
                            bgr = cv2.resize(bgr, (w, h))
                        writer.write(bgr)
                        written += 1

                # Static hold
                br.anim_move = None
                br.anim_rook_move = None
                br.anim_progress = 1.0
                br.last_move = move

                if uci_engine:
                    _, ev = uci_engine.analyse(board.fen(), 14)
                    vr.eval_cp = float(ev)
                else:
                    vr.eval_cp = 0.0

                state, result, detail = _detect_game_state(board)
                vr.game_state = state
                vr.game_result = result
                vr.game_detail = detail
                vr.current_move_index = i
                vr.captured_by_white, vr.captured_by_black = VideoRenderer.compute_captures(board)

                if node.parent:
                    pb = node.parent.board()
                    vr.move_text = (
                        f"{pb.fullmove_number}. {node.san()}"
                        if pb.turn == chess.WHITE
                        else f"{pb.fullmove_number}... {node.san()}"
                    )

                extra = hf * 3 if state != GAME_NORMAL else 0
                for _ in range(hf + extra):
                    if self._c:
                        return False
                    bgr = _qimage_to_bgr_numpy(vr.render())
                    if bgr is not None:
                        if bgr.shape[:2] != (h, w):
                            bgr = cv2.resize(bgr, (w, h))
                        writer.write(bgr)
                        written += 1

            return written > 0

        except Exception as e:
            logger.error("Batch game export error: %s", e)
            return False

        finally:
            writer.release()
            if uci_engine:
                try:
                    uci_engine.close()
                except Exception:
                    pass


# ════════════════════════════════════════════════════════════════════
#  Board Preview Widget (for the GUI)
# ════════════════════════════════════════════════════════════════════

class BoardPreviewWidget(QWidget):
    """Displays a chess board in the GUI using BoardRenderer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._renderer = BoardRenderer()
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # NEW: Accept focus for keyboard events
        self.setFocusPolicy(Qt.StrongFocus)

    def set_board(self, board, last_move=None):
        self._renderer.board = board
        self._renderer.last_move = last_move
        self._renderer.anim_move = None
        self._renderer.anim_rook_move = None
        self._renderer.anim_progress = 1.0
        self.update()

    def set_theme(self, theme):
        self._renderer.theme = theme
        self.update()

    def set_flipped(self, f):
        self._renderer.flipped = f
        self.update()

    @property
    def flipped(self):
        return self._renderer.flipped

    @property
    def renderer(self):
        return self._renderer

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        t = min(self.width(), self.height())
        m = t * 0.05
        sz = (t - 2 * m) / 8
        self._renderer._paint(p, t, m, sz)
        p.end()


# ════════════════════════════════════════════════════════════════════
#  Stylesheet
# ════════════════════════════════════════════════════════════════════

PGN_STYLE = """
QMainWindow, QWidget {
    background-color: #1e1e22;
    color: #ddd;
    font-family: "Segoe UI", Arial, sans-serif;
}
QGroupBox {
    border: 1px solid #3a3a40;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    color: #ccc;
    font-size: 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}
QPushButton {
    background: #2a2a30;
    color: #ddd;
    border: 1px solid #3a3a40;
    border-radius: 5px;
    padding: 6px 14px;
    font-size: 12px;
}
QPushButton:hover {
    background: #3a3a42;
    border-color: #555;
}
QPushButton:pressed {
    background: #4a4a55;
}
QPushButton:disabled {
    background: #222;
    color: #666;
    border-color: #333;
}
QLineEdit, QTextEdit {
    background: #26262c;
    color: #ddd;
    border: 1px solid #3a3a40;
    border-radius: 4px;
    padding: 5px;
    selection-background-color: #4a6fa5;
}
QLineEdit:focus, QTextEdit:focus {
    border-color: #5a8aba;
}
QComboBox {
    background: #2a2a30;
    color: #ddd;
    border: 1px solid #3a3a40;
    border-radius: 4px;
    padding: 5px 8px;
}
QComboBox:hover {
    border-color: #555;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background: #2a2a30;
    color: #ddd;
    selection-background-color: #4a6fa5;
    border: 1px solid #3a3a40;
}
QSpinBox, QDoubleSpinBox {
    background: #26262c;
    color: #ddd;
    border: 1px solid #3a3a40;
    border-radius: 4px;
    padding: 4px;
}
QTabWidget::pane {
    border: 1px solid #3a3a40;
    border-radius: 4px;
    top: -1px;
}
QTabBar::tab {
    background: #2a2a30;
    color: #aaa;
    padding: 8px 18px;
    border: 1px solid #3a3a40;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    font-size: 12px;
}
QTabBar::tab:selected {
    background: #1e1e22;
    color: #fff;
    border-bottom: 2px solid #4a8aba;
}
QTabBar::tab:hover:!selected {
    background: #333340;
}
QLabel {
    color: #ccc;
    font-size: 12px;
}
QCheckBox {
    color: #ccc;
    spacing: 6px;
    font-size: 12px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid #555;
    background: #26262c;
}
QCheckBox::indicator:checked {
    background: #4a8aba;
    border-color: #5a9aca;
}
QProgressBar {
    border: 1px solid #3a3a40;
    border-radius: 4px;
    background: #1e1e22;
    text-align: center;
    color: #ddd;
    font-size: 11px;
    min-height: 22px;
}
QProgressBar::chunk {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #2a6a8a, stop:1 #3a9aba
    );
    border-radius: 3px;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: #1e1e22;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #3a3a40;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QTableWidget {
    background-color: #1e1e22;
    color: #ddd;
    border: none;
    gridline-color: #2a2a30;
    font-size: 12px;
}
QTableWidget::item {
    padding: 4px;
    border-bottom: 1px solid #2a2a30;
}
QTableWidget::item:selected {
    background-color: #4a6fa5;
    color: white;
}
QHeaderView::section {
    background-color: #2a2a30;
    color: #aaa;
    padding: 5px;
    border: 1px solid #3a3a40;
    font-weight: bold;
    font-size: 11px;
}
QSplitter::handle {
    background-color: #3a3a40;
}
"""


# ════════════════════════════════════════════════════════════════════
#  Main Window
# ════════════════════════════════════════════════════════════════════

class PGNtoMP4Window(QMainWindow):
    """Main application window for PGN → MP4 conversion."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("📄 PGN → MP4 Converter")
        self.setMinimumSize(1100, 700)
        self.resize(1300, 820)

        # State
        self.game = None
        self.move_list = []
        self.eval_cache = {}
        self.video_bg_color = QColor(30, 30, 32)
        self._worker = None
        self._batch_worker = None
        self._current_move_idx = -1
        self._all_games = []  # NEW: store all games from PGN

        # Build UI
        self._build_ui()
        self.setStyleSheet(PGN_STYLE)

        # NEW: Accept drag & drop
        self.setAcceptDrops(True)

        # NEW: Keyboard shortcuts
        QShortcut(QKeySequence(Qt.Key_Left), self, self._go_prev)
        QShortcut(QKeySequence(Qt.Key_Right), self, self._go_next)
        QShortcut(QKeySequence(Qt.Key_Home), self, self._go_first)
        QShortcut(QKeySequence(Qt.Key_End), self, self._go_last)

        # Auto-detect Stockfish
        sf = find_stockfish()
        if sf:
            self.engine_path_edit.setText(sf)

    # ════════════════════════════════════════════════════════════════
    #  UI Construction
    # ════════════════════════════════════════════════════════════════

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # ── Left: board preview ────────────────────────────────────
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.board_preview = BoardPreviewWidget()
        left_layout.addWidget(self.board_preview, stretch=1)

        # Game info
        info_row = QHBoxLayout()
        self.game_info_lbl = QLabel("No game loaded")
        self.game_info_lbl.setStyleSheet(
            "color:#999;font-size:12px;font-weight:bold;"
        )
        info_row.addWidget(self.game_info_lbl)
        info_row.addStretch()

        # NEW: Opening label
        self.opening_lbl = QLabel("")
        self.opening_lbl.setStyleSheet("color:#7aa;font-size:11px;")
        info_row.addWidget(self.opening_lbl)

        left_layout.addLayout(info_row)

        # Move navigation
        nav_row = QHBoxLayout()
        nav_btns = [
            ("⏮", self._go_first),
            ("◀", self._go_prev),
            ("▶", self._go_next),
            ("⏭", self._go_last),
        ]
        for text, fn in nav_btns:
            btn = QPushButton(text)
            btn.setFixedSize(44, 34)
            btn.clicked.connect(fn)
            nav_row.addWidget(btn)
        self.move_pos_lbl = QLabel("0 / 0")
        self.move_pos_lbl.setStyleSheet("color:#9cf;font-size:11px;")
        self.move_pos_lbl.setAlignment(Qt.AlignCenter)
        nav_row.addWidget(self.move_pos_lbl)
        left_layout.addLayout(nav_row)

        # Move table
        self.move_table = QTableWidget()
        self.move_table.setColumnCount(3)
        self.move_table.setHorizontalHeaderLabels(["#", "White", "Black"])
        self.move_table.horizontalHeader().setStretchLastSection(True)
        self.move_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.move_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.move_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        self.move_table.verticalHeader().setVisible(False)
        self.move_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.move_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.move_table.setShowGrid(False)
        self.move_table.setMaximumHeight(180)
        self.move_table.currentCellChanged.connect(self._on_move_cell)
        left_layout.addWidget(self.move_table)

        main_layout.addLayout(left_layout, stretch=2)

        # ── Right: tabs ────────────────────────────────────────────
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()

        # ── Tab 1: PGN Input ───────────────────────────────────────
        input_tab = QWidget()
        input_layout = QVBoxLayout(input_tab)

        # File open
        file_grp = QGroupBox("PGN File")
        file_lay = QHBoxLayout(file_grp)
        self.pgn_path_edit = QLineEdit()
        self.pgn_path_edit.setPlaceholderText("Select a .pgn file…")
        file_lay.addWidget(self.pgn_path_edit, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._load_pgn_file)
        file_lay.addWidget(browse_btn)
        input_layout.addWidget(file_grp)

        # NEW: Paste PGN
        paste_grp = QGroupBox("Or Paste PGN Text")
        paste_lay = QVBoxLayout(paste_grp)
        self.pgn_text_edit = QTextEdit()
        self.pgn_text_edit.setMaximumHeight(100)
        self.pgn_text_edit.setPlaceholderText("Paste PGN text here…")
        paste_lay.addWidget(self.pgn_text_edit)
        paste_btn = QPushButton("📋 Load Pasted PGN")
        paste_btn.clicked.connect(self._paste_pgn)
        paste_lay.addWidget(paste_btn)
        input_layout.addWidget(paste_grp)

        # NEW: Game selector for multi-game PGN
        game_grp = QGroupBox("Game Selection")
        game_lay = QHBoxLayout(game_grp)
        game_lay.addWidget(QLabel("Game:"))
        self.game_select_combo = QComboBox()
        self.game_select_combo.setMinimumWidth(200)
        self.game_select_combo.currentIndexChanged.connect(self._on_game_selected)
        game_lay.addWidget(self.game_select_combo, stretch=1)
        input_layout.addWidget(game_grp)

        # Player names
        names_grp = QGroupBox("Player Names (overrides)")
        names_lay = QFormLayout(names_grp)
        self.white_name_edit = QLineEdit()
        self.white_name_edit.setPlaceholderText("Auto from PGN")
        names_lay.addRow("White:", self.white_name_edit)
        self.black_name_edit = QLineEdit()
        self.black_name_edit.setPlaceholderText("Auto from PGN")
        names_lay.addRow("Black:", self.black_name_edit)
        input_layout.addWidget(names_grp)

        input_layout.addStretch()
        tabs.addTab(input_tab, "📂 Input")

        # ── Tab 2: Export Settings ─────────────────────────────────
        export_tab = QWidget()
        export_layout = QVBoxLayout(export_tab)

        # Video settings
        vid_grp = QGroupBox("Video Settings")
        vid_form = QFormLayout(vid_grp)
        self.res_combo = QComboBox()
        self.res_combo.addItems(RESOLUTION_LIST)
        vid_form.addRow("Resolution:", self.res_combo)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(10, 120)
        self.fps_spin.setValue(30)
        vid_form.addRow("FPS:", self.fps_spin)
        self.hold_spin = QDoubleSpinBox()
        self.hold_spin.setRange(0.3, 30.0)
        self.hold_spin.setValue(1.5)
        self.hold_spin.setSingleStep(0.5)
        self.hold_spin.setSuffix(" s")
        vid_form.addRow("Hold per move:", self.hold_spin)
        # NEW: Animation duration
        self.anim_spin = QDoubleSpinBox()
        self.anim_spin.setRange(0.0, 3.0)
        self.anim_spin.setValue(DEFAULT_ANIM_DURATION)
        self.anim_spin.setSingleStep(0.1)
        self.anim_spin.setSuffix(" s")
        vid_form.addRow("Move animation:", self.anim_spin)
        export_layout.addWidget(vid_grp)

        # Output
        out_grp = QGroupBox("Output")
        out_lay = QHBoxLayout(out_grp)
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Output video path…")
        self.output_path_edit.setText("chess_video.mp4")
        out_lay.addWidget(self.output_path_edit, stretch=1)
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self._browse_output)
        out_lay.addWidget(out_browse)
        export_layout.addWidget(out_grp)

        # Export buttons
        btn_row = QHBoxLayout()
        self.export_btn = QPushButton("🎬 Export Video")
        self.export_btn.setStyleSheet(
            "QPushButton{background:#2a6a3a;color:#fff;font-weight:bold;padding:10px 20px;}"
            "QPushButton:hover{background:#3a8a4a;}"
            "QPushButton:disabled{background:#222;color:#666;}"
        )
        self.export_btn.clicked.connect(self._start_export)
        btn_row.addWidget(self.export_btn)
        self.cancel_btn = QPushButton("✖ Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_export)
        btn_row.addWidget(self.cancel_btn)
        export_layout.addLayout(btn_row)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        export_layout.addWidget(self.progress_bar)
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#aaa;font-size:11px;")
        self.status_lbl.setWordWrap(True)
        export_layout.addWidget(self.status_lbl)

        export_layout.addStretch()
        tabs.addTab(export_tab, "🎬 Export")

        # ── Tab 3: Batch Export ────────────────────────────────────
        batch_tab = QWidget()
        batch_layout = QVBoxLayout(batch_tab)

        bsrc_grp = QGroupBox("PGN Source Folder")
        bsrc_lay = QHBoxLayout(bsrc_grp)
        self.batch_src_edit = QLineEdit()
        self.batch_src_edit.setPlaceholderText("Folder with .pgn files…")
        bsrc_lay.addWidget(self.batch_src_edit, stretch=1)
        bsrc_browse = QPushButton("Browse…")
        bsrc_browse.clicked.connect(self._browse_batch_src)
        bsrc_lay.addWidget(bsrc_browse)
        batch_layout.addWidget(bsrc_grp)

        bdst_grp = QGroupBox("Output Folder")
        bdst_lay = QHBoxLayout(bdst_grp)
        self.batch_dst_edit = QLineEdit()
        self.batch_dst_edit.setPlaceholderText("Output folder…")
        bdst_lay.addWidget(self.batch_dst_edit, stretch=1)
        bdst_browse = QPushButton("Browse…")
        bdst_browse.clicked.connect(self._browse_batch_dst)
        bdst_lay.addWidget(bdst_browse)
        batch_layout.addWidget(bdst_grp)

        # Batch settings (simplified)
        bset_grp = QGroupBox("Batch Settings")
        bset_form = QFormLayout(bset_grp)
        self.batch_res_combo = QComboBox()
        self.batch_res_combo.addItems(RESOLUTION_LIST)
        bset_form.addRow("Resolution:", self.batch_res_combo)
        self.batch_fps_spin = QSpinBox()
        self.batch_fps_spin.setRange(10, 120)
        self.batch_fps_spin.setValue(30)
        bset_form.addRow("FPS:", self.batch_fps_spin)
        self.batch_hold_spin = QDoubleSpinBox()
        self.batch_hold_spin.setRange(0.3, 30.0)
        self.batch_hold_spin.setValue(1.5)
        self.batch_hold_spin.setSingleStep(0.5)
        self.batch_hold_spin.setSuffix(" s")
        bset_form.addRow("Hold per move:", self.batch_hold_spin)
        batch_layout.addWidget(bset_grp)

        # Batch eval
        beval_grp = QGroupBox("Engine Eval (Batch)")
        beval_lay = QFormLayout(beval_grp)
        self.batch_eval_chk = QCheckBox("Run Stockfish during batch export")
        beval_lay.addRow(self.batch_eval_chk)
        batch_layout.addWidget(beval_grp)

        # Batch buttons
        bbtn_row = QHBoxLayout()
        self.batch_start_btn = QPushButton("🚀 Start Batch")
        self.batch_start_btn.setStyleSheet(
            "QPushButton{background:#2a6a3a;color:#fff;font-weight:bold;padding:10px 20px;}"
            "QPushButton:hover{background:#3a8a4a;}"
            "QPushButton:disabled{background:#222;color:#666;}"
        )
        self.batch_start_btn.clicked.connect(self._start_batch)
        bbtn_row.addWidget(self.batch_start_btn)
        self.batch_cancel_btn = QPushButton("✖ Cancel Batch")
        self.batch_cancel_btn.setEnabled(False)
        self.batch_cancel_btn.clicked.connect(self._cancel_batch)
        bbtn_row.addWidget(self.batch_cancel_btn)
        batch_layout.addLayout(bbtn_row)

        self.batch_progress_lbl = QLabel("")
        self.batch_progress_lbl.setStyleSheet("color:#aaa;font-size:11px;")
        batch_layout.addWidget(self.batch_progress_lbl)

        batch_layout.addStretch()
        tabs.addTab(batch_tab, "📦 Batch")

        # ── Tab 4: Theme & Engine ──────────────────────────────────
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)

        # Board theme
        theme_grp = QGroupBox("Board Theme")
        theme_lay = QFormLayout(theme_grp)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES.keys())
        self.theme_combo.currentTextChanged.connect(self._set_theme)
        theme_lay.addRow("Theme:", self.theme_combo)
        self.flip_chk = QCheckBox("Flip board")
        self.flip_chk.toggled.connect(self._toggle_flip)
        theme_lay.addRow(self.flip_chk)
        settings_layout.addWidget(theme_grp)

        # Engine
        engine_grp = QGroupBox("Stockfish Engine")
        engine_lay = QFormLayout(engine_grp)
        self.engine_path_edit = QLineEdit()
        self.engine_path_edit.setPlaceholderText("Path to Stockfish…")
        engine_lay.addRow("Path:", self.engine_path_edit)
        engine_browse = QPushButton("Browse…")
        engine_browse.clicked.connect(self._browse_engine)
        engine_lay.addRow("", engine_browse)
        self.eval_export_chk = QCheckBox("Run eval during export")
        self.eval_export_chk.setChecked(False)
        engine_lay.addRow(self.eval_export_chk)
        self.eval_depth_spin = QSpinBox()
        self.eval_depth_spin.setRange(10, 30)
        self.eval_depth_spin.setValue(18)
        engine_lay.addRow("Eval depth:", self.eval_depth_spin)
        self.eval_preview_btn = QPushButton("🔍 Analyze Current Game")
        self.eval_preview_btn.clicked.connect(self._analyze_game)
        engine_lay.addRow(self.eval_preview_btn)
        settings_layout.addWidget(engine_grp)

        # NEW: FEN copy
        fen_grp = QGroupBox("FEN")
        fen_lay = QHBoxLayout(fen_grp)
        self.fen_lbl = QLabel("—")
        self.fen_lbl.setStyleSheet("color:#9cf;font-size:11px;")
        self.fen_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fen_lay.addWidget(self.fen_lbl, stretch=1)
        copy_fen_btn = QPushButton("📋 Copy")
        copy_fen_btn.clicked.connect(self._copy_fen)
        fen_lay.addWidget(copy_fen_btn)
        settings_layout.addWidget(fen_grp)

        settings_layout.addStretch()
        tabs.addTab(settings_tab, "⚙ Settings")

        right_layout.addWidget(tabs)
        main_layout.addWidget(right_widget, stretch=3)

    # ════════════════════════════════════════════════════════════════
    #  PGN Loading
    # ════════════════════════════════════════════════════════════════

    def _load_pgn_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PGN File", "", "PGN Files (*.pgn);;All Files (*)"
        )
        if path:
            self.pgn_path_edit.setText(path)
            self._load_pgn_from_path(path)

    def _paste_pgn(self):
        """NEW: Load PGN from the text edit."""
        text = self.pgn_text_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "No PGN", "Paste PGN text first.")
            return
        self._load_pgn_from_text(text)

    def _load_pgn_from_path(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            self._load_pgn_from_text(text)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read PGN:\n{e}")

    def _load_pgn_from_text(self, text):
        """Parse PGN text and populate game selector."""
        self._all_games = []
        try:
            pgn_io = io.StringIO(text)
            while True:
                game = chess.pgn.read_game(pgn_io)
                if game is None:
                    break
                self._all_games.append(game)
        except Exception as e:
            QMessageBox.critical(self, "PGN Parse Error", str(e))
            return

        if not self._all_games:
            QMessageBox.warning(self, "No Games", "No valid games found in PGN.")
            return

        # Populate game selector
        self.game_select_combo.blockSignals(True)
        self.game_select_combo.clear()
        for i, g in enumerate(self._all_games):
            white = g.headers.get("White", "?")
            black = g.headers.get("Black", "?")
            date = g.headers.get("Date", "")
            label = f"{i+1}. {white} vs {black}"
            if date:
                label += f"  ({date})"
            self.game_select_combo.addItem(label)
        self.game_select_combo.blockSignals(False)

        # Load first game
        if self._all_games:
            self._load_game(self._all_games[0])

    def _on_game_selected(self, idx):
        if 0 <= idx < len(self._all_games):
            self._load_game(self._all_games[idx])

    def _load_game(self, game):
        """Load a game into the viewer."""
        self.game = game
        self.move_list = list(game.mainline())
        self.eval_cache = {}
        self._current_move_idx = -1

        # Update game info
        white = game.headers.get("White", "White")
        black = game.headers.get("Black", "Black")
        result = game.headers.get("Result", "*")
        event = game.headers.get("Event", "")
        opening = game.headers.get("Opening", "")

        info_text = f"{white} vs {black}  {result}"
        if event:
            info_text += f"  —  {event}"
        self.game_info_lbl.setText(info_text)
        self.opening_lbl.setText(opening)

        # Update name overrides placeholder
        self.white_name_edit.setPlaceholderText(white)
        self.black_name_edit.setPlaceholderText(black)

        # Populate move table
        self.move_table.blockSignals(True)
        self.move_table.setRowCount(0)
        row = 0
        for i, node in enumerate(self.move_list):
            if i % 2 == 0:
                self.move_table.insertRow(row)
                self.move_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
                self.move_table.setItem(row, 1, QTableWidgetItem(node.san()))
            else:
                self.move_table.setItem(row, 2, QTableWidgetItem(node.san()))
                row += 1
        # Handle odd number of moves
        if len(self.move_list) % 2 == 1:
            self.move_table.setItem(row, 2, QTableWidgetItem(""))

        self.move_table.blockSignals(False)

        # Show starting position
        self._go_last()

    # ════════════════════════════════════════════════════════════════
    #  Navigation
    # ════════════════════════════════════════════════════════════════

    def _go_first(self):
        if not self.game:
            return
        self._current_move_idx = -1
        self._update_board_position()

    def _go_prev(self):
        if not self.game or self._current_move_idx < 0:
            return
        self._current_move_idx -= 1
        self._update_board_position()

    def _go_next(self):
        if not self.game or self._current_move_idx >= len(self.move_list) - 1:
            return
        self._current_move_idx += 1
        self._update_board_position()

    def _go_last(self):
        if not self.game:
            return
        self._current_move_idx = len(self.move_list) - 1
        self._update_board_position()

    def _on_move_cell(self, row, col, _prev_row, _prev_col):
        if not self.move_list:
            return
        idx = row * 2 + (1 if col == 2 else 0)
        if 0 <= idx < len(self.move_list):
            self._current_move_idx = idx
            self._update_board_position(scroll_to=False)

    def _update_board_position(self, scroll_to=True):
        if not self.game:
            return

        if self._current_move_idx < 0:
            board = self.game.board()
            last_move = None
        else:
            node = self.move_list[self._current_move_idx]
            board = node.board()
            last_move = node.move

        self.board_preview.set_board(board, last_move)

        # Update move position label
        total = len(self.move_list)
        current = self._current_move_idx + 1
        self.move_pos_lbl.setText(f"{current} / {total}")

        # NEW: Update FEN display
        self.fen_lbl.setText(board.fen())

        # IMPROVED: Highlight current move in table
        self.move_table.blockSignals(True)
        self.move_table.clearSelection()
        if 0 <= self._current_move_idx < total:
            row = self._current_move_idx // 2
            col = 1 if self._current_move_idx % 2 == 0 else 2
            if row < self.move_table.rowCount():
                item = self.move_table.item(row, col)
                if item:
                    self.move_table.setCurrentItem(item)
                    if scroll_to:
                        self.move_table.scrollToItem(item)
        self.move_table.blockSignals(False)

    # ════════════════════════════════════════════════════════════════
    #  Theme & Settings
    # ════════════════════════════════════════════════════════════════

    def _set_theme(self, name):
        theme = THEMES.get(name, BoardTheme())
        self.board_preview.set_theme(theme)

    def _toggle_flip(self, checked):
        self.board_preview.set_flipped(checked)

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Video", "chess_video.mp4",
            "MP4 Files (*.mp4);;AVI Files (*.avi);;All Files (*)"
        )
        if path:
            self.output_path_edit.setText(path)

    def _browse_engine(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Stockfish", "",
            "Executables (*);;All Files (*)"
        )
        if path:
            self.engine_path_edit.setText(path)

    def _copy_fen(self):
        """NEW: Copy current FEN to clipboard."""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.fen_lbl.text())

    # ════════════════════════════════════════════════════════════════
    #  Export
    # ════════════════════════════════════════════════════════════════

    def _start_export(self):
        if not HAS_CV2:
            QMessageBox.critical(
                self, "Missing Dependency",
                "opencv-python is required.\nRun: pip install opencv-python numpy"
            )
            return
        if not self.game or not self.move_list:
            QMessageBox.warning(self, "No Game", "Load a PGN game first.")
            return
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "Busy", "Export already in progress.")
            return

        theme = THEMES.get(self.theme_combo.currentText(), BoardTheme())
        br = BoardRenderer(theme=theme, flipped=self.flip_chk.isChecked())

        white_name = self.white_name_edit.text().strip() or self.game.headers.get("White", "White")
        black_name = self.black_name_edit.text().strip() or self.game.headers.get("Black", "Black")

        self._worker = StreamingExportWorker(
            game=self.game,
            move_list=self.move_list,
            eval_cache=self.eval_cache,
            board_renderer=br,
            video_bg_color=self.video_bg_color,
            white_name=white_name,
            black_name=black_name,
            overlays=[],
            fps=self.fps_spin.value(),
            hold=self.hold_spin.value(),
            res_str=self.res_combo.currentText(),
            output_path=self.output_path_edit.text().strip() or "chess_video.mp4",
            stockfish_path=self.engine_path_edit.text().strip(),
            eval_during_export=self.eval_export_chk.isChecked(),
            anim_duration=self.anim_spin.value(),  # NEW
        )
        self._worker.progress.connect(self._on_export_progress)
        self._worker.export_finished.connect(self._on_export_finished)
        self._worker.start()

        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_lbl.setText("Exporting…")

    def _cancel_export(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self.status_lbl.setText("Cancelling…")

    def _on_export_progress(self, pct, msg):
        self.progress_bar.setValue(pct)
        self.status_lbl.setText(msg)

    def _on_export_finished(self, msg):
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(100 if not msg.startswith("ERROR") else 0)
        self.status_lbl.setText(msg)

        if msg.startswith("ERROR"):
            QMessageBox.critical(self, "Export Error", msg)
        elif not msg.startswith("Cancelled"):
            QMessageBox.information(self, "Export Complete", msg)

    # ════════════════════════════════════════════════════════════════
    #  Batch Export
    # ════════════════════════════════════════════════════════════════

    def _browse_batch_src(self):
        path = QFileDialog.getExistingDirectory(self, "Select PGN Source Folder")
        if path:
            self.batch_src_edit.setText(path)

    def _browse_batch_dst(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if path:
            self.batch_dst_edit.setText(path)

    def _start_batch(self):
        if not HAS_CV2:
            QMessageBox.critical(
                self, "Missing Dependency",
                "opencv-python is required.\nRun: pip install opencv-python numpy"
            )
            return

        src_dir = self.batch_src_edit.text().strip()
        dst_dir = self.batch_dst_edit.text().strip()
        if not src_dir or not os.path.isdir(src_dir):
            QMessageBox.warning(self, "Invalid Source", "Select a valid PGN source folder.")
            return
        if not dst_dir:
            QMessageBox.warning(self, "Invalid Output", "Select an output folder.")
            return

        pgn_files = sorted(glob.glob(os.path.join(src_dir, "*.pgn")))
        if not pgn_files:
            QMessageBox.warning(self, "No PGN Files", f"No .pgn files found in:\n{src_dir}")
            return

        theme = THEMES.get(self.theme_combo.currentText(), BoardTheme())
        settings = {
            "res_str": self.batch_res_combo.currentText(),
            "fps": self.batch_fps_spin.value(),
            "hold": self.batch_hold_spin.value(),
            "anim_duration": self.anim_spin.value(),  # NEW
            "theme": theme,
            "flipped": self.flip_chk.isChecked(),
            "bg_color": self.video_bg_color,
            "white_name": "White",
            "black_name": "Black",
            "overlays": [],
            "eval_during": self.batch_eval_chk.isChecked(),
            "stockfish_path": self.engine_path_edit.text().strip(),
        }

        self._batch_worker = BatchPGNExportWorker(pgn_files, dst_dir, settings)
        self._batch_worker.batch_progress.connect(self._on_batch_progress)
        self._batch_worker.game_exported.connect(self._on_batch_game_exported)
        self._batch_worker.batch_finished.connect(self._on_batch_finished)
        self._batch_worker.start()

        self.batch_start_btn.setEnabled(False)
        self.batch_cancel_btn.setEnabled(True)
        self.batch_progress_lbl.setText("Starting batch export…")

    def _cancel_batch(self):
        if self._batch_worker and self._batch_worker.isRunning():
            self._batch_worker.cancel()

    def _on_batch_progress(self, current, total, filename):
        self.batch_progress_lbl.setText(
            f"Processing game {current}/{total} — {filename}"
        )

    def _on_batch_game_exported(self, path):
        logger.info("Batch exported: %s", path)

    def _on_batch_finished(self, success, fail):
        self.batch_start_btn.setEnabled(True)
        self.batch_cancel_btn.setEnabled(False)
        msg = f"Batch complete: {success} succeeded, {fail} failed"
        self.batch_progress_lbl.setText(msg)
        QMessageBox.information(self, "Batch Complete", msg)

    # ════════════════════════════════════════════════════════════════
    #  Engine Analysis
    # ════════════════════════════════════════════════════════════════

    def _analyze_game(self):
        """Run Stockfish on the current game and populate eval cache."""
        sf_path = self.engine_path_edit.text().strip()
        if not sf_path or not os.path.isfile(sf_path):
            QMessageBox.warning(self, "No Engine", "Set a valid Stockfish path first.")
            return
        if not self.game or not self.move_list:
            QMessageBox.warning(self, "No Game", "Load a PGN game first.")
            return

        depth = self.eval_depth_spin.value()
        self.eval_preview_btn.setEnabled(False)
        self.eval_preview_btn.setText("⏳ Analyzing…")
        QApplication.processEvents()

        try:
            uci = _SyncUCI(sf_path)
        except Exception as e:
            QMessageBox.critical(self, "Engine Error", str(e))
            self.eval_preview_btn.setEnabled(True)
            self.eval_preview_btn.setText("🔍 Analyze Current Game")
            return

        self.eval_cache = {}
        try:
            # Starting position
            start_board = self.game.board()
            _, ev = uci.analyse(start_board.fen(), depth)
            self.eval_cache[None] = float(ev)

            for i, node in enumerate(self.move_list):
                board = node.board()
                _, ev = uci.analyse(board.fen(), depth)
                self.eval_cache[node] = float(ev)

                if i % 5 == 0:
                    self.status_lbl.setText(f"Analyzing move {i+1}/{len(self.move_list)}…")
                    QApplication.processEvents()

        except Exception as e:
            logger.error("Analysis error: %s", e)
        finally:
            try:
                uci.close()
            except Exception:
                pass

        self.eval_preview_btn.setEnabled(True)
        self.eval_preview_btn.setText("🔍 Analyze Current Game")
        self.status_lbl.setText(
            f"Analysis complete — {len(self.eval_cache)} positions evaluated"
        )

    # ════════════════════════════════════════════════════════════════
    #  Drag & Drop (NEW)
    # ════════════════════════════════════════════════════════════════

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pgn"):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pgn"):
                self.pgn_path_edit.setText(path)
                self._load_pgn_from_path(path)
                break

    # ════════════════════════════════════════════════════════════════
    #  Keyboard (NEW — shortcuts are registered in __init__)
    # ════════════════════════════════════════════════════════════════

    def keyPressEvent(self, event):
        """Additional keyboard handling."""
        if event.key() == Qt.Key_F:
            self._toggle_flip(not self.flip_chk.isChecked())
            self.flip_chk.setChecked(not self.flip_chk.isChecked())
        super().keyPressEvent(event)


# ════════════════════════════════════════════════════════════════════
#  Entry Point
# ════════════════════════════════════════════════════════════════════

def main():
    if not HAS_CV2:
        print("ERROR: opencv-python is required.")
        print("Install with: pip install opencv-python numpy")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("PGN → MP4 Converter")

    window = PGNtoMP4Window()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()