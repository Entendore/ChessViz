#!/usr/bin/env python3
"""Chess board widget — rendering, animation, mouse interaction."""

import math
import time

import chess
import numpy as np

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, QRectF, Signal, QTimer, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QRadialGradient,
    QImage, QPixmap, QPolygonF, QPainterPath, QTransform,
)

from config import (
    SQ_SIZE, BOARD_PX, PIECE_SYM, FILES_STR, RANKS_STR,
    ANIM_SPEED_DEFAULT, ANIM_FPS, THEMES,
)
from utils import get_render_assets, ease_out_cubic, log

# ── Local Dependency Check ──────────────────────────────────────────────────

HAS_NUMBA = False
try:
    import numba
    HAS_NUMBA = True
except ImportError:
    pass

HAS_CUPY = False
try:
    import cupy as cp
    HAS_CUPY = True
except Exception:
    pass

# ── Stride fixer (Numba-optional) ──────────────────────────────────────────

if HAS_NUMBA:
    from numba import njit as _njit2

    @_njit2(cache=True, nogil=True)
    def _fix_stride_nb(raw, w, h, bpl):
        out = np.empty((h, w, 3), dtype=np.uint8)
        w3 = w * 3
        for i in range(h):
            src = i * bpl
            dst = i * w3
            for j in range(w3):
                out.flat[dst + j] = raw.flat[src + j]
        return out
    log("Numba JIT stride-fixer loaded", "BOARD")
else:
    def _fix_stride_nb(raw, w, h, bpl):
        return raw[:, :w * 3].reshape(h, w, 3)


# ── Chess Board Widget ─────────────────────────────────────────────────────

