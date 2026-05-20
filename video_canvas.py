"""Chess Video Maker Pro — Video Canvas (Full-frame renderer)"""

import math
import os
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QImage, QLinearGradient, QPainterPath, QPen


class VideoCanvas:
    """Canvas generating full video frames combining board, eval bar, and graphics."""

    def __init__(self, board_widget, eval_bar_widget, w=1920, h=1080, bg_color=QColor(30, 30, 32)):
        self.bw = board_widget
        self.ew = eval_bar_widget
        self.w = w
        self.h = h
        self.bg_color = bg_color
        self.eval_cp = 0.0
        self.move_text = ""
        self.white_name = "White"
        self.black_name = "Black"
        self.engine_text = ""
        self.overlays = []
        self.move_list_text = []
        self.current_move_index = 0

    @staticmethod
    def _cp_to_ratio(cp):
        """Sigmoid mapping matching EvalBarWidget."""
        clamped = max(-10000.0, min(10000.0, cp))
        return 1.0 / (1.0 + math.exp(-0.004 * clamped))

    def render(self):
        img = QImage(self.w, self.h, QImage.Format_ARGB32)
        img.fill(self.bg_color)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        margin = 40
        board_size = int(self.h * 0.85)

        # ── 1. Professional Eval Bar ────────────────────────────────
        bar_w = max(30, int(board_size * 0.048))
        bar_h = board_size
        bar_x = margin
        bar_y = (self.h - board_size) // 2
        bar_cr = max(4, int(bar_w * 0.12))

        # Outer frame
        p.setPen(QPen(QColor(65, 65, 72), 2))
        p.setBrush(QColor(24, 24, 28))
        p.drawRoundedRect(
            QRectF(bar_x - 2, bar_y - 2, bar_w + 4, bar_h + 4),
            bar_cr + 2, bar_cr + 2
        )

        # Black section (top, full bar)
        blk = QLinearGradient(bar_x, bar_y, bar_x, bar_y + bar_h)
        blk.setColorAt(0.0, QColor(68, 68, 76))
        blk.setColorAt(0.5, QColor(54, 54, 60))
        blk.setColorAt(1.0, QColor(46, 46, 52))
        p.setPen(Qt.NoPen)
        p.setBrush(blk)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), bar_cr, bar_cr)

        # White section (bottom)
        ratio = self._cp_to_ratio(self.eval_cp)
        wh = max(0, min(bar_h, int(bar_h * ratio)))

        if wh > 0:
            wt = bar_y + bar_h - wh
            wg = QLinearGradient(bar_x, wt, bar_x, bar_y + bar_h)
            wg.setColorAt(0.0, QColor(252, 249, 242))
            wg.setColorAt(0.3, QColor(246, 243, 235))
            wg.setColorAt(1.0, QColor(238, 234, 226))
            p.setBrush(wg)

            if wh >= bar_h:
                p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), bar_cr, bar_cr)
            elif wh < bar_cr * 2:
                p.drawRoundedRect(QRectF(bar_x, wt, bar_w, wh), bar_cr, bar_cr)
            else:
                path = QPainterPath()
                path.moveTo(bar_x, wt)
                path.lineTo(bar_x + bar_w, wt)
                path.lineTo(bar_x + bar_w, bar_y + bar_h - bar_cr)
                path.quadTo(bar_x + bar_w, bar_y + bar_h,
                            bar_x + bar_w - bar_cr, bar_y + bar_h)
                path.lineTo(bar_x + bar_cr, bar_y + bar_h)
                path.quadTo(bar_x, bar_y + bar_h, bar_x, bar_y + bar_h - bar_cr)
                path.lineTo(bar_x, wt)
                path.closeSubpath()
                p.drawPath(path)

            # Subtle shine
            if wh > 40:
                shine = QLinearGradient(bar_x, wt, bar_x, wt + 40)
                shine.setColorAt(0.0, QColor(255, 255, 255, 20))
                shine.setColorAt(1.0, QColor(255, 255, 255, 0))
                p.setBrush(shine)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(
                    QRectF(bar_x + 2, wt + 1, bar_w - 4, min(40, wh - 2)), 2, 2
                )

        # Boundary line
        bdy = bar_y + bar_h - wh
        if 0 < wh < bar_h:
            p.setPen(QPen(QColor(125, 120, 110, 180), 1.5))
            p.drawLine(QPointF(bar_x + 4, bdy), QPointF(bar_x + bar_w - 4, bdy))

        # Centre tick
        cy = bar_y + bar_h / 2.0
        p.setPen(QPen(QColor(165, 160, 152, 90), 1.0, Qt.DotLine))
        p.drawLine(QPointF(bar_x + 5, cy), QPointF(bar_x + bar_w - 5, cy))

        # Small ticks at key eval thresholds
        p.setPen(QPen(QColor(135, 130, 122, 70), 0.8))
        for cp_tick in (50, 100, 200, 500, 1000, 2000):
            for sign in (1, -1):
                t_ratio = self._cp_to_ratio(cp_tick * sign)
                ty = bar_y + bar_h * (1.0 - t_ratio)
                if bar_y + 4 < ty < bar_y + bar_h - 4:
                    p.drawLine(QPointF(bar_x + bar_w - 6, ty),
                               QPointF(bar_x + bar_w - 1, ty))

        # Eval text pill
        is_mate = abs(self.eval_cp) > 9000
        if is_mate:
            n = int(abs(self.eval_cp) - 10000)
            txt = f"M{n}"
        else:
            ev = self.eval_cp / 100.0
            if abs(ev) >= 10:
                txt = f"{ev:+.0f}"
            elif abs(ev) >= 1:
                txt = f"{ev:+.1f}"
            else:
                txt = f"{ev:+.2f}"

        fsz = max(12, int(bar_w * 0.42))
        fnt = QFont("Segoe UI", fsz, QFont.Bold)
        p.setFont(fnt)
        fm = p.fontMetrics()
        th = fm.height()
        tw = fm.horizontalAdvance(txt) + 14

        ty = bdy
        ty = max(bar_y + th / 2 + 10, min(bar_y + bar_h - th / 2 - 10, ty))

        pill = QRectF(bar_x + (bar_w - tw) / 2, ty - th / 2 - 3, tw, th + 6)
        on_white = (ty >= bar_y + bar_h - wh)

        if is_mate:
            pbg = (QColor(28, 150, 52, 220) if self.eval_cp > 0
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
        p.drawRoundedRect(pill.adjusted(1, 1, 1, 1), 8, 8)

        # Pill background
        p.setBrush(pbg)
        p.drawRoundedRect(pill, 8, 8)

        # Pill text
        p.setPen(pfg)
        p.drawText(pill, Qt.AlignCenter, txt)

        # ── 2. Board ────────────────────────────────────────────────
        board_x = bar_x + bar_w + margin
        board_y = bar_y
        board_img = self.bw.render_to_image(board_size)
        p.drawImage(QRectF(board_x, board_y, board_size, board_size), board_img)

        # ── 3. Move List Panel ──────────────────────────────────────
        ml_x = board_x + board_size + margin
        ml_y = board_y
        ml_w = self.w - ml_x - margin
        ml_h = board_size
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(40, 40, 40))
        p.drawRoundedRect(ml_x, ml_y, ml_w, ml_h, 8, 8)
        p.setPen(QColor(200, 200, 200))
        p.setFont(QFont("Consolas", 14))

        x_off, y_off, line_h = 10, 15, 25
        move_num_w, san_w = 40, 70
        for i, san in enumerate(self.move_list_text):
            is_curr = (i == self.current_move_index)
            if is_curr:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(80, 120, 200, 150))
                p.drawRoundedRect(ml_x + x_off - 2, ml_y + y_off - 2, san_w + 4, line_h, 3, 3)
                p.setPen(QColor(255, 255, 255))
            else:
                p.setPen(QColor(180, 180, 180))
            if i % 2 == 0:
                p.drawText(QRectF(ml_x + x_off, ml_y + y_off, move_num_w, line_h), Qt.AlignLeft, f"{i // 2 + 1}.")
                p.drawText(QRectF(ml_x + x_off + move_num_w, ml_y + y_off, san_w, line_h), Qt.AlignLeft, san)
            else:
                p.drawText(QRectF(ml_x + x_off + move_num_w + san_w + 10, ml_y + y_off, san_w, line_h), Qt.AlignLeft, san)
            if i % 2 == 1:
                y_off += line_h
                x_off = 10
                if y_off > ml_h - 20:
                    break
            else:
                x_off = 0

        # ── 4. Names ────────────────────────────────────────────────
        p.setPen(QColor(200, 200, 200))
        p.setFont(QFont("Segoe UI", int(self.h * 0.025), QFont.Bold))
        top_name = self.black_name if not self.bw.flipped else self.white_name
        bot_name = self.white_name if not self.bw.flipped else self.black_name
        p.drawText(QRectF(board_x, board_y + board_size + 10, board_size / 2, 40), Qt.AlignLeft | Qt.AlignVCenter, bot_name)
        p.drawText(QRectF(board_x, board_y - 50, board_size / 2, 40), Qt.AlignLeft | Qt.AlignVCenter, top_name)

        if self.move_text:
            p.setFont(QFont("Segoe UI", int(self.h * 0.022)))
            p.setPen(QColor(170, 170, 170))
            p.drawText(QRectF(board_x + board_size / 2, board_y + board_size + 10, board_size / 2, 40),
                       Qt.AlignRight | Qt.AlignVCenter, self.move_text)
        if self.engine_text:
            p.setFont(QFont("Segoe UI", int(self.h * 0.018)))
            p.setPen(QColor(100, 170, 255))
            p.drawText(QRectF(board_x + board_size / 2, board_y - 45, board_size / 2, 40),
                       Qt.AlignRight | Qt.AlignVCenter, self.engine_text)

        # ── 5. Image Overlays ───────────────────────────────────────
        for ov in self.overlays:
            if os.path.exists(ov['path']):
                ov_img = QImage(ov['path'])
                if not ov_img.isNull():
                    p.drawImage(QRectF(ov['x'], ov['y'], ov['w'], ov['h']), ov_img)
        p.end()
        return img