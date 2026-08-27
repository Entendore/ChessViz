"""
Move quality classification: Brilliant, Great, Best, Good,
Inaccuracy, Mistake, Blunder.

Tightened thresholds so badges are RARE and MEANINGFUL.
Most moves will classify as Good or Best with no badge.
Only genuinely exceptional or terrible moves get visible badges.
"""

import chess
from constants import (
    MQ_BRILLIANT, MQ_GREAT, MQ_BEST, MQ_GOOD,
    MQ_INACCURACY, MQ_MISTAKE, MQ_BLUNDER, MQ_BOOK,
    PIECE_VALUES,
)


def classify_move(eval_before, eval_after, is_white_move,
                  board=None, move=None, move_number=0):
    """
    Classify a move by evaluation swing.

    Thresholds are intentionally tight so that:
      - "Good" and "Best" (no badge) cover ~80%+ of moves
      - Badges only appear for genuinely notable moves
      - Brilliant/Blunder are VERY rare and dramatic
    """
    if move_number <= 2:
        return MQ_BOOK

    if is_white_move:
        delta = eval_after - eval_before
    else:
        delta = eval_before - eval_after

    def _clamp(cp):
        return max(-3000, min(3000, cp))

    delta = _clamp(delta)

    # ── Blunder: game-changing error (VERY strict) ────────────
    if delta <= -200:
        abs_before = abs(eval_before)
        if abs_before < 5000:
            return MQ_BLUNDER

    # ── Mistake: notable error ────────────────────────────────
    if delta <= -100:
        return MQ_MISTAKE

    # ── Inaccuracy: small error (NO badge, just subtle) ──────
    if delta <= -50:
        return MQ_INACCURACY

    # ── Brilliant: sacrifice + big gain (EXTREMELY rare) ──────
    is_sacrifice = _detect_sacrifice(board, move) if (board and move) else False
    if delta >= 150 and is_sacrifice:
        return MQ_BRILLIANT

    # ── Great: significantly better than alternatives (rare) ──
    if delta >= 80:
        return MQ_GREAT

    # ── Best: essentially the top engine choice (no badge) ────
    if delta >= -15:
        return MQ_BEST

    # ── Good: reasonable move (no badge) ──────────────────────
    return MQ_GOOD


def _detect_sacrifice(board, move):
    """Heuristic: did the moving piece go to a square attacked by a
    lower-value enemy piece? Stricter — requires a REAL material sacrifice."""
    if not move or not board:
        return False
    piece = board.piece_at(move.from_square)
    if not piece:
        return False
    piece_val = PIECE_VALUES.get(piece.piece_type, 0)
    if piece_val <= 1:
        return False

    captured = board.piece_at(move.to_square)
    if captured:
        cap_val = PIECE_VALUES.get(captured.piece_type, 0)
        if cap_val >= piece_val:
            return False

    attackers = board.attackers(not piece.color, move.to_square)
    for atk_sq in attackers:
        atk = board.piece_at(atk_sq)
        if atk and PIECE_VALUES.get(atk.piece_type, 0) < piece_val:
            return True
    return False


class MoveAnalyzer:
    """Accumulates eval history and classifies every move."""

    def __init__(self):
        self._evals: list[float] = []
        self._qualities: list[str] = []
        self._move_number = 0

    def reset(self):
        self._evals.clear()
        self._qualities.clear()
        self._move_number = 0

    def push(self, eval_cp: float, is_white: bool,
             board=None, move=None):
        self._move_number += 1
        prev = self._evals[-1] if self._evals else 0.0
        q = classify_move(prev, eval_cp, is_white, board, move, self._move_number)
        self._evals.append(eval_cp)
        self._qualities.append(q)
        return q

    @property
    def evals(self) -> list[float]:
        return list(self._evals)

    @property
    def qualities(self) -> list[str]:
        return list(self._qualities)

    @property
    def last_quality(self) -> str:
        return self._qualities[-1] if self._qualities else MQ_GOOD