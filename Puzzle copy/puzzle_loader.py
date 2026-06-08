#!/usr/bin/env python3
"""Puzzle file loading — iterative, vectorized, lazy, with filtering and pagination."""

import os
import csv
import json
import random

import chess
import numpy as np

from utils import log, HAS_PANDAS, HAS_PYARROW, HAS_DUCKDB
from puzzle_utils import (
    _parse_uci_value, _extract_uci_moves,
    _generate_name, _generate_name_fallback, _rating_category,
    _clean_move_tokens, _detect_move_format, _san_to_uci,
    _compute_iterative_difficulty, batch_count_moves,
    batch_validate_uci, gpu_difficulty_scores,
    _is_lichess_format, _normalize_lichess_row, LICHESS_THEME_LIST,
)
from config import PUZZLES_PER_PAGE, LICHESS_COLUMNS

# ── Sort definitions ────────────────────────────────────────────────────────

SORT_OPTIONS = {
    "rating_desc":      ("Rating ↓",       f'"{LICHESS_COLUMNS["rating"]}" DESC'),
    "rating_asc":       ("Rating ↑",       f'"{LICHESS_COLUMNS["rating"]}" ASC'),
    "popularity_desc":  ("Popularity ↓",   f'"{LICHESS_COLUMNS["popularity"]}" DESC'),
    "nb_plays_desc":    ("Most Played ↓",  f'"{LICHESS_COLUMNS["nb_plays"]}" DESC'),
    "random":           ("Random",         'random()'),
}

SORT_DEFAULT = "rating_desc"

# Map sort key → (column_key_for_pandas, ascending_bool)
_PANDAS_SORT_MAP = {
    "rating_desc":      ("rating", False),
    "rating_asc":       ("rating", True),
    "popularity_desc":  ("popularity", False),
    "nb_plays_desc":    ("nb_plays", False),
    "random":           ("rating", False),  # handled specially
}


# ── Lazy Puzzle Store for Large Parquet ─────────────────────────────────────

