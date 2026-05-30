#!/usr/bin/env python3
"""Chess board widget — rendering, animation, move list."""

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
    ANIM_SPEED_DEFAULT, ANIM_FPS, THEMES, MOVE_LIST_COLORS,
    LayoutMode, MIN_MOVE_PANEL_W, MAX_MOVE_PANEL_W,
    MIN_MOVE_PANEL_H, MAX_MOVE_PANEL_H,
)
from utils import get_render_assets, ease_out_cubic, log, fix_stride, HAS_CUPY

# ── Coordinate conversion helpers ──────────────────────────────────────────

def _sq_to_rc(sq, flipped=False):
    """Convert a chess square to (row, col) screen coordinates."""
    rank = chess.square_rank(sq)
    file = chess.square_file(sq)
    if flipped:
        return rank, 7 - file
    return 7 - rank, file


def _rc_to_sq(r, c, flipped=False):
    """Convert (row, col) screen coordinates to a chess square."""
    if flipped:
        return chess.square(7 - c, r)
    return chess.square(c, 7 - r)


def _engine_rc_to_screen_rc(eng_r, eng_c, flipped=False):
    """Convert engine (non-flipped) screen coords to display screen coords."""
    sq = chess.square(eng_c, 7 - eng_r)
    return _sq_to_rc(sq, flipped)


def _screen_rc_to_engine_rc(screen_r, screen_c, flipped=False):
    """Convert display screen coords to engine (non-flipped) screen coords."""
    sq = _rc_to_sq(screen_r, screen_c, flipped)
    return 7 - chess.square_rank(sq), chess.square_file(sq)


# ── Chess Board Widget ─────────────────────────────────────────────────────

