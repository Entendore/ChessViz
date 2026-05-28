#!/usr/bin/env python3
"""Puzzle file loading — iterative, vectorized, and lazy for large datasets."""

import os
import csv
import json

import chess
import numpy as np

from utils import log
from puzzle_utils import (
    HAS_PANDAS, _parse_uci_value, _extract_uci_moves,
    _generate_name, _generate_name_fallback, _rating_category,
    _clean_move_tokens, _detect_move_format, _san_to_uci,
    _compute_iterative_difficulty, batch_count_moves,
    batch_validate_uci, gpu_difficulty_scores,
    _is_lichess_format, _normalize_lichess_row, LICHESS_THEME_LIST,
)
from config import PUZZLES_PER_PAGE, LICHESS_COLUMNS

# ── Local Dependency Check ──────────────────────────────────────────────────

HAS_PYARROW = False
try:
    import pyarrow.parquet as pq
    HAS_PYARROW = True
except ImportError:
    pass

HAS_DUCKDB = False
try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    pass


# ── Lazy Puzzle Store for Large Parquet ─────────────────────────────────────

class LazyPuzzleStore:
    """Lazy-loading store for large puzzle datasets (e.g., 5M Lichess puzzles).
    Uses DuckDB for efficient SQL-based slicing without loading all into memory."""

    def __init__(self, path):
        self.path = path
        self._total = 0
        self._conn = None
        self._df = None
        self._use_duckdb = HAS_DUCKDB
        self._columns = []
        self._is_lichess = False
        self._filtered_total = 0
        self._filters = {}
        self._init_store()

    def _init_store(self):
        if self._use_duckdb:
            try:
                self._conn = duckdb.connect()
                self._conn.execute(f"CREATE VIEW puzzles AS SELECT * FROM read_parquet('{self.path}')")
                count_result = self._conn.execute("SELECT COUNT(*) FROM puzzles").fetchone()
                self._total = count_result[0] if count_result else 0
                desc = self._conn.execute("SELECT * FROM puzzles LIMIT 0").description
                self._columns = [d[0] for d in desc]
                self._is_lichess = _is_lichess_format(self._columns)
                self._filtered_total = self._total
                log(f"DuckDB lazy store: {self._total} puzzles, lichess={self._is_lichess}", "PUZZLE")
                return
            except Exception as e:
                log(f"DuckDB init failed: {e}, falling back to pandas", "PUZZLE")
                self._use_duckdb = False

        if HAS_PANDAS:
            import pandas as pd
            log(f"Loading parquet with pandas (may take a moment for 5M rows)...", "PUZZLE")
            self._df = pd.read_parquet(self.path)
            self._total = len(self._df)
            self._columns = list(self._df.columns)
            self._is_lichess = _is_lichess_format(self._columns)
            self._filtered_total = self._total
            log(f"Pandas lazy store: {self._total} puzzles, lichess={self._is_lichess}", "PUZZLE")
        elif HAS_PYARROW:
            table = pq.read_table(self.path)
            self._df = table.to_pandas() if HAS_PANDAS else None
            if self._df is None:
                self._all_rows = table.to_pylist()
                self._total = len(self._all_rows)
                self._columns = list(self._all_rows[0].keys()) if self._all_rows else []
                self._is_lichess = _is_lichess_format(self._columns)
                self._filtered_total = self._total
                return
            self._total = len(self._df)
            self._columns = list(self._df.columns)
            self._is_lichess = _is_lichess_format(self._columns)
            self._filtered_total = self._total
        else:
            raise ImportError("Need duckdb, pandas, or pyarrow for Parquet files")

    @property
    def total(self):
        return self._total

    @property
    def filtered_total(self):
        return self._filtered_total

    @property
    def is_lichess(self):
        return self._is_lichess

    def set_filters(self, filters):
        self._filters = filters or {}
        self._update_filtered_count()

    def _update_filtered_count(self):
        if self._use_duckdb:
            where = self._build_duckdb_where()
            if where:
                result = self._conn.execute(f"SELECT COUNT(*) FROM puzzles {where}").fetchone()
                self._filtered_total = result[0] if result else 0
            else:
                self._filtered_total = self._total
        elif self._df is not None:
            mask = self._pandas_mask()
            self._filtered_total = int(mask.sum()) if mask is not None else self._total
        else:
            self._filtered_total = self._total

    def _build_duckdb_where(self):
        f = self._filters
        conditions = []
        # Use exact Lichess column mappings for SQL safety
        if f.get('min_rating') is not None:
            conditions.append(f'"{LICHESS_COLUMNS["rating"]}" >= {f["min_rating"]}')
        if f.get('max_rating') is not None:
            conditions.append(f'"{LICHESS_COLUMNS["rating"]}" <= {f["max_rating"]}')
        if f.get('theme'):
            theme = f['theme'].replace("'", "''")
            conditions.append(f'"{LICHESS_COLUMNS["themes"]}" LIKE \'%{theme}%\'')
        if f.get('opening'):
            opening = f['opening'].replace("'", "''")
            conditions.append(f'"{LICHESS_COLUMNS["opening"]}" ILIKE \'%{opening}%\'')
        if f.get('search'):
            search = f['search'].replace("'", "''")
            conditions.append(
                f'("{LICHESS_COLUMNS["id"]}" LIKE \'%{search}%\' '
                f'OR "{LICHESS_COLUMNS["themes"]}" LIKE \'%{search}%\' '
                f'OR "{LICHESS_COLUMNS["opening"]}" ILIKE \'%{search}%\')')
        return "WHERE " + " AND ".join(conditions) if conditions else ""

    def _pandas_mask(self):
        import pandas as pd
        f = self._filters
        if not f: return None
        mask = pd.Series(True, index=self._df.index)
        if f.get('min_rating') is not None:
            col = LICHESS_COLUMNS['rating']
            if col in self._df.columns:
                mask &= pd.to_numeric(self._df[col], errors='coerce') >= f['min_rating']
        if f.get('max_rating') is not None:
            col = LICHESS_COLUMNS['rating']
            if col in self._df.columns:
                mask &= pd.to_numeric(self._df[col], errors='coerce') <= f['max_rating']
        if f.get('theme'):
            col = LICHESS_COLUMNS['themes']
            if col in self._df.columns:
                mask &= self._df[col].astype(str).str.contains(f['theme'], case=False, na=False)
        if f.get('opening'):
            col = LICHESS_COLUMNS['opening']
            if col in self._df.columns:
                mask &= self._df[col].astype(str).str.contains(f['opening'], case=False, na=False)
        return mask

    def get_page(self, page=0, page_size=PUZZLES_PER_PAGE):
        offset = page * page_size
        if self._use_duckdb:
            return self._get_page_duckdb(offset, page_size)
        elif self._df is not None:
            return self._get_page_pandas(offset, page_size)
        elif hasattr(self, '_all_rows'):
            return self._get_page_list(offset, page_size)
        return []

    def _get_page_duckdb(self, offset, limit):
        where = self._build_duckdb_where()
        # Default sort by Rating descending
        query = f'SELECT * FROM puzzles {where} ORDER BY "{LICHESS_COLUMNS["rating"]}" DESC LIMIT {limit} OFFSET {offset}'
        try:
            rows = self._conn.execute(query).fetchall()
            cols = [d[0] for d in self._conn.execute("SELECT * FROM puzzles LIMIT 0").description]
            result = []
            for i, row in enumerate(rows):
                row_dict = dict(zip(cols, row))
                global_idx = offset + i
                if self._is_lichess:
                    result.append(_normalize_lichess_row(row_dict, global_idx))
                else:
                    result.append(self._row_to_puzzle(row_dict, global_idx))
            return result
        except Exception as e:
            log(f"DuckDB query error: {e}", "PUZZLE")
            return []

    def _get_page_pandas(self, offset, limit):
        import pandas as pd
        mask = self._pandas_mask()
        if mask is not None:
            df = self._df[mask].reset_index(drop=True)
        else:
            df = self._df
        # Sort by rating descending
        col = LICHESS_COLUMNS['rating']
        if col in df.columns:
            df = df.sort_values(by=col, ascending=False).reset_index(drop=True)
            
        page_df = df.iloc[offset:offset + limit]
        result = []
        for i, (_, row) in enumerate(page_df.iterrows()):
            row_dict = row.to_dict()
            global_idx = offset + i
            if self._is_lichess:
                result.append(_normalize_lichess_row(row_dict, global_idx))
            else:
                result.append(self._row_to_puzzle(row_dict, global_idx))
        return result

    def _get_page_list(self, offset, limit):
        rows = self._all_rows[offset:offset + limit]
        result = []
        for i, row_dict in enumerate(rows):
            global_idx = offset + i
            if self._is_lichess:
                result.append(_normalize_lichess_row(row_dict, global_idx))
            else:
                result.append(self._row_to_puzzle(row_dict, global_idx))
        return result

    def _row_to_puzzle(self, row, idx):
        row_lower = {str(k).lower(): (v if v is not None else '') for k, v in row.items()}
        uci_moves = _extract_uci_moves(row_lower)
        name = _generate_name(row_lower, uci_moves, idx)
        difficulty = _compute_iterative_difficulty(row_lower, uci_moves)
        return {
            'name': name,
            'fen': str(row_lower.get('fen', '')),
            'moves': uci_moves,
            'desc': str(row_lower.get('desc', row_lower.get('description', ''))),
            'difficulty': difficulty,
            'setup_count': 0,
        }

    def close(self):
        if self._conn:
            try: self._conn.close()
            except Exception: pass
            self._conn = None


