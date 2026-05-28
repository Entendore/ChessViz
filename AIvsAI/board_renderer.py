"""
Enhanced board renderer with move-quality badges,
improved piece shadows, and cleaner coordinates.

Badge system:
  - Only Brilliant & Blunder get board badges (rare, dramatic)
  - Brilliant/Blunder/Mistake get a colored square border glow
  - Badges are LARGER with stronger glow effects
  - Double-ring design for Brilliant/Blunder
"""

import chess
from PySide6.QtGui import (
    QPainter, QColor, QFont, QLinearGradient, QRadialGradient,
    QPainterPath, QPen,
)
from PySide6.QtCore import Qt, QRectF, QPointF
from constants import (
    PIECE_SYM, MQ_COLORS, MQ_ICONS, MQ_GOOD, MQ_BEST, MQ_BOOK,
    MQ_BRILLIANT, MQ_BLUNDER, MQ_MISTAKE, MQ_GREAT,
    MQ_SHOW_BADGE, MQ_SHOW_SQUARE_GLOW, MQ_SQUARE_GLOW_COLORS,
    THEMES,
)


class BoardRenderer:
    def __init__(self, board=None, theme=None, flipped=False):
        self.board = board or chess.Board()
        self.theme = theme if theme is not None else THEMES.get(
            "Classic", type('BoardTheme', (), {
                'light_sq': QColor(240, 217, 181),
                'dark_sq': QColor(181, 136, 99),
                'bg': QColor(32, 32, 36),
                'last_move': QColor(155, 199, 0, 100),
                'highlight': QColor(255, 255, 0, 100),
                'coord': QColor(180, 160, 130),
            })()
        )
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
        self.move_quality = MQ_GOOD
        self.policy_vis: dict = {}

        # Pre-cached rendering objects
        self._cache_sz = -1
        self._font_piece = None
        self._font_coord = None
        self._font_badge_normal = None
        self._font_badge_symbol = None
        self._pen_white_shadow = None
        self._pen_white_outline = None
        self._pen_black_shadow = None
        self._pen_badge_outline = None
        self._pen_badge_outer_ring = None

    def _update_cache(self, sz):
        isz = int(sz * 100)
        if isz == self._cache_sz:
            return
        self._cache_sz = isz

        self._font_piece = QFont("Segoe UI Symbol", sz * 0.72)
        self._font_piece.setStyleStrategy(QFont.PreferAntialias)

        self._font_coord = QFont("Inter", max(7, int(sz * 0.13)))
        self._font_coord.setBold(True)

        # Larger badge fonts for more prominent badges
        self._font_badge_normal = QFont("Inter", max(8, int(sz * 0.26 * 0.9)), QFont.Bold)
        self._font_badge_symbol = QFont("Segoe UI Symbol", max(9, int(sz * 0.26 * 1.1)), QFont.Bold)

        self._pen_white_shadow  = QPen(QColor(0, 0, 0, 50), max(1, sz * 0.03))
        self._pen_white_outline = QPen(QColor(0, 0, 0, 200), max(1, sz * 0.04))
        self._pen_black_shadow  = QPen(QColor(0, 0, 0, 60), max(1, sz * 0.03))
        self._pen_badge_outline = QPen(QColor(255, 255, 255, 140), max(1.0, sz * 0.012))
        self._pen_badge_outer_ring = QPen(QColor(255, 255, 255, 80), max(0.8, sz * 0.008))

    def render(self, size=1080):
        from PySide6.QtGui import QImage
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
        self._update_cache(sz)

        # Background
        bg_grad = QLinearGradient(0, 0, 0, t)
        bg_grad.setColorAt(0.0, self.theme.bg.darker(110))
        bg_grad.setColorAt(1.0, self.theme.bg)
        p.fillRect(QRectF(0, 0, t, t), bg_grad)

        # Square glow (BEFORE normal square fill for subtle effect)
        if self.last_move and self.move_quality in MQ_SHOW_SQUARE_GLOW:
            self._draw_square_glow(p, self.last_move.to_square, t, m, sz)

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

        # Square quality overlay on destination
        if self.last_move and self.move_quality in MQ_SHOW_SQUARE_GLOW:
            self._draw_square_quality_overlay(p, self.last_move.to_square, t, m, sz)

        # Check glow
        if self._check_square is not None and self._check_opacity > 0:
            cr = self._sq_rect(self._check_square, t, m, sz)
            rg = QRadialGradient(cr.center(), sz * 0.7)
            rg.setColorAt(0.0, QColor(255, 30, 30, int(self._check_opacity * 160)))
            rg.setColorAt(0.6, QColor(255, 0, 0, int(self._check_opacity * 70)))
            rg.setColorAt(1.0, QColor(255, 0, 0, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(rg)
            p.drawRect(cr)

        # Coordinates
        if self.show_coords:
            p.setFont(self._font_coord)
            p.setPen(self.theme.coord)
            for i in range(8):
                fl = chr(ord("h") - i if self.flipped else ord("a") + i)
                rn = str(i + 1 if self.flipped else 8 - i)
                p.drawText(QRectF(m + i * sz + sz / 2 - sz / 2, t - m, sz, m),
                           Qt.AlignCenter, fl)
                p.drawText(QRectF(0, m + i * sz, m, sz), Qt.AlignCenter, rn)

        # Pieces (skip animated squares)
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

        # Animated piece
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
                w, h = sz * scale, sz * scale
                p.setPen(Qt.NoPen)
                so = 30 + int(70 * (lift / 0.18)) if lift > 0 else 30
                p.setBrush(QColor(0, 0, 0, so))
                sy = rf.y() + (rt.y() - rf.y()) * pr + sz * 0.85
                p.drawEllipse(QRectF(x + (w - sz * 0.7) / 2, sy, sz * 0.7, sz * 0.15))
                self._draw_piece(p, pc, QRectF(x, y, w, h), sz * scale)

        # Animated rook (castling)
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
                w, h = sz * scale, sz * scale
                p.setPen(Qt.NoPen)
                shadow_a = 30 + int(50 * (lift / 0.12)) if lift > 0 else 30
                p.setBrush(QColor(0, 0, 0, shadow_a))
                sy = rf.y() + (rt.y() - rf.y()) * pr + sz * 0.85
                p.drawEllipse(QRectF(x + (w - sz * 0.7) / 2, sy, sz * 0.7, sz * 0.15))
                self._draw_piece(p, pc, QRectF(x, y, w, h), sz * scale)

        # Move-quality badge (only for Brilliant & Blunder)
        if self.last_move and self.move_quality in MQ_SHOW_BADGE:
            self._draw_quality_badge(p, self.last_move.to_square, t, m, sz)

    # ── Square glow ───────────────────────────────────────────
    def _draw_square_glow(self, p, sq, t, m, sz):
        rect = self._sq_rect(sq, t, m, sz)
        glow_color = MQ_SQUARE_GLOW_COLORS.get(self.move_quality, QColor(150, 150, 150))

        glow_extent = sz * 0.35
        rg = QRadialGradient(rect.center(), glow_extent + sz * 0.5)
        c = glow_color
        rg.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 120))
        rg.setColorAt(0.4, QColor(c.red(), c.green(), c.blue(), 60))
        rg.setColorAt(0.7, QColor(c.red(), c.green(), c.blue(), 20))
        rg.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(rg)
        outer = rect.adjusted(-glow_extent, -glow_extent, glow_extent, glow_extent)
        p.drawRoundedRect(outer, 8, 8)

    # ── Square quality overlay ────────────────────────────────
    def _draw_square_quality_overlay(self, p, sq, t, m, sz):
        rect = self._sq_rect(sq, t, m, sz)
        glow_color = MQ_SQUARE_GLOW_COLORS.get(self.move_quality, QColor(150, 150, 150))
        c = glow_color

        border_w = max(3, sz * 0.04)
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 200), border_w))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect.adjusted(border_w / 2, border_w / 2,
                                 -border_w / 2, -border_w / 2))

    # ── Quality badge ─────────────────────────────────────────
    def _draw_quality_badge(self, p, sq, t, m, sz):
        rect = self._sq_rect(sq, t, m, sz)
        quality = self.move_quality
        color = MQ_COLORS.get(quality, QColor(150, 150, 150))
        icon = MQ_ICONS.get(quality, "")

        # LARGER badge: 0.26 instead of 0.19
        r = sz * 0.26
        cx = rect.right() - r - sz * 0.04
        cy = rect.top() + r + sz * 0.04
        center = QPointF(cx, cy)

        # DRAMATIC multi-layered glow
        if quality == MQ_BRILLIANT:
            for radius_mult, alpha in [(5.0, 50), (3.5, 80), (2.5, 110)]:
                glow = QRadialGradient(center, r * radius_mult)
                glow.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), alpha))
                glow.setColorAt(0.5, QColor(color.red(), color.green(), color.blue(), alpha // 3))
                glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                p.drawEllipse(QRectF(cx - r * radius_mult, cy - r * radius_mult,
                                      r * 2 * radius_mult, r * 2 * radius_mult))

        elif quality == MQ_BLUNDER:
            for radius_mult, alpha in [(5.0, 60), (3.5, 90), (2.5, 120)]:
                glow = QRadialGradient(center, r * radius_mult)
                glow.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), alpha))
                glow.setColorAt(0.5, QColor(color.red(), color.green(), color.blue(), alpha // 3))
                glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                p.drawEllipse(QRectF(cx - r * radius_mult, cy - r * radius_mult,
                                      r * 2 * radius_mult, r * 2 * radius_mult))

        # Badge shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawEllipse(QRectF(cx - r + 1.5, cy - r + 2, 2 * r, 2 * r))

        # Outer ring (decorative double-ring effect)
        outer_r = r + max(2, sz * 0.025)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 100),
                       max(1, sz * 0.012)))
        p.drawEllipse(QRectF(cx - outer_r, cy - outer_r, 2 * outer_r, 2 * outer_r))

        # Badge background with gradient
        bg_grad = QRadialGradient(QPointF(cx - r * 0.3, cy - r * 0.3), r * 1.5)
        bg_grad.setColorAt(0.0, color.lighter(130))
        bg_grad.setColorAt(1.0, color)
        p.setPen(Qt.NoPen)
        p.setBrush(bg_grad)
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))

        # White outline
        p.setPen(self._pen_badge_outline)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))

        # Icon
        if icon:
            if icon in ("★", "✕"):
                p.setFont(self._font_badge_symbol)
            else:
                p.setFont(self._font_badge_normal)
            p.setPen(QColor(0, 0, 0, 80))
            p.drawText(QRectF(cx - r + 1, cy - r + 1, 2 * r, 2 * r),
                       Qt.AlignCenter, icon)
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(cx - r, cy - r, 2 * r, 2 * r),
                       Qt.AlignCenter, icon)

    # ── Piece drawing ─────────────────────────────────────────
    def _draw_piece(self, p, piece, rect, sz):
        sym = PIECE_SYM.get((piece.piece_type, piece.color), "?")
        p.setFont(self._font_piece)
        if piece.color == chess.WHITE:
            p.setPen(self._pen_white_shadow)
            p.drawText(rect.adjusted(0, sz * 0.02, 0, sz * 0.02), Qt.AlignCenter, sym)
            p.setPen(self._pen_white_outline)
            p.drawText(rect, Qt.AlignCenter, sym)
            p.setPen(QColor(255, 255, 255))
            p.drawText(rect, Qt.AlignCenter, sym)
        else:
            p.setPen(self._pen_black_shadow)
            p.drawText(rect.adjusted(0, sz * 0.02, 0, sz * 0.02), Qt.AlignCenter, sym)
            p.setPen(QColor(30, 30, 30))
            p.drawText(rect, Qt.AlignCenter, sym)