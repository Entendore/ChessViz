"""Openings data loader — CSV, Parquet, DuckDB, SQLite."""

import csv, sqlite3
from pathlib import Path

from constants import (
    log, HAS_PANDAS, HAS_PYARROW, HAS_DUCKDB, parse_opening_image,
)


def load_openings(filepath):
    """Detect file format and dispatch to the correct parser.

    Returns a list of dicts with keys:
        volume, eco, name, pixmap, pgn, uci_moves, epd
    """
    ext = Path(filepath).suffix.lower()
    log(f"Loading openings file: {filepath} (Format: {ext})", "OPENINGS")

    if ext == '.csv':
        rows = _parse_csv(filepath)
    elif ext == '.parquet':
        rows = _parse_parquet(filepath)
    elif ext == '.duckdb':
        rows = _parse_duckdb(filepath)
    elif ext in ('.db', '.sqlite'):
        rows = _parse_sqlite(filepath)
    else:
        raise ValueError(f"Unsupported file format: {ext}")

    return _process_rows(rows)


# ── Per-format parsers ────────────────────────────────────────────────────────

def _parse_csv(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return list(reader)


def _parse_parquet(filepath):
    if not HAS_PANDAS and not HAS_PYARROW:
        raise ImportError(
            "Parquet support requires 'pandas' or 'pyarrow'. "
            "Install via: pip install pandas pyarrow")
    if HAS_PANDAS:
        import pandas as pd
        df = pd.read_parquet(filepath)
    else:
        import pyarrow.parquet as pq
        df = pq.read_table(filepath).to_pandas()
    return df.to_dict('records')


def _parse_duckdb(filepath):
    if not HAS_DUCKDB:
        raise ImportError(
            "DuckDB support requires 'duckdb'. Install via: pip install duckdb")
    import duckdb
    con = duckdb.connect(filepath, read_only=True)
    tables = con.execute("SHOW TABLES").fetchall()
    if not tables:
        raise ValueError("No tables found in DuckDB database")
    table_name = tables[0][0]
    log(f"Reading from DuckDB table: {table_name}", "OPENINGS")
    df = con.execute(f'SELECT * FROM "{table_name}"').fetchdf()
    con.close()
    return df.to_dict('records')


def _parse_sqlite(filepath):
    conn = sqlite3.connect(filepath)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    if not tables:
        conn.close()
        raise ValueError("No tables found in SQLite database")
    table_name = tables[0][0]
    log(f"Reading from SQLite table: {table_name}", "OPENINGS")
    cursor = conn.execute(f'SELECT * FROM "{table_name}"')
    col_names = [desc[0] for desc in cursor.description]
    rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]
    conn.close()
    return rows


# ── Row normalisation ─────────────────────────────────────────────────────────

def _process_rows(rows):
    """Normalize rows from any data source into the app's internal format."""
    openings = []
    for row in rows:
        # Normalise keys to lowercase strings; replace None with ''
        row = {str(k).lower(): (v if v is not None else '')
               for k, v in row.items()}

        # Image
        pixmap = parse_opening_image(row.get('img', ''))

        # UCI moves list
        uci_val = row.get('uci', '')
        if isinstance(uci_val, list):
            uci_moves = [str(m).strip() for m in uci_val if m]
        else:
            uci_moves = [m.strip() for m in str(uci_val).split(',')
                         if m.strip()]

        openings.append({
            'volume': str(row.get('eco-volume', '')),
            'eco':    str(row.get('eco', '')),
            'name':   str(row.get('name', 'Unknown')),
            'pixmap': pixmap,
            'pgn':    str(row.get('pgn', '')),
            'uci_moves': uci_moves,
            'epd':    str(row.get('epd', '')),
        })
    return openings