"""Chess Video Maker Pro — Chess Board Widget"""
import math
import chess
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, Property
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QImage, QPainterPath, QPolygonF
from constants import PIECE_SYM, BoardTheme


class ChessBoardWidget(QWidget):
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
        self._arr_s = self._arr_e = None
        self._draw_arr = False
        self.anim_move = None
        self.anim_rook_move = None
        self._anim_progress_val = 1.0
        self._check_square = None
        self._check_opacity_val = 0.0
        self._flash_squares = ()
        self._flash_opacity_val = 0.0
        self.policy_vis = {}
        self.setMinimumSize(400, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    # ── Qt Properties ──────────────────────────────────────────────
    def _get_ap(self):
        return self._anim_progress_val

    def _set_ap(self, v):
        self._anim_progress_val = v
        self.update()

    animProgress = Property(float, _get_ap, _set_ap)

    def _get_co(self):
        return self._check_opacity_val

    def _set_co(self, v):
        self._check_opacity_val = v
        self.update()

    checkOpacity = Property(float, _get_co, _set_co)

    def _get_fo(self):
        return self._flash_opacity_val

    def _set_fo(self, v):
        self._flash_opacity_val = v
        self.update()

    flashOpacity = Property(float, _get_fo, _set_fo)

    # ── Layout helpers ─────────────────────────────────────────────
    def _layout(self):
        t = min(self.width(), self.height())
        m = t * 0.05 if self.show_coords else 0
        s = (t - 2 * m) / 8
        return t, m, s

    def _sq_rect(self, sq, t, m, sz):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        c = (7 - f) if self.flipped else f
        rw = r if self.flipped else (7 - r)
        return QRectF(m + c * sz, m + rw * sz, sz, sz)

    def _pos_to_sq(self, pos, t, m, sz):
        c = int((pos.x() - m) / sz)
        r = int((pos.y() - m) / sz)
        if not (0 <= c < 8 and 0 <= r < 8):
            return None
        return chess.square(7 - c, r) if self.flipped else chess.square(c, 7 - r)

    # ── Public setters ─────────────────────────────────────────────
    def set_theme(self, t):
        self.theme = t
        self.update()

    def set_position(self, board, lm=None):
        self.board = board
        self.last_move = lm
        self.selected_sq = None
        self.legal_targets = []
        self.anim_move = None
        self.anim_rook_move = None
        self._anim_progress_val = 1.0
        self._check_square = None
        self._check_opacity_val = 0.0
        self._flash_squares = ()
        self._flash_opacity_val = 0.0
        self.update()

    def set_position_animated(self, board, lm=None):
        self.board = board
        self.last_move = lm
        self.selected_sq = None
        self.legal_targets = []
        self.update()

    # ── Mouse events ───────────────────────────────────────────────
    def mousePressEvent(self, e):
        t, m, sz = self._layout()
        sq = self._pos_to_sq(e.position().toPoint(), t, m, sz)
        if sq is None:
            return
        if e.button() == Qt.LeftButton:
            if e.modifiers() & Qt.ShiftModifier:
                self._arr_s = sq
                self._draw_arr = True
                self._arr_e = sq
            else:
                self.squareClicked.emit(sq)
        elif e.button() == Qt.RightButton:
            self.highlighted.symmetric_difference_update({sq})
            self.update()

    def mouseMoveEvent(self, e):
        if self._draw_arr:
            t, m, sz = self._layout()
            sq = self._pos_to_sq(e.position().toPoint(), t, m, sz)
            if sq is not None:
                self._arr_e = sq
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._draw_arr:
            t, m, sz = self._layout()
            sq = self._pos_to_sq(e.position().toPoint(), t, m, sz)
            if sq and self._arr_s is not None and sq != self._arr_s:
                self.arrows.append((self._arr_s, sq, QColor(self.theme.arrow_clr)))
                self.update()
            self._draw_arr = False
            self._arr_s = self._arr_e = None

    # ── Painting ───────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        t, m, sz = self._layout()
        self._paint_content(p, t, m, sz)
        p.end()

    def _paint_content(self, p, t, m, sz):
        """Core board painting logic.  Works with any QPainter — can be
        called from ``paintEvent`` (widget on screen) or from
        ``render_to_image`` (off-screen QImage).  No backing store needed."""

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
            if self.last_move and s in (self.last_move.from_square, self.last_move.to_square):
                p.fillRect(rect, self.theme.last_move)
            if s == self.selected_sq:
                p.fillRect(rect, self.theme.highlight)
            if s in self.highlighted:
                p.fillRect(rect, QColor(0, 130, 255, 80))

        # Flash overlay
        if self._flash_squares and self._flash_opacity_val > 0:
            for fsq in self._flash_squares:
                p.fillRect(self._sq_rect(fsq, t, m, sz),
                           QColor(255, 255, 180, int(self._flash_opacity_val * 140)))

        # Check highlight
        if self._check_square is not None and self._check_opacity_val > 0:
            p.fillRect(self._sq_rect(self._check_square, t, m, sz),
                       QColor(255, 30, 30, int(self._check_opacity_val * 130)))

        # Coordinates
        if self.show_coords:
            fnt = QFont("Arial", max(7, int(sz * 0.14)))
            fnt.setBold(True)
            p.setFont(fnt)
            p.setPen(self.theme.coord)
            for i in range(8):
                fl = chr(ord('h') - i if self.flipped else ord('a') + i)
                rn = str(i + 1 if self.flipped else 8 - i)
                p.drawText(QRectF(m + i * sz + sz / 2 - sz / 2, t - m, sz, m),
                           Qt.AlignCenter, fl)
                p.drawText(QRectF(0, m + i * sz, m, sz), Qt.AlignCenter, rn)

        # Legal-move dots
        for mv in self.legal_targets:
            rect = self._sq_rect(mv, t, m, sz)
            p.setPen(Qt.NoPen)
            if self.board.piece_at(mv):
                p.setBrush(QColor(0, 0, 0, 60))
                p.drawEllipse(rect.adjusted(sz * 0.1, sz * 0.1, -sz * 0.1, -sz * 0.1))
            else:
                p.setBrush(QColor(0, 0, 0, 40))
                p.drawEllipse(rect.center(), sz * 0.15, sz * 0.15)

        # Policy visualization
        if self.policy_vis:
            p.setPen(Qt.NoPen)
            for uci, pr in self.policy_vis.items():
                try:
                    mv = chess.Move.from_uci(uci)
                    if mv in self.board.legal_moves:
                        rect = self._sq_rect(mv.to_square, t, m, sz)
                        p.setBrush(QColor.fromHsvF(0.33 * pr, 0.9, 0.9, 0.6 * pr + 0.1))
                        p.drawEllipse(rect.center(),
                                      sz * 0.4 * pr + sz * 0.1,
                                      sz * 0.4 * pr + sz * 0.1)
                except Exception:
                    pass

        # Arrows
        for fr, to, clr in self.arrows:
            self._draw_arrow(p, fr, to, clr, t, m, sz)
        if self._draw_arr and self._arr_s and self._arr_e:
            self._draw_arrow(p, self._arr_s, self._arr_e,
                             QColor(self.theme.arrow_clr), t, m, sz)

        # Pieces — skip squares that are being animated
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
                pr = self._anim_progress_val
                rf = self._sq_rect(self.anim_move.from_square, t, m, sz)
                rt = self._sq_rect(self.anim_move.to_square, t, m, sz)
                self._draw_piece(p, pc,
                                 QRectF(rf.x() + (rt.x() - rf.x()) * pr,
                                        rf.y() + (rt.y() - rf.y()) * pr,
                                        sz, sz), sz)

        # Animated rook (castling)
        if self.anim_rook_move:
            rfs, rts = self.anim_rook_move
            pc = self.board.piece_at(rts)
            if pc:
                pr = self._anim_progress_val
                rf = self._sq_rect(rfs, t, m, sz)
                rt = self._sq_rect(rts, t, m, sz)
                self._draw_piece(p, pc,
                                 QRectF(rf.x() + (rt.x() - rf.x()) * pr,
                                        rf.y() + (rt.y() - rf.y()) * pr,
                                        sz, sz), sz)

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

    def _draw_arrow(self, p, fr, to, color, total, margin, sz):
        r1 = self._sq_rect(fr, total, margin, sz)
        r2 = self._sq_rect(to, total, margin, sz)
        c1, c2 = r1.center(), r2.center()
        dx, dy = c2.x() - c1.x(), c2.y() - c1.y()
        length = math.hypot(dx, dy)
        if length < 1:
            return
        ux, uy = dx / length, dy / length
        start = QPointF(c1.x() + ux * sz * 0.35, c1.y() + uy * sz * 0.35)
        end = QPointF(c2.x() - ux * sz * 0.35, c2.y() - uy * sz * 0.35)
        pw = sz * 0.13
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.save()
        p.setOpacity(color.alphaF())
        px, py = -uy, ux
        path = QPainterPath()
        path.moveTo(start.x() + px * pw / 2, start.y() + py * pw / 2)
        path.lineTo(end.x() + px * pw / 2, end.y() + py * pw / 2)
        path.lineTo(end.x() - px * pw / 2, end.y() - py * pw / 2)
        path.lineTo(start.x() - px * pw / 2, start.y() - py * pw / 2)
        path.closeSubpath()
        p.drawPath(path)
        hw = pw * 2.0
        hl = pw * 1.8
        tip = QPointF(end.x() + ux * hl, end.y() + uy * hl)
        p.drawPolygon(QPolygonF([
            end,
            QPointF(end.x() + px * hw / 2, end.y() + py * hw / 2),
            tip,
            QPointF(end.x() - px * hw / 2, end.y() - py * hw / 2),
        ]))
        p.restore()

    def render_to_image(self, size=1080):
        """Render the board directly to a QImage at the requested resolution.

        Paints directly onto the image using the same ``_paint_content``
        method as ``paintEvent``, so **no widget backing store is needed**.
        Works even for widgets that have never been shown.
        """
        img = QImage(size, size, QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        m = size * 0.05 if self.show_coords else 0
        sz = (size - 2 * m) / 8
        self._paint_content(p, size, m, sz)
        p.end()
        return img