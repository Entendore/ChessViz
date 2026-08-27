"""
rendering.py — Board, composite, title-card rendering + image conversion.
"""

import math, threading
import chess
import numpy as np
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QRadialGradient,
    QLinearGradient, QImage, QPolygonF, QPainterPath, QTransform
)
from PySide6.QtCore import Qt, QRect, QRectF, QPointF

from config import (
    SQ_SIZE, PIECE_SYM, FILES_STR, RANKS_STR, THEMES,
    HAS_NUMBA, HAS_CUPY, log
)
from helpers import _ease_out_cubic

# ═══════════════════════════════════════════════════════════════════════════════
#  STRIDE FIXER
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
else:
    def _fix_stride_nb(raw, w, h, bpl):
        return raw[:, :w * 3].reshape(h, w, 3)

# ═══════════════════════════════════════════════════════════════════════════════
#  THREAD-LOCAL RENDER ASSETS
# ═══════════════════════════════════════════════════════════════════════════════

_tl = threading.local()

def get_render_assets(sz):
    isz = int(sz * 100)
    if getattr(_tl, 'cache_sz', -1) == isz: return _tl.assets
    fp = QFont("Segoe UI Emoji", sz * 0.9); fp.setStyleStrategy(QFont.PreferAntialias)
    fc = QFont("Sans", max(7, int(sz * 0.13)), QFont.Bold)
    fb1 = QFont("Sans", max(6, int(sz * 0.19 * 0.95)), QFont.Bold)
    fb2 = QFont("Segoe UI Emoji", max(7, int(sz * 0.19 * 1.15)), QFont.Bold)
    pb = QPen(QColor(255, 255, 255, 120), max(0.8, sz * 0.008))
    _tl.assets = (fp, fc, fb1, fb2, pb); _tl.cache_sz = isz
    return _tl.assets

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
        s = min((w * FIT_FRAC) / br.width(), (h * FIT_FRAC) / br.height())
        path = QTransform.fromScale(s, s).map(path)
    path.translate(center.x(), center.y())
    shadow = QPainterPath(path); shadow.translate(1.5, 2.0)
    p.setPen(Qt.NoPen)
    if is_w:
        p.setBrush(QColor(0, 0, 0, 50)); p.drawPath(shadow)
        olw = max(1.2, sz * 0.028)
        p.setPen(QPen(QColor(30, 30, 30), olw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QColor(255, 255, 255)); p.drawPath(path)
    else:
        p.setBrush(QColor(0, 0, 0, 60)); p.drawPath(shadow)
        olw = max(0.8, sz * 0.018)
        p.setPen(QPen(QColor(10, 10, 10), olw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QColor(40, 40, 40)); p.drawPath(path)

def _draw_arrow(painter, fx, fy, tx, ty, color, sz):
    dx = tx - fx; dy = ty - fy; dist = max(1, math.hypot(dx, dy)); margin = sz * 0.22
    fx2 = fx + dx * margin / dist; fy2 = fy + dy * margin / dist
    tx2 = tx - dx * margin / dist; ty2 = ty - dy * margin / dist
    painter.setPen(QPen(color, max(2, sz // 20), Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(int(fx2), int(fy2), int(tx2), int(ty2))
    angle = math.atan2(dy, dx); a_sz = sz * 0.22
    p1x = tx2 - a_sz * math.cos(angle - 0.45); p1y = ty2 - a_sz * math.sin(angle - 0.45)
    p2x = tx2 - a_sz * math.cos(angle + 0.45); p2y = ty2 - a_sz * math.sin(angle + 0.45)
    tri = QPolygonF([QPointF(tx2, ty2), QPointF(p1x, p1y), QPointF(p2x, p2y)])
    painter.setBrush(color); painter.setPen(Qt.NoPen); painter.drawPolygon(tri)

_PIECE_TYPE_MAP = {'K': chess.KING, 'Q': chess.QUEEN, 'R': chess.ROOK,
                   'B': chess.BISHOP, 'N': chess.KNIGHT, 'P': chess.PAWN,
                   'k': chess.KING, 'q': chess.QUEEN, 'r': chess.ROOK,
                   'b': chess.BISHOP, 'n': chess.KNIGHT, 'p': chess.PAWN}

def _reconstruct_piece(symbol):
    pt = _PIECE_TYPE_MAP.get(symbol)
    if pt is None: return None
    return chess.Piece(pt, chess.WHITE if symbol.isupper() else chess.BLACK)

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD-ONLY FRAME (for widget + composite)
# ═══════════════════════════════════════════════════════════════════════════════

def render_board_image(board, last_move=None, selected=None, legal_targets=None,
                       check_squares=None, anim_state=None, sq_size=SQ_SIZE,
                       show_arrow=True, theme=None, flipped=False):
    if theme is None: theme = THEMES["Classic"]
    sz = sq_size; img = QImage(sz * 8, sz * 8, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent); p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
    (font_piece, font_coord, *_) = get_render_assets(sz)
    check_set = set(check_squares or []); skip_sq = set()
    if anim_state: skip_sq.add(anim_state['from']); skip_sq.add(anim_state['to'])
    b2s = (lambda br, bc: (7 - br, 7 - bc)) if flipped else (lambda br, bc: (br, bc))

    for sq in chess.SQUARES:
        br, bc = 7 - chess.square_rank(sq), chess.square_file(sq)
        sr, sc = b2s(br, bc); x, y = sc * sz, sr * sz
        is_light = (br + bc) % 2 == 0
        p.fillRect(x, y, sz, sz, theme.light_sq if is_light else theme.dark_sq)
        if last_move and (br, bc) in last_move: p.fillRect(x, y, sz, sz, theme.last_move)
        if selected and (br, bc) == selected: p.fillRect(x, y, sz, sz, theme.highlight)
        if (br, bc) in check_set:
            grad = QRadialGradient(x + sz / 2, y + sz / 2, sz * 0.7)
            grad.setColorAt(0, QColor(255, 30, 30, 180)); grad.setColorAt(1, QColor(255, 0, 0, 0))
            p.setBrush(QBrush(grad)); p.setPen(Qt.NoPen); p.drawRect(x, y, sz, sz)
        if legal_targets and (br, bc) in legal_targets:
            cx, cy = x + sz // 2, y + sz // 2
            if board.piece_at(sq) is not None:
                p.setPen(QPen(QColor(0, 0, 0, 90), max(3, sz // 14))); p.setBrush(Qt.NoBrush)
                p.drawEllipse(cx - sz * 5 // 12, cy - sz * 5 // 12, sz * 10 // 12, sz * 10 // 12)
            else:
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 90))
                p.drawEllipse(cx - sz // 6, cy - sz // 6, sz // 3, sz // 3)

    if show_arrow and last_move:
        (bfr, bfc), (btr, btc) = last_move
        sfr, sfc = b2s(bfr, bfc); str_, stc = b2s(btr, btc)
        _draw_arrow(p, sfc * sz + sz // 2, sfr * sz + sz // 2,
                    stc * sz + sz // 2, str_ * sz + sz // 2, theme.arrow_clr, sz)

    for sq in chess.SQUARES:
        br, bc = 7 - chess.square_rank(sq), chess.square_file(sq)
        if (br, bc) in skip_sq: continue
        piece = board.piece_at(sq)
        if piece: sr, sc = b2s(br, bc); _draw_piece(p, piece, sr, sc, sz, font_piece)

    if anim_state and anim_state.get('captured', '.') != '.':
        bfr, bfc_ = anim_state['from']; btr, btc_ = anim_state['to']
        cap_piece = _reconstruct_piece(anim_state['captured'])
        if cap_piece is not None:
            fade = max(0, int(200 * (1.0 - anim_state['progress'])))
            p.setOpacity(fade / 255.0)
            sr, sc = b2s(btr, btc_); _draw_piece(p, cap_piece, sr, sc, sz, font_piece)
            p.setOpacity(1.0)

    if anim_state:
        bfr, bfc_ = anim_state['from']; btr, btc_ = anim_state['to']
        t = anim_state['progress']; anim_obj = anim_state.get('piece_obj')
        if anim_obj:
            lift = 4.0 * t * (1.0 - t) * 0.15; scale = 1.0 + 4.0 * t * (1.0 - t) * 0.08
            ir = bfr + (btr - bfr) * t; ic = bfc_ + (btc_ - bfc_) * t
            sir, sic = b2s(ir, ic)
            sa = 30 + int(70 * (lift / 0.15))
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, sa))
            p.drawEllipse(QRectF(sic * sz + (sz * scale - sz * 0.65) / 2,
                                 sir * sz + sz * 0.82, sz * 0.65, sz * 0.12))
            _draw_piece_at(p, anim_obj, (sir * sz - sz * lift) / sz, sic,
                           sz, sz * scale, sz * scale, font_piece)

    p.setFont(font_coord); cm = max(3, int(sz * 0.04)); cs = max(12, sz // 5)
    for c in range(8):
        is_light = (7 + c) % 2 == 0
        p.setPen(theme.dark_sq if is_light else theme.light_sq)
        p.drawText(QRect(c * sz + sz - cs - cm, 7 * sz + cm, cs, cs),
                   Qt.AlignCenter, FILES_STR[7 - c if flipped else c])
    for r in range(8):
        is_light = r % 2 == 0
        p.setPen(theme.dark_sq if is_light else theme.light_sq)
        p.drawText(QRect(cm, r * sz + cm, cs, cs),
                   Qt.AlignCenter, RANKS_STR[7 - r if flipped else r])
    p.end(); return img

# ═══════════════════════════════════════════════════════════════════════════════
#  COMPOSITE LAYOUT CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════

class CompositeLayout:
    """Calculates board, title-bar, and move-list positions for a composite frame."""
    def __init__(self, width, height, sq_size, is_vertical):
        self.w = width; self.h = height; self.sz = sq_size
        self.bpx = sq_size * 8; self.vert = is_vertical
        self.pad = max(12, int(min(width, height) * 0.025))
        if is_vertical:
            self._vert_layout()
        else:
            self._horiz_layout()

    def _horiz_layout(self):
        self.title_h = max(44, int(self.h * 0.075))
        self.bx = self.pad * 2
        self.by = self.title_h + self.pad
        avail_h = self.h - self.by - self.pad
        if self.bpx < avail_h:
            self.by += (avail_h - self.bpx) // 2
        self.mx = self.bx + self.bpx + self.pad * 2
        self.my = self.by
        self.mw = self.w - self.mx - self.pad * 2
        self.mh = self.bpx

    def _vert_layout(self):
        self.title_h = max(36, int(self.h * 0.04))
        self.bx = (self.w - self.bpx) // 2
        self.by = self.title_h + self.pad
        self.mx = self.pad * 2
        self.my = self.by + self.bpx + self.pad
        self.mw = self.w - self.pad * 4
        self.mh = self.h - self.my - self.pad

# ═══════════════════════════════════════════════════════════════════════════════
#  COMPOSITE FRAME (board + title bar + move list)
# ═══════════════════════════════════════════════════════════════════════════════

def render_composite_frame(board, notations, current_move_idx,
                           last_move=None, check_squares=None,
                           anim_state=None, opening_name="", eco="",
                           width=1920, height=1080, sq_size=None,
                           theme=None, flipped=False, bg_color=(26, 26, 46)):
    if theme is None: theme = THEMES["Classic"]
    if sq_size is None: sq_size = max(8, min(height, width) // 10)
    is_vert = height > width
    layout = CompositeLayout(width, height, sq_size, is_vert)
    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    bg = QColor(*bg_color); img.fill(bg); p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)

    # ── Title bar ──────────────────────────────────────────────────────────
    title_grad = QLinearGradient(0, 0, 0, layout.title_h)
    title_grad.setColorAt(0, bg.lighter(140)); title_grad.setColorAt(1, bg)
    p.fillRect(0, 0, width, layout.title_h, title_grad)
    p.setPen(QPen(bg.lighter(160), 1)); p.drawLine(0, layout.title_h, width, layout.title_h)
    title_fs = max(14, int(layout.title_h * 0.42))
    p.setFont(QFont("Sans", title_fs, QFont.Bold)); p.setPen(QColor(230, 230, 240))
    title_text = f"♟  {opening_name}"
    p.drawText(QRectF(layout.pad * 2, 0, width * 0.7, layout.title_h),
               Qt.AlignVCenter | Qt.AlignLeft, title_text)
    eco_fs = max(10, int(layout.title_h * 0.3))
    p.setFont(QFont("Sans", eco_fs)); p.setPen(QColor(160, 160, 180))
    eco_text = f"ECO {eco}  ·  {len(notations)} moves"
    p.drawText(QRectF(width * 0.7, 0, width * 0.28, layout.title_h),
               Qt.AlignVCenter | Qt.AlignRight, eco_text)

    # ── Board ──────────────────────────────────────────────────────────────
    board_img = render_board_image(board, last_move=last_move,
                                   check_squares=check_squares,
                                   anim_state=anim_state, sq_size=sq_size,
                                   theme=theme, flipped=flipped)
    p.drawImage(layout.bx, layout.by, board_img)

    # ── Move list panel ────────────────────────────────────────────────────
    _draw_move_list(p, notations, current_move_idx, layout, bg_color)

    p.end(); return img

def _draw_move_list(p, notations, current_idx, layout, bg_color):
    """Draw the move-list panel with current-move highlight."""
    mx, my, mw, mh = layout.mx, layout.my, layout.mw, layout.mh
    if mw < 20 or mh < 20: return
    # Panel background
    panel_bg = QColor(*bg_color).lighter(115)
    p.setPen(Qt.NoPen); p.setBrush(panel_bg)
    p.drawRoundedRect(QRectF(mx, my, mw, mh), 8, 8)
    # Header
    hdr_h = max(24, int(mh * 0.07))
    p.setPen(QColor(140, 140, 160)); hdr_fs = max(9, int(hdr_h * 0.6))
    p.setFont(QFont("Sans", hdr_fs, QFont.Bold))
    p.drawText(QRectF(mx + 10, my + 4, mw - 20, hdr_h), Qt.AlignVCenter | Qt.AlignLeft, "MOVES")
    sep_y = my + hdr_h + 4; p.setPen(QPen(QColor(80, 80, 100), 1))
    p.drawLine(int(mx + 10), int(sep_y), int(mx + mw - 10), int(sep_y))

    # Move rows
    row_h = max(18, int(mh * 0.055))
    fs = max(10, int(row_h * 0.55))
    move_font = QFont("Monospace", fs); num_font = QFont("Sans", fs - 1)
    content_y = sep_y + 6
    available_h = my + mh - content_y - 8
    max_rows = max(1, available_h // row_h)
    # Build pairs
    pairs = []
    for i in range(0, len(notations), 2):
        w_move = notations[i] if i < len(notations) else ""
        b_move = notations[i + 1] if i + 1 < len(notations) else ""
        pairs.append((i + 1, w_move, b_move, i, i + 1 if i + 1 < len(notations) else -1))
    # Scroll so current move is visible
    scroll = 0
    if len(pairs) > max_rows:
        cur_pair = current_idx // 2 if current_idx >= 0 else 0
        scroll = max(0, min(cur_pair - max_rows // 2, len(pairs) - max_rows))
    # Draw pairs
    col_num_w = max(28, int(mw * 0.12))
    col_w = (mw - col_num_w - 20) / 2
    highlight_clr = QColor(42, 130, 218, 70)
    for row_i in range(max_rows):
        pi = scroll + row_i
        if pi >= len(pairs): break
        move_num, w_txt, b_txt, w_idx, b_idx = pairs[pi]
        ry = content_y + row_i * row_h
        # White move highlight
        if current_idx == w_idx and w_txt:
            p.setPen(Qt.NoPen); p.setBrush(highlight_clr)
            p.drawRoundedRect(QRectF(mx + col_num_w + 10, ry, col_w, row_h - 2), 3, 3)
        # Black move highlight
        if current_idx == b_idx and b_txt:
            p.setPen(Qt.NoPen); p.setBrush(highlight_clr)
            p.drawRoundedRect(QRectF(mx + col_num_w + 10 + col_w + 4, ry, col_w, row_h - 2), 3, 3)
        # Number
        p.setFont(num_font); p.setPen(QColor(120, 120, 140))
        p.drawText(QRectF(mx + 10, ry, col_num_w, row_h - 2),
                   Qt.AlignVCenter | Qt.AlignRight, f"{move_num}.")
        # White move
        p.setFont(move_font); p.setPen(QColor(230, 230, 230))
        if w_txt:
            p.drawText(QRectF(mx + col_num_w + 14, ry, col_w, row_h - 2),
                       Qt.AlignVCenter | Qt.AlignLeft, w_txt)
        # Black move
        p.setPen(QColor(190, 190, 200))
        if b_txt:
            p.drawText(QRectF(mx + col_num_w + 14 + col_w + 8, ry, col_w, row_h - 2),
                       Qt.AlignVCenter | Qt.AlignLeft, b_txt)

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT TITLE CARD
# ═══════════════════════════════════════════════════════════════════════════════

def render_export_title_card(opening_name, eco, num_moves,
                             width=1920, height=1080, bg_color=(26, 26, 46)):
    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    bg = QColor(*bg_color); img.fill(bg)
    p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    # Gradient overlay
    grad = QLinearGradient(0, 0, 0, height)
    grad.setColorAt(0, bg.lighter(130)); grad.setColorAt(0.5, bg); grad.setColorAt(1, bg.lighter(110))
    p.fillRect(0, 0, width, height, grad)
    # Large piece watermark
    p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 12))
    wm_sz = min(width, height) * 0.45
    wm_font = QFont("Segoe UI Emoji", wm_sz)
    p.setFont(wm_font)
    p.drawText(QRectF(0, 0, width, height), Qt.AlignCenter, "♚")
    # Opening name
    name_fs = max(28, int(min(width, height) * 0.05))
    p.setFont(QFont("Sans", name_fs, QFont.Bold)); p.setPen(QColor(240, 240, 245))
    p.drawText(QRectF(60, height * 0.32, width - 120, height * 0.15),
               Qt.AlignCenter, opening_name)
    # ECO + move count
    info_fs = max(16, name_fs // 2)
    p.setFont(QFont("Sans", info_fs)); p.setPen(QColor(160, 160, 190))
    info = f"ECO {eco}   ·   {num_moves} half-moves"
    p.drawText(QRectF(60, height * 0.52, width - 120, height * 0.08),
               Qt.AlignCenter, info)
    # Subtle line
    lw = min(width * 0.4, 500)
    p.setPen(QPen(QColor(100, 100, 140, 120), 2))
    p.drawLine(int((width - lw) / 2), int(height * 0.48),
               int((width + lw) / 2), int(height * 0.48))
    p.end(); return img

# ═══════════════════════════════════════════════════════════════════════════════
#  QIMAGE ↔ NUMPY
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