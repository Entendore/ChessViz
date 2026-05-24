"""
Two-column move list rendering with move-quality colour badges.
Used by both the live GUI widget and the video exporter.
"""

import math
from PySide6.QtGui import (
    QPainter, QColor, QFont, QLinearGradient, QPainterPath, QPen,
)
from PySide6.QtCore import Qt, QRectF, QPointF
from constants import (
    MQ_COLORS, MQ_SYMBOLS, MQ_GOOD, MQ_BEST, MQ_VIDEO_COLORS, MQ_BG_COLORS,
    MQ_SHOW_BADGE,
)


def render_movelist_2col(p, mx, my, mw, mh,
                         move_list_text, current_move_index,
                         move_qualities=None):
    """Render move list; *move_qualities* is a parallel list of MQ_* strings."""
    if mw < 160 or mh < 80:
        return
    qualities = move_qualities or [MQ_GOOD] * len(move_list_text)

    # ── Panel ─────────────────────────────────────────────────
    p.setPen(QPen(QColor(48, 48, 56), 1.0))
    p.setBrush(QColor(22, 22, 26))
    p.drawRoundedRect(QRectF(mx, my, mw, mh), 8, 8)

    # ── Header ────────────────────────────────────────────────
    hh = 34
    hr = QRectF(mx + 1, my + 1, mw - 2, hh)
    hg = QLinearGradient(hr.topLeft(), hr.bottomLeft())
    hg.setColorAt(0.0, QColor(48, 48, 56))
    hg.setColorAt(1.0, QColor(38, 38, 44))
    p.setPen(Qt.NoPen); p.setBrush(hg)
    cr = 7
    hp = QPainterPath()
    hp.moveTo(hr.left(), hr.bottom())
    hp.lineTo(hr.left(), hr.top() + cr)
    hp.quadTo(hr.left(), hr.top(), hr.left() + cr, hr.top())
    hp.lineTo(hr.right() - cr, hr.top())
    hp.quadTo(hr.right(), hr.top(), hr.right(), hr.top() + cr)
    hp.lineTo(hr.right(), hr.bottom()); hp.closeSubpath()
    p.drawPath(hp)

    p.setFont(QFont("Inter", 10, QFont.Bold))
    p.setPen(QColor(165, 170, 185))
    p.drawText(QRectF(mx + 14, my + 1, mw - 28, hh),
               Qt.AlignVCenter | Qt.AlignLeft, "♟  MOVES")
    p.setPen(QPen(QColor(58, 58, 68), 0.8))
    p.drawLine(QPointF(mx + 8, my + hh + 1), QPointF(mx + mw - 8, my + hh + 1))

    # ── Build pairs ───────────────────────────────────────────
    pairs = []
    i = 0
    while i < len(move_list_text):
        num = i // 2 + 1
        wm = move_list_text[i]
        bm = move_list_text[i + 1] if i + 1 < len(move_list_text) else None
        wq = qualities[i] if i < len(qualities) else MQ_GOOD
        bq = qualities[i + 1] if i + 1 < len(qualities) else MQ_GOOD
        pairs.append((num, wm, bm, i, i + 1 if bm is not None else -1, wq, bq))
        i += 2

    if not pairs:
        p.setFont(QFont("Inter", 9))
        p.setPen(QColor(85, 85, 105))
        p.drawText(QRectF(mx, my + hh, mw, mh - hh), Qt.AlignCenter, "No moves yet")
        return

    # ── Layout ────────────────────────────────────────────────
    pad_x, pad_top = 10, 6
    line_h = 26
    content_y = my + hh + pad_top
    content_h = mh - hh - pad_top * 2
    rows_avail = max(1, int(content_h / line_h))
    col_gap = 16
    min_col_w = 160
    max_cols_w = max(1, int((mw - pad_x * 2 + col_gap) / (min_col_w + col_gap)))
    req_cols = 1
    if len(pairs) > rows_avail:
        req_cols = math.ceil(len(pairs) / rows_avail)
    
    # FORCE strictly 2 columns (1 pair of White/Black) instead of 4 columns
    num_cols = 1
    
    ppc = max(1, math.ceil(len(pairs) / num_cols))
    col_w = (mw - pad_x * 2 - col_gap * (num_cols - 1)) / num_cols
    start_pair = 0
    if current_move_index >= 0:
        cp = current_move_index // 2
        if cp >= rows_avail:
            start_pair = max(0, min(cp - rows_avail + 1, len(pairs) - rows_avail))

    for ci in range(num_cols):
        cx = mx + pad_x + ci * (col_w + col_gap)
        start = ci * ppc + start_pair
        end = min(start + ppc, len(pairs))
        num_w = 30
        move_w = (col_w - num_w - 12) / 2
        w_x = cx + num_w + 4
        b_x = w_x + move_w + 4

        for row in range(end - start):
            pidx = start + row
            if pidx >= len(pairs):
                break
            num, wm, bm, widx, bidx, wq, bq = pairs[pidx]
            ry = content_y + row * line_h

            if row % 2 == 0:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(30, 30, 38, 100))
                p.drawRoundedRect(QRectF(cx - 2, ry, col_w + 4, line_h - 1), 3, 3)

            is_cur_row = (widx == current_move_index or bidx == current_move_index)
            if is_cur_row:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(38, 95, 190, 45))
                p.drawRoundedRect(QRectF(cx - 2, ry, col_w + 4, line_h - 1), 3, 3)

            p.setFont(QFont("Consolas", 9))
            p.setPen(QColor(80, 80, 100))
            p.drawText(QRectF(cx, ry, num_w, line_h - 1),
                       Qt.AlignVCenter | Qt.AlignRight, f"{num}.")

            _draw_move_cell(p, w_x, ry, move_w, line_h, wm, wq,
                            widx == current_move_index)
            if bm is not None:
                _draw_move_cell(p, b_x, ry, move_w, line_h, bm, bq,
                                bidx == current_move_index)

    if num_cols > 1:
        for ci in range(num_cols - 1):
            sx = mx + pad_x + (ci + 1) * col_w + ci * col_gap + col_gap / 2
            p.setPen(QPen(QColor(52, 52, 62, 150), 1, Qt.DotLine))
            p.drawLine(QPointF(sx, content_y),
                       QPointF(sx, content_y + ppc * line_h))


