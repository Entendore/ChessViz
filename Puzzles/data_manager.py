"""Data manager — Parquet cache, data-load workers, and openings loader.
Merged openings_loader to keep file count at 10.
Database cache uses .parquet files exclusively (no SQLite).
"""

import os, csv, sqlite3, json, base64
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from constants import log, DATA_DIR, HAS_PANDAS, HAS_PYARROW, HAS_DUCKDB, parse_opening_image
from puzzle_loader import load_puzzles

DB_PUZZLES_PATH = os.path.join(DATA_DIR, "cache_puzzles.parquet")
DB_OPENINGS_PATH = os.path.join(DATA_DIR, "cache_openings.parquet")


# ═══════════════════════════════════════════════════════════════════════════════
#  JSON Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _sanitize_for_json(obj):
    """Recursively sanitize objects for JSON, turning bytes into base64 strings."""
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    elif isinstance(obj, bytes):
        return base64.b64encode(obj).decode('ascii')
    elif isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    else:
        return str(obj)


# ═══════════════════════════════════════════════════════════════════════════════
#  Openings loader (merged from openings_loader.py)
# ═══════════════════════════════════════════════════════════════════════════════

def load_openings(filepath):
    ext = Path(filepath).suffix.lower()
    if ext == '.csv': rows = _parse_csv(filepath)
    elif ext in ('.parquet', '.pq'): rows = _parse_parquet(filepath)
    elif ext == '.duckdb': rows = _parse_duckdb(filepath)
    elif ext in ('.db', '.sqlite'): rows = _parse_sqlite(filepath)
    else: raise ValueError(f"Unsupported file format: {ext}")

    for i in range(0, len(rows), 5000):
        yield _process_opening_rows(rows[i:i+5000])

def _parse_csv(filepath):
    with open(filepath, 'r', encoding='utf-8') as f: return list(csv.DictReader(f))

def _parse_parquet(filepath):
    if not HAS_PANDAS and not HAS_PYARROW: raise ImportError("Parquet requires 'pandas' or 'pyarrow'")
    if HAS_PANDAS: 
        import pandas as pd
        df = pd.read_parquet(filepath)
        return df.where(df.notna(), None).to_dict('records')
    else: 
        import pyarrow.parquet as pq
        tbl = pq.read_table(filepath)
        df = tbl.to_pandas()
        return df.where(df.notna(), None).to_dict('records')

def _parse_duckdb(filepath):
    if not HAS_DUCKDB: raise ImportError("DuckDB requires 'duckdb'")
    import duckdb; con = duckdb.connect(filepath, read_only=True); tables = con.execute("SHOW TABLES").fetchall()
    if not tables: raise ValueError("No tables found in DuckDB database")
    table_name = tables[0][0]; df = con.execute(f'SELECT * FROM "{table_name}"').fetchdf(); con.close()
    return df.where(df.notna(), None).to_dict('records')

def _parse_sqlite(filepath):
    conn = sqlite3.connect(filepath); cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';"); tables = cursor.fetchall()
    if not tables: conn.close(); raise ValueError("No tables found in SQLite database")
    table_name = tables[0][0]; cursor = conn.execute(f'SELECT * FROM "{table_name}"'); col_names = [desc[0] for desc in cursor.description]; rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]; conn.close(); return rows

def _process_opening_rows(rows):
    openings = []
    for row in rows:
        row = {str(k).lower(): (v if v is not None else '') for k, v in row.items()}
        
        img_val = row.get('img', '')
        if isinstance(img_val, dict):
            img_raw = json.dumps(_sanitize_for_json(img_val))
        elif isinstance(img_val, bytes):
            img_raw = json.dumps({"bytes": base64.b64encode(img_val).decode('ascii')})
        elif img_val is None:
            img_raw = ''
        else:
            img_raw = str(img_val)

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

        eco = str(row.get('eco', ''))
        name = str(row.get('name', 'Unknown'))
        display_title = f"{eco} - {name}" if eco else name

        openings.append({
            'volume': str(row.get('eco-volume', '')),
            'eco': eco,
            'name': name,
            'img_raw': img_raw,
            'pgn': str(row.get('pgn', '')),
            'uci_moves': uci_moves,
            'epd': str(row.get('epd', '')),
            'display_title': display_title
        })
    return openings


# ═══════════════════════════════════════════════════════════════════════════════
#  Parquet Data Provider
# ═══════════════════════════════════════════════════════════════════════════════