class LazyPuzzleStore:
    """Lazy-loading store for large puzzle datasets (e.g., 5M Lichess puzzles).
    Uses DuckDB for efficient SQL-based slicing without loading all into memory."""

    def __init__(self, path):
        self.path = path
        self._total = 0
        self._conn = None
        self._df = None
        self._all_rows = None
        self._use_duckdb = HAS_DUCKDB
        self._columns = []
        self._is_lichess = False
        self._filtered_total = 0
        self._filters = {}
        self._filter_params = []
        self._sort_by = SORT_DEFAULT
        self._init_store()

    def _init_store(self):
        if self._use_duckdb:
            try:
                import duckdb
                self._conn = duckdb.connect()
                self._conn.execute(
                    f"CREATE VIEW puzzles AS SELECT * FROM read_parquet('{self.path}')")
                count_result = self._conn.execute(
                    "SELECT COUNT(*) FROM puzzles").fetchone()
                self._total = count_result[0] if count_result else 0
                desc = self._conn.execute(
                    "SELECT * FROM puzzles LIMIT 0").description
                self._columns = [d[0] for d in desc]
                self._is_lichess = _is_lichess_format(self._columns)
                self._filtered_total = self._total
                log(f"DuckDB lazy store: {self._total} puzzles, "
                    f"lichess={self._is_lichess}", "PUZZLE")
                return
            except Exception as e:
                log(f"DuckDB init failed: {e}, falling back to pandas", "PUZZLE")
                self._use_duckdb = False

        if HAS_PANDAS:
            import pandas as pd
            log(f"Loading parquet with pandas "
                f"(may take a moment for 5M rows)...", "PUZZLE")
            self._df = pd.read_parquet(self.path)
            self._total = len(self._df)
            self._columns = list(self._df.columns)
            self._is_lichess = _is_lichess_format(self._columns)
            self._filtered_total = self._total
            log(f"Pandas lazy store: {self._total} puzzles, "
                f"lichess={self._is_lichess}", "PUZZLE")
        elif HAS_PYARROW:
            import pyarrow.parquet as pq
            table = pq.read_table(self.path)
            if HAS_PANDAS:
                self._df = table.to_pandas()
                self._total = len(self._df)
                self._columns = list(self._df.columns)
            else:
                self._all_rows = table.to_pylist()
                self._total = len(self._all_rows)
                self._columns = (list(self._all_rows[0].keys())
                                 if self._all_rows else [])
            self._is_lichess = _is_lichess_format(self._columns)
            self._filtered_total = self._total
        else:
            raise ImportError(
                "Need duckdb, pandas, or pyarrow for Parquet files")

    @property
    def total(self):
        return self._total

    @property
    def filtered_total(self):
        return self._filtered_total

    @property
    def is_lichess(self):
        return self._is_lichess

    @property
    def sort_by(self):
        return self._sort_by

    @sort_by.setter
    def sort_by(self, value):
        self._sort_by = value if value in SORT_OPTIONS else SORT_DEFAULT

    def set_filters(self, filters):
        self._filters = filters or {}
        self._update_filtered_count()

    def set_sort(self, sort_key):
        self._sort_by = sort_key if sort_key in SORT_OPTIONS else SORT_DEFAULT

    def _update_filtered_count(self):
        if self._use_duckdb:
            where, params = self._build_duckdb_where()
            self._filter_params = params
            if where:
                result = self._conn.execute(
                    f"SELECT COUNT(*) FROM puzzles {where}", params).fetchone()
                self._filtered_total = result[0] if result else 0
            else:
                self._filtered_total = self._total
                self._filter_params = []
        elif self._df is not None:
            mask = self._pandas_mask()
            self._filtered_total = (int(mask.sum())
                                    if mask is not None else self._total)
        else:
            if self._filters:
                self._filtered_total = sum(
                    1 for r in self._all_rows
                    if self._row_matches_filters(r))
            else:
                self._filtered_total = self._total

    def _build_duckdb_where(self):
        """Build WHERE clause with parameterized values to avoid SQL injection."""
        f = self._filters
        conditions = []
        params = []
        if f.get('min_rating') is not None:
            conditions.append(f'"{LICHESS_COLUMNS["rating"]}" >= ?')
            params.append(f["min_rating"])
        if f.get('max_rating') is not None:
            conditions.append(f'"{LICHESS_COLUMNS["rating"]}" <= ?')
            params.append(f["max_rating"])
        if f.get('theme'):
            conditions.append(f'"{LICHESS_COLUMNS["themes"]}" LIKE ?')
            params.append(f'%{f["theme"]}%')
        if f.get('opening'):
            conditions.append(f'"{LICHESS_COLUMNS["opening"]}" ILIKE ?')
            params.append(f'%{f["opening"]}%')
        if f.get('search'):
            conditions.append(
                f'("{LICHESS_COLUMNS["id"]}" LIKE ? '
                f'OR "{LICHESS_COLUMNS["themes"]}" LIKE ? '
                f'OR "{LICHESS_COLUMNS["opening"]}" ILIKE ?)')
            s = f'%{f["search"]}%'
            params.extend([s, s, s])
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        return where, params

    def _pandas_mask(self):
        """Build a boolean mask over the DataFrame matching current filters."""
        import pandas as pd
        f = self._filters
        if not f:
            return None
        mask = pd.Series(True, index=self._df.index)
        if f.get('min_rating') is not None:
            col = LICHESS_COLUMNS['rating']
            if col in self._df.columns:
                mask &= (pd.to_numeric(self._df[col], errors='coerce')
                         >= f['min_rating'])
        if f.get('max_rating') is not None:
            col = LICHESS_COLUMNS['rating']
            if col in self._df.columns:
                mask &= (pd.to_numeric(self._df[col], errors='coerce')
                         <= f['max_rating'])
        if f.get('theme'):
            col = LICHESS_COLUMNS['themes']
            if col in self._df.columns:
                mask &= self._df[col].astype(str).str.contains(
                    f['theme'], case=False, na=False)
        if f.get('opening'):
            col = LICHESS_COLUMNS['opening']
            if col in self._df.columns:
                mask &= self._df[col].astype(str).str.contains(
                    f['opening'], case=False, na=False)
        if f.get('search'):
            search = f['search'].lower()
            combined = pd.Series('', index=self._df.index)
            for col_key in ('id', 'themes', 'opening'):
                col = LICHESS_COLUMNS.get(col_key, col_key)
                if col in self._df.columns:
                    combined = combined + ' ' + self._df[col].astype(str)
            mask &= combined.str.lower().str.contains(search, na=False)
        return mask

    def _row_matches_filters(self, row):
        """Check if a row dict matches current filters (for list-mode fallback)."""
        f = self._filters
        if not f:
            return True
        if f.get('min_rating') is not None or f.get('max_rating') is not None:
            try:
                rating = float(row.get('rating', 0) or 0)
            except (ValueError, TypeError):
                rating = 0
            if f.get('min_rating') is not None and rating < f['min_rating']:
                return False
            if f.get('max_rating') is not None and rating > f['max_rating']:
                return False
        if f.get('theme'):
            themes = str(row.get('themes', '')).lower()
            if f['theme'].lower() not in themes:
                return False
        if f.get('opening'):
            opening = str(row.get('opening', '')).lower()
            if f['opening'].lower() not in opening:
                return False
        if f.get('search'):
            search = f['search'].lower()
            searchable = ' '.join([
                str(row.get('id', '')),
                str(row.get('themes', '')),
                str(row.get('opening', '')),
            ]).lower()
            if search not in searchable:
                return False
        return True

    def get_page(self, page=0, page_size=PUZZLES_PER_PAGE):
        """Retrieve a single page of normalized puzzle dicts."""
        offset = page * page_size
        if self._use_duckdb:
            return self._get_page_duckdb(offset, page_size)
        elif self._df is not None:
            return self._get_page_pandas(offset, page_size)
        elif self._all_rows is not None:
            return self._get_page_list(offset, page_size)
        return []

    def get_random_puzzle(self):
        """Get a single random puzzle matching current filters."""
        if self._use_duckdb:
            where, params = self._build_duckdb_where()
            query = f"SELECT * FROM puzzles {where} ORDER BY random() LIMIT 1"
            try:
                rows = self._conn.execute(query, params).fetchall()
                if rows:
                    cols = [d[0] for d in
                            self._conn.execute("SELECT * FROM puzzles LIMIT 0").description]
                    row_dict = dict(zip(cols, rows[0]))
                    if self._is_lichess:
                        return _normalize_lichess_row(row_dict, 0)
                    return self._row_to_puzzle(row_dict, 0)
            except Exception as e:
                log(f"DuckDB random query error: {e}", "PUZZLE")
            return None
        elif self._df is not None:
            mask = self._pandas_mask()
            df = self._df[mask] if mask is not None else self._df
            if len(df) == 0:
                return None
            idx = random.randint(0, len(df) - 1)
            row_dict = df.iloc[idx].to_dict()
            if self._is_lichess:
                return _normalize_lichess_row(row_dict, idx)
            return self._row_to_puzzle(row_dict, idx)
        elif self._all_rows is not None:
            if self._filters:
                filtered = [r for r in self._all_rows
                            if self._row_matches_filters(r)]
            else:
                filtered = self._all_rows
            if not filtered:
                return None
            row = random.choice(filtered)
            idx = self._all_rows.index(row)
            if self._is_lichess:
                return _normalize_lichess_row(row, idx)
            return self._row_to_puzzle(row, idx)
        return None

    def _get_page_duckdb(self, offset, limit):
        where, params = self._build_duckdb_where()
        order_clause = SORT_OPTIONS.get(
            self._sort_by, SORT_OPTIONS[SORT_DEFAULT])[1]
        query = (
            f'SELECT * FROM puzzles {where} '
            f'ORDER BY {order_clause} '
            f'LIMIT {limit} OFFSET {offset}'
        )
        try:
            rows = self._conn.execute(query, params).fetchall()
            cols = [d[0] for d in
                    self._conn.execute(
                        "SELECT * FROM puzzles LIMIT 0").description]
            result = []
            for i, row in enumerate(rows):
                row_dict = dict(zip(cols, row))
                global_idx = offset + i
                if self._is_lichess:
                    result.append(
                        _normalize_lichess_row(row_dict, global_idx))
                else:
                    result.append(
                        self._row_to_puzzle(row_dict, global_idx))
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

        # Sort
        if self._sort_by == "random":
            df = df.sample(frac=1, random_state=None).reset_index(drop=True)
        else:
            sort_col_key, sort_asc = _PANDAS_SORT_MAP.get(
                self._sort_by, _PANDAS_SORT_MAP[SORT_DEFAULT])
            lichess_col = LICHESS_COLUMNS.get(sort_col_key, sort_col_key)
            if lichess_col in df.columns:
                sort_col = lichess_col
            elif sort_col_key in df.columns:
                sort_col = sort_col_key
            else:
                sort_col = None
            if sort_col:
                df = df.sort_values(
                    by=sort_col, ascending=sort_asc,
                    na_position='last').reset_index(drop=True)

        page_df = df.iloc[offset:offset + limit]
        result = []
        for i, (_, row) in enumerate(page_df.iterrows()):
            row_dict = row.to_dict()
            global_idx = offset + i
            if self._is_lichess:
                result.append(
                    _normalize_lichess_row(row_dict, global_idx))
            else:
                result.append(
                    self._row_to_puzzle(row_dict, global_idx))
        return result

    def _get_page_list(self, offset, limit):
        """Page through list-mode data with filtering and sorting applied."""
        if self._filters:
            filtered = [r for r in self._all_rows
                        if self._row_matches_filters(r)]
        else:
            filtered = list(self._all_rows)

        # Sort — BUG FIX: was using reverse=not sort_asc with negated values
        if self._sort_by == "random":
            random.shuffle(filtered)
        else:
            sort_col_key, sort_asc = _PANDAS_SORT_MAP.get(
                self._sort_by, _PANDAS_SORT_MAP[SORT_DEFAULT])

            def _sort_val(row):
                val = row.get(sort_col_key, 0)
                try:
                    return float(val) if val is not None else 0
                except (ValueError, TypeError):
                    return 0

            filtered.sort(key=_sort_val, reverse=not sort_asc)

        page = filtered[offset:offset + limit]
        result = []
        for i, row_dict in enumerate(page):
            global_idx = offset + i
            if self._is_lichess:
                result.append(
                    _normalize_lichess_row(row_dict, global_idx))
            else:
                result.append(
                    self._row_to_puzzle(row_dict, global_idx))
        return result

    def _row_to_puzzle(self, row, idx):
        """Convert a generic row dict to a standardized puzzle dict."""
        row_lower = {str(k).lower(): (v if v is not None else '')
                     for k, v in row.items()}
        uci_moves = _extract_uci_moves(row_lower)
        name = _generate_name(row_lower, uci_moves, idx)
        difficulty = _compute_iterative_difficulty(row_lower, uci_moves)
        return {
            'name': name,
            'fen': str(row_lower.get('fen', '')),
            'moves': uci_moves,
            'desc': str(row_lower.get('desc',
                                       row_lower.get('description', ''))),
            'difficulty': difficulty,
            'setup_count': 0,
        }

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


