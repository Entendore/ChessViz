#!/usr/bin/env python3
"""Puzzle parsing, move conversion, and Numba/CuPy batch helpers."""

import re
import csv
import chess
import numpy as np

from utils import log, HAS_NUMBA, HAS_CUPY, HAS_PANDAS, compute_difficulty

csv.field_size_limit(2**31 - 1)

# ── Regex patterns ──────────────────────────────────────────────────────────

_UCI_RE = re.compile(r'^[a-h][1-8][a-h][1-8][qrbn]?$')
_MVNUM_RE = re.compile(r'^\d+\.+$')
_RESULT_RE = frozenset({'1-0', '0-1', '1/2-1/2', '*'})

# ── Lichess column mappings ────────────────────────────────────────────────

LICHESS_COL_MAP = {
    'puzzleid': 'id',
    'fen': 'fen',
    'moves': 'moves',
    'rating': 'rating',
    'ratingdeviation': 'rating_deviation',
    'popularity': 'popularity',
    'nbplays': 'nb_plays',
    'themes': 'themes',
    'gameurl': 'game_url',
    'openingtags': 'opening',
}

LICHESS_THEME_LIST = sorted({
    'advancedPawn', 'advantage', 'anastasiaMate', 'arabianMate', 'attackingF2F7',
    'attraction', 'backRankMate', 'bishopEndgame', 'bodenMate', 'castling',
    'capture', 'clearance', 'coercion', 'cooksMate', 'crushing', 'defensiveMove',
    'deflection', 'discoveredAttack', 'doubleAttack', 'doubleCheck', 'dovetailMate',
    'endgame', 'enPassant', 'equality', 'exposedKing', 'fork', 'hangingPiece',
    'hookMate', 'interference', 'intermezzo', 'knightEndgame', 'kingsideAttack',
    'long', 'legalMate', 'master', 'masterVsMaster', 'mate', 'mateIn1', 'mateIn2',
    'mateIn3', 'mateIn4', 'mateIn5', 'middlegame', 'miniature', 'oneMove',
    'opening', 'pawnEndgame', 'pin', 'promotion', 'queenEndgame', 'queenRookEndgame',
    'quietMove', 'rookEndgame', 'sacrifice', 'scholarMate', 'short', 'skewer',
    'smotheredMate', 'superGM', 'trappedPiece', 'underPromotion', 'veryLong',
    'xRayAttack', 'zugzwang',
})


# ── Move helpers ────────────────────────────────────────────────────────────

def _clean_move_tokens(tokens):
    """Remove move numbers, result strings, and trailing dots from token list."""
    out = []
    for t in tokens:
        t = t.strip()
        if not t or _MVNUM_RE.match(t) or t in _RESULT_RE:
            continue
        t = t.rstrip('.')
        if not t:
            continue
        out.append(t)
    return out


def _detect_move_format(tokens):
    """Detect whether tokens are UCI or SAN format by inspecting the first few."""
    checked = 0
    for t in tokens:
        if _UCI_RE.match(t):
            return 'uci'
        if re.match(r'^[A-Z]', t) or 'x' in t or t.endswith('#') or t.endswith('+'):
            return 'san'
        checked += 1
        if checked >= 3:
            break
    return 'san' if tokens else 'uci'


def _san_to_uci(tokens, fen=''):
    """Convert a list of SAN move tokens to UCI strings."""
    board = chess.Board(fen) if fen else chess.Board()
    result = []
    for t in tokens:
        try:
            m = board.parse_san(t)
            result.append(m.uci())
            board.push(m)
            continue
        except Exception:
            pass
        try:
            m = chess.Move.from_uci(t)
            if m in board.legal_moves:
                result.append(t)
                board.push(m)
                continue
        except Exception:
            pass
        break
    return result


def _parse_uci_value(val):
    """Parse a moves value that may be a list, string, or other type into a flat list of tokens."""
    if isinstance(val, list):
        flat = []
        for item in val:
            if isinstance(item, str):
                flat.extend(item.replace(',', ' ').split())
            elif item is not None:
                s = str(item).strip().replace(',', ' ')
                if s:
                    flat.extend(s.split())
        return flat
    s = str(val).strip().replace(',', ' ')
    return s.split() if s else []


def _extract_uci_moves(row):
    """Extract UCI moves from a row dict, handling various column names and formats."""
    raw_val = ''
    for col in ('uci', 'moves', 'pgn'):
        v = row.get(col, '')
        if v and str(v).strip():
            raw_val = v
            break
    tokens = _parse_uci_value(raw_val)
    tokens = _clean_move_tokens(tokens)
    if not tokens:
        return []
    fen = str(row.get('fen', row.get('epd', ''))).strip()
    if fen and len(fen.split()) < 6:
        fen += " 0 1"
    fmt = _detect_move_format(tokens)
    if fmt == 'san':
        uci_moves = _san_to_uci(tokens, fen)
        if uci_moves:
            return uci_moves
    return tokens


