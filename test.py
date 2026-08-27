#!/usr/bin/env python3
"""
Chess Puzzle MP4 Generator — Professional Vector Pieces, Random Puzzles, Expanded Filters
pip install PySide6 pandas pyarrow python-chess imageio[ffmpeg] numpy numba cupy-cuda12x
"""

import sys, os, json, math, random
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import pyarrow.dataset as pds
import pyarrow.compute as pc

try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

try:
    import cupy as cp
    HAS_CUPY = True
except ImportError:
    HAS_CUPY = False

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableView, QHeaderView, QLabel, QPushButton, QComboBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QProgressBar,
    QGroupBox, QFormLayout, QLineEdit,
    QAbstractItemView, QMessageBox, QSplitter, QGridLayout,
    QSizePolicy, QTextEdit, QCheckBox, QTabWidget, QFrame
)
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QThread, Signal, QSize,
    QRect, QPointF, QMutex, QSortFilterProxyModel
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QImage,
    QRadialGradient, QPalette, QAction, QMouseEvent, QPainterPath
)

import chess
import imageio.v2 as imageio

# ═══════════════════════════════════════════════════════════
# Numba JIT Accelerated Pixel Manipulation
# ═══════════════════════════════════════════════════════════

if HAS_NUMBA:
    @njit(fastmath=True, cache=True)
    def _apply_highlight_numba(img, x_start, y_start, sq_size, r, g, b, alpha):
        h, w, c = img.shape
        for y in range(y_start, y_start + sq_size):
            if 0 <= y < h:
                for x in range(x_start, x_start + sq_size):
                    if 0 <= x < w:
                        img[y, x, 0] = int(img[y, x, 0] * (1.0 - alpha) + r * alpha)
                        img[y, x, 1] = int(img[y, x, 1] * (1.0 - alpha) + g * alpha)
                        img[y, x, 2] = int(img[y, x, 2] * (1.0 - alpha) + b * alpha)

    @njit(fastmath=True, cache=True)
    def _draw_arrow_numba(img, x1, y1, x2, y2, thickness, r, g, b):
        min_x = max(0, min(x1, x2) - thickness - 5); max_x = min(img.shape[1], max(x1, x2) + thickness + 5)
        min_y = max(0, min(y1, y2) - thickness - 5); max_y = min(img.shape[0], max(y1, y2) + thickness + 5)
        dx = x2 - x1; dy = y2 - y1; len_sq = dx*dx + dy*dy
        if len_sq == 0: return
        for y in range(min_y, max_y):
            for x in range(min_x, max_x):
                t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / len_sq))
                proj_x = x1 + t * dx; proj_y = y1 + t * dy; dist_sq = (x - proj_x)**2 + (y - proj_y)**2
                if t > 0.8:
                    head_scale = (t - 0.8) / 0.2; head_thickness = thickness + head_scale * (thickness * 2)
                    if dist_sq <= head_thickness * head_thickness: img[y, x, 0] = r; img[y, x, 1] = g; img[y, x, 2] = b
                elif dist_sq <= thickness * thickness: img[y, x, 0] = r; img[y, x, 1] = g; img[y, x, 2] = b

# ═══════════════════════════════════════════════════════════
# Chess Renderer - Professional Vector Pieces
# ═══════════════════════════════════════════════════════════

