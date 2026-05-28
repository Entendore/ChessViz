#!/usr/bin/env python3
"""
Chess Learning App with CSV/Parquet/DuckDB/SQLite Opening Loader — PySide6
Install:  pip install PySide6 numpy imageio[ffmpeg]
Optional: pip install pandas pyarrow duckdb
"""

import sys, os, wave, struct, math, tempfile, random, re, csv, ast, base64, sqlite3
from pathlib import Path

# ── FIX: Increase CSV field size limit for large fields (e.g., embedded images) ──
csv.field_size_limit(2**31 - 1)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QComboBox, QTextEdit,
    QFileDialog, QGroupBox, QGridLayout, QSplitter, QFrame,
    QScrollArea, QListWidget, QListWidgetItem,
    QSizePolicy, QDialog, QDialogButtonBox
)
from PySide6.QtCore import Qt, QRect, QSize, Signal, QUrl, QTimer, QMargins, QThread
from PySide6.QtGui import (QPainter, QColor, QFont, QPen, QPixmap,
                            QImage, QFontMetrics, QIcon)
from PySide6.QtMultimedia import QSoundEffect

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

HAS_IMAGEIO = False
try:
    import imageio.v3 as iio
    HAS_IMAGEIO = True
except Exception:
    pass

# Optional dependencies for advanced database formats
HAS_PANDAS = False
HAS_PYARROW = False
HAS_DUCKDB = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    pass

if not HAS_PANDAS:
    try:
        import pyarrow.parquet as pq
        HAS_PYARROW = True
    except ImportError:
        pass

try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    pass


# ── Logging helper ────────────────────────────────────────────────────────────
def log(msg, level="INFO"):
    """Print a timestamped log message to the terminal."""
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{level}] {msg}", flush=True)

# ── Constants ─────────────────────────────────────────────────────────────────
SQ_SIZE = 68
LIGHT_SQ  = QColor("#F0D9B5")
DARK_SQ   = QColor("#B58863")
SEL_COL   = QColor(106, 175, 228, 160)
MOVE_DOT  = QColor(0, 0, 0, 60)
CAP_RING  = QColor(0, 0, 0, 50)
LAST_COL  = QColor(205, 210, 106, 130)
CHECK_COL = QColor(235, 97, 80, 170)
UNICODE_PIECES = {
    'K':'♔','Q':'♕','R':'♖','B':'♗','N':'♘','P':'♙',
    'k':'♚','q':'♛','r':'♜','b':'♝','n':'♞','p':'♟'
}
FILES_STR = 'abcdefgh'
RANKS_STR = '87654321'
PIECE_VAL = {'P':100,'N':320,'B':330,'R':500,'Q':900,'K':20000}
PST = {
    'P':[[0,0,0,0,0,0,0,0],[50,50,50,50,50,50,50,50],[10,10,20,30,30,20,10,10],
         [5,5,10,25,25,10,5,5],[0,0,0,20,20,0,0,0],[5,-5,-10,0,0,-10,-5,5],
         [5,10,10,-20,-20,10,10,5],[0,0,0,0,0,0,0,0]],
    'N':[[-50,-40,-30,-30,-30,-30,-40,-50],[-40,-20,0,0,0,0,-20,-40],
         [-30,0,10,15,15,10,0,-30],[-30,5,15,20,20,15,5,-30],
         [-30,0,15,20,20,15,0,-30],[-30,5,10,15,15,10,5,-30],
         [-40,-20,0,5,5,0,-20,-40],[-50,-40,-30,-30,-30,-30,-40,-50]],
    'B':[[-20,-10,-10,-10,-10,-10,-10,-20],[-10,0,0,0,0,0,0,-10],
         [-10,0,10,10,10,10,0,-10],[-10,5,5,10,10,5,5,-10],
         [-10,0,5,10,10,5,0,-10],[-10,10,5,10,10,5,10,-10],
         [-10,5,0,0,0,0,5,-10],[-20,-10,-10,-10,-10,-10,-10,-20]],
    'R':[[0,0,0,0,0,0,0,0],[5,10,10,10,10,10,10,5],[-5,0,0,0,0,0,0,-5],
         [-5,0,0,0,0,0,0,-5],[-5,0,0,0,0,0,0,-5],[-5,0,0,0,0,0,0,-5],
         [-5,0,0,0,0,0,0,-5],[0,0,0,5,5,0,0,0]],
    'Q':[[-20,-10,-10,-5,-5,-10,-10,-20],[-10,0,0,0,0,0,0,-10],
         [-10,0,5,5,5,5,0,-10],[-5,0,5,5,5,5,0,-5],
         [0,0,5,5,5,5,0,-5],[-10,5,5,5,5,5,0,-10],
         [-10,0,5,0,0,0,0,-10],[-20,-10,-10,-5,-5,-10,-10,-20]],
    'K':[[-30,-40,-40,-50,-50,-40,-40,-30],[-30,-40,-40,-50,-50,-40,-40,-30],
         [-30,-40,-40,-50,-50,-40,-40,-30],[-30,-40,-40,-50,-50,-40,-40,-30],
         [-20,-30,-30,-40,-40,-30,-30,-20],[-10,-20,-20,-20,-20,-20,-20,-10],
         [20,20,0,0,0,0,20,20],[20,30,10,0,0,10,30,20]],
}

# ── Puzzles ───────────────────────────────────────────────────────────────────
PUZZLES = [
    {
        "name": "Scholar's Mate",
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4",
        "moves": [((3,7),(1,5))], # Qh5xf7#
        "desc": "White checkmates in one move using the Queen.\n\nThe f7 pawn is only defended by the King. Qxf7# is checkmate!"
    },
    {
        "name": "Back Rank Mate",
        "fen": "6k1/5ppp/8/8/8/8/8/R3K3 w Q - 0 1",
        "moves": [((7,0),(0,0))], # Ra1-a8#
        "desc": "White's Rook delivers a back rank mate.\n\nThe Black King is trapped behind its own pawns. Ra8# is checkmate!"
    },
    {
        "name": "Ladder Mate",
        "fen": "8/8/8/8/8/1k6/8/R3K3 w Q - 0 1",
        "moves": [((7,0),(0,0))], # Ra1-a8
        "desc": "The Rook forces the King to the edge.\n\nRa1-a8 creates a barrier the King cannot cross."
    },
    {
        "name": "Two Move Mate",
        "fen": "k7/8/1K6/8/8/8/8/7R w - - 0 1",
        "moves": [((7,7),(7,0)), ((7,0),(0,0))], # Rh1-a1, Ra1-a8#
        "desc": "White checkmates in two moves.\n1. Rh1-a1 forces the Black King to b8.\n2. Ra8# is checkmate."
    }
]

