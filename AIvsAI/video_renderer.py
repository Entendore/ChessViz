"""
Enhanced video renderer with Lichess-style layout,
title screen, and result screen.
"""

import math
import os
from PySide6.QtGui import (
    QPainter, QColor, QFont, QImage, QLinearGradient,
    QPainterPath, QPen, QPolygonF,
)
from PySide6.QtCore import Qt, QRectF, QPointF
from constants import (
    GAME_NORMAL, GAME_CHECKMATE,
    MQ_GOOD, MQ_VIDEO_COLORS, MQ_SYMBOLS, MQ_COLORS,
)
from board_renderer import BoardRenderer
from movelist_renderer import render_movelist_2col


class VideoRenderer:
    def __init__(self, board_renderer, w=1920, h=1080,
                 bg_color=QColor(28, 28, 30)):
        self.board_renderer = board_renderer
        self.w, self.h = w, h
        self.bg_color = bg_color
        self.eval_cp = 0.0
        self.eval_history: list[float] = []
        self.move_qualities: list[str] = []
        self.move_text = ""
        self.white_name = "White"
        self.black_name = "Black"
        self.white_engine_info = ""
        self.black_engine_info = ""
        self.overlays = []
        self.move_list_text: list[str] = []
        self.current_move_index = 0
        self.game_state = GAME_NORMAL
        self.game_result = ""
        self.game_detail = ""

    @staticmethod
    def _cp2r(cp):
        if cp >= 9000: return 1.0
        if cp <= -9000: return 0.0
        return 1.0 / (1.0 + math.exp(-0.004 * max(-10000, min(10000, cp))))

    # ── Main render ───────────────────────────────────────────
    def render(self):
        img = QImage(self.w, self.h, QImage.Format_ARGB32)
        bg = QLinearGradient(0, 0, 0, self.h)
        bg.setColorAt(0.0, QColor(30, 30, 34))
        bg.setColorAt(1.0, QColor(22, 22, 26))
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(QRectF(0, 0, self.w, self.h), bg)
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

    # ── Title Screen ──────────────────────────────────────────
    def render_title_screen(self):
        """Render a title/intro card for the video."""
        img = QImage(self.w, self.h, QImage.Format_ARGB32)
        bg = QLinearGradient(0, 0, 0, self.h)
        bg.setColorAt(0.0, QColor(26, 26, 30))
        bg.setColorAt(0.5, QColor(30, 30, 36))
        bg.setColorAt(1.0, QColor(22, 22, 26))
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(QRectF(0, 0, self.w, self.h), bg)

        cx, cy = self.w / 2, self.h / 2

        if self.h > self.w:
            self._render_title_portrait(p, cx, cy)
        else:
            self._render_title_landscape(p, cx, cy)

        p.end()
        return img

    def _render_title_landscape(self, p, cx, cy):
        bsz = int(min(self.w * 0.35, self.h * 0.6))
        bx = cx - bsz / 2
        by = cy - bsz / 2 - 10

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 100))
        p.drawRoundedRect(QRectF(bx - 15, by - 15, bsz + 30, bsz + 30), 12, 12)

        bimg = self.board_renderer.render(bsz)
        p.setOpacity(0.25)
        p.drawImage(QRectF(bx, by, bsz, bsz), bimg)
        p.setOpacity(1.0)

        card_w = min(340, (self.w - bsz) / 2 - 60)
        card_h = 120
        left_cx = (bx - card_w) / 2
        self._draw_player_card(p, left_cx, cy - card_h / 2, card_w, card_h,
                               self.white_name, self.white_engine_info, True)

        right_cx = bx + bsz + (self.w - bx - bsz - card_w) / 2
        self._draw_player_card(p, right_cx, cy - card_h / 2, card_w, card_h,
                               self.black_name, self.black_engine_info, False)

        # VS emblem
        vs_r = 48
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawEllipse(QRectF(cx - vs_r + 2, cy - vs_r + 2, vs_r * 2, vs_r * 2))
        vs_grad = QLinearGradient(cx, cy - vs_r, cx, cy + vs_r)
        vs_grad.setColorAt(0.0, QColor(60, 120, 210))
        vs_grad.setColorAt(1.0, QColor(40, 90, 170))
        p.setBrush(vs_grad)
        p.drawEllipse(QRectF(cx - vs_r, cy - vs_r, vs_r * 2, vs_r * 2))
        p.setPen(QPen(QColor(255, 255, 255, 50), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(cx - vs_r, cy - vs_r, vs_r * 2, vs_r * 2))
        p.setFont(QFont("Inter", 28, QFont.Bold))
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(cx - vs_r, cy - vs_r, vs_r * 2, vs_r * 2),
                   Qt.AlignCenter, "VS")

        p.setFont(QFont("Inter", 11))
        p.setPen(QColor(120, 120, 140))
        sub_y = by + bsz + 40
        p.drawText(QRectF(0, sub_y, self.w, 30),
                   Qt.AlignHCenter | Qt.AlignTop, "AI vs AI  ·  Chess Battle")

    def _render_title_portrait(self, p, cx, cy):
        bsz = int(self.w * 0.5)
        bx = cx - bsz / 2
        by = cy - bsz / 2 + 30

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 100))
        p.drawRoundedRect(QRectF(bx - 12, by - 12, bsz + 24, bsz + 24), 10, 10)

        bimg = self.board_renderer.render(bsz)
        p.setOpacity(0.25)
        p.drawImage(QRectF(bx, by, bsz, bsz), bimg)
        p.setOpacity(1.0)

        card_w = min(300, self.w - 60)
        card_h = 80

        self._draw_player_card(p, (self.w - card_w) / 2, by - card_h - 30,
                               card_w, card_h,
                               self.white_name, self.white_engine_info, True)

        self._draw_player_card(p, (self.w - card_w) / 2, by + bsz + 30,
                               card_w, card_h,
                               self.black_name, self.black_engine_info, False)

        vs_r = 36
        p.setPen(Qt.NoPen)
        vs_grad = QLinearGradient(cx, cy - vs_r, cx, cy + vs_r)
        vs_grad.setColorAt(0.0, QColor(60, 120, 210))
        vs_grad.setColorAt(1.0, QColor(40, 90, 170))
        p.setBrush(vs_grad)
        p.drawEllipse(QRectF(cx - vs_r, cy - vs_r, vs_r * 2, vs_r * 2))
        p.setFont(QFont("Inter", 22, QFont.Bold))
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(cx - vs_r, cy - vs_r, vs_r * 2, vs_r * 2),
                   Qt.AlignCenter, "VS")

    def _draw_player_card(self, p, x, y, w, h, name, engine_info, is_white):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRoundedRect(QRectF(x + 2, y + 2, w, h), 8, 8)

        card_bg = QLinearGradient(x, y, x, y + h)
        card_bg.setColorAt(0.0, QColor(42, 42, 48))
        card_bg.setColorAt(1.0, QColor(34, 34, 40))
        p.setBrush(card_bg)
        p.setPen(QPen(QColor(60, 60, 70), 1.0))
        p.drawRoundedRect(QRectF(x, y, w, h), 8, 8)

        icon_r = 24
        icon_x = x + 18
        icon_y = y + (h - icon_r * 2) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(240, 240, 240) if is_white else QColor(50, 50, 55))
        p.drawEllipse(QRectF(icon_x, icon_y, icon_r * 2, icon_r * 2))
        p.setPen(QPen(QColor(0, 0, 0, 150), 1))
        p.drawEllipse(QRectF(icon_x, icon_y, icon_r * 2, icon_r * 2))
        sym = "♔" if is_white else "♚"
        p.setFont(QFont("Segoe UI Symbol", 20, QFont.Bold))
        p.setPen(QColor(30, 30, 30) if is_white else QColor(220, 220, 220))
        p.drawText(QRectF(icon_x, icon_y, icon_r * 2, icon_r * 2),
                   Qt.AlignCenter, sym)

        p.setPen(QColor(225, 225, 230))
        p.setFont(QFont("Inter", 14, QFont.Bold))
        p.drawText(QRectF(icon_x + icon_r * 2 + 14, y + 8, w - 100, h / 2),
                   Qt.AlignVCenter | Qt.AlignLeft, name)

        p.setPen(QColor(140, 140, 160))
        p.setFont(QFont("Inter", 10))
        p.drawText(QRectF(icon_x + icon_r * 2 + 14, y + h / 2 - 4, w - 100, h / 2),
                   Qt.AlignVCenter | Qt.AlignLeft, engine_info)

    # ── Result Screen ─────────────────────────────────────────
    def render_result_screen(self):
        img = self.render()
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(QRectF(0, 0, self.w, self.h), QColor(0, 0, 0, 160))

        cx, cy = self.w / 2, self.h / 2
        card_w, card_h = min(600, self.w * 0.5), min(260, self.h * 0.3)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawRoundedRect(QRectF(cx - card_w/2 + 4, cy - card_h/2 + 4,
                                 card_w, card_h), 16, 16)

        card_bg = QLinearGradient(cx, cy - card_h/2, cx, cy + card_h/2)
        card_bg.setColorAt(0.0, QColor(38, 38, 44))
        card_bg.setColorAt(1.0, QColor(30, 30, 36))
        p.setBrush(card_bg)
        p.setPen(QPen(QColor(70, 70, 80), 1.5))
        p.drawRoundedRect(QRectF(cx - card_w/2, cy - card_h/2,
                                 card_w, card_h), 16, 16)

        if self.game_state == GAME_CHECKMATE:
            w_wins = "1-0" in self.game_result
            accent = QColor(40, 180, 70) if w_wins else QColor(200, 50, 50)
            result_txt = "CHECKMATE"
            score_txt = self.game_result
        else:
            accent = QColor(180, 160, 50)
            result_txt = "DRAW"
            score_txt = "½ - ½"

        bar_h = 5
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        path = QPainterPath()
        r = 16
        bx1, by1 = cx - card_w/2, cy - card_h/2
        path.moveTo(bx1 + r, by1)
        path.lineTo(bx1 + card_w - r, by1)
        path.quadTo(bx1 + card_w, by1, bx1 + card_w, by1 + r)
        path.lineTo(bx1 + card_w, by1 + bar_h)
        path.lineTo(bx1, by1 + bar_h)
        path.lineTo(bx1, by1 + r)
        path.quadTo(bx1, by1, bx1 + r, by1)
        path.closeSubpath()
        p.drawPath(path)

        p.setFont(QFont("Inter", 28, QFont.Bold))
        p.setPen(accent)
        p.drawText(QRectF(cx - card_w/2, cy - card_h/2 + bar_h + 20,
                          card_w, 50), Qt.AlignHCenter | Qt.AlignTop, result_txt)

        p.setFont(QFont("Inter", 42, QFont.Bold))
        p.setPen(QColor(240, 240, 245))
        p.drawText(QRectF(cx - card_w/2, cy - card_h/2 + bar_h + 65,
                          card_w, 70), Qt.AlignHCenter | Qt.AlignTop, score_txt)

        if self.game_detail:
            p.setFont(QFont("Inter", 12))
            p.setPen(QColor(140, 140, 160))
            p.drawText(QRectF(cx - card_w/2, cy - card_h/2 + bar_h + 135,
                              card_w, 30), Qt.AlignHCenter | Qt.AlignTop,
                       self.game_detail)

        n = len(self.move_list_text)
        p.setFont(QFont("Inter", 10))
        p.setPen(QColor(100, 100, 120))
        p.drawText(QRectF(cx - card_w/2, cy - card_h/2 + card_h - 40,
                          card_w, 24), Qt.AlignHCenter | Qt.AlignTop,
                   f"{n} moves played")

        p.end()
        return img

    # ── Player Bar Helper ─────────────────────────────────────
    def _draw_player_bar_v(self, p, x, y, w, h, name, engine_info, eval_cp, is_white):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(30, 30, 34))
        p.drawRoundedRect(QRectF(x, y, w, h), 6, 6)

        p.setPen(QPen(QColor(55, 55, 65), 0.8))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(x, y, w, h), 6, 6)

        icon_r = 18
        icon_x = x + 12
        icon_y = y + (h - icon_r * 2) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(240, 240, 240) if is_white else QColor(50, 50, 55))
        p.drawEllipse(QRectF(icon_x, icon_y, icon_r * 2, icon_r * 2))
        p.setPen(QPen(QColor(0, 0, 0, 150), 1))
        p.drawEllipse(QRectF(icon_x, icon_y, icon_r * 2, icon_r * 2))

        sym = "♔" if is_white else "♚"
        p.setFont(QFont("Segoe UI Symbol", 14, QFont.Bold))
        p.setPen(QColor(30, 30, 30) if is_white else QColor(210, 210, 210))
        p.drawText(QRectF(icon_x, icon_y, icon_r * 2, icon_r * 2),
                   Qt.AlignCenter, sym)

        p.setPen(QColor(220, 220, 225))
        p.setFont(QFont("Inter", 12, QFont.Bold))
        p.drawText(QRectF(icon_x + icon_r * 2 + 10, y, w - 130, h / 2 + 4),
                   Qt.AlignVCenter | Qt.AlignLeft, name)

        p.setPen(QColor(140, 140, 155))
        p.setFont(QFont("Inter", 9))
        p.drawText(QRectF(icon_x + icon_r * 2 + 10, y + h / 2 - 4, w - 130, h / 2 + 4),
                   Qt.AlignVCenter | Qt.AlignLeft, engine_info)

        if abs(eval_cp) > 9000:
            txt = f"M{int(abs(eval_cp) - 10000)}"
        else:
            txt = f"{eval_cp / 100.0:+.1f}"

        pill_w = 60
        pill_h = 22
        pill_x = x + w - pill_w - 10
        pill_y = y + (h - pill_h) / 2

        if abs(eval_cp) > 9000:
            pill_bg = QColor(28, 165, 55, 200) if eval_cp > 0 else QColor(200, 45, 45, 200)
            pill_fg = QColor(255, 255, 255)
        elif eval_cp >= 0:
            pill_bg = QColor(245, 242, 235, 210)
            pill_fg = QColor(32, 30, 26)
        else:
            pill_bg = QColor(38, 38, 48, 210)
            pill_fg = QColor(220, 218, 210)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(QRectF(pill_x + 1, pill_y + 1, pill_w, pill_h), 10, 10)
        p.setBrush(pill_bg)
        p.drawRoundedRect(QRectF(pill_x, pill_y, pill_w, pill_h), 10, 10)

        p.setFont(QFont("Inter", 11, QFont.Bold))
        p.setPen(pill_fg)
        p.drawText(QRectF(pill_x, pill_y, pill_w, pill_h),
                   Qt.AlignCenter, txt)

    # ── Game-over helpers ─────────────────────────────────────
    def _draw_gameover_pill_v(self, p, ebx, by, ebw, bsz):
        epx, eph = max(40, ebw + 20), 24
        if "1-0" in self.game_result:
            txt, ety = "♔ 1-0", by + eph / 2 + 10
            epbg, epfg = QColor(255, 255, 255, 225), QColor(28, 28, 28)
        elif "0-1" in self.game_result:
            txt, ety = "♚ 0-1", by + bsz - eph / 2 - 10
            epbg, epfg = QColor(28, 28, 28, 235), QColor(228, 228, 228)
        else:
            txt, ety = "½-½", by + bsz / 2
            epbg, epfg = QColor(135, 125, 48, 235), QColor(255, 255, 255)
        epill = QRectF(ebx + (ebw - epx) / 2, ety - eph / 2, epx, eph)
        p.setFont(QFont("Inter", max(8, min(12, int(ebw * 0.3))), QFont.Bold))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawRoundedRect(epill.adjusted(1, 1, 1, 1), 10, 10)
        p.setBrush(epbg); p.drawRoundedRect(epill, 10, 10)
        p.setPen(epfg); p.drawText(epill, Qt.AlignCenter, txt)

    def _draw_gameover_pill_h(self, p, ebx, eby, ebw, ebh):
        pill_w, pill_h = max(50, ebh + 30), 24
        if "1-0" in self.game_result:
            txt, pill_x = "♔ 1-0", ebx + pill_w / 2 + 10
            pbg, pfg = QColor(255, 255, 255, 225), QColor(28, 28, 28)
        elif "0-1" in self.game_result:
            txt, pill_x = "♚ 0-1", ebx + ebw - pill_w / 2 - 10
            pbg, pfg = QColor(28, 28, 28, 235), QColor(228, 228, 228)
        else:
            txt, pill_x = "½-½", ebx + ebw / 2
            pbg, pfg = QColor(135, 125, 48, 235), QColor(255, 255, 255)
        pill = QRectF(pill_x - pill_w / 2, eby + (ebh - pill_h) / 2, pill_w, pill_h)
        p.setFont(QFont("Inter", 12, QFont.Bold))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawRoundedRect(pill.adjusted(1, 2, 1, 2), 11, 11)
        p.setBrush(pbg); p.drawRoundedRect(pill, 11, 11)
        p.setPen(pfg); p.drawText(pill, Qt.AlignCenter, txt)

    # ── Portrait ──────────────────────────────────────────────
    def _render_portrait(self, p):
        margin = 20
        bsz = self.w - 2 * margin
        bx, by = margin, margin + 45

        p.setPen(QColor(195, 195, 205))
        p.setFont(QFont("Inter", 22, QFont.Bold))
        p.drawText(QRectF(bx, margin, bsz, 35),
                   Qt.AlignLeft | Qt.AlignVCenter, f"♚ {self.black_name}")
        bimg = self.board_renderer.render(bsz)
        p.drawImage(QRectF(bx, by, bsz, bsz), bimg)
        wy = by + bsz + 10
        p.drawText(QRectF(bx, wy, bsz, 35),
                   Qt.AlignLeft | Qt.AlignVCenter, f"♔ {self.white_name}")

        ebx = bx; eby = wy + 45; ebh = 32; ebw = bsz; cr = 5
        p.setPen(QPen(QColor(50, 50, 58), 1.0))
        p.setBrush(QColor(16, 16, 20))
        p.drawRoundedRect(QRectF(ebx - 2, eby - 2, ebw + 4, ebh + 4), cr + 2, cr + 2)
        blk = QLinearGradient(ebx, eby, ebx + ebw, eby)
        blk.setColorAt(0.0, QColor(38, 38, 45))
        blk.setColorAt(1.0, QColor(58, 58, 66))
        p.setPen(Qt.NoPen); p.setBrush(blk)
        p.drawRoundedRect(QRectF(ebx, eby, ebw, ebh), cr, cr)

        ratio = self._cp2r(self.eval_cp)
        ww = max(0, min(ebw, int(ebw * ratio)))
        if ww > 0:
            wg = QLinearGradient(ebx, eby, ebx + ww, eby)
            wg.setColorAt(0.0, QColor(246, 243, 236))
            wg.setColorAt(1.0, QColor(230, 226, 216))
            p.setBrush(wg)
            path = QPainterPath()
            if ww >= ebw:
                path.addRoundedRect(QRectF(ebx, eby, ebw, ebh), cr, cr)
            elif ww < cr * 2:
                path.addRoundedRect(QRectF(ebx, eby, ww, ebh), cr, cr)
            else:
                path.moveTo(ebx + cr, eby); path.lineTo(ebx + ww, eby)
                path.lineTo(ebx + ww, eby + ebh)
                path.lineTo(ebx + cr, eby + ebh)
                path.quadTo(ebx, eby + ebh, ebx, eby + ebh - cr)
                path.lineTo(ebx, eby + cr)
                path.quadTo(ebx, eby, ebx + cr, eby); path.closeSubpath()
            p.drawPath(path)

        xdy = ebx + ww
        if 0 < ww < ebw:
            p.setPen(QPen(QColor(105, 100, 90, 150), 1.5))
            p.drawLine(QPointF(xdy, eby + 2), QPointF(xdy, eby + ebh - 2))

        if self.game_state == GAME_NORMAL:
            is_mate = abs(self.eval_cp) > 9000
            txt = (f"M{int(abs(self.eval_cp) - 10000)}" if is_mate
                   else f"{self.eval_cp / 100.0:+.1f}")
            p.setFont(QFont("Inter", 12, QFont.Bold))
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(txt) + 16
            pill_w, pill_h = max(tw, 32), 22
            pill_x = max(ebx + pill_w / 2 + 4,
                         min(ebx + ebw - pill_w / 2 - 4, xdy))
            pill = QRectF(pill_x - pill_w / 2, eby + (ebh - pill_h) / 2,
                          pill_w, pill_h)
            on_white = (pill_x <= ebx + ww) if 0 < ww < ebw else (self.eval_cp >= 0)
            if is_mate:
                pbg = QColor(28, 165, 55, 225) if self.eval_cp > 0 else QColor(205, 40, 40, 225)
                pfg = QColor(255, 255, 255)
            elif on_white:
                pbg, pfg = QColor(255, 255, 255, 210), QColor(32, 30, 26)
            else:
                pbg, pfg = QColor(20, 20, 28, 210), QColor(235, 232, 224)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 80))
            p.drawRoundedRect(pill.adjusted(1, 2, 1, 2), 11, 11)
            p.setBrush(pbg); p.drawRoundedRect(pill, 11, 11)
            p.setPen(QPen(QColor(255, 255, 255, 35), 0.8))
            p.drawRoundedRect(pill, 11, 11)
            p.setPen(pfg); p.drawText(pill, Qt.AlignCenter, txt)
        else:
            self._draw_gameover_pill_h(p, ebx, eby, ebw, ebh)

        mly = eby + ebh + 12
        mlh = self.h - mly - margin
        if mlh > 60:
            render_movelist_2col(p, bx, mly, bsz, mlh,
                                 self.move_list_text, self.current_move_index,
                                 self.move_qualities)

        if self.game_state != GAME_NORMAL:
            self._draw_gameover_banner(p, bx, by, bsz)

    # ── Landscape ─────────────────────────────────────────────
    def _render_landscape(self, p):
        margin = 20
        bsz = int(self.h * 0.92)
        by = (self.h - bsz) // 2

        ebw = max(32, int(bsz * 0.035))
        ebx = margin
        ratio = self._cp2r(self.eval_cp)
        wh = max(0, min(bsz, int(bsz * ratio)))

        # Eval bar background
        p.setPen(QPen(QColor(50, 50, 58), 1.0))
        p.setBrush(QColor(16, 16, 20))
        p.drawRoundedRect(QRectF(ebx - 2, by - 2, ebw + 4, bsz + 4), 7, 7)
        blk = QLinearGradient(ebx, by, ebx, by + bsz)
        blk.setColorAt(0.0, QColor(58, 58, 66))
        blk.setColorAt(0.5, QColor(44, 44, 52))
        blk.setColorAt(1.0, QColor(38, 38, 45))
        p.setPen(Qt.NoPen); p.setBrush(blk)
        p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5)

        if wh > 0:
            wt = by + bsz - wh
            wg = QLinearGradient(ebx, wt, ebx, by + bsz)
            wg.setColorAt(0.0, QColor(230, 226, 216))
            wg.setColorAt(0.4, QColor(238, 235, 226))
            wg.setColorAt(1.0, QColor(246, 243, 236))
            p.setBrush(wg)
            if wh >= bsz:
                p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5)
            elif wh < 10:
                p.drawRoundedRect(QRectF(ebx, wt, ebw, wh), 5, 5)
            else:
                path = QPainterPath()
                path.moveTo(ebx, wt); path.lineTo(ebx + ebw, wt)
                path.lineTo(ebx + ebw, by + bsz - 5)
                path.quadTo(ebx + ebw, by + bsz, ebx + ebw - 5, by + bsz)
                path.lineTo(ebx + 5, by + bsz)
                path.quadTo(ebx, by + bsz, ebx, by + bsz - 5)
                path.lineTo(ebx, wt); path.closeSubpath()
                p.drawPath(path)

        p.setPen(QPen(QColor(115, 175, 250, 60), 1, Qt.DashLine))
        p.drawLine(QPointF(ebx + 2, by + bsz / 2),
                   QPointF(ebx + ebw - 2, by + bsz / 2))

        bdy = by + bsz - wh
        if 0 < wh < bsz:
            p.setPen(QPen(QColor(105, 100, 90, 150), 1.5))
            p.drawLine(QPointF(ebx + 2, bdy), QPointF(ebx + ebw - 2, bdy))

        if self.game_state == GAME_NORMAL:
            is_mate = abs(self.eval_cp) > 9000
            txt = (f"M{int(abs(self.eval_cp) - 10000)}" if is_mate
                   else f"{self.eval_cp / 100.0:+.1f}")
            efsz = max(9, min(14, int(ebw * 0.36)))
            p.setFont(QFont("Inter", efsz, QFont.Bold))
            efm = p.fontMetrics()
            etw = efm.horizontalAdvance(txt) + 12
            epx, eph = max(etw, 30), 22
            ety = bdy if 0 < wh < bsz else by + bsz / 2
            ety = max(by + eph / 2 + 4, min(by + bsz - eph / 2 - 4, ety))
            epill = QRectF(ebx + (ebw - epx) / 2, ety - eph / 2, epx, eph)
            on_w = (ety >= by + bsz - wh) if 0 < wh < bsz else (self.eval_cp >= 0)
            if is_mate:
                epbg = QColor(28, 165, 55, 215) if self.eval_cp > 0 else QColor(205, 40, 40, 215)
                epfg = QColor(255, 255, 255)
            else:
                epbg = QColor(255, 255, 255, 195) if on_w else QColor(20, 20, 28, 205)
                epfg = QColor(32, 30, 26) if on_w else QColor(235, 232, 224)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 45))
            p.drawRoundedRect(epill.adjusted(1, 1, 1, 1), 10, 10)
            p.setBrush(epbg); p.drawRoundedRect(epill, 10, 10)
            p.setPen(epfg); p.drawText(epill, Qt.AlignCenter, txt)
        else:
            self._draw_gameover_pill_v(p, ebx, by, ebw, bsz)

        # Board
        bx_board = ebx + ebw + margin
        bimg = self.board_renderer.render(bsz)
        p.drawImage(QRectF(bx_board, by, bsz, bsz), bimg)

        # Right Panel
        mx = bx_board + bsz + margin
        mw = self.w - mx - margin

        if mw > 160:
            bar_h = 52
            gap = 8

            # Black Player Bar (Top)
            black_eval = -self.eval_cp
            self._draw_player_bar_v(p, mx, by, mw, bar_h,
                                    self.black_name, self.black_engine_info,
                                    black_eval, False)

            # Move List (Middle - full available height)
            ml_y = by + bar_h + gap
            ml_h = bsz - 2 * (bar_h + gap)
            ml_h = max(60, ml_h)

            render_movelist_2col(p, mx, ml_y, mw, ml_h,
                                 self.move_list_text, self.current_move_index,
                                 self.move_qualities)

            # White Player Bar (Bottom)
            white_y = by + bsz - bar_h
            white_eval = self.eval_cp
            self._draw_player_bar_v(p, mx, white_y, mw, bar_h,
                                    self.white_name, self.white_engine_info,
                                    white_eval, True)

        if self.game_state != GAME_NORMAL:
            self._draw_gameover_banner(p, bx_board, by, bsz, landscape=True)

    # ── Game-over banner ──────────────────────────────────────
    def _draw_gameover_banner(self, p, bx, by, bsz, landscape=False):
        if landscape:
            banner_h = int(self.h * 0.06)
            banner_y = by + bsz + 10
        else:
            banner_h = int(bsz * 0.08)
            banner_y = by + bsz - banner_h - 30
        banner = QRectF(bx, banner_y, bsz, banner_h)

        if self.game_state == GAME_CHECKMATE:
            w_wins = self.eval_cp > 0 or self.game_result == "1-0"
            bg = QColor(22, 135, 50, 205) if w_wins else QColor(185, 32, 32, 205)
            txt = (f"♔ CHECKMATE  {self.game_result or '1-0'}" if w_wins
                   else f"♚ CHECKMATE  {self.game_result or '0-1'}")
        else:
            bg = QColor(155, 135, 38, 195)
            detail = self.game_detail or ""
            txt = f"½-½  {detail}" if detail else "½-½  DRAW"

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawRoundedRect(banner.adjusted(2, 2, 2, 2), 6, 6)
        p.setBrush(bg)
        p.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
        p.drawRoundedRect(banner, 6, 6)
        p.setFont(QFont("Inter", max(10, int(banner_h * 0.45)), QFont.Bold))
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(banner, Qt.AlignCenter, txt)