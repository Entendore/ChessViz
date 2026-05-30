"""
board_widget.py — Interactive chess board widget. Delegates rendering to rendering.py.
"""

import chess, time
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPainter, QPixmap

from config import SQ_SIZE, ANIM_SPEED_DEFAULT, ANIM_FPS, THEMES, log
from rendering import render_board_image


def _ease_out_cubic(t):
    return 1.0 - (1.0 - t) ** 3


class ChessBoardWidget(QWidget):
    move_made = Signal(str)

    def __init__(self, engine, sound_mgr, parent=None):
        super().__init__(parent)
        self.engine = engine; self.snd = sound_mgr
        self.selected = None; self.legal_targets = []
        self.flipped = False
        self.setFixedSize(SQ_SIZE * 8, SQ_SIZE * 8); self.setMouseTracking(True)
        self.animating = False; self.anim_from = None; self.anim_to = None
        self.anim_piece_obj = None
        self.anim_captured = '.'; self.anim_progress = 0.0
        self.anim_speed = ANIM_SPEED_DEFAULT
        self.anim_start_time = 0.0; self.pending_notation = None
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(1000 // ANIM_FPS)
        self._anim_timer.timeout.connect(self._anim_tick)
        self.current_theme = THEMES["Classic"]
        # NEW: flag to block user interaction during auto-play
        self.auto_playing = False

    def flip(self):
        self.flipped = not self.flipped; self.update()

    def start_animation(self, fr, fc, tr, tc, piece_obj, captured='.', notation=''):
        # NEW: safely finish any previous animation before starting a new one
        if self.animating:
            self._anim_timer.stop()
            self.animating = False
            self.anim_piece_obj = None
            # Silently discard the old pending notation so it won't
            # fire a stale move_made signal that could double-advance
            self.pending_notation = None
        self.animating = True; self.anim_from = (fr, fc)
        self.anim_to = (tr, tc); self.anim_piece_obj = piece_obj
        self.anim_captured = captured; self.anim_progress = 0.0
        self.anim_start_time = time.perf_counter()
        self.pending_notation = notation; self._anim_timer.start()

    def _anim_tick(self):
        elapsed = time.perf_counter() - self.anim_start_time
        duration = self.anim_speed / 1000.0
        self.anim_progress = min(1.0, elapsed / duration) if duration > 0 else 1.0
        self.update()
        if self.anim_progress >= 1.0:
            self._anim_timer.stop(); self.animating = False
            self.anim_piece_obj = None; self.update()
            if self.pending_notation:
                self.move_made.emit(self.pending_notation)
                self.pending_notation = None

    def _get_anim_state(self):
        if not self.animating: return None
        t = _ease_out_cubic(self.anim_progress)
        return {'from': self.anim_from, 'to': self.anim_to,
                'piece_obj': self.anim_piece_obj,
                'captured': self.anim_captured, 'progress': t}

    def paintEvent(self, e):
        chk = self.engine.check_squares()
        img = render_board_image(
            self.engine.board, self.engine.last_move,
            self.selected, self.legal_targets,
            check_squares=chk, anim_state=self._get_anim_state(),
            theme=self.current_theme, flipped=self.flipped)
        painter = QPainter(self)
        painter.drawPixmap(0, 0, QPixmap.fromImage(img))
        painter.end()

    def mousePressEvent(self, e):
        # NEW: also block during auto-play
        if self.animating or self.engine.game_over or self.auto_playing: return
        sc = int(e.position().x()) // SQ_SIZE
        sr = int(e.position().y()) // SQ_SIZE
        if not (0 <= sr < 8 and 0 <= sc < 8): return
        r, c = (7 - sr, 7 - sc) if self.flipped else (sr, sc)
        sq = self.engine.rc_to_sq(r, c)
        piece = self.engine.board.piece_at(sq)
        if self.selected:
            selr, selc = self.selected
            if (r, c) in self.legal_targets:
                info = self.engine.make_move(selr, selc, r, c)
                if info:
                    is_capture = info['captured'] != '.'
                    sfx = ("capture" if is_capture
                           else "castle" if info['castle'] else "move")
                    if info['mate']: sfx = "checkmate"
                    elif info['check']: sfx = "check"
                    self.snd.play(sfx)
                    if self.anim_speed > 0:
                        self.start_animation(selr, selc, r, c,
                                             info['piece_obj'],
                                             info['captured'],
                                             info['notation'])
                    else:
                        self.move_made.emit(info['notation'])
            self.selected = None; self.legal_targets = []
        else:
            if piece and piece.color == self.engine.board.turn:
                self.selected = (r, c)
                self.legal_targets = self.engine.legal_moves(r, c)
                if not self.legal_targets:
                    self.snd.play("error"); self.selected = None
        self.update()