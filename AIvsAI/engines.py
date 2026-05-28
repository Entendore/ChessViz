"""Chess engines — Minimax (α-β), MCTS, and Stockfish UCI wrapper.

All engines operate on python-chess Board objects for consistency.
"""

import random
import time
import logging
import subprocess
import threading
from typing import Optional

import chess

from constants import PIECE_VAL, PST, FILES_STR, RANKS_STR, log

logger = logging.getLogger("AIvsAI2MP4")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


# ════════════════════════════════════════════════════════════════════
#  Minimax with Alpha-Beta Pruning
# ════════════════════════════════════════════════════════════════════

class MinimaxEngine:
    """Minimax engine using python-chess for move generation."""

    def __init__(self):
        self._nodes = 0

    def search(self, board: chess.Board, depth: int):
        """
        Returns (chess.Move, eval_cp, nodes_searched, policy_dict).
        eval_cp is from White's POV.
        """
        self._nodes = 0
        is_white = board.turn == chess.WHITE

        best_move = None
        best_score = float('-inf')
        alpha = float('-inf')
        beta = float('inf')
        policy = {}

        moves = list(board.legal_moves)
        moves.sort(key=lambda m: (
            0 if board.is_capture(m) else (1 if board.gives_check(m) else 2)
        ))

        for move in moves:
            board.push(move)
            score = -self._alphabeta(board, depth - 1, -beta, -alpha,
                                     not is_white)
            board.pop()
            self._nodes += 1

            policy[move.uci()] = score
            if score > best_score:
                best_score = score
                best_move = move
            alpha = max(alpha, score)

        eval_cp = best_score if is_white else -best_score
        return best_move, eval_cp, self._nodes, policy

    def _alphabeta(self, board, depth, alpha, beta, maximizing):
        if depth == 0 or board.is_game_over():
            if depth == 0 and not board.is_game_over():
                return self._quiesce(board, alpha, beta, 3)
            return self._evaluate(board)

        self._nodes += 1
        moves = list(board.legal_moves)
        moves.sort(key=lambda m: (
            0 if board.is_capture(m) else (1 if board.gives_check(m) else 2)
        ))

        if maximizing:
            value = float('-inf')
            for move in moves:
                board.push(move)
                value = max(value, self._alphabeta(board, depth - 1, alpha, beta, False))
                board.pop()
                alpha = max(alpha, value)
                if alpha >= beta:
                    break
            return value
        else:
            value = float('inf')
            for move in moves:
                board.push(move)
                value = min(value, self._alphabeta(board, depth - 1, alpha, beta, True))
                board.pop()
                beta = min(beta, value)
                if alpha >= beta:
                    break
            return value

    def _quiesce(self, board, alpha, beta, depth_left):
        """Quiescence search — only examine captures."""
        self._nodes += 1
        stand_pat = self._evaluate(board)

        if depth_left == 0:
            return stand_pat

        if stand_pat >= beta:
            return beta
        alpha = max(alpha, stand_pat)

        for move in board.legal_moves:
            if not board.is_capture(move):
                continue
            board.push(move)
            score = -self._quiesce(board, -beta, -alpha, depth_left - 1)
            board.pop()
            if score >= beta:
                return beta
            alpha = max(alpha, score)
        return alpha

    def _evaluate(self, board: chess.Board) -> int:
        """Static evaluation in centipawns from the side-to-move's POV."""
        if board.is_checkmate():
            return -30000
        if board.is_stalemate() or board.is_insufficient_material():
            return 0

        score = 0
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece is None:
                continue
            pt = piece.symbol().upper()
            val = PIECE_VAL.get(pt, 0)
            pst = PST.get(pt)
            if piece.color == chess.WHITE:
                rank = chess.square_rank(sq)
                file_ = chess.square_file(sq)
                score += val + (pst[7 - rank][file_] if pst else 0)
            else:
                rank = chess.square_rank(sq)
                file_ = chess.square_file(sq)
                score -= val + (pst[rank][file_] if pst else 0)

        mobility = board.legal_moves.count()
        mob_bonus = 5 * mobility
        if board.turn == chess.WHITE:
            score += mob_bonus
        else:
            score -= mob_bonus

        return score if board.turn == chess.WHITE else -score


# ════════════════════════════════════════════════════════════════════
#  Monte Carlo Tree Search
# ════════════════════════════════════════════════════════════════════