class ChessBoardWidget(QWidget):
    move_made = Signal(str)

    def __init__(self, engine, sound_mgr, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.snd = sound_mgr
        self.selected = None
        self.legal_targets = []
        self.legal_targets_set = set()
        self.setFixedSize(SQ_SIZE * 8, SQ_SIZE * 8)

        self.flipped = False
        self.auto_playing = False

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

        self.current_theme = THEMES["Midnight"]
        self.show_arrow = True

    # ── Legal targets sync ──────────────────────────────────────────────

    def _set_legal_targets(self, targets):
        """Set legal targets list and keep the set in sync for O(1) lookup."""
        self.legal_targets = targets
        self.legal_targets_set = set(targets)

    # ── Flip ────────────────────────────────────────────────────────────

    def flip(self):
        """Toggle the board orientation."""
        self.flipped = not self.flipped
        # If a square is programmatically selected, update its screen coords
        if self.selected is not None:
            sr, sc = self.selected
            sq = _rc_to_sq(sr, sc, not self.flipped)
            self.selected = _sq_to_rc(sq, self.flipped)
            eng_r, eng_c = _screen_rc_to_engine_rc(self.selected[0], self.selected[1], self.flipped)
            eng_targets = self.engine.legal_moves(eng_r, eng_c)
            self._set_legal_targets([
                _engine_rc_to_screen_rc(et_r, et_c, self.flipped)
                for et_r, et_c in eng_targets
            ])
        else:
            self._set_legal_targets([])
        self.update()

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
                'piece_obj': self.anim_piece_obj,
                'captured': self.anim_captured,
                'progress': t_eased}

    # ── Paint ───────────────────────────────────────────────────────────

    def paintEvent(self, e):
        chk = self.engine.check_squares()
        screen_check = [_engine_rc_to_screen_rc(cr, cc, self.flipped) for cr, cc in chk]

        screen_last_move = None
        if self.engine.last_move:
            (fr, fc), (tr, tc) = self.engine.last_move
            screen_last_move = (
                _engine_rc_to_screen_rc(fr, fc, self.flipped),
                _engine_rc_to_screen_rc(tr, tc, self.flipped),
            )

        img = self.render_frame(
            self.engine.board, screen_last_move,
            self.selected, self.legal_targets_set,
            check_squares=screen_check, anim_state=self._get_anim_state(),
            theme=self.current_theme, show_arrow=self.show_arrow,
            flipped=self.flipped)
        pix = QPixmap.fromImage(img)
        painter = QPainter(self)
        painter.drawPixmap(0, 0, pix)
        painter.end()

    # ── Static rendering ────────────────────────────────────────────────

    @staticmethod
    def render_frame(board, last_move=None, selected=None, legal_targets=None,
                     text_overlay="", check_squares=None, anim_state=None,
                     sq_size=SQ_SIZE, show_arrow=True, theme=None,
                     highlight_last_move=True, show_coords=True,
                     flipped=False):
        if theme is None:
            theme = THEMES["Midnight"]
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

        # ── 1. Squares, highlights, legal targets ───────────────────────
        for sq in chess.SQUARES:
            r, c = _sq_to_rc(sq, flipped)
            x, y = c * sz, r * sz
            is_light = (r + c) % 2 == 0
            color = theme.light_sq if is_light else theme.dark_sq
            p.fillRect(x, y, sz, sz, color)
            if highlight_last_move and last_move and (r, c) in last_move:
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

        # ── 2. Stationary pieces ────────────────────────────────────────
        for sq in chess.SQUARES:
            r, c = _sq_to_rc(sq, flipped)
            if (r, c) in skip_sq:
                continue
            piece = board.piece_at(sq)
            if piece:
                ChessBoardWidget._draw_piece(p, piece, r, c, sz, font_piece)

        # ── 3. Captured piece fade-out ──────────────────────────────────
        if anim_state and anim_state.get('captured', '.') != '.':
            tr, tc_ = anim_state['to']
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

        # ── 4. Arrow (AFTER pieces, BEFORE animated piece) ──────────────
        if show_arrow and last_move:
            (fr, fc), (tr, tc) = last_move
            ChessBoardWidget._draw_arrow(
                p, fc * sz + sz // 2, fr * sz + sz // 2,
                tc * sz + sz // 2, tr * sz + sz // 2,
                theme.arrow_clr, sz)

        # ── 5. Animated piece ───────────────────────────────────────────
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

        # ── 6. Coordinates ──────────────────────────────────────────────
        if show_coords:
            p.setFont(font_coord)
            coord_margin = max(3, int(sz * 0.04))
            coord_sz = max(12, sz // 5)
            for c_idx in range(8):
                file_idx = (7 - c_idx) if flipped else c_idx
                is_light = (7 + c_idx) % 2 == 0
                col = theme.dark_sq if is_light else theme.light_sq
                p.setPen(col)
                p.drawText(QRect(c_idx * sz + sz - coord_sz - coord_margin,
                                 7 * sz + coord_margin, coord_sz, coord_sz),
                           Qt.AlignCenter, FILES_STR[file_idx])
            for r_idx in range(8):
                rank_idx = r_idx if flipped else (7 - r_idx)
                is_light = r_idx % 2 == 0
                col = theme.dark_sq if is_light else theme.light_sq
                p.setPen(col)
                p.drawText(QRect(coord_margin, r_idx * sz + coord_margin,
                                 coord_sz, coord_sz),
                           Qt.AlignCenter, RANKS_STR[rank_idx])

        # ── 7. Text overlay ─────────────────────────────────────────────
        if text_overlay:
            p.fillRect(0, sz * 4 - 28, sz * 8, 56, QColor(0, 0, 0, 200))
            p.setPen(Qt.white)
            p.setFont(QFont("Sans", max(12, sz // 4), QFont.Bold))
            p.drawText(QRect(0, sz * 4 - 28, sz * 8, 56),
                       Qt.AlignCenter, text_overlay)
        p.end()
        return img

    # ── Move List Panel Rendering ───────────────────────────────────────

    @staticmethod
    def render_move_list(moves_san, current_idx=-1, width=240, height=544,
                         puzzle_info=None, colors=None, status_text=""):
        if colors is None:
            colors = MOVE_LIST_COLORS

        img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        bg = QColor(*colors['bg'][:3])
        img.fill(bg)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        margin = max(8, width // 24)
        line_h = max(18, min(26, height // 22))
        header_h = max(32, height // 14)

        # ── Header ──
        p.setFont(QFont("Sans", max(10, line_h - 4), QFont.Bold))
        p.setPen(QColor(*colors['accent'][:3]))
        header_text = "Puzzle"
        if puzzle_info and puzzle_info.get('name'):
            header_text = puzzle_info['name'][:30]
        p.drawText(QRect(margin, 4, width - 2 * margin, header_h - 4),
                   Qt.AlignVCenter | Qt.AlignLeft, header_text)

        sep_y = header_h
        p.setPen(QPen(QColor(*colors['border'][:3]), 1))
        p.drawLine(margin, sep_y, width - margin, sep_y)

        # ── Attributes ──
        info_y = sep_y + 4
        if puzzle_info:
            info_parts = []
            rating = puzzle_info.get('rating', 0)
            if rating:
                try:
                    r_val = int(float(rating))
                    stars = "★" * min(5, max(1, r_val // 500))
                    info_parts.append(f"Difficulty: {stars}")
                except (ValueError, TypeError):
                    pass
            themes = puzzle_info.get('themes', '')
            if themes:
                theme_tags = themes.split()[:2]
                info_parts.append(' '.join(theme_tags))
            if info_parts:
                p.setFont(QFont("Sans", max(8, line_h - 8)))
                p.setPen(QColor(*colors['dim'][:3]))
                p.drawText(QRect(margin, info_y, width - 2 * margin, line_h - 2),
                           Qt.AlignLeft, '  ·  '.join(info_parts))
                info_y += line_h

        # ── Moves ──
        y = info_y + 4
        p.setFont(QFont("Monospace", max(9, line_h - 6)))

        half_w = (width - 2 * margin - 36) // 2
        num_w = 32

        for i in range(0, max(len(moves_san), 1), 2):
            if y + line_h > height - (line_h * 2) - margin:
                if i < len(moves_san):
                    p.setPen(QColor(*colors['dim'][:3]))
                    p.drawText(QRect(margin, y, width - 2 * margin, line_h),
                               Qt.AlignLeft, "…")
                break

            move_num = i // 2 + 1
            white_move = moves_san[i] if i < len(moves_san) else ""
            black_move = moves_san[i + 1] if i + 1 < len(moves_san) else ""

            p.setPen(QColor(*colors['dim'][:3]))
            p.drawText(QRect(margin, y, num_w, line_h),
                       Qt.AlignRight | Qt.AlignVCenter, f"{move_num}.")

            if i == current_idx:
                p.fillRect(QRect(margin + num_w + 2, y, half_w, line_h),
                           QColor(colors['accent'][0], colors['accent'][1],
                                  colors['accent'][2], 35))
                p.setPen(QColor(*colors['accent'][:3]))
            else:
                p.setPen(QColor(*colors['text'][:3]))
            p.drawText(QRect(margin + num_w + 4, y, half_w, line_h),
                       Qt.AlignLeft | Qt.AlignVCenter, white_move)

            x_black = margin + num_w + half_w + 6
            if i + 1 == current_idx:
                p.fillRect(QRect(x_black - 2, y, half_w, line_h),
                           QColor(colors['accent'][0], colors['accent'][1],
                                  colors['accent'][2], 35))
                p.setPen(QColor(*colors['accent'][:3]))
            else:
                p.setPen(QColor(*colors['text'][:3]))
            p.drawText(QRect(x_black, y, half_w, line_h),
                       Qt.AlignLeft | Qt.AlignVCenter, black_move)

            y += line_h

        # ── Status Indicator ──
        if status_text:
            p.setPen(QPen(QColor(*colors['border'][:3]), 1))
            p.drawLine(margin, height - line_h - 12, width - margin, height - line_h - 12)
            p.setFont(QFont("Sans", max(9, line_h - 6), QFont.Bold))
            p.setPen(QColor(*colors['accent'][:3]))
            p.drawText(QRect(margin, height - line_h - 8, width - 2 * margin, line_h),
                       Qt.AlignLeft, f"▶ {status_text}")

        p.end()
        return img

    # ── Layout compositing ──────────────────────────────────────────────

    @staticmethod
    def render_layout(board_img, moves_san, current_move_idx,
                      layout_mode, target_w, target_h, bg_color,
                      sq_size, puzzle_info=None, status_text="",
                      move_list_visible=True):
        if not move_list_visible or layout_mode == LayoutMode.BOARD_ONLY:
            return board_img

        colors = MOVE_LIST_COLORS
        bw, bh = sq_size * 8, sq_size * 8

        if layout_mode == LayoutMode.BOARD_MOVES_RIGHT:
            panel_w = max(MIN_MOVE_PANEL_W, min(MAX_MOVE_PANEL_W, int(bw * 0.38)))
            remaining_w = target_w - bw
            if remaining_w < panel_w:
                panel_w = max(80, remaining_w)
            if panel_w < 80:
                return board_img

            panel_img = ChessBoardWidget.render_move_list(
                moves_san, current_move_idx, panel_w, bh,
                puzzle_info, colors, status_text)

            result = QImage(target_w, target_h, QImage.Format_ARGB32_Premultiplied)
            result.fill(QColor(*bg_color[:3]))
            rp = QPainter(result)
            rp.setRenderHint(QPainter.Antialiasing)

            total_w = bw + panel_w
            offset_x = (target_w - total_w) // 2
            offset_y = (target_h - bh) // 2

            rp.drawImage(offset_x, offset_y, board_img)
            rp.drawImage(offset_x + bw, offset_y, panel_img)

            rp.setPen(QPen(QColor(*colors['border'][:3]), 1))
            rp.drawLine(offset_x + bw, offset_y, offset_x + bw, offset_y + bh)
            rp.end()
            return result

        elif layout_mode == LayoutMode.BOARD_MOVES_BOTTOM:
            panel_h = max(MIN_MOVE_PANEL_H, min(MAX_MOVE_PANEL_H, int(bh * 0.28)))
            remaining_h = target_h - bh
            if remaining_h < panel_h:
                panel_h = max(60, remaining_h)
            if panel_h < 60:
                return board_img

            panel_w = bw
            panel_img = ChessBoardWidget.render_move_list(
                moves_san, current_move_idx, panel_w, panel_h,
                puzzle_info, colors, status_text)

            result = QImage(target_w, target_h, QImage.Format_ARGB32_Premultiplied)
            result.fill(QColor(*bg_color[:3]))
            rp = QPainter(result)
            rp.setRenderHint(QPainter.Antialiasing)

            total_h = bh + panel_h
            offset_x = (target_w - bw) // 2
            offset_y = (target_h - total_h) // 2

            rp.drawImage(offset_x, offset_y, board_img)
            rp.drawImage(offset_x, offset_y + bh, panel_img)

            rp.setPen(QPen(QColor(*colors['border'][:3]), 1))
            rp.drawLine(offset_x, offset_y + bh, offset_x + bw, offset_y + bh)
            rp.end()
            return result

        return board_img

    # ── Card rendering ──────────────────────────────────────────────────

    @staticmethod
    def render_card(text, bg="#1a1b26", fg="#c0caf5", w=544, h=544,
                    width=None, height=None, font_size=36, sub_text="",
                    bg_color=None, fg_color=None):
        bg_val = bg_color or bg
        fg_val = fg_color or fg
        w_val = width if width is not None else w
        h_val = height if height is not None else h
        img = QImage(w_val, h_val, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(bg_val))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
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
            shadow = QPainterPath(path); shadow.translate(1.5, 2.0)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 50)); p.drawPath(shadow)
            olw = max(1.2, sz * 0.028)
            p.setPen(QPen(QColor(30, 30, 30), olw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QColor(255, 255, 255)); p.drawPath(path)
        else:
            shadow = QPainterPath(path); shadow.translate(1.5, 2.0)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 60)); p.drawPath(shadow)
            olw = max(0.8, sz * 0.018)
            p.setPen(QPen(QColor(10, 10, 10), olw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QColor(40, 40, 40)); p.drawPath(path)

    # ── Arrow drawing ───────────────────────────────────────────────────

    @staticmethod
    def _draw_arrow(painter, fx, fy, tx, ty, color, sz):
        dx = tx - fx; dy = ty - fy
        dist = max(1, math.hypot(dx, dy)); margin = sz * 0.22
        fx2 = fx + dx * margin / dist; fy2 = fy + dy * margin / dist
        tx2 = tx - dx * margin / dist; ty2 = ty - dy * margin / dist
        painter.setPen(QPen(color, max(2, sz // 20), Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(int(fx2), int(fy2), int(tx2), int(ty2))
        angle = math.atan2(dy, dx); a_sz = sz * 0.22
        p1x = tx2 - a_sz * math.cos(angle - 0.45); p1y = ty2 - a_sz * math.sin(angle - 0.45)
        p2x = tx2 - a_sz * math.cos(angle + 0.45); p2y = ty2 - a_sz * math.sin(angle + 0.45)
        tri = QPolygonF([QPointF(tx2, ty2), QPointF(p1x, p1y), QPointF(p2x, p2y)])
        painter.setBrush(color); painter.setPen(Qt.NoPen); painter.drawPolygon(tri)

    # ── QImage ↔ NumPy ─────────────────────────────────────────────────

    @staticmethod
    def qimage_to_np(img):
        img2 = img.convertToFormat(QImage.Format_RGB888)
        ptr = img2.constBits()
        if hasattr(ptr, 'setsize'): ptr.setsize(img2.sizeInBytes())
        w = img2.width(); h = img2.height(); bpl = img2.bytesPerLine()
        raw = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl)).copy()
        if bpl == w * 3: return raw.reshape((h, w, 3))
        return fix_stride(raw, w, h, bpl)

    @staticmethod
    def qimage_to_np_batch(images, use_gpu=False):
        if not images: return np.empty((0, 0, 0, 3), dtype=np.uint8)
        arrays = [ChessBoardWidget.qimage_to_np(im) for im in images]
        stack = np.stack(arrays)
        if use_gpu and HAS_CUPY:
            import cupy as _cp; return _cp.asarray(stack)
        return stack