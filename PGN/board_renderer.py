import chess
from PySide6.QtGui import QPainter, QColor, QFont, QImage, QPen, QFontMetrics
from PySide6.QtCore import Qt, QRectF
from constants import PIECE_SYM, BoardTheme

class BoardRenderer:
    def __init__(self, board=None, theme=None, flipped=False):
        self.board = board or chess.Board(); self.theme = theme or BoardTheme(); self.flipped = flipped
        self.show_coords = True; self.selected_sq = None; self.legal_targets = []
        self.last_move = None; self.highlighted = set(); self.arrows = []
        self.anim_move = None; self.anim_rook_move = None; self.anim_progress = 1.0
        self._check_square = None; self._check_opacity = 0.0; self._flash_squares = (); self._flash_opacity = 0.0

    def render(self, size=1080):
        img = QImage(size, size, QImage.Format_ARGB32); img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        m = size * 0.05 if self.show_coords else 0; sz = (size - 2 * m) / 8; self._paint(p, size, m, sz); p.end(); return img

    def _sq_rect(self, sq, t, m, sz):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        c = (7 - f) if self.flipped else f; rw = r if self.flipped else (7 - r)
        return QRectF(m + c * sz, m + rw * sz, sz, sz)

    def _paint(self, p, t, m, sz):
        p.fillRect(QRectF(0, 0, t, t), self.theme.bg); p.setPen(Qt.NoPen); p.setBrush(self.theme.border); p.drawRect(QRectF(0, 0, t, t))
        for s in chess.SQUARES:
            rect = self._sq_rect(s, t, m, sz); f, r = chess.square_file(s), chess.square_rank(s)
            base = self.theme.light_sq if (f + r) % 2 == 0 else self.theme.dark_sq; p.fillRect(rect, base)
            if self.last_move and s in (self.last_move.from_square, self.last_move.to_square): p.fillRect(rect, self.theme.last_move)
            if s == self.selected_sq: p.fillRect(rect, self.theme.highlight)
            if s in self.highlighted: p.fillRect(rect, QColor(0, 130, 255, 80))
        if self._flash_squares and self._flash_opacity > 0:
            for fsq in self._flash_squares: p.fillRect(self._sq_rect(fsq, t, m, sz), QColor(255, 255, 180, int(self._flash_opacity * 140)))
        if self._check_square is not None and self._check_opacity > 0: p.fillRect(self._sq_rect(self._check_square, t, m, sz), QColor(255, 30, 30, int(self._check_opacity * 130)))
        if self.show_coords:
            fnt = QFont("Arial", max(7, int(sz * 0.14))); fnt.setBold(True); p.setFont(fnt); p.setPen(self.theme.coord)
            for i in range(8):
                fl = chr(ord("h") - i if self.flipped else ord("a") + i); rn = str(i + 1 if self.flipped else 8 - i)
                p.drawText(QRectF(m + i * sz + sz / 2 - sz / 2, t - m, sz, m), Qt.AlignCenter, fl); p.drawText(QRectF(0, m + i * sz, m, sz), Qt.AlignCenter, rn)
        for mv in self.legal_targets:
            rect = self._sq_rect(mv, t, m, sz); p.setPen(Qt.NoPen)
            if self.board.piece_at(mv): p.setBrush(QColor(0, 0, 0, 60)); p.drawEllipse(rect.adjusted(sz * 0.1, sz * 0.1, -sz * 0.1, -sz * 0.1))
            else: p.setBrush(QColor(0, 0, 0, 40)); p.drawEllipse(rect.center(), sz * 0.15, sz * 0.15)
        ats = self.anim_move.to_square if self.anim_move else None; rts = self.anim_rook_move[1] if self.anim_rook_move else None
        for s in chess.SQUARES:
            pc = self.board.piece_at(s)
            if pc:
                if self.anim_move and s == ats: continue
                if self.anim_rook_move and s == rts: continue
                self._draw_piece(p, pc, self._sq_rect(s, t, m, sz), sz)
        if self.anim_move:
            pc = self.board.piece_at(self.anim_move.to_square)
            if pc: pr = self.anim_progress; rf, rt = self._sq_rect(self.anim_move.from_square, t, m, sz), self._sq_rect(self.anim_move.to_square, t, m, sz); self._draw_piece(p, pc, QRectF(rf.x() + (rt.x() - rf.x()) * pr, rf.y() + (rt.y() - rf.y()) * pr, sz, sz), sz)
        if self.anim_rook_move:
            rfs, rts_val = self.anim_rook_move; pc = self.board.piece_at(rts_val)
            if pc: pr = self.anim_progress; rf, rt = self._sq_rect(rfs, t, m, sz), self._sq_rect(rts_val, t, m, sz); self._draw_piece(p, pc, QRectF(rf.x() + (rt.x() - rf.x()) * pr, rf.y() + (rt.y() - rf.y()) * pr, sz, sz), sz)

    def _draw_piece(self, p, piece, rect, sz):
        sym = PIECE_SYM.get((piece.piece_type, piece.color), "?")
        for family in ["Segoe UI Symbol", "Arial Unicode MS", "DejaVu Sans", "Noto Sans", "Arial"]:
            fnt = QFont(family, sz * 0.72); fnt.setStyleStrategy(QFont.PreferAntialias); fm = QFontMetrics(fnt)
            if fm.inFont(sym) or family == "Arial": p.setFont(fnt); break
        if piece.color == chess.WHITE: p.setPen(QPen(QColor(0, 0, 0, 200), max(1, sz * 0.04))); p.drawText(rect, Qt.AlignCenter, sym); p.setPen(QColor(255, 255, 255)); p.drawText(rect, Qt.AlignCenter, sym)
        else: p.setPen(QColor(30, 30, 30)); p.drawText(rect, Qt.AlignCenter, sym)