# ── Sound Manager ─────────────────────────────────────────────────────────────
class SoundManager:
    def __init__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="chess_sfx_")
        self.sounds = {}
        self._gen_all(); self._load_all()
        log("SoundManager initialized", "AUDIO")

    @staticmethod
    def _wav(path, samples, sr=44100):
        with wave.open(path,'w') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(b''.join(struct.pack('<h',max(-32768,min(32767,int(s)))) for s in samples))

    @staticmethod
    def _sin(f,d,v=.5,sr=44100):
        return [32767*v*math.sin(2*math.pi*f*i/sr) for i in range(int(sr*d))]

    @staticmethod
    def _env(s,a=.01,r=.02,sr=44100):
        o=list(s); ai=int(sr*a); ri=int(sr*r)
        for i in range(min(ai,len(o))): o[i]*=i/ai
        for i in range(min(ri,len(o))): o[-(i+1)]*=i/ri
        return o

    def _mix(self,*ls):
        m=max(len(l) for l in ls); o=[0.0]*m
        for l in ls:
            for i,v in enumerate(l): o[i]+=v
        return o

    def _gen_all(self):
        sr=44100; d=self.tmpdir
        self._wav(os.path.join(d,"move.wav"), self._env(self._sin(800,.06,.4),.005,.03))
        self._wav(os.path.join(d,"capture.wav"), self._env(self._mix(self._sin(300,.10,.5),self._sin(600,.08,.3)),.005,.04))
        self._wav(os.path.join(d,"check.wav"), self._env(self._mix(self._sin(1000,.12,.5),self._sin(1250,.10,.3)),.005,.04))
        self._wav(os.path.join(d,"checkmate.wav"), self._env(self._sin(800,.15,.5)+self._sin(600,.15,.5)+self._sin(400,.25,.5),.01,.08))
        n=int(sr*.15); sw=[32767*.4*math.sin(2*math.pi*(400+400*i/n)*i/sr) for i in range(n)]
        self._wav(os.path.join(d,"castle.wav"), self._env(sw,.005,.03))
        self._wav(os.path.join(d,"error.wav"), self._env(self._sin(200,.10,.4),.005,.03))
        n2=int(sr*.2); ri=[32767*.4*math.sin(2*math.pi*(400+400*i/n2)*i/sr) for i in range(n2)]
        self._wav(os.path.join(d,"promote.wav"), self._env(ri,.01,.05))
        gs=self._sin(523,.12,.4)+[0]*int(sr*.03)+self._sin(659,.18,.4)
        self._wav(os.path.join(d,"start.wav"), self._env(gs,.005,.04))

    def _load_all(self):
        for n in ("move","capture","check","checkmate","castle","error","promote","start"):
            e=QSoundEffect(); e.setSource(QUrl.fromLocalFile(os.path.join(self.tmpdir,f"{n}.wav"))); e.setVolume(.7)
            self.sounds[n]=e

    def play(self,name):
        s=self.sounds.get(name)
        if s: s.stop(); s.play()
        log(f"Sound played: {name}", "AUDIO")

