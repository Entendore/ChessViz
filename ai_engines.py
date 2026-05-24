"""Chess Video Maker Pro — AI Engines"""
import math
import random
import logging
import chess

logger = logging.getLogger("ChessVideoMaker.AI")


class HeuristicEvaluator:
    PV = {
        chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
        chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 20000,
    }
    PT = [
        0,0,0,0,0,0,0,0, 5,10,10,-20,-20,10,10,5,
        5,-5,-10,0,0,-10,-5,5, 0,0,0,20,20,0,0,0,
        5,5,10,25,25,10,5,5, 10,-5,0,10,10,0,-5,10,
        -15,-15,-20,-5,-5,-20,-15,-15, 0,0,0,0,0,0,0,0,
    ]

    def evaluate(self, board):
        if board.is_checkmate():
            return -10000 if board.turn == chess.WHITE else 10000
        if board.is_stalemate() or board.is_insufficient_material():
            return 0
        s = 0
        for sq in chess.SQUARES:
            pc = board.piece_at(sq)
            if pc:
                v = self.PV[pc.piece_type]
                if pc.piece_type == chess.PAWN:
                    idx = sq if pc.color == chess.WHITE else chess.square_mirror(sq)
                    v += self.PT[idx]
                s += v if pc.color == chess.WHITE else -v
        return s


class MinimaxEngine:
    def __init__(self):
        self.ev = HeuristicEvaluator(); self.nodes = 0

    def search(self, board, depth):
        self.nodes = 0; bm = None
        a = -float('inf'); b = float('inf'); be = -float('inf')
        pol = {}
        for m in board.legal_moves:
            board.push(m); e = -self._neg(board, depth-1, -b, -a); board.pop()
            pol[m.uci()] = e
            if e > be: be = e; bm = m
            a = max(a, e)
        if pol:
            mn, mx = min(pol.values()), max(pol.values())
            r = mx - mn if mx != mn else 1
            pol = {k: (v-mn)/r for k, v in pol.items()}
        return bm, (be if board.turn == chess.WHITE else -be), self.nodes, pol

    def _neg(self, board, d, a, b):
        self.nodes += 1
        if d == 0 or board.is_game_over():
            ev = self.ev.evaluate(board)
            return ev if board.turn == chess.WHITE else -ev
        for m in board.legal_moves:
            board.push(m); e = -self._neg(board, d-1, -b, -a); board.pop()
            if e >= b: return b
            if e > a: a = e
        return a


class MCTSNode:
    def __init__(self, board, parent=None, move=None):
        self.board = board; self.parent = parent; self.move = move
        self.children = []; self.wins = 0.0; self.visits = 0
        self.untried = list(board.legal_moves)

    def ucb1(self, c=1.414):
        if self.visits == 0: return float('inf')
        return (self.wins/self.visits) + c * math.sqrt(math.log(self.parent.visits)/self.visits)

    def best_child(self): return max(self.children, key=lambda x: x.ucb1())

    def expand(self):
        m = self.untried.pop(); nb = self.board.copy(); nb.push(m)
        c = MCTSNode(nb, self, m); self.children.append(c); return c


class MCTSEngine:
    def __init__(self): self.ev = HeuristicEvaluator()

    def search(self, board, iters):
        root = MCTSNode(board)
        for _ in range(iters):
            n = root
            while not n.untried and n.children: n = n.best_child()
            if n.untried: n = n.expand()
            sc = self._roll(n.board)
            while n:
                n.visits += 1
                n.wins += sc if n.board.turn != board.turn else (1 - sc)
                n = n.parent
        bm = max(root.children, key=lambda c: c.visits).move if root.children else None
        pol = {}
        if root.children:
            tv = sum(c.visits for c in root.children)
            pol = {c.move.uci(): c.visits/tv if tv else 0 for c in root.children}
        return bm, self.ev.evaluate(board), root.visits, pol

    def _roll(self, board, d=10):
        if board.is_checkmate():
            return 0.0 if board.turn == chess.WHITE else 1.0
        if board.is_stalemate(): return 0.5
        if d == 0:
            return 1.0 / (1.0 + math.exp(-0.004 * self.ev.evaluate(board)))
        m = random.choice(list(board.legal_moves)); board.push(m)
        s = self._roll(board, d-1); board.pop(); return s