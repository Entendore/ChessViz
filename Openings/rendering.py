"""
rendering.py — Board rendering, piece drawing, image conversion, and card rendering.
All pure rendering logic with no widget dependency.
"""

import math, threading
import chess
import numpy as np
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QRadialGradient,
    QImage, QPolygonF, QPainterPath, QTransform
)
from PySide6.QtCore import Qt, QRect, QRectF, QPointF

from config import (
    SQ_SIZE, PIECE_SYM, FILES_STR, RANKS_STR, THEMES,
    HAS_NUMBA, HAS_CUPY, log          # BUG-FIX: HAS_CUPY was missing
)
from helpers import _ease_out_cubic

# ═══════════════════════════════════════════════════════════════════════════════
#  STRIDE FIXER (numba JIT or pure-numpy fallback)
# ═══════════════════════════════════════════════════════════════════════════════

if HAS_NUMBA:
    from numba import njit as _njit2

    @_njit2(cache=True, nogil=True)
    def _fix_stride_nb(raw, w, h, bpl):
        out = np.empty((h, w, 3), dtype=np.uint8); w3 = w * 3
        for i in range(h):
            src = i * bpl; dst = i * w3
            for j in range(w3): out.flat[dst + j] = raw.flat[src + j]
        return out
    log("Numba JIT stride-fixer loaded", "BOARD")
else:
    def _fix_stride_nb(raw, w, h, bpl):
        return raw[:, :w * 3].reshape(h, w, 3)


# ═══════════════════════════════════════════════════════════════════════════════
#  THREAD-LOCAL RENDER ASSETS (fonts, pens)
# ═══════════════════════════════════════════════════════════════════════════════

_thread_local = threading.local()

def get_render_assets(sz):
    isz = int(sz * 100)
    if getattr(_thread_local, 'cache_sz', -1) == isz:
        return _thread_local.assets
    font_piece = QFont("Segoe UI Emoji", sz * 0.9)
    font_piece.setStyleStrategy(QFont.PreferAntialias)
    font_coord = QFont("Sans", max(7, int(sz * 0.13)), QFont.Bold)
    font_badge_normal = QFont("Sans", max(6, int(sz * 0.19 * 0.95)), QFont.Bold)
    font_badge_symbol = QFont("Segoe UI Emoji", max(7, int(sz * 0.19 * 1.15)), QFont.Bold)
    pen_badge_outline = QPen(QColor(255, 255, 255, 120), max(0.8, sz * 0.008))
    assets = (font_piece, font_coord, font_badge_normal,
              font_badge_symbol, pen_badge_outline)
    _thread_local.cache_sz = isz; _thread_local.assets = assets
    return assets


# ═══════════════════════════════════════════════════════════════════════════════
#  PIECE & ARROW DRAWING
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_piece(p, piece_obj, row, col, sz, font):
    _draw_piece_at(p, piece_obj, float(row), float(col), sz, sz, sz, font)


def _draw_piece_at(p, piece_obj, row_f, col_f, sz, w, h, font):
    FIT_FRAC = 0.85; is_w = piece_obj.color == chess.WHITE
    glyph = PIECE_SYM[(piece_obj.piece_type, piece_obj.color)]
    px = col_f * sz; py = row_f * sz
    rect = QRectF(px + (sz - w) / 2, py + (sz - h) / 2, w, h)
    center = rect.center(); p.setFont(font)
    path = QPainterPath(); path.addText(QPointF(0, 0), font, glyph)
    br = path.boundingRect(); path.translate(-br.center().x(), -br.center().y())
    if br.width() > 0 and br.height() > 0:
        sx = (w * FIT_FRAC) / br.width()
        sy = (h * FIT_FRAC) / br.height()
        s = min(sx, sy); path = QTransform.fromScale(s, s).map(path)
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


