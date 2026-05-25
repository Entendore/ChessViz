"""Puzzle database loader — CSV, Parquet, DuckDB, SQLite with dynamic auto-naming.
Optimised for large datasets (millions of rows):
  • Chunked CSV processing keeps peak memory ≈ final data size
  • Pandas vectorized string ops for bulk name generation & move parsing
  • Numba JIT for batch byte-level move counting / UCI validation
  • CuPy GPU for batch difficulty scoring on numeric metadata
  • Thread-safe: zero shared mutable state; safe to call from QThread workers
"""

import csv, sqlite3, re, gc
from pathlib import Path
import numpy as np
from constants import log, HAS_PANDAS, HAS_PYARROW, HAS_DUCKDB, HAS_NUMBA, HAS_CUPY

_CHUNK = 4096
_CSV_PROCESS_CHUNK = 50_000       # rows processed at a time for memory control

# ═══════════════════════════════════════════════════════════════════════════════
#  Numba JIT helpers
# ═══════════════════════════════════════════════════════════════════════════════

if HAS_NUMBA:
    from numba import njit, prange

    @njit(cache=True, nogil=True)
    def _count_moves_nb(data, offsets, lengths):
        n = len(offsets)
        out = np.empty(n, dtype=np.int64)
        comma = np.uint8(44)
        for i in range(n):
            ln = lengths[i]
            if ln == 0:
                out[i] = 0
                continue
            c = 1
            s = offsets[i]
            e = s + ln
            for j in range(s, e):
                if data[j] == comma:
                    c += 1
            out[i] = c
        return out

    @njit(cache=True, nogil=True)
    def _validate_uci_first_nb(data, offsets, lengths):
        n = len(offsets)
        valid = np.ones(n, dtype=np.bool_)
        for i in range(n):
            s = offsets[i]
            ln = lengths[i]
            if ln == 0 or ln < 4:
                valid[i] = False
                continue
            for j in range(4):
                b = int(data[s + j])
                if not ((48 <= b <= 57) or (97 <= b <= 122)):
                    valid[i] = False
                    break
        return valid

    @njit(cache=True, nogil=True)
    def _compute_difficulty_nb(move_counts, has_fen, has_rating, rating_vals):
        n = len(move_counts)
        out = np.empty(n, dtype=np.float64)
        for i in range(n):
            base = min(1.0, max(0.0, float(move_counts[i]) / 8.0))
            fen_b = 0.15 if has_fen[i] else 0.0
            if has_rating[i]:
                rating = min(1.0, max(0.0, rating_vals[i] / 3000.0))
            else:
                rating = 0.5
            out[i] = 0.4 * base + 0.2 * fen_b + 0.4 * rating
        return out

    log("Numba JIT puzzle helpers ready", "PUZZLE")

else:
    def _count_moves_nb(data, offsets, lengths):
        out = np.empty(len(offsets), dtype=np.int64)
        for i in range(len(offsets)):
            if lengths[i] == 0:
                out[i] = 0
            else:
                seg = data[offsets[i]:offsets[i] + lengths[i]].tobytes()
                out[i] = seg.count(b',') + 1
        return out

    def _validate_uci_first_nb(data, offsets, lengths):
        valid = np.ones(len(offsets), dtype=np.bool_)
        for i in range(len(offsets)):
            if lengths[i] < 4:
                valid[i] = lengths[i] > 0
        return valid

    def _compute_difficulty_nb(move_counts, has_fen, has_rating, rating_vals):
        n = len(move_counts)
        out = np.empty(n, dtype=np.float64)
        for i in range(n):
            base = min(1.0, max(0.0, float(move_counts[i]) / 8.0))
            fen_b = 0.15 if has_fen[i] else 0.0
            rating = (min(1.0, max(0.0, rating_vals[i] / 3000.0))
                      if has_rating[i] else 0.5)
            out[i] = 0.4 * base + 0.2 * fen_b + 0.4 * rating
        return out


