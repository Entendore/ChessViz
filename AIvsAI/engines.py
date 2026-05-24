"""Chess AI engines: Minimax (Alpha-Beta), MCTS (Monte Carlo),
and synchronous UCI (Stockfish) wrapper."""

import math
import random
import os
import time
import subprocess
import numpy as np

import chess

# ═══════════════════════════════════════════════════════════════════
#  Optional dependencies
# ═══════════════════════════════════════════════════════════════════
try:
    from numba import njit, int8, int32, int64, float64
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

try:
    import cupy as cp
    HAS_CUPY = True
except ImportError:
    HAS_CUPY = False


# ═══════════════════════════════════════════════════════════════════
#  Board Representation  (int8[64]: +white / -black)
#   0=empty  1=pawn  2=knight  3=bishop  4=rook  5=queen  6=king
# ═══════════════════════════════════════════════════════════════════
_PIECE_CHAR = {'p': 1, 'n': 2, 'b': 3, 'r': 4, 'q': 5, 'k': 6}

PIECE_VAL = np.array([0, 100, 320, 330, 500, 900, 20000], dtype=np.int32)

# ── Piece-square tables (White perspective, a1 = idx 0) ────────
_PST_W = {
    1: np.array([  # Pawn
         0,  0,  0,  0,  0,  0,  0,  0,
         5, 10, 10,-20,-20, 10, 10,  5,
         5, -5,-10,  0,  0,-10, -5,  5,
         0,  0,  0, 20, 20,  0,  0,  0,
         5,  5, 10, 25, 25, 10,  5,  5,
        10, -5,  0, 10, 10,  0, -5, 10,
       -15,-15,-20, -5, -5,-20,-15,-15,
         0,  0,  0,  0,  0,  0,  0,  0], dtype=np.int32),
    2: np.array([  # Knight
       -50,-40,-30,-30,-30,-30,-40,-50,
       -40,-20,  0,  0,  0,  0,-20,-40,
       -30,  0, 10, 15, 15, 10,  0,-30,
       -30,  5, 15, 20, 20, 15,  5,-30,
       -30,  0, 15, 20, 20, 15,  0,-30,
       -30,  5, 10, 15, 15, 10,  5,-30,
       -40,-20,  0,  5,  5,  0,-20,-40,
       -50,-40,-30,-30,-30,-30,-40,-50], dtype=np.int32),
    3: np.array([  # Bishop
       -20,-10,-10,-10,-10,-10,-10,-20,
       -10,  5,  0,  0,  0,  0,  5,-10,
       -10, 10, 10, 10, 10, 10, 10,-10,
       -10,  0, 10, 10, 10, 10,  0,-10,
       -10,  5,  5, 10, 10,  5,  5,-10,
       -10,  0,  5, 10, 10,  5,  0,-10,
       -10,  0,  0,  0,  0,  0,  0,-10,
       -20,-10,-10,-10,-10,-10,-10,-20], dtype=np.int32),
    4: np.array([  # Rook
         0,  0,  0,  5,  5,  0,  0,  0,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
         5, 10, 10, 10, 10, 10, 10,  5,
         0,  0,  0,  0,  0,  0,  0,  0], dtype=np.int32),
    5: np.array([  # Queen
       -20,-10,-10, -5, -5,-10,-10,-20,
       -10,  0,  5,  0,  0,  0,  0,-10,
       -10,  5,  5,  5,  5,  5,  0,-10,
         0,  0,  5,  5,  5,  5,  0, -5,
        -5,  0,  5,  5,  5,  5,  0, -5,
       -10,  0,  5,  5,  5,  5,  0,-10,
       -10,  0,  0,  0,  0,  0,  0,-10,
       -20,-10,-10, -5, -5,-10,-10,-20], dtype=np.int32),
    6: np.array([  # King (middlegame)
        20, 30, 10,  0,  0, 10, 30, 20,
        20, 20,  0,  0,  0,  0, 20, 20,
       -10,-20,-20,-20,-20,-20,-20,-10,
       -20,-30,-30,-40,-40,-30,-30,-20,
       -30,-40,-40,-50,-50,-40,-40,-30,
       -30,-40,-40,-50,-50,-40,-40,-30,
       -30,-40,-40,-50,-50,-40,-40,-30,
       -30,-40,-40,-50,-50,-40,-40,-30], dtype=np.int32),
}

