"""Chess engine — Wrapper around python-chess for robust board logic and validation."""

import chess
from constants import log, FILES_STR, RANKS_STR


class ChessEngine:
    def __init__(self):
        self.board = chess.Board()
        self.game_over = False
        self.result = ""
        self.last_move = None

    def reset(self):
        self.board.reset()
        self.game_over = False
        self.result = ""
        self.last_move = None

    # ── Coordinate Helpers ────────────────────────────────────────────────────
    @staticmethod
    def sq_to_rc(sq):
        return 7 - chess.square_rank(sq), chess.square_file(sq)

    @staticmethod
    def rc_to_sq(r, c):
        return chess.square(c, 7 - r)

    # ── State Checks ──────────────────────────────────────────────────────────
    @property
    def turn(self):
        return 'w' if self.board.turn == chess.WHITE else 'b'

    def color_of(self, piece):
        return 'w' if piece.color == chess.WHITE else 'b'

    def check_squares(self):
        if self.board.is_check():
            return [self.sq_to_rc(self.board.king(self.board.turn))]
        return []

    # ── Move Generation ───────────────────────────────────────────────────────
    def legal_moves(self, r, c):
        sq = self.rc_to_sq(r, c)
        return [self.sq_to_rc(m.to_square) for m in self.board.legal_moves if m.from_square == sq]

    # ── Make / Undo ───────────────────────────────────────────────────────────
    def make_move(self, fr, fc, tr, tc, promo=None):
        from_sq = self.rc_to_sq(fr, fc)
        to_sq = self.rc_to_sq(tr, tc)
        piece = self.board.piece_at(from_sq)
        if not piece:
            return None

        promotion = None
        if piece.piece_type == chess.PAWN:
            if (piece.color == chess.WHITE and tr == 0) or (piece.color == chess.BLACK and tr == 7):
                promotion = chess.PIECE_SYMBOLS.index(promo.lower()) if promo else chess.QUEEN

        move = chess.Move(from_sq, to_sq, promotion=promotion)
        if move not in self.board.legal_moves:
            return None

        cap = self.board.piece_at(to_sq)
        captured = cap.symbol() if cap else '.'
        is_castle = self.board.is_castling(move)
        is_ep = self.board.is_en_passant(move)

        notation = self.board.san(move)

        piece_obj = chess.Piece(piece.piece_type, piece.color)

        self.board.push(move)
        self.last_move = ((fr, fc), (tr, tc))

        self.game_over = self.board.is_game_over()
        self.result = self.board.result() if self.game_over else ""

        info = {
            'from': (fr, fc), 'to': (tr, tc),
            'piece': piece.symbol(),
            'piece_obj': piece_obj,
            'captured': captured,
            'castle': is_castle, 'ep': is_ep, 'promo': promo,
            'check': self.board.is_check(), 'mate': self.board.is_checkmate(),
            'notation': notation
        }
        return info

    def make_move_uci(self, uci_str):
        move = chess.Move.from_uci(uci_str)
        if move in self.board.legal_moves:
            fr, fc = self.sq_to_rc(move.from_square)
            tr, tc = self.sq_to_rc(move.to_square)
            promo = chess.piece_symbol(move.promotion) if move.promotion else None
            return self.make_move(fr, fc, tr, tc, promo)
        return None

    def undo(self):
        if len(self.board.move_stack) > 0:
            self.board.pop()
            self.game_over = self.board.is_game_over()
            self.result = self.board.result() if self.game_over else ""
            if self.board.move_stack:
                last = self.board.peek()
                self.last_move = (self.sq_to_rc(last.from_square), self.sq_to_rc(last.to_square))
            else:
                self.last_move = None
            return True
        return False

    # ── FEN ───────────────────────────────────────────────────────────────────
    def load_fen(self, fen):
        self.board.set_fen(fen)
        self.game_over = self.board.is_game_over()
        self.result = self.board.result() if self.game_over else ""
        self.last_move = None