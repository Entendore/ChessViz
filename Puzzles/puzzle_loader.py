"""Puzzle database loader — CSV, Parquet, DuckDB, SQLite with dynamic auto-naming."""

import csv, sqlite3
from pathlib import Path
from constants import log, HAS_PANDAS, HAS_PYARROW, HAS_DUCKDB


def load_puzzles(filepath):
    ext = Path(filepath).suffix.lower()
    if ext == '.csv':       rows = _parse_csv(filepath)
    elif ext == '.parquet': rows = _parse_parquet(filepath)
    elif ext == '.duckdb':  rows = _parse_duckdb(filepath)
    elif ext in ('.db', '.sqlite'): rows = _parse_sqlite(filepath)
    else: raise ValueError(f"Unsupported file format: {ext}")
    return _process_rows(rows)

def _parse_csv(filepath):
    with open(filepath, 'r', encoding='utf-8') as f: return list(csv.DictReader(f))

def _parse_parquet(filepath):
    if not HAS_PANDAS and not HAS_PYARROW: raise ImportError("Parquet requires 'pandas' or 'pyarrow'. pip install pandas pyarrow")
    if HAS_PANDAS:
        import pandas as pd; return pd.read_parquet(filepath).to_dict('records')
    else:
        import pyarrow.parquet as pq; return pq.read_table(filepath).to_pandas().to_dict('records')

def _parse_duckdb(filepath):
    if not HAS_DUCKDB: raise ImportError("DuckDB requires 'duckdb'. pip install duckdb")
    import duckdb
    con = duckdb.connect(filepath, read_only=True)
    tables = con.execute("SHOW TABLES").fetchall()
    if not tables: raise ValueError("No tables found in DuckDB database")
    table_name = tables[0][0]
    df = con.execute(f'SELECT * FROM "{table_name}"').fetchdf(); con.close()
    return df.to_dict('records')

def _parse_sqlite(filepath):
    conn = sqlite3.connect(filepath)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    if not tables: conn.close(); raise ValueError("No tables found in SQLite database")
    table_name = tables[0][0]
    cursor = conn.execute(f'SELECT * FROM "{table_name}"')
    col_names = [desc[0] for desc in cursor.description]
    rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]; conn.close()
    return rows

def _generate_name(row, uci_moves, idx):
    name = str(row.get('name', '')).strip()
    if name: return name
    white = str(row.get('white', '')).strip()
    black = str(row.get('black', '')).strip()
    if white and black: return f"{white} vs {black}"
    event = str(row.get('event', '')).strip()
    if event: return event
    ignore_keys = {'fen', 'moves', 'uci', 'pgn', 'id', 'name', 'img', 'desc', 'description', 'white', 'black', 'event'}
    parts = []
    for k, v in row.items():
        val = str(v).strip()
        if k not in ignore_keys and val and val.lower() not in ('nan', 'none', ''):
            parts.append(f"{k.title()}: {val}")
            if len(parts) == 3: break
    if parts: return " | ".join(parts)
    fen = str(row.get('fen', ''))
    if uci_moves: return f"Puzzle: {uci_moves[0]} ({fen[:10]}...)" if fen else f"Puzzle: {uci_moves[0]}"
    return f"Puzzle #{idx + 1}"

def _process_rows(rows):
    puzzles = []
    for idx, row in enumerate(rows):
        row = {str(k).lower(): (v if v is not None else '') for k, v in row.items()}
        uci_val = row.get('moves', row.get('uci', ''))
        if isinstance(uci_val, list): uci_moves = [str(m).strip() for m in uci_val if m]
        else: uci_moves = [m.strip() for m in str(uci_val).split(',') if m.strip()]
        name = _generate_name(row, uci_moves, idx)
        puzzles.append({'name': name, 'fen': str(row.get('fen', '')), 'moves': uci_moves, 'desc': str(row.get('desc', row.get('description', '')))})
    return puzzles