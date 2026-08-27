"""Data manager — Parquet cache, streaming import, slim-index DataProvider.
Database cache uses .parquet files exclusively (no SQLite).

Memory strategy for millions of rows:
  • Import streams chunks → ParquetWriter (never accumulates all rows in RAM)
  • A "slim" DataFrame (id, name, display_title, difficulty/eco) stays in
    memory for fast pagination and filtering (~50–100 MB per million rows)
  • Full records (fen, moves, pgn, img_raw, …) are loaded on-demand from
    the parquet cache via pyarrow batch scanning
"""

import os, json, sqlite3, csv, base64, re, ast, tempfile, shutil
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from constants import (log, DATA_DIR, HAS_PANDAS, HAS_PYARROW,
                       HAS_DUCKDB, parse_opening_image)
from puzzle_loader import load_puzzles

DB_PUZZLES_PATH = os.path.join(DATA_DIR, "cache_puzzles.parquet")
DB_OPENINGS_PATH = os.path.join(DATA_DIR, "cache_openings.parquet")


# ═══════════════════════════════════════════════════════════════════════════════
#  JSON Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _sanitize_for_json(obj):
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
    if ext == '.csv':
        rows = _parse_csv(filepath)
    elif ext in ('.parquet', '.pq'):
        rows = _parse_parquet(filepath)
    elif ext == '.duckdb':
        rows = _parse_duckdb(filepath)
    elif ext in ('.db', '.sqlite'):
        rows = _parse_sqlite(filepath)
    else:
        raise ValueError(f"Unsupported file format: {ext}")
    for i in range(0, len(rows), 5000):
        yield _process_opening_rows(rows[i:i + 5000])


def _parse_csv(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _parse_parquet(filepath):
    if not HAS_PANDAS and not HAS_PYARROW:
        raise ImportError("Parquet requires 'pandas' or 'pyarrow'")
    if HAS_PANDAS:
        import pandas as pd
        df = pd.read_parquet(filepath)
        return df.where(df.notna(), None).to_dict('records')
    else:
        import pyarrow.parquet as pq
        tbl = pq.read_table(filepath)
        return tbl.to_pandas().where(
            tbl.to_pandas().notna(), None).to_dict('records')


def _parse_duckdb(filepath):
    if not HAS_DUCKDB:
        raise ImportError("DuckDB requires 'duckdb'")
    import duckdb
    con = duckdb.connect(filepath, read_only=True)
    tables = con.execute("SHOW TABLES").fetchall()
    if not tables:
        raise ValueError("No tables found in DuckDB database")
    table_name = tables[0][0]
    df = con.execute(f'SELECT * FROM "{table_name}"').fetchdf()
    con.close()
    return df.where(df.notna(), None).to_dict('records')


def _parse_sqlite(filepath):
    conn = sqlite3.connect(filepath)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    if not tables:
        conn.close()
        raise ValueError("No tables found")
    table_name = tables[0][0]
    cursor = conn.execute(f'SELECT * FROM "{table_name}"')
    col_names = [desc[0] for desc in cursor.description]
    rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]
    conn.close()
    return rows


def _process_opening_rows(rows):
    openings = []
    for row in rows:
        row = {str(k).lower(): (v if v is not None else '')
               for k, v in row.items()}
        img_val = row.get('img', '')
        if isinstance(img_val, dict):
            img_raw = json.dumps(_sanitize_for_json(img_val))
        elif isinstance(img_val, bytes):
            img_raw = json.dumps(
                {"bytes": base64.b64encode(img_val).decode('ascii')})
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
                    if s:
                        uci_moves.extend(s.split())
        else:
            s = str(uci_val).strip().replace(',', ' ')
            uci_moves = s.split() if s else []
        eco = str(row.get('eco', ''))
        name = str(row.get('name', 'Unknown'))
        display_title = f"{eco} - {name}" if eco else name
        openings.append({
            'volume': str(row.get('eco-volume', '')),
            'eco': eco, 'name': name, 'img_raw': img_raw,
            'pgn': str(row.get('pgn', '')),
            'uci_moves': uci_moves,
            'epd': str(row.get('epd', '')),
            'display_title': display_title,
        })
    return openings