def _pack_strings(strings):
    encoded = [s.encode('utf-8') if s else b'' for s in strings]
    lengths = np.array([len(e) for e in encoded], dtype=np.int64)
    offsets = np.empty(len(encoded), dtype=np.int64)
    total = 0
    for i in range(len(encoded)):
        offsets[i] = total
        total += lengths[i]
    buf = b''.join(encoded)
    data = np.frombuffer(buf, dtype=np.uint8).copy() if buf else np.empty(0, dtype=np.uint8)
    return data, offsets, lengths


def batch_count_moves(move_strings):
    if not move_strings:
        return np.array([], dtype=np.int64)
    data, offsets, lengths = _pack_strings(move_strings)
    return _count_moves_nb(data, offsets, lengths)


def batch_validate_uci(move_strings):
    if not move_strings:
        return np.array([], dtype=np.bool_)
    data, offsets, lengths = _pack_strings(move_strings)
    return _validate_uci_first_nb(data, offsets, lengths)


# ═══════════════════════════════════════════════════════════════════════════════
#  CuPy GPU helpers
# ═══════════════════════════════════════════════════════════════════════════════

if HAS_CUPY:
    import cupy as _cp

    def gpu_difficulty_scores(move_counts, has_fen, has_rating, rating_vals):
        mc_gpu   = _cp.asarray(move_counts.astype(np.float64))
        hf_gpu   = _cp.asarray(has_fen.astype(np.float64))
        hr_gpu   = _cp.asarray(has_rating.astype(np.float64))
        rv_gpu   = _cp.asarray(rating_vals.astype(np.float64))

        base    = _cp.clip(mc_gpu / 8.0, 0.0, 1.0)
        fen_b   = 0.15 * hf_gpu
        rating  = _cp.where(hr_gpu > 0, _cp.clip(rv_gpu / 3000.0, 0.0, 1.0), 0.5)
        scores  = 0.4 * base + 0.2 * fen_b + 0.4 * rating

        return _cp.asnumpy(scores)

    def gpu_sort_by_difficulty(puzzles, scores):
        idx = _cp.asnumpy(_cp.argsort(_cp.asarray(scores))).tolist()
        return [puzzles[i] for i in idx]

    log("CuPy GPU puzzle helpers ready", "PUZZLE")

else:
    _cp = None

    def gpu_difficulty_scores(move_counts, has_fen, has_rating, rating_vals):
        return _compute_difficulty_nb(move_counts, has_fen, has_rating, rating_vals)

    def gpu_sort_by_difficulty(puzzles, scores):
        idx = np.argsort(scores).tolist()
        return [puzzles[i] for i in idx]


# ═══════════════════════════════════════════════════════════════════════════════
#  File format parsers
# ═══════════════════════════════════════════════════════════════════════════════

def load_puzzles(filepath):
    ext = Path(filepath).suffix.lower()
    log(f"Loading puzzles from {Path(filepath).name} ({ext})…", "PUZZLE")

    if ext == '.csv':
        yield from _load_csv_chunked(filepath)
    elif ext == '.parquet':
        rows = _parse_parquet(filepath)
        for i in range(0, len(rows), 5000):
            yield _process_rows(rows[i:i+5000])
        del rows; gc.collect()
    elif ext == '.duckdb':
        rows = _parse_duckdb(filepath)
        for i in range(0, len(rows), 5000):
            yield _process_rows(rows[i:i+5000])
        del rows; gc.collect()
    elif ext in ('.db', '.sqlite'):
        rows = _parse_sqlite(filepath)
        for i in range(0, len(rows), 5000):
            yield _process_rows(rows[i:i+5000])
        del rows; gc.collect()
    else:
        raise ValueError(f"Unsupported file format: {ext}")

    gc.collect()


