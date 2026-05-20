"""Chess Video Maker Pro — Chess Board Widget"""

import math
import chess
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (QPainter, QColor, QFont, QPen, QImage,
                            QPainterPath, QPolygonF)

from constants import PIECE_SYM, BoardTheme


class ChessBoardWidget(QWidget):
    """Custom Qt Widget for rendering and interacting with a Chess Board."""

    squareClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.board = chess.Board()
        self.theme = BoardTheme()
        self.flipped = False
        self.show_coords = True
        self.selected_sq = None
        self.legal_targets = []
        self.last_move = None
        self.highlighted = set()
        self.arrows = []
        self._arrow_start = self._arrow_end = None
        self._drawing_arrow = False
        self.anim_move = None
        self.anim_progress = 0.0
        self.policy_vis = {}
        self.setMinimumSize(400, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    def _layout(self):
        total = min(self.width(), self.height())
        margin = total * 0.05 if self.show_coords else 0
        sq = (total - 2 * margin) / 8
        return total, margin, sq

    def _sq_rect(self, sq, total, margin, sq_sz):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        col = (7 - f) if self.flipped else f
        row = r if self.flipped else (7 - r)
        return QRectF(margin + col * sq_sz, margin + row * sq_sz, sq_sz, sq_sz)

    def _pos_to_sq(self, pos, total, margin, sq_sz):
        col = int((pos.x() - margin) / sq_sz)
        row = int((pos.y() - margin) / sq_sz)
        if not (0 <= col < 8 and 0 <= row < 8):
            return None
        return chess.square(7 - col, row) if self.flipped else chess.square(col, 7 - row)

    def set_theme(self, t):
        self.theme = t
        self.update()

    def set_position(self, board, last_move=None):
        self.board = board
        self.last_move = last_move
        self.selected_sq = None
        self.legal_targets = []
        self.anim_move = None
        self.anim_progress = 0.0
        self.update()

    def mousePressEvent(self, e):
        total, margin, sq_sz = self._layout()
        sq = self._pos_to_sq(e.position().toPoint(), total, margin, sq_sz)
        if sq is None:
            return
        if e.button() == Qt.LeftButton:
            if e.modifiers() & Qt.ShiftModifier:
                self._arrow_start = sq
                self._drawing_arrow = True
                self._arrow_end = sq
            else:
                self.squareClicked.emit(sq)
        elif e.button() == Qt.RightButton:
            self.highlighted.symmetric_difference_update({sq})
            self.update()

    def mouseMoveEvent(self, e):
        if self._drawing_arrow:
            total, margin, sq_sz = self._layout()
            sq = self._pos_to_sq(e.position().toPoint(), total, margin, sq_sz)
            if sq is not None:
                self._arrow_end = sq
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drawing_arrow:
            total, margin, sq_sz = self._layout()
            sq = self._pos_to_sq(e.position().toPoint(), total, margin, sq_sz)
            if sq and self._arrow_start is not None and sq != self._arrow_start:
                self.arrows.append((self._arrow_start, sq, QColor(self.theme.arrow_clr)))
                self.update()
            self._drawing_arrow = False
            self._arrow_start = self._arrow_end = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        total, margin, sq = self._layout()
        p.fillRect(self.rect(), self.theme.bg)
        p.setPen(Qt.NoPen)
        p.setBrush(self.theme.border)
        p.drawRect(QRectF(0, 0, total, total))

        for s in chess.SQUARES:
            rect = self._sq_rect(s, total, margin, sq)
            f, r = chess.square_file(s), chess.square_rank(s)
            base = self.theme.light_sq if (f + r) % 2 == 0 else self.theme.dark_sq
            p.fillRect(rect, base)
            if self.last_move and s in (self.last_move.from_square, self.last_move.to_square):
                p.fillRect(rect, self.theme.last_move)
            if s == self.selected_sq:
                p.fillRect(rect, self.theme.highlight)
            if s in self.highlighted:
                p.fillRect(rect, QColor(0, 130, 255, 80))

        if self.show_coords:
            fnt = QFont("Arial", max(7, int(sq * 0.14)))
            fnt.setBold(True)
            p.setFont(fnt)
            p.setPen(self.theme.coord)
            for i in range(8):
                fl = chr(ord('h') - i if self.flipped else ord('a') + i)
                rn = str(i + 1 if self.flipped else 8 - i)
                x = margin + i * sq + sq / 2
                p.drawText(QRectF(x - sq / 2, total - margin, sq, margin), Qt.AlignCenter, fl)
                p.drawText(QRectF(0, margin + i * sq, margin, sq), Qt.AlignCenter, rn)

        for mv in self.legal_targets:
            rect = self._sq_rect(mv, total, margin, sq)
            p.setPen(Qt.NoPen)
            if self.board.piece_at(mv):
                p.setBrush(QColor(0, 0, 0, 60))
                p.drawEllipse(rect.adjusted(sq * 0.1, sq * 0.1, -sq * 0.1, -sq * 0.1))
            else:
                p.setBrush(QColor(0, 0, 0, 40))
                p.drawEllipse(rect.center(), sq * 0.15, sq * 0.15)

        if self.policy_vis:
            p.setPen(Qt.NoPen)
            for uci, prob in self.policy_vis.items():
                try:
                    move = chess.Move.from_uci(uci)
                    if move in self.board.legal_moves:
                        to_sq = move.to_square
                        rect = self._sq_rect(to_sq, total, margin, sq)
                        color = QColor.fromHsvF(0.33 * prob, 0.9, 0.9, 0.6 * prob + 0.1)
                        p.setBrush(color)
                        p.drawEllipse(rect.center(), sq * 0.4 * prob + sq * 0.1, sq * 0.4 * prob + sq * 0.1)
                except Exception:
                    pass

        for (fr, to, clr) in self.arrows:
            self._draw_arrow(p, fr, to, clr, margin, sq)
        if self._drawing_arrow and self._arrow_start and self._arrow_end:
            self._draw_arrow(p, self._arrow_start, self._arrow_end, QColor(self.theme.arrow_clr), margin, sq)

        for s in chess.SQUARES:
            pc = self.board.piece_at(s)
            if pc:
                if self.anim_move and s == self.anim_move.from_square:
                    continue
                self._draw_piece(p, pc, self._sq_rect(s, total, margin, sq), sq)

        if self.anim_move:
            pc = self.board.piece_at(self.anim_move.from_square)
            if pc:
                r_from = self._sq_rect(self.anim_move.from_square, total, margin, sq)
                r_to = self._sq_rect(self.anim_move.to_square, total, margin, sq)
                x = r_from.x() + (r_to.x() - r_from.x()) * self.anim_progress
                y = r_from.y() + (r_to.y() - r_from.y()) * self.anim_progress
                self._draw_piece(p, pc, QRectF(x, y, sq, sq), sq)
        p.end()

    def _draw_piece(self, p, piece, rect, sq_sz):
        sym = PIECE_SYM.get((piece.piece_type, piece.color), "?")
        fnt = QFont("Segoe UI Symbol", sq_sz * 0.72)
        fnt.setStyleStrategy(QFont.PreferAntialias)
        p.setFont(fnt)
        p.setPen(QPen(QColor(0, 0, 0, 180), max(1, sq_sz * 0.03)))
        if piece.color == chess.WHITE:
            p.drawText(rect, Qt.AlignCenter, sym)
            p.setPen(Qt.NoPen)
            p.drawText(rect.adjusted(0, -1, 0, -1), Qt.AlignCenter, sym)
        else:
            p.drawText(rect, Qt.AlignCenter, sym)

    def _draw_arrow(self, p, fr, to, color, margin, sq_sz):
        r1 = self._sq_rect(fr, margin, margin, sq_sz)
        r2 = self._sq_rect(to, margin, margin, sq_sz)
        c1, c2 = r1.center(), r2.center()
        dx, dy = c2.x() - c1.x(), c2.y() - c1.y()
        length = math.hypot(dx, dy)
        if length < 1:
            return
        ux, uy = dx / length, dy / length
        start = QPointF(c1.x() + ux * sq_sz * 0.35, c1.y() + uy * sq_sz * 0.35)
        end = QPointF(c2.x() - ux * sq_sz * 0.35, c2.y() - uy * sq_sz * 0.35)
        pw = sq_sz * 0.13
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.save()
        p.setOpacity(color.alphaF())
        shaft = QPainterPath()
        perp_x, perp_y = -uy, ux
        shaft.moveTo(start.x() + perp_x * pw / 2, start.y() + perp_y * pw / 2)
        shaft.lineTo(end.x() + perp_x * pw / 2, end.y() + perp_y * pw / 2)
        shaft.lineTo(end.x() - perp_x * pw / 2, end.y() - perp_y * pw / 2)
        shaft.lineTo(start.x() - perp_x * pw / 2, start.y() - perp_y * pw / 2)
        shaft.closeSubpath()
        p.drawPath(shaft)
        hw = pw * 2.0
        hl = pw * 1.8
        tip = QPointF(end.x() + ux * hl, end.y() + uy * hl)
        tri = QPolygonF([end, QPointF(end.x() + perp_x * hw / 2, end.y() + perp_y * hw / 2), tip,
                         QPointF(end.x() - perp_x * hw / 2, end.y() - perp_y * hw / 2)])
        p.drawPolygon(tri)
        p.restore()

    def render_to_image(self, size=1080):
        pixmap = self.grab()
        if not pixmap.isNull():
            return pixmap.toImage().scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        img = QImage(size, size, QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        self.render(p)
        p.end()
        return img