# ── Iterative processing (small files) ─────────────────────────────────────

def _process_rows_iterative(rows):
    """Process rows one-by-one into puzzle dicts. Used for small files."""
    columns = list(rows[0].keys()) if rows else []
    is_lichess = _is_lichess_format(columns)
    puzzles = []
    for idx, row in enumerate(rows):
        if is_lichess:
            puzzles.append(_normalize_lichess_row(row, idx))
        else:
            row_lower = {str(k).lower(): (v if v is not None else '')
                         for k, v in row.items()}
            uci_moves = _extract_uci_moves(row_lower)
            name = _generate_name(row_lower, uci_moves, idx)
            difficulty = _compute_iterative_difficulty(row_lower, uci_moves)
            puzzles.append({
                'name': name,
                'fen': str(row_lower.get('fen', '')),
                'moves': uci_moves,
                'desc': str(row_lower.get('desc',
                                           row_lower.get('description', ''))),
                'difficulty': difficulty,
                'setup_count': 0,
            })
    return puzzles


# ── Vectorized processing ──────────────────────────────────────────────────

def _process_rows_vectorized(rows):
    """Process rows using pandas vectorized operations. Used for larger files."""
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
    moves_series = (df[moves_col] if moves_col
                    else pd.Series([''] * n, index=df.index))
    uci_moves_list = moves_series.apply(_parse_uci_value)

    move_strs = moves_series.astype(str).tolist()
    move_counts = batch_count_moves(move_strs)
    uci_valid = batch_validate_uci(move_strs)

    has_fen = np.array([bool(str(v).strip())
                        for v in df.get('fen',
                                        pd.Series('', index=df.index))],
                       dtype=np.bool_)
    rating_col = None
    for candidate in ('rating', 'difficulty', 'score', 'elo'):
        if candidate in df.columns:
            rating_col = candidate
            break
    if rating_col:
        rating_vals = (pd.to_numeric(df[rating_col], errors='coerce')
                       .fillna(0).values.astype(np.float64))
        has_rating = rating_vals > 0
    else:
        rating_vals = np.zeros(n, dtype=np.float64)
        has_rating = np.zeros(n, dtype=np.bool_)

    difficulty = gpu_difficulty_scores(
        move_counts, has_fen, has_rating, rating_vals)
    is_lichess = _is_lichess_format(df.columns.tolist())
    setup_count = 1 if is_lichess else 0

    fen_col = 'fen' if 'fen' in df.columns else None
    fens = (df[fen_col].astype(str) if fen_col
            else pd.Series([''] * n, index=df.index))

    desc_col = ('themes' if 'themes' in df.columns else
                'desc' if 'desc' in df.columns else
                'description' if 'description' in df.columns else None)
    descs = (df[desc_col].astype(str) if desc_col
             else pd.Series([''] * n, index=df.index))

    for i in range(n):
        raw_tokens = _clean_move_tokens(uci_moves_list.iloc[i])
        fmt = _detect_move_format(raw_tokens)
        if fmt == 'san' and raw_tokens:
            fen = fens.iloc[i] if fen_col else ''
            converted = _san_to_uci(raw_tokens, fen)
            if converted:
                uci_moves_list.iloc[i] = converted
            else:
                uci_moves_list.iloc[i] = raw_tokens
        else:
            uci_moves_list.iloc[i] = raw_tokens

    puzzles = []
    for i in range(n):
        row_dict = df.iloc[i].to_dict()
        name = _generate_name(row_dict, uci_moves_list.iloc[i], i)
        puzzles.append({
            'name': name,
            'fen': fens.iloc[i],
            'moves': uci_moves_list.iloc[i],
            'desc': descs.iloc[i],
            'difficulty': float(difficulty[i]),
            'setup_count': setup_count,
        })
    return puzzles