def _load_csv_chunked(filepath):
    if HAS_PANDAS:
        import pandas as pd
        for chunk_df in pd.read_csv(filepath, dtype=str, chunksize=_CSV_PROCESS_CHUNK,
                                     encoding='utf-8', on_bad_lines='skip'):
            chunk_df = chunk_df.fillna('')
            rows = chunk_df.to_dict('records')
            yield _process_rows(rows)
            del rows, chunk_df
        gc.collect()
    else:
        rows = _parse_csv_stdlib(filepath)
        for i in range(0, len(rows), _CSV_PROCESS_CHUNK):
            yield _process_rows(rows[i:i + _CSV_PROCESS_CHUNK])
        del rows
        gc.collect()


def _parse_csv_stdlib(filepath):
    rows = []
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    log(f"Parsed {len(rows)} CSV rows (stdlib)", "PUZZLE")
    return rows


def _parse_parquet(filepath):
    if not HAS_PANDAS and not HAS_PYARROW:
        raise ImportError("Parquet requires 'pandas' or 'pyarrow'")
    if HAS_PANDAS:
        import pandas as pd
        df = pd.read_parquet(filepath)
        log(f"Parsed {len(df)} Parquet rows", "PUZZLE")
        return df.where(df.notna(), None).to_dict('records')
    else:
        import pyarrow.parquet as pq
        tbl = pq.read_table(filepath)
        log(f"Parsed {len(tbl)} Parquet rows", "PUZZLE")
        return tbl.to_pandas().where(tbl.to_pandas().notna(), None).to_dict('records')


def _parse_duckdb(filepath):
    if not HAS_DUCKDB:
        raise ImportError("DuckDB requires 'duckdb'")
    import duckdb
    con = duckdb.connect(filepath, read_only=True)
    try:
        tables = con.execute("SHOW TABLES").fetchall()
        if not tables:
            raise ValueError("No tables found in DuckDB database")
        table_name = tables[0][0]
        df = con.execute(f'SELECT * FROM "{table_name}"').fetchdf()
        log(f"Parsed {len(df)} DuckDB rows", "PUZZLE")
        return df.where(df.notna(), None).to_dict('records')
    finally:
        con.close()


def _parse_sqlite(filepath):
    conn = sqlite3.connect(filepath)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        if not tables:
            raise ValueError("No tables found in SQLite database")
        table_name = tables[0][0]
        cursor = conn.execute(f'SELECT * FROM "{table_name}"')
        col_names = [desc[0] for desc in cursor.description]
        rows = [dict(zip(col_names, row)) for row in cursor.fetchall()]
        log(f"Parsed {len(rows)} SQLite rows", "PUZZLE")
        return rows
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  Row processing
# ═══════════════════════════════════════════════════════════════════════════════

def _process_rows(rows):
    if not rows:
        return []
    n = len(rows)

    if HAS_PANDAS and n > 100:
        try:
            return _process_rows_vectorized(rows)
        except Exception as exc:
            log(f"Vectorized path failed ({exc}); falling back to iterative", "PUZZLE")

    return _process_rows_iterative(rows)


def _parse_uci_value(val):
    if isinstance(val, list):
        flat = []
        for item in val:
            if isinstance(item, str):
                flat.extend(item.replace(',', ' ').split())
            elif item is not None:
                s = str(item).strip().replace(',', ' ')
                if s:
                    flat.extend(s.split())
        return flat
    s = str(val).strip().replace(',', ' ')
    if not s:
        return []
    return s.split()


# ═══════════════════════════════════════════════════════════════════════════════
#  Iterative path
# ═══════════════════════════════════════════════════════════════════════════════

def _process_rows_iterative(rows):
    puzzles = []
    for idx, row in enumerate(rows):
        row = {str(k).lower(): (v if v is not None else '') for k, v in row.items()}
        uci_val = row.get('moves', row.get('uci', ''))
        uci_moves = _parse_uci_value(uci_val)
        name = _generate_name(row, uci_moves, idx)
        puzzles.append({
            'name':  name,
            'fen':   str(row.get('fen', '')),
            'moves': uci_moves,
            'desc':  str(row.get('desc', row.get('description', ''))),
        })
    return puzzles


