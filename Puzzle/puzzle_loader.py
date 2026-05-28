#!/usr/bin/env python3
"""Puzzle file loading, iterative and vectorized processing."""

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
)

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


# ── Iterative processing ───────────────────────────────────────────────────

def _process_rows_iterative(rows):
    puzzles = []
    for idx, row in enumerate(rows):
        row = {str(k).lower(): (v if v is not None else '') for k, v in row.items()}
        uci_moves = _extract_uci_moves(row)
        name = _generate_name(row, uci_moves, idx)
        difficulty = _compute_iterative_difficulty(row, uci_moves)
        puzzles.append({
            'name': name,
            'fen': str(row.get('fen', '')),
            'moves': uci_moves,
            'desc': str(row.get('desc', row.get('description', ''))),
            'difficulty': difficulty,
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
    moves_series = (df[moves_col] if moves_col
                    else pd.Series([''] * n, index=df.index))
    uci_moves_list = moves_series.apply(_parse_uci_value)

    move_strs = moves_series.astype(str).tolist()
    move_counts = batch_count_moves(move_strs)
    uci_valid = batch_validate_uci(move_strs)
    invalid_n = int((~uci_valid).sum())
    if invalid_n:
        log(f"Note: {invalid_n}/{n} rows have non-UCI first token", "PUZZLE")

    has_fen = np.array(
        [bool(str(v).strip()) for v in df.get('fen', pd.Series('', index=df.index))],
        dtype=np.bool_)

    rating_col = None
    for candidate in ('rating', 'difficulty', 'score', 'elo'):
        if candidate in df.columns:
            rating_col = candidate
            break
    if rating_col:
        rating_vals = pd.to_numeric(df[rating_col], errors='coerce').fillna(
            0).values.astype(np.float64)
        has_rating = rating_vals > 0
    else:
        rating_vals = np.zeros(n, dtype=np.float64)
        has_rating = np.zeros(n, dtype=np.bool_)

    difficulty = gpu_difficulty_scores(move_counts, has_fen, has_rating, rating_vals)

    fen_col = 'fen' if 'fen' in df.columns else None
    desc_col = ('desc' if 'desc' in df.columns
                else 'description' if 'description' in df.columns else None)
    fens = (df[fen_col].astype(str) if fen_col
            else pd.Series([''] * n, index=df.index))
    descs = (df[desc_col].astype(str) if desc_col
             else pd.Series([''] * n, index=df.index))

    # Convert SAN → UCI where needed
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

    # Generate names
    def _str_col(col_name):
        s = df.get(col_name, pd.Series('', index=df.index))
        if isinstance(s, pd.Series):
            return s.fillna('').astype(str).str.strip()
        return pd.Series('', index=df.index)

    names = np.empty(n, dtype=object)
    for i in range(n):
        row_dict = df.iloc[i].to_dict()
        uci_m = uci_moves_list.iloc[i]
        names[i] = _generate_name(row_dict, uci_m, i)

    puzzles = []
    for i in range(n):
        puzzles.append({
            'name': names[i],
            'fen': fens.iloc[i],
            'moves': uci_moves_list.iloc[i],
            'desc': descs.iloc[i],
            'difficulty': float(difficulty[i]),
        })
    return puzzles


# ── Puzzle Loader ───────────────────────────────────────────────────────────

class PuzzleLoader:
    def __init__(self, use_vectorized=True):
        self.puzzles = []
        self.use_vectorized = use_vectorized and HAS_PANDAS

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
        self.puzzles = self._process_rows(rows)
        return self.puzzles

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
        self.puzzles = self._process_rows(rows)
        return self.puzzles

    def load_parquet(self, path):
        if HAS_PANDAS:
            import pandas as pd
            df = pd.read_parquet(path)
            rows = df.to_dict('records')
        elif HAS_PYARROW:
            table = pq.read_table(path)
            rows = table.to_pylist()
        elif HAS_DUCKDB:
            result = duckdb.sql(f"SELECT * FROM '{path}'")
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
        self.puzzles = self._process_rows(rows)
        return self.puzzles

    def _process_rows(self, rows):
        if not rows:
            return []
        if self.use_vectorized and len(rows) > 100:
            try:
                return _process_rows_vectorized(rows)
            except Exception as e:
                log(f"Vectorized failed ({e}), falling back to iterative", "PUZZLE")
        return _process_rows_iterative(rows)