# ── Puzzle Loader (with filtering + pagination) ────────────────────────────

class PuzzleLoader:
    """High-level puzzle loading interface with filtering, sorting, pagination.

    For large Parquet files (>50 MB), delegates to LazyPuzzleStore which uses
    DuckDB SQL for efficient slicing. For smaller files, loads everything into
    memory and applies filters in-process.
    """

    def __init__(self, use_vectorized=True):
        self.puzzles = []
        self._all_puzzles = []
        self.use_vectorized = use_vectorized and HAS_PANDAS
        self.lazy_store = None

        self._filters = {}
        self._filtered_indices = None
        self._page = 0
        self._page_size = PUZZLES_PER_PAGE
        self._sort_by = SORT_DEFAULT

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def total_count(self):
        if self.lazy_store:
            return self.lazy_store.total
        return len(self._all_puzzles)

    @property
    def filtered_count(self):
        if self.lazy_store:
            return self.lazy_store.filtered_total
        if self._filtered_indices is not None:
            return len(self._filtered_indices)
        return len(self._all_puzzles)

    @property
    def current_page(self):
        return self._page

    @property
    def total_pages(self):
        total = self.filtered_count
        return max(1, (total + self._page_size - 1) // self._page_size)

    @property
    def page_size(self):
        return self._page_size

    @page_size.setter
    def page_size(self, value):
        self._page_size = max(10, min(1000, int(value)))
        self._page = 0
        self.refresh_page()

    @property
    def sort_by(self):
        return self._sort_by

    @sort_by.setter
    def sort_by(self, value):
        self._sort_by = value if value in SORT_OPTIONS else SORT_DEFAULT
        if self.lazy_store:
            self.lazy_store.set_sort(self._sort_by)
        self._page = 0
        self.refresh_page()

    @property
    def has_puzzles(self):
        return len(self._all_puzzles) > 0 or self.lazy_store is not None

    @property
    def filters(self):
        return dict(self._filters)

    # ── Filtering ───────────────────────────────────────────────────────

    def set_filters(self, filters):
        self._filters = filters or {}
        self._page = 0
        if self.lazy_store:
            self.lazy_store.set_filters(self._filters)
        else:
            self._apply_memory_filters()
        self.refresh_page()

    def clear_filters(self):
        self._filters = {}
        self._filtered_indices = None
        self._page = 0
        if self.lazy_store:
            self.lazy_store.set_filters({})
        self.refresh_page()

    def _apply_memory_filters(self):
        if not self._filters:
            self._filtered_indices = None
            return

        indices = []
        f = self._filters
        min_rating = f.get('min_rating')
        max_rating = f.get('max_rating')
        theme = f.get('theme', '').lower()
        opening = f.get('opening', '').lower()
        search = f.get('search', '').lower()

        for i, p in enumerate(self._all_puzzles):
            if min_rating is not None or max_rating is not None:
                try:
                    rating = float(p.get('rating', 0) or 0)
                except (ValueError, TypeError):
                    rating = 0
                if min_rating is not None and rating < min_rating:
                    continue
                if max_rating is not None and rating > max_rating:
                    continue
            if theme:
                p_themes = str(p.get('themes',
                                     p.get('desc', ''))).lower()
                if theme not in p_themes:
                    continue
            if opening:
                p_opening = str(p.get('opening', '')).lower()
                if opening not in p_opening:
                    continue
            if search:
                searchable = ' '.join([
                    str(p.get('name', '')),
                    str(p.get('themes', p.get('desc', ''))),
                    str(p.get('opening', '')),
                    str(p.get('id', '')),
                ]).lower()
                if search not in searchable:
                    continue
            indices.append(i)

        self._filtered_indices = indices

    # ── Random puzzle ───────────────────────────────────────────────────

    def get_random_puzzle(self):
        """Get a random puzzle matching current filters."""
        if self.lazy_store:
            return self.lazy_store.get_random_puzzle()

        if self._filtered_indices is not None:
            if not self._filtered_indices:
                return None
            idx = random.choice(self._filtered_indices)
            return self._all_puzzles[idx]

        if not self._all_puzzles:
            return None
        idx = random.randint(0, len(self._all_puzzles) - 1)
        return self._all_puzzles[idx]

    def get_puzzle_by_id(self, puzzle_id):
        """Find a puzzle by its ID. Returns the puzzle dict or None."""
        pid = str(puzzle_id)
        # Search in current page first
        for p in self.puzzles:
            if str(p.get('id', '')) == pid:
                return p
        # Search all puzzles (only works for non-lazy mode)
        if not self.lazy_store:
            for p in self._all_puzzles:
                if str(p.get('id', '')) == pid:
                    return p
        return None

    # ── Pagination ──────────────────────────────────────────────────────

    def go_to_page(self, page):
        page = max(0, min(page, self.total_pages - 1))
        if page != self._page:
            self._page = page
            self.refresh_page()
            return True
        return False

    def next_page(self):
        if self._page < self.total_pages - 1:
            self._page += 1
            self.refresh_page()
            return True
        return False

    def prev_page(self):
        if self._page > 0:
            self._page -= 1
            self.refresh_page()
            return True
        return False

    def first_page(self):
        return self.go_to_page(0)

    def last_page(self):
        return self.go_to_page(self.total_pages - 1)

    def refresh_page(self):
        """Re-fetch the current page of puzzles into self.puzzles."""
        if self.lazy_store:
            self.puzzles = self.lazy_store.get_page(
                self._page, self._page_size)
            return

        if self._filtered_indices is not None:
            sorted_indices = self._sort_memory_indices(
                self._filtered_indices)
        else:
            sorted_indices = self._sort_memory_indices(
                list(range(len(self._all_puzzles))))

        start = self._page * self._page_size
        page_indices = sorted_indices[start:start + self._page_size]
        self.puzzles = [self._all_puzzles[i] for i in page_indices]

    def _sort_memory_indices(self, indices):
        """Sort a list of indices into _all_puzzles by the current sort key."""
        if not indices:
            return indices

        if self._sort_by == "random":
            result = list(indices)
            random.shuffle(result)
            return result

        sort_col_key, sort_asc = _PANDAS_SORT_MAP.get(
            self._sort_by, _PANDAS_SORT_MAP[SORT_DEFAULT])

        def get_sort_value(idx):
            p = self._all_puzzles[idx]
            val = p.get(sort_col_key, 0)
            try:
                return float(val) if val is not None else 0
            except (ValueError, TypeError):
                return 0

        return sorted(indices, key=get_sort_value, reverse=not sort_asc)

    # ── Internal storage ────────────────────────────────────────────────

    def _store_all_puzzles(self, puzzles):
        self._all_puzzles = puzzles
        self._filtered_indices = None
        self._page = 0
        self._filters = {}
        self._sort_by = SORT_DEFAULT
        self.refresh_page()

    # ── File loading ────────────────────────────────────────────────────

    def load_file(self, path):
        from pathlib import Path
        path = Path(path)
        ext = path.suffix.lower()
        if ext == '.csv':
            return self.load_csv(str(path))
        elif ext == '.json':
            return self.load_json(str(path))
        elif ext in ('.parquet', '.pq'):
            return self.load_parquet(str(path))
        elif ext == '.pgn':
            return self.load_pgn(str(path))
        elif ext in ('.tsv', '.txt'):
            return self.load_csv(str(path), delimiter='\t')
        else:
            try:
                return self.load_csv(str(path))
            except Exception:
                return self.load_json(str(path))

    def load_csv(self, path, delimiter=','):
        rows = []
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                rows.append(row)
        all_puzzles = self._process_rows(rows)
        self._store_all_puzzles(all_puzzles)
        return all_puzzles

    def load_json(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            for key in ('puzzles', 'data', 'results'):
                if key in data and isinstance(data[key], list):
                    rows = data[key]
                    break
            else:
                rows = [data]
        else:
            rows = []
        all_puzzles = self._process_rows(rows)
        self._store_all_puzzles(all_puzzles)
        return all_puzzles

    def load_parquet(self, path):
        file_size = os.path.getsize(path)
        if file_size > 50 * 1024 * 1024:
            log(f"Large parquet detected ({file_size / 1024 / 1024:.0f} MB), "
                f"using lazy loading", "PUZZLE")
            if self.lazy_store:
                self.lazy_store.close()
            self._all_puzzles = []
            self.lazy_store = LazyPuzzleStore(path)
            self.lazy_store.set_sort(self._sort_by)
            self._page = 0
            self.refresh_page()
            return self.puzzles

        if HAS_PANDAS:
            import pandas as pd
            df = pd.read_parquet(path)
            rows = df.to_dict('records')
        elif HAS_PYARROW:
            import pyarrow.parquet as pq
            table = pq.read_table(path)
            rows = table.to_pylist()
        elif HAS_DUCKDB:
            import duckdb
            result = duckdb.sql(
                f"SELECT * FROM read_parquet('{path}')")
            cols = [d[0] for d in result.description]
            rows = [dict(zip(cols, r)) for r in result.fetchall()]
        else:
            raise ImportError(
                "Need pandas, pyarrow, or duckdb for Parquet")
        all_puzzles = self._process_rows(rows)
        self._store_all_puzzles(all_puzzles)
        return all_puzzles

    def load_pgn(self, path):
        rows = []
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            while True:
                game = chess.pgn.read_game(f)
                if game is None:
                    break
                moves = [m.uci() for m in game.mainline_moves()]
                headers = dict(game.headers)
                row = {
                    'fen': headers.get('FEN', ''),
                    'moves': ' '.join(moves),
                    'name': headers.get('Event', ''),
                    'white': headers.get('White', ''),
                    'black': headers.get('Black', ''),
                    'event': headers.get('Event', ''),
                    'eco': headers.get('ECO', ''),
                    'opening': headers.get('Opening', ''),
                }
                rows.append(row)
        all_puzzles = self._process_rows(rows)
        self._store_all_puzzles(all_puzzles)
        return all_puzzles

    def _process_rows(self, rows):
        if not rows:
            return []
        if self.use_vectorized and len(rows) > 100:
            try:
                return _process_rows_vectorized(rows)
            except Exception as e:
                log(f"Vectorized failed ({e}), falling back to iterative",
                    "PUZZLE")
        return _process_rows_iterative(rows)

    def close(self):
        if self.lazy_store:
            self.lazy_store.close()
            self.lazy_store = None