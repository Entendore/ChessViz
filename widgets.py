"""Chess Video Maker Pro — Eval Bar, Promotion Widget, and Video Canvas"""
import math
import os
import chess
import logging
from PySide6.QtWidgets import QWidget, QSizePolicy, QHBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt, QRectF, Signal, QPropertyAnimation, QEasingCurve, Property, QPointF, QTimer
from PySide6.QtGui import QPainter, QColor, QFont, QImage, QLinearGradient, QRadialGradient, QPainterPath, QPen, QBrush

from constants import GAME_NORMAL, GAME_CHECKMATE, GAME_STALEMATE, GAME_DRAW, GAME_INSUFFICIENT


class EvalBarWidget(QWidget):
    """Professional evaluation bar with gradients, tick marks, center line,
    glassmorphism eval pill, smooth animation, and professional
    checkmate/draw indications."""

    # ── Design constants ───────────────────────────────────────────
    BAR_WIDTH       = 48
    PADDING         = 6
    CORNER_RADIUS   = 6
    TICK_MAJOR_W    = 6
    TICK_MINOR_W    = 3
    PILL_H          = 22
    PILL_RADIUS     = 11
    PILL_PAD_X      = 6

    # Colour palette
    CLR_OUTER_BG    = QColor(18, 18, 22)
    CLR_BORDER      = QColor(55, 55, 62)
    CLR_BLACK_TOP   = QColor(62, 62, 70)
    CLR_BLACK_MID   = QColor(48, 48, 55)
    CLR_BLACK_BOT   = QColor(40, 40, 47)
    CLR_WHITE_BOT   = QColor(248, 245, 238)
    CLR_WHITE_MID   = QColor(240, 237, 228)
    CLR_WHITE_TOP   = QColor(232, 228, 218)
    CLR_DIVIDER     = QColor(110, 105, 95, 160)
    CLR_CENTER_LINE = QColor(120, 180, 255, 90)
    CLR_TICK        = QColor(90, 90, 100, 100)
    CLR_TICK_LABEL  = QColor(140, 140, 155, 180)
    CLR_PILL_SHADOW = QColor(0, 0, 0, 70)
    CLR_MATE_GREEN  = QColor(30, 170, 60, 230)
    CLR_MATE_RED    = QColor(210, 45, 45, 230)

    # Game-state overlay colours
    CLR_CHECKMATE_WHITE_WIN = QColor(25, 140, 55, 220)
    CLR_CHECKMATE_BLACK_WIN = QColor(190, 35, 35, 220)
    CLR_DRAW_AMBER          = QColor(200, 160, 40, 220)
    CLR_DRAW_GRAY           = QColor(100, 100, 110, 200)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._eval_cp = 0.0
        self._anim_cp = 0.0
        self._game_state = GAME_NORMAL
        self._game_result = ""       # "1-0", "0-1", "½-½"
        self._game_detail = ""       # "Checkmate", "Stalemate", etc.
        self.setFixedWidth(self.BAR_WIDTH + 2 * self.PADDING)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumHeight(200)

        self._animation = QPropertyAnimation(self, b"anim_cp")
        self._anim_dur = 300
        self._animation.setDuration(300)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    # ── Game state API ─────────────────────────────────────────────
    def set_game_state(self, state, result="", detail=""):
        """Set the game state for professional overlay indication.

        state: one of GAME_NORMAL, GAME_CHECKMATE, GAME_STALEMATE,
               GAME_DRAW, GAME_INSUFFICIENT
        result: "1-0", "0-1", or "½-½"
        detail: "Checkmate", "Stalemate", "Insufficient Material", etc.
        """
        self._game_state = state
        self._game_result = result
        self._game_detail = detail
        self.update()

    def reset_game_state(self):
        """Reset to normal game state."""
        self._game_state = GAME_NORMAL
        self._game_result = ""
        self._game_detail = ""
        self.update()

    # ── Qt Property ────────────────────────────────────────────────
    def _get_ac(self):
        return self._anim_cp

    def _set_ac(self, v):
        self._anim_cp = v
        self.update()

    anim_cp = Property(float, _get_ac, _set_ac)

    def set_eval(self, cp):
        old = self._eval_cp
        self._eval_cp = cp
        # If game is over, snap without animation
        if self._game_state != GAME_NORMAL:
            self._anim_cp = float(cp)
            self.update()
            return
        if abs(cp) > 9000 or abs(old) > 9000 or self._anim_dur == 0:
            self._anim_cp = float(cp)
            self.update()
            return
        self._animation.stop()
        self._animation.setStartValue(self._anim_cp)
        self._animation.setEndValue(float(cp))
        self._animation.start()

    def set_anim_duration(self, ms):
        self._anim_dur = max(0, ms)
        self._animation.setDuration(self._anim_dur if self._anim_dur > 0 else 1)

    # ── Conversion ─────────────────────────────────────────────────
    @staticmethod
    def _cp_to_ratio(cp):
        if cp >= 9000:
            return 1.0
        if cp <= -9000:
            return 0.0
        return 1.0 / (1.0 + math.exp(-0.004 * max(-10000.0, min(10000.0, cp))))

    # ── Paint ──────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        W, H = self.width(), self.height()
        pad = self.PADDING
        cr  = self.CORNER_RADIUS
        bx, by = pad, pad
        bw, bh = W - 2 * pad, H - 2 * pad

        # ── 1. Outer frame with subtle shadow ──────────────────────
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(QRectF(1, 2, W - 1, H - 1), cr + 3, cr + 3)

        p.setPen(QPen(self.CLR_BORDER, 1.2))
        p.setBrush(self.CLR_OUTER_BG)
        p.drawRoundedRect(QRectF(0, 0, W, H), cr + 2, cr + 2)

        # ── 2. Black (dark) gradient — full bar background ─────────
        blk = QLinearGradient(bx, by, bx, by + bh)
        blk.setColorAt(0.0, self.CLR_BLACK_TOP)
        blk.setColorAt(0.5, self.CLR_BLACK_MID)
        blk.setColorAt(1.0, self.CLR_BLACK_BOT)
        p.setPen(Qt.NoPen)
        p.setBrush(blk)
        p.drawRoundedRect(QRectF(bx, by, bw, bh), cr, cr)

        # ── 3. White portion ───────────────────────────────────────
        ratio = self._cp_to_ratio(self._anim_cp)
        is_mate = abs(self._anim_cp) > 9000
        wh = max(0, min(bh, int(bh * ratio)))

        if wh > 0:
            wt = by + bh - wh   # y-top of white section
            wg = QLinearGradient(bx, wt, bx, by + bh)
            wg.setColorAt(0.0, self.CLR_WHITE_TOP)
            wg.setColorAt(0.4, self.CLR_WHITE_MID)
            wg.setColorAt(1.0, self.CLR_WHITE_BOT)
            p.setBrush(wg)

            if is_mate or wh >= bh:
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

        # ── 4. Centre line (eval = 0 indicator) ────────────────────
        centre_y = by + bh / 2.0
        p.setPen(QPen(self.CLR_CENTER_LINE, 1.0, Qt.DashLine))
        p.drawLine(QPointF(bx + 2, centre_y), QPointF(bx + bw - 2, centre_y))

        # ── 5. Tick marks ──────────────────────────────────────────
        p.setPen(Qt.NoPen)
        self._draw_ticks(p, bx, by, bw, bh)

        # ── 6. Divider line between white and black ────────────────
        bdy = by + bh - wh
        if 0 < wh < bh and not is_mate:
            p.setPen(QPen(self.CLR_DIVIDER, 1.5))
            p.drawLine(QPointF(bx + 2, bdy), QPointF(bx + bw - 2, bdy))

        # ── 7. Subtle inner highlight (top edge shine) ─────────────
        shine = QLinearGradient(bx, by, bx, by + 4)
        shine.setColorAt(0.0, QColor(255, 255, 255, 30))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(shine)
        p.drawRoundedRect(QRectF(bx, by, bw, 4), cr, cr)

        # ── 8. Eval pill (normal or mate) ──────────────────────────
        if self._game_state == GAME_NORMAL:
            self._draw_eval_pill(p, bx, by, bw, bh, wh, bdy, is_mate, W)

        # ── 9. Game state professional overlay ──────────────────────
        if self._game_state != GAME_NORMAL:
            self._draw_game_state_overlay(p, bx, by, bw, bh, W, H)

        p.end()

    # ── Tick marks ─────────────────────────────────────────────────
    def _draw_ticks(self, p, bx, by, bw, bh):
        major_cp = 100
        minor_cp = 50
        for cp_val in range(-900, 901, minor_cp):
            ratio = self._cp_to_ratio(cp_val)
            y = by + bh - ratio * bh
            if by + 4 > y or y > by + bh - 4:
                continue
            is_major = (cp_val % major_cp == 0)
            tw = self.TICK_MAJOR_W if is_major else self.TICK_MINOR_W
            alpha = 80 if is_major else 40
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, alpha))
            p.drawRect(QRectF(bx + bw - tw, y - 0.5, tw, 1.0))
            if is_major and cp_val % 200 == 0 and cp_val != 0:
                label = f"{cp_val // 100:+d}"
                fnt = QFont("Segoe UI", max(6, int(bw * 0.17)))
                p.setFont(fnt)
                p.setPen(QColor(180, 180, 200, 120))
                p.drawText(QRectF(bx + 1, y - 8, bw - self.TICK_MAJOR_W - 1, 12),
                           Qt.AlignLeft | Qt.AlignVCenter, label)

    # ── Eval pill ──────────────────────────────────────────────────
    def _draw_eval_pill(self, p, bx, by, bw, bh, wh, bdy, is_mate, W):
        is_mate_val = abs(self._eval_cp) > 9000
        txt = (f"M{int(abs(self._eval_cp) - 10000)}"
               if is_mate_val else f"{self._eval_cp / 100.0:+.1f}")

        fsz = max(8, min(12, int(bw * 0.27)))
        fnt = QFont("Segoe UI", fsz, QFont.Bold)
        p.setFont(fnt)
        fm = p.fontMetrics()
        th = fm.height()
        tw = fm.horizontalAdvance(txt) + self.PILL_PAD_X * 2 + 4
        pill_w = max(tw, 32)
        pill_h = self.PILL_H

        ty = bdy if 0 < wh < bh else (by + bh / 2.0 if is_mate else by + bh / 2.0)
        ty = max(by + pill_h / 2 + 4, min(by + bh - pill_h / 2 - 4, ty))

        pill = QRectF((W - pill_w) / 2, ty - pill_h / 2, pill_w, pill_h)
        on_white = (ty >= by + bh - wh) if 0 < wh < bh else (self._eval_cp >= 0)

        if is_mate_val:
            pbg = self.CLR_MATE_GREEN if self._eval_cp > 0 else self.CLR_MATE_RED
            pfg = QColor(255, 255, 255)
        else:
            if on_white:
                pbg = QColor(255, 255, 255, 215)
                pfg = QColor(35, 32, 28)
            else:
                pbg = QColor(22, 22, 30, 220)
                pfg = QColor(238, 234, 226)

        pr = self.PILL_RADIUS
        p.setPen(Qt.NoPen)
        p.setBrush(self.CLR_PILL_SHADOW)
        p.drawRoundedRect(pill.adjusted(1, 2, 1, 2), pr, pr)
        p.setBrush(pbg)
        p.setPen(QPen(QColor(255, 255, 255, 30) if on_white
                       else QColor(255, 255, 255, 15), 0.8))
        p.drawRoundedRect(pill, pr, pr)

        glass = QLinearGradient(pill.topLeft(), pill.bottomLeft())
        glass.setColorAt(0.0, QColor(255, 255, 255, 50))
        glass.setColorAt(0.5, QColor(255, 255, 255, 10))
        glass.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glass)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(pill, pr, pr)
        p.save()
        p.setClipPath(clip_path)
        p.drawRect(QRectF(pill.x(), pill.y(), pill.width(), pill.height() / 2))
        p.restore()

        p.setPen(pfg)
        p.setFont(fnt)
        p.drawText(pill, Qt.AlignCenter, txt)

        if is_mate_val:
            icon_fnt = QFont("Segoe UI Symbol", fsz - 1)
            p.setFont(icon_fnt)
            icon = "♔" if self._eval_cp > 0 else "♚"
            p.drawText(QRectF(pill.x() + 3, pill.y(), pill_w * 0.3, pill_h),
                       Qt.AlignCenter, icon)

    # ── Professional game state overlay ────────────────────────────
    def _draw_game_state_overlay(self, p, bx, by, bw, bh, W, H):
        """Draw professional checkmate/draw indication overlays."""
        state = self._game_state

        if state == GAME_CHECKMATE:
            self._draw_checkmate_overlay(p, bx, by, bw, bh, W, H)
        elif state in (GAME_STALEMATE, GAME_DRAW, GAME_INSUFFICIENT):
            self._draw_draw_overlay(p, bx, by, bw, bh, W, H, state)

    def _draw_checkmate_overlay(self, p, bx, by, bw, bh, W, H):
        """Professional checkmate indication:
        - Full color bar (green for winner, red for loser)
        - Large 'CHECKMATE' banner
        - Result (1-0 / 0-1)
        - Crown icon
        """
        white_wins = (self._eval_cp > 0) or (self._game_result == "1-0")

        # ── Colored overlay on the bar ─────────────────────────────
        p.setPen(Qt.NoPen)
        if white_wins:
            # Green tint over white portion
            ov = QColor(25, 160, 55, 50)
            p.setBrush(ov)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), self.CORNER_RADIUS,
                              self.CORNER_RADIUS)
        else:
            # Red tint over black portion
            ov = QColor(190, 35, 35, 50)
            p.setBrush(ov)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), self.CORNER_RADIUS,
                              self.CORNER_RADIUS)

        # ── Result banner in center ────────────────────────────────
        center_y = by + bh / 2.0

        # Banner background
        banner_h = min(80, max(50, int(bh * 0.12)))
        banner_w = W - 2 * self.PADDING
        banner = QRectF(self.PADDING, center_y - banner_h / 2, banner_w, banner_h)

        if white_wins:
            bg_color = self.CLR_CHECKMATE_WHITE_WIN
            crown = "♔"
        else:
            bg_color = self.CLR_CHECKMATE_BLACK_WIN
            crown = "♚"

        # Shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(banner.adjusted(2, 3, 2, 3), 8, 8)

        # Banner body
        p.setBrush(bg_color)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1.0))
        p.drawRoundedRect(banner, 8, 8)

        # Glass highlight
        glass = QLinearGradient(banner.topLeft(), banner.bottomLeft())
        glass.setColorAt(0.0, QColor(255, 255, 255, 50))
        glass.setColorAt(0.5, QColor(255, 255, 255, 10))
        glass.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glass)
        clip = QPainterPath()
        clip.addRoundedRect(banner, 8, 8)
        p.save()
        p.setClipPath(clip)
        p.drawRect(QRectF(banner.x(), banner.y(), banner.width(),
                          banner.height() / 2))
        p.restore()

        # Crown icon at top of banner
        crown_fnt = QFont("Segoe UI Symbol", max(10, int(banner_h * 0.35)))
        p.setFont(crown_fnt)
        p.setPen(QColor(255, 255, 255, 240))
        p.drawText(banner.adjusted(0, -2, 0, -banner_h * 0.35),
                   Qt.AlignCenter, crown)

        # "CHECKMATE" text
        cm_fnt = QFont("Segoe UI", max(7, int(banner_h * 0.22)), QFont.Bold)
        p.setFont(cm_fnt)
        p.setPen(QColor(255, 255, 255, 240))
        p.drawText(banner.adjusted(0, banner_h * 0.08, 0, 0),
                   Qt.AlignCenter, "CHECKMATE")

        # Result text (1-0 or 0-1)
        res_fnt = QFont("Segoe UI", max(8, int(banner_h * 0.25)), QFont.Bold)
        p.setFont(res_fnt)
        p.setPen(QColor(255, 255, 255, 220))
        result_txt = self._game_result or ("1-0" if white_wins else "0-1")
        p.drawText(banner.adjusted(0, banner_h * 0.35, 0, 0),
                   Qt.AlignCenter, result_txt)

        # ── Subtle pulsing border glow ─────────────────────────────
        glow_color = QColor(25, 200, 60, 30) if white_wins else QColor(220, 40, 40, 30)
        p.setPen(QPen(glow_color, 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(bx - 1, by - 1, bw + 2, bh + 2),
                          self.CORNER_RADIUS + 1, self.CORNER_RADIUS + 1)

    def _draw_draw_overlay(self, p, bx, by, bw, bh, W, H, state):
        """Professional draw indication:
        - 50/50 bar
        - '½-½' result
        - Draw type label
        - Amber/neutral color scheme
        """
        # ── Subtle amber overlay ───────────────────────────────────
        p.setPen(Qt.NoPen)
        ov = QColor(180, 150, 40, 25)
        p.setBrush(ov)
        p.drawRoundedRect(QRectF(bx, by, bw, bh), self.CORNER_RADIUS,
                          self.CORNER_RADIUS)

        # ── Center divider emphasis ────────────────────────────────
        center_y = by + bh / 2.0
        p.setPen(QPen(QColor(220, 190, 60, 140), 2.0))
        p.drawLine(QPointF(bx + 2, center_y), QPointF(bx + bw - 2, center_y))

        # ── Banner ─────────────────────────────────────────────────
        banner_h = min(90, max(55, int(bh * 0.13)))
        banner_w = W - 2 * self.PADDING
        banner = QRectF(self.PADDING, center_y - banner_h / 2, banner_w, banner_h)

        # Shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawRoundedRect(banner.adjusted(2, 3, 2, 3), 8, 8)

        # Banner body — amber/gray
        bg = self.CLR_DRAW_AMBER if state == GAME_STALEMATE else self.CLR_DRAW_GRAY
        p.setBrush(bg)
        p.setPen(QPen(QColor(255, 255, 255, 50), 1.0))
        p.drawRoundedRect(banner, 8, 8)

        # Glass highlight
        glass = QLinearGradient(banner.topLeft(), banner.bottomLeft())
        glass.setColorAt(0.0, QColor(255, 255, 255, 40))
        glass.setColorAt(0.5, QColor(255, 255, 255, 8))
        glass.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glass)
        clip = QPainterPath()
        clip.addRoundedRect(banner, 8, 8)
        p.save()
        p.setClipPath(clip)
        p.drawRect(QRectF(banner.x(), banner.y(), banner.width(),
                          banner.height() / 2))
        p.restore()

        # "½-½" result text
        res_fnt = QFont("Segoe UI", max(10, int(banner_h * 0.32)), QFont.Bold)
        p.setFont(res_fnt)
        p.setPen(QColor(255, 255, 255, 240))
        result_txt = self._game_result or "½-½"
        p.drawText(banner.adjusted(0, -banner_h * 0.1, 0, -banner_h * 0.2),
                   Qt.AlignCenter, result_txt)

        # Draw type label
        detail_map = {
            GAME_STALEMATE: "STALEMATE",
            GAME_INSUFFICIENT: "INSUFFICIENT\nMATERIAL",
            GAME_DRAW: "DRAW",
        }
        detail_txt = self._game_detail or detail_map.get(state, "DRAW")
        det_fnt = QFont("Segoe UI", max(6, int(banner_h * 0.17)))
        p.setFont(det_fnt)
        p.setPen(QColor(255, 255, 255, 190))
        p.drawText(banner.adjusted(0, banner_h * 0.28, 0, 0),
                   Qt.AlignCenter, detail_txt)

        # ── Subtle amber border glow ───────────────────────────────
        p.setPen(QPen(QColor(200, 170, 40, 35), 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(bx - 1, by - 1, bw + 2, bh + 2),
                          self.CORNER_RADIUS + 1, self.CORNER_RADIUS + 1)


# ── PromotionWidget ────────────────────────────────────────────────
class PromotionWidget(QWidget):
    piece_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.addWidget(QLabel("Promote to:"))
        self._btns = []
        for pt, sym in {chess.QUEEN: "♕", chess.ROOK: "♖",
                        chess.BISHOP: "♗", chess.KNIGHT: "♘"}.items():
            b = QPushButton(sym)
            b.setFont(QFont("Segoe UI Symbol", 20))
            b.setFixedSize(48, 40)
            b.clicked.connect(lambda _, p=pt: self._pick(p))
            lay.addWidget(b)
            self._btns.append((pt, b))
        self.hide()

    def show_for_color(self, color):
        bm = {chess.QUEEN: "♛", chess.ROOK: "♜", chess.BISHOP: "♝", chess.KNIGHT: "♞"}
        wm = {chess.QUEEN: "♕", chess.ROOK: "♖", chess.BISHOP: "♗", chess.KNIGHT: "♘"}
        s = bm if color == chess.BLACK else wm
        for pt, b in self._btns:
            b.setText(s[pt])
        self.show()

    def _pick(self, pt):
        self.piece_selected.emit(pt)
        self.hide()


# ── VideoCanvas ────────────────────────────────────────────────────
class VideoCanvas:
    """Renders a full video frame (board + eval bar + move list + overlays)."""

    def __init__(self, bw, ew, w=1920, h=1080, bg_color=QColor(30, 30, 32)):
        self.bw = bw
        self.ew = ew
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
        # Game state for professional indications
        self.game_state = GAME_NORMAL
        self.game_result = ""
        self.game_detail = ""

    @staticmethod
    def _cp2r(cp):
        if abs(cp) >= 9000:
            return 1.0 if cp > 0 else 0.0
        return 1.0 / (1.0 + math.exp(-0.004 * max(-10000, min(10000, cp))))

    def render(self):
        img = QImage(self.w, self.h, QImage.Format_ARGB32)
        img.fill(self.bg_color)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        margin = 40
        bsz = int(self.h * 0.85)
        by = (self.h - bsz) // 2

        # ── Professional eval bar for video ─────────────────────────
        ebw = max(32, int(bsz * 0.05))
        ebx = margin
        ratio = self._cp2r(self.eval_cp)
        wh = max(0, min(bsz, int(bsz * ratio)))

        # Outer frame
        p.setPen(QPen(QColor(55, 55, 62), 1.2))
        p.setBrush(QColor(18, 18, 22))
        p.drawRoundedRect(QRectF(ebx - 2, by - 2, ebw + 4, bsz + 4), 7, 7)

        # Black gradient
        blk = QLinearGradient(ebx, by, ebx, by + bsz)
        blk.setColorAt(0.0, QColor(62, 62, 70))
        blk.setColorAt(0.5, QColor(48, 48, 55))
        blk.setColorAt(1.0, QColor(40, 40, 47))
        p.setPen(Qt.NoPen)
        p.setBrush(blk)
        p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5)

        # White portion
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
        p.drawLine(QPointF(ebx + 2, by + bsz / 2),
                   QPointF(ebx + ebw - 2, by + bsz / 2))

        # Divider
        bdy = by + bsz - wh
        if 0 < wh < bsz:
            p.setPen(QPen(QColor(110, 105, 95, 160), 1.5))
            p.drawLine(QPointF(ebx + 2, bdy), QPointF(ebx + ebw - 2, bdy))

        # Tick marks
        for cp_val in range(-900, 901, 100):
            r = self._cp2r(cp_val)
            y = by + bsz - r * bsz
            if by + 4 > y or y > by + bsz - 4:
                continue
            is_major = cp_val % 200 == 0
            tw = 6 if is_major else 3
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 60 if is_major else 30))
            p.drawRect(QRectF(ebx + ebw - tw, y - 0.5, tw, 1.0))
            if is_major and cp_val % 400 == 0 and cp_val != 0:
                fnt = QFont("Segoe UI", max(7, int(ebw * 0.18)))
                p.setFont(fnt)
                p.setPen(QColor(170, 170, 190, 130))
                p.drawText(QRectF(ebx + 1, y - 7, ebw - 7, 12),
                           Qt.AlignLeft | Qt.AlignVCenter,
                           f"{cp_val // 100:+d}")

        # ── Game state overlay for video eval bar ──────────────────
        if self.game_state != GAME_NORMAL:
            self._draw_video_game_state(p, ebx, by, ebw, bsz, bdy, wh)
        else:
            # Normal eval text pill
            is_mate = abs(self.eval_cp) > 9000
            txt = (f"M{int(abs(self.eval_cp) - 10000)}" if is_mate
                   else f"{self.eval_cp / 100.0:+.1f}")
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
                epbg = QColor(30, 170, 60, 220) if self.eval_cp > 0 else QColor(210, 45, 45, 220)
                epfg = QColor(255, 255, 255)
            else:
                epbg = QColor(255, 255, 255, 200) if on_w else QColor(22, 22, 30, 210)
                epfg = QColor(35, 32, 28) if on_w else QColor(238, 234, 226)

            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 50))
            p.drawRoundedRect(epill.adjusted(1, 1, 1, 1), 10, 10)
            p.setBrush(epbg)
            p.drawRoundedRect(epill, 10, 10)
            p.setPen(epfg)
            p.drawText(epill, Qt.AlignCenter, txt)

        # ── Board ──────────────────────────────────────────────────
        bx_board = ebx + ebw + margin
        bimg = self.bw.render_to_image(bsz)
        p.drawImage(QRectF(bx_board, by, bsz, bsz), bimg)

        # ── Move list ──────────────────────────────────────────────
        mx = bx_board + bsz + margin
        mw = self.w - mx - margin
        if mw > 60:
            p.setBrush(QColor(40, 40, 40))
            p.drawRoundedRect(mx, by, mw, bsz, 8, 8)
            p.setPen(QColor(200, 200, 200))
            p.setFont(QFont("Consolas", 14))
            xo, yo, lh = 10, 15, 25
            for i, san in enumerate(self.move_list_text):
                if i == self.current_move_index:
                    p.setPen(QColor(100, 180, 255))
                else:
                    p.setPen(QColor(180, 180, 180))
                if i % 2 == 0:
                    p.drawText(QRectF(mx + xo, by + yo, 40, lh),
                               Qt.AlignLeft, f"{i // 2 + 1}.")
                    p.drawText(QRectF(mx + xo + 40, by + yo, 70, lh),
                               Qt.AlignLeft, san)
                else:
                    p.drawText(QRectF(mx + xo + 120, by + yo, 70, lh),
                               Qt.AlignLeft, san)
                if i % 2 == 1:
                    yo += lh
                if yo > bsz - 20:
                    break

        # ── Player names ───────────────────────────────────────────
        p.setPen(QColor(200, 200, 200))
        p.setFont(QFont("Segoe UI", int(self.h * 0.025), QFont.Bold))
        name_x = bx_board
        p.drawText(QRectF(name_x, by + bsz + 10, bsz / 2, 40),
                   Qt.AlignLeft | Qt.AlignVCenter, self.white_name)
        p.drawText(QRectF(name_x, by - 50, bsz / 2, 40),
                   Qt.AlignLeft | Qt.AlignVCenter, self.black_name)

        # ── Game result banner on video ────────────────────────────
        if self.game_state != GAME_NORMAL:
            self._draw_video_result_banner(p, bx_board, by, bsz)

        # ── Overlays ───────────────────────────────────────────────
        for ov in self.overlays:
            if os.path.exists(ov['path']):
                oi = QImage(ov['path'])
                if not oi.isNull():
                    p.drawImage(QRectF(ov['x'], ov['y'], ov['w'], ov['h']), oi)

        p.end()
        return img

    # ── Video: game state overlay on eval bar ──────────────────────
    def _draw_video_game_state(self, p, ebx, by, ebw, bsz, bdy, wh):
        """Draw professional game-state overlay on the video eval bar."""
        if self.game_state == GAME_CHECKMATE:
            white_wins = self.eval_cp > 0 or self.game_result == "1-0"
            # Colored tint
            p.setPen(Qt.NoPen)
            tint = QColor(25, 160, 55, 40) if white_wins else QColor(190, 35, 35, 40)
            p.setBrush(tint)
            p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5)

            # Center banner
            center_y = by + bsz / 2
            bh_banner = max(40, int(bsz * 0.10))
            banner = QRectF(ebx - 4, center_y - bh_banner / 2, ebw + 8, bh_banner)
            bg = QColor(25, 140, 55, 220) if white_wins else QColor(190, 35, 35, 220)
            p.setBrush(QColor(0, 0, 0, 70))
            p.drawRoundedRect(banner.adjusted(2, 2, 2, 2), 6, 6)
            p.setBrush(bg)
            p.setPen(QPen(QColor(255, 255, 255, 50), 0.8))
            p.drawRoundedRect(banner, 6, 6)

            # Result text
            fsz = max(8, int(bh_banner * 0.4))
            p.setFont(QFont("Segoe UI", fsz, QFont.Bold))
            p.setPen(QColor(255, 255, 255))
            res = self.game_result or ("1-0" if white_wins else "0-1")
            p.drawText(banner, Qt.AlignCenter, res)

            # Crown
            crown = "♔" if white_wins else "♚"
            p.setFont(QFont("Segoe UI Symbol", max(7, int(bh_banner * 0.3))))
            p.drawText(QRectF(banner.x(), banner.y() - bh_banner * 0.5,
                              banner.width(), bh_banner * 0.5),
                       Qt.AlignCenter, crown)

            # Border glow
            glow = QColor(25, 200, 60, 50) if white_wins else QColor(220, 40, 40, 50)
            p.setPen(QPen(glow, 2.0))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(ebx - 2, by - 2, ebw + 4, bsz + 4), 6, 6)

        elif self.game_state in (GAME_STALEMATE, GAME_DRAW, GAME_INSUFFICIENT):
            # Amber tint
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(180, 150, 40, 20))
            p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5)

            # Center divider emphasis
            center_y = by + bsz / 2
            p.setPen(QPen(QColor(220, 190, 60, 130), 2.0))
            p.drawLine(QPointF(ebx + 2, center_y), QPointF(ebx + ebw - 2, center_y))

            # Banner
            bh_banner = max(50, int(bsz * 0.12))
            banner = QRectF(ebx - 4, center_y - bh_banner / 2, ebw + 8, bh_banner)
            bg = QColor(180, 150, 40, 210) if self.game_state == GAME_STALEMATE \
                else QColor(100, 100, 110, 200)
            p.setBrush(QColor(0, 0, 0, 60))
            p.drawRoundedRect(banner.adjusted(2, 2, 2, 2), 6, 6)
            p.setBrush(bg)
            p.setPen(QPen(QColor(255, 255, 255, 45), 0.8))
            p.drawRoundedRect(banner, 6, 6)

            # Result
            fsz = max(8, int(bh_banner * 0.35))
            p.setFont(QFont("Segoe UI", fsz, QFont.Bold))
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(banner.x(), banner.y(), banner.width(),
                              banner.height() * 0.55),
                       Qt.AlignCenter, self.game_result or "½-½")

            # Detail
            detail_map = {
                GAME_STALEMATE: "STALEMATE",
                GAME_INSUFFICIENT: "INSUFF.",
                GAME_DRAW: "DRAW",
            }
            det = self.game_detail or detail_map.get(self.game_state, "DRAW")
            p.setFont(QFont("Segoe UI", max(6, int(bh_banner * 0.2))))
            p.setPen(QColor(255, 255, 255, 180))
            p.drawText(QRectF(banner.x(), banner.y() + banner.height() * 0.5,
                              banner.width(), banner.height() * 0.5),
                       Qt.AlignCenter, det)

            # Border glow
            p.setPen(QPen(QColor(200, 170, 40, 30), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(ebx - 2, by - 2, ebw + 4, bsz + 4), 6, 6)

    # ── Video: result banner on board ──────────────────────────────
    def _draw_video_result_banner(self, p, bx, by, bsz):
        """Draw a professional result banner overlaid on the video frame."""
        banner_h = int(self.h * 0.06)
        banner_y = by + bsz + 55
        banner_w = bsz
        banner = QRectF(bx, banner_y, banner_w, banner_h)

        if self.game_state == GAME_CHECKMATE:
            white_wins = self.eval_cp > 0 or self.game_result == "1-0"
            if white_wins:
                bg = QColor(25, 140, 55, 210)
                txt = f"♔ CHECKMATE  {self.game_result or '1-0'}"
            else:
                bg = QColor(190, 35, 35, 210)
                txt = f"♚ CHECKMATE  {self.game_result or '0-1'}"
        else:
            bg = QColor(160, 140, 40, 200)
            detail = self.game_detail or ""
            txt = f"½-½  {detail}" if detail else "½-½  DRAW"

        # Shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawRoundedRect(banner.adjusted(2, 2, 2, 2), 6, 6)

        # Body
        p.setBrush(bg)
        p.setPen(QPen(QColor(255, 255, 255, 50), 1.0))
        p.drawRoundedRect(banner, 6, 6)

        # Text
        fsz = max(10, int(banner_h * 0.45))
        p.setFont(QFont("Segoe UI", fsz, QFont.Bold))
        p.setPen(QColor(255, 255, 255, 240))
        p.drawText(banner, Qt.AlignCenter, txt)