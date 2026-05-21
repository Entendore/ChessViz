"""Chess Video Maker Pro — Smooth Animation Manager"""
import chess
import logging
from PySide6.QtCore import QObject, QPropertyAnimation, QEasingCurve
from constants import ANIM_EASINGS

logger = logging.getLogger("ChessVideoMaker.Animation")

_EASING_MAP = {
    "Linear": QEasingCurve.Linear,
    "OutCubic": QEasingCurve.OutCubic,
    "InCubic": QEasingCurve.InCubic,
    "InOutCubic": QEasingCurve.InOutCubic,
    "OutBack": QEasingCurve.OutBack,
    "OutBounce": QEasingCurve.OutBounce,
}


class AnimationManager(QObject):
    def __init__(self, board_widget, eval_bar_widget, parent=None):
        super().__init__(parent)
        self.bw = board_widget
        self.ew = eval_bar_widget
        self.enabled = True
        self.piece_anim = True
        self.highlight_anim = True
        self.eval_anim = True
        self.duration = 250
        self.easing_name = "OutCubic"
        self._active = []

    def _easing(self):
        return _EASING_MAP.get(self.easing_name, QEasingCurve.OutCubic)

    def _reg(self, a):
        """Register an active animation so we can track it."""
        self._active.append(a)
        # FIX: use a weak ref callback so we don't leak or double-unregister
        a.finished.connect(lambda checked=False, anim=a: self._unreg(anim))

    def _unreg(self, a):
        if a in self._active:
            self._active.remove(a)

    def cancel_all(self):
        """Cancel all active animations immediately."""
        for a in list(self._active):
            a.stop()
        self._active.clear()

    def animate_piece_move(self, move, callback=None):
        if not self.enabled or not self.piece_anim:
            if callback:
                callback()
            return

        bw = self.bw
        bw.anim_move = move
        bw._anim_progress_val = 0.0

        # Detect castling rook movement
        rook_move = None
        pc = bw.board.piece_at(move.to_square)
        if (pc and pc.piece_type == chess.KING and
                abs(chess.square_file(move.from_square) -
                    chess.square_file(move.to_square)) == 2):
            rank = chess.square_rank(move.from_square)
            if chess.square_file(move.to_square) > chess.square_file(move.from_square):
                rook_move = (chess.square(7, rank), chess.square(5, rank))
            else:
                rook_move = (chess.square(0, rank), chess.square(3, rank))
        bw.anim_rook_move = rook_move

        a = QPropertyAnimation(bw, b"animProgress")
        a.setDuration(self.duration)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(self._easing())

        def done():
            bw.anim_move = None
            bw.anim_rook_move = None
            bw._anim_progress_val = 1.0
            bw.update()
            if callback:
                callback()

        a.finished.connect(done)
        a.start()
        self._reg(a)

    def animate_check(self, king_sq):
        if not self.enabled or not self.highlight_anim:
            return
        self.bw._check_square = king_sq
        a = QPropertyAnimation(self.bw, b"checkOpacity")
        a.setDuration(700)
        a.setKeyValueAt(0.0, 0.0)
        a.setKeyValueAt(0.15, 1.0)
        a.setKeyValueAt(0.35, 0.25)
        a.setKeyValueAt(0.55, 0.75)
        a.setKeyValueAt(1.0, 0.0)

        def done():
            self.bw._check_square = None
            self.bw._check_opacity_val = 0.0
            self.bw.update()

        a.finished.connect(done)
        a.start()
        self._reg(a)

    def animate_last_move_flash(self, fr, to):
        if not self.enabled or not self.highlight_anim:
            return
        self.bw._flash_squares = (fr, to)
        a = QPropertyAnimation(self.bw, b"flashOpacity")
        a.setDuration(350)
        a.setKeyValueAt(0.0, 0.0)
        a.setKeyValueAt(0.2, 0.8)
        a.setKeyValueAt(1.0, 0.0)
        a.setEasingCurve(QEasingCurve.OutCubic)

        def done():
            self.bw._flash_squares = ()
            self.bw._flash_opacity_val = 0.0
            self.bw.update()

        a.finished.connect(done)
        a.start()
        self._reg(a)

    def configure_eval_bar(self):
        if self.ew:
            self.ew.set_anim_duration(self.duration if self.eval_anim else 0)

    def set_duration(self, ms):
        self.duration = max(50, min(2000, ms))
        self.configure_eval_bar()

    def set_easing(self, n):
        self.easing_name = n if n in ANIM_EASINGS else "OutCubic"

    def set_piece_anim(self, e):
        self.piece_anim = e

    def set_highlight_anim(self, e):
        self.highlight_anim = e

    def set_eval_anim(self, e):
        self.eval_anim = e
        self.configure_eval_bar()