import os
import math
import chess
from PySide6.QtGui import QPainter, QColor, QFont, QImage, QLinearGradient, QPainterPath, QPen
from PySide6.QtCore import Qt, QRectF, QPointF
from board_renderer import BoardRenderer
from constants import PIECE_SYM, PIECE_VALUES, HAS_NUMBA, GAME_NORMAL, GAME_CHECKMATE, GAME_STALEMATE, GAME_DRAW, GAME_INSUFFICIENT

if HAS_NUMBA: from helpers import _cp2r_numba

class VideoRenderer:
    def __init__(self, board_renderer, w=1920, h=1080, bg_color=QColor(30, 30, 32)):
        self.board_renderer, self.w, self.h, self.bg_color = board_renderer, w, h, bg_color
        self.eval_cp, self.move_text, self.white_name, self.black_name = 0.0, "", "White", "Black"
        self.overlays, self.move_list_text, self.current_move_index = [], [], 0
        self.game_state, self.game_result, self.game_detail = GAME_NORMAL, "", ""
        self.captured_by_white, self.captured_by_black, self.opening_name = [], [], ""

    @staticmethod
    def _cp2r(cp):
        if HAS_NUMBA: return _cp2r_numba(cp)
        if cp >= 10000: return 1.0
        if cp <= -10000: return 0.0
        return 1.0 / (1.0 + math.exp(-0.004 * max(-10000, min(10000, cp))))

    @staticmethod
    def compute_captures(board):
        start_pieces = {(chess.PAWN, chess.WHITE): 8, (chess.KNIGHT, chess.WHITE): 2, (chess.BISHOP, chess.WHITE): 2, (chess.ROOK, chess.WHITE): 2, (chess.QUEEN, chess.WHITE): 1, (chess.PAWN, chess.BLACK): 8, (chess.KNIGHT, chess.BLACK): 2, (chess.BISHOP, chess.BLACK): 2, (chess.ROOK, chess.BLACK): 2, (chess.QUEEN, chess.BLACK): 1}
        current = {(pt, clr): len(board.pieces(pt, clr)) for pt in chess.PIECE_TYPES[:-1] for clr in (chess.WHITE, chess.BLACK)}
        captured_by_white, captured_by_black = [], []
        for pt in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]:
            diff_b = start_pieces.get((pt, chess.BLACK), 0) - current.get((pt, chess.BLACK), 0)
            diff_w = start_pieces.get((pt, chess.WHITE), 0) - current.get((pt, chess.WHITE), 0)
            for _ in range(diff_b): captured_by_white.append((pt, chess.BLACK))
            for _ in range(diff_w): captured_by_black.append((pt, chess.WHITE))
        return captured_by_white, captured_by_black

    def render(self):
        img = QImage(self.w, self.h, QImage.Format_ARGB32); img.fill(self.bg_color)
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        margin, bsz = 40, int(self.h * 0.85); by = (self.h - bsz) // 2
        
        # ── PROFESSIONAL EVALUATION BAR ──────────────────────────
        ebw = max(34, int(bsz * 0.058)); ebx = margin; ratio = self._cp2r(self.eval_cp); wh = max(0, min(bsz, int(bsz * ratio)))
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 60)); p.drawRoundedRect(QRectF(ebx - 1, by + 2, ebw + 2, bsz + 2), 6, 6)
        track_path = QPainterPath(); track_path.addRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5); p.setClipPath(track_path)
        blk = QLinearGradient(ebx, by, ebx, by + bsz); blk.setColorAt(0.0, QColor(55, 55, 60)); blk.setColorAt(1.0, QColor(35, 35, 40)); p.fillRect(QRectF(ebx, by, ebw, bsz), blk)
        if wh > 0:
            wt_y = by + bsz - wh; wg = QLinearGradient(ebx, wt_y, ebx, by + bsz); wg.setColorAt(0.0, QColor(245, 245, 240)); wg.setColorAt(1.0, QColor(230, 230, 225)); p.fillRect(QRectF(ebx, wt_y, ebw, wh), wg)
        p.setPen(Qt.NoPen)
        for cp_val in range(-900, 901, 100):
            r = self._cp2r(cp_val); y = by + bsz - r * bsz
            if by + 8 > y or y > by + bsz - 8: continue
            p.setBrush(QColor(255, 255, 255, 40 if cp_val % 200 == 0 else 20)); p.drawRect(QRectF(ebx + 2, y - 0.5, ebw - 4, 1.0))
        bdy = by + bsz - wh
        if 0 < wh < bsz: p.setPen(QPen(QColor(0, 0, 0, 150), 1.0)); p.drawLine(QPointF(ebx + 2, bdy), QPointF(ebx + ebw - 2, bdy))
        p.setClipping(False); p.setPen(QPen(QColor(20, 20, 22), 1.5)); p.setBrush(Qt.NoBrush); p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5)
        if self.game_state == GAME_NORMAL:
            is_mate = abs(self.eval_cp) >= 10000; txt = (f"M{int(abs(self.eval_cp) - 10000)}" if self.eval_cp > 0 else f"-M{int(abs(self.eval_cp) - 10000)}") if is_mate else f"{self.eval_cp / 100.0:+.1f}"
            efsz = max(9, min(14, int(ebw * 0.38))); efnt = QFont("Segoe UI", efsz, QFont.Bold); p.setFont(efnt); efm = p.fontMetrics(); etw = efm.horizontalAdvance(txt) + 14; eth = efm.height() + 6
            pill_y = max(by + 4, min(by + bsz - eth - 4, bdy - eth / 2)); pill_rect = QRectF(ebx + (ebw - etw)/2, pill_y, etw, eth)
            on_white = (pill_y + eth / 2) > bdy
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 50)); p.drawRoundedRect(pill_rect.adjusted(1, 1, 1, 1), eth/2, eth/2)
            p.setBrush(QColor(240, 240, 235, 210) if on_white else QColor(40, 40, 45, 210)); p.drawRoundedRect(pill_rect, eth/2, eth/2)
            p.setPen(QColor(30, 30, 30) if on_white else QColor(220, 220, 220)); p.drawText(pill_rect, Qt.AlignCenter, txt)
        else: self._draw_video_eval_game_state(p, ebx, by, ebw, bsz, wh)

        # ── BOARD ────────────────────────────────────────────────
        bx_board = ebx + ebw + margin; bimg = self.board_renderer.render(bsz); p.drawImage(QRectF(bx_board, by, bsz, bsz), bimg)

        # ── AUTO-SCROLLING MOVE LIST ─────────────────────────────
        mx, mw = bx_board + bsz + margin, self.w - (bx_board + bsz + margin) - margin
        if mw > 80:
            # Panel Background
            p.setBrush(QColor(35, 35, 40)); p.setPen(QPen(QColor(50, 50, 55), 1)); p.drawRoundedRect(QRectF(mx, by, mw, bsz), 8, 8)
            
            # Header
            header_y = by + 10
            if self.opening_name: p.setFont(QFont("Segoe UI", max(10, int(self.h * 0.014)), QFont.Bold)); p.setPen(QColor(140, 180, 220)); p.drawText(QRectF(mx + 10, header_y, mw - 20, 22), Qt.AlignLeft, self.opening_name); header_y += 24
            
            # Column Headers
            col_header_y = header_y; header_h = 24
            p.setFont(QFont("Consolas", max(9, int(self.h * 0.012)))); p.setPen(QColor(90, 90, 100))
            p.drawText(QRectF(mx + 10, col_header_y, 35, header_h), Qt.AlignLeft, "#"); p.drawText(QRectF(mx + 45, col_header_y, 65, header_h), Qt.AlignLeft, "White"); p.drawText(QRectF(mx + 115, col_header_y, 65, header_h), Qt.AlignLeft, "Black")
            col_header_y += header_h
            
            # Separator
            p.setPen(QPen(QColor(50, 50, 55), 1)); p.drawLine(QPointF(mx + 8, col_header_y), QPointF(mx + mw - 8, col_header_y))
            
            # Scrolling Calculation
            lh = max(22, int(self.h * 0.025))
            moves_start_y = col_header_y + 4
            visible_h = by + bsz - moves_start_y - 10
            
            p.save()
            p.setClipRect(QRectF(mx, moves_start_y, mw, visible_h))
            
            current_line = self.current_move_index // 2 if self.current_move_index >= 0 else 0
            target_y = current_line * lh
            total_lines = math.ceil(len(self.move_list_text) / 2) if self.move_list_text else 1
            max_scroll = max(0, total_lines * lh - visible_h)
            desired_scroll = target_y - (visible_h * 0.4) # Keep current move roughly in middle
            scroll_offset = max(0, min(max_scroll, desired_scroll))
            
            list_y = moves_start_y - scroll_offset
            fnt_move = QFont("Consolas", max(10, int(self.h * 0.013))); fnt_num = QFont("Consolas", max(9, int(self.h * 0.012)))
            
            for i, san in enumerate(self.move_list_text):
                row = i // 2
                y_pos = list_y + row * lh
                
                if y_pos + lh < moves_start_y or y_pos > moves_start_y + visible_h: continue # Skip off-screen
                
                is_current = (i == self.current_move_index)
                
                if is_current: 
                    p.setPen(Qt.NoPen); p.setBrush(QColor(60, 120, 200, 50)); p.drawRoundedRect(QRectF(mx + 4, y_pos - 1, mw - 8, lh + 2), 4, 4)
                    
                if i % 2 == 0: 
                    p.setFont(fnt_num); p.setPen(QColor(100, 100, 110)); p.drawText(QRectF(mx + 10, y_pos, 30, lh), Qt.AlignLeft, f"{row + 1}.")
                    
                p.setFont(fnt_move); p.setPen(QColor(130, 200, 255) if is_current else QColor(210, 210, 210))
                if i % 2 == 0: p.drawText(QRectF(mx + 45, y_pos, 65, lh), Qt.AlignLeft, san)
                else: p.drawText(QRectF(mx + 115, y_pos, 65, lh), Qt.AlignLeft, san)
                
            p.restore()

        # ── PLAYERS & CAPTURES ───────────────────────────────────
        name_font_sz = max(14, int(self.h * 0.026)); p.setFont(QFont("Segoe UI", name_font_sz, QFont.Bold))
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 20)); black_rect = QRectF(bx_board, by - 60, bsz, 50); p.drawRoundedRect(black_rect, 6, 6)
        p.setPen(QColor(220, 220, 220)); p.drawText(QRectF(bx_board + 12, by - 54, bsz / 2, 24), Qt.AlignLeft | Qt.AlignVCenter, self.black_name)
        if self.captured_by_white: cap_str = "".join(PIECE_SYM.get((pt, clr), "") for pt, clr in self.captured_by_white); p.setFont(QFont("Segoe UI Symbol", max(9, int(self.h * 0.016)))); p.setPen(QColor(180, 180, 180)); p.drawText(QRectF(bx_board + bsz / 2, by - 54, bsz / 2 - 12, 24), Qt.AlignRight | Qt.AlignVCenter, cap_str)
        p.setFont(QFont("Segoe UI", name_font_sz, QFont.Bold)); p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 20)); white_rect = QRectF(bx_board, by + bsz + 6, bsz, 50); p.drawRoundedRect(white_rect, 6, 6)
        p.setPen(QColor(255, 255, 255)); p.drawText(QRectF(bx_board + 12, by + bsz + 12, bsz / 2, 24), Qt.AlignLeft | Qt.AlignVCenter, self.white_name)
        if self.captured_by_black: cap_str = "".join(PIECE_SYM.get((pt, clr), "") for pt, clr in self.captured_by_black); p.setFont(QFont("Segoe UI Symbol", max(9, int(self.h * 0.016)))); p.setPen(QColor(180, 180, 180)); p.drawText(QRectF(bx_board + bsz / 2, by + bsz + 12, bsz / 2 - 12, 24), Qt.AlignRight | Qt.AlignVCenter, cap_str)

        if self.game_state != GAME_NORMAL: self._draw_video_result_banner(p, bx_board, by, bsz)
        for ov in self.overlays:
            if os.path.exists(ov["path"]): oi = QImage(ov["path"]); 
            if not oi.isNull(): p.drawImage(QRectF(ov["x"], ov["y"], ov["w"], ov["h"]), oi)
        p.end(); return img

    def _draw_video_eval_game_state(self, p, ebx, by, ebw, bsz, wh):
        if self.game_state == GAME_CHECKMATE:
            white_wins = self.eval_cp > 0 or self.game_result == "1-0"
            p.setPen(Qt.NoPen); p.setBrush(QColor(25, 160, 55, 40) if white_wins else QColor(190, 35, 35, 40)); p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5)
            center_y, bh_b = by + bsz / 2, max(40, int(bsz * 0.10)); banner = QRectF(ebx - 4, center_y - bh_b / 2, ebw + 8, bh_b); bg = QColor(25, 140, 55, 220) if white_wins else QColor(190, 35, 35, 220); p.setBrush(QColor(0, 0, 0, 70)); p.drawRoundedRect(banner.adjusted(2, 2, 2, 2), 6, 6); p.setBrush(bg); p.setPen(QPen(QColor(255, 255, 255, 50), 0.8)); p.drawRoundedRect(banner, 6, 6); p.setFont(QFont("Segoe UI", max(8, int(bh_b * 0.4)), QFont.Bold)); p.setPen(QColor(255, 255, 255)); p.drawText(banner, Qt.AlignCenter, self.game_result or ("1-0" if white_wins else "0-1"))
        elif self.game_state in (GAME_STALEMATE, GAME_DRAW, GAME_INSUFFICIENT):
            p.setPen(Qt.NoPen); p.setBrush(QColor(180, 150, 40, 20)); p.drawRoundedRect(QRectF(ebx, by, ebw, bsz), 5, 5); center_y = by + bsz / 2; p.setPen(QPen(QColor(220, 190, 60, 130), 2.0)); p.drawLine(QPointF(ebx + 2, center_y), QPointF(ebx + ebw - 2, center_y)); bh_b = max(50, int(bsz * 0.12)); banner = QRectF(ebx - 4, center_y - bh_b / 2, ebw + 8, bh_b); bg = QColor(180, 150, 40, 210) if self.game_state == GAME_STALEMATE else QColor(100, 100, 110, 200); p.setBrush(QColor(0, 0, 0, 60)); p.drawRoundedRect(banner.adjusted(2, 2, 2, 2), 6, 6); p.setBrush(bg); p.setPen(QPen(QColor(255, 255, 255, 45), 0.8)); p.drawRoundedRect(banner, 6, 6); p.setFont(QFont("Segoe UI", max(8, int(bh_b * 0.35)), QFont.Bold)); p.setPen(QColor(255, 255, 255)); p.drawText(QRectF(banner.x(), banner.y(), banner.width(), banner.height() * 0.55), Qt.AlignCenter, self.game_result or "½-½"); detail_map = {GAME_STALEMATE: "STALEMATE", GAME_INSUFFICIENT: "INSUFF.", GAME_DRAW: "DRAW"}; p.setFont(QFont("Segoe UI", max(6, int(bh_b * 0.2)))); p.setPen(QColor(255, 255, 255, 180)); p.drawText(QRectF(banner.x(), banner.y() + banner.height() * 0.5, banner.width(), banner.height() * 0.5), Qt.AlignCenter, self.game_detail or detail_map.get(self.game_state, "DRAW"))

    def _draw_video_result_banner(self, p, bx, by, bsz):
        banner_h, banner_y = int(self.h * 0.06), by + bsz + 65; banner = QRectF(bx, banner_y, bsz, banner_h)
        if self.game_state == GAME_CHECKMATE: white_wins = self.eval_cp > 0 or self.game_result == "1-0"; bg = QColor(25, 140, 55, 210) if white_wins else QColor(190, 35, 35, 210); txt = f"♔ CHECKMATE  {self.game_result or '1-0'}" if white_wins else f"♚ CHECKMATE  {self.game_result or '0-1'}"
        else: bg = QColor(160, 140, 40, 200); detail = self.game_detail or ""; txt = f"½-½  {detail}" if detail else "½-½  DRAW"
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 80)); p.drawRoundedRect(banner.adjusted(2, 2, 2, 2), 6, 6); p.setBrush(bg); p.setPen(QPen(QColor(255, 255, 255, 50), 1.0)); p.drawRoundedRect(banner, 6, 6); p.setFont(QFont("Segoe UI", max(10, int(banner_h * 0.45)), QFont.Bold)); p.setPen(QColor(255, 255, 255, 240)); p.drawText(banner, Qt.AlignCenter, txt)