# ═══════════════════════════════════════════════════════════════════════════════
#  Parquet Data Provider  —  slim-index + on-demand full records
# ═══════════════════════════════════════════════════════════════════════════════

class DataProvider:
    """Two-tier storage:
      • _slim[db_type]  →  pd.DataFrame with only listing columns (in RAM)
      • cache parquet   →  full records on disk, loaded on demand
    Import streams directly to the parquet file via ParquetWriter
    (no full-dataset RAM accumulation).
    """

    _PUZZLE_COLS = ['id', 'name', 'fen', 'moves', 'desc',
                    'difficulty', 'display_title']
    _OPENING_COLS = ['id', 'name', 'eco', 'img_raw', 'pgn',
                     'uci_moves', 'epd', 'display_title']

    _SLIM_PUZZLE_COLS = ['id', 'name', 'difficulty', 'display_title']
    _SLIM_OPENING_COLS = ['id', 'name', 'eco', 'display_title']

    _LIST_COLS = {'moves', 'uci_moves'}

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._slim = {}
        self._next_id = {}
        self._dirty = {}
        for dt in ('puzzles', 'openings'):
            self._load_slim(dt)
            self._dirty[dt] = False

    # ── Schema helpers ────────────────────────────────────────────────────

    def _columns(self, db_type):
        return (self._PUZZLE_COLS if db_type == 'puzzles'
                else self._OPENING_COLS)

    def _slim_columns(self, db_type):
        return (self._SLIM_PUZZLE_COLS if db_type == 'puzzles'
                else self._SLIM_OPENING_COLS)

    def _cache_path(self, db_type):
        return (DB_PUZZLES_PATH if db_type == 'puzzles'
                else DB_OPENINGS_PATH)

    # ── Parquet column detection ──────────────────────────────────────────

    @staticmethod
    def _parquet_columns(path):
        """Get column names from a parquet file without reading data."""
        try:
            if HAS_PYARROW:
                import pyarrow.parquet as pq
                return [f.name for f in pq.read_schema(path)]
        except Exception:
            pass
        try:
            import pyarrow.parquet as pq          # second attempt
            return [f.name for f in pq.read_schema(path)]
        except Exception:
            pass
        try:
            if HAS_PANDAS:
                import pandas as pd
                return list(pd.read_parquet(
                    path, columns=None).head(0).columns)
        except Exception:
            pass
        return []

    # ── Slim-index I/O ────────────────────────────────────────────────────

    def _empty_slim(self, db_type):
        if HAS_PANDAS:
            import pandas as pd
            return pd.DataFrame(columns=self._slim_columns(db_type))
        return []

    def _load_slim(self, db_type):
        """Load only the slim columns from the parquet cache into RAM."""
        path = self._cache_path(db_type)
        slim_cols = self._slim_columns(db_type)

        if not os.path.exists(path):
            log(f"No cache file for {db_type}", "DATA")
            self._slim[db_type] = self._empty_slim(db_type)
            self._next_id[db_type] = 1
            return

        if not HAS_PANDAS and not HAS_PYARROW:
            log(f"No pandas/pyarrow; cannot load {db_type} cache", "DATA")
            self._slim[db_type] = self._empty_slim(db_type)
            self._next_id[db_type] = 1
            return

        try:
            # Determine which slim columns exist in the file
            available = self._parquet_columns(path)
            if available:
                read_cols = [c for c in slim_cols if c in available]
            else:
                # Cannot detect columns — try reading with slim_cols anyway
                read_cols = slim_cols

            if not read_cols:
                log(f"No matching columns in {db_type} cache", "DATA")
                self._slim[db_type] = self._empty_slim(db_type)
                self._next_id[db_type] = 1
                return

            df = None
            # Try reading only the slim columns (column pruning)
            try:
                if HAS_PANDAS:
                    import pandas as pd
                    df = pd.read_parquet(path, columns=read_cols)
                elif HAS_PYARROW:
                    import pyarrow.parquet as pq
                    tbl = pq.read_table(path, columns=read_cols)
                    df = tbl.to_pandas()
            except (KeyError, ValueError, AttributeError,
                    OSError, Exception) as e:
                log(f"Column-pruned read failed for {db_type} "
                    f"({e}), reading all columns", "DATA")
                df = None

            # Fallback: read all columns then keep only slim ones
            if df is None:
                try:
                    if HAS_PANDAS:
                        import pandas as pd
                        df = pd.read_parquet(path)
                    elif HAS_PYARROW:
                        import pyarrow.parquet as pq
                        df = pq.read_table(path).to_pandas()
                except Exception as e2:
                    log(f"All-column read also failed for {db_type}: "
                        f"{e2}", "DATA")
                    self._slim[db_type] = self._empty_slim(db_type)
                    self._next_id[db_type] = 1
                    return

            # Ensure all slim columns exist (fill missing with defaults)
            for c in slim_cols:
                if c not in df.columns:
                    if c == 'id':
                        df[c] = 0
                    elif c == 'difficulty':
                        df[c] = 0.5
                    else:
                        df[c] = ''
            df = df[slim_cols]

            # Normalise types
            if 'id' in df.columns:
                df['id'] = df['id'].astype(int)
            if 'difficulty' in df.columns:
                df['difficulty'] = pd.to_numeric(
                    df['difficulty'], errors='coerce').fillna(0.5)

            self._slim[db_type] = df
            self._next_id[db_type] = (
                int(df['id'].max()) + 1 if len(df) > 0 else 1)
            mem_mb = df.memory_usage(deep=True).sum() / 1e6
            log(f"Loaded slim {len(df):,} {db_type} ({mem_mb:.1f} MB)",
                "DATA")
        except Exception as e:
            log(f"Error loading {db_type} slim: {e}", "DATA")
            import traceback
            traceback.print_exc()
            self._slim[db_type] = self._empty_slim(db_type)
            self._next_id[db_type] = 1

    # ── Full-record I/O (on-demand from parquet) ──────────────────────────

    def _deserialize_record(self, rec):
        """Deserialize JSON columns and normalise types."""
        for col in self._LIST_COLS:
            if col in rec and isinstance(rec[col], str):
                try:
                    rec[col] = json.loads(rec[col])
                except Exception:
                    pass
        if 'id' in rec:
            rec['id'] = int(rec['id'])
        if 'difficulty' in rec and rec.get('difficulty') is None:
            rec['difficulty'] = 0.5
        for key in list(rec.keys()):
            if rec[key] is None:
                if key == 'id':
                    rec[key] = 0
                elif key == 'difficulty':
                    rec[key] = 0.5
                else:
                    rec[key] = ''
        return rec

    def _records_from_parquet(self, db_type, ids=None):
        """Read full records from the parquet cache on demand.
        Uses iter_batches to keep peak memory bounded.
        """
        path = self._cache_path(db_type)
        if not os.path.exists(path):
            return []

        id_set = set(ids) if ids is not None else None
        results = []
        scan_batch = 100_000

        try:
            if HAS_PYARROW:
                import pyarrow.parquet as pq
                pf = pq.ParquetFile(path)
                for batch in pf.iter_batches(batch_size=scan_batch):
                    df = batch.to_pandas()
                    if id_set is not None:
                        df = df[df['id'].isin(id_set)]
                        id_set -= set(df['id'].tolist())
                    for rec in df.to_dict('records'):
                        results.append(self._deserialize_record(rec))
                    del df, batch
                    if id_set is not None and not id_set:
                        break
            elif HAS_PANDAS:
                import pandas as pd
                df = pd.read_parquet(path)
                if id_set is not None:
                    df = df[df['id'].isin(id_set)]
                for rec in df.to_dict('records'):
                    results.append(self._deserialize_record(rec))
                del df
        except Exception as e:
            log(f"Error reading {db_type} records: {e}", "DATA")

        return results

    def _chunks_from_parquet(self, db_type, ids=None, chunk_size=500):
        """Yield lists of full-record dicts in chunks (for batch export)."""
        path = self._cache_path(db_type)
        if not os.path.exists(path):
            return

        id_set = set(ids) if ids is not None else None
        buf = []
        scan_batch = 100_000

        try:
            if HAS_PYARROW:
                import pyarrow.parquet as pq
                pf = pq.ParquetFile(path)
                for batch in pf.iter_batches(batch_size=scan_batch):
                    df = batch.to_pandas()
                    if id_set is not None:
                        df = df[df['id'].isin(id_set)]
                        id_set -= set(df['id'].tolist())
                    for rec in df.to_dict('records'):
                        buf.append(self._deserialize_record(rec))
                        if len(buf) >= chunk_size:
                            yield buf
                            buf = []
                    del df
                    if id_set is not None and not id_set:
                        break
            elif HAS_PANDAS:
                import pandas as pd
                df = pd.read_parquet(path)
                if id_set is not None:
                    df = df[df['id'].isin(id_set)]
                for rec in df.to_dict('records'):
                    buf.append(self._deserialize_record(rec))
                    if len(buf) >= chunk_size:
                        yield buf
                        buf = []
                del df
        except Exception as e:
            log(f"Error scanning {db_type}: {e}", "DATA")

        if buf:
            yield buf

    # ── Record construction ───────────────────────────────────────────────

    def _make_record(self, db_type, item, next_id):
        if db_type == 'puzzles':
            return {
                'id': next_id,
                'name': str(item.get('name', '')),
                'fen': str(item.get('fen', '')),
                'moves': item.get('moves', []),
                'desc': str(item.get('desc', '')),
                'difficulty': float(item.get('difficulty', 0.5)),
                'display_title': str(
                    item.get('display_title', item.get('name', ''))),
            }
        else:
            return {
                'id': next_id,
                'name': str(item.get('name', '')),
                'eco': str(item.get('eco', '')),
                'img_raw': str(item.get('img_raw', '')),
                'pgn': str(item.get('pgn', '')),
                'uci_moves': item.get('uci_moves', []),
                'epd': str(item.get('epd', '')),
                'display_title': str(
                    item.get('display_title', item.get('name', ''))),
            }

    def _serialize_record_for_parquet(self, rec, cols):
        """Prepare a record for parquet storage: JSON-encode lists."""
        sr = dict(rec)
        for col in self._LIST_COLS:
            if col in sr and isinstance(sr[col], list):
                sr[col] = json.dumps(sr[col], default=str)
        if 'difficulty' in sr:
            try:
                sr['difficulty'] = float(sr.get('difficulty', 0.5))
            except (ValueError, TypeError):
                sr['difficulty'] = 0.5
        if 'id' in sr:
            sr['id'] = int(sr['id'])
        for col in cols:
            if col not in sr:
                if col == 'id':
                    sr[col] = 0
                elif col == 'difficulty':
                    sr[col] = 0.5
                else:
                    sr[col] = ''
        return sr

    # ── Streaming import (for bulk data load) ─────────────────────────────

    def stream_import(self, db_type, chunk_generator):
        """Import chunks from a generator directly into the parquet cache.
        Uses ParquetWriter to write row groups incrementally —
        only ONE chunk is in memory at a time.
        Yields (chunk_count, total_count) after each chunk.
        """
        cols = self._columns(db_type)
        path = self._cache_path(db_type)
        next_id = self._next_id[db_type]
        total_count = 0

        # ── Choose strategy ───────────────────────────────────────────
        # pyarrow ParquetWriter:  writes row groups incrementally, O(1) RAM
        # pandas temp-file:       writes each chunk to a temp parquet,
        #                          then concatenates at the end

        if HAS_PYARROW:
            yield from self._stream_import_pyarrow(
                db_type, chunk_generator, cols, path, next_id)
        elif HAS_PANDAS:
            yield from self._stream_import_pandas(
                db_type, chunk_generator, cols, path, next_id)
        else:
            raise ImportError("Need pandas or pyarrow for parquet I/O")

        # Rebuild slim index from the newly written file
        self._load_slim(db_type)
        self._dirty[db_type] = False

    # ── pyarrow ParquetWriter path (best: constant RAM) ───────────────────

    def _stream_import_pyarrow(self, db_type, chunk_generator,
                               cols, path, next_id):
        import pyarrow as pa
        import pyarrow.parquet as pq

        writer = None
        total_count = 0
        schema = None

        try:
            for chunk in chunk_generator:
                if not chunk:
                    continue

                records = []
                for item in chunk:
                    rec = self._make_record(db_type, item, next_id)
                    records.append(
                        self._serialize_record_for_parquet(rec, cols))
                    next_id += 1

                # Build a pyarrow Table from this chunk
                chunk_df = self._records_to_dataframe(records, cols)
                table = pa.Table.from_pandas(chunk_df, preserve_index=False)

                if writer is None:
                    schema = table.schema
                    writer = pq.ParquetWriter(path, schema)
                else:
                    # Ensure schema compatibility (cast if needed)
                    if table.schema != schema:
                        table = table.cast(schema)

                writer.write_table(table)
                total_count += len(chunk)
                del records, chunk_df, table

                yield len(chunk), total_count
        finally:
            if writer is not None:
                writer.close()

        self._next_id[db_type] = next_id

    # ── pandas temp-file path (fallback: one chunk + merge in RAM) ────────

    def _stream_import_pandas(self, db_type, chunk_generator,
                              cols, path, next_id):
        import pandas as pd

        temp_dir = path + '.parts'
        os.makedirs(temp_dir, exist_ok=True)
        temp_files = []
        total_count = 0

        try:
            for chunk_idx, chunk in enumerate(chunk_generator):
                if not chunk:
                    continue

                records = []
                for item in chunk:
                    rec = self._make_record(db_type, item, next_id)
                    records.append(
                        self._serialize_record_for_parquet(rec, cols))
                    next_id += 1

                chunk_df = self._records_to_dataframe(records, cols)
                temp_path = os.path.join(
                    temp_dir, f'part_{chunk_idx:06d}.parquet')
                chunk_df.to_parquet(temp_path, index=False)
                temp_files.append(temp_path)
                total_count += len(chunk)
                del records, chunk_df

                yield len(chunk), total_count

            # Merge all temp files into the final parquet
            if temp_files:
                log(f"Merging {len(temp_files)} temp parts for "
                    f"{db_type}…", "DATA")
                dfs = []
                for tf in temp_files:
                    dfs.append(pd.read_parquet(tf))
                combined = pd.concat(dfs, ignore_index=True)
                combined.to_parquet(path, index=False)
                del dfs, combined
                log(f"Merge complete: {total_count:,} {db_type}", "DATA")
            else:
                # No data — write empty parquet
                pd.DataFrame(columns=cols).to_parquet(path, index=False)

        finally:
            # Clean up temp files
            for f in temp_files:
                try:
                    os.remove(f)
                except OSError:
                    pass
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except OSError:
                pass

        self._next_id[db_type] = next_id

    # ── DataFrame construction helper ─────────────────────────────────────

    def _records_to_dataframe(self, records, cols):
        """Convert serialized record dicts to a pandas DataFrame."""
        import pandas as pd

        if not records:
            return pd.DataFrame(columns=cols)

        df = pd.DataFrame(records, columns=cols)

        # Ensure correct types
        if 'id' in df.columns:
            df['id'] = df['id'].astype(int)
        if 'difficulty' in df.columns:
            df['difficulty'] = pd.to_numeric(
                df['difficulty'], errors='coerce').fillna(0.5)

        return df

    # ── Small-batch append (for incremental inserts) ──────────────────────

    def _append_records_to_parquet(self, db_type, records, cols):
        """Append a small batch of records to the existing parquet file.
        NOT suitable for bulk import (use stream_import instead).
        """
        path = self._cache_path(db_type)

        save_records = [
            self._serialize_record_for_parquet(rec, cols)
            for rec in records
        ]

        if HAS_PANDAS:
            import pandas as pd
            new_df = self._records_to_dataframe(save_records, cols)
        else:
            return

        if not os.path.exists(path):
            new_df.to_parquet(path, index=False)
        else:
            existing = pd.read_parquet(path)
            combined = pd.concat(
                [existing, new_df], ignore_index=True)
            combined.to_parquet(path, index=False)
            del existing, combined

    def _save_cache(self, db_type):
        """Mark clean. Streaming import writes directly."""
        self._dirty[db_type] = False

    # ── Public API ────────────────────────────────────────────────────────

    def clear_table(self, db_type):
        """Remove all data (deletes the cache file and resets slim index)."""
        path = self._cache_path(db_type)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        self._slim[db_type] = self._empty_slim(db_type)
        self._next_id[db_type] = 1
        self._dirty[db_type] = False

    def insert_batch(self, db_type, items):
        """Append a small batch of items. For bulk import use stream_import."""
        if not items:
            return

        cols = self._columns(db_type)
        slim_cols = self._slim_columns(db_type)
        next_id = self._next_id[db_type]

        records = []
        slim_rows = []
        for item in items:
            rec = self._make_record(db_type, item, next_id)
            records.append(rec)
            slim_rows.append({c: rec.get(c, '') for c in slim_cols})
            next_id += 1

        self._append_records_to_parquet(db_type, records, cols)

        # Update slim index
        if HAS_PANDAS:
            import pandas as pd
            new_slim = pd.DataFrame(slim_rows, columns=slim_cols)
            if 'id' in new_slim.columns:
                new_slim['id'] = new_slim['id'].astype(int)
            existing = self._slim.get(db_type)
            if existing is not None and len(existing) > 0:
                self._slim[db_type] = pd.concat(
                    [existing, new_slim], ignore_index=True)
            else:
                self._slim[db_type] = new_slim

        self._next_id[db_type] = next_id
        self._dirty[db_type] = True

    def flush(self, db_type=None):
        if db_type:
            if self._dirty.get(db_type, False):
                self._save_cache(db_type)
        else:
            for dt in list(self._dirty.keys()):
                if self._dirty[dt]:
                    self._save_cache(dt)

    def reload(self, db_type):
        """Reload slim index from parquet file."""
        self._load_slim(db_type)
        self._dirty[db_type] = False

    # ── Query API (uses slim index for fast counting / filtering) ─────────

    def get_count(self, db_type, filter_text=""):
        df = self._slim.get(db_type)
        if df is None or not HAS_PANDAS or len(df) == 0:
            return 0
        if filter_text:
            ft = filter_text.lower()
            mask = df['name'].str.lower().str.contains(ft, na=False)
            if 'display_title' in df.columns:
                mask |= df['display_title'].str.lower().str.contains(
                    ft, na=False)
            if 'eco' in df.columns:
                mask |= df['eco'].str.lower().str.contains(ft, na=False)
            return int(mask.sum())
        return len(df)

    def get_page(self, db_type, page, page_size, filter_text=""):
        """Return a page of slim records for the list widget.
        Full records (fen, moves, etc.) are fetched on-demand via
        get_items_by_ids().
        """
        df = self._slim.get(db_type)
        if df is None or not HAS_PANDAS or len(df) == 0:
            return []

        if filter_text:
            ft = filter_text.lower()
            mask = df['name'].str.lower().str.contains(ft, na=False)
            if 'display_title' in df.columns:
                mask |= df['display_title'].str.lower().str.contains(
                    ft, na=False)
            if 'eco' in df.columns:
                mask |= df['eco'].str.lower().str.contains(ft, na=False)
            filtered = df[mask]
        else:
            filtered = df

        start = page * page_size
        end = start + page_size
        page_df = filtered.iloc[start:end]

        results = []
        for rec in page_df.to_dict('records'):
            r = dict(rec)
            if 'id' in r:
                r['id'] = int(r['id'])
            if 'difficulty' in r and r.get('difficulty') is not None:
                try:
                    r['difficulty'] = float(r['difficulty'])
                except (ValueError, TypeError):
                    r['difficulty'] = 0.5
            results.append(r)
        return results

    def get_ids_by_filter(self, db_type, filter_text=""):
        """Return all IDs matching the filter."""
        df = self._slim.get(db_type)
        if df is None or not HAS_PANDAS or len(df) == 0:
            return []

        if filter_text:
            ft = filter_text.lower()
            mask = df['name'].str.lower().str.contains(ft, na=False)
            if 'display_title' in df.columns:
                mask |= df['display_title'].str.lower().str.contains(
                    ft, na=False)
            if 'eco' in df.columns:
                mask |= df['eco'].str.lower().str.contains(ft, na=False)
            filtered = df[mask]
        else:
            filtered = df

        return filtered['id'].astype(int).tolist()

    def get_items_by_ids(self, db_type, ids):
        """Load FULL records (fen, moves, pgn, img_raw, etc.) on demand."""
        if not ids:
            return []
        return self._records_from_parquet(db_type, ids)

    def get_chunks_by_ids(self, db_type, ids, chunk_size=500):
        """Yield chunks of full records for batch export."""
        if not ids:
            return
        yield from self._chunks_from_parquet(db_type, ids, chunk_size)


