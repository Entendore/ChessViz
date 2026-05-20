"""Chess Video Maker Pro — AI Engines (Heuristic Evaluator, Minimax, MCTS)"""

import math
import random
import chess


class HeuristicEvaluator:
    """Evaluates board strictly from White's perspective in centipawns."""

    PIECE_VALUES = {
        chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
        chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 20000,
    }

    PAWN_TABLE = [
         0,  0,  0,  0,  0,  0,  0,  0,
         5, 10, 10,-20,-20, 10, 10,  5,
         5, -5,-10,  0,  0,-10, -5,  5,
         0,  0,  0, 20, 20,  0,  0,  0,
         5,  5, 10, 25, 25, 10,  5,  5,
        10, -5,  0, 10, 10,  0, -5, 10,
       -15,-15,-20, -5, -5,-20,-15,-15,
         0,  0,  0,  0,  0,  0,  0,  0,
    ]

    def evaluate(self, board):
        if board.is_checkmate():
            return -99999 if board.turn == chess.WHITE else 99999
        if board.is_stalemate() or board.is_insufficient_material():
            return 0
        score = 0
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece:
                value = self.PIECE_VALUES[piece.piece_type]
                if piece.piece_type == chess.PAWN:
                    idx = sq if piece.color == chess.WHITE else chess.square_mirror(sq)
                    value += self.PAWN_TABLE[idx]
                score += value if piece.color == chess.WHITE else -value
        return score


class MinimaxEngine:
    """Alpha-Beta pruning Minimax chess engine."""

    def __init__(self):
        self.evaluator = HeuristicEvaluator()
        self.nodes_searched = 0

    def search(self, board, depth):
        self.nodes_searched = 0
        best_move = None
        alpha = -float('inf')
        beta = float('inf')
        best_eval = -float('inf')
        policy = {}

        for move in board.legal_moves:
            board.push(move)
            eval_score = -self._negamax(board, depth - 1, -beta, -alpha)
            board.pop()
            policy[move.uci()] = eval_score
            if eval_score > best_eval:
                best_eval = eval_score
                best_move = move
            alpha = max(alpha, eval_score)

        if policy:
            min_p = min(policy.values())
            max_p = max(policy.values())
            rng = max_p - min_p if max_p != min_p else 1
            policy = {k: (v - min_p) / rng for k, v in policy.items()}

        white_eval = best_eval if board.turn == chess.WHITE else -best_eval
        return best_move, white_eval, self.nodes_searched, policy

    def _negamax(self, board, depth, alpha, beta):
        self.nodes_searched += 1
        if depth == 0 or board.is_game_over():
            eval_w = self.evaluator.evaluate(board)
            return eval_w if board.turn == chess.WHITE else -eval_w

        for move in board.legal_moves:
            board.push(move)
            eval_score = -self._negamax(board, depth - 1, -beta, -alpha)
            board.pop()
            if eval_score >= beta:
                return beta
            if eval_score > alpha:
                alpha = eval_score
        return alpha


class MCTSNode:
    """Monte Carlo Tree Search node."""

    def __init__(self, board, parent=None, move=None):
        self.board = board
        self.parent = parent
        self.move = move
        self.children = []
        self.wins = 0.0
        self.visits = 0
        self.untried_moves = list(board.legal_moves)

    def ucb1(self, c=1.414):
        if self.visits == 0:
            return float('inf')
        return (self.wins / self.visits) + c * math.sqrt(math.log(self.parent.visits) / self.visits)

    def best_child(self):
        return max(self.children, key=lambda child: child.ucb1())

    def expand(self):
        move = self.untried_moves.pop()
        next_board = self.board.copy()
        next_board.push(move)
        child = MCTSNode(next_board, parent=self, move=move)
        self.children.append(child)
        return child


class MCTSEngine:
    """Monte Carlo Tree Search chess engine with heuristic rollouts."""

    def __init__(self):
        self.evaluator = HeuristicEvaluator()

    def search(self, board, iterations):
        root = MCTSNode(board)
        for _ in range(iterations):
            node = root
            while not node.untried_moves and node.children:
                node = node.best_child()
            if node.untried_moves:
                node = node.expand()
            score = self._heuristic_rollout(node.board)
            while node is not None:
                node.visits += 1
                node.wins += score if node.board.turn != board.turn else (1 - score)
                node = node.parent

        best_move = max(root.children, key=lambda c: c.visits).move if root.children else None
        policy = {}
        if root.children:
            total_visits = sum(c.visits for c in root.children)
            for child in root.children:
                policy[child.move.uci()] = child.visits / total_visits if total_visits > 0 else 0

        white_eval = self.evaluator.evaluate(board)
        return best_move, white_eval, root.visits, policy

    def _heuristic_rollout(self, board, depth=10):
        if board.is_checkmate():
            return 0.0 if board.turn == chess.WHITE else 1.0
        if board.is_stalemate():
            return 0.5
        if depth == 0:
            return 1.0 / (1.0 + math.exp(-0.004 * self.evaluator.evaluate(board)))
        move = random.choice(list(board.legal_moves))
        board.push(move)
        score = self._heuristic_rollout(board, depth - 1)
        board.pop()
        return score