# ═══════════════════════════════════════════════════════════════════════════════
#  Vectorized path
# ═══════════════════════════════════════════════════════════════════════════════

def _process_rows_vectorized(rows):
    import pandas as pd
    df = pd.DataFrame(rows)
    df.columns = df.columns.str.lower().str.strip()
    str_cols = df.select_dtypes(include=['object']).columns
    df[str_cols] = df[str_cols].fillna('')
    n = len(df)

    moves_col = ('moves' if 'moves' in df.columns
                 else 'uci' if 'uci' in df.columns
                 else None)
    moves_series = df[moves_col] if moves_col else pd.Series([''] * n, index=df.index)
    uci_moves_list = moves_series.apply(_parse_uci_value)

    move_strs = moves_series.astype(str).tolist()
    move_counts = batch_count_moves(move_strs)
    uci_valid   = batch_validate_uci(move_strs)
    invalid_n   = int((~uci_valid).sum())
    if invalid_n:
        log(f"Warning: {invalid_n}/{n} puzzles have unusual UCI format", "PUZZLE")

    has_fen = np.array(
        [bool(str(v).strip()) for v in df.get('fen', pd.Series('', index=df.index))],
        dtype=np.bool_)

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
    names = _generate_names_vectorized(df, uci_moves_list, move_counts)

    fen_col  = ('fen' if 'fen' in df.columns else None)
    desc_col = ('desc' if 'desc' in df.columns
                else 'description' if 'description' in df.columns
                else None)
    fens  = df[fen_col].astype(str)  if fen_col  else pd.Series([''] * n, index=df.index)
    descs = df[desc_col].astype(str) if desc_col else pd.Series([''] * n, index=df.index)

    puzzles = []
    for i in range(n):
        puzzles.append({
            'name':       names[i],
            'fen':        fens.iloc[i],
            'moves':      uci_moves_list.iloc[i],
            'desc':       descs.iloc[i],
            'difficulty': float(difficulty[i]),
        })

    return puzzles


# ═══════════════════════════════════════════════════════════════════════════════
#  Name generation
# ═══════════════════════════════════════════════════════════════════════════════

def _rating_category(rating):
    if rating < 800:  return "Beginner"
    if rating < 1200: return "Easy"
    if rating < 1600: return "Medium"
    if rating < 2000: return "Hard"
    return "Expert"


def _generate_name(row, uci_moves, idx):
    number = idx + 1
    attrs = []

    name = str(row.get('name', '')).strip()
    if name and name.lower() not in ('nan', 'none', ''):
        attrs.append(name)

    themes = str(row.get('themes', row.get('theme', ''))).strip()
    if themes and themes.lower() not in ('nan', 'none', ''):
        attrs.append(themes)

    opening = str(row.get('opening',
                 row.get('opening_tags',
                 row.get('openingtags', '')))).strip()
    if opening and opening.lower() not in ('nan', 'none', ''):
        attrs.append(opening)

    for rkey in ('rating', 'elo', 'difficulty', 'score'):
        rval = str(row.get(rkey, '')).strip()
        if rval and rval.lower() not in ('nan', 'none', ''):
            try:
                rv = float(rval)
                attrs.append(f"{_rating_category(rv)} ({int(rv)})")
                break
            except ValueError:
                pass

    if not name:
        white = str(row.get('white', '')).strip()
        black = str(row.get('black', '')).strip()
        if white and black:
            attrs.append(f"{white} vs {black}")

    if not name:
        event = str(row.get('event', '')).strip()
        if event and event.lower() not in ('nan', 'none', ''):
            attrs.append(event)

    eco = str(row.get('eco', '')).strip()
    if eco and eco.lower() not in ('nan', 'none', ''):
        attrs.append(f"ECO {eco}")

    if attrs:
        return f"Puzzle #{number} — {' | '.join(attrs)}"
    return _generate_name_fallback(row, uci_moves, idx)