class ChessBoardWidget(QWidget):
    move_made = Signal(str)

    def __init__(self, engine, sound_mgr, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.snd = sound_mgr
        self.selected = None
        self.legal_targets = []
        self.setFixedSize(SQ_SIZE * 8, SQ_SIZE * 8)
        self.setMouseTracking(True)

        self.animating = False
        self.anim_from = None
        self.anim_to = None
        self.anim_piece_obj = None
        self.anim_captured = '.'
        self.anim_progress = 0.0
        self.anim_speed = ANIM_SPEED_DEFAULT
        self.anim_start_time = 0.0
        self.pending_notation = None

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(1000 // ANIM_FPS)
        self._anim_timer.timeout.connect(self._anim_tick)

        self.current_theme = THEMES["Classic"]

    # ── Animation ───────────────────────────────────────────────────────

    def start_animation(self, fr, fc, tr, tc, piece_obj, captured='.', notation=''):
        self.animating = True
        self.anim_from = (fr, fc)
        self.anim_to = (tr, tc)
        self.anim_piece_obj = piece_obj
        self.anim_captured = captured
        self.anim_progress = 0.0
        self.anim_start_time = time.perf_counter()
        self.pending_notation = notation
        self._anim_timer.start()

    def _anim_tick(self):
        elapsed = time.perf_counter() - self.anim_start_time
        duration = self.anim_speed / 1000.0
        self.anim_progress = min(1.0, elapsed / duration) if duration > 0 else 1.0
        self.update()
        if self.anim_progress >= 1.0:
            self._anim_timer.stop()
            self.animating = False
            self.anim_piece_obj = None
            self.update()
            if self.pending_notation:
                self.move_made.emit(self.pending_notation)
                self.pending_notation = None

    def _get_anim_state(self):
        if not self.animating:
            return None
        t_eased = ease_out_cubic(self.anim_progress)
        return {'from': self.anim_from, 'to': self.anim_to,
                'piece_obj': self.anim_piece_obj, 'progress': t_eased}

    # ── Paint ───────────────────────────────────────────────────────────

    def paintEvent(self, e):
        chk = self.engine.check_squares()
        img = self.render_frame(
            self.engine.board, self.engine.last_move,
            self.selected, self.legal_targets,
            check_squares=chk, anim_state=self._get_anim_state(),
            theme=self.current_theme)
        pix = QPixmap.fromImage(img)
        painter = QPainter(self)
        painter.drawPixmap(0, 0, pix)
        painter.end()

    # ── Static rendering ────────────────────────────────────────────────

    @staticmethod
    def render_frame(board, last_move=None, selected=None, legal_targets=None,
                     text_overlay="", check_squares=None, anim_state=None,
                     sq_size=SQ_SIZE, show_arrow=True, theme=None):
        if theme is None:
            theme = THEMES["Classic"]
        sz = sq_size
        img = QImage(sz * 8, sz * 8, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        (font_piece, font_coord, font_badge_normal,
         font_badge_symbol, pen_badge_outline) = get_render_assets(sz)

        check_set = set(check_squares or [])
        skip_sq = set()
        if anim_state:
            skip_sq.add(anim_state['from'])
            skip_sq.add(anim_state['to'])

        for sq in chess.SQUARES:
            r, c = 7 - chess.square_rank(sq), chess.square_file(sq)
            x, y = c * sz, r * sz
            is_light = (r + c) % 2 == 0
            color = theme.light_sq if is_light else theme.dark_sq
            p.fillRect(x, y, sz, sz, color)
            if last_move and (r, c) in last_move:
                p.fillRect(x, y, sz, sz, theme.last_move)
            if selected and (r, c) == selected:
                p.fillRect(x, y, sz, sz, theme.highlight)
            if (r, c) in check_set:
                grad = QRadialGradient(x + sz / 2, y + sz / 2, sz * 0.7)
                grad.setColorAt(0, QColor(255, 30, 30, 180))
                grad.setColorAt(1, QColor(255, 0, 0, 0))
                p.setBrush(QBrush(grad))
                p.setPen(Qt.NoPen)
                p.drawRect(x, y, sz, sz)
            if legal_targets and (r, c) in legal_targets:
                cx, cy = x + sz // 2, y + sz // 2
                if board.piece_at(sq) is not None:
                    p.setPen(QPen(QColor(0, 0, 0, 90), max(3, sz // 14)))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(cx - sz * 5 // 12, cy - sz * 5 // 12,
                                  sz * 10 // 12, sz * 10 // 12)
                else:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(0, 0, 0, 90))
                    p.drawEllipse(cx - sz // 6, cy - sz // 6, sz // 3, sz // 3)

        if show_arrow and last_move:
            (fr, fc), (tr, tc) = last_move
            ChessBoardWidget._draw_arrow(
                p, fc * sz + sz // 2, fr * sz + sz // 2,
                tc * sz + sz // 2, tr * sz + sz // 2,
                theme.arrow_clr, sz)

        for sq in chess.SQUARES:
            r, c = 7 - chess.square_rank(sq), chess.square_file(sq)
            if (r, c) in skip_sq:
                continue
            piece = board.piece_at(sq)
            if piece:
                ChessBoardWidget._draw_piece(p, piece, r, c, sz, font_piece)

        if anim_state and anim_state.get('captured', '.') != '.':
            fr, fc_ = anim_state['from']
            tr, tc_ = anim_state['to']
            cap_piece = board.piece_at(chess.square(tc_, 7 - tr))
            if cap_piece is None:
                sym = anim_state['captured']
                is_w = sym.isupper()
                pt_map = {'K': chess.KING, 'Q': chess.QUEEN, 'R': chess.ROOK,
                          'B': chess.BISHOP, 'N': chess.KNIGHT, 'P': chess.PAWN}
                pt = pt_map.get(sym.upper())
                if pt:
                    cap_piece = chess.Piece(pt, chess.WHITE if is_w else chess.BLACK)
                    fade = max(0, int(200 * (1.0 - anim_state['progress'])))
                    p.setOpacity(fade / 255.0)
                    ChessBoardWidget._draw_piece(p, cap_piece, tr, tc_, sz, font_piece)
                    p.setOpacity(1.0)

        if anim_state:
            fr, fc_ = anim_state['from']
            tr, tc_ = anim_state['to']
            t = anim_state['progress']
            anim_piece_obj = anim_state.get('piece_obj')
            if anim_piece_obj:
                lift = 4.0 * t * (1.0 - t) * 0.15
                scale = 1.0 + 4.0 * t * (1.0 - t) * 0.08
                ir = fr + (tr - fr) * t
                ic = fc_ + (tc_ - fc_) * t
                shadow_alpha = 30 + int(70 * (lift / 0.15))
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, shadow_alpha))
                sy = ir * sz + sz * 0.82
                p.drawEllipse(QRectF(ic * sz + (sz * scale - sz * 0.65) / 2,
                                     sy, sz * 0.65, sz * 0.12))
                w, h = sz * scale, sz * scale
                y_lift = ir * sz - (sz * lift)
                ChessBoardWidget._draw_piece_at(
                    p, anim_piece_obj, y_lift / sz, ic, sz, w, h, font_piece)

        p.setFont(font_coord)
        coord_margin = max(3, int(sz * 0.04))
        coord_sz = max(12, sz // 5)
        for c in range(8):
            is_light = (7 + c) % 2 == 0
            col = theme.dark_sq if is_light else theme.light_sq
            p.setPen(col)
            p.drawText(QRect(c * sz + sz - coord_sz - coord_margin,
                             7 * sz + coord_margin, coord_sz, coord_sz),
                       Qt.AlignCenter, FILES_STR[c])
        for r in range(8):
            is_light = r % 2 == 0
            col = theme.dark_sq if is_light else theme.light_sq
            p.setPen(col)
            p.drawText(QRect(coord_margin, r * sz + coord_margin,
                             coord_sz, coord_sz), Qt.AlignCenter, RANKS_STR[r])

        if text_overlay:
            p.fillRect(0, sz * 4 - 28, sz * 8, 56, QColor(0, 0, 0, 200))
            p.setPen(Qt.white)
            p.setFont(QFont("Sans", max(12, sz // 4), QFont.Bold))
            p.drawText(QRect(0, sz * 4 - 28, sz * 8, 56),
                       Qt.AlignCenter, text_overlay)
        p.end()
        return img

    # ── Card rendering (title / end) ────────────────────────────────────

    @staticmethod
    def render_card(text, bg="#1a1a2e", fg="#e0e0e0", w=544, h=544,
                    width=None, height=None, font_size=36, sub_text="",
                    bg_color=None, fg_color=None):
        bg_val = bg if bg != "#1a1a2e" else (bg_color or bg)
        fg_val = fg if fg != "#e0e0e0" else (fg_color or fg)
        w_val = width if width is not None else w
        h_val = height if height is not None else h
        img = QImage(w_val, h_val, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(bg_val))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(fg_val))
        p.setFont(QFont("Sans", font_size, QFont.Bold))
        p.drawText(QRect(0, 0, w_val, h_val), Qt.AlignCenter, text)
        if sub_text:
            p.setFont(QFont("Sans", max(10, font_size // 2)))
            p.setPen(QColor(fg_val).lighter(140))
            p.drawText(QRect(0, h_val * 3 // 5, w_val, h_val // 4),
                       Qt.AlignCenter, sub_text)
        p.end()
        return img

    # ── Piece drawing ───────────────────────────────────────────────────

    @staticmethod
    def _draw_piece(p, piece_obj, row, col, sz, font):
        ChessBoardWidget._draw_piece_at(p, piece_obj, float(row), float(col),
                                        sz, sz, sz, font)

    @staticmethod
    def _draw_piece_at(p, piece_obj, row_f, col_f, sz, w, h, font):
        FIT_FRAC = 0.85
        is_w = piece_obj.color == chess.WHITE
        glyph = PIECE_SYM[(piece_obj.piece_type, piece_obj.color)]
        px = col_f * sz
        py = row_f * sz
        rect = QRectF(px + (sz - w) / 2, py + (sz - h) / 2, w, h)
        center = rect.center()
        p.setFont(font)
        path = QPainterPath()
        path.addText(QPointF(0, 0), font, glyph)
        br = path.boundingRect()
        path.translate(-br.center().x(), -br.center().y())
        if br.width() > 0 and br.height() > 0:
            sx = (w * FIT_FRAC) / br.width()
            sy = (h * FIT_FRAC) / br.height()
            s = min(sx, sy)
            path = QTransform.fromScale(s, s).map(path)
        path.translate(center.x(), center.y())
        if is_w:
            shadow = QPainterPath(path)
            shadow.translate(1.5, 2.0)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 50))
            p.drawPath(shadow)
            olw = max(1.2, sz * 0.028)
            p.setPen(QPen(QColor(30, 30, 30), olw, Qt.SolidLine,
                          Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QColor(255, 255, 255))
            p.drawPath(path)
        else:
            shadow = QPainterPath(path)
            shadow.translate(1.5, 2.0)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 60))
            p.drawPath(shadow)
            olw = max(0.8, sz * 0.018)
            p.setPen(QPen(QColor(10, 10, 10), olw, Qt.SolidLine,
                          Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QColor(40, 40, 40))
            p.drawPath(path)

    # ── Arrow drawing ───────────────────────────────────────────────────

    @staticmethod
    def _draw_arrow(painter, fx, fy, tx, ty, color, sz):
        dx = tx - fx
        dy = ty - fy
        dist = max(1, math.hypot(dx, dy))
        margin = sz * 0.22
        fx2 = fx + dx * margin / dist
        fy2 = fy + dy * margin / dist
        tx2 = tx - dx * margin / dist
        ty2 = ty - dy * margin / dist
        painter.setPen(QPen(color, max(2, sz // 20), Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(int(fx2), int(fy2), int(tx2), int(ty2))
        angle = math.atan2(dy, dx)
        a_sz = sz * 0.22
        p1x = tx2 - a_sz * math.cos(angle - 0.45)
        p1y = ty2 - a_sz * math.sin(angle - 0.45)
        p2x = tx2 - a_sz * math.cos(angle + 0.45)
        p2y = ty2 - a_sz * math.sin(angle + 0.45)
        tri = QPolygonF([QPointF(tx2, ty2), QPointF(p1x, p1y), QPointF(p2x, p2y)])
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(tri)

    # ── QImage ↔ NumPy ─────────────────────────────────────────────────

    @staticmethod
    def qimage_to_np(img):
        img2 = img.convertToFormat(QImage.Format_RGB888)
        ptr = img2.constBits()
        if hasattr(ptr, 'setsize'):
            ptr.setsize(img2.sizeInBytes())
        w = img2.width()
        h = img2.height()
        bpl = img2.bytesPerLine()
        raw = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl)).copy()
        if bpl == w * 3:
            return raw.reshape((h, w, 3))
        return _fix_stride_nb(raw, w, h, bpl)

    @staticmethod
    def qimage_to_np_batch(images, use_gpu=False):
        if not images:
            return np.empty((0, 0, 0, 3), dtype=np.uint8)
        arrays = [ChessBoardWidget.qimage_to_np(im) for im in images]
        stack = np.stack(arrays)
        if use_gpu and HAS_CUPY:
            import cupy as _cp
            return _cp.asarray(stack)
        return stack

    # ── Mouse ───────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if self.animating or self.engine.game_over:
            return
        c = int(e.position().x()) // SQ_SIZE
        r = int(e.position().y()) // SQ_SIZE
        if not (0 <= r < 8 and 0 <= c < 8):
            return
        sq = self.engine.rc_to_sq(r, c)
        piece = self.engine.board.piece_at(sq)

        if self.selected:
            sr, sc = self.selected
            if (r, c) in self.legal_targets:
                info = self.engine.make_move(sr, sc, r, c)
                if info:
                    is_capture = info['captured'] != '.'
                    sfx = ("capture" if is_capture
                           else "castle" if info['castle'] else "move")
                    if info['mate']:
                        sfx = "checkmate"
                    elif info['check']:
                        sfx = "check"
                    self.snd.play(sfx)
                    if self.anim_speed > 0:
                        self.start_animation(sr, sc, r, c, info['piece_obj'],
                                             info['captured'], info['notation'])
                    else:
                        self.move_made.emit(info['notation'])
            self.selected = None
            self.legal_targets = []
        else:
            if piece and piece.color == self.engine.board.turn:
                self.selected = (r, c)
                self.legal_targets = self.engine.legal_moves(r, c)
                if not self.legal_targets:
                    self.snd.play("error")
                    self.selected = None
        self.update()