# ═══════════════════════════════════════════════════════════════════════════════
#  Data-load worker thread  —  uses streaming import
# ═══════════════════════════════════════════════════════════════════════════════

class DataLoadWorker(QThread):
    data_ready = Signal(str, int)
    load_error = Signal(str, str)

    def __init__(self, db_type, directory=None, single_file=None):
        super().__init__()
        self.db_type = db_type
        self.directory = directory
        self.single_file = single_file
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            db = DataProvider()
            db.clear_table(self.db_type)
            total_count = 0

            files = self._get_files()
            for f in files:
                if self._abort:
                    break
                try:
                    loader = (load_puzzles if self.db_type == 'puzzles'
                              else load_openings)

                    # Stream each chunk directly to parquet —
                    # only one chunk in RAM at a time
                    chunk_gen = loader(str(f))
                    for chunk_count, running_total in db.stream_import(
                            self.db_type, chunk_gen):
                        if self._abort:
                            break
                        total_count = running_total
                        if chunk_count % 100_000 < 60_000:
                            log(f"  {self.db_type}: {total_count:,} rows"
                                f" (+{chunk_count})", "DATA")

                except Exception as e:
                    log(f"Error loading {f.name}: {e}", "DATA")
                    import traceback
                    traceback.print_exc()
                    self.load_error.emit(
                        self.db_type, f"{f.name}: {e}")

            db.flush(self.db_type)
            log(f"Load complete: {total_count:,} {self.db_type}", "DATA")
            self.data_ready.emit(self.db_type, total_count)

        except Exception as e:
            log(f"Fatal load error ({self.db_type}): {e}", "DATA")
            import traceback
            traceback.print_exc()
            self.load_error.emit(self.db_type, str(e))
            self.data_ready.emit(self.db_type, 0)

    def _get_files(self):
        valid_exts = {'.csv', '.parquet', '.pq', '.duckdb', '.db', '.sqlite'}
        if self.single_file:
            return [Path(self.single_file)]
        directory = self.directory
        if not directory or not os.path.exists(directory):
            if directory:
                os.makedirs(directory, exist_ok=True)
            return []
        return sorted(
            f for f in Path(directory).iterdir()
            if f.suffix.lower() in valid_exts)