# ── Iterative processing (small files) ─────────────────────────────────────

def _process_rows_iterative(rows):
    columns = list(rows[0].keys()) if rows else []
    is_lichess = _is_lichess_format(columns)
    puzzles = []
    for idx, row in enumerate(rows):
        if is_lichess:
            puzzles.append(_normalize_lichess_row(row, idx))
        else:
            row_lower = {str(k).lower(): (v if v is not None else '') for k, v in row.items()}
            uci_moves = _extract_uci_moves(row_lower)
            name = _generate_name(row_lower, uci_moves, idx)
            difficulty = _compute_iterative_difficulty(row_lower, uci_moves)
            puzzles.append({
                'name': name, 'fen': str(row_lower.get('fen', '')),
                'moves': uci_moves, 'desc': str(row_lower.get('desc', row_lower.get('description', ''))),
                'difficulty': difficulty, 'setup_count': 0,
            })
    return puzzles


# ── Vectorized processing ──────────────────────────────────────────────────

def _process_rows_vectorized(rows):
    import pandas as pd
    df = pd.DataFrame(rows)
    df.columns = df.columns.str.lower().str.strip()
    str_cols = df.select_dtypes(include=['object']).columns
    df[str_cols] = df[str_cols].fillna('')
    n = len(df)

    moves_col = None
    for candidate in ('uci', 'moves', 'pgn'):
        if candidate in df.columns:
            moves_col = candidate
            break
    moves_series = (df[moves_col] if moves_col else pd.Series([''] * n, index=df.index))
    uci_moves_list = moves_series.apply(_parse_uci_value)

    move_strs = moves_series.astype(str).tolist()
    move_counts = batch_count_moves(move_strs)
    uci_valid = batch_validate_uci(move_strs)

    has_fen = np.array([bool(str(v).strip()) for v in df.get('fen', pd.Series('', index=df.index))], dtype=np.bool_)
    rating_col = None
    for candidate in ('rating', 'difficulty', 'score', 'elo'):
        if candidate in df.columns:
            rating_col = candidate
            break
    if rating_col:
        rating_vals = pd.to_numeric(df[rating_col], errors='coerce').fillna(0).values.astype(np.float64)
        has_rating = rating_vals > 0
    else:
        rating_vals = np.zeros(n, dtype=np.float64)
        has_rating = np.zeros(n, dtype=np.bool_)

    difficulty = gpu_difficulty_scores(move_counts, has_fen, has_rating, rating_vals)
    is_lichess = _is_lichess_format(df.columns.tolist())
    setup_count = 1 if is_lichess else 0

    fen_col = 'fen' if 'fen' in df.columns else None
    fens = (df[fen_col].astype(str) if fen_col else pd.Series([''] * n, index=df.index))
    
    desc_col = ('themes' if 'themes' in df.columns else 'desc' if 'desc' in df.columns else 'description' if 'description' in df.columns else None)
    descs = (df[desc_col].astype(str) if desc_col else pd.Series([''] * n, index=df.index))

    for i in range(n):
        raw_tokens = _clean_move_tokens(uci_moves_list.iloc[i])
        fmt = _detect_move_format(raw_tokens)
        if fmt == 'san' and raw_tokens:
            fen = fens.iloc[i] if fen_col else ''
            converted = _san_to_uci(raw_tokens, fen)
            if converted: uci_moves_list.iloc[i] = converted
            else: uci_moves_list.iloc[i] = raw_tokens
        else:
            uci_moves_list.iloc[i] = raw_tokens

    puzzles = []
    for i in range(n):
        row_dict = df.iloc[i].to_dict()
        name = _generate_name(row_dict, uci_moves_list.iloc[i], i)
        puzzles.append({
            'name': name, 'fen': fens.iloc[i], 'moves': uci_moves_list.iloc[i],
            'desc': descs.iloc[i], 'difficulty': float(difficulty[i]), 'setup_count': setup_count,
        })
    return puzzles


