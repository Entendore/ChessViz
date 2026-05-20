"""Chess Video Maker Pro — Professional Evaluation Bar Widget

Features:
  • Sigmoid (logistic) mapping instead of linear — better visual
    differentiation in the ±1–3 pawn range where most games live
  • Gradient fills on both white and black sections
  • Smooth 300 ms QPropertyAnimation on eval changes
  • Boundary line at the white/black transition
  • Dashed centre tick at equal (0.00)
  • Small tick marks at key eval thresholds
  • Pill-shaped eval text that repositions at the boundary
  • Mate scores with green/red pill styling
  • Rounded bottom corners on the white section
"""

import math
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QRectF, QPropertyAnimation, QEasingCurve, Property, QPointF
from PySide6.QtGui import (QPainter, QColor, QFont, QPen, QBrush,
                            QLinearGradient, QPainterPath)


class EvalBarWidget(QWidget):
    """Professional vertical evaluation bar with sigmoid mapping,
    gradient fills, smooth animation, and overlaid eval text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._eval_cp = 0.0       # target / current eval (centipawns, White POV)
        self._anim_cp = 0.0       # animated eval for smooth bar movement
        self.setFixedWidth(54)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumHeight(200)

        # Smooth bar-fill animation
        self._animation = QPropertyAnimation(self, b"anim_cp")
        self._animation.setDuration(300)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    # ── Qt Property for QPropertyAnimation ──────────────────────────

    def _get_anim_cp(self):
        return self._anim_cp

    def _set_anim_cp(self, val):
        self._anim_cp = val
        self.update()

    anim_cp = Property(float, _get_anim_cp, _set_anim_cp)

    # ── Public API ──────────────────────────────────────────────────

    def set_eval(self, cp):
        """Set the evaluation in centipawns (from White's perspective)."""
        old = self._eval_cp
        self._eval_cp = cp

        # Snap instantly when transitioning to / from mate scores
        if abs(cp) > 9000 or abs(old) > 9000:
            self._anim_cp = float(cp)
            self.update()
            return

        # Smooth animation for normal eval changes
        self._animation.stop()
        self._animation.setStartValue(self._anim_cp)
        self._animation.setEndValue(float(cp))
        self._animation.start()

    # ── Sigmoid Mapping ─────────────────────────────────────────────

    @staticmethod
    def _cp_to_ratio(cp):
        """Map centipawns → [0, 1] via logistic function.

        k = 0.004 yields:
            0 cp  → 0.500
          ±100     → 0.60 / 0.40   (~1 pawn)
          ±200     → 0.69 / 0.31   (~2 pawns)
          ±300     → 0.77 / 0.23   (~3 pawns)
          ±500     → 0.88 / 0.12
          ±1000    → 0.98 / 0.02
          ±2000    → ≈1.0 / ≈0.0
        """
        clamped = max(-10000.0, min(10000.0, cp))
        return 1.0 / (1.0 + math.exp(-0.004 * clamped))

    # ── Painting ────────────────────────────────────────────────────

    def paintEvent(self, _):                          # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        W, H = self.width(), self.height()
        pad = 5                                       # inner padding
        cr  = 5                                       # corner radius

        bx, by = pad, pad
        bw, bh = W - 2 * pad, H - 2 * pad

        # ── 1. Outer frame ──────────────────────────────────────────
        p.setPen(QPen(QColor(65, 65, 72), 1.5))
        p.setBrush(QColor(24, 24, 28))
        p.drawRoundedRect(QRectF(0, 0, W, H), cr + 2, cr + 2)

        # ── 2. Black section (top — fills entire bar as base) ───────
        blk = QLinearGradient(bx, by, bx, by + bh)
        blk.setColorAt(0.0, QColor(68, 68, 76))
        blk.setColorAt(0.5, QColor(54, 54, 60))
        blk.setColorAt(1.0, QColor(46, 46, 52))
        p.setPen(Qt.NoPen)
        p.setBrush(blk)
        p.drawRoundedRect(QRectF(bx, by, bw, bh), cr, cr)

        # ── 3. White section (bottom, height = eval ratio × bar) ───
        ratio = self._cp_to_ratio(self._anim_cp)
        wh = max(0, min(bh, int(bh * ratio)))         # white height in px

        if wh > 0:
            wt = by + bh - wh                          # white-top Y
            wg = QLinearGradient(bx, wt, bx, by + bh)
            wg.setColorAt(0.0, QColor(252, 249, 242))
            wg.setColorAt(0.3, QColor(246, 243, 235))
            wg.setColorAt(1.0, QColor(238, 234, 226))
            p.setBrush(wg)

            if wh >= bh:
                # Entire bar is white
                p.drawRoundedRect(QRectF(bx, by, bw, bh), cr, cr)
            elif wh < cr * 2:
                # Very thin strip — just draw a small rounded rect
                p.drawRoundedRect(QRectF(bx, wt, bw, wh), cr, cr)
            else:
                # Rounded bottom corners, flat top edge
                path = QPainterPath()
                path.moveTo(bx, wt)
                path.lineTo(bx + bw, wt)
                path.lineTo(bx + bw, by + bh - cr)
                path.quadTo(bx + bw, by + bh,
                            bx + bw - cr, by + bh)
                path.lineTo(bx + cr, by + bh)
                path.quadTo(bx, by + bh, bx, by + bh - cr)
                path.lineTo(bx, wt)
                path.closeSubpath()
                p.drawPath(path)

            # Subtle highlight / shine at top of white section
            if wh > 30:
                shine = QLinearGradient(bx, wt, bx, wt + 30)
                shine.setColorAt(0.0, QColor(255, 255, 255, 20))
                shine.setColorAt(1.0, QColor(255, 255, 255, 0))
                p.setBrush(shine)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(
                    QRectF(bx + 2, wt + 1, bw - 4, min(30, wh - 2)), 2, 2
                )

        # ── 4. Boundary line at white / black transition ────────────
        bdy = by + bh - wh
        if 0 < wh < bh:
            p.setPen(QPen(QColor(125, 120, 110, 180), 1.2))
            p.drawLine(QPointF(bx + 3, bdy), QPointF(bx + bw - 3, bdy))

        # ── 5. Centre tick (dashed) at equal evaluation ─────────────
        cy = by + bh / 2.0
        p.setPen(QPen(QColor(165, 160, 152, 90), 0.7, Qt.DotLine))
        p.drawLine(QPointF(bx + 4, cy), QPointF(bx + bw - 4, cy))

        # ── 6. Small ticks at ±0.5, ±1, ±2, ±5, ±10 ───────────────
        p.setPen(QPen(QColor(135, 130, 122, 70), 0.6))
        for cp_tick in (50, 100, 200, 500, 1000, 2000):
            for sign in (1, -1):
                t_ratio = self._cp_to_ratio(cp_tick * sign)
                ty = by + bh * (1.0 - t_ratio)
                if by + 3 < ty < by + bh - 3:
                    p.drawLine(QPointF(bx + bw - 5, ty),
                               QPointF(bx + bw - 1, ty))

        # ── 7. Eval text in a pill ──────────────────────────────────
        is_mate = abs(self._eval_cp) > 9000
        if is_mate:
            n = int(abs(self._eval_cp) - 10000)
            txt = f"M{n}"
        else:
            ev = self._eval_cp / 100.0
            if abs(ev) >= 10:
                txt = f"{ev:+.0f}"
            elif abs(ev) >= 1:
                txt = f"{ev:+.1f}"
            else:
                txt = f"{ev:+.2f}"

        fsz = max(8, min(13, int(bw * 0.32)))
        fnt = QFont("Segoe UI", fsz, QFont.Bold)
        p.setFont(fnt)
        fm = p.fontMetrics()
        th = fm.height()
        tw = fm.horizontalAdvance(txt) + 14

        # Position at the boundary, clamped inside the bar
        ty = bdy
        ty = max(by + th / 2 + 8, min(by + bh - th / 2 - 8, ty))

        pill = QRectF((W - tw) / 2, ty - th / 2 - 3, tw, th + 6)
        on_white = (ty >= by + bh - wh)

        if is_mate:
            pbg = (QColor(28, 150, 52, 220) if self._eval_cp > 0
                   else QColor(198, 38, 38, 220))
            pfg = QColor(255, 255, 255)
        else:
            pbg = (QColor(255, 255, 255, 200) if on_white
                   else QColor(18, 18, 24, 200))
            pfg = (QColor(28, 26, 22) if on_white
                   else QColor(242, 238, 230))

        # Pill shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRoundedRect(pill.adjusted(1, 1, 1, 1), 7, 7)

        # Pill background
        p.setBrush(pbg)
        p.drawRoundedRect(pill, 7, 7)

        # Pill text
        p.setPen(pfg)
        p.drawText(pill, Qt.AlignCenter, txt)

        p.end()