# Build mirrored tables for Black (flip rank)
def _mirror_pst(table):
    out = np.empty(64, dtype=np.int32)
    for sq in range(64):
        f, r = sq % 8, sq // 8
        out[sq] = table[f + (7 - r) * 8]
    return out

_PST_B = {pt: _mirror_pst(t) for pt, t in _PST_W.items()}

# Stacked array [color 0=W 1=B][piece_type 1-6][sq 0-63]
PST_ALL = np.zeros((2, 7, 64), dtype=np.int32)
for pt in range(1, 7):
    PST_ALL[0, pt] = _PST_W[pt]
    PST_ALL[1, pt] = _PST_B[pt]

# ═══════════════════════════════════════════════════════════════════
#  Zobrist Keys
# ═══════════════════════════════════════════════════════════════════
_rng = np.random.RandomState(54321)
ZOBRIST_PIECES = _rng.randint(0, 2**63, size=(13, 64), dtype=np.int64)
ZOBRIST_SIDE   = _rng.randint(0, 2**63, dtype=np.int64)

# ═══════════════════════════════════════════════════════════════════
#  Fast Board → Array Conversion (FEN-based, ~3-5× faster than
#  iterating piece_at for all 64 squares)
# ═══════════════════════════════════════════════════════════════════
def board_to_array(board):
    """Convert *board* to int8[64] using FEN parsing."""
    arr = np.zeros(64, dtype=np.int8)
    fen = board.board_fen()
    sq = 56                         # a8
    for ch in fen:
        if ch == '/':
            sq -= 16               # next rank down
        elif ch.isdigit():
            sq += int(ch)
        else:
            pt = _PIECE_CHAR[ch.lower()]
            arr[sq] = pt if ch.isupper() else -pt
            sq += 1
    return arr

# ═══════════════════════════════════════════════════════════════════
#  Numba-JIT Evaluation & Hashing  (or pure-numpy fallback)
# ═══════════════════════════════════════════════════════════════════
if HAS_NUMBA:

    @njit(int32(int8[:]), cache=True)
    def evaluate_numba(board_arr):
        """Full PST evaluation — Numba JIT compiled."""
        score = int32(0)
        for sq in range(64):
            pc = board_arr[sq]
            if pc == 0:
                continue
            abs_pc = pc if pc > 0 else -pc
            val = PIECE_VAL[abs_pc]
            cidx = 0 if pc > 0 else 1
            pst  = PST_ALL[cidx, abs_pc, sq]
            if pc > 0:
                score += val + pst
            else:
                score -= val + pst
        return score

    @njit(int64(int8[:], int64), cache=True)
    def zobrist_hash_numba(board_arr, side_key):
        h = int64(0)
        for sq in range(64):
            pc = board_arr[sq]
            if pc != 0:
                h ^= ZOBRIST_PIECES[pc + 6, sq]
        h ^= side_key
        return h

else:

    def evaluate_numba(board_arr):
        """Vectorised numpy fallback (still faster than pure-Python loop)."""
        abs_pc  = np.abs(board_arr).astype(np.int32)
        cidx    = (board_arr < 0).astype(np.int32)
        sqs     = np.arange(64, dtype=np.int32)
        vals    = PIECE_VAL[abs_pc]
        psts    = PST_ALL[cidx, abs_pc, sqs]
        sign    = np.where(board_arr > 0, 1, np.where(board_arr < 0, -1, 0))
        return int(np.sum((vals + psts) * sign))

    def zobrist_hash_numba(board_arr, side_key):
        h = np.int64(0)
        for sq in range(64):
            pc = board_arr[sq]
            if pc != 0:
                h ^= ZOBRIST_PIECES[pc + 6, sq]
        h ^= side_key
        return int(h)


# ═══════════════════════════════════════════════════════════════════
#  Transposition Table
# ═══════════════════════════════════════════════════════════════════
EXACT  = 1
LOWER  = 2   # beta cutoff  (score ≥ beta)
UPPER  = 3   # fail-low     (score ≤ alpha)

MAX_PLY = 128