def _is_lichess_format(columns):
    """Detect if column names match lichess puzzle DB format."""
    lower_cols = {c.lower() for c in columns}
    lichess_signatures = {'puzzleid', 'fen', 'moves', 'rating', 'themes'}
    return len(lichess_signatures & lower_cols) >= 4


def _normalize_lichess_row(row, idx):
    """Normalize a lichess-format row, handling first-move convention."""
    normalized = {}
    for k, v in row.items():
        kl = k.lower()
        mapped = LICHESS_COL_MAP.get(kl, kl)
        normalized[mapped] = v

    # Extract UCI moves
    raw_moves = str(normalized.get('moves', '')).strip()
    uci_moves = raw_moves.split() if raw_moves else []

    # Lichess convention: first move is opponent's setup move
    setup_count = 0
    if uci_moves and _is_lichess_format(row.keys()):
        setup_count = 1

    # Generate name
    name = _generate_name(normalized, uci_moves, idx)

    # Difficulty
    difficulty = _compute_iterative_difficulty(normalized, uci_moves)

    return {
        'name': name,
        'fen': str(normalized.get('fen', '')),
        'moves': uci_moves,
        'desc': str(normalized.get('themes', normalized.get('desc', ''))),
        'difficulty': difficulty,
        'setup_count': setup_count,
        'id': str(normalized.get('id', '')),
        'rating': normalized.get('rating', 0),
        'themes': str(normalized.get('themes', '')),
        'opening': str(normalized.get('opening', '')),
        'popularity': normalized.get('popularity', 0),
        'nb_plays': normalized.get('nb_plays', 0),
    }


# ── Rating / naming helpers ─────────────────────────────────────────────────

def _rating_category(rating):
    try:
        r = float(rating)
    except (ValueError, TypeError):
        return "Unknown"
    if r < 800:  return "Beginner"
    if r < 1200: return "Easy"
    if r < 1600: return "Medium"
    if r < 2000: return "Hard"
    return "Expert"


def _generate_name(row, uci_moves, idx):
    """Generate a human-readable puzzle name from row data."""
    number = idx + 1
    attrs = []
    name = str(row.get('name', '')).strip()
    if name and name.lower() not in ('nan', 'none', ''):
        attrs.append(name)

    opening = str(row.get('opening', row.get('opening_tags',
                  row.get('openingtags', '')))).strip()
    if opening and opening.lower() not in ('nan', 'none', ''):
        attrs.append(opening)

    themes = str(row.get('themes', row.get('theme', ''))).strip()
    if themes and themes.lower() not in ('nan', 'none', ''):
        theme_list = themes.split()
        attrs.append(' '.join(theme_list[:2]))

    for rkey in ('rating', 'elo', 'difficulty', 'score'):
        rval = str(row.get(rkey, '')).strip()
        if rval and rval.lower() not in ('nan', 'none', ''):
            try:
                rv = float(rval)
                attrs.append(f"{_rating_category(rv)} ({int(rv)})")
                break
            except ValueError:
                pass
    if not name:
        white = str(row.get('white', '')).strip()
        black = str(row.get('black', '')).strip()
        if white and black:
            attrs.append(f"{white} vs {black}")
    if not name:
        event = str(row.get('event', '')).strip()
        if event and event.lower() not in ('nan', 'none', ''):
            attrs.append(event)
    eco = str(row.get('eco', '')).strip()
    if eco and eco.lower() not in ('nan', 'none', ''):
        attrs.append(f"ECO {eco}")
    if attrs:
        return f"Puzzle #{number} — {' | '.join(attrs)}"
    return _generate_name_fallback(row, uci_moves, idx)


def _generate_name_fallback(row, uci_moves, idx):
    """Generate a fallback name when no useful metadata is available."""
    number = idx + 1
    ignore = frozenset({
        'fen', 'moves', 'uci', 'pgn', 'id', 'name', 'img',
        'desc', 'description', 'white', 'black', 'event',
        'rating', 'difficulty', 'score', 'elo', 'themes',
        'theme', 'opening', 'opening_tags', 'openingtags', 'eco',
        'rating_deviation', 'popularity', 'nb_plays', 'game_url',
        'opening_variation', 'setup_count'})
    parts = []
    for k, v in row.items():
        val = str(v).strip() if v is not None else ''
        if k not in ignore and val and val.lower() not in ('nan', 'none', ''):
            parts.append(f"{k.title()}: {val}")
            if len(parts) == 2:
                break
    if parts:
        return f"Puzzle #{number} — {' | '.join(parts)}"
    if uci_moves:
        return f"Puzzle #{number} — {uci_moves[0]}…"
    return f"Puzzle #{number}"


# ── Numba-accelerated batch helpers ─────────────────────────────────────────