def _draw_arrow(painter, fx, fy, tx, ty, color, sz):
    dx = tx - fx; dy = ty - fy; dist = max(1, math.hypot(dx, dy))
    margin = sz * 0.22
    fx2 = fx + dx * margin / dist; fy2 = fy + dy * margin / dist
    tx2 = tx - dx * margin / dist; ty2 = ty - dy * margin / dist
    painter.setPen(QPen(color, max(2, sz // 20), Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(int(fx2), int(fy2), int(tx2), int(ty2))
    angle = math.atan2(dy, dx); a_sz = sz * 0.22
    p1x = tx2 - a_sz * math.cos(angle - 0.45)
    p1y = ty2 - a_sz * math.sin(angle - 0.45)
    p2x = tx2 - a_sz * math.cos(angle + 0.45)
    p2y = ty2 - a_sz * math.sin(angle + 0.45)
    tri = QPolygonF([QPointF(tx2, ty2), QPointF(p1x, p1y), QPointF(p2x, p2y)])
    painter.setBrush(color); painter.setPen(Qt.NoPen); painter.drawPolygon(tri)


# ═══════════════════════════════════════════════════════════════════════════════
#  CAPTURED-PIECE RECONSTRUCTION
# ═══════════════════════════════════════════════════════════════════════════════

_PIECE_TYPE_MAP = {
    'K': chess.KING, 'Q': chess.QUEEN, 'R': chess.ROOK,
    'B': chess.BISHOP, 'N': chess.KNIGHT, 'P': chess.PAWN,
    'k': chess.KING, 'q': chess.QUEEN, 'r': chess.ROOK,
    'b': chess.BISHOP, 'n': chess.KNIGHT, 'p': chess.PAWN,
}

def _reconstruct_piece(symbol):
    """Reconstruct a chess.Piece from its FEN symbol (e.g. 'P', 'p')."""
    pt = _PIECE_TYPE_MAP.get(symbol)
    if pt is None:
        return None
    color = chess.WHITE if symbol.isupper() else chess.BLACK
    return chess.Piece(pt, color)


# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD FRAME RENDERING
# ═══════════════════════════════════════════════════════════════════════════════

def render_frame(board, last_move=None, selected=None, legal_targets=None,
                 text_overlay="", check_squares=None, anim_state=None,
                 sq_size=SQ_SIZE, show_arrow=True, theme=None, flipped=False):
    if theme is None: theme = THEMES["Classic"]
    sz = sq_size
    img = QImage(sz * 8, sz * 8, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent); p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    (font_piece, font_coord, font_badge_normal,
     font_badge_symbol, pen_badge_outline) = get_render_assets(sz)

    check_set = set(check_squares or []); skip_sq = set()
    if anim_state:
        skip_sq.add(anim_state['from']); skip_sq.add(anim_state['to'])

    # helper: board coords → screen coords
    def b2s(br, bc):
        return (7 - br, 7 - bc) if flipped else (br, bc)

    # --- Squares ---
    for sq in chess.SQUARES:
        br, bc = 7 - chess.square_rank(sq), chess.square_file(sq)
        sr, sc = b2s(br, bc)
        x, y = sc * sz, sr * sz
        is_light = (br + bc) % 2 == 0
        color = theme.light_sq if is_light else theme.dark_sq
        p.fillRect(x, y, sz, sz, color)

        if last_move and (br, bc) in last_move:
            p.fillRect(x, y, sz, sz, theme.last_move)
        if selected and (br, bc) == selected:
            p.fillRect(x, y, sz, sz, theme.highlight)
        if (br, bc) in check_set:
            grad = QRadialGradient(x + sz / 2, y + sz / 2, sz * 0.7)
            grad.setColorAt(0, QColor(255, 30, 30, 180))
            grad.setColorAt(1, QColor(255, 0, 0, 0))
            p.setBrush(QBrush(grad)); p.setPen(Qt.NoPen)
            p.drawRect(x, y, sz, sz)
        if legal_targets and (br, bc) in legal_targets:
            cx, cy = x + sz // 2, y + sz // 2
            if board.piece_at(sq) is not None:
                p.setPen(QPen(QColor(0, 0, 0, 90), max(3, sz // 14)))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(cx - sz * 5 // 12, cy - sz * 5 // 12,
                              sz * 10 // 12, sz * 10 // 12)
            else:
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 90))
                p.drawEllipse(cx - sz // 6, cy - sz // 6, sz // 3, sz // 3)

    # --- Arrow ---
    if show_arrow and last_move:
        (bfr, bfc), (btr, btc) = last_move
        sfr, sfc = b2s(bfr, bfc); str_, stc = b2s(btr, btc)
        _draw_arrow(p, sfc * sz + sz // 2, sfr * sz + sz // 2,
                    stc * sz + sz // 2, str_ * sz + sz // 2,
                    theme.arrow_clr, sz)

    # --- Pieces (static) ---
    for sq in chess.SQUARES:
        br, bc = 7 - chess.square_rank(sq), chess.square_file(sq)
        if (br, bc) in skip_sq: continue
        piece = board.piece_at(sq)
        if piece:
            sr, sc = b2s(br, bc)
            _draw_piece(p, piece, sr, sc, sz, font_piece)

    # --- Captured piece fade (animation) ---
    # BUG-FIX: always reconstruct from the symbol — the board already has the
    # moving piece at the destination square, so board.piece_at() would return
    # the mover, not None, and the old reconstruction path was unreachable.
    if anim_state and anim_state.get('captured', '.') != '.':
        bfr, bfc_ = anim_state['from']; btr, btc_ = anim_state['to']
        cap_piece = _reconstruct_piece(anim_state['captured'])
        if cap_piece is not None:
            fade = max(0, int(200 * (1.0 - anim_state['progress'])))
            p.setOpacity(fade / 255.0)
            sr, sc = b2s(btr, btc_)
            _draw_piece(p, cap_piece, sr, sc, sz, font_piece)
            p.setOpacity(1.0)

    # --- Animating piece ---
    if anim_state:
        bfr, bfc_ = anim_state['from']; btr, btc_ = anim_state['to']
        t = anim_state['progress']
        anim_piece_obj = anim_state.get('piece_obj')
        if anim_piece_obj:
            lift = 4.0 * t * (1.0 - t) * 0.15
            scale = 1.0 + 4.0 * t * (1.0 - t) * 0.08
            # interpolate in board coords, then convert to screen
            ir = bfr + (btr - bfr) * t; ic = bfc_ + (btc_ - bfc_) * t
            sir, sic = b2s(ir, ic)

            shadow_alpha = 30 + int(70 * (lift / 0.15))
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, shadow_alpha))
            sy = sir * sz + sz * 0.82
            p.drawEllipse(QRectF(sic * sz + (sz * scale - sz * 0.65) / 2, sy,
                                 sz * 0.65, sz * 0.12))
            w, h = sz * scale, sz * scale
            y_lift = sir * sz - (sz * lift)
            _draw_piece_at(p, anim_piece_obj, y_lift / sz, sic, sz, w, h, font_piece)

    # --- Coordinates ---
    p.setFont(font_coord)
    coord_margin = max(3, int(sz * 0.04)); coord_sz = max(12, sz // 5)
    for c in range(8):
        is_light = (7 + c) % 2 == 0  # parity is flip-invariant
        col = theme.dark_sq if is_light else theme.light_sq; p.setPen(col)
        file_idx = 7 - c if flipped else c
        p.drawText(QRect(c * sz + sz - coord_sz - coord_margin,
                         7 * sz + coord_margin, coord_sz, coord_sz),
                   Qt.AlignCenter, FILES_STR[file_idx])
    for r in range(8):
        is_light = r % 2 == 0  # parity is flip-invariant
        col = theme.dark_sq if is_light else theme.light_sq; p.setPen(col)
        rank_idx = 7 - r if flipped else r
        p.drawText(QRect(coord_margin, r * sz + coord_margin,
                         coord_sz, coord_sz),
                   Qt.AlignCenter, RANKS_STR[rank_idx])

    # --- Text overlay ---
    if text_overlay:
        p.fillRect(0, sz * 4 - 28, sz * 8, 56, QColor(0, 0, 0, 200))
        p.setPen(Qt.white); p.setFont(QFont("Sans", max(12, sz // 4), QFont.Bold))
        p.drawText(QRect(0, sz * 4 - 28, sz * 8, 56), Qt.AlignCenter, text_overlay)

    p.end(); return img


# ═══════════════════════════════════════════════════════════════════════════════
#  CARD RENDERING (title/end cards for video export)
# ═══════════════════════════════════════════════════════════════════════════════

def render_card(text, bg="#1a1a2e", fg="#e0e0e0", w=544, h=544,
                width=None, height=None, font_size=36, sub_text="",
                bg_color=None, fg_color=None):
    bg_val = bg if bg != "#1a1a2e" else (bg_color or bg)
    fg_val = fg if fg != "#e0e0e0" else (fg_color or fg)
    w_val = width if width is not None else w
    h_val = height if height is not None else h
    img = QImage(w_val, h_val, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(bg_val))
    p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(fg_val))
    p.setFont(QFont("Sans", font_size, QFont.Bold))
    p.drawText(QRect(0, 0, w_val, h_val), Qt.AlignCenter, text)
    if sub_text:
        p.setFont(QFont("Sans", max(10, font_size // 2)))
        p.setPen(QColor(fg_val).lighter(140))
        p.drawText(QRect(0, h_val * 3 // 5, w_val, h_val // 4),
                   Qt.AlignCenter, sub_text)
    p.end(); return img


# ═══════════════════════════════════════════════════════════════════════════════
#  QIMAGE ↔ NUMPY CONVERSION
# ═══════════════════════════════════════════════════════════════════════════════

def qimage_to_np(img):
    img2 = img.convertToFormat(QImage.Format_RGB888)
    ptr = img2.constBits()
    if hasattr(ptr, 'setsize'): ptr.setsize(img2.sizeInBytes())
    w = img2.width(); h = img2.height(); bpl = img2.bytesPerLine()
    raw = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl)).copy()
    if bpl == w * 3: return raw.reshape((h, w, 3))
    return _fix_stride_nb(raw, w, h, bpl)


def qimage_to_np_batch(images, use_gpu=False):
    if not images: return np.empty((0, 0, 0, 3), dtype=np.uint8)
    arrays = [qimage_to_np(im) for im in images]
    stack = np.stack(arrays)
    if use_gpu and HAS_CUPY:
        import cupy as _cp; return _cp.asarray(stack)
    return stack