class DataProvider:
    """Parquet-backed data provider. Stores data in-memory as list-of-dicts
    with .parquet / .pq file persistence via pandas or pyarrow."""

    _PUZZLE_COLS  = ['id', 'name', 'fen', 'moves', 'desc', 'difficulty', 'display_title']
    _OPENING_COLS = ['id', 'name', 'eco', 'img_raw', 'pgn', 'uci_moves', 'epd', 'display_title']

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._data    = {}   # {db_type: [dict, ...]}
        self._next_id = {}   # {db_type: int}
        self._dirty   = {}   # {db_type: bool}
        for dt in ('puzzles', 'openings'):
            self._load_cache(dt)
            self._dirty[dt] = False

    # ── Schema helpers ────────────────────────────────────────────────────────

    def _columns(self, db_type):
        return self._PUZZLE_COLS if db_type == 'puzzles' else self._OPENING_COLS

    def _cache_path(self, db_type):
        return DB_PUZZLES_PATH if db_type == 'puzzles' else DB_OPENINGS_PATH

    # ── Cache I/O ─────────────────────────────────────────────────────────────

    def _load_cache(self, db_type):
        path = self._cache_path(db_type)
        if not os.path.exists(path):
            self._data[db_type]    = []
            self._next_id[db_type] = 1
            return

        if not HAS_PANDAS and not HAS_PYARROW:
            log(f"No pandas/pyarrow; cannot load {db_type} cache", "DATA")
            self._data[db_type]    = []
            self._next_id[db_type] = 1
            return

        try:
            if HAS_PANDAS:
                import pandas as pd
                df = pd.read_parquet(path)
            else:
                import pyarrow.parquet as pq
                df = pq.read_table(path).to_pandas()

            df = df.where(df.notna(), None)
            records = df.to_dict('records')

            for rec in records:
                # Normalise None → sensible defaults
                for key in list(rec.keys()):
                    if rec[key] is None:
                        if key == 'id':         rec[key] = 0
                        elif key == 'difficulty': rec[key] = 0.5
                        else:                   rec[key] = ''
                # Deserialize JSON list columns back to Python lists
                if 'moves' in rec and isinstance(rec['moves'], str):
                    try: rec['moves'] = json.loads(rec['moves'])
                    except Exception: pass
                if 'uci_moves' in rec and isinstance(rec['uci_moves'], str):
                    try: rec['uci_moves'] = json.loads(rec['uci_moves'])
                    except Exception: pass
                if 'id' in rec:
                    rec['id'] = int(rec['id'])

            self._data[db_type]    = records
            self._next_id[db_type] = max((r['id'] for r in records), default=0) + 1
            log(f"Loaded {len(records)} {db_type} from parquet cache", "DATA")

        except Exception as e:
            log(f"Error loading {db_type} cache: {e}", "DATA")
            self._data[db_type]    = []
            self._next_id[db_type] = 1

    def _save_cache(self, db_type):
        if not HAS_PANDAS and not HAS_PYARROW:
            return

        path     = self._cache_path(db_type)
        tmp_path = path + '.tmp'
        items    = self._data.get(db_type, [])
        cols     = self._columns(db_type)

        try:
            # Serialize list columns to JSON strings for parquet storage
            save_items = []
            for item in items:
                si = dict(item)
                if 'moves' in si and isinstance(si['moves'], list):
                    si['moves'] = json.dumps(si['moves'], default=str)
                if 'uci_moves' in si and isinstance(si['uci_moves'], list):
                    si['uci_moves'] = json.dumps(si['uci_moves'], default=str)
                if 'difficulty' in si:
                    si['difficulty'] = float(si.get('difficulty', 0.5))
                if 'id' in si:
                    si['id'] = int(si['id'])
                # Ensure every column is present
                for col in cols:
                    if col not in si:
                        if col == 'id':          si[col] = 0
                        elif col == 'difficulty': si[col] = 0.5
                        else:                    si[col] = ''
                save_items.append(si)

            if HAS_PANDAS:
                import pandas as pd
                df = (pd.DataFrame(save_items, columns=cols) if save_items
                      else pd.DataFrame(columns=cols))
                df.to_parquet(tmp_path, index=False)
            else:
                import pyarrow as pa
                import pyarrow.parquet as pq
                type_map = {'id': pa.int64(), 'difficulty': pa.float64()}
                if save_items:
                    arrays = []
                    for col in cols:
                        vals = [r.get(col, '') for r in save_items]
                        pa_type = type_map.get(col, pa.string())
                        if pa_type == pa.int64():
                            arrays.append(pa.array([int(v) for v in vals], type=pa.int64()))
                        elif pa_type == pa.float64():
                            arrays.append(pa.array([float(v) for v in vals], type=pa.float64()))
                        else:
                            arrays.append(pa.array([str(v) for v in vals], type=pa.string()))
                    schema = pa.schema([(c, type_map.get(c, pa.string())) for c in cols])
                    tbl = pa.Table.from_arrays(arrays, schema=schema)
                else:
                    schema = pa.schema([(c, type_map.get(c, pa.string())) for c in cols])
                    tbl = pa.Table.from_arrays(
                        [pa.array([], type=type_map.get(c, pa.string())) for c in cols],
                        schema=schema)
                pq.write_table(tbl, tmp_path)

            # Atomic replace
            os.replace(tmp_path, path)
            self._dirty[db_type] = False
            log(f"Saved {len(items)} {db_type} to parquet cache", "DATA")

        except Exception as e:
            log(f"Error saving {db_type} cache: {e}", "DATA")
            if os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except OSError: pass

    # ── Public API ────────────────────────────────────────────────────────────

    def clear_table(self, db_type):
        self._data[db_type]    = []
        self._next_id[db_type] = 1
        self._save_cache(db_type)

    def insert_batch(self, db_type, items):
        for i in items:
            if db_type == 'puzzles':
                rec = {
                    'id': self._next_id[db_type],
                    'name': str(i.get('name', '')),
                    'fen': str(i.get('fen', '')),
                    'moves': i.get('moves', []),       # list in memory
                    'desc': str(i.get('desc', '')),
                    'difficulty': float(i.get('difficulty', 0.5)),
                    'display_title': str(i.get('display_title', i.get('name', '')))
                }
            else:
                rec = {
                    'id': self._next_id[db_type],
                    'name': str(i.get('name', '')),
                    'eco': str(i.get('eco', '')),
                    'img_raw': str(i.get('img_raw', '')),
                    'pgn': str(i.get('pgn', '')),
                    'uci_moves': i.get('uci_moves', []),  # list in memory
                    'epd': str(i.get('epd', '')),
                    'display_title': str(i.get('display_title', i.get('name', '')))
                }
            self._data[db_type].append(rec)
            self._next_id[db_type] += 1
        self._dirty[db_type] = True

    def flush(self, db_type=None):
        """Persist dirty caches to .parquet files."""
        if db_type:
            if self._dirty.get(db_type, False):
                self._save_cache(db_type)
        else:
            for dt in list(self._dirty.keys()):
                if self._dirty[dt]:
                    self._save_cache(dt)

    def reload(self, db_type):
        """Reload from parquet file (call after external writes complete)."""
        self._load_cache(db_type)
        self._dirty[db_type] = False

    def get_count(self, db_type, filter_text=""):
        items = self._data.get(db_type, [])
        if filter_text:
            ft = filter_text.lower()
            return sum(1 for item in items if ft in str(item.get('name', '')).lower())
        return len(items)

    def get_page(self, db_type, page, page_size, filter_text=""):
        items = self._data.get(db_type, [])
        if filter_text:
            ft = filter_text.lower()
            filtered = [item for item in items if ft in str(item.get('name', '')).lower()]
        else:
            filtered = items
        start = page * page_size
        end   = start + page_size
        return [dict(item) for item in filtered[start:end]]

    def get_ids_by_filter(self, db_type, filter_text=""):
        items = self._data.get(db_type, [])
        if filter_text:
            ft = filter_text.lower()
            return [item['id'] for item in items if ft in str(item.get('name', '')).lower()]
        return [item['id'] for item in items]

    def get_items_by_ids(self, db_type, ids):
        items  = self._data.get(db_type, [])
        id_set = set(ids)
        return [dict(item) for item in items if item.get('id') in id_set]