class _MCTSNode:
    __slots__ = ('board', 'move', 'parent', 'children',
                 'visits', 'wins', 'untried_moves')

    def __init__(self, board, move=None, parent=None):
        self.board = board
        self.move = move
        self.parent = parent
        self.children = []
        self.visits = 0
        self.wins = 0.0
        self.untried_moves = list(board.legal_moves)
        random.shuffle(self.untried_moves)

    def ucb1(self, c=1.414):
        if self.visits == 0:
            return float('inf')
        return (self.wins / self.visits +
                c * (2.0 * (self.parent.visits + 1) / (self.visits + 1)) ** 0.5)

    def best_child(self):
        return max(self.children, key=lambda ch: ch.ucb1())

    def expand(self):
        move = self.untried_moves.pop()
        next_board = self.board.copy()
        next_board.push(move)
        child = _MCTSNode(next_board, move=move, parent=self)
        self.children.append(child)
        return child

    def is_fully_expanded(self):
        return len(self.untried_moves) == 0

    def is_terminal(self):
        return self.board.is_game_over()


class MCTSEngine:
    """MCTS engine using python-chess Board."""

    def __init__(self):
        self._nodes = 0

    def search(self, board: chess.Board, iterations: int):
        """
        Returns (chess.Move, eval_cp, nodes_visited, policy_dict).
        eval_cp is from White's POV.
        """
        self._nodes = 0
        root = _MCTSNode(board.copy())

        if not list(board.legal_moves):
            return None, 0.0, 0, {}

        for _ in range(iterations):
            node = root
            while not node.is_terminal() and node.is_fully_expanded():
                node = node.best_child()
            if not node.is_terminal() and not node.is_fully_expanded():
                node = node.expand()
            self._nodes += 1
            result = self._rollout(node.board.copy())
            while node is not None:
                node.visits += 1
                if node.board.turn == chess.WHITE:
                    node.wins += (1.0 - result)
                else:
                    node.wins += result
                node = node.parent

        if not root.children:
            return None, 0.0, self._nodes, {}

        best = max(root.children, key=lambda ch: ch.visits)
        policy = {ch.move.uci(): ch.visits / max(1, root.visits) for ch in root.children}

        wr = best.wins / max(1, best.visits)
        eval_cp = (wr - 0.5) * 600
        if board.turn == chess.BLACK:
            eval_cp = -eval_cp

        return best.move, eval_cp, self._nodes, policy

    def _rollout(self, board: chess.Board, max_moves: int = 80) -> float:
        """Random playout; returns 1.0 if White wins, 0.0 if Black wins, 0.5 draw."""
        for _ in range(max_moves):
            if board.is_game_over():
                break
            moves = list(board.legal_moves)
            captures = [m for m in moves if board.is_capture(m)]
            if captures and random.random() < 0.3:
                move = random.choice(captures)
            else:
                move = random.choice(moves)
            board.push(move)

        if board.is_checkmate():
            return 1.0 if board.turn == chess.BLACK else 0.0
        return 0.5


# ════════════════════════════════════════════════════════════════════
#  Stockfish UCI Wrapper
# ════════════════════════════════════════════════════════════════════

