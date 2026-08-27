"""
data_provider.py — Parquet-backed data manager for chess openings.
"""

import os, json, shutil
from config import DATA_DIR, DB_OPENINGS_PATH, HAS_PANDAS, HAS_PYARROW, HAS_DUCKDB, log


class DataProvider:
    _OPENING_COLS = ['id', 'name', 'eco', 'img_raw', 'pgn',
                     'uci_moves', 'epd', 'display_title']
    _SLIM_OPENING_COLS = ['id', 'name', 'eco', 'display_title']
    _LIST_COLS = {'uci_moves'}

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._slim = {}; self._next_id = {}; self._dirty = {}
        self._load_slim('openings'); self._dirty['openings'] = False

    def _columns(self, db_type):      return self._OPENING_COLS
    def _slim_columns(self, db_type): return self._SLIM_OPENING_COLS
    def _cache_path(self, db_type):   return DB_OPENINGS_PATH

    @staticmethod
    def _parquet_columns(path):
        try:
            if HAS_PYARROW:
                import pyarrow.parquet as pq
                return [f.name for f in pq.read_schema(path)]
        except Exception: pass
        try:
            if HAS_PANDAS:
                import pandas as pd
                return list(pd.read_parquet(path, columns=None).head(0).columns)
        except Exception: pass
        return []

    def _empty_slim(self, db_type):
        if HAS_PANDAS:
            import pandas as pd
            return pd.DataFrame(columns=self._slim_columns(db_type))
        return []

    def _load_slim(self, db_type):
        path = self._cache_path(db_type); slim_cols = self._slim_columns(db_type)
        if not os.path.exists(path):
            self._slim[db_type] = self._empty_slim(db_type)
            self._next_id[db_type] = 1; return
        if not HAS_PANDAS and not HAS_PYARROW:
            self._slim[db_type] = self._empty_slim(db_type)
            self._next_id[db_type] = 1; return
        try:
            available = self._parquet_columns(path)
            read_cols = [c for c in slim_cols if c in available] if available else slim_cols
            if not read_cols:
                self._slim[db_type] = self._empty_slim(db_type)
                self._next_id[db_type] = 1; return
            df = None
            try:
                if HAS_PANDAS:
                    import pandas as pd; df = pd.read_parquet(path, columns=read_cols)
                elif HAS_PYARROW:
                    import pyarrow.parquet as pq
                    df = pq.read_table(path, columns=read_cols).to_pandas()
            except Exception: df = None
            if df is None:
                try:
                    if HAS_PANDAS:
                        import pandas as pd; df = pd.read_parquet(path)
                    elif HAS_PYARROW:
                        import pyarrow.parquet as pq
                        df = pq.read_table(path).to_pandas()
                except Exception:
                    self._slim[db_type] = self._empty_slim(db_type)
                    self._next_id[db_type] = 1; return
            for c in slim_cols:
                if c not in df.columns:
                    df[c] = 0 if c == 'id' else ''
            df = df[slim_cols]
            if 'id' in df.columns: df['id'] = df['id'].astype(int)
            self._slim[db_type] = df
            self._next_id[db_type] = (int(df['id'].max()) + 1 if len(df) > 0 else 1)
        except Exception as e:
            log(f"Error loading {db_type} slim: {e}", "DATA")
            self._slim[db_type] = self._empty_slim(db_type)
            self._next_id[db_type] = 1

    def _deserialize_record(self, rec):
        for col in self._LIST_COLS:
            if col in rec and isinstance(rec[col], str):
                try: rec[col] = json.loads(rec[col])
                except Exception: pass
        if 'id' in rec: rec['id'] = int(rec['id'])
        for key in list(rec.keys()):
            if rec[key] is None: rec[key] = 0 if key == 'id' else ''
        return rec

    def _records_from_parquet(self, db_type, ids=None):
        path = self._cache_path(db_type)
        if not os.path.exists(path): return []
        id_set = set(ids) if ids is not None else None; results = []
        try:
            if HAS_PYARROW:
                import pyarrow.parquet as pq; pf = pq.ParquetFile(path)
                for batch in pf.iter_batches(batch_size=100_000):
                    df = batch.to_pandas()
                    if id_set is not None:
                        df = df[df['id'].isin(id_set)]
                        id_set -= set(df['id'].tolist())
                    for rec in df.to_dict('records'):
                        results.append(self._deserialize_record(rec))
                    del df, batch
                    if id_set is not None and not id_set: break
            elif HAS_PANDAS:
                import pandas as pd; df = pd.read_parquet(path)
                if id_set is not None: df = df[df['id'].isin(id_set)]
                for rec in df.to_dict('records'):
                    results.append(self._deserialize_record(rec))
                del df
        except Exception as e:
            log(f"Error reading {db_type} records: {e}", "DATA")
        return results

    def _make_record(self, db_type, item, next_id):
        return {'id': next_id, 'name': str(item.get('name', '')),
                'eco': str(item.get('eco', '')),
                'img_raw': str(item.get('img_raw', '')),
                'pgn': str(item.get('pgn', '')),
                'uci_moves': item.get('uci_moves', []),
                'epd': str(item.get('epd', '')),
                'display_title': str(item.get('display_title', item.get('name', '')))}

    def _serialize_record_for_parquet(self, rec, cols):
        sr = dict(rec)
        for col in self._LIST_COLS:
            if col in sr and isinstance(sr[col], list):
                sr[col] = json.dumps(sr[col], default=str)
        if 'id' in sr: sr['id'] = int(sr['id'])
        for col in cols:
            if col not in sr: sr[col] = ''
        return sr

    def _records_to_dataframe(self, records, cols):
        import pandas as pd
        if not records: return pd.DataFrame(columns=cols)
        df = pd.DataFrame(records, columns=cols)
        if 'id' in df.columns: df['id'] = df['id'].astype(int)
        return df

    def stream_import(self, db_type, chunk_generator):
        cols = self._columns(db_type); path = self._cache_path(db_type)
        if HAS_PYARROW:
            yield from self._stream_import_pyarrow(db_type, chunk_generator, cols, path, self._next_id[db_type])
        elif HAS_PANDAS:
            yield from self._stream_import_pandas(db_type, chunk_generator, cols, path, self._next_id[db_type])
        else:
            raise ImportError("Need pandas or pyarrow for parquet I/O")
        self._load_slim(db_type); self._dirty[db_type] = False

    def _stream_import_pyarrow(self, db_type, chunk_generator, cols, path, next_id):
        import pyarrow as pa; import pyarrow.parquet as pq
        writer = None; total_count = 0; schema = None
        try:
            for chunk in chunk_generator:
                if not chunk: continue
                records = [self._serialize_record_for_parquet(
                    self._make_record(db_type, item, next_id + i), cols)
                    for i, item in enumerate(chunk)]
                next_id += len(chunk)
                chunk_df = self._records_to_dataframe(records, cols)
                table = pa.Table.from_pandas(chunk_df, preserve_index=False)
                if writer is None:
                    schema = table.schema; writer = pq.ParquetWriter(path, schema)
                else:
                    if table.schema != schema: table = table.cast(schema)
                writer.write_table(table); total_count += len(chunk)
                del records, chunk_df, table; yield len(chunk), total_count
        finally:
            if writer is not None: writer.close()
        self._next_id[db_type] = next_id

    def _stream_import_pandas(self, db_type, chunk_generator, cols, path, next_id):
        import pandas as pd
        temp_dir = path + '.parts'; os.makedirs(temp_dir, exist_ok=True)
        temp_files = []; total_count = 0
        try:
            for chunk_idx, chunk in enumerate(chunk_generator):
                if not chunk: continue
                records = [self._serialize_record_for_parquet(
                    self._make_record(db_type, item, next_id + i), cols)
                    for i, item in enumerate(chunk)]
                next_id += len(chunk)
                chunk_df = self._records_to_dataframe(records, cols)
                temp_path = os.path.join(temp_dir, f'part_{chunk_idx:06d}.parquet')
                chunk_df.to_parquet(temp_path, index=False)
                temp_files.append(temp_path); total_count += len(chunk)
                del records, chunk_df; yield len(chunk), total_count
            if temp_files:
                dfs = [pd.read_parquet(tf) for tf in temp_files]
                combined = pd.concat(dfs, ignore_index=True)
                combined.to_parquet(path, index=False); del dfs, combined
            else:
                pd.DataFrame(columns=cols).to_parquet(path, index=False)
        finally:
            for f in temp_files:
                try: os.remove(f)
                except OSError: pass
            try: shutil.rmtree(temp_dir, ignore_errors=True)
            except OSError: pass
        self._next_id[db_type] = next_id

    def _append_records_to_parquet(self, db_type, records, cols):
        save_records = [self._serialize_record_for_parquet(rec, cols) for rec in records]
        path = self._cache_path(db_type)
        if HAS_PANDAS:
            import pandas as pd
            new_df = self._records_to_dataframe(save_records, cols)
            if not os.path.exists(path): new_df.to_parquet(path, index=False)
            else:
                existing = pd.read_parquet(path)
                combined = pd.concat([existing, new_df], ignore_index=True)
                combined.to_parquet(path, index=False); del existing, combined
        elif HAS_PYARROW:
            import pyarrow as pa; import pyarrow.parquet as pq
            new_table = pa.Table.from_pandas(self._records_to_dataframe(save_records, cols), preserve_index=False)
            if not os.path.exists(path): pq.write_table(new_table, path)
            else:
                existing = pq.read_table(path)
                combined = pa.concat_tables([existing, new_table])
                pq.write_table(combined, path); del existing, combined
        else:
            raise ImportError("Need pandas or pyarrow for parquet I/O")

    def clear_table(self, db_type):
        path = self._cache_path(db_type)
        if os.path.exists(path):
            try: os.remove(path)
            except OSError: pass
        self._slim[db_type] = self._empty_slim(db_type)
        self._next_id[db_type] = 1; self._dirty[db_type] = False

    def insert_batch(self, db_type, items):
        cols = self._columns(db_type); records = []
        next_id = self._next_id.get(db_type, 1)
        for item in items:
            records.append(self._make_record(db_type, item, next_id)); next_id += 1
        self._append_records_to_parquet(db_type, records, cols)
        self._next_id[db_type] = next_id; self._load_slim(db_type)
        log(f"Inserted {len(records)} records into {db_type}", "DATA")

    @property
    def openings_slim(self):
        return self._slim.get('openings', self._empty_slim('openings'))

    def get_opening(self, opening_id):
        records = self._records_from_parquet('openings', ids=[opening_id])
        return records[0] if records else None

    # ══════════════════════════════════════════════════════════════════════════
    #  SLICED / CHUNKED QUERIES
    # ══════════════════════════════════════════════════════════════════════════

    def get_openings_slice(self, offset=0, limit=200):
        """Return a slice of slim openings as list of dicts."""
        import pandas as pd
        slim = self.openings_slim
        if not isinstance(slim, pd.DataFrame) or len(slim) == 0:
            return []
        return slim.iloc[offset:offset + limit].to_dict('records')

    def get_opening_count(self):
        import pandas as pd
        slim = self.openings_slim
        return len(slim) if isinstance(slim, pd.DataFrame) else 0

    def search_openings(self, query, limit=50):
        import pandas as pd
        slim = self.openings_slim
        if isinstance(slim, pd.DataFrame) and len(slim) > 0:
            mask = (slim['name'].str.contains(query, case=False, na=False) |
                    slim['eco'].str.contains(query, case=False, na=False))
            return slim[mask].head(limit).to_dict('records')
        return []

    def search_openings_sliced(self, query, offset=0, limit=200):
        """Return a slice of search results as list of dicts."""
        import pandas as pd
        slim = self.openings_slim
        if not isinstance(slim, pd.DataFrame) or len(slim) == 0:
            return []
        mask = (slim['name'].str.contains(query, case=False, na=False) |
                slim['eco'].str.contains(query, case=False, na=False))
        return slim[mask].iloc[offset:offset + limit].to_dict('records')

    def search_openings_count(self, query):
        """Return total number of search matches (without fetching all rows)."""
        import pandas as pd
        slim = self.openings_slim
        if not isinstance(slim, pd.DataFrame) or len(slim) == 0:
            return 0
        mask = (slim['name'].str.contains(query, case=False, na=False) |
                slim['eco'].str.contains(query, case=False, na=False))
        return int(mask.sum())


# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT MANIFEST TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

class ExportTracker:
    """JSON-backed manifest tracking which openings have been exported."""

    def __init__(self, path):
        self._path = path
        self._data = {}          # { str(opening_id): { "path": str, "timestamp": str } }
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, 'r', encoding='utf-8') as f:
                    self._data = json.load(f)
            except Exception as e:
                log(f"Error loading export manifest: {e}", "DATA")
                self._data = {}

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        try:
            with open(self._path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log(f"Error saving export manifest: {e}", "DATA")

    def mark_exported(self, opening_id, path):
        from datetime import datetime
        self._data[str(opening_id)] = {
            "path": path,
            "timestamp": datetime.now().isoformat(timespec='seconds')
        }
        self._save()

    def is_exported(self, opening_id):
        return str(opening_id) in self._data

    def get_info(self, opening_id):
        return self._data.get(str(opening_id))

    def get_path(self, opening_id):
        info = self.get_info(opening_id)
        return info['path'] if info else None

    def remove(self, opening_id):
        if str(opening_id) in self._data:
            del self._data[str(opening_id)]
            self._save()

    @property
    def exported_ids(self):
        return set(self._data.keys())