"""
Combined Qt widgets: BoardPreviewWidget, MoveListWidget, EvalBarWidget.
"""

import math
import chess
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QRectF, QPointF, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import (
    QPainter, QColor, QFont, QLinearGradient, QRadialGradient,
    QPainterPath, QPen,
)
from constants import (
    GAME_NORMAL, MQ_GOOD, MQ_COLORS, MQ_SYMBOLS, MQ_BG_COLORS,
)
from board_renderer import BoardRenderer
from movelist_renderer import render_movelist_2col


# ═══════════════════════════════════════════════════════════════
#  Move List Widget
# ═══════════════════════════════════════════════════════════════

class MoveListWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._moves: list[str] = []
        self._qualities: list[str] = []
        self._current: int = -1
        self.setMinimumWidth(280)
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def add_move(self, san, quality=MQ_GOOD):
        self._moves.append(san)
        self._qualities.append(quality)
        self._current = len(self._moves) - 1
        self.update()

    def set_moves(self, moves, qualities=None, current=-1):
        self._moves = list(moves)
        self._qualities = list(qualities) if qualities else [MQ_GOOD] * len(moves)
        self._current = current
        self.update()

    def set_current(self, idx):
        self._current = idx
        self.update()

    def clear(self):
        self._moves.clear()
        self._qualities.clear()
        self._current = -1
        self.update()

    @property
    def moves(self):
        return list(self._moves)

    @property
    def qualities(self):
        return list(self._qualities)

    @property
    def current_index(self):
        return self._current

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        render_movelist_2col(p, 0, 0, self.width(), self.height(),
                             self._moves, self._current, self._qualities)
        p.end()


# ═══════════════════════════════════════════════════════════════
#  Board Preview Widget
# ═══════════════════════════════════════════════════════════════

class BoardPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._renderer = BoardRenderer()
        self._anim_progress_val = 1.0
        self._active_anim = None
        self._anim_duration = 300
        self.setMinimumSize(360, 360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _get_ap(self):
        return self._anim_progress_val

    def _set_ap(self, v):
        self._anim_progress_val = v
        self._renderer.anim_progress = v
        self.update()

    animProgress = Property(float, _get_ap, _set_ap)

    @property
    def flipped(self):
        return self._renderer.flipped

    def set_board(self, board, last_move=None):
        self._renderer.board = board
        self._renderer.last_move = last_move
        self._renderer.anim_move = None
        self._renderer.anim_rook_move = None
        self._renderer.anim_progress = 1.0
        self._anim_progress_val = 1.0
        self.update()

    def set_theme(self, theme):
        self._renderer.theme = theme
        self.update()

    def set_flipped(self, f):
        self._renderer.flipped = f
        self.update()

    def set_anim_duration(self, ms):
        self._anim_duration = max(50, int(ms))

    def set_show_coords(self, show):
        self._renderer.show_coords = show
        self.update()

    def set_move_quality(self, q):
        self._renderer.move_quality = q
        self.update()

    def animate_move(self, move):
        self._renderer.anim_move = move
        self._renderer.anim_progress = 0.0
        self._anim_progress_val = 0.0
        rook_move = None
        pc = self._renderer.board.piece_at(move.to_square)
        if (pc and pc.piece_type == chess.KING and
                abs(chess.square_file(move.from_square) -
                    chess.square_file(move.to_square)) == 2):
            rank = chess.square_rank(move.from_square)
            if chess.square_file(move.to_square) > chess.square_file(move.from_square):
                rook_move = (chess.square(7, rank), chess.square(5, rank))
            else:
                rook_move = (chess.square(0, rank), chess.square(3, rank))
        self._renderer.anim_rook_move = rook_move

        # FIX: Stop previous animation to prevent reference leak
        if self._active_anim is not None:
            self._active_anim.stop()
            self._active_anim = None

        anim = QPropertyAnimation(self, b"animProgress")
        anim.setDuration(self._anim_duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutQuint)

        def cleanup():
            self._renderer.anim_move = None
            self._renderer.anim_rook_move = None
            self._renderer.anim_progress = 1.0
            self._anim_progress_val = 1.0
            self.update()

        anim.finished.connect(cleanup)
        anim.start()
        self._active_anim = anim

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        t = min(self.width(), self.height())
        m = t * 0.05 if self._renderer.show_coords else 0
        sz = (t - 2 * m) / 8
        self._renderer._paint(p, t, m, sz)
        p.end()


# ═══════════════════════════════════════════════════════════════
#  Eval Bar Widget
# ═══════════════════════════════════════════════════════════════

class EvalBarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._eval_cp = 0.0
        self._anim_cp = 0.0
        self._game_state = GAME_NORMAL
        self._game_result = ""
        self._game_detail = ""
        self.setFixedWidth(48 + 16)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumHeight(200)
        self._animation = QPropertyAnimation(self, b"anim_cp")
        self._animation.setDuration(450)
        self._animation.setEasingCurve(QEasingCurve.OutQuart)

    def set_game_state(self, state, result="", detail=""):
        self._game_state = state
        self._game_result = result
        self._game_detail = detail
        self.update()

    def reset_game_state(self):
        self._game_state = GAME_NORMAL
        self._game_result = ""
        self._game_detail = ""
        self.update()

    def _get_ac(self):
        return self._anim_cp

    def _set_ac(self, v):
        self._anim_cp = v
        self.update()

    anim_cp = Property(float, _get_ac, _set_ac)

    def set_eval(self, cp):
        old = self._eval_cp
        self._eval_cp = cp
        if self._game_state != GAME_NORMAL or abs(cp) > 9000 or abs(old) > 9000:
            self._anim_cp = float(cp)
            self.update()
            return
        self._animation.stop()
        self._animation.setStartValue(self._anim_cp)
        self._animation.setEndValue(float(cp))
        self._animation.start()

    @staticmethod
    def _cp2r(cp):
        if cp >= 9000: return 1.0
        if cp <= -9000: return 0.0
        return 1.0 / (1.0 + math.exp(-0.004 * max(-10000, min(10000, cp))))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        W, H = self.width(), self.height()
        pad, cr = 8, 6
        bx, by, bw, bh = pad, pad, W - 2 * pad, H - 2 * pad

        p.setPen(QPen(QColor(50, 50, 58), 1.0))
        p.setBrush(QColor(16, 16, 20))
        p.drawRoundedRect(QRectF(0, 0, W, H), cr + 2, cr + 2)

        blk = QLinearGradient(bx, by, bx, by + bh)
        blk.setColorAt(0.0, QColor(58, 58, 66))
        blk.setColorAt(0.5, QColor(44, 44, 52))
        blk.setColorAt(1.0, QColor(38, 38, 45))
        p.setPen(Qt.NoPen)
        p.setBrush(blk)
        p.drawRoundedRect(QRectF(bx, by, bw, bh), cr, cr)

        ratio = self._cp2r(self._anim_cp)
        wh = max(0, min(bh, int(bh * ratio)))
        if wh > 0:
            wt = by + bh - wh
            wg = QLinearGradient(bx, wt, bx, by + bh)
            wg.setColorAt(0.0, QColor(230, 226, 216))
            wg.setColorAt(0.4, QColor(238, 235, 226))
            wg.setColorAt(1.0, QColor(246, 243, 236))
            p.setBrush(wg)
            if wh >= bh:
                p.drawRoundedRect(QRectF(bx, by, bw, bh), cr, cr)
            elif wh < cr * 2:
                p.drawRoundedRect(QRectF(bx, wt, bw, wh), cr, cr)
            else:
                path = QPainterPath()
                path.moveTo(bx, wt)
                path.lineTo(bx + bw, wt)
                path.lineTo(bx + bw, by + bh - cr)
                path.quadTo(bx + bw, by + bh, bx + bw - cr, by + bh)
                path.lineTo(bx + cr, by + bh)
                path.quadTo(bx, by + bh, bx, by + bh - cr)
                path.lineTo(bx, wt)
                path.closeSubpath()
                p.drawPath(path)

        ig = QLinearGradient(bx, by, bx, by + bh)
        ig.setColorAt(0.0, QColor(0, 0, 0, 50))
        ig.setColorAt(0.1, QColor(0, 0, 0, 18))
        ig.setColorAt(0.5, QColor(255, 255, 255, 12))
        ig.setColorAt(0.9, QColor(0, 0, 0, 8))
        ig.setColorAt(1.0, QColor(0, 0, 0, 35))
        p.setBrush(ig)
        p.drawRoundedRect(QRectF(bx, by, bw, bh), cr, cr)

        bdy = by + bh - wh
        if 0 < wh < bh:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(105, 100, 90, 35))
            p.drawRect(QRectF(bx + 2, bdy - 2, bw - 4, 5))
            p.setPen(QPen(QColor(105, 100, 90, 150), 1.5))
            p.drawLine(QPointF(bx + 2, bdy), QPointF(bx + bw - 2, bdy))

        if self._game_state == GAME_NORMAL:
            is_mate = abs(self._eval_cp) > 9000
            txt = (f"M{int(abs(self._eval_cp) - 10000)}" if is_mate
                   else f"{self._eval_cp / 100.0:+.1f}")
            fnt = QFont("Inter", max(8, min(12, int(bw * 0.27))), QFont.Bold)
            p.setFont(fnt)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(txt) + 16
            pill_w, pill_h = max(tw, 32), 22
            ty = bdy if 0 < wh < bh else by + bh / 2
            ty = max(by + pill_h / 2 + 4, min(by + bh - pill_h / 2 - 4, ty))
            pill = QRectF((W - pill_w) / 2, ty - pill_h / 2, pill_w, pill_h)
            on_white = (ty >= by + bh - wh) if 0 < wh < bh else (self._eval_cp >= 0)
            if is_mate:
                pbg = QColor(28, 165, 55, 225) if self._eval_cp > 0 else QColor(205, 40, 40, 225)
                pfg = QColor(255, 255, 255)
            elif on_white:
                pbg, pfg = QColor(255, 255, 255, 210), QColor(32, 30, 26)
            else:
                pbg, pfg = QColor(20, 20, 28, 210), QColor(235, 232, 224)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 80))
            p.drawRoundedRect(pill.adjusted(1, 2, 1, 2), 11, 11)
            p.setBrush(pbg)
            p.drawRoundedRect(pill, 11, 11)
            p.setPen(QPen(QColor(255, 255, 255, 35), 0.8))
            p.drawRoundedRect(pill, 11, 11)
            p.setPen(pfg)
            p.drawText(pill, Qt.AlignCenter, txt)
        else:
            pill_w, pill_h = max(32, int(bw * 0.8)), 24
            pill_x = (W - pill_w) / 2
            if "1-0" in self._game_result:
                txt = "♔ 1-0"; pill_y = by + 15
                pbg, pfg = QColor(255, 255, 255, 225), QColor(28, 28, 28)
            elif "0-1" in self._game_result:
                txt = "♚ 0-1"; pill_y = by + bh - pill_h - 15
                pbg, pfg = QColor(28, 28, 28, 235), QColor(228, 228, 228)
            else:
                txt = "½-½"; pill_y = by + (bh - pill_h) / 2
                pbg, pfg = QColor(135, 125, 48, 235), QColor(255, 255, 255)
            pill = QRectF(pill_x, pill_y, pill_w, pill_h)
            p.setFont(QFont("Inter", max(8, min(11, int(bw * 0.25))), QFont.Bold))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 80))
            p.drawRoundedRect(pill.adjusted(1, 2, 1, 2), 11, 11)
            p.setBrush(pbg)
            p.drawRoundedRect(pill, 11, 11)
            p.setPen(pfg)
            p.drawText(pill, Qt.AlignCenter, txt)

        p.end()