class ChessRenderer:
    LIGHT  = QColor("#F0D9B5");  DARK   = QColor("#B58863"); BG = QColor("#1E1E1E")

    @staticmethod
    def render_base(board, size=720, info="", turn=""):
        img = QImage(size, size, QImage.Format_RGB32); img.fill(ChessRenderer.BG)
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        sq = (size-20)//8; bpx = sq*8; ox = (size-bpx)//2; oy = (size-bpx)//2
        for r in range(8):
            for f in range(8):
                x=ox+f*sq; y=oy+r*sq; col = ChessRenderer.LIGHT if (f+r)%2==0 else ChessRenderer.DARK
                p.fillRect(x,y,sq,sq,col)
        for c in chess.SQUARES:
            pc = board.piece_at(c)
            if pc: fi,ri = chess.square_file(c), chess.square_rank(c); ChessRenderer._piece(p, pc, ox+fi*sq, oy+(7-ri)*sq, sq)
        ChessRenderer._labels(p, ox, oy, sq, bpx)
        if info: p.setPen(QColor("#CCCCCC")); p.setFont(QFont("Inter", 13, QFont.Bold)); p.drawText(QRect(0,4,size,22), Qt.AlignCenter, info)
        if turn: p.setPen(QColor("#888888")); p.setFont(QFont("Inter", 10)); p.drawText(QRect(0,size-20,size,18), Qt.AlignCenter, turn)
        p.end(); return img

    @staticmethod
    def render_title(size, pid, rating, themes, turn):
        img = QImage(size, size, QImage.Format_RGB32); img.fill(ChessRenderer.BG)
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#3A3A3A"), 2)); p.drawRect(20, 20, size-40, size-40)
        p.setPen(QColor("#E0E0E0")); p.setFont(QFont("Inter", 28, QFont.Bold)); p.drawText(QRect(0, size//4 - 40, size, 50), Qt.AlignCenter, f"Puzzle #{pid}")
        p.setFont(QFont("Inter", 20)); p.setPen(QColor("#CCCCCC")); p.drawText(QRect(0, size//4 + 30, size, 40), Qt.AlignCenter, f"Rating: {rating}")
        p.setFont(QFont("Inter", 16)); p.setPen(QColor("#888888")); p.drawText(QRect(50, size//4 + 80, size-100, 80), Qt.AlignCenter | Qt.TextWordWrap, str(themes))
        turn_str = "White to play" if turn == chess.WHITE else "Black to play"
        p.setFont(QFont("Inter", 22, QFont.Bold)); p.setPen(QColor("#3A8FD6")); p.drawText(QRect(0, size//2 + 50, size, 50), Qt.AlignCenter, turn_str)
        p.end(); return img

    @staticmethod
    def _get_piece_path(piece_type):
        path = QPainterPath(); path.setFillRule(Qt.WindingFill)
        if piece_type == chess.PAWN:
            path.addEllipse(20, 80, 60, 12)
            path.moveTo(30, 86); path.lineTo(70, 86); path.lineTo(64, 52); path.lineTo(36, 52); path.closeSubpath()
            path.addEllipse(38, 22, 24, 24)
        elif piece_type == chess.ROOK:
            path.addEllipse(20, 80, 60, 12)
            path.moveTo(28, 86); path.lineTo(72, 86); path.lineTo(70, 38); path.lineTo(30, 38); path.closeSubpath()
            path.addRoundedRect(30, 20, 12, 20, 2, 2)
            path.addRoundedRect(44, 20, 12, 20, 2, 2)
            path.addRoundedRect(58, 20, 12, 20, 2, 2)
        elif piece_type == chess.BISHOP:
            path.addEllipse(20, 80, 60, 12)
            path.moveTo(32, 86); path.lineTo(68, 86); path.lineTo(60, 38); path.lineTo(40, 38); path.closeSubpath()
            path.moveTo(40, 38); path.lineTo(60, 38); path.lineTo(50, 18); path.closeSubpath()
            path.addEllipse(44, 8, 12, 12)
        elif piece_type == chess.QUEEN:
            path.addEllipse(20, 80, 60, 12)
            path.moveTo(28, 86); path.lineTo(72, 86); path.lineTo(68, 42); path.lineTo(32, 42); path.closeSubpath()
            path.moveTo(32, 42); path.lineTo(68, 42); path.lineTo(70, 26); path.lineTo(58, 34)
            path.lineTo(50, 14); path.lineTo(42, 34); path.lineTo(30, 26); path.closeSubpath()
            path.addEllipse(43, 4, 14, 14)
        elif piece_type == chess.KING:
            path.addEllipse(20, 80, 60, 12)
            path.moveTo(30, 86); path.lineTo(70, 86); path.lineTo(66, 40); path.lineTo(34, 40); path.closeSubpath()
            path.addRoundedRect(46, 16, 8, 28, 2, 2)
            path.addRoundedRect(36, 24, 28, 8, 2, 2)
        elif piece_type == chess.KNIGHT:
            path.addEllipse(20, 80, 60, 12)
            path.moveTo(30, 86); path.lineTo(70, 86); path.lineTo(66, 54); path.lineTo(34, 54); path.closeSubpath()
            path.moveTo(34, 54); path.lineTo(66, 54); path.lineTo(68, 36); path.lineTo(56, 30)
            path.lineTo(62, 16); path.lineTo(46, 10); path.lineTo(32, 28); path.closeSubpath()
            path.addEllipse(46, 28, 10, 10) # Eye
        return path

    @staticmethod
    def _piece(p, pc, x, y, sq):
        is_white = pc.color == chess.WHITE; pt = pc.piece_type
        path = ChessRenderer._get_piece_path(pt)
        s = sq / 100.0

        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 35))
        p.save(); p.translate(x + 3, y + 3); p.scale(s, s); p.drawPath(path); p.restore()

        if is_white:
            p.setBrush(QColor("#FFFFFF")); p.setPen(QPen(QColor("#333333"), 3.0))
        else:
            p.setBrush(QColor("#333333")); p.setPen(QPen(QColor("#111111"), 3.0))
        p.save(); p.translate(x, y); p.scale(s, s); p.drawPath(path); p.restore()

        if pt == chess.KNIGHT:
            eye_path = QPainterPath(); eye_path.addEllipse(46, 28, 10, 10)
            p.save(); p.translate(x, y); p.scale(s, s)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#333333") if is_white else QColor("#EEEEEE"))
            p.drawPath(eye_path); p.restore()

    @staticmethod
    def _labels(p, ox, oy, sq, bpx):
        p.setFont(QFont("Inter",max(7,sq//10)))
        for i in range(8):
            il=(i+7)%2==0; p.setPen(QColor("#B58863") if il else QColor("#F0D9B5")); p.drawText(ox+i*sq+sq-8,oy+bpx-3,chr(97+i))
            il2=i%2==0; p.setPen(QColor("#B58863") if il2 else QColor("#F0D9B5")); p.drawText(ox+2,oy+i*sq+12,str(8-i))

    @staticmethod
    def to_numpy(qimg):
        qimg = qimg.convertToFormat(QImage.Format_RGB888); w,h = qimg.width(), qimg.height(); ptr = qimg.bits(); ptr.setsize(h*w*3)
        return np.frombuffer(ptr,dtype=np.uint8).reshape((h,w,3)).copy()

# ═══════════════════════════════════════════════════════════
# Overlay Accelerator
# ═══════════════════════════════════════════════════════════

class OverlayAccelerator:
    def __init__(self, size): self.size = size; self.sq = (size-20)//8; self.ox = (size - self.sq*8)//2; self.oy = self.ox
    def apply_overlays(self, base_arr, highlights, arrows):
        frame = base_arr.copy()
        if HAS_CUPY: self._apply_cupy(frame, highlights, arrows)
        elif HAS_NUMBA: self._apply_numba(frame, highlights, arrows)
        else: self._apply_numpy(frame, highlights, arrows)
        return frame
    def _sq_to_xy(self, sq): f, r = chess.square_file(sq), chess.square_rank(sq); return self.ox + f * self.sq, self.oy + (7 - r) * self.sq
    def _apply_cupy(self, frame, highlights, arrows):
        gpu_frame = cp.asarray(frame); alpha = 0.6; color = cp.array([155, 199, 0], dtype=cp.float32)
        for sq in highlights: x1, y1 = self._sq_to_xy(sq); region = gpu_frame[y1:y1+self.sq, x1:x1+self.sq].astype(cp.float32); gpu_frame[y1:y1+self.sq, x1:x1+self.sq] = (region * (1.0 - alpha) + color * alpha).astype(cp.uint8)
        frame[:] = cp.asnumpy(gpu_frame)
        if arrows and HAS_NUMBA: self._draw_arrows_numba(frame, arrows)
        elif arrows: self._draw_arrows_numpy(frame, arrows)
    def _apply_numba(self, frame, highlights, arrows):
        for sq in highlights: x1, y1 = self._sq_to_xy(sq); _apply_highlight_numba(frame, x1, y1, self.sq, 155, 199, 0, 0.6)
        if arrows: self._draw_arrows_numba(frame, arrows)
    def _draw_arrows_numba(self, frame, arrows):
        t = max(5, self.sq // 10)
        for fsq, tsq in arrows: fx, fy = self._sq_to_xy(fsq); tx, ty = self._sq_to_xy(tsq); x1 = fx + self.sq//2; y1 = fy + self.sq//2; x2 = tx + self.sq//2; y2 = ty + self.sq//2; _draw_arrow_numba(frame, x1, y1, x2, y2, t, 255, 100, 0)
    def _apply_numpy(self, frame, highlights, arrows):
        alpha = 0.6; color = np.array([155, 199, 0], dtype=np.float32)
        for sq in highlights: x1, y1 = self._sq_to_xy(sq); region = frame[y1:y1+self.sq, x1:x1+self.sq].astype(np.float32); frame[y1:y1+self.sq, x1:x1+self.sq] = (region * (1.0 - alpha) + color * alpha).astype(np.uint8)
        if arrows: self._draw_arrows_numpy(frame, arrows)
    def _draw_arrows_numpy(self, frame, arrows):
        for fsq, tsq in arrows: fx, fy = self._sq_to_xy(fsq); tx, ty = self._sq_to_xy(tsq); x1, y1 = fx + self.sq//2, fy + self.sq//2; x2, y2 = tx + self.sq//2, ty + self.sq//2; frame[y1:y1+self.sq, x1:x1+self.sq] = [255, 100, 0]; frame[y2:y2+self.sq, x2:x2+self.sq] = [255, 100, 0]

# ═══════════════════════════════════════════════════════════
# Chess Board Widget
# ═══════════════════════════════════════════════════════════

class ChessBoardWidget(QWidget):
    squareClicked = Signal(chess.Square)

    def __init__(self, parent=None):
        super().__init__(parent); self.board=chess.Board(); self.lastmove=None; self.arrows=[]; self.info="Load DB to begin"; self.turn=""
        self.editor_selected_sq = None
        self.setMinimumSize(380,380); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
    def set_position(self,fen): self.board=chess.Board(fen); self.lastmove=None; self.arrows=[]; self.turn="White to move" if self.board.turn==chess.WHITE else "Black to move"; self.update()
    def set_lastmove(self,m): self.lastmove=m; self.update()
    def set_arrows(self,a): self.arrows=a; self.update()
    def set_info(self,t): self.info=t; self.update()
    def set_turn(self,t): self.turn=t; self.update()
    def clear_hl(self): self.lastmove=None; self.arrows=[]; self.editor_selected_sq=None; self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            sz=min(self.width(),self.height())
            sq_sz = (sz-20)//8; bpx = sq_sz*8; ox = (sz-bpx)//2; oy = (sz-bpx)//2
            x = event.position().x(); y = event.position().y()
            if ox <= x < ox + bpx and oy <= y < oy + bpx:
                file_idx = int((x - ox) // sq_sz); rank_idx = 7 - int((y - oy) // sq_sz)
                if 0 <= file_idx <= 7 and 0 <= rank_idx <= 7:
                    self.squareClicked.emit(chess.square(file_idx, rank_idx))

    def paintEvent(self,_):
        sz=min(self.width(),self.height())
        img=ChessRenderer.render_base(self.board,sz,self.info,self.turn)
        p=QPainter(img); p.setRenderHint(QPainter.Antialiasing)
        if self.lastmove:
            sq = (sz-20)//8; bpx = sq*8; ox = (sz-bpx)//2; oy = ox; hl={self.lastmove.from_square, self.lastmove.to_square}
            for c in hl: f,r = chess.square_file(c), chess.square_rank(c); p.fillRect(ox+f*sq, oy+(7-r)*sq, sq, sq, QColor(155,199,0,130))
        if self.editor_selected_sq is not None:
            sq = (sz-20)//8; bpx = sq*8; ox = (sz-bpx)//2; oy = ox
            f,r = chess.square_file(self.editor_selected_sq), chess.square_rank(self.editor_selected_sq)
            p.setBrush(QColor(100, 180, 255, 100)); p.setPen(Qt.NoPen)
            p.drawRect(ox+f*sq, oy+(7-r)*sq, sq, sq)
        if self.arrows:
            sq = (sz-20)//8; bpx = sq*8; ox = (sz-bpx)//2; oy = ox
            for fsq, tsq in self.arrows:
                fx,fy=chess.square_file(fsq),chess.square_rank(fsq); tx,ty=chess.square_file(tsq),chess.square_rank(tsq)
                x1=ox+fx*sq+sq/2;y1=oy+(7-fy)*sq+sq/2; x2=ox+tx*sq+sq/2;y2=oy+(7-ty)*sq+sq/2
                p.setPen(QPen(QColor(255,100,0,180), max(5,sq//10), Qt.SolidLine, Qt.RoundCap)); p.drawLine(QPointF(x1,y1),QPointF(x2,y2))
        p.end()
        qp=QPainter(self); qp.drawImage((self.width()-sz)//2,(self.height()-sz)//2,img); qp.end()

# ═══════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════

class PaginatedModel(QAbstractTableModel):
    COLS  = ["PuzzleId","Rating","Themes","NbPlays","Popularity","OpeningTags"]
    def __init__(self, parent=None): super().__init__(parent); self._page = pd.DataFrame(columns=self.COLS); self.total_rows = 0
    def set_page(self, df_page, total): self.beginResetModel(); self._page = df_page.reset_index(drop=True); self.total_rows = total; self.endResetModel()
    def rowCount(self,_=QModelIndex()): return len(self._page)
    def columnCount(self,_=QModelIndex()): return len(self.COLS)
    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid(): return None; c=self.COLS[idx.column()]; r=idx.row()
        if r>=len(self._page): return None; v=self._page.iloc[r][c]
        if role==Qt.DisplayRole:
            if c in ("NbPlays",): return f"{int(v):,}" if pd.notna(v) else ""
            return str(v) if pd.notna(v) else ""
        if role==Qt.TextAlignmentRole: return Qt.AlignCenter if c in ("Rating","NbPlays","Popularity") else (Qt.AlignLeft|Qt.AlignVCenter)
        if role==Qt.UserRole: return v
        return None
    def headerData(self,s,o,role=Qt.DisplayRole):
        if role==Qt.DisplayRole: return self.COLS[s] if o==Qt.Horizontal else str(s+1)
    def row_data(self, r): return self._page.iloc[r] if 0<=r<len(self._page) else None

class ManifestManager:
    def __init__(self, path="manifest.json"): self.path=Path(path); self.data=self._load()
    def _load(self):
        if self.path.exists(): 
            try: 
                with open(self.path) as f: return json.load(f)
            except Exception: pass
        return {"puzzles":{},"version":"1.0"}
    def save(self): 
        with open(self.path,"w") as f: json.dump(self.data,f,indent=2,default=str)
    def add(self,pid,info): self.data["puzzles"][pid]={**info,"generated_at":datetime.now().isoformat()}; self.save()
    def has(self,pid): return pid in self.data["puzzles"]
    def get(self,pid): return self.data["puzzles"].get(pid)
    def all(self): return dict(self.data["puzzles"])
    def count(self): return len(self.data["puzzles"])
    def remove(self,pid):
        if pid in self.data["puzzles"]: del self.data["puzzles"][pid]; self.save()

class ManifestModel(QAbstractTableModel):
    COLS = ["PuzzleId","Rating","Themes","Source","GeneratedAt"]
    def __init__(self, parent=None): super().__init__(parent); self._data={}; self._keys=[]
    def refresh(self, d): self.beginResetModel(); self._data=dict(d); self._keys=list(d); self.endResetModel()
    def rowCount(self,_=QModelIndex()): return len(self._keys)
    def columnCount(self,_=QModelIndex()): return len(self.COLS)
    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid() or role!=Qt.DisplayRole: return None; k=self._keys[idx.row()]; info=self._data[k]
        m={"PuzzleId":k,"Rating":info.get("rating",""),"Themes":info.get("themes",""),"Source":info.get("source","DB"),"GeneratedAt":info.get("generated_at","")}
        return str(m.get(self.COLS[idx.column()],""))
    def headerData(self,s,o,role=Qt.DisplayRole):
        if role==Qt.DisplayRole: return self.COLS[s] if o==Qt.Horizontal else str(s+1)
    def pid(self, row): return self._keys[row] if 0<=row<len(self._keys) else None

# ═══════════════════════════════════════════════════════════
# Video Worker
# ═══════════════════════════════════════════════════════════

class VideoWorker(QThread):
    progress = Signal(int,int); status   = Signal(str)
    done     = Signal(str,str);  error    = Signal(str,str)
    def __init__(self, pid, fen, moves_str, rating, themes, out, settings):
        super().__init__()
        self.pid=pid; self.fen=fen; self.moves=moves_str.split() if pd.notna(moves_str) else []
        self.rating=str(rating) if pd.notna(rating) else ""; self.themes=str(themes) if pd.notna(themes) else ""
        self.out=out; self.s=settings; self._cancel=False
    def cancel(self): self._cancel=True

    def run(self):
        try:
            board=chess.Board(self.fen); sz=self.s["resolution"]; fps=self.s["fps"]; accelerator = OverlayAccelerator(sz)
            title_f = max(1, int(fps * self.s["title_seconds"])); start_f = max(1, int(fps * self.s["start_seconds"]))
            move_f  = max(1, int(fps * self.s["move_seconds"]));  arrow_f = max(1, int(fps * self.s["arrow_seconds"]))
            end_f   = max(1, int(fps * self.s["end_seconds"]))
            show_arrows = self.s.get("show_arrows", True); show_hl = self.s.get("show_highlights", True)
            w=imageio.get_writer(self.out,fps=fps,codec="libx264",quality=self.s["quality"],pixelformat="yuv420p",output_params=["-preset","medium"])
            try:
                self.status.emit("Title screen …")
                t_arr = ChessRenderer.to_numpy(ChessRenderer.render_title(sz, self.pid, self.rating, self.themes, board.turn))
                for _ in range(title_f):
                    if self._cancel: raise Exception("Cancelled")
                    w.append_data(t_arr)
                self.status.emit("Starting position …")
                turn = "White to move" if board.turn==chess.WHITE else "Black to move"
                base_arr = ChessRenderer.to_numpy(ChessRenderer.render_base(board, sz, info="Starting Position", turn=turn))
                f = accelerator.apply_overlays(base_arr, highlights=[], arrows=[])
                for _ in range(start_f):
                    if self._cancel: raise Exception("Cancelled")
                    w.append_data(f)
                n = len(self.moves)
                for i, uci in enumerate(self.moves):
                    if self._cancel: raise Exception("Cancelled")
                    move = chess.Move.from_uci(uci); is_puzzle_move = (i % 2 == 1) 
                    if is_puzzle_move and show_arrows:
                        arr = [(move.from_square, move.to_square)]; f = accelerator.apply_overlays(base_arr, highlights=[], arrows=arr)
                        for _ in range(arrow_f):
                            if self._cancel: raise Exception("Cancelled")
                            w.append_data(f)
                    san = board.san(move); board.push(move); turn = "White to move" if board.turn==chess.WHITE else "Black to move"
                    base_arr = ChessRenderer.to_numpy(ChessRenderer.render_base(board, sz, info=f"{'✓' if is_puzzle_move else '→'} {san}", turn=turn))
                    highlights = [move.from_square, move.to_square] if show_hl else []
                    f = accelerator.apply_overlays(base_arr, highlights=highlights, arrows=[])
                    for _ in range(move_f):
                        if self._cancel: raise Exception("Cancelled")
                        w.append_data(f)
                self.status.emit("End position …")
                f = accelerator.apply_overlays(ChessRenderer.to_numpy(ChessRenderer.render_base(board, sz, info="✓ Puzzle Complete!")), highlights=highlights, arrows=[])
                for _ in range(end_f):
                    if self._cancel: raise Exception("Cancelled")
                    w.append_data(f)
                w.close(); self.done.emit(self.pid,self.out)
            except Exception as e:
                w.close()
                if os.path.exists(self.out): os.remove(self.out)
                if "Cancelled" in str(e): return
                raise e
        except Exception as e:
            import traceback; traceback.print_exc(); self.error.emit(self.pid,str(e))

# ═══════════════════════════════════════════════════════════
# Main Window
# ═══════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    PAGE_SIZE = 200
    def __init__(self):
        super().__init__()
        accel_txt = "CuPy (GPU)" if HAS_CUPY else ("Numba (CPU JIT)" if HAS_NUMBA else "NumPy (CPU)")
        self.setWindowTitle(f"Chess Puzzle MP4 Generator — Lazy DB & {accel_txt}"); self.setMinimumSize(1360,860)
        self.ds=None; self.current_puzzle=None; self.move_idx=0; self.puzzle_moves=[]; self.current_filter_expr=None; self.total_rows=0
        self.manifest=ManifestManager(); self.worker=None; self.output_folder=Path("output"); self.output_folder.mkdir(exist_ok=True)
        self.batch_queue=[]; self.batch_i=0; self.batch_running=False
        self.continuous_mode = False; self.fetch_page_idx = 0; self.total_rendered_count = 0
        self.cur_page=0; self.total_pages=0
        self.editor_mode = False; self.editor_board = chess.Board(); self.editor_moves = []; self.editor_selected = None
        self._build_ui(); self._refresh_manifest()

    def _build_ui(self):
        cw=QWidget(); self.setCentralWidget(cw); root=QHBoxLayout(cw); root.setContentsMargins(12,12,12,12); root.setSpacing(12)
        splitter=QSplitter(Qt.Horizontal); splitter.setHandleWidth(1)

        # ─── LEFT: DATABASE ───
        left_widget = QWidget(); left_layout = QVBoxLayout(left_widget); left_layout.setContentsMargins(0,0,0,0); left_layout.setSpacing(10)
        db_btn_layout = QHBoxLayout()
        self.btn_load_db = QPushButton("📂 Load Database")
        self.btn_load_db.setObjectName("generateBtn")
        self.btn_load_db.setStyleSheet("QPushButton { background-color: #2E7D32; font-size: 12px; padding: 8px; } QPushButton:hover { background-color: #388E3C; }")
        self.btn_load_db.clicked.connect(self._load_db)
        self.btn_random = QPushButton("🎲 Random")
        self.btn_random.setObjectName("accentBtn")
        self.btn_random.clicked.connect(self._random_puzzle)
        db_btn_layout.addWidget(self.btn_load_db); db_btn_layout.addWidget(self.btn_random)
        left_layout.addLayout(db_btn_layout)

        filter_group = QGroupBox("Database Filters"); fl = QGridLayout(); fl.setSpacing(6)
        fl.addWidget(QLabel("Rating"),0,0); self.rmin=QSpinBox(); self.rmin.setRange(0,3500); self.rmin.setValue(800); fl.addWidget(self.rmin,0,1)
        self.rmax=QSpinBox(); self.rmax.setRange(0,3500); self.rmax.setValue(1800); fl.addWidget(self.rmax,0,2)
        fl.addWidget(QLabel("Max RD"),0,3); self.rd_max=QSpinBox(); self.rd_max.setRange(0,1000); self.rd_max.setValue(80); self.rd_max.setToolTip("Rating Deviation (lower=stable)"); fl.addWidget(self.rd_max,0,4)
        fl.addWidget(QLabel("Theme"),1,0); self.tcombo=QComboBox(); self.tcombo.setEditable(True); self.tcombo.addItem("All"); fl.addWidget(self.tcombo,1,1,1,2)
        fl.addWidget(QLabel("Opening"),1,3); self.opening_edit=QLineEdit(); self.opening_edit.setPlaceholderText("e.g. Sicilian"); fl.addWidget(self.opening_edit,1,4)
        fl.addWidget(QLabel("Popularity ≥"),2,0); self.pmin=QSpinBox(); self.pmin.setRange(-100,100); self.pmin.setValue(60); fl.addWidget(self.pmin,2,1)
        fl.addWidget(QLabel("Plays ≥"),2,2); self.nmin=QSpinBox(); self.nmin.setRange(0,10_000_000); self.nmin.setValue(500); fl.addWidget(self.nmin,2,3)
        fl.addWidget(QLabel("ID"),2,4); self.sid=QLineEdit(); self.sid.setPlaceholderText("Puzzle ID"); fl.addWidget(self.sid,2,4)
        ab=QPushButton("Apply Filter"); ab.setObjectName("accentBtn"); ab.clicked.connect(self._apply_filter)
        cb=QPushButton("Clear"); cb.clicked.connect(self._clear_filter); fl.addWidget(ab,3,0,1,3); fl.addWidget(cb,3,3,1,2)
        filter_group.setLayout(fl); left_layout.addWidget(filter_group)
        
        self.tmodel=PaginatedModel(); self.tview=QTableView(); self.tview.setModel(self.tmodel)
        self.tview.setSelectionBehavior(QAbstractItemView.SelectRows); self.tview.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tview.setAlternatingRowColors(True); self.tview.verticalHeader().setDefaultSectionSize(28); self.tview.verticalHeader().hide(); self.tview.setShowGrid(False)
        widths=[80,50,160,70,70,140]
        for i,w in enumerate(widths): self.tview.setColumnWidth(i,w)
        self.tview.horizontalHeader().setStretchLastSection(True); self.tview.clicked.connect(self._on_click); left_layout.addWidget(self.tview, stretch=1)
        pg_layout = QHBoxLayout(); pg_layout.setSpacing(4)
        self.b_first=QPushButton("⏮"); self.b_prev=QPushButton("◀"); self.b_next=QPushButton("▶"); self.b_last=QPushButton("⏭")
        for btn in [self.b_first, self.b_prev, self.b_next, self.b_last]: btn.setFixedWidth(30); btn.setObjectName("paginationBtn")
        self.b_first.clicked.connect(lambda:self._goto_page(0)); self.b_prev.clicked.connect(self._prev_page)
        self.b_next.clicked.connect(self._next_page); self.b_last.clicked.connect(self._goto_last)
        self.page_lbl=QLabel("Page 0/0"); self.page_lbl.setAlignment(Qt.AlignCenter)
        self.goto_spin=QSpinBox(); self.goto_spin.setRange(1,1); goto_btn=QPushButton("Go"); goto_btn.setObjectName("paginationBtn"); goto_btn.clicked.connect(self._goto_spin_page)
        self.row_lbl=QLabel("0 puzzles"); self.row_lbl.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        pg_layout.addWidget(self.b_first); pg_layout.addWidget(self.b_prev); pg_layout.addWidget(self.page_lbl); pg_layout.addWidget(self.b_next); pg_layout.addWidget(self.b_last)
        pg_layout.addStretch(); pg_layout.addWidget(self.goto_spin); pg_layout.addWidget(goto_btn); pg_layout.addWidget(self.row_lbl); left_layout.addLayout(pg_layout)
        splitter.addWidget(left_widget)

        # ─── CENTER: WORKSPACE ───
        center_widget = QWidget(); center_layout = QVBoxLayout(center_widget); center_layout.setContentsMargins(0,0,0,0); center_layout.setSpacing(10)
        self.board=ChessBoardWidget(); self.board.squareClicked.connect(self._on_square_clicked); center_layout.addWidget(self.board, stretch=1)
        nav_layout = QHBoxLayout(); nav_layout.setSpacing(4)
        b1=QPushButton("⟲ Reset"); b2=QPushButton("◀ Prev"); b3=QPushButton("Next ▶"); b4=QPushButton("End ⟫")
        for btn in [b1,b2,b3,b4]: btn.setObjectName("navBtn")
        b1.clicked.connect(self._reset); b2.clicked.connect(self._prev); b3.clicked.connect(self._next); b4.clicked.connect(self._end)
        self.mlbl=QLabel("Move 0/0"); self.mlbl.setAlignment(Qt.AlignCenter); self.mlbl.setObjectName("moveLabel")
        nav_layout.addWidget(b1); nav_layout.addWidget(b2); nav_layout.addWidget(self.mlbl); nav_layout.addWidget(b3); nav_layout.addWidget(b4); center_layout.addLayout(nav_layout)
        self.render_btn=QPushButton("🎬  Generate MP4"); self.render_btn.setObjectName("generateBtn"); self.render_btn.clicked.connect(self._render_single); center_layout.addWidget(self.render_btn)
        self.prog=QProgressBar(); self.prog.setVisible(False); self.prog.setTextVisible(True); center_layout.addWidget(self.prog)
        self.stat_lbl=QLabel(""); self.stat_lbl.setAlignment(Qt.AlignCenter); center_layout.addWidget(self.stat_lbl)
        
        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.currentChanged.connect(self._toggle_editor_mode)
        
        # Settings Tab
        settings_tab = QWidget(); st_layout = QFormLayout(settings_tab); st_layout.setSpacing(8)
        self.s_res=QComboBox(); self.s_res.addItems(["480","720","1080"]); self.s_res.setCurrentText("720"); st_layout.addRow("Resolution",self.s_res)
        self.s_fps=QSpinBox(); self.s_fps.setRange(10,60); self.s_fps.setValue(24); st_layout.addRow("FPS",self.s_fps)
        self.s_title=QDoubleSpinBox(); self.s_title.setRange(0.5,15); self.s_title.setValue(2.0); self.s_title.setSingleStep(0.5); st_layout.addRow("Title Screen (s)", self.s_title)
        self.s_start=QDoubleSpinBox(); self.s_start.setRange(0.5,15); self.s_start.setValue(2.0); self.s_start.setSingleStep(0.5); st_layout.addRow("Start Position (s)", self.s_start)
        self.s_arrow=QDoubleSpinBox(); self.s_arrow.setRange(0.5,15); self.s_arrow.setValue(2.0); self.s_arrow.setSingleStep(0.5); st_layout.addRow("Arrow Prompt (s)", self.s_arrow)
        self.s_move=QDoubleSpinBox(); self.s_move.setRange(0.3,10); self.s_move.setValue(1.0); self.s_move.setSingleStep(0.1); st_layout.addRow("Move Animation (s)", self.s_move)
        self.s_end=QDoubleSpinBox(); self.s_end.setRange(0.5,15); self.s_end.setValue(3.0); self.s_end.setSingleStep(0.5); st_layout.addRow("End Position (s)", self.s_end)
        self.s_qual=QComboBox(); self.s_qual.addItems(["3","5","7","10"]); self.s_qual.setCurrentText("5"); st_layout.addRow("Quality (1-10)",self.s_qual)
        self.chk_hl = QCheckBox("Highlight Last Move"); self.chk_hl.setChecked(True); st_layout.addRow(self.chk_hl)
        self.chk_arr = QCheckBox("Show Move Arrows"); self.chk_arr.setChecked(True); st_layout.addRow(self.chk_arr)
        self.workspace_tabs.addTab(settings_tab, "Video Settings")
        
        # Batch Tab
        batch_tab = QWidget(); bt_layout = QVBoxLayout(batch_tab); bt_layout.setSpacing(8); batch_btn_layout = QHBoxLayout()
        self.b_batch=QPushButton("Render Current Page"); self.b_batch.setObjectName("accentBtn"); self.b_batch.clicked.connect(self._batch_page)
        self.b_ball=QPushButton("🔄 Render ALL Filtered"); self.b_ball.setObjectName("generateBtn")
        self.b_ball.setStyleSheet("QPushButton { background-color: #2E7D32; font-size: 12px; padding: 8px; } QPushButton:hover { background-color: #388E3C; }")
        self.b_ball.clicked.connect(self._start_continuous_render)
        self.b_bstop=QPushButton("Stop Batch"); self.b_bstop.clicked.connect(self._stop_batch); self.b_bstop.setEnabled(False)
        batch_btn_layout.addWidget(self.b_batch); batch_btn_layout.addWidget(self.b_ball); batch_btn_layout.addWidget(self.b_bstop); bt_layout.addLayout(batch_btn_layout)
        self.batch_log=QTextEdit(); self.batch_log.setReadOnly(True); self.batch_log.setObjectName("consoleLog"); bt_layout.addWidget(self.batch_log)
        self.workspace_tabs.addTab(batch_tab, "Batch & Loop Render")

        # Editor Tab 
        editor_tab = QWidget(); et_layout = QVBoxLayout(editor_tab); et_layout.setSpacing(6)
        et_layout.addWidget(QLabel("Create custom puzzles by playing moves on the board."))
        fen_layout = QHBoxLayout()
        self.e_fen = QLineEdit(); self.e_fen.setPlaceholderText("Paste FEN here to setup board...")
        fen_load = QPushButton("Load FEN"); fen_load.setObjectName("accentBtn"); fen_load.clicked.connect(self._editor_load_fen)
        fen_layout.addWidget(self.e_fen, stretch=1); fen_layout.addWidget(fen_load); et_layout.addLayout(fen_layout)
        preset_layout = QHBoxLayout()
        std_btn = QPushButton("Standard Start"); std_btn.clicked.connect(self._editor_start_pos)
        clr_btn = QPushButton("Clear Board"); clr_btn.clicked.connect(self._editor_clear_board)
        preset_layout.addWidget(std_btn); preset_layout.addWidget(clr_btn); et_layout.addLayout(preset_layout)
        self.e_moves_lbl = QLabel("Moves: (Play on board to build sequence)")
        self.e_moves_lbl.setWordWrap(True); self.e_moves_lbl.setObjectName("moveLabel"); et_layout.addWidget(self.e_moves_lbl)
        undo_btn = QPushButton("Undo Last Move"); undo_btn.clicked.connect(self._editor_undo); et_layout.addWidget(undo_btn)
        meta_layout = QFormLayout()
        self.e_rating = QSpinBox(); self.e_rating.setRange(0, 3500); self.e_rating.setValue(1500)
        self.e_themes = QLineEdit(); self.e_themes.setPlaceholderText("crushing middlegame short")
        meta_layout.addRow("Rating:", self.e_rating); meta_layout.addRow("Themes:", self.e_themes); et_layout.addLayout(meta_layout)
        gen_btn = QPushButton("🎬 Generate Custom Puzzle MP4"); gen_btn.setObjectName("generateBtn"); gen_btn.clicked.connect(self._editor_generate); et_layout.addWidget(gen_btn)
        et_layout.addStretch(); self.workspace_tabs.addTab(editor_tab, "Puzzle Maker")
        center_layout.addWidget(self.workspace_tabs); splitter.addWidget(center_widget)

        # ─── RIGHT: DETAILS ───
        right_widget = QWidget(); right_layout = QVBoxLayout(right_widget); right_layout.setContentsMargins(0,0,0,0); right_layout.setSpacing(0)
        self.detail_tabs = QTabWidget()
        info_tab = QWidget(); ifl = QFormLayout(info_tab); ifl.setSpacing(6)
        self.i_id=QLabel("-"); self.i_fen=QLabel("-"); self.i_fen.setWordWrap(True); self.i_rat=QLabel("-"); self.i_th=QLabel("-"); self.i_th.setWordWrap(True)
        self.i_mv=QLabel("-"); self.i_mv.setWordWrap(True); self.i_pl=QLabel("-"); self.i_op=QLabel("-"); self.i_op.setWordWrap(True)
        self.i_st=QLabel("-"); self.i_st.setObjectName("statusLabel")
        ifl.addRow("ID",self.i_id); ifl.addRow("FEN",self.i_fen); ifl.addRow("Rating",self.i_rat); ifl.addRow("Themes",self.i_th); ifl.addRow("Moves",self.i_mv); ifl.addRow("Plays",self.i_pl); ifl.addRow("Opening",self.i_op); ifl.addRow("Status",self.i_st); self.detail_tabs.addTab(info_tab, "Puzzle Info")
        manifest_tab = QWidget(); mtl = QVBoxLayout(manifest_tab); mtl.setContentsMargins(0,6,0,0)
        self.mmodel=ManifestModel(); self.mview=QTableView(); self.mview.setModel(self.mmodel); self.mview.setSelectionBehavior(QAbstractItemView.SelectRows); self.mview.setAlternatingRowColors(True); self.mview.verticalHeader().setDefaultSectionSize(24); self.mview.verticalHeader().hide(); self.mview.setShowGrid(False); self.mview.setColumnWidth(0,70); self.mview.setColumnWidth(1,50); self.mview.setColumnWidth(2,120); self.mview.setColumnWidth(3,50)
        mtl.addWidget(self.mview); mbl=QHBoxLayout(); mbr=QPushButton("Remove"); mbr.clicked.connect(self._manifest_remove); mbo=QPushButton("Open Folder"); mbo.clicked.connect(self._open_folder); mbc=QLabel(f"0 videos"); mbc.setObjectName("manifestCount"); mbl.addWidget(mbc); mbl.addStretch(); mbl.addWidget(mbr); mbl.addWidget(mbo); self.manifest_count=mbc; mtl.addLayout(mbl); self.detail_tabs.addTab(manifest_tab, "Manifest")
        right_layout.addWidget(self.detail_tabs); splitter.addWidget(right_widget)
        splitter.setSizes([320,520,320]); root.addWidget(splitter)

    # ──────────── LAZY DATABASE LOADING ────────────
    def _load_db(self):
        f,_=QFileDialog.getOpenFileName(self,"Open puzzle database","","Parquet (*.parquet)")
        if not f: return
        p=Path(f)
        self.statusBar().showMessage(f"Opening {p} …"); QApplication.processEvents()
        try:
            self.ds = pds.dataset(p, format="parquet"); self._populate_themes(); self._apply_filter()
            self.btn_load_db.setText(f"✅ DB: {p.name}")
            self.btn_load_db.setStyleSheet("QPushButton { background-color: #444444; font-size: 11px; padding: 8px; } QPushButton:hover { background-color: #555555; }")
            self.statusBar().showMessage(f"Database ready: {p.name}")
        except Exception as e: QMessageBox.critical(self,"Error",f"Failed to load: {e}")

    def _populate_themes(self):
        self.tcombo.clear(); self.tcombo.addItem("All"); themes=set()
        try:
            table = self.ds.to_table(columns=["Themes"])
            for t in table.column("Themes").to_pylist():
                if t: themes.update(str(t).split())
        except Exception as e: print(f"Error loading themes: {e}")
        for t in sorted(themes): self.tcombo.addItem(t)

    def _apply_filter(self):
        if self.ds is None: return
        self.statusBar().showMessage("Filtering …"); QApplication.processEvents()
        expr = (pc.field("Rating") >= self.rmin.value()) & (pc.field("Rating") <= self.rmax.value())
        expr = expr & (pc.field("Popularity") >= self.pmin.value()) & (pc.field("NbPlays") >= self.nmin.value())
        expr = expr & (pc.field("RatingDeviation") <= self.rd_max.value())
        theme=self.tcombo.currentText().strip()
        if theme and theme!="All": expr = expr & pc.field("Themes").match_substring(theme)
        opening=self.opening_edit.text().strip()
        if opening: expr = expr & pc.field("OpeningTags").match_substring(opening)
        sid=self.sid.text().strip()
        if sid: expr = expr & pc.field("PuzzleId").match_substring(sid)
        self.current_filter_expr = expr; self.total_rows = self.ds.count_rows(filter=expr)
        self.cur_page=0; self._calc_pages(); self._load_page()
        self.row_lbl.setText(f"{self.total_rows:,} puzzles"); self.statusBar().showMessage("Filter applied")

    def _clear_filter(self):
        self.rmin.setValue(0); self.rmax.setValue(3500); self.pmin.setValue(-100); self.nmin.setValue(0)
        self.rd_max.setValue(1000); self.tcombo.setCurrentText("All"); self.sid.clear(); self.opening_edit.clear()
        self._apply_filter()

    def _random_puzzle(self):
        if self.ds is None: QMessageBox.warning(self,"Warning","Load a database first"); return
        self._apply_filter() # Ensure filter is active
        if self.total_rows == 0: return
        offset = random.randint(0, self.total_rows - 1)
        table = self.ds.to_table(columns=PaginatedModel.COLS, filter=self.current_filter_expr, offset=offset, limit=1)
        if table.num_rows > 0:
            row = table.to_pandas().iloc[0]
            self._load_puzzle(row)

    def _calc_pages(self): self.total_pages=max(1,math.ceil(self.total_rows/self.PAGE_SIZE)); self.goto_spin.setRange(1,self.total_pages)
    def _load_page(self):
        if self.ds is None: return
        start=self.cur_page*self.PAGE_SIZE
        page_df = self.ds.to_table(columns=PaginatedModel.COLS, filter=self.current_filter_expr, offset=start, limit=self.PAGE_SIZE).to_pandas()
        self.tmodel.set_page(page_df, self.total_rows)
        self.page_lbl.setText(f"Page {self.cur_page+1}/{self.total_pages}")
        self.b_first.setEnabled(self.cur_page>0); self.b_prev.setEnabled(self.cur_page>0)
        self.b_next.setEnabled(self.cur_page<self.total_pages-1); self.b_last.setEnabled(self.cur_page<self.total_pages-1)

    def _goto_page(self, p): self.cur_page=max(0,min(p,self.total_pages-1)); self._load_page()
    def _prev_page(self): self._goto_page(self.cur_page-1)
    def _next_page(self): self._goto_page(self.cur_page+1)
    def _goto_last(self): self._goto_page(self.total_pages-1)
    def _goto_spin_page(self): self._goto_page(self.goto_spin.value()-1)

    # ──────────── MODE SWITCHING ────────────
    def _toggle_editor_mode(self, index):
        tab_name = self.workspace_tabs.tabText(index)
        self.editor_mode = (tab_name == "Puzzle Maker")
        if self.editor_mode: self._update_editor_board()
        elif self.current_puzzle: self._load_puzzle(self.current_puzzle)

    def _on_click(self, idx):
        rd = self.tmodel.row_data(idx.row())
        if rd is not None:
            if self.editor_mode: self.workspace_tabs.setCurrentIndex(0)
            self._load_puzzle(rd)

    # ──────────── BOARD INTERACTION (DB PREVIEW) ────────────
    def _load_puzzle(self, row):
        self.current_puzzle=row; self.puzzle_moves=row["Moves"].split() if pd.notna(row["Moves"]) else []
        self.move_idx=0; self.board.set_position(row["FEN"]); self.i_id.setText(str(row["PuzzleId"])); self.i_fen.setText(str(row["FEN"]))
        self.i_rat.setText(str(int(row["Rating"]))); self.i_th.setText(str(row.get("Themes",""))); self.i_mv.setText(str(row["Moves"])); self.i_pl.setText(f"{int(row['NbPlays']):,}")
        self.i_op.setText(str(row.get("OpeningTags",""))); self._check_manifest_status(str(row["PuzzleId"]))

    def _check_manifest_status(self, pid):
        if self.manifest.has(pid):
            info = self.manifest.get(pid)
            self.i_st.setText(f"✅ Rendered ({info.get('source','DB')})")
            self.i_st.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self.i_st.setText("Not Rendered")
            self.i_st.setStyleSheet("color: #AAAAAA; font-weight: normal;")

    def _reset(self):
        if self.editor_mode: self._editor_undo_all()
        elif self.current_puzzle is not None: self.move_idx=0; self.board.set_position(self.current_puzzle["FEN"]); self.board.clear_hl(); self.mlbl.setText(f"Move 0/{len(self.puzzle_moves)}")

    def _prev(self):
        if self.editor_mode or not self.current_puzzle or self.move_idx<=0: return
        self.move_idx-=1; self._show_move()

    def _next(self):
        if self.editor_mode or not self.current_puzzle or self.move_idx>=len(self.puzzle_moves): return
        self.move_idx+=1; self._show_move()

    def _end(self):
        if self.editor_mode or not self.current_puzzle: return
        self.move_idx=len(self.puzzle_moves); self._show_move()

    def _show_move(self):
        b=chess.Board(self.current_puzzle["FEN"]); last=None
        for i in range(self.move_idx): m=chess.Move.from_uci(self.puzzle_moves[i]); b.push(m); last=m
        self.board.board=b; self.board.lastmove=last
        if self.move_idx<len(self.puzzle_moves):
            nm=chess.Move.from_uci(self.puzzle_moves[self.move_idx]); self.board.arrows=[(nm.from_square,nm.to_square)]
            self.board.turn="White to move" if b.turn==chess.WHITE else "Black to move"
        else: self.board.arrows=[]; self.board.turn=""
        self.board.info=f"Move {self.move_idx}/{len(self.puzzle_moves)}"; self.mlbl.setText(self.board.info); self.board.update()

    # ──────────── BOARD INTERACTION (PUZZLE MAKER EDITOR) ────────────
    def _on_square_clicked(self, sq):
        if not self.editor_mode: return
        if self.editor_selected is None:
            piece = self.editor_board.piece_at(sq)
            if piece and piece.color == self.editor_board.turn:
                self.editor_selected = sq; self.board.editor_selected_sq = sq; self.board.update()
        else:
            move = chess.Move(self.editor_selected, sq)
            if move not in self.editor_board.legal_moves: move = chess.Move(self.editor_selected, sq, promotion=chess.QUEEN)
            if move in self.editor_board.legal_moves:
                self.editor_moves.append(move.uci()); self.editor_board.push(move)
            self.editor_selected = None; self.board.editor_selected_sq = None; self._update_editor_board()

    def _update_editor_board(self):
        self.e_fen.setText(self.editor_board.fen())
        self.board.board = self.editor_board; self.board.lastmove = self.editor_board.peek() if self.editor_board.move_stack else None
        self.board.arrows = []; self.board.info = "✏️ Editor Mode"
        self.board.turn = "White to move" if self.editor_board.turn == chess.WHITE else "Black to move"
        self.e_moves_lbl.setText(f"Moves: {' '.join(self.editor_moves)}"); self.mlbl.setText(f"Move {len(self.editor_moves)}/{len(self.editor_moves)}"); self.board.update()

    def _editor_load_fen(self):
        fen = self.e_fen.text().strip()
        if fen:
            try: self.editor_board = chess.Board(fen); self.editor_moves = []; self._update_editor_board()
            except ValueError: QMessageBox.warning(self, "Invalid FEN", "Could not parse FEN string.")

    def _editor_start_pos(self): self.editor_board = chess.Board(); self.e_fen.setText(self.editor_board.fen()); self.editor_moves = []; self._update_editor_board()
    def _editor_clear_board(self): self.editor_board = chess.Board(fen="8/8/8/8/8/8/8/8 w - - 0 1"); self.e_fen.setText(self.editor_board.fen()); self.editor_moves = []; self._update_editor_board()

    def _editor_undo(self):
        if self.editor_moves:
            self.editor_moves.pop(); initial_fen = self.e_fen.text().split(" moves ")[0]
            self.editor_board = chess.Board(initial_fen)
            for m in self.editor_moves: self.editor_board.push_uci(m)
            self._update_editor_board()

    def _editor_undo_all(self):
        if self.editor_moves:
            self.editor_moves = []; initial_fen = self.e_fen.text().split(" moves ")[0]
            self.editor_board = chess.Board(initial_fen); self._update_editor_board()

    def _editor_generate(self):
        if not self.editor_moves: QMessageBox.warning(self, "No Moves", "Please play some moves on the board first."); return
        pid = f"custom_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        fen = self.e_fen.text().strip() if self.e_fen.text().strip() else chess.STARTING_FEN
        moves = " ".join(self.editor_moves); rating = self.e_rating.value(); themes = self.e_themes.text().strip()
        self.current_puzzle = {"PuzzleId": pid, "FEN": fen, "Moves": moves, "Rating": rating, "Themes": themes, "NbPlays": 0, "OpeningTags": "Custom"}
        out = self._output_path(pid)
        if self.manifest.has(pid) and os.path.exists(out):
            if QMessageBox.question(self, "Exists", f"Puzzle {pid} already rendered. Overwrite?") != QMessageBox.Yes: return
        self.worker = VideoWorker(pid, fen, moves, rating, themes, out, self._settings())
        self.worker.progress.connect(self._on_progress); self.worker.status.connect(self._on_status)
        self.worker.done.connect(self._on_done); self.worker.error.connect(self._on_error)
        self.prog.setVisible(True); self.render_btn.setEnabled(False)
        self.stat_lbl.setText(f"Rendering Custom {pid} …"); self.worker.start()

    # ──────────── VIDEO GENERATION ────────────
    def _settings(self):
        return {"resolution":int(self.s_res.currentText()),"fps":self.s_fps.value(),"title_seconds":self.s_title.value(),"start_seconds":self.s_start.value(),"move_seconds":self.s_move.value(),"arrow_seconds":self.s_arrow.value(),"end_seconds":self.s_end.value(),"quality":int(self.s_qual.currentText()),"show_arrows":self.chk_arr.isChecked(),"show_highlights":self.chk_hl.isChecked()}
    def _output_path(self, pid): self.output_folder.mkdir(exist_ok=True); return str(self.output_folder / f"puzzle_{pid}.mp4")
    def _render_single(self):
        if self.editor_mode: return
        if self.current_puzzle is None: QMessageBox.warning(self,"Warning","Select a puzzle first"); return
        if self.worker and self.worker.isRunning(): QMessageBox.warning(self,"Warning","A render is already running"); return
        pid=str(self.current_puzzle["PuzzleId"]); out=self._output_path(pid)
        if self.manifest.has(pid) and os.path.exists(out):
            if QMessageBox.question(self,"Exists",f"Puzzle {pid} already rendered. Overwrite?") != QMessageBox.Yes: return
        self.worker=VideoWorker(pid, self.current_puzzle["FEN"], self.current_puzzle["Moves"], self.current_puzzle["Rating"], self.current_puzzle.get("Themes",""), out, self._settings())
        self.worker.progress.connect(self._on_progress); self.worker.status.connect(self._on_status); self.worker.done.connect(self._on_done); self.worker.error.connect(self._on_error)
        self.prog.setVisible(True); self.render_btn.setEnabled(False); self.stat_lbl.setText(f"Rendering {pid} …"); self.worker.start()
    
    def _on_progress(self,c,t): self.prog.setMaximum(t); self.prog.setValue(c)
    def _on_status(self,s): self.stat_lbl.setText(s)
    def _on_done(self,pid,path):
        self.prog.setVisible(False); self.render_btn.setEnabled(True); self.stat_lbl.setText(f"✅ Done: {pid}")
        if self.current_puzzle:
            source = "Custom" if "custom_" in str(pid) else "DB"
            self.manifest.add(pid,{"rating":self.current_puzzle["Rating"],"themes":self.current_puzzle["Themes"],"fen":self.current_puzzle["FEN"],"moves":self.current_puzzle["Moves"],"output_path":path,"source":source})
            self._refresh_manifest(); self._check_manifest_status(pid)
        if self.batch_running: self.total_rendered_count += 1; self._batch_next()
    def _on_error(self,pid,msg):
        self.prog.setVisible(False); self.render_btn.setEnabled(True); self.stat_lbl.setText(f"❌ Error: {pid}"); self.batch_log.append(f"❌ ERROR {pid}: {msg}")
        if self.batch_running: self.total_rendered_count += 1; self._batch_next()

    # ──────────── BATCH & CONTINUOUS LOOP RENDERING ────────────
    def _fetch_and_queue_page(self):
        if self.fetch_page_idx >= self.total_pages: return False
        offset = self.fetch_page_idx * self.PAGE_SIZE
        page_df = self.ds.to_table(columns=PaginatedModel.COLS, filter=self.current_filter_expr, offset=offset, limit=self.PAGE_SIZE).to_pandas()
        skip = 0
        for _, row in page_df.iterrows():
            pid=str(row["PuzzleId"]); out=self._output_path(pid)
            if self.manifest.has(pid) and os.path.exists(out): skip += 1; continue
            self.batch_queue.append({"pid":pid,"fen":row["FEN"],"moves":row["Moves"],"rating":row["Rating"],"themes":str(row.get("Themes","")),"output":out})
        if skip > 0: self.batch_log.append(f"Page {self.fetch_page_idx+1}: Skipped {skip} already rendered")
        self.fetch_page_idx += 1
        return True

    def _batch_page(self):
        if self.ds is None or self.total_rows==0: QMessageBox.warning(self,"Warning","Load a database first"); return
        if self.batch_running: QMessageBox.warning(self,"Warning","A batch is already running"); return
        self.continuous_mode = False
        start=self.cur_page*self.PAGE_SIZE
        page_df = self.ds.to_table(columns=PaginatedModel.COLS, filter=self.current_filter_expr, offset=start, limit=self.PAGE_SIZE).to_pandas()
        self._start_batch(page_df)

    def _start_continuous_render(self):
        if self.ds is None or self.total_rows==0: QMessageBox.warning(self,"Warning","Load a database first"); return
        if self.batch_running: QMessageBox.warning(self,"Warning","A batch is already running"); return
        self.continuous_mode = True; self.fetch_page_idx = 0; self.total_rendered_count = 0
        self.batch_queue = []
        if not self._fetch_and_queue_page(): return
        self._activate_batch_ui(len(self.batch_queue))

    def _start_batch(self, items):
        self.continuous_mode = False; self.batch_queue=[]; skip=0
        for _,row in (items.iterrows() if hasattr(items,'iterrows') else enumerate(items)):
            pid=str(row["PuzzleId"]); out=self._output_path(pid)
            if self.manifest.has(pid) and os.path.exists(out): skip+=1; continue
            self.batch_queue.append({"pid":pid,"fen":row["FEN"],"moves":row["Moves"],"rating":row["Rating"],"themes":str(row.get("Themes","")),"output":out})
        if skip>0: self.batch_log.append(f"Skipped {skip} already rendered")
        if not self.batch_queue: QMessageBox.information(self,"Info","All puzzles already rendered"); return
        self._activate_batch_ui(len(self.batch_queue))

    def _activate_batch_ui(self, initial_count):
        self.batch_i=0; self.batch_running=True; self.b_bstop.setEnabled(True); self.b_batch.setEnabled(False); self.b_ball.setEnabled(False); self.render_btn.setEnabled(False)
        self.batch_log.append(f"━━━ Batch started: {initial_count} initially queued ━━━"); self.prog.setVisible(True)
        self.prog.setMaximum(self.total_rows if self.continuous_mode else initial_count)
        self.prog.setValue(0); self.prog.setFormat("%v / %m")
        self._batch_next()

    def _batch_next(self):
        if self.continuous_mode and len(self.batch_queue) - self.batch_i < 10:
            self._fetch_and_queue_page()
        if self.batch_i >= len(self.batch_queue):
            if self.continuous_mode and self.fetch_page_idx < self.total_pages: pass
            else: self._end_batch(); return

        item=self.batch_queue[self.batch_i]; pid=item["pid"]; total=self.prog.maximum()
        self.stat_lbl.setText(f"Batch {self.total_rendered_count+1}/{total}: {pid}")
        self.prog.setValue(self.total_rendered_count)
        self.batch_log.append(f"▶ [{self.total_rendered_count+1}/{total}] {pid}")
        self.worker=VideoWorker(pid, item["fen"], item["moves"], item["rating"], item["themes"], item["output"], self._settings())
        self.worker.progress.connect(self._batch_progress); self.worker.status.connect(self._on_status); self.worker.done.connect(self._batch_done); self.worker.error.connect(self._batch_error); self.worker.start()

    def _batch_progress(self,c,t): pass
    def _batch_done(self,pid,path):
        item=self.batch_queue[self.batch_i]
        self.manifest.add(pid,{"rating":item["rating"],"themes":item["themes"],"fen":item["fen"],"moves":item["moves"],"output_path":path,"source":"DB"})
        self._refresh_manifest(); self.batch_log.append(f"  ✅ {pid}"); self.batch_i+=1; self._batch_next()
    def _batch_error(self,pid,msg): self.batch_log.append(f"  ❌ {pid}: {msg}"); self.batch_i+=1; self._batch_next()
    def _end_batch(self):
        self.batch_running=False; self.b_bstop.setEnabled(False); self.b_batch.setEnabled(True); self.b_ball.setEnabled(True); self.render_btn.setEnabled(True)
        self.prog.setVisible(False); self.stat_lbl.setText("Batch complete ✅"); self.batch_log.append("━━━ Batch complete ━━━"); self._refresh_manifest()
    def _stop_batch(self):
        self.batch_log.append("⏹ Stopping …")
        if self.worker and self.worker.isRunning(): self.worker.cancel()
        self.batch_running=False; self.b_bstop.setEnabled(False); self.b_batch.setEnabled(True); self.b_ball.setEnabled(True); self.render_btn.setEnabled(True)
        self.prog.setVisible(False); self.stat_lbl.setText("Batch stopped")

    # ──────────── MANIFEST ────────────
    def _refresh_manifest(self): self.mmodel.refresh(self.manifest.all()); self.manifest_count.setText(f"{self.manifest.count()} videos")
    def _manifest_remove(self):
        idxs=self.mview.selectionModel().selectedRows()
        if not idxs: return
        for i in idxs:
            pid=self.mmodel.pid(i.row())
            if pid:
                info=self.manifest.get(pid)
                if info and os.path.exists(info.get("output_path","")): 
                    try: os.remove(info["output_path"])
                    except: pass
                self.manifest.remove(pid)
        self._refresh_manifest()
    def _open_folder(self):
        import subprocess, platform; p=str(self.output_folder.resolve()); s=platform.system()
        if s=="Windows": os.startfile(p)
        elif s=="Darwin": subprocess.Popen(["open",p])
        else: subprocess.Popen(["xdg-open",p])
    def closeEvent(self,ev):
        if self.worker and self.worker.isRunning(): self.worker.cancel(); self.worker.wait(3000)
        self.manifest.save(); ev.accept()

# ═══════════════════════════════════════════════════════════
# Minimalist Professional Stylesheet
# ═══════════════════════════════════════════════════════════
STYLESHEET = """
QMainWindow { background-color: #1E1E1E; }
QWidget { color: #CCCCCC; font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 13px; }
QGroupBox { border: 1px solid #3C3C3C; border-radius: 6px; margin-top: 12px; padding-top: 16px; font-weight: bold; color: #888888; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QPushButton { background-color: #2D2D2D; border: 1px solid #3C3C3C; border-radius: 4px; padding: 6px 16px; color: #CCCCCC; }
QPushButton:hover { background-color: #383838; border-color: #505050; }
QPushButton:pressed { background-color: #404040; }
QPushButton:disabled { background-color: #252525; color: #555555; border-color: #2D2D2D; }
QPushButton#generateBtn { background-color: #0E639C; color: #FFFFFF; font-weight: bold; font-size: 14px; border: none; padding: 10px; border-radius: 6px; }
QPushButton#generateBtn:hover { background-color: #1177BB; }
QPushButton#generateBtn:disabled { background-color: #1A4560; color: #888888; }
QPushButton#accentBtn { background-color: #333333; border: 1px solid #555555; font-weight: bold; }
QPushButton#accentBtn:hover { background-color: #404040; }
QPushButton#paginationBtn, QPushButton#navBtn { background-color: #252525; border: 1px solid #3C3C3C; padding: 4px; font-weight: bold; }
QTableView { background-color: #1E1E1E; alternate-background-color: #252526; border: none; selection-background-color: #094771; selection-color: #FFFFFF; }
QHeaderView::section { background-color: #252526; color: #888888; border: none; border-bottom: 1px solid #3C3C3C; padding: 4px; font-weight: bold; font-size: 12px; }
QTabWidget::pane { border: 1px solid #3C3C3C; border-radius: 4px; background-color: #1E1E1E; }
QTabBar::tab { background-color: #252526; border: 1px solid #3C3C3C; padding: 6px 12px; border-top-left-radius: 4px; border-top-right-radius: 4px; color: #888888; }
QTabBar::tab:selected { background-color: #1E1E1E; border-bottom-color: #1E1E1E; color: #CCCCCC; font-weight: bold; }
QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox { background-color: #2D2D2D; border: 1px solid #3C3C3C; border-radius: 4px; padding: 4px; color: #CCCCCC; }
QComboBox::drop-down { border-left: 1px solid #3C3C3C; }
QComboBox QAbstractItemView { background-color: #2D2D2D; border: 1px solid #3C3C3C; selection-background-color: #094771; }
QTextEdit { background-color: #1E1E1E; border: 1px solid #3C3C3C; border-radius: 4px; color: #CCCCCC; font-family: 'Consolas', 'Courier New', monospace; font-size: 12px; }
QProgressBar { background-color: #2D2D2D; border: none; border-radius: 2px; text-align: center; color: white; font-weight: bold; }
QProgressBar::chunk { background-color: #0E639C; border-radius: 2px; }
QLabel#moveLabel { font-weight: bold; font-size: 14px; color: #E0E0E0; }
QLabel#statusLabel { font-weight: bold; color: #4CAF50; }
QLabel#manifestCount { color: #888888; font-size: 12px; }
QScrollBar:vertical { border: none; background: #1E1E1E; width: 10px; margin: 0px; }
QScrollBar::handle:vertical { background: #4A4A4A; min-height: 20px; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QSplitter::handle { background-color: #3C3C3C; }
"""

def main():
    app=QApplication(sys.argv); app.setStyleSheet(STYLESHEET); win=MainWindow(); win.show(); sys.exit(app.exec())

if __name__=="__main__":
    main()