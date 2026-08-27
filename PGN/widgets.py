from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtGui import QPainter
from PySide6.QtCore import Qt
from board_renderer import BoardRenderer

class BoardPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._renderer = BoardRenderer()
        self.setMinimumSize(320, 320); self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding); self.setFocusPolicy(Qt.StrongFocus)

    def set_board(self, board, last_move=None):
        self._renderer.board, self._renderer.last_move = board, last_move; self._renderer.anim_move, self._renderer.anim_rook_move, self._renderer.anim_progress = None, None, 1.0; self.update()

    def set_theme(self, theme): self._renderer.theme = theme; self.update()
    def set_flipped(self, f): self._renderer.flipped = f; self.update()
    @property
    def flipped(self): return self._renderer.flipped
    @property
    def renderer(self): return self._renderer

    def paintEvent(self, _event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing); t = min(self.width(), self.height()); m = t * 0.05; sz = (t - 2 * m) / 8; self._renderer._paint(p, t, m, sz); p.end()