def _generate_name_fallback(row, uci_moves, idx):
    number = idx + 1
    ignore = frozenset({
        'fen', 'moves', 'uci', 'pgn', 'id', 'name', 'img',
        'desc', 'description', 'white', 'black', 'event',
        'rating', 'difficulty', 'score', 'elo', 'themes', 'theme',
        'opening', 'opening_tags', 'openingtags', 'eco',
    })
    parts = []
    for k, v in row.items():
        val = str(v).strip() if v is not None else ''
        if k not in ignore and val and val.lower() not in ('nan', 'none', ''):
            parts.append(f"{k.title()}: {val}")
            if len(parts) == 2:
                break
    if parts:
        return f"Puzzle #{number} — {' | '.join(parts)}"
    if uci_moves:
        return f"Puzzle #{number} — {uci_moves[0]}…"
    return f"Puzzle #{number}"


def _generate_names_vectorized(df, uci_moves_list, move_counts):
    import pandas as pd
    n = len(df)
    names = np.empty(n, dtype=object)

    def _str_col(col_name):
        s = df.get(col_name, pd.Series('', index=df.index))
        return (s.fillna('').astype(str).str.strip()
                if isinstance(s, pd.Series)
                else pd.Series('', index=df.index))

    name_col    = _str_col('name')
    themes_col  = _str_col('themes')
    if (themes_col == '').all():
        themes_col = _str_col('theme')
    opening_col = _str_col('opening')
    if (opening_col == '').all():
        opening_col = _str_col('opening_tags')
    if (opening_col == '').all():
        opening_col = _str_col('openingtags')
    rating_col  = _str_col('rating')
    eco_col     = _str_col('eco')
    white_col   = _str_col('white')
    black_col   = _str_col('black')
    event_col   = _str_col('event')

    for i in range(n):
        number = i + 1
        attrs = []

        nm = name_col.iloc[i]
        if nm and nm.lower() not in ('nan', 'none', ''):
            attrs.append(nm)

        th = themes_col.iloc[i]
        if th and th.lower() not in ('nan', 'none', ''):
            attrs.append(th)

        op = opening_col.iloc[i]
        if op and op.lower() not in ('nan', 'none', ''):
            attrs.append(op)

        rv = rating_col.iloc[i]
        if rv and rv.lower() not in ('nan', 'none', ''):
            try:
                rvf = float(rv)
                attrs.append(f"{_rating_category(rvf)} ({int(rvf)})")
            except ValueError:
                pass

        if not nm:
            w, b = white_col.iloc[i], black_col.iloc[i]
            if w and b:
                attrs.append(f"{w} vs {b}")

        if not nm:
            ev = event_col.iloc[i]
            if ev and ev.lower() not in ('nan', 'none', ''):
                attrs.append(ev)

        eco = eco_col.iloc[i]
        if eco and eco.lower() not in ('nan', 'none', ''):
            attrs.append(f"ECO {eco}")

        if attrs:
            names[i] = f"Puzzle #{number} — {' | '.join(attrs)}"
        else:
            row_dict = df.iloc[i].to_dict()
            uci_moves = uci_moves_list.iloc[i]
            names[i] = _generate_name_fallback(row_dict, uci_moves, i)

    return names


# ═══════════════════════════════════════════════════════════════════════════════
#  Public utility
# ═══════════════════════════════════════════════════════════════════════════════

def sort_by_difficulty(puzzles, ascending=True):
    if not puzzles:
        return []
    scores = np.array([p.get('difficulty', 0.5) for p in puzzles],
                      dtype=np.float64)
    if HAS_CUPY:
        idx = _cp.asnumpy(_cp.argsort(_cp.asarray(scores))).tolist()
    else:
        idx = np.argsort(scores).tolist()
    if not ascending:
        idx = idx[::-1]
    return [puzzles[i] for i in idx]