if HAS_NUMBA:
    from numba import njit as _njit3

    @_njit3(cache=True, nogil=True)
    def _count_moves_nb(data, offsets, lengths):
        n = len(offsets)
        out = np.empty(n, dtype=np.int64)
        space = np.uint8(32)
        for i in range(n):
            ln = lengths[i]
            if ln == 0:
                out[i] = 0
                continue
            c = 1
            s = offsets[i]
            e = s + ln
            for j in range(s, e):
                if data[j] == space:
                    c += 1
            out[i] = c
        return out

    @_njit3(cache=True, nogil=True)
    def _validate_uci_first_nb(data, offsets, lengths):
        n = len(offsets)
        valid = np.ones(n, dtype=np.bool_)
        for i in range(n):
            s = offsets[i]
            ln = lengths[i]
            if ln == 0 or ln < 4:
                valid[i] = False
                continue
            for j in range(4):
                b = int(data[s + j])
                if not ((48 <= b <= 57) or (97 <= b <= 122)):
                    valid[i] = False
                    break
        return valid

    log("Numba JIT puzzle helpers ready", "PUZZLE")
else:
    def _count_moves_nb(data, offsets, lengths):
        out = np.empty(len(offsets), dtype=np.int64)
        for i in range(len(offsets)):
            if lengths[i] == 0:
                out[i] = 0
            else:
                seg = data[offsets[i]:offsets[i] + lengths[i]].tobytes()
                out[i] = seg.count(32) + 1
        return out

    def _validate_uci_first_nb(data, offsets, lengths):
        valid = np.ones(len(offsets), dtype=np.bool_)
        for i in range(len(offsets)):
            if lengths[i] < 4:
                valid[i] = lengths[i] > 0
        return valid


# ── Unified difficulty (delegates to utils.compute_difficulty) ──────────────

def _compute_iterative_difficulty(row, uci_moves):
    """Compute difficulty for a single row using the unified formula."""
    move_count = len(uci_moves)
    fen = str(row.get('fen', '')).strip()
    has_fen = bool(fen)
    has_rating = False
    rating_val = 0.0
    for rkey in ('rating', 'elo', 'difficulty', 'score'):
        rval = str(row.get(rkey, '')).strip()
        if rval and rval.lower() not in ('nan', 'none', ''):
            try:
                rating_val = float(rval)
                has_rating = True
                break
            except ValueError:
                pass
    return compute_difficulty(move_count, has_fen, has_rating, rating_val)


# ── Batch helpers ───────────────────────────────────────────────────────────

def _pack_strings(strings):
    """Pack a list of strings into a flat uint8 buffer with offsets and lengths."""
    encoded = [s.encode('utf-8') if s else b'' for s in strings]
    lengths = np.array([len(e) for e in encoded], dtype=np.int64)
    offsets = np.empty(len(encoded), dtype=np.int64)
    total = 0
    for i in range(len(encoded)):
        offsets[i] = total
        total += lengths[i]
    buf = b''.join(encoded)
    data = (np.frombuffer(buf, dtype=np.uint8).copy()
            if buf else np.empty(0, dtype=np.uint8))
    return data, offsets, lengths


def batch_count_moves(move_strings):
    """Count the number of space-separated moves in each string."""
    if not move_strings:
        return np.array([], dtype=np.int64)
    data, offsets, lengths = _pack_strings(move_strings)
    return _count_moves_nb(data, offsets, lengths)


def batch_validate_uci(move_strings):
    """Validate that the first token in each string looks like a UCI move."""
    if not move_strings:
        return np.array([], dtype=np.bool_)
    data, offsets, lengths = _pack_strings(move_strings)
    return _validate_uci_first_nb(data, offsets, lengths)


# ── GPU difficulty ──────────────────────────────────────────────────────────

if HAS_CUPY:
    import cupy as _cp_gpu

    def gpu_difficulty_scores(move_counts, has_fen, has_rating, rating_vals):
        """CuPy-accelerated vectorized difficulty computation on GPU."""
        mc_gpu = _cp_gpu.asarray(move_counts.astype(np.float64))
        hf_gpu = _cp_gpu.asarray(has_fen.astype(np.float64))
        hr_gpu = _cp_gpu.asarray(has_rating.astype(np.float64))
        rv_gpu = _cp_gpu.asarray(rating_vals.astype(np.float64))
        base = _cp_gpu.clip(mc_gpu / 8.0, 0.0, 1.0)
        fen_b = 0.15 * hf_gpu
        rating = _cp_gpu.where(hr_gpu > 0,
                               _cp_gpu.clip(rv_gpu / 3000.0, 0.0, 1.0), 0.5)
        return _cp_gpu.asnumpy(0.4 * base + 0.2 * fen_b + 0.4 * rating)

    log("CuPy GPU puzzle helpers ready", "PUZZLE")
else:
    def gpu_difficulty_scores(move_counts, has_fen, has_rating, rating_vals):
        """Fallback: vectorized NumPy difficulty (same formula as compute_difficulty)."""
        mc = move_counts.astype(np.float64)
        base = np.clip(mc / 8.0, 0.0, 1.0)
        fen_b = 0.15 * has_fen.astype(np.float64)
        hr = has_rating.astype(np.float64)
        rv = rating_vals.astype(np.float64)
        rating = np.where(hr > 0, np.clip(rv / 3000.0, 0.0, 1.0), 0.5)
        return 0.4 * base + 0.2 * fen_b + 0.4 * rating