# ═══════════════════════════════════════════════════════════════════════════════
#  Data-load worker thread
# ═══════════════════════════════════════════════════════════════════════════════

class DataLoadWorker(QThread):
    data_ready = Signal(str, int)
    load_error = Signal(str, str)

    def __init__(self, db_type, directory=None, single_file=None):
        super().__init__()
        self.db_type     = db_type
        self.directory   = directory
        self.single_file = single_file
        self._abort      = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            db = DataProvider()
            db.clear_table(self.db_type)
            total_count = 0

            files = self._get_files()
            for f in files:
                if self._abort: break
                try:
                    loader = load_puzzles if self.db_type == 'puzzles' else load_openings
                    for chunk in loader(str(f)):
                        if self._abort: break
                        db.insert_batch(self.db_type, chunk)
                        total_count += len(chunk)
                except Exception as e:
                    log(f"Error loading {f.name}: {e}", "DATA")
                    self.load_error.emit(self.db_type, f"{f.name}: {e}")

            db.flush(self.db_type)   # ← persist to .parquet
            self.data_ready.emit(self.db_type, total_count)

        except Exception as e:
            log(f"Fatal load error ({self.db_type}): {e}", "DATA")
            self.load_error.emit(self.db_type, str(e))
            self.data_ready.emit(self.db_type, 0)

    def _get_files(self):
        valid_exts = {'.csv', '.parquet', '.pq', '.duckdb', '.db', '.sqlite'}
        if self.single_file:
            return [Path(self.single_file)]
        directory = self.directory
        if not directory or not os.path.exists(directory):
            if directory: os.makedirs(directory, exist_ok=True)
            return []
        return sorted(f for f in Path(directory).iterdir()
                      if f.suffix.lower() in valid_exts)