"""Chess engine — board state, move generation, validation, AI, and FEN handling."""

from constants import log, PIECE_VAL, PST, FILES_STR, RANKS_STR


class ChessEngine:
    def __init__(self):
        self.reset()

    # ── Reset / helpers ───────────────────────────────────────────────────────
    def reset(self):
        self.board = [
            ['r', 'n', 'b', 'q', 'k', 'b', 'n', 'r'],
            ['p', 'p', 'p', 'p', 'p', 'p', 'p', 'p'],
            ['.', '.', '.', '.', '.', '.', '.', '.'],
            ['.', '.', '.', '.', '.', '.', '.', '.'],
            ['.', '.', '.', '.', '.', '.', '.', '.'],
            ['.', '.', '.', '.', '.', '.', '.', '.'],
            ['P', 'P', 'P', 'P', 'P', 'P', 'P', 'P'],
            ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R'],
        ]
        self.turn = 'w'
        self.castling = {'K': True, 'Q': True, 'k': True, 'q': True}
        self.ep = None
        self.history = []
        self.game_over = False
        self.result = ""
        self.last_move = None
        log("ChessEngine reset to starting position", "ENGINE")

    @staticmethod
    def is_white(p):
        return p != '.' and p.isupper()

    @staticmethod
    def is_black(p):
        return p != '.' and p.islower()

    @staticmethod
    def color_of(p):
        return 'w' if p.isupper() else ('b' if p != '.' else None)

    def copy_board(self):
        return [r[:] for r in self.board]

    def find_king(self, color):
        k = 'K' if color == 'w' else 'k'
        for r in range(8):
            for c in range(8):
                if self.board[r][c] == k:
                    return (r, c)
        return None

    # ── Attack detection ──────────────────────────────────────────────────────
    def attacked(self, row, col, by):
        # Knights
        kn = 'N' if by == 'w' else 'n'
        for dr, dc in [(-2, -1), (-2, 1), (-1, -2), (-1, 2),
                        (1, -2), (1, 2), (2, -1), (2, 1)]:
            r2, c2 = row + dr, col + dc
            if 0 <= r2 < 8 and 0 <= c2 < 8 and self.board[r2][c2] == kn:
                return True
        # King
        ki = 'K' if by == 'w' else 'k'
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                r2, c2 = row + dr, col + dc
                if 0 <= r2 < 8 and 0 <= c2 < 8 and self.board[r2][c2] == ki:
                    return True
        # Pawns
        pw = 'P' if by == 'w' else 'p'
        pd = 1 if by == 'w' else -1
        r2 = row + pd
        if 0 <= r2 < 8:
            for dc2 in (-1, 1):
                c2 = col + dc2
                if 0 <= c2 < 8 and self.board[r2][c2] == pw:
                    return True
        # Rooks / Queens (straight)
        rk = 'R' if by == 'w' else 'r'
        qu = 'Q' if by == 'w' else 'q'
        for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            r2, c2 = row + dr, col + dc
            while 0 <= r2 < 8 and 0 <= c2 < 8:
                p = self.board[r2][c2]
                if p != '.':
                    if p in (rk, qu):
                        return True
                    break
                r2 += dr; c2 += dc
        # Bishops / Queens (diagonal)
        bi = 'B' if by == 'w' else 'b'
        for dr, dc in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
            r2, c2 = row + dr, col + dc
            while 0 <= r2 < 8 and 0 <= c2 < 8:
                p = self.board[r2][c2]
                if p != '.':
                    if p in (bi, qu):
                        return True
                    break
                r2 += dr; c2 += dc
        return False

    def in_check(self, color):
        kp = self.find_king(color)
        return self.attacked(kp[0], kp[1], 'b' if color == 'w' else 'w') if kp else True

    # ── Move generation ───────────────────────────────────────────────────────
    def pseudo_moves(self, r, c):
        p = self.board[r][c]
        if p == '.':
            return []
        co = self.color_of(p)
        pt = p.upper()
        mv = []

        if pt == 'P':
            d = -1 if co == 'w' else 1
            sr = 6 if co == 'w' else 1
            nr = r + d
            if 0 <= nr < 8 and self.board[nr][c] == '.':
                mv.append((nr, c))
                nr2 = r + 2 * d
                if r == sr and self.board[nr2][c] == '.':
                    mv.append((nr2, c))
            for dc in (-1, 1):
                nc = c + dc; nr2 = r + d
                if 0 <= nr2 < 8 and 0 <= nc < 8:
                    t = self.board[nr2][nc]
                    if (t != '.' and self.color_of(t) != co) or (self.ep and (nr2, nc) == self.ep):
                        mv.append((nr2, nc))

        elif pt == 'N':
            for dr, dc in [(-2, -1), (-2, 1), (-1, -2), (-1, 2),
                            (1, -2), (1, 2), (2, -1), (2, 1)]:
                r2, c2 = r + dr, c + dc
                if 0 <= r2 < 8 and 0 <= c2 < 8:
                    t = self.board[r2][c2]
                    if t == '.' or self.color_of(t) != co:
                        mv.append((r2, c2))

        elif pt in ('B', 'R', 'Q'):
            dirs = []
            if pt in ('B', 'Q'):
                dirs += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
            if pt in ('R', 'Q'):
                dirs += [(0, 1), (0, -1), (1, 0), (-1, 0)]
            for dr, dc in dirs:
                r2, c2 = r + dr, c + dc
                while 0 <= r2 < 8 and 0 <= c2 < 8:
                    t = self.board[r2][c2]
                    if t == '.':
                        mv.append((r2, c2))
                    elif self.color_of(t) != co:
                        mv.append((r2, c2)); break
                    else:
                        break
                    r2 += dr; c2 += dc

        elif pt == 'K':
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    r2, c2 = r + dr, c + dc
                    if 0 <= r2 < 8 and 0 <= c2 < 8:
                        t = self.board[r2][c2]
                        if t == '.' or self.color_of(t) != co:
                            mv.append((r2, c2))
            enemy = 'b' if co == 'w' else 'w'
            if co == 'w' and r == 7 and c == 4:
                if (self.castling['K'] and self.board[7][5] == '.'
                        and self.board[7][6] == '.' and self.board[7][7] == 'R'):
                    if (not self.attacked(7, 4, enemy)
                            and not self.attacked(7, 5, enemy)
                            and not self.attacked(7, 6, enemy)):
                        mv.append((7, 6))
                if (self.castling['Q'] and self.board[7][3] == '.'
                        and self.board[7][2] == '.' and self.board[7][1] == '.'
                        and self.board[7][0] == 'R'):
                    if (not self.attacked(7, 4, enemy)
                            and not self.attacked(7, 3, enemy)
                            and not self.attacked(7, 2, enemy)):
                        mv.append((7, 2))
            elif co == 'b' and r == 0 and c == 4:
                if (self.castling['k'] and self.board[0][5] == '.'
                        and self.board[0][6] == '.' and self.board[0][7] == 'r'):
                    if (not self.attacked(0, 4, enemy)
                            and not self.attacked(0, 5, enemy)
                            and not self.attacked(0, 6, enemy)):
                        mv.append((0, 6))
                if (self.castling['q'] and self.board[0][3] == '.'
                        and self.board[0][2] == '.' and self.board[0][1] == '.'
                        and self.board[0][0] == 'r'):
                    if (not self.attacked(0, 4, enemy)
                            and not self.attacked(0, 3, enemy)
                            and not self.attacked(0, 2, enemy)):
                        mv.append((0, 2))
        return mv

    def legal_moves(self, r, c):
        p = self.board[r][c]
        if p == '.' or self.color_of(p) != self.turn:
            return []
        co = self.color_of(p)
        out = []
        for tr, tc in self.pseudo_moves(r, c):
            sb = self.copy_board()
            sep = self.ep
            sc = dict(self.castling)
            self.board[tr][tc] = p; self.board[r][c] = '.'
            if p.upper() == 'P' and self.ep and (tr, tc) == self.ep:
                self.board[r][tc] = '.'
            if p.upper() == 'K' and abs(tc - c) == 2:
                if tc == 6:
                    self.board[r][5] = self.board[r][7]; self.board[r][7] = '.'
                elif tc == 2:
                    self.board[r][3] = self.board[r][0]; self.board[r][0] = '.'
            chk = self.in_check(co)
            self.board = sb; self.ep = sep; self.castling = sc
            if not chk:
                out.append((tr, tc))
        return out

    def all_legal_moves(self, color=None):
        if color is None:
            color = self.turn
        out = []
        for r in range(8):
            for c in range(8):
                if self.color_of(self.board[r][c]) == color:
                    for m in self.legal_moves(r, c):
                        out.append(((r, c), m))
        return out

    # ── Make / undo moves ─────────────────────────────────────────────────────
    def make_move(self, fr, fc, tr, tc, promo=None):
        p = self.board[fr][fc]
        if p == '.':
            return None
        co = self.color_of(p)
        cap = self.board[tr][tc]
        info = {
            'from': (fr, fc), 'to': (tr, tc), 'piece': p, 'captured': cap,
            'castle': False, 'ep': False, 'promo': None,
            'check': False, 'mate': False, 'notation': '',
        }
        self.history.append({
            'board': self.copy_board(), 'turn': self.turn,
            'castling': dict(self.castling), 'ep': self.ep,
            'last_move': self.last_move,
            'game_over': self.game_over, 'result': self.result,
        })

        # En passant capture
        if p.upper() == 'P' and self.ep and (tr, tc) == self.ep:
            info['ep'] = True
            info['captured'] = self.board[fr][tc]
            self.board[fr][tc] = '.'

        self.ep = None
        if p.upper() == 'P' and abs(tr - fr) == 2:
            self.ep = ((fr + tr) // 2, fc)

        # Castling rook move
        if p.upper() == 'K' and abs(tc - fc) == 2:
            info['castle'] = True
            if tc == 6:
                self.board[fr][5] = self.board[fr][7]; self.board[fr][7] = '.'
            elif tc == 2:
                self.board[fr][3] = self.board[fr][0]; self.board[fr][0] = '.'

        self.board[tr][tc] = p; self.board[fr][fc] = '.'

        # Promotion
        prow = 0 if co == 'w' else 7
        if p.upper() == 'P' and tr == prow:
            pp = promo or ('Q' if co == 'w' else 'q')
            self.board[tr][tc] = pp; info['promo'] = pp

        # Update castling rights
        if (fr, fc) == (7, 4):
            self.castling['K'] = False; self.castling['Q'] = False
        if (fr, fc) == (0, 4):
            self.castling['k'] = False; self.castling['q'] = False
        for pos, key in [((7, 7), 'K'), ((7, 0), 'Q'), ((0, 7), 'k'), ((0, 0), 'q')]:
            if (fr, fc) == pos or (tr, tc) == pos:
                self.castling[key] = False

        self.last_move = ((fr, fc), (tr, tc))
        self.turn = 'b' if self.turn == 'w' else 'w'

        if self.in_check(self.turn):
            info['check'] = True
            if not self.all_legal_moves(self.turn):
                info['mate'] = True; self.game_over = True
                self.result = "White wins!" if self.turn == 'b' else "Black wins!"
        elif not self.all_legal_moves(self.turn):
            self.game_over = True; self.result = "Stalemate — Draw"

        info['notation'] = self._nota(info)
        log(f"Move: {info['notation']}  piece={info['piece']}  from={info['from']}  "
            f"to={info['to']}  capture={info['captured']}  castle={info['castle']}  "
            f"ep={info['ep']}  promo={info['promo']}  check={info['check']}  "
            f"mate={info['mate']}", "ENGINE")
        return info

    def undo(self):
        if not self.history:
            return False
        s = self.history.pop()
        self.board = s['board']; self.turn = s['turn']
        self.castling = s['castling']; self.ep = s['ep']
        self.last_move = s['last_move']
        self.game_over = s['game_over']; self.result = s['result']
        log("Move undone", "ENGINE")
        return True

    def _nota(self, info):
        if info['castle']:
            n = "O-O" if info['to'][1] == 6 else "O-O-O"
        else:
            pt = info['piece'].upper()
            fr, fc = info['from']; tr, tc = info['to']
            n = "" if pt == 'P' else pt
            if info['captured'] != '.':
                if pt == 'P':
                    n += FILES_STR[fc]
                n += 'x'
            n += FILES_STR[tc] + RANKS_STR[tr]
            if info['promo']:
                n += '=' + info['promo'].upper()
        if info['mate']:
            n += '#'
        elif info['check']:
            n += '+'
        return n

    # ── FEN ───────────────────────────────────────────────────────────────────
    def load_fen(self, fen):
        parts = fen.split()
        rows = parts[0].split('/')
        self.board = []
        for row_str in rows:
            row = []
            for ch in row_str:
                if ch.isdigit():
                    row.extend(['.'] * int(ch))
                else:
                    row.append(ch)
            self.board.append(row)
        self.turn = 'w' if parts[1] == 'w' else 'b'
        self.castling = {
            'K': 'K' in parts[2], 'Q': 'Q' in parts[2],
            'k': 'k' in parts[2], 'q': 'q' in parts[2],
        }
        self.ep = None
        if len(parts) > 3 and parts[3] != '-':
            c = ord(parts[3][0]) - ord('a')
            r = 8 - int(parts[3][1])
            self.ep = (r, c)
        self.history = []; self.game_over = False
        self.result = ""; self.last_move = None
        log(f"FEN loaded: {fen}", "ENGINE")

    def parse_uci(self, uci_str):
        """Parse a UCI move string like 'e2e4' into ((fr,fc),(tr,tc)), promo."""
        if not uci_str or len(uci_str) < 4:
            return None, None
        fc = ord(uci_str[0]) - ord('a')
        fr = 8 - int(uci_str[1])
        tc = ord(uci_str[2]) - ord('a')
        tr = 8 - int(uci_str[3])
        promo = uci_str[4] if len(uci_str) == 5 else None
        return ((fr, fc), (tr, tc)), promo

    # ── Evaluation ────────────────────────────────────────────────────────────
    def evaluate(self):
        s = 0
        for r in range(8):
            for c in range(8):
                p = self.board[r][c]
                if p == '.':
                    continue
                pt = p.upper()
                v = PIECE_VAL.get(pt, 0)
                t = PST.get(pt)
                if p.isupper():
                    s += v + (t[r][c] if t else 0)
                else:
                    s -= v + (t[7 - r][c] if t else 0)
        return s

    # ── AI (minimax + alpha-beta) ─────────────────────────────────────────────
    def minimax(self, depth, alpha, beta, maximizing):
        if depth == 0:
            return self.evaluate()
        co = 'w' if maximizing else 'b'
        moves = self.all_legal_moves(co)
        if not moves:
            if self.in_check(co):
                return -99999 if maximizing else 99999
            return 0
        if maximizing:
            val = -999999
            for (fr, fc), (tr, tc) in moves:
                sb, st, sc, se, slm = self._snapshot()
                self._apply_raw(fr, fc, tr, tc, se)
                val = max(val, self.minimax(depth - 1, alpha, beta, False))
                self._restore(sb, st, sc, se, slm)
                alpha = max(alpha, val)
                if beta <= alpha:
                    break
            return val
        else:
            val = 999999
            for (fr, fc), (tr, tc) in moves:
                sb, st, sc, se, slm = self._snapshot()
                self._apply_raw(fr, fc, tr, tc, se)
                val = min(val, self.minimax(depth - 1, alpha, beta, True))
                self._restore(sb, st, sc, se, slm)
                beta = min(beta, val)
                if beta <= alpha:
                    break
            return val

    def _snapshot(self):
        return (self.copy_board(), self.turn,
                dict(self.castling), self.ep, self.last_move)

    def _apply_raw(self, fr, fc, tr, tc, ep):
        p = self.board[fr][fc]
        self.board[tr][tc] = p; self.board[fr][fc] = '.'
        if p.upper() == 'P' and ep and (tr, tc) == ep:
            self.board[fr][tc] = '.'
        if p.upper() == 'K' and abs(tc - fc) == 2:
            if tc == 6:
                self.board[fr][5] = self.board[fr][7]; self.board[fr][7] = '.'
            elif tc == 2:
                self.board[fr][3] = self.board[fr][0]; self.board[fr][0] = '.'
        self.turn = 'b' if self.turn == 'w' else 'w'
        self.last_move = ((fr, fc), (tr, tc))

    def _restore(self, sb, st, sc, se, slm):
        self.board = sb; self.turn = st
        self.castling = sc; self.ep = se; self.last_move = slm

    def get_ai_move(self, depth=2):
        moves = self.all_legal_moves()
        if not moves:
            return None
        log(f"AI computing move (depth={depth}, {len(moves)} legal moves)...", "AI")
        best = None
        if self.turn == 'w':
            mx = -999999
            for (fr, fc), (tr, tc) in moves:
                sb, st, sc, se, slm = self._snapshot()
                self._apply_raw(fr, fc, tr, tc, se)
                ev = self.minimax(depth - 1, -999999, 999999, False)
                self._restore(sb, st, sc, se, slm)
                if ev > mx:
                    mx = ev; best = ((fr, fc), (tr, tc))
        else:
            mn = 999999
            for (fr, fc), (tr, tc) in moves:
                sb, st, sc, se, slm = self._snapshot()
                self._apply_raw(fr, fc, tr, tc, se)
                ev = self.minimax(depth - 1, -999999, 999999, True)
                self._restore(sb, st, sc, se, slm)
                if ev < mn:
                    mn = ev; best = ((fr, fc), (tr, tc))
        if best:
            (fr, fc), (tr, tc) = best
            log(f"AI chosen move: {FILES_STR[fc]}{RANKS_STR[fr]}{FILES_STR[tc]}{RANKS_STR[tr]}", "AI")
        else:
            log("AI: no move found", "AI")
        return best