def _draw_move_cell(p, x, y, w, h, san, quality, is_current):
    """Draw a single move cell with optional quality badge.
    No badge for normal/good/best/book moves."""
    sym = MQ_SYMBOLS.get(quality, "")
    show_badge = quality in MQ_SHOW_BADGE and sym
    badge_w = 28 if show_badge else 0

    bg = MQ_BG_COLORS.get(quality, QColor(0, 0, 0, 0))
    if bg.alpha() > 0:
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(x - 2, y + 2, w + 4, h - 5), 3, 3)

    if is_current:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(42, 110, 210, 70))
        p.drawRoundedRect(QRectF(x - 3, y + 2, w + 6, h - 5), 4, 4)

    p.setFont(QFont("Consolas", 11, QFont.Bold if is_current else QFont.Normal))
    p.setPen(QColor(82, 160, 245) if is_current else QColor(208, 210, 220))
    p.drawText(QRectF(x, y, w - badge_w, h - 1),
               Qt.AlignVCenter | Qt.AlignLeft, san)

    if show_badge:
        bx = x + w - badge_w
        color = MQ_COLORS.get(quality, QColor(150, 150, 150))
        pill = QRectF(bx + 2, y + (h - 16) / 2, badge_w - 4, 16)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(pill.adjusted(0.5, 1, 0.5, 1), 8, 8)

        p.setBrush(color)
        p.drawRoundedRect(pill, 8, 8)

        p.setPen(QPen(QColor(255, 255, 255, 60), 0.6))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(pill, 8, 8)

        if sym in ("★", "✕"):
            fnt = QFont("Segoe UI Symbol", max(7, int(16 * 0.6)), QFont.Bold)
        else:
            fnt = QFont("Inter", max(7, int(16 * 0.6)), QFont.Bold)
        p.setFont(fnt)
        p.setPen(QColor(255, 255, 255))
        p.drawText(pill, Qt.AlignCenter, sym)