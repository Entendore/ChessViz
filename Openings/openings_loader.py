"""
openings_loader.py — Load and parse chess openings from CSV / Parquet / DuckDB / SQLite.
Auto-detects UCI, SAN, and PGN move columns (including lichess DB format).
Generates EPD from moves when not present in the source.
"""

import csv, json, sqlite3, base64, re, io
from pathlib import Path

import chess
import chess.pgn

from config import HAS_PANDAS, HAS_PYARROW, HAS_DUCKDB, log
from helpers import _sanitize_for_json

csv.field_size_limit(2**31 - 1)

# ═══════════════════════════════════════════════════════════════════════════════
#  MOVE FORMAT DETECTION & CONVERSION
# ═══════════════════════════════════════════════════════════════════════════════

_UCI_RE = re.compile(r'^[a-h][1-8][a-h][1-8][qrbn]?$', re.IGNORECASE)
_RESULTS = frozenset({'1-0', '0-1', '1/2-1/2', '*', '\u00bd-\u00bd'})


def _looks_like_uci(token: str) -> bool:
    """Return True if *token* matches the UCI move pattern (e2e4, e7e8q …)."""
    return bool(_UCI_RE.match(token))


def _tokenize(val) -> list[str]:
    """Split a move-string or list-of-strings into clean tokens.

    Handles:
      • Python lists  ["e2e4", "e7e5", …]
      • Space / comma separated strings
      • PGN-style move numbers  "1. e4 e5 2. Nf3"
      • Result tokens  "1-0", "*", etc. (stripped)
    """
    if isinstance(val, list):
        out: list[str] = []
        for item in val:
            if isinstance(item, str):
                out.extend(item.replace(',', ' ').split())
            elif item is not None:
                s = str(item).strip().replace(',', ' ')
                if s:
                    out.extend(s.split())
        return [t for t in out if t and t not in _RESULTS]

    s = str(val).strip().replace(',', ' ')
    # Strip PGN move numbers like "1." "10."  —  keep everything else
    s = re.sub(r'\d+\.+', ' ', s)
    tokens = s.split()
    return [t for t in tokens if t and t not in _RESULTS]


def _pgn_to_uci(pgn_str: str) -> list[str]:
    """Parse a PGN string (with or without headers) and return UCI moves."""
    if not pgn_str or not isinstance(pgn_str, str):
        return []
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_str))
        if game is None:
            return []
        return [m.uci() for m in game.mainline_moves()]
    except Exception:
        return []


def _san_tokens_to_uci(tokens: list[str]) -> list[str]:
    """Play a sequence of SAN tokens on a board and return UCI moves.

    Stops at the first illegal / ambiguous token so partial results are
    still useful.
    """
    board = chess.Board()
    uci: list[str] = []
    for san in tokens:
        try:
            move = board.parse_san(san)
            uci.append(move.uci())
            board.push(move)
        except (chess.InvalidMoveError, chess.IllegalMoveError,
                chess.AmbiguousMoveError):
            break
    return uci


def _uci_to_epd(uci_moves: list[str]) -> str:
    """Play *uci_moves* from the starting position and return the EPD."""
    board = chess.Board()
    for u in uci_moves:
        try:
            move = chess.Move.from_uci(u)
            if move in board.legal_moves:
                board.push(move)
            else:
                break
        except Exception:
            break
    return board.epd()


def _uci_to_pgn(uci_moves: list[str]) -> str:
    """Convert a UCI move list to a PGN move-text string."""
    board = chess.Board()
    san_parts: list[str] = []
    for u in uci_moves:
        try:
            move = chess.Move.from_uci(u)
            if move not in board.legal_moves:
                break
            san = board.san(move)
            if board.turn == chess.WHITE:
                san_parts.append(f"{board.fullmove_number}. {san}")
            else:
                san_parts.append(san)
            board.push(move)
        except Exception:
            break
    return " ".join(san_parts)


# ── High-level extractor ────────────────────────────────────────────────────

def _extract_uci_moves(row: dict) -> list[str]:
    """Try every plausible column to extract a list of UCI moves.

    Column priority:  uci  →  moves  →  pgn
    Format auto-detection:  UCI  →  SAN  →  full PGN
    """
    # 1) 'uci' column — trust it is UCI
    uci_val = row.get('uci', '')
    if uci_val:
        tokens = _tokenize(uci_val)
        if tokens:
            # Validate; tolerate a few bad tokens at the end
            good = [t for t in tokens if _looks_like_uci(t)]
            if good and len(good) >= len(tokens) * 0.8:
                return good

    # 2) 'moves' column — could be UCI *or* SAN
    moves_val = row.get('moves', '')
    if moves_val:
        tokens = _tokenize(moves_val)
        if tokens:
            if all(_looks_like_uci(t) for t in tokens):
                return tokens
            # Mixed / all-SAN — try SAN parse
            uci_list = _san_tokens_to_uci(tokens)
            if uci_list:
                return uci_list

    # 3) 'pgn' column — full PGN (possibly with headers)
    pgn_val = row.get('pgn', '')
    if pgn_val:
        uci_list = _pgn_to_uci(pgn_val)
        if uci_list:
            return uci_list

    return []


# ═══════════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def load_openings(filepath):
    """Yield chunks of processed opening dicts from the given file."""
    ext = Path(filepath).suffix.lower()
    if ext == '.csv':          rows = _parse_csv(filepath)
    elif ext in ('.parquet', '.pq'): rows = _parse_parquet(filepath)
    elif ext == '.duckdb':     rows = _parse_duckdb(filepath)
    elif ext in ('.db', '.sqlite'): rows = _parse_sqlite(filepath)
    else: raise ValueError(f"Unsupported file format: {ext}")
    for i in range(0, len(rows), 5000):
        yield _process_opening_rows(rows[i:i + 5000])


# ═══════════════════════════════════════════════════════════════════════════════
#  FILE PARSERS
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_csv(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _parse_parquet(filepath):
    if HAS_PANDAS:
        import pandas as pd; df = pd.read_parquet(filepath)
        return df.where(df.notna(), None).to_dict('records')
    elif HAS_PYARROW:
        import pyarrow.parquet as pq; tbl = pq.read_table(filepath)
        return tbl.to_pandas().where(tbl.to_pandas().notna(), None).to_dict('records')
    raise ImportError("Parquet requires 'pandas' or 'pyarrow'")


def _parse_duckdb(filepath):
    if not HAS_DUCKDB: raise ImportError("DuckDB requires 'duckdb'")
    import duckdb; con = duckdb.connect(filepath, read_only=True)
    tables = con.execute("SHOW TABLES").fetchall()
    if not tables: raise ValueError("No tables found in DuckDB database")
    table_name = tables[0][0]
    df = con.execute(f'SELECT * FROM "{table_name}"').fetchdf(); con.close()
    return df.where(df.notna(), None).to_dict('records')


def _parse_sqlite(filepath):
    conn = sqlite3.connect(filepath)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    if not tables: conn.close(); raise ValueError("No tables found")
    table_name = tables[0][0]
    cursor = conn.execute(f'SELECT * FROM "{table_name}"')
    col_names = [desc[0] for desc in cursor.description]
    rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]
    conn.close(); return rows


# ═══════════════════════════════════════════════════════════════════════════════
#  ROW PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

# Common column-name aliases (lowercased after normalisation)
_NAME_ALIASES  = ('name', 'opening', 'opening_name', 'opening_name')
_ECO_ALIASES   = ('eco', 'eco_code', 'ecocode')
_ECOVOL_ALIASES = ('eco-volume', 'eco_volume', 'ecovolume')


def _first_match(row: dict, aliases: tuple) -> str:
    """Return the value of the first alias found in *row*, else ''."""
    for a in aliases:
        v = row.get(a, '')
        if v is not None and str(v).strip():
            return v
    return ''


def _process_opening_rows(rows):
    openings = []
    for row in rows:
        # ── Normalise keys to lowercase ────────────────────────────────────
        row = {str(k).lower(): (v if v is not None else '') for k, v in row.items()}

        # ── Name / ECO / volume with alias fallbacks ───────────────────────
        name = str(_first_match(row, _NAME_ALIASES)) or 'Unknown'
        eco  = str(_first_match(row, _ECO_ALIASES))
        eco_vol = str(_first_match(row, _ECOVOL_ALIASES))

        # ── Image (lichess DBs don't have images) ─────────────────────────
        img_val = row.get('img', '')
        if isinstance(img_val, dict):
            img_raw = json.dumps(_sanitize_for_json(img_val))
        elif isinstance(img_val, bytes):
            img_raw = json.dumps({"bytes": base64.b64encode(img_val).decode('ascii')})
        elif img_val is None or img_val == '':
            img_raw = ''
        else:
            img_raw = str(img_val)

        # ── UCI moves — auto-detect format ─────────────────────────────────
        uci_moves = _extract_uci_moves(row)

        # ── EPD — use existing or derive from moves ────────────────────────
        epd_val = row.get('epd', '')
        if not epd_val and uci_moves:
            epd_val = _uci_to_epd(uci_moves)

        # ── PGN — use existing or derive from UCI moves ────────────────────
        pgn_val = row.get('pgn', '')
        if not pgn_val and uci_moves:
            pgn_val = _uci_to_pgn(uci_moves)

        # ── Display title ──────────────────────────────────────────────────
        display_title = f"{eco} — {name}" if eco else name

        openings.append({
            'volume': eco_vol,
            'eco': eco,
            'name': name,
            'img_raw': img_raw,
            'pgn': str(pgn_val),
            'uci_moves': uci_moves,
            'epd': str(epd_val),
            'display_title': display_title,
        })
    return openings