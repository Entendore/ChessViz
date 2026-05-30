"""
openings_loader.py — Load and parse chess openings. Auto-detects UCI/SAN/PGN.
"""

import csv, json, sqlite3, base64, re, io
from pathlib import Path
import chess, chess.pgn
from config import HAS_PANDAS, HAS_PYARROW, HAS_DUCKDB, log
from helpers import _sanitize_for_json

csv.field_size_limit(2**31 - 1)

_UCI_RE = re.compile(r'^[a-h][1-8][a-h][1-8][qrbn]?$', re.IGNORECASE)
_RESULTS = frozenset({'1-0', '0-1', '1/2-1/2', '*', '\u00bd-\u00bd'})

def _looks_like_uci(token): return bool(_UCI_RE.match(token))

def _tokenize(val):
    if isinstance(val, list):
        out = []
        for item in val:
            if isinstance(item, str): out.extend(item.replace(',', ' ').split())
            elif item is not None:
                s = str(item).strip().replace(',', ' ')
                if s: out.extend(s.split())
        return [t for t in out if t and t not in _RESULTS]
    s = str(val).strip().replace(',', ' ')
    s = re.sub(r'\d+\.+', ' ', s)
    return [t for t in s.split() if t and t not in _RESULTS]

def _pgn_to_uci(pgn_str):
    if not pgn_str: return []
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_str))
        return [m.uci() for m in game.mainline_moves()] if game else []
    except Exception: return []

def _san_tokens_to_uci(tokens):
    board = chess.Board(); uci = []
    for san in tokens:
        try:
            move = board.parse_san(san); uci.append(move.uci()); board.push(move)
        except Exception: break
    return uci

def _uci_to_epd(uci_moves):
    board = chess.Board()
    for u in uci_moves:
        try:
            move = chess.Move.from_uci(u)
            if move in board.legal_moves: board.push(move)
            else: break
        except Exception: break
    return board.epd()

def _uci_to_pgn(uci_moves):
    board = chess.Board(); parts = []
    for u in uci_moves:
        try:
            move = chess.Move.from_uci(u)
            if move not in board.legal_moves: break
            san = board.san(move)
            if board.turn == chess.WHITE: parts.append(f"{board.fullmove_number}. {san}")
            else: parts.append(san)
            board.push(move)
        except Exception: break
    return " ".join(parts)

def _extract_uci_moves(row):
    for col in ('uci', 'moves', 'pgn'):
        val = row.get(col, '')
        if not val: continue
        tokens = _tokenize(val)
        if not tokens: continue
        if col == 'uci':
            good = [t for t in tokens if _looks_like_uci(t)]
            if good and len(good) >= len(tokens) * 0.8: return good
        if col == 'moves':
            if all(_looks_like_uci(t) for t in tokens): return tokens
            uci = _san_tokens_to_uci(tokens)
            if uci: return uci
        if col == 'pgn':
            uci = _pgn_to_uci(val if isinstance(val, str) else ' '.join(tokens))
            if uci: return uci
    return []

def load_openings(filepath):
    ext = Path(filepath).suffix.lower()
    if ext == '.csv':          rows = _parse_csv(filepath)
    elif ext in ('.parquet', '.pq'): rows = _parse_parquet(filepath)
    elif ext == '.duckdb':     rows = _parse_duckdb(filepath)
    elif ext in ('.db', '.sqlite'): rows = _parse_sqlite(filepath)
    else: raise ValueError(f"Unsupported format: {ext}")
    for i in range(0, len(rows), 5000):
        yield _process_opening_rows(rows[i:i + 5000])

def _parse_csv(filepath):
    with open(filepath, 'r', encoding='utf-8') as f: return list(csv.DictReader(f))

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
    if not tables: raise ValueError("No tables in DuckDB")
    df = con.execute(f'SELECT * FROM "{tables[0][0]}"').fetchdf(); con.close()
    return df.where(df.notna(), None).to_dict('records')

def _parse_sqlite(filepath):
    conn = sqlite3.connect(filepath)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    if not tables: conn.close(); raise ValueError("No tables found")
    cursor = conn.execute(f'SELECT * FROM "{tables[0][0]}"')
    col_names = [d[0] for d in cursor.description]
    rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]
    conn.close(); return rows

_NAME_ALIASES = ('name', 'opening', 'opening_name')
_ECO_ALIASES = ('eco', 'eco_code', 'ecocode')

def _first_match(row, aliases):
    for a in aliases:
        v = row.get(a, '')
        if v is not None and str(v).strip(): return v
    return ''

def _process_opening_rows(rows):
    openings = []
    for row in rows:
        row = {str(k).lower(): (v if v is not None else '') for k, v in row.items()}
        name = str(_first_match(row, _NAME_ALIASES)) or 'Unknown'
        eco  = str(_first_match(row, _ECO_ALIASES))
        uci_moves = _extract_uci_moves(row)
        epd = row.get('epd', '') or (_uci_to_epd(uci_moves) if uci_moves else '')
        pgn = row.get('pgn', '') or (_uci_to_pgn(uci_moves) if uci_moves else '')
        img_val = row.get('img', '')
        if isinstance(img_val, dict): img_raw = json.dumps(_sanitize_for_json(img_val))
        elif isinstance(img_val, bytes): img_raw = json.dumps({"bytes": base64.b64encode(img_val).decode('ascii')})
        else: img_raw = str(img_val) if img_val else ''
        display_title = f"{eco} — {name}" if eco else name
        openings.append({'volume': str(row.get('eco-volume', '')), 'eco': eco,
                         'name': name, 'img_raw': img_raw, 'pgn': str(pgn),
                         'uci_moves': uci_moves, 'epd': str(epd),
                         'display_title': display_title})
    return openings