class SyncUCI:
    """Synchronous UCI protocol wrapper for Stockfish."""

    def __init__(self, path: str, timeout: int = 30):
        self._path = path
        self._timeout = timeout
        self._lock = threading.Lock()
        try:
            self._proc = subprocess.Popen(
                [path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            self._uci_init()
        except Exception as e:
            logger.error("Failed to start Stockfish: %s", e)
            raise

    def _send(self, cmd: str):
        self._proc.stdin.write((cmd + "\n").encode())
        self._proc.stdin.flush()

    def _read_line(self) -> str:
        return self._proc.stdout.readline().decode().strip()

    def _uci_init(self):
        self._send("uci")
        while True:
            line = self._read_line()
            if line == "uciok":
                break
        self._send("isready")
        while True:
            line = self._read_line()
            if line == "readyok":
                break

    def analyse(self, fen: str, depth: int = 18,
                movetime: Optional[int] = None) -> tuple:
        """
        Analyse position; returns (best_move_uci, score_cp).
        score_cp is from White's POV.
        """
        with self._lock:
            self._send("ucinewgame")
            self._send(f"position fen {fen}")
            if movetime is not None:
                self._send(f"go movetime {movetime}")
            else:
                self._send(f"go depth {depth}")

            best_move = None
            score_cp = 0.0
            while True:
                line = self._read_line()
                if not line:
                    break
                parts = line.split()
                if parts and parts[0] == "bestmove":
                    best_move = parts[1] if len(parts) > 1 else None
                    break
                if "score" in parts:
                    idx = parts.index("score")
                    if idx + 2 < len(parts):
                        stype = parts[idx + 1]
                        sval = parts[idx + 2]
                        if stype == "cp":
                            score_cp = int(sval)
                        elif stype == "mate":
                            mate_plies = int(sval)
                            score_cp = 10000 - abs(mate_plies)
                            if mate_plies < 0:
                                score_cp = -score_cp

            board = chess.Board(fen)
            if board.turn == chess.BLACK:
                score_cp = -score_cp

            return best_move, score_cp

    def close(self):
        try:
            self._send("quit")
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
#  Batch RGB → BGR conversion (optional GPU acceleration)
# ════════════════════════════════════════════════════════════════════

def rgb_to_bgr_batch(frames):
    """Convert a list of RGB numpy arrays to BGR for OpenCV.
    Uses CuPy if available, else NumPy batch."""
    if not HAS_NUMPY:
        import cv2
        return [cv2.cvtColor(f, cv2.COLOR_RGB2BGR) for f in frames]

    try:
        import cupy as cp
        results = []
        for f in frames:
            gpu = cp.asarray(f)
            bgr = cp.stack([gpu[:, :, 2], gpu[:, :, 1], gpu[:, :, 0]], axis=2)
            results.append(cp.asnumpy(bgr))
        return results
    except ImportError:
        pass

    arr = np.stack(frames)
    bgr = arr[:, :, :, ::-1].copy()
    return [bgr[i] for i in range(len(frames))]


# ════════════════════════════════════════════════════════════════════
#  Legacy ChessEngine (backward compat)
# ════════════════════════════════════════════════════════════════════

class ChessEngine:
    def __init__(self):
        self.reset()

    def reset(self):
        self.board = [
            ['r','n','b','q','k','b','n','r'],
            ['p','p','p','p','p','p','p','p'],
            ['.','.','.','.','.','.','.','.'],
            ['.','.','.','.','.','.','.','.'],
            ['.','.','.','.','.','.','.','.'],
            ['.','.','.','.','.','.','.','.'],
            ['P','P','P','P','P','P','P','P'],
            ['R','N','B','Q','K','B','N','R'],
        ]
        self.turn = 'w'
        self.castling = {'K': True, 'Q': True, 'k': True, 'q': True}
        self.ep = None
        self.history = []
        self.game_over = False
        self.result = ""
        self.last_move = None

    @staticmethod
    def is_white(p):  return p != '.' and p.isupper()
    @staticmethod
    def is_black(p):  return p != '.' and p.islower()
    @staticmethod
    def color_of(p):  return 'w' if p.isupper() else ('b' if p != '.' else None)

    def copy_board(self):  return [r[:] for r in self.board]

    def find_king(self, color):
        k = 'K' if color == 'w' else 'k'
        for r in range(8):
            for c in range(8):
                if self.board[r][c] == k: return (r, c)
        return None

    def attacked(self, row, col, by):
        kn = 'N' if by == 'w' else 'n'
        for dr, dc in [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]:
            r2, c2 = row+dr, col+dc
            if 0<=r2<8 and 0<=c2<8 and self.board[r2][c2]==kn: return True
        ki = 'K' if by=='w' else 'k'
        for dr in (-1,0,1):
            for dc in (-1,0,1):
                if dr==0 and dc==0: continue
                r2,c2 = row+dr, col+dc
                if 0<=r2<8 and 0<=c2<8 and self.board[r2][c2]==ki: return True
        pw = 'P' if by=='w' else 'p'; pd = 1 if by=='w' else -1; r2 = row+pd
        if 0<=r2<8:
            for dc2 in (-1,1):
                c2 = col+dc2
                if 0<=c2<8 and self.board[r2][c2]==pw: return True
        rk = 'R' if by=='w' else 'r'; qu = 'Q' if by=='w' else 'q'
        for dr,dc in [(0,1),(0,-1),(1,0),(-1,0)]:
            r2,c2 = row+dr, col+dc
            while 0<=r2<8 and 0<=c2<8:
                p = self.board[r2][c2]
                if p!='.':
                    if p in (rk,qu): return True
                    break
                r2+=dr; c2+=dc
        bi = 'B' if by=='w' else 'b'
        for dr,dc in [(1,1),(1,-1),(-1,1),(-1,-1)]:
            r2,c2 = row+dr, col+dc
            while 0<=r2<8 and 0<=c2<8:
                p = self.board[r2][c2]
                if p!='.':
                    if p in (bi,qu): return True
                    break
                r2+=dr; c2+=dc
        return False

    def in_check(self, color):
        kp = self.find_king(color)
        return self.attacked(kp[0], kp[1], 'b' if color=='w' else 'w') if kp else True

    def pseudo_moves(self, r, c):
        p = self.board[r][c]
        if p=='.': return []
        co = self.color_of(p); pt = p.upper(); mv = []
        if pt=='P':
            d = -1 if co=='w' else 1; sr = 6 if co=='w' else 1; nr = r+d
            if 0<=nr<8 and self.board[nr][c]=='.':
                mv.append((nr,c)); nr2 = r+2*d
                if r==sr and self.board[nr2][c]=='.': mv.append((nr2,c))
            for dc in (-1,1):
                nc = c+dc; nr2 = r+d
                if 0<=nr2<8 and 0<=nc<8:
                    t = self.board[nr2][nc]
                    if (t!='.' and self.color_of(t)!=co) or (self.ep and (nr2,nc)==self.ep): mv.append((nr2,nc))
        elif pt=='N':
            for dr,dc in [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]:
                r2,c2 = r+dr, c+dc
                if 0<=r2<8 and 0<=c2<8:
                    t = self.board[r2][c2]
                    if t=='.' or self.color_of(t)!=co: mv.append((r2,c2))
        elif pt in ('B','R','Q'):
            dirs = []
            if pt in ('B','Q'): dirs += [(1,1),(1,-1),(-1,1),(-1,-1)]
            if pt in ('R','Q'): dirs += [(0,1),(0,-1),(1,0),(-1,0)]
            for dr,dc in dirs:
                r2,c2 = r+dr, c+dc
                while 0<=r2<8 and 0<=c2<8:
                    t = self.board[r2][c2]
                    if t=='.': mv.append((r2,c2))
                    elif self.color_of(t)!=co: mv.append((r2,c2)); break
                    else: break
                    r2+=dr; c2+=dc
        elif pt=='K':
            for dr in (-1,0,1):
                for dc in (-1,0,1):
                    if dr==0 and dc==0: continue
                    r2,c2 = r+dr, c+dc
                    if 0<=r2<8 and 0<=c2<8:
                        t = self.board[r2][c2]
                        if t=='.' or self.color_of(t)!=co: mv.append((r2,c2))
            enemy = 'b' if co=='w' else 'w'
            if co=='w' and r==7 and c==4:
                if (self.castling['K'] and self.board[7][5]=='.' and self.board[7][6]=='.' and self.board[7][7]=='R'):
                    if not self.attacked(7,4,enemy) and not self.attacked(7,5,enemy) and not self.attacked(7,6,enemy): mv.append((7,6))
                if (self.castling['Q'] and self.board[7][3]=='.' and self.board[7][2]=='.' and self.board[7][1]=='.' and self.board[7][0]=='R'):
                    if not self.attacked(7,4,enemy) and not self.attacked(7,3,enemy) and not self.attacked(7,2,enemy): mv.append((7,2))
            elif co=='b' and r==0 and c==4:
                if (self.castling['k'] and self.board[0][5]=='.' and self.board[0][6]=='.' and self.board[0][7]=='r'):
                    if not self.attacked(0,4,enemy) and not self.attacked(0,5,enemy) and not self.attacked(0,6,enemy): mv.append((0,6))
                if (self.castling['q'] and self.board[0][3]=='.' and self.board[0][2]=='.' and self.board[0][1]=='.' and self.board[0][0]=='r'):
                    if not self.attacked(0,4,enemy) and not self.attacked(0,3,enemy) and not self.attacked(0,2,enemy): mv.append((0,2))
        return mv

    def legal_moves(self, r, c):
        p = self.board[r][c]
        if p=='.' or self.color_of(p)!=self.turn: return []
        co = self.color_of(p); out = []
        for tr,tc in self.pseudo_moves(r,c):
            sb = self.copy_board(); sep = self.ep; sc = dict(self.castling)
            self.board[tr][tc] = p; self.board[r][c] = '.'
            if p.upper()=='P' and self.ep and (tr,tc)==self.ep: self.board[r][tc] = '.'
            if p.upper()=='K' and abs(tc-c)==2:
                if tc==6: self.board[r][5]=self.board[r][7]; self.board[r][7]='.'
                elif tc==2: self.board[r][3]=self.board[r][0]; self.board[r][0]='.'
            chk = self.in_check(co)
            self.board = sb; self.ep = sep; self.castling = sc
            if not chk: out.append((tr,tc))
        return out

    def all_legal_moves(self, color=None):
        if color is None: color = self.turn
        out = []
        for r in range(8):
            for c in range(8):
                if self.color_of(self.board[r][c])==color:
                    for m in self.legal_moves(r,c): out.append(((r,c),m))
        return out

    def make_move(self, fr, fc, tr, tc, promo=None):
        p = self.board[fr][fc]
        if p=='.': return None
        co = self.color_of(p); cap = self.board[tr][tc]
        info = {'from':(fr,fc),'to':(tr,tc),'piece':p,'captured':cap,
                'castle':False,'ep':False,'promo':None,'check':False,'mate':False,'notation':''}
        self.history.append({'board':self.copy_board(),'turn':self.turn,
            'castling':dict(self.castling),'ep':self.ep,
            'last_move':self.last_move,'game_over':self.game_over,'result':self.result})
        if p.upper()=='P' and self.ep and (tr,tc)==self.ep:
            info['ep']=True; info['captured']=self.board[fr][tc]; self.board[fr][tc]='.'
        self.ep = None
        if p.upper()=='P' and abs(tr-fr)==2: self.ep = ((fr+tr)//2, fc)
        if p.upper()=='K' and abs(tc-fc)==2:
            info['castle']=True
            if tc==6: self.board[fr][5]=self.board[fr][7]; self.board[fr][7]='.'
            elif tc==2: self.board[fr][3]=self.board[fr][0]; self.board[fr][0]='.'
        self.board[tr][tc]=p; self.board[fr][fc]='.'
        prow = 0 if co=='w' else 7
        if p.upper()=='P' and tr==prow:
            pp = promo or ('Q' if co=='w' else 'q')
            self.board[tr][tc]=pp; info['promo']=pp
        if (fr,fc)==(7,4): self.castling['K']=False; self.castling['Q']=False
        if (fr,fc)==(0,4): self.castling['k']=False; self.castling['q']=False
        for pos,key in [((7,7),'K'),((7,0),'Q'),((0,7),'k'),((0,0),'q')]:
            if (fr,fc)==pos or (tr,tc)==pos: self.castling[key]=False
        self.last_move = ((fr,fc),(tr,tc))
        self.turn = 'b' if self.turn=='w' else 'w'
        if self.in_check(self.turn):
            info['check']=True
            if not self.all_legal_moves(self.turn):
                info['mate']=True; self.game_over=True
                self.result = "White wins!" if self.turn=='b' else "Black wins!"
        elif not self.all_legal_moves(self.turn):
            self.game_over=True; self.result="Stalemate — Draw"
        info['notation'] = self._nota(info)
        return info

    def undo(self):
        if not self.history: return False
        s = self.history.pop()
        self.board=s['board']; self.turn=s['turn']; self.castling=s['castling']
        self.ep=s['ep']; self.last_move=s['last_move']
        self.game_over=s['game_over']; self.result=s['result']
        return True

    def _nota(self, info):
        if info['castle']: n = "O-O" if info['to'][1]==6 else "O-O-O"
        else:
            pt=info['piece'].upper(); fr,fc=info['from']; tr,tc=info['to']
            n = "" if pt=='P' else pt
            if info['captured']!='.':
                if pt=='P': n += FILES_STR[fc]
                n += 'x'
            n += FILES_STR[tc]+RANKS_STR[tr]
            if info['promo']: n += '='+info['promo'].upper()
        if info['mate']: n+='#'
        elif info['check']: n+='+'
        return n

    def load_fen(self, fen):
        parts = fen.split(); rows = parts[0].split('/')
        self.board = []
        for row_str in rows:
            row = []
            for ch in row_str:
                if ch.isdigit(): row.extend(['.']*int(ch))
                else: row.append(ch)
            self.board.append(row)
        self.turn = 'w' if parts[1]=='w' else 'b'
        self.castling = {'K':'K' in parts[2],'Q':'Q' in parts[2],'k':'k' in parts[2],'q':'q' in parts[2]}
        self.ep = None
        if len(parts)>3 and parts[3]!='-':
            c = ord(parts[3][0])-ord('a'); r = 8-int(parts[3][1])
            self.ep = (r,c)
        self.history=[]; self.game_over=False; self.result=""; self.last_move=None

    def parse_uci(self, uci_str):
        if not uci_str or len(uci_str)<4: return None, None
        fc = ord(uci_str[0])-ord('a'); fr = 8-int(uci_str[1])
        tc = ord(uci_str[2])-ord('a'); tr = 8-int(uci_str[3])
        promo = uci_str[4] if len(uci_str)==5 else None
        return ((fr,fc),(tr,tc)), promo

    def evaluate(self):
        s = 0
        for r in range(8):
            for c in range(8):
                p = self.board[r][c]
                if p=='.': continue
                pt = p.upper(); v = PIECE_VAL.get(pt,0); t = PST.get(pt)
                if p.isupper(): s += v + (t[r][c] if t else 0)
                else: s -= v + (t[7-r][c] if t else 0)
        return s