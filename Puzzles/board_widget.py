"""Chess board widget — renders the board and handles mouse interaction."""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import (QPainter, QColor, QFont, QPen, QPixmap, QImage)

from constants import (
    SQ_SIZE, LIGHT_SQ, DARK_SQ, SEL_COL, MOVE_DOT,
    CAP_RING, LAST_COL, UNICODE_PIECES, FILES_STR, RANKS_STR, log,
)


class ChessBoardWidget(QWidget):
    move_made = Signal(str)

    def __init__(self, engine, sound_mgr, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.snd = sound_mgr
        self.selected = None
        self.legal_targets = []
        self.setFixedSize(SQ_SIZE * 8, SQ_SIZE * 8)
        self.setMouseTracking(True)

    # ── Paint ─────────────────────────────────────────────────────────────────
    def paintEvent(self, e):
        pix = self.render_image(
            self.engine.board, self.engine.last_move,
            self.selected, self.legal_targets,
        )
        painter = QPainter(self)
        painter.drawPixmap(0, 0, pix)

    # ── Static rendering (used by widget + export) ────────────────────────────
    @staticmethod
    def render_image(board, last_move=None, selected=None,
                     legal_targets=None, text_overlay=""):
        sz = SQ_SIZE
        pix = QPixmap(sz * 8, sz * 8)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)

        for r in range(8):
            for c in range(8):
                # Square colour
                color = QColor(LIGHT_SQ) if (r + c) % 2 == 0 else QColor(DARK_SQ)
                p.fillRect(c * sz, r * sz, sz, sz, color)

                # Last-move highlight
                if last_move and (r, c) in last_move:
                    p.fillRect(c * sz, r * sz, sz, sz, QColor(*LAST_COL))

                # Selection highlight
                if selected and (r, c) == selected:
                    p.fillRect(c * sz, r * sz, sz, sz, QColor(*SEL_COL))

                # Legal-target indicators
                if legal_targets and (r, c) in legal_targets:
                    cx, cy = c * sz + sz // 2, r * sz + sz // 2
                    if board[r][c] != '.':
                        p.setPen(QPen(QColor(*CAP_RING), 4)); p.setBrush(Qt.NoBrush)
                        p.drawEllipse(cx - sz // 3, cy - sz // 3,
                                      sz * 2 // 3, sz * 2 // 3)
                    else:
                        p.setPen(Qt.NoPen); p.setBrush(QColor(*MOVE_DOT))
                        p.drawEllipse(cx - sz // 8, cy - sz // 8,
                                      sz // 4, sz // 4)

                # Piece glyph
                piece = board[r][c]
                if piece != '.':
                    is_w = piece.isupper()
                    p.setFont(QFont("Segoe UI Emoji",
                                    sz * 0.65 if is_w else sz * 0.7))
                    # Shadow
                    p.setPen(QColor(0, 0, 0, 60))
                    p.drawText(QRect(c * sz + 2, r * sz + 2, sz, sz),
                               Qt.AlignCenter, UNICODE_PIECES[piece])
                    # Foreground
                    p.setPen(QColor("#FFFFFF") if not is_w else QColor("#000000"))
                    p.drawText(QRect(c * sz, r * sz, sz, sz),
                               Qt.AlignCenter, UNICODE_PIECES[piece])

        # Coordinate labels
        p.setFont(QFont("Sans", 9, QFont.Bold))
        for c in range(8):
            col = QColor(DARK_SQ) if (7 + c) % 2 == 0 else QColor(LIGHT_SQ)
            p.setPen(col)
            p.drawText(QRect(c * sz + sz - 14, 7 * sz + 2, 12, 14),
                       Qt.AlignCenter, FILES_STR[c])
        for r in range(8):
            col = QColor(DARK_SQ) if r % 2 == 0 else QColor(LIGHT_SQ)
            p.setPen(col)
            p.drawText(QRect(2, r * sz + 2, 12, 14),
                       Qt.AlignCenter, RANKS_STR[r])

        # Overlay text (e.g. "Puzzle: …", "Solved!")
        if text_overlay:
            p.fillRect(0, sz * 4 - 25, sz * 8, 50, QColor(0, 0, 0, 200))
            p.setPen(Qt.white)
            p.setFont(QFont("Sans", 16, QFont.Bold))
            p.drawText(QRect(0, sz * 4 - 25, sz * 8, 50),
                       Qt.AlignCenter, text_overlay)

        p.end()
        return pix

    # ── Mouse input ───────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if self.engine.game_over:
            return
        c = int(e.position().x()) // SQ_SIZE
        r = int(e.position().y()) // SQ_SIZE
        if not (0 <= r < 8 and 0 <= c < 8):
            return

        piece = self.engine.board[r][c]

        if self.selected:
            sr, sc = self.selected
            if (r, c) in self.legal_targets:
                info = self.engine.make_move(sr, sc, r, c)
                if info:
                    sfx = ("capture" if info['captured'] != '.'
                           else "castle" if info['castle'] else "move")
                    if info['mate']:
                        sfx = "checkmate"
                    elif info['check']:
                        sfx = "check"
                    self.snd.play(sfx)
                    self.move_made.emit(info['notation'])
            else:
                log(f"Invalid move attempt: ({sr},{sc})->({r},{c})", "INPUT")
            self.selected = None
            self.legal_targets = []
        else:
            if piece != '.' and self.engine.color_of(piece) == self.engine.turn:
                self.selected = (r, c)
                self.legal_targets = self.engine.legal_moves(r, c)
                if not self.legal_targets:
                    self.snd.play("error")
                    self.selected = None
                else:
                    log(f"Selected {piece} at {FILES_STR[c]}{RANKS_STR[r]}, "
                        f"{len(self.legal_targets)} legal moves", "INPUT")
            else:
                if piece != '.':
                    log(f"Cannot select {piece} at {FILES_STR[c]}{RANKS_STR[r]} "
                        f"— not your turn", "INPUT")
        self.update()