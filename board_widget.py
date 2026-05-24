"""Chess Video Maker Pro — Interactive Chess Board Widget

Uses BoardRenderer internally for both on-screen painting and
render_to_image, so the rendering code lives in one place.
"""
import chess
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, Property
from PySide6.QtGui import QPainter, QColor
from board_renderer import BoardRenderer
from constants import BoardTheme


class ChessBoardWidget(QWidget):
    squareClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.board = chess.Board()
        self.theme = BoardTheme()
        self.flipped = False
        self.show_coords = True
        self.selected_sq = None
        self.legal_targets: list = []
        self.last_move = None
        self.highlighted: set = set()
        self.arrows: list = []
        self._arr_s = self._arr_e = None
        self._draw_arr = False
        # Animation properties (driven by QPropertyAnimation)
        self.anim_move = None
        self.anim_rook_move = None
        self._anim_progress_val = 1.0
        self._check_square = None
        self._check_opacity_val = 0.0
        self._flash_squares = ()
        self._flash_opacity_val = 0.0
        self.policy_vis: dict = {}
        self.setMinimumSize(400, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    # ── Qt Properties for animation ────────────────────────────────
    def _get_ap(self): return self._anim_progress_val
    def _set_ap(self, v): self._anim_progress_val = v; self.update()
    animProgress = Property(float, _get_ap, _set_ap)

    def _get_co(self): return self._check_opacity_val
    def _set_co(self, v): self._check_opacity_val = v; self.update()
    checkOpacity = Property(float, _get_co, _set_co)

    def _get_fo(self): return self._flash_opacity_val
    def _set_fo(self, v): self._flash_opacity_val = v; self.update()
    flashOpacity = Property(float, _get_fo, _set_fo)

    # ── Renderer factory ───────────────────────────────────────────
    def _make_renderer(self):
        """Create a BoardRenderer snapshot of the current widget state."""
        r = BoardRenderer()
        r.board = self.board
        r.theme = self.theme
        r.flipped = self.flipped
        r.show_coords = self.show_coords
        r.selected_sq = self.selected_sq
        r.legal_targets = self.legal_targets
        r.last_move = self.last_move
        r.highlighted = self.highlighted
        r.arrows = self.arrows
        r.policy_vis = self.policy_vis
        r.anim_move = self.anim_move
        r.anim_rook_move = self.anim_rook_move
        r.anim_progress = self._anim_progress_val
        r._check_square = self._check_square
        r._check_opacity = self._check_opacity_val
        r._flash_squares = self._flash_squares
        r._flash_opacity = self._flash_opacity_val
        return r

    # ── Layout helpers ─────────────────────────────────────────────
    def _layout(self):
        t = min(self.width(), self.height())
        m = t * 0.05 if self.show_coords else 0
        s = (t - 2 * m) / 8
        return t, m, s

    def _pos_to_sq(self, pos, t, m, sz):
        c = int((pos.x() - m) / sz)
        r = int((pos.y() - m) / sz)
        if not (0 <= c < 8 and 0 <= r < 8):
            return None
        return chess.square(7 - c, r) if self.flipped else chess.square(c, 7 - r)

    # ── Public setters ─────────────────────────────────────────────
    def set_theme(self, t):
        self.theme = t
        self.update()

    def set_position(self, board, lm=None):
        self.board = board
        self.last_move = lm
        self.selected_sq = None
        self.legal_targets = []
        self.anim_move = None
        self.anim_rook_move = None
        self._anim_progress_val = 1.0
        self._check_square = None
        self._check_opacity_val = 0.0
        self._flash_squares = ()
        self._flash_opacity_val = 0.0
        self.update()

    def set_position_animated(self, board, lm=None):
        self.board = board
        self.last_move = lm
        self.selected_sq = None
        self.legal_targets = []
        self.update()

    # ── Mouse events ───────────────────────────────────────────────
    def mousePressEvent(self, e):
        t, m, sz = self._layout()
        sq = self._pos_to_sq(e.position().toPoint(), t, m, sz)
        if sq is None:
            return
        if e.button() == Qt.LeftButton:
            if e.modifiers() & Qt.ShiftModifier:
                self._arr_s = sq
                self._draw_arr = True
                self._arr_e = sq
            else:
                self.squareClicked.emit(sq)
        elif e.button() == Qt.RightButton:
            self.highlighted.symmetric_difference_update({sq})
            self.update()

    def mouseMoveEvent(self, e):
        if self._draw_arr:
            t, m, sz = self._layout()
            sq = self._pos_to_sq(e.position().toPoint(), t, m, sz)
            if sq is not None:
                self._arr_e = sq
                self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._draw_arr:
            t, m, sz = self._layout()
            sq = self._pos_to_sq(e.position().toPoint(), t, m, sz)
            if sq and self._arr_s is not None and sq != self._arr_s:
                self.arrows.append((self._arr_s, sq, QColor(self.theme.arrow_clr)))
                self.update()
            self._draw_arr = False
            self._arr_s = self._arr_e = None

    # ── Painting — delegates to BoardRenderer ──────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        t, m, sz = self._layout()
        renderer = self._make_renderer()
        renderer._paint(p, t, m, sz)
        p.end()

    def render_to_image(self, size=1080):
        """Render the board to QImage using the standalone BoardRenderer."""
        renderer = self._make_renderer()
        return renderer.render(size)