# ── Puzzle Loader ───────────────────────────────────────────────────────────

class PuzzleLoader:
    def __init__(self, use_vectorized=True):
        self.puzzles = []
        self.use_vectorized = use_vectorized and HAS_PANDAS
        self.lazy_store = None

    def load_file(self, path):
        from pathlib import Path
        path = Path(path)
        ext = path.suffix.lower()
        if ext == '.csv': return self.load_csv(str(path))
        elif ext == '.json': return self.load_json(str(path))
        elif ext in ('.parquet', '.pq'): return self.load_parquet(str(path))
        elif ext == '.pgn': return self.load_pgn(str(path))
        elif ext in ('.tsv', '.txt'): return self.load_csv(str(path), delimiter='\t')
        else:
            try: return self.load_csv(str(path))
            except Exception: return self.load_json(str(path))

    def load_csv(self, path, delimiter=','):
        rows = []
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader: rows.append(row)
        self.puzzles = self._process_rows(rows)
        return self.puzzles

    def load_json(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list): rows = data
        elif isinstance(data, dict):
            for key in ('puzzles', 'data', 'results'):
                if key in data and isinstance(data[key], list):
                    rows = data[key]; break
            else: rows = [data]
        else: rows = []
        self.puzzles = self._process_rows(rows)
        return self.puzzles

    def load_parquet(self, path):
        file_size = os.path.getsize(path)
        if file_size > 50 * 1024 * 1024: # > 50MB triggers lazy load
            log(f"Large parquet detected ({file_size / 1024 / 1024:.0f} MB), using lazy loading", "PUZZLE")
            if self.lazy_store: self.lazy_store.close()
            self.lazy_store = LazyPuzzleStore(path)
            self.puzzles = self.lazy_store.get_page(0)
            return self.puzzles

        if HAS_PANDAS:
            import pandas as pd
            df = pd.read_parquet(path); rows = df.to_dict('records')
        elif HAS_PYARROW:
            table = pq.read_table(path); rows = table.to_pylist()
        elif HAS_DUCKDB:
            result = duckdb.sql(f"SELECT * FROM read_parquet('{path}')")
            cols = [d[0] for d in result.description]
            rows = [dict(zip(cols, r)) for r in result.fetchall()]
        else:
            raise ImportError("Need pandas, pyarrow, or duckdb for Parquet")
        self.puzzles = self._process_rows(rows)
        return self.puzzles

    def load_pgn(self, path):
        rows = []
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            while True:
                game = chess.pgn.read_game(f)
                if game is None: break
                moves = [m.uci() for m in game.mainline_moves()]
                headers = dict(game.headers)
                row = {
                    'fen': headers.get('FEN', ''), 'moves': ' '.join(moves),
                    'name': headers.get('Event', ''), 'white': headers.get('White', ''),
                    'black': headers.get('Black', ''), 'event': headers.get('Event', ''),
                    'eco': headers.get('ECO', ''), 'opening': headers.get('Opening', ''),
                }
                rows.append(row)
        self.puzzles = self._process_rows(rows)
        return self.puzzles

    def _process_rows(self, rows):
        if not rows: return []
        if self.use_vectorized and len(rows) > 100:
            try: return _process_rows_vectorized(rows)
            except Exception as e:
                log(f"Vectorized failed ({e}), falling back to iterative", "PUZZLE")
        return _process_rows_iterative(rows)

    def close(self):
        if self.lazy_store:
            self.lazy_store.close()