# ── Chess Engine ──────────────────────────────────────────────────────────────
class ChessEngine:
    def __init__(self): self.reset()

    def reset(self):
        self.board=[
            ['r','n','b','q','k','b','n','r'],['p','p','p','p','p','p','p','p'],
            ['.','.','.','.','.','.','.','.'],['.','.','.','.','.','.','.','.'],
            ['.','.','.','.','.','.','.','.'],['.','.','.','.','.','.','.','.'],
            ['P','P','P','P','P','P','P','P'],['R','N','B','Q','K','B','N','R']]
        self.turn='w'; self.castling={'K':True,'Q':True,'k':True,'q':True}
        self.ep=None; self.history=[]; self.game_over=False; self.result=""; self.last_move=None
        log("ChessEngine reset to starting position", "ENGINE")

    @staticmethod
    def is_white(p): return p!='.' and p.isupper()
    @staticmethod
    def is_black(p): return p!='.' and p.islower()
    @staticmethod
    def color_of(p): return 'w' if p.isupper() else ('b' if p!='.' else None)

    def copy_board(self): return [r[:] for r in self.board]

    def find_king(self,color):
        k='K' if color=='w' else 'k'
        for r in range(8):
            for c in range(8):
                if self.board[r][c]==k: return(r,c)
        return None

    def attacked(self,row,col,by):
        kn='N' if by=='w' else 'n'
        for dr,dc in[(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]:
            r2,c2=row+dr,col+dc
            if 0<=r2<8 and 0<=c2<8 and self.board[r2][c2]==kn: return True
        ki='K' if by=='w' else 'k'
        for dr in(-1,0,1):
            for dc in(-1,0,1):
                if dr==0 and dc==0: continue
                r2,c2=row+dr,col+dc
                if 0<=r2<8 and 0<=c2<8 and self.board[r2][c2]==ki: return True
        pw='P' if by=='w' else 'p'; pd=1 if by=='w' else -1; r2=row+pd
        if 0<=r2<8:
            for dc2 in(-1,1):
                c2=col+dc2
                if 0<=c2<8 and self.board[r2][c2]==pw: return True
        rk='R' if by=='w' else 'r'; qu='Q' if by=='w' else 'q'
        for dr,dc in[(0,1),(0,-1),(1,0),(-1,0)]:
            r2,c2=row+dr,col+dc
            while 0<=r2<8 and 0<=c2<8:
                p=self.board[r2][c2]
                if p!='.':
                    if p in(rk,qu): return True
                    break
                r2+=dr;c2+=dc
        bi='B' if by=='w' else 'b'
        for dr,dc in[(1,1),(1,-1),(-1,1),(-1,-1)]:
            r2,c2=row+dr,col+dc
            while 0<=r2<8 and 0<=c2<8:
                p=self.board[r2][c2]
                if p!='.':
                    if p in(bi,qu): return True
                    break
                r2+=dr;c2+=dc
        return False

    def in_check(self,color):
        kp=self.find_king(color)
        return self.attacked(kp[0],kp[1],'b' if color=='w' else 'w') if kp else True

    def pseudo_moves(self,r,c):
        p=self.board[r][c]
        if p=='.': return[]
        co=self.color_of(p); pt=p.upper(); mv=[]
        if pt=='P':
            d=-1 if co=='w' else 1; sr=6 if co=='w' else 1; nr=r+d
            if 0<=nr<8 and self.board[nr][c]=='.':
                mv.append((nr,c)); nr2=r+2*d
                if r==sr and self.board[nr2][c]=='.': mv.append((nr2,c))
            for dc in(-1,1):
                nc=c+dc; nr2=r+d
                if 0<=nr2<8 and 0<=nc<8:
                    t=self.board[nr2][nc]
                    if (t!='.' and self.color_of(t)!=co) or (self.ep and(nr2,nc)==self.ep):
                        mv.append((nr2,nc))
        elif pt=='N':
            for dr,dc in[(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]:
                r2,c2=r+dr,c+dc
                if 0<=r2<8 and 0<=c2<8:
                    t=self.board[r2][c2]
                    if t=='.' or self.color_of(t)!=co: mv.append((r2,c2))
        elif pt in('B','R','Q'):
            dirs=[]
            if pt in('B','Q'): dirs+=[(1,1),(1,-1),(-1,1),(-1,-1)]
            if pt in('R','Q'): dirs+=[(0,1),(0,-1),(1,0),(-1,0)]
            for dr,dc in dirs:
                r2,c2=r+dr,c+dc
                while 0<=r2<8 and 0<=c2<8:
                    t=self.board[r2][c2]
                    if t=='.': mv.append((r2,c2))
                    elif self.color_of(t)!=co: mv.append((r2,c2)); break
                    else: break
                    r2+=dr;c2+=dc
        elif pt=='K':
            for dr in(-1,0,1):
                for dc in(-1,0,1):
                    if dr==0 and dc==0: continue
                    r2,c2=r+dr,c+dc
                    if 0<=r2<8 and 0<=c2<8:
                        t=self.board[r2][c2]
                        if t=='.' or self.color_of(t)!=co: mv.append((r2,c2))
            enemy='b' if co=='w' else 'w'
            if co=='w' and r==7 and c==4:
                if self.castling['K'] and self.board[7][5]=='.' and self.board[7][6]=='.' and self.board[7][7]=='R':
                    if not self.attacked(7,4,enemy) and not self.attacked(7,5,enemy) and not self.attacked(7,6,enemy):
                        mv.append((7,6))
                if self.castling['Q'] and self.board[7][3]=='.' and self.board[7][2]=='.' and self.board[7][1]=='.' and self.board[7][0]=='R':
                    if not self.attacked(7,4,enemy) and not self.attacked(7,3,enemy) and not self.attacked(7,2,enemy):
                        mv.append((7,2))
            elif co=='b' and r==0 and c==4:
                if self.castling['k'] and self.board[0][5]=='.' and self.board[0][6]=='.' and self.board[0][7]=='r':
                    if not self.attacked(0,4,enemy) and not self.attacked(0,5,enemy) and not self.attacked(0,6,enemy):
                        mv.append((0,6))
                if self.castling['q'] and self.board[0][3]=='.' and self.board[0][2]=='.' and self.board[0][1]=='.' and self.board[0][0]=='r':
                    if not self.attacked(0,4,enemy) and not self.attacked(0,3,enemy) and not self.attacked(0,2,enemy):
                        mv.append((0,2))
        return mv

    def legal_moves(self,r,c):
        p=self.board[r][c]
        if p=='.' or self.color_of(p)!=self.turn: return[]
        co=self.color_of(p); out=[]
        for tr,tc in self.pseudo_moves(r,c):
            sb=self.copy_board(); sep=self.ep; sc=dict(self.castling)
            self.board[tr][tc]=p; self.board[r][c]='.'
            if p.upper()=='P' and self.ep and(tr,tc)==self.ep: self.board[r][tc]='.'
            if p.upper()=='K' and abs(tc-c)==2:
                if tc==6: self.board[r][5]=self.board[r][7]; self.board[r][7]='.'
                elif tc==2: self.board[r][3]=self.board[r][0]; self.board[r][0]='.'
            chk=self.in_check(co)
            self.board=sb; self.ep=sep; self.castling=sc
            if not chk: out.append((tr,tc))
        return out

    def all_legal_moves(self,color=None):
        if color is None: color=self.turn
        out=[]
        for r in range(8):
            for c in range(8):
                if self.color_of(self.board[r][c])==color:
                    for m in self.legal_moves(r,c): out.append(((r,c),m))
        return out

    def make_move(self,fr,fc,tr,tc,promo=None):
        p=self.board[fr][fc]
        if p=='.': return None
        co=self.color_of(p); cap=self.board[tr][tc]
        info={'from':(fr,fc),'to':(tr,tc),'piece':p,'captured':cap,
              'castle':False,'ep':False,'promo':None,'check':False,'mate':False,'notation':''}
        self.history.append({'board':self.copy_board(),'turn':self.turn,
            'castling':dict(self.castling),'ep':self.ep,'last_move':self.last_move,
            'game_over':self.game_over,'result':self.result})
        if p.upper()=='P' and self.ep and(tr,tc)==self.ep:
            info['ep']=True; info['captured']=self.board[fr][tc]; self.board[fr][tc]='.'
        self.ep=None
        if p.upper()=='P' and abs(tr-fr)==2: self.ep=((fr+tr)//2,fc)
        if p.upper()=='K' and abs(tc-fc)==2:
            info['castle']=True
            if tc==6: self.board[fr][5]=self.board[fr][7]; self.board[fr][7]='.'
            elif tc==2: self.board[fr][3]=self.board[fr][0]; self.board[fr][0]='.'
        self.board[tr][tc]=p; self.board[fr][fc]='.'
        prow=0 if co=='w' else 7
        if p.upper()=='P' and tr==prow:
            pp=promo or('Q' if co=='w' else 'q')
            self.board[tr][tc]=pp; info['promo']=pp
        if(fr,fc)==(7,4): self.castling['K']=False; self.castling['Q']=False
        if(fr,fc)==(0,4): self.castling['k']=False; self.castling['q']=False
        for pos,key in[((7,7),'K'),((7,0),'Q'),((0,7),'k'),((0,0),'q')]:
            if(fr,fc)==pos or(tr,tc)==pos: self.castling[key]=False
        self.last_move=((fr,fc),(tr,tc)); self.turn='b' if self.turn=='w' else 'w'
        if self.in_check(self.turn):
            info['check']=True
            if not self.all_legal_moves(self.turn):
                info['mate']=True; self.game_over=True
                self.result="White wins!" if self.turn=='b' else "Black wins!"
        elif not self.all_legal_moves(self.turn):
            self.game_over=True; self.result="Stalemate — Draw"
        info['notation']=self._nota(info)
        log(f"Move: {info['notation']}  piece={info['piece']}  from={info['from']}  to={info['to']}  "
            f"capture={info['captured']}  castle={info['castle']}  ep={info['ep']}  "
            f"promo={info['promo']}  check={info['check']}  mate={info['mate']}", "ENGINE")
        return info

    def undo(self):
        if not self.history: return False
        s=self.history.pop()
        self.board=s['board']; self.turn=s['turn']; self.castling=s['castling']
        self.ep=s['ep']; self.last_move=s['last_move']
        self.game_over=s['game_over']; self.result=s['result']
        log("Move undone", "ENGINE")
        return True

    def _nota(self,info):
        if info['castle']: n="O-O" if info['to'][1]==6 else "O-O-O"
        else:
            pt=info['piece'].upper(); fr,fc=info['from']; tr,tc=info['to']
            n="" if pt=='P' else pt
            if info['captured']!='.':
                if pt=='P': n+=FILES_STR[fc]
                n+='x'
            n+=FILES_STR[tc]+RANKS_STR[tr]
            if info['promo']: n+='='+info['promo'].upper()
        if info['mate']: n+='#'
        elif info['check']: n+='+'
        return n

    def evaluate(self):
        s=0
        for r in range(8):
            for c in range(8):
                p=self.board[r][c]
                if p=='.': continue
                pt=p.upper(); v=PIECE_VAL.get(pt,0); t=PST.get(pt)
                if p.isupper(): s+=v+(t[r][c] if t else 0)
                else: s-=v+(t[7-r][c] if t else 0)
        return s

    def minimax(self, depth, alpha, beta, maximizing):
        if depth==0: return self.evaluate()
        co='w' if maximizing else 'b'
        moves=self.all_legal_moves(co)
        if not moves:
            if self.in_check(co): return -99999 if maximizing else 99999
            return 0
        if maximizing:
            val=-999999
            for (fr,fc),(tr,tc) in moves:
                sb=self.copy_board(); st=self.turn; sc=dict(self.castling); se=self.ep; slm=self.last_move
                p=self.board[fr][fc]
                self.board[tr][tc]=p; self.board[fr][fc]='.'
                if p.upper()=='P' and se and(tr,tc)==se: self.board[fr][tc]='.'
                if p.upper()=='K' and abs(tc-fc)==2:
                    if tc==6: self.board[fr][5]=self.board[fr][7]; self.board[fr][7]='.'
                    elif tc==2: self.board[fr][3]=self.board[fr][0]; self.board[fr][0]='.'
                self.turn='b' if self.turn=='w' else 'w'; self.last_move=((fr,fc),(tr,tc))
                val=max(val, self.minimax(depth-1, alpha, beta, False))
                self.board=sb; self.turn=st; self.castling=sc; self.ep=se; self.last_move=slm
                alpha=max(alpha,val)
                if beta<=alpha: break
            return val
        else:
            val=999999
            for (fr,fc),(tr,tc) in moves:
                sb=self.copy_board(); st=self.turn; sc=dict(self.castling); se=self.ep; slm=self.last_move
                p=self.board[fr][fc]
                self.board[tr][tc]=p; self.board[fr][fc]='.'
                if p.upper()=='P' and se and(tr,tc)==se: self.board[fr][tc]='.'
                if p.upper()=='K' and abs(tc-fc)==2:
                    if tc==6: self.board[fr][5]=self.board[fr][7]; self.board[fr][7]='.'
                    elif tc==2: self.board[fr][3]=self.board[fr][0]; self.board[fr][0]='.'
                self.turn='b' if self.turn=='w' else 'w'
                self.last_move=((fr,fc),(tr,tc))
                val=min(val, self.minimax(depth-1, alpha, beta, True))
                self.board=sb; self.turn=st; self.castling=sc; self.ep=se; self.last_move=slm
                beta=min(beta,val)
                if beta<=alpha: break
            return val

    def get_ai_move(self, depth=2):
        moves=self.all_legal_moves()
        if not moves: return None
        log(f"AI computing move (depth={depth}, {len(moves)} legal moves)...", "AI")
        best=None
        if self.turn=='w':
            mx=-999999
            for (fr,fc),(tr,tc) in moves:
                sb=self.copy_board(); st=self.turn; sc=dict(self.castling); se=self.ep; slm=self.last_move
                p=self.board[fr][fc]
                self.board[tr][tc]=p; self.board[fr][fc]='.'
                if p.upper()=='P' and se and(tr,tc)==se: self.board[fr][tc]='.'
                if p.upper()=='K' and abs(tc-fc)==2:
                    if tc==6: self.board[fr][5]=self.board[fr][7]; self.board[fr][7]='.'
                    elif tc==2: self.board[fr][3]=self.board[fr][0]; self.board[fr][0]='.'
                self.turn='b' if self.turn=='w' else 'w'; self.last_move=((fr,fc),(tr,tc))
                ev=self.minimax(depth-1,-999999,999999,False)
                self.board=sb; self.turn=st; self.castling=sc; self.ep=se; self.last_move=slm
                if ev>mx: mx=ev; best=((fr,fc),(tr,tc))
        else:
            mn=999999
            for (fr,fc),(tr,tc) in moves:
                sb=self.copy_board(); st=self.turn; sc=dict(self.castling); se=self.ep; slm=self.last_move
                p=self.board[fr][fc]
                self.board[tr][tc]=p; self.board[fr][fc]='.'
                if p.upper()=='P' and se and(tr,tc)==se: self.board[fr][tc]='.'
                if p.upper()=='K' and abs(tc-fc)==2:
                    if tc==6: self.board[fr][5]=self.board[fr][7]; self.board[fr][7]='.'
                    elif tc==2: self.board[fr][3]=self.board[fr][0]; self.board[fr][0]='.'
                self.turn='b' if self.turn=='w' else 'w'; self.last_move=((fr,fc),(tr,tc))
                ev=self.minimax(depth-1,-999999,999999,True)
                self.board=sb; self.turn=st; self.castling=sc; self.ep=se; self.last_move=slm
                if ev<mn: mn=ev; best=((fr,fc),(tr,tc))
        if best:
            (fr,fc),(tr,tc) = best
            log(f"AI chosen move: {FILES_STR[fc]}{RANKS_STR[fr]}{FILES_STR[tc]}{RANKS_STR[tr]}", "AI")
        else:
            log("AI: no move found", "AI")
        return best

    def load_fen(self, fen):
        parts=fen.split(); rows=parts[0].split('/')
        self.board=[]
        for row_str in rows:
            row=[]
            for ch in row_str:
                if ch.isdigit(): row.extend(['.']*int(ch))
                else: row.append(ch)
            self.board.append(row)
        self.turn='w' if parts[1]=='w' else 'b'
        self.castling={'K':'K' in parts[2],'Q':'Q' in parts[2],'k':'k' in parts[2],'q':'q' in parts[2]}
        self.ep=None
        if len(parts)>3 and parts[3]!='-':
            c=ord(parts[3][0])-ord('a'); r=8-int(parts[3][1]); self.ep=(r,c)
        self.history=[]; self.game_over=False; self.result=""; self.last_move=None
        log(f"FEN loaded: {fen}", "ENGINE")

    def parse_uci(self, uci_str):
        if not uci_str or len(uci_str) < 4: return None, None
        fc = ord(uci_str[0]) - ord('a')
        fr = 8 - int(uci_str[1])
        tc = ord(uci_str[2]) - ord('a')
        tr = 8 - int(uci_str[3])
        promo = uci_str[4] if len(uci_str) == 5 else None
        return ((fr, fc), (tr, tc)), promo


# ── Chess Board Widget ────────────────────────────────────────────────────────
class ChessBoardWidget(QWidget):
    move_made = Signal(str)

    def __init__(self, engine, sound_mgr, parent=None):
        super().__init__(parent)
        self.engine = engine; self.snd = sound_mgr
        self.selected = None; self.legal_targets = []
        self.setFixedSize(SQ_SIZE*8, SQ_SIZE*8); self.setMouseTracking(True)

    def paintEvent(self, e):
        pix = self.render_image(self.engine.board, self.engine.last_move, self.selected, self.legal_targets)
        painter = QPainter(self); painter.drawPixmap(0, 0, pix)

    @staticmethod
    def render_image(board, last_move=None, selected=None, legal_targets=None, text_overlay=""):
        sz = SQ_SIZE; pix = QPixmap(sz*8, sz*8); p = QPainter(pix); p.setRenderHint(QPainter.Antialiasing)
        for r in range(8):
            for c in range(8):
                color = LIGHT_SQ if (r+c)%2==0 else DARK_SQ; p.fillRect(c*sz, r*sz, sz, sz, color)
                if last_move and (r,c) in last_move: p.fillRect(c*sz, r*sz, sz, sz, LAST_COL)
                if selected and (r,c)==selected: p.fillRect(c*sz, r*sz, sz, sz, SEL_COL)
                if legal_targets and (r,c) in legal_targets:
                    cx, cy = c*sz+sz//2, r*sz+sz//2
                    if board[r][c] != '.':
                        p.setPen(QPen(CAP_RING, 4)); p.setBrush(Qt.NoBrush); p.drawEllipse(cx-sz//3, cy-sz//3, sz*2//3, sz*2//3)
                    else:
                        p.setPen(Qt.NoPen); p.setBrush(MOVE_DOT); p.drawEllipse(cx-sz//8, cy-sz//8, sz//4, sz//4)
                piece = board[r][c]
                if piece != '.':
                    is_w = piece.isupper()
                    p.setFont(QFont("Segoe UI Emoji", sz*0.65 if is_w else sz*0.7))
                    p.setPen(QColor(0,0,0,60)); p.drawText(QRect(c*sz+2, r*sz+2, sz, sz), Qt.AlignCenter, UNICODE_PIECES[piece])
                    p.setPen(QColor("#FFFFFF") if not is_w else QColor("#000000")); p.drawText(QRect(c*sz, r*sz, sz, sz), Qt.AlignCenter, UNICODE_PIECES[piece])
        p.setFont(QFont("Sans", 9, QFont.Bold))
        for c in range(8):
            col = DARK_SQ if (7+c)%2==0 else LIGHT_SQ; p.setPen(col); p.drawText(QRect(c*sz+sz-14, 7*sz+2, 12, 14), Qt.AlignCenter, FILES_STR[c])
        for r in range(8):
            col = DARK_SQ if (r)%2==0 else LIGHT_SQ; p.setPen(col); p.drawText(QRect(2, r*sz+2, 12, 14), Qt.AlignCenter, RANKS_STR[r])
        if text_overlay:
            p.fillRect(0, sz*4-25, sz*8, 50, QColor(0,0,0,200)); p.setPen(Qt.white); p.setFont(QFont("Sans", 16, QFont.Bold))
            p.drawText(QRect(0, sz*4-25, sz*8, 50), Qt.AlignCenter, text_overlay)
        p.end(); return pix

    def mousePressEvent(self, e):
        if self.engine.game_over: return
        c = int(e.position().x()) // SQ_SIZE; r = int(e.position().y()) // SQ_SIZE
        if not (0<=r<8 and 0<=c<8): return
        piece = self.engine.board[r][c]
        if self.selected:
            sr, sc = self.selected
            if (r,c) in self.legal_targets:
                info = self.engine.make_move(sr, sc, r, c)
                if info:
                    sfx = "capture" if info['captured']!='.' else ("castle" if info['castle'] else "move")
                    if info['mate']: sfx = "checkmate"
                    elif info['check']: sfx = "check"
                    self.snd.play(sfx); self.move_made.emit(info['notation'])
            else:
                log(f"Invalid move attempt: ({sr},{sc})->({r},{c})", "INPUT")
            self.selected = None; self.legal_targets = []
        else:
            if piece != '.' and self.engine.color_of(piece) == self.engine.turn:
                self.selected = (r,c); self.legal_targets = self.engine.legal_moves(r,c)
                if not self.legal_targets: self.snd.play("error"); self.selected = None
                else:
                    log(f"Selected {piece} at {FILES_STR[c]}{RANKS_STR[r]}, {len(self.legal_targets)} legal moves", "INPUT")
            else:
                if piece != '.':
                    log(f"Cannot select {piece} at {FILES_STR[c]}{RANKS_STR[r]} — not your turn", "INPUT")
        self.update()


# ── Export MP4 Worker ─────────────────────────────────────────────────────────
class ExportWorker(QThread):
    progress = Signal(int); finished = Signal(str)

    def __init__(self, puzzle, file_path):
        super().__init__(); self.puzzle = puzzle; self.file_path = file_path

    def run(self):
        if not HAS_NUMPY or not HAS_IMAGEIO:
            msg = "ERROR: Missing numpy or imageio. Install via:\npip install numpy imageio[ffmpeg]"
            log(msg, "EXPORT"); self.finished.emit(msg); return
        log(f"Starting MP4 export for puzzle '{self.puzzle['name']}' -> {self.file_path}", "EXPORT")
        eng = ChessEngine(); eng.load_fen(self.puzzle["fen"]); fps = 30; frames = []
        log("Rendering intro frames...", "EXPORT")
        for i in range(fps * 3):
            pix = ChessBoardWidget.render_image(eng.board, text_overlay=f"Puzzle: {self.puzzle['name']}")
            img = pix.toImage().convertToFormat(QImage.Format_RGB888); ptr = img.bits(); ptr.setsize(img.sizeInBytes())
            frames.append(np.frombuffer(ptr, dtype=np.uint8).reshape((img.height(), img.width(), 3)).copy())
        self.progress.emit(30)
        for idx, move in enumerate(self.puzzle["moves"]):
            (fr,fc), (tr,tc) = move
            log(f"Rendering move {idx+1}/{len(self.puzzle['moves'])}: ({fr},{fc})->({tr},{tc})...", "EXPORT")
            is_cap = eng.board[tr][tc] != '.'
            for i in range(int(fps * 1.5)):
                pix = ChessBoardWidget.render_image(eng.board, selected=(fr,fc))
                img = pix.toImage().convertToFormat(QImage.Format_RGB888); ptr = img.bits(); ptr.setsize(img.sizeInBytes())
                frames.append(np.frombuffer(ptr, dtype=np.uint8).reshape((img.height(), img.width(), 3)).copy())
            info = eng.make_move(fr, fc, tr, tc)
            for i in range(fps * 2):
                pix = ChessBoardWidget.render_image(eng.board, last_move=((fr,fc),(tr,tc)))
                img = pix.toImage().convertToFormat(QImage.Format_RGB888); ptr = img.bits(); ptr.setsize(img.sizeInBytes())
                frames.append(np.frombuffer(ptr, dtype=np.uint8).reshape((img.height(), img.width(), 3)).copy())
            pct = 30 + (40 * (idx + 1) // len(self.puzzle["moves"]))
            self.progress.emit(pct)
            log(f"Move {idx+1} rendered — progress {pct}%", "EXPORT")
        log("Rendering outro frames...", "EXPORT")
        for i in range(fps * 2):
            pix = ChessBoardWidget.render_image(eng.board, text_overlay="Solved!")
            img = pix.toImage().convertToFormat(QImage.Format_RGB888); ptr = img.bits(); ptr.setsize(img.sizeInBytes())
            frames.append(np.frombuffer(ptr, dtype=np.uint8).reshape((img.height(), img.width(), 3)).copy())
        self.progress.emit(85)
        log(f"Writing {len(frames)} frames to {self.file_path}...", "EXPORT")
        try: iio.write(self.file_path, fps, frames)
        except Exception as e:
            msg = f"Error writing MP4: {e}"
            log(msg, "EXPORT"); self.finished.emit(msg); return
        self.progress.emit(100)
        msg = f"MP4 successfully saved to: {self.file_path}"
        log(msg, "EXPORT"); self.finished.emit(msg)


# ── Main Window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("♚ Chess Learning App")
        log("Initializing Chess Learning App...", "APP")
        self.engine = ChessEngine(); self.snd = SoundManager()
        self.board_widget = ChessBoardWidget(self.engine, self.snd)
        self.board_widget.move_made.connect(self.on_move)
        self.opening_data = []
        self.opening_step_idx = 0

        central = QWidget(); self.setCentralWidget(central)
        layout = QHBoxLayout(central); layout.setContentsMargins(10,10,10,10)
        self.tabs = QTabWidget(); self.tabs.setFixedWidth(400); layout.addWidget(self.tabs)
        board_frame = QFrame(); board_frame.setFrameStyle(QFrame.Box|QFrame.Raised)
        bl = QVBoxLayout(board_frame); bl.setContentsMargins(0,0,0,0); bl.addWidget(self.board_widget)
        layout.addWidget(board_frame, alignment=Qt.AlignCenter)

        self._build_play_tab(); self._build_puzzle_tab(); self._build_openings_tab()
        self.snd.play("start")
        log("App initialization complete", "APP")

    # --- Play Tab ---
    def _build_play_tab(self):
        w = QWidget(); l = QVBoxLayout(w)
        self.ai_cb = QComboBox(); self.ai_cb.addItems(["Human vs Human", "Play vs AI (White)", "Play vs AI (Black)"])
        self.depth_cb = QComboBox(); self.depth_cb.addItems(["Depth 1 (Easy)","Depth 2 (Medium)","Depth 3 (Hard)"]); self.depth_cb.setCurrentIndex(1)
        btn_new = QPushButton("♻ New Game"); btn_new.clicked.connect(self.new_game)
        btn_undo = QPushButton("↩ Undo Move"); btn_undo.clicked.connect(self.undo)
        self.status_lbl = QLabel("White's turn"); self.status_lbl.setFont(QFont("Sans", 14, QFont.Bold)); self.status_lbl.setAlignment(Qt.AlignCenter)
        self.log_te = QTextEdit(); self.log_te.setReadOnly(True); self.log_te.setFont(QFont("Courier", 12))
        l.addWidget(QLabel("Game Mode:")); l.addWidget(self.ai_cb)
        l.addWidget(QLabel("AI Strength:")); l.addWidget(self.depth_cb)
        l.addWidget(btn_new); l.addWidget(btn_undo); l.addWidget(self.status_lbl); l.addWidget(self.log_te)
        self.tabs.addTab(w, "♟ Play")

    # --- Puzzle Tab ---
    def _build_puzzle_tab(self):
        w = QWidget(); l = QVBoxLayout(w)
        self.puzzle_list = QListWidget()
        for pz in PUZZLES:
            it = QListWidgetItem(pz["name"]); it.setData(Qt.UserRole, pz); self.puzzle_list.addItem(it)
        self.puzzle_list.setCurrentRow(0)
        btn_load = QPushButton("📋 Load Puzzle"); btn_load.clicked.connect(self.load_puzzle)
        btn_export = QPushButton("🎬 Export to MP4"); btn_export.clicked.connect(self.export_mp4)
        self.puzzle_info = QTextEdit(); self.puzzle_info.setReadOnly(True)
        l.addWidget(QLabel("Select a Puzzle:")); l.addWidget(self.puzzle_list)
        l.addWidget(btn_load); l.addWidget(btn_export); l.addWidget(QLabel("Instructions:")); l.addWidget(self.puzzle_info)
        self.tabs.addTab(w, "🧩 Puzzles")

    # --- Openings Tab ---
    def _build_openings_tab(self):
        w = QWidget(); l = QVBoxLayout(w)
        btn_load = QPushButton("📂 Load Openings File..."); btn_load.clicked.connect(self.load_openings_file)
        self.opening_list = QListWidget(); self.opening_list.currentRowChanged.connect(self.select_opening)

        # Image Display
        self.opening_img_lbl = QLabel("Opening Image")
        self.opening_img_lbl.setFixedSize(250, 250); self.opening_img_lbl.setAlignment(Qt.AlignCenter)
        self.opening_img_lbl.setStyleSheet("background-color: #2b2b2b; border: 1px solid #555;")

        step_layout = QHBoxLayout()
        btn_start = QPushButton("⏮"); btn_start.clicked.connect(self.opening_start)
        btn_prev = QPushButton("◀ Prev"); btn_prev.clicked.connect(self.opening_prev)
        btn_next = QPushButton("Next ▶"); btn_next.clicked.connect(self.opening_next)
        btn_end = QPushButton("⏭"); btn_end.clicked.connect(self.opening_end)
        step_layout.addWidget(btn_start); step_layout.addWidget(btn_prev)
        step_layout.addWidget(btn_next); step_layout.addWidget(btn_end)

        self.opening_moves_te = QTextEdit(); self.opening_moves_te.setReadOnly(True)
        self.opening_moves_te.setFont(QFont("Courier", 13)); self.opening_moves_te.setMaximumHeight(150)
        self.opening_status = QLabel("Load a CSV, Parquet, DuckDB, or SQLite file to study openings.")
        self.opening_status.setWordWrap(True)

        l.addWidget(btn_load)
        l.addWidget(QLabel("Openings Loaded:")); l.addWidget(self.opening_list)
        l.addWidget(self.opening_img_lbl, alignment=Qt.AlignCenter)
        l.addLayout(step_layout)
        l.addWidget(QLabel("Moves:")); l.addWidget(self.opening_moves_te)
        l.addWidget(self.opening_status)
        self.tabs.addTab(w, "📚 Openings")

    # --- Game Logic ---
    def new_game(self):
        self.engine.reset(); self.log_te.clear()
        self.board_widget.selected = None; self.board_widget.legal_targets = []
        self.board_widget.update(); self.update_status(); self.snd.play("start")
        log("New game started", "GAME")

    def undo(self):
        if self.engine.undo():
            self.board_widget.selected = None; self.board_widget.legal_targets = []
            self.board_widget.update(); self.update_status(); self.snd.play("move")
        else:
            log("Undo failed — no history", "GAME")

    def on_move(self, notation):
        self.log_te.append(notation); self.update_status()
        if self.engine.game_over:
            log(f"Game over: {self.engine.result}", "GAME")
        if not self.engine.game_over and self.is_ai_turn(): QTimer.singleShot(200, self.ai_move)

    def is_ai_turn(self):
        idx = self.ai_cb.currentIndex()
        if idx == 1 and self.engine.turn == 'b': return True
        if idx == 2 and self.engine.turn == 'w': return True
        return False

    def ai_move(self):
        depth = self.depth_cb.currentIndex() + 1; move = self.engine.get_ai_move(depth)
        if move:
            (fr,fc),(tr,tc) = move; info = self.engine.make_move(fr, fc, tr, tc)
            if info:
                sfx = "capture" if info['captured']!='.' else ("castle" if info['castle'] else "move")
                if info['mate']: sfx = "checkmate"
                elif info['check']: sfx = "check"
                self.snd.play(sfx); self.log_te.append(info['notation'])
                self.board_widget.selected = None; self.board_widget.legal_targets = []
                self.board_widget.update(); self.update_status()
                if self.engine.game_over:
                    log(f"Game over after AI move: {self.engine.result}", "GAME")

    def update_status(self):
        if self.engine.game_over:
            self.status_lbl.setText(self.engine.result); self.status_lbl.setStyleSheet("color: red; font-weight: bold;")
            log(f"Status: {self.engine.result}", "GAME")
        else:
            turn = "White's turn" if self.engine.turn == 'w' else "Black's turn"
            if self.engine.in_check(self.engine.turn):
                turn += " (CHECK!)"; self.status_lbl.setStyleSheet("color: orange; font-weight: bold;")
                log(f"Status: {turn}", "GAME")
            else: self.status_lbl.setStyleSheet("color: black; font-weight: bold;")
            self.status_lbl.setText(turn)

    def load_puzzle(self):
        item = self.puzzle_list.currentItem()
        if not item: return
        pz = item.data(Qt.UserRole); self.engine.load_fen(pz["fen"]); self.ai_cb.setCurrentIndex(0)
        self.log_te.clear(); self.puzzle_info.setText(pz.get("desc", ""))
        self.board_widget.selected = None; self.board_widget.legal_targets = []
        self.board_widget.update(); self.update_status(); self.snd.play("start")
        log(f"Puzzle loaded: {pz['name']}", "PUZZLE")

    def export_mp4(self):
        item = self.puzzle_list.currentItem()
        if not item: return
        pz = item.data(Qt.UserRole); path, _ = QFileDialog.getSaveFileName(self, "Save MP4", f"{pz['name']}.mp4", "Video (*.mp4)")
        if not path: return
        if not HAS_NUMPY or not HAS_IMAGEIO:
            log("ERROR: MP4 export requires numpy and imageio. Install via: pip install numpy imageio[ffmpeg]", "EXPORT")
            return
        log(f"Starting MP4 export: {pz['name']} -> {path}", "EXPORT")
        self.export_worker = ExportWorker(pz, path)
        self.export_worker.progress.connect(self._on_export_progress)
        self.export_worker.finished.connect(self.on_export_finished)
        self.export_worker.start()

    def _on_export_progress(self, pct):
        log(f"Export progress: {pct}%", "EXPORT")

    def on_export_finished(self, msg):
        if "ERROR" in msg:
            log(f"Export error: {msg}", "EXPORT")
        else:
            log(f"Export complete: {msg}", "EXPORT")

    # --- Openings Logic ---
    def load_openings_file(self):
        file_filter = "Supported Files (*.csv *.parquet *.duckdb *.db *.sqlite);;CSV (*.csv);;Parquet (*.parquet);;DuckDB (*.duckdb);;SQLite (*.db *.sqlite);;All Files (*)"
        path, _ = QFileDialog.getOpenFileName(self, "Open Openings File", "", file_filter)
        if not path: return
        
        ext = Path(path).suffix.lower()
        log(f"Loading openings file: {path} (Format: {ext})", "OPENINGS")
        
        try:
            if ext == '.csv':
                self.opening_data = self.parse_openings_csv(path)
            elif ext == '.parquet':
                self.opening_data = self.parse_openings_parquet(path)
            elif ext in ('.duckdb', '.db', '.sqlite'):
                # Let duckdb handle .duckdb, sqlite handle .db/.sqlite (or fallback)
                if ext == '.duckdb':
                    self.opening_data = self.parse_openings_duckdb(path)
                else:
                    self.opening_data = self.parse_openings_sqlite(path)
            else:
                log(f"Unsupported file format: {ext}", "OPENINGS")
                return
                
            self.opening_list.clear()
            for data in self.opening_data:
                self.opening_list.addItem(f"{data['eco']} - {data['name']}")
            if self.opening_data:
                self.opening_list.setCurrentRow(0)
                self.opening_status.setText(f"Loaded {len(self.opening_data)} openings from {Path(path).name}")
                log(f"Loaded {len(self.opening_data)} openings from {path}", "OPENINGS")
            else:
                self.opening_status.setText("No valid openings found in file.")
                log(f"No valid openings found in {path}", "OPENINGS")
        except Exception as e:
            log(f"Failed to read file: {e}", "OPENINGS")

    def _process_opening_rows(self, rows):
        """Normalize rows from any data source into the app's internal format."""
        openings = []
        for row in rows:
            # Normalize keys to lowercase strings and handle None values
            row = {str(k).lower(): (v if v is not None else '') for k, v in row.items()}
            
            # Parse Image
            pixmap = None
            img_val = row.get('img', '')
            img_dict = None
            
            if isinstance(img_val, dict):
                img_dict = img_val
            elif isinstance(img_val, str) and img_val.strip().startswith("{"):
                try:
                    safe_str = img_val
                    safe_str = re.sub(r'\bnull\b', 'None', safe_str)
                    safe_str = re.sub(r'\btrue\b', 'True', safe_str)
                    safe_str = re.sub(r'\bfalse\b', 'False', safe_str)
                    safe_str = re.sub(r'\bNaN\b', 'None', safe_str)
                    safe_str = re.sub(r'\bundefined\b', 'None', safe_str)
                    img_dict = ast.literal_eval(safe_str)
                except Exception as e:
                    log(f"Image parse error: {e}", "OPENINGS")
                    
            if img_dict:
                try:
                    bytes_val = img_dict.get('bytes')
                    actual_bytes = None
                    if isinstance(bytes_val, bytes):
                        actual_bytes = bytes_val
                    elif isinstance(bytes_val, str):
                        try:
                            actual_bytes = base64.b64decode(bytes_val)
                        except Exception:
                            pass
                        if actual_bytes is None:
                            try:
                                actual_bytes = bytes(bytes_val, "utf-8").decode("unicode_escape").encode("latin1")
                            except Exception:
                                pass
                                
                    if actual_bytes:
                        pixmap = QPixmap()
                        pixmap.loadFromData(actual_bytes)
                except Exception as e:
                    log(f"Image byte extraction error: {e}", "OPENINGS")

            # Parse UCI moves list
            uci_val = row.get('uci', '')
            if isinstance(uci_val, list):
                uci_moves = [str(m).strip() for m in uci_val if m]
            else:
                uci_moves = [m.strip() for m in str(uci_val).split(',') if m.strip()]

            openings.append({
                'volume': str(row.get('eco-volume', '')),
                'eco': str(row.get('eco', '')),
                'name': str(row.get('name', 'Unknown')),
                'pixmap': pixmap,
                'pgn': str(row.get('pgn', '')),
                'uci_moves': uci_moves,
                'epd': str(row.get('epd', ''))
            })
        return openings

    def parse_openings_csv(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return self._process_opening_rows(rows)

    def parse_openings_parquet(self, filepath):
        if not HAS_PANDAS and not HAS_PYARROW:
            raise ImportError("Parquet support requires 'pandas' or 'pyarrow'. Install via: pip install pandas pyarrow")
        
        if HAS_PANDAS:
            df = pd.read_parquet(filepath)
        else:
            import pyarrow.parquet as pq
            df = pq.read_table(filepath).to_pandas()
            
        rows = df.to_dict('records')
        return self._process_opening_rows(rows)

    def parse_openings_duckdb(self, filepath):
        if not HAS_DUCKDB:
            raise ImportError("DuckDB support requires 'duckdb'. Install via: pip install duckdb")
        
        con = duckdb.connect(filepath, read_only=True)
        tables = con.execute("SHOW TABLES").fetchall()
        if not tables:
            raise ValueError("No tables found in DuckDB database")
        
        table_name = tables[0][0] # Use the first table found
        log(f"Reading from DuckDB table: {table_name}", "OPENINGS")
        
        df = con.execute(f'SELECT * FROM "{table_name}"').fetchdf()
        con.close()
        
        rows = df.to_dict('records')
        return self._process_opening_rows(rows)

    def parse_openings_sqlite(self, filepath):
        conn = sqlite3.connect(filepath)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        if not tables:
            conn.close()
            raise ValueError("No tables found in SQLite database")
            
        table_name = tables[0][0] # Use the first table found
        log(f"Reading from SQLite table: {table_name}", "OPENINGS")
        
        cursor = conn.execute(f'SELECT * FROM "{table_name}"')
        col_names = [desc[0] for desc in cursor.description]
        rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]
        conn.close()
        
        return self._process_opening_rows(rows)

    def select_opening(self, row):
        if row < 0 or row >= len(self.opening_data): return
        data = self.opening_data[row]
        self.ai_cb.setCurrentIndex(0)
        self.opening_step_idx = 0

        fen = data['epd']
        if not fen: fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        if len(fen.split()) < 6: fen += " 0 1"
        self.engine.load_fen(fen)

        if data['pixmap'] and not data['pixmap'].isNull():
            self.opening_img_lbl.setPixmap(data['pixmap'].scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.opening_img_lbl.setText("No Image")

        self.board_widget.selected = None; self.board_widget.legal_targets = []
        self.board_widget.update(); self.update_opening_display()
        log(f"Opening selected: {data['eco']} - {data['name']} ({len(data['uci_moves'])} moves)", "OPENINGS")

    def update_opening_display(self):
        row = self.opening_list.currentRow()
        if row < 0: return
        data = self.opening_data[row]
        text = ""
        for i, uci in enumerate(data['uci_moves']):
            marker = "<b><u>" + uci + "</u></b>" if i == self.opening_step_idx else uci
            text += marker + " "
            if (i + 1) % 2 == 0: text += "  "
        self.opening_moves_te.setHtml(text)

    def opening_start(self):
        self.opening_step_idx = 0; self.select_opening(self.opening_list.currentRow())
        self.snd.play("move")
        log("Opening: reset to start", "OPENINGS")

    def opening_prev(self):
        if self.opening_step_idx > 0:
            self.opening_step_idx -= 1
            row = self.opening_list.currentRow()
            if row < 0: return
            data = self.opening_data[row]
            fen = data['epd']
            if not fen: fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
            if len(fen.split()) < 6: fen += " 0 1"
            self.engine.load_fen(fen)
            for i in range(self.opening_step_idx):
                m, promo = self.engine.parse_uci(data['uci_moves'][i])
                if m: self.engine.make_move(m[0][0], m[0][1], m[1][0], m[1][1], promo)
            self.board_widget.selected = None; self.board_widget.legal_targets = []
            self.board_widget.update(); self.update_opening_display(); self.snd.play("move")
            log(f"Opening: step back to move {self.opening_step_idx}", "OPENINGS")

    def opening_next(self):
        row = self.opening_list.currentRow()
        if row < 0: return
        data = self.opening_data[row]
        if self.opening_step_idx < len(data['uci_moves']):
            uci = data['uci_moves'][self.opening_step_idx]
            move, promo = self.engine.parse_uci(uci)
            if move:
                (fr,fc), (tr,tc) = move
                info = self.engine.make_move(fr, fc, tr, tc, promo)
                if info:
                    sfx = "capture" if info['captured']!='.' else ("castle" if info['castle'] else "move")
                    if info['check']: sfx = "check"
                    self.snd.play(sfx)
                    log(f"Opening step {self.opening_step_idx+1}: {uci} -> {info['notation']}", "OPENINGS")
            self.opening_step_idx += 1
            self.board_widget.selected = None; self.board_widget.legal_targets = []
            self.board_widget.update(); self.update_opening_display()

    def opening_end(self):
        row = self.opening_list.currentRow()
        if row < 0: return
        data = self.opening_data[row]
        while self.opening_step_idx < len(data['uci_moves']):
            uci = data['uci_moves'][self.opening_step_idx]
            move, promo = self.engine.parse_uci(uci)
            if move: self.engine.make_move(move[0][0], move[0][1], move[1][0], move[1][1], promo)
            self.opening_step_idx += 1
        self.board_widget.selected = None; self.board_widget.legal_targets = []
        self.board_widget.update(); self.update_opening_display(); self.snd.play("move")
        log(f"Opening: skipped to end (step {self.opening_step_idx})", "OPENINGS")


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(palette.ColorRole.WindowText, Qt.white)
    palette.setColor(palette.ColorRole.Base, QColor(35, 35, 35))
    palette.setColor(palette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(palette.ColorRole.ToolTipBase, QColor(25, 25, 25))
    palette.setColor(palette.ColorRole.ToolTipText, Qt.white)
    palette.setColor(palette.ColorRole.Text, Qt.white)
    palette.setColor(palette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(palette.ColorRole.ButtonText, Qt.white)
    palette.setColor(palette.ColorRole.BrightText, Qt.red)
    palette.setColor(palette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(palette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(palette.ColorRole.HighlightedText, QColor(35, 35, 35))
    app.setPalette(palette)
    window = MainWindow(); window.show()
    log("Chess Learning App running", "APP")
    sys.exit(app.exec())