class TranspositionTable:
    """Fixed-size, replace-by-depth transposition table."""

    def __init__(self, size=1 << 20):      # ~1 M slots
        self.size    = size
        self.keys    = np.zeros(size, dtype=np.int64)
        self.values  = np.zeros(size, dtype=np.int32)
        self.depths  = np.zeros(size, dtype=np.int8)
        self.flags   = np.zeros(size, dtype=np.int8)
        self.moves   = [None] * size

    def _idx(self, key):
        return int(key & (self.size - 1))

    def clear(self):
        self.keys[:]   = 0
        self.depths[:] = 0
        self.flags[:]  = 0

    def store(self, key, depth, value, flag, best_move=None):
        i = self._idx(key)
        # replace-if-deeper
        if self.depths[i] <= depth or self.keys[i] == 0:
            self.keys[i]   = key
            self.values[i] = value
            self.depths[i] = depth
            self.flags[i]  = flag
            self.moves[i]  = best_move.uci() if best_move else None

    def probe(self, key, depth, alpha, beta):
        """Return (cutoff_score_or_None, tt_move_or_None)."""
        i = self._idx(key)
        if self.keys[i] != key:
            return None, None
        tt_move = (chess.Move.from_uci(self.moves[i])
                   if self.moves[i] else None)
        if self.depths[i] >= depth:
            f = self.flags[i]
            v = int(self.values[i])
            if f == EXACT:
                return v, tt_move
            if f == LOWER and v >= beta:
                return v, tt_move
            if f == UPPER and v <= alpha:
                return v, tt_move
        return None, tt_move


# ═══════════════════════════════════════════════════════════════════
#  Move Ordering Helpers
# ═══════════════════════════════════════════════════════════════════
_PIECE_ORDER = {chess.PAWN: 1, chess.KNIGHT: 2, chess.BISHOP: 3,
                chess.ROOK: 4, chess.QUEEN: 5, chess.KING: 6}

def _mvv_lva(board, move):
    """Most-Valuable-Victim – Least-Valuable-Attacker score."""
    victim   = board.piece_at(move.to_square)
    attacker = board.piece_at(move.from_square)
    vv = _PIECE_ORDER.get(victim.piece_type, 0)   if victim   else 0
    av = _PIECE_ORDER.get(attacker.piece_type, 0)  if attacker else 0
    return vv * 10 - av

def order_moves(board, moves, tt_move=None, killers=None):
    """Sort moves for best alpha-beta pruning.

    Priority: TT move → captures (MVV-LVA) → killers → quiet.
    """
    scored = []
    k1 = killers[0] if killers else None
    k2 = killers[1] if killers and len(killers) > 1 else None

    for m in moves:
        if m == tt_move:
            s = 2_000_000
        elif board.is_capture(m):
            s = 1_000_000 + _mvv_lva(board, m)
        elif m == k1:
            s = 900_000
        elif m == k2:
            s = 800_000
        else:
            s = 0
        scored.append((s, m))

    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored]


# ═══════════════════════════════════════════════════════════════════
#  CuPy Batch BGR Conversion (optional GPU acceleration)
# ═══════════════════════════════════════════════════════════════════
def rgb_to_bgr_batch_cpu(frames):
    """Convert list of (H,W,3) uint8 RGB arrays → BGR (numpy)."""
    return [f[:, :, ::-1].copy() for f in frames]

if HAS_CUPY:
    def rgb_to_bgr_batch_gpu(frames):
        """Batch RGB→BGR on GPU via CuPy (amortises PCIe transfer)."""
        stacked = np.stack(frames)                    # (N,H,W,3)
        gpu     = cp.asarray(stacked)
        bgr     = gpu[:, :, :, ::-1].copy()          # channel swap on GPU
        return [cp.asnumpy(bgr[i]) for i in range(len(frames))]
else:
    def rgb_to_bgr_batch_gpu(frames):
        return rgb_to_bgr_batch_cpu(frames)

def rgb_to_bgr_batch(frames):
    if HAS_CUPY and len(frames) >= 4:       # GPU only worthwhile for batches
        return rgb_to_bgr_batch_gpu(frames)
    return rgb_to_bgr_batch_cpu(frames)



# ════════════════════════════════════════════════════════════════════
#  Minimax (Alpha-Beta)  — Enhanced
# ════════════════════════════════════════════════════════════════════

class MinimaxEngine:
    """Alpha-Beta with TT, move ordering, iterative deepening,
    quiescence search, killer-move heuristic."""

    def __init__(self):
        self.nodes = 0
        self.tt = TranspositionTable()
        self._killers = [[None, None] for _ in range(MAX_PLY)]
        self._board_arr = None         
        self._state_stack = []

    # ── public ────────────────────────────────────────────────
    def search(self, board, depth):
        self.nodes = 0
        self.tt.clear()
        self._killers = [[None, None] for _ in range(MAX_PLY)]
        self._board_arr = board_to_array(board)
        self._state_stack = []

        best_move = None
        best_eval = -math.inf
        policy = {}

        # Iterative deepening: use shallow results to order deeper search
        for d in range(1, depth + 1):
            move, ev = self._search_root(board, d)
            if move is not None:
                best_move, best_eval = move, ev

        # Build policy from root TT entry
        tt_key = self._hash(board)
        _, tt_move = self.tt.probe(tt_key, 0, -math.inf, math.inf)
        for m in board.legal_moves:
            board.push(m)
            k = self._hash(board)
            v, _ = self.tt.probe(k, 0, -math.inf, math.inf)
            board.pop()
            policy[m.uci()] = v if v is not None else 0

        if policy:
            mn, mx = min(policy.values()), max(policy.values())
            rng = mx - mn if mx != mn else 1
            policy = {k: (v - mn) / rng for k, v in policy.items()}

        fe = best_eval if board.turn == chess.WHITE else -best_eval
        return best_move, fe, self.nodes, policy

    # ── root search ───────────────────────────────────────────
    def _search_root(self, board, depth):
        alpha, beta = -math.inf, math.inf
        best_move, best_eval = None, -math.inf
        tt_key = self._hash(board)
        _, tt_move = self.tt.probe(tt_key, depth, alpha, beta)
        moves = order_moves(board, list(board.legal_moves), tt_move, None)

        for move in moves:
            board.push(move)
            self._update_arr_push(board, move)
            e = -self._negamax(board, depth - 1, -beta, -alpha, 1)
            board.pop()
            self._update_arr_pop(board, move)
            if e > best_eval:
                best_eval, best_move = e, move
            alpha = max(alpha, e)

        if best_move:
            self.tt.store(tt_key, depth, best_eval,
                          EXACT, best_move)
        return best_move, best_eval

    # ── negamax ───────────────────────────────────────────────
    def _negamax(self, board, depth, alpha, beta, ply):
        self.nodes += 1

        # Terminal / leaf
        if board.is_game_over():
            if board.is_checkmate():
                return -10000 + ply       # prefer shorter mates
            return 0                      # stalemate / draw

        if depth <= 0:
            return self._quiescence(board, alpha, beta, ply)

        # TT probe
        tt_key = self._hash(board)
        tt_val, tt_move = self.tt.probe(tt_key, depth, alpha, beta)
        if tt_val is not None:
            return tt_val

        orig_alpha = alpha
        best_move = None
        moves = order_moves(board, list(board.legal_moves), tt_move, None)

        for move in moves:
            board.push(move)
            self._update_arr_push(board, move)
            e = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1)
            board.pop()
            self._update_arr_pop(board, move)

            if e >= beta:
                # Beta cutoff — store killer for quiet moves
                if not board.is_capture(move) and ply < MAX_PLY:
                    if move != self._killers[ply][0]:
                        self._killers[ply][1] = self._killers[ply][0]
                        self._killers[ply][0] = move
                self.tt.store(tt_key, depth, beta, LOWER, move)
                return beta

            if e > alpha:
                alpha = e
                best_move = move

        # Store TT entry
        if alpha <= orig_alpha:
            flag = UPPER
        else:
            flag = EXACT
        self.tt.store(tt_key, depth, alpha, flag, best_move)
        return alpha

    # ── quiescence search (captures only) ─────────────────────
    def _quiescence(self, board, alpha, beta, ply):
        self.nodes += 1
        stand_pat = self._evaluate(board)
        if stand_pat >= beta:
            return beta
        if stand_pat > alpha:
            alpha = stand_pat


        # Only look at captures
        captures = [m for m in board.legal_moves if board.is_capture(m)]
        captures.sort(key=lambda m: -_mvv_lva_q(board, m))

        for move in captures:
            # Delta pruning: skip if capture can't raise alpha
            victim = board.piece_at(move.to_square)
            if victim:
                if stand_pat + 200 + _piece_val_fast(victim.piece_type) < alpha:
                    continue

            if move.promotion is None:
                if stand_pat + 200 + _piece_val_fast(victim.piece_type) < alpha:
                    continue


            board.push(move)
            self._update_arr_push(board, move)
            e = -self._quiescence(board, -beta, -alpha, ply + 1)
            board.pop()
            self._update_arr_pop(board, move)

            if e >= beta:
                return beta
            if e > alpha:
                alpha = e
        return alpha

    # ── evaluation helpers ────────────────────────────────────
    def _evaluate(self, board):
        """Evaluate position using Numba/numpy fast evaluator."""
        ev = evaluate_numba(self._board_arr)
        return ev if board.turn == chess.WHITE else -ev

    def _hash(self, board):
        return zobrist_hash_numba(self._board_arr, ZOBRIST_SIDE
                                  if board.turn == chess.WHITE else 0)

    # ── incremental board-array updates ───────────────────────
    def _update_arr_push(self, board, move):
        """Incrementally update board_arr in O(1) after board.push(move)."""
        from_sq = move.from_square
        to_sq = move.to_square
        
        # Save state for pop: list of (square, old_value)
        changes = [
            (from_sq, self._board_arr[from_sq]),
            (to_sq, self._board_arr[to_sq])
        ]
        
        piece = self._board_arr[from_sq]
        
        # ── En Passant Detection ──────────────────────────────
        # A pawn moves diagonally to an empty square
        is_ep = False
        ep_captured_sq = -1
        if (move.promotion is None and abs(piece) == 1 and
                chess.square_file(from_sq) != chess.square_file(to_sq) and
                self._board_arr[to_sq] == 0):
            is_ep = True
            # The captured pawn is on the same file as `to_sq` but the same rank as `from_sq`
            ep_captured_sq = chess.square(chess.square_file(to_sq), 
                                          chess.square_rank(from_sq))
            changes.append((ep_captured_sq, self._board_arr[ep_captured_sq]))
            
        # ── Castling Detection ────────────────────────────────
        # A king moves exactly 2 squares horizontally
        is_castle = False
        rook_from = -1
        rook_to = -1
        if (abs(piece) == 6 and 
                abs(chess.square_file(from_sq) - chess.square_file(to_sq)) == 2):
            is_castle = True
            rank = chess.square_rank(from_sq)
            if chess.square_file(to_sq) == 6:  # King-side
                rook_from = chess.square(7, rank)  # h-file
                rook_to = chess.square(5, rank)    # f-file
            else:                                # Queen-side
                rook_from = chess.square(0, rank)  # a-file
                rook_to = chess.square(3, rank)    # d-file
            changes.append((rook_from, self._board_arr[rook_from]))
            changes.append((rook_to, self._board_arr[rook_to]))
            
        self._state_stack.append(changes)
        
        # ── Apply changes to the board array ──────────────────
        # 1. Main piece movement / promotion
        if move.promotion:
            # python-chess uses 2=Knight, 3=Bishop, 4=Rook, 5=Queen
            # Which perfectly matches our internal array mapping!
            sign = 1 if piece > 0 else -1
            self._board_arr[to_sq] = sign * move.promotion
        else:
            self._board_arr[to_sq] = piece
            
        self._board_arr[from_sq] = 0
        
        # 2. En Passant removal
        if is_ep:
            self._board_arr[ep_captured_sq] = 0
            
        # 3. Castling Rook movement
        if is_castle:
            self._board_arr[rook_to] = self._board_arr[rook_from]
            self._board_arr[rook_from] = 0

    def _update_arr_pop(self, board, move):
        """Restore board_arr in O(1) after board.pop()."""
        # Simply reverse the exact squares that were modified
        changes = self._state_stack.pop()
        for sq, val in changes:
            self._board_arr[sq] = val


# ── Quick helpers for quiescence ──────────────────────────────
_PVAL = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
         chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 20000}

def _piece_val_fast(pt):
    return _PVAL.get(pt, 0)

def _mvv_lva_q(board, move):
    victim   = board.piece_at(move.to_square)
    attacker = board.piece_at(move.from_square)
    vv = _PVAL.get(victim.piece_type, 0)   if victim   else 0
    av = _PVAL.get(attacker.piece_type, 0)  if attacker else 0
    return vv * 10 - av


# ════════════════════════════════════════════════════════════════════
#  MCTS (Monte Carlo Tree Search) — Enhanced with fast evaluator
# ════════════════════════════════════════════════════════════════════

class MCTSNode:
    __slots__ = ('board', 'parent', 'move', 'children',
                 'wins', 'visits', 'untried')

    def __init__(self, board, parent=None, move=None):
        self.board    = board
        self.parent   = parent
        self.move     = move
        self.children = []
        self.wins     = 0.0
        self.visits   = 0
        self.untried  = list(board.legal_moves)

    def ucb1(self, c=1.414):
        if self.visits == 0:
            return float("inf")
        return (self.wins / self.visits) + c * math.sqrt(
            math.log(self.parent.visits) / self.visits)

    def best_child(self):
        return max(self.children, key=lambda x: x.ucb1())

    def expand(self):
        move = self.untried.pop()
        nb = self.board.copy()
        nb.push(move)
        child = MCTSNode(nb, self, move)
        self.children.append(child)
        return child


class MCTSEngine:
    def __init__(self):
        pass

    def search(self, board, iterations):
        root = MCTSNode(board)
        for _ in range(iterations):
            node = root
            # Selection
            while not node.untried and node.children:
                node = node.best_child()
            # Expansion
            if node.untried:
                node = node.expand()
            # Rollout + evaluation
            score = self._rollout(node.board)
            # Backpropagation
            while node:
                node.visits += 1
                node.wins += score if node.board.turn != board.turn else (1 - score)
                node = node.parent

        best_move = (max(root.children, key=lambda c: c.visits).move
                     if root.children else None)
        policy = {}
        if root.children:
            tv = sum(c.visits for c in root.children)
            policy = {c.move.uci(): c.visits / tv if tv else 0
                      for c in root.children}

        # Fast evaluation for return value
        board_arr = board_to_array(board)
        ev = evaluate_numba(board_arr)
        return best_move, ev, root.visits, policy

    def _rollout(self, board, depth=12):
        """Semi-random rollout with fast Numba evaluation at leaves."""
        if board.is_checkmate():
            return 0.0 if board.turn == chess.WHITE else 1.0
        if board.is_stalemate():
            return 0.5
        if depth == 0:
            board_arr = board_to_array(board)
            ev = evaluate_numba(board_arr)
            return 1.0 / (1.0 + math.exp(-0.004 * ev))

        # Prefer captures & checks for more realistic rollouts
        moves = list(board.legal_moves)
        captures = [m for m in moves if board.is_capture(m)]
        if captures and random.random() < 0.7:
            move = random.choice(captures)
        else:
            move = random.choice(moves)

        board.push(move)
        score = self._rollout(board, depth - 1)
        board.pop()
        return score


# ════════════════════════════════════════════════════════════════════
#  Synchronous UCI (Stockfish) Wrapper — Unchanged
# ════════════════════════════════════════════════════════════════════

class SyncUCI:
    def __init__(self, path):
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"Stockfish not found: {path}")
        try:
            self.proc = subprocess.Popen(
                [path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1,
            )
        except OSError as e:
            raise RuntimeError(f"Failed to launch Stockfish: {e}")
        self._cmd("uci")
        self._read("uciok")

    def _cmd(self, t):
        try:
            self.proc.stdin.write(t + "\n")
            self.proc.stdin.flush()
        except BrokenPipeError:
            raise RuntimeError("Broken pipe writing to Stockfish")

    def _read(self, tok):
        lines = []
        deadline = time.time() + 30
        while True:
            if time.time() > deadline:
                break
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            lines.append(line)
            if tok in line:
                break
        return lines

    def analyse(self, fen, depth=18):
        board = chess.Board(fen)
        if not board.legal_moves:
            return None, 0
        self._cmd(f"position fen {fen}")
        self._cmd(f"go depth {depth}")
        bm, sc, wt = None, 0, board.turn == chess.WHITE
        for line in self._read("bestmove"):
            if line.startswith("info") and " score " in line:
                parts = line.split()
                if "cp" in parts:
                    idx = parts.index("cp")
                    sc = int(parts[idx + 1]) if wt else -int(parts[idx + 1])
                elif "mate" in parts:
                    idx = parts.index("mate")
                    mi = int(parts[idx + 1])
                    sc = (10000 if mi > 0 else -10000) if wt else (-10000 if mi > 0 else 10000)
            if line.startswith("bestmove"):
                parts = line.split()
                bm = parts[1] if len(parts) >= 2 else None
        return bm, sc

    def close(self):
        try:
            self._cmd("quit")
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass