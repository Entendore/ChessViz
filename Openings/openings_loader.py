"""
openings_loader.py — Load and parse chess openings from CSV / Parquet / DuckDB / SQLite.
"""

import csv, json, sqlite3, base64
from pathlib import Path

from config import HAS_PANDAS, HAS_PYARROW, HAS_DUCKDB, log
from helpers import _sanitize_for_json

csv.field_size_limit(2**31 - 1)


def load_openings(filepath):
    """Yield chunks of processed opening dicts from the given file."""
    ext = Path(filepath).suffix.lower()
    if ext == '.csv':        rows = _parse_csv(filepath)
    elif ext in ('.parquet', '.pq'): rows = _parse_parquet(filepath)
    elif ext == '.duckdb':   rows = _parse_duckdb(filepath)
    elif ext in ('.db', '.sqlite'): rows = _parse_sqlite(filepath)
    else: raise ValueError(f"Unsupported file format: {ext}")
    for i in range(0, len(rows), 5000):
        yield _process_opening_rows(rows[i:i + 5000])


# ═══════════════════════════════════════════════════════════════════════════════
#  PARSERS
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

def _process_opening_rows(rows):
    openings = []
    for row in rows:
        row = {str(k).lower(): (v if v is not None else '') for k, v in row.items()}

        # Image
        img_val = row.get('img', '')
        if isinstance(img_val, dict):
            img_raw = json.dumps(_sanitize_for_json(img_val))
        elif isinstance(img_val, bytes):
            img_raw = json.dumps({"bytes": base64.b64encode(img_val).decode('ascii')})
        elif img_val is None:
            img_raw = ''
        else:
            img_raw = str(img_val)

        # UCI moves
        uci_val = row.get('uci', '')
        if isinstance(uci_val, list):
            uci_moves = []
            for item in uci_val:
                if isinstance(item, str):
                    uci_moves.extend(item.replace(',', ' ').split())
                elif item is not None:
                    s = str(item).strip().replace(',', ' ')
                    if s: uci_moves.extend(s.split())
        else:
            s = str(uci_val).strip().replace(',', ' ')
            uci_moves = s.split() if s else []

        eco = str(row.get('eco', '')); name = str(row.get('name', 'Unknown'))
        display_title = f"{eco} - {name}" if eco else name

        openings.append({
            'volume': str(row.get('eco-volume', '')), 'eco': eco, 'name': name,
            'img_raw': img_raw, 'pgn': str(row.get('pgn', '')),
            'uci_moves': uci_moves, 'epd': str(row.get('epd', '')),
            'display_title': display_title,
        })
    return openings