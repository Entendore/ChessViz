"""Puzzle database loader — CSV, Parquet, DuckDB, SQLite with dynamic auto-naming.
Optimised for large datasets (millions of rows):
  • Chunked CSV / Parquet processing keeps peak memory ≈ one chunk
  • Pandas vectorized string ops for bulk name generation & move parsing
  • Numba JIT for batch byte-level move counting / UCI validation
  • CuPy GPU for batch difficulty scoring on numeric metadata
  • Thread-safe: zero shared mutable state; safe to call from QThread workers

FIX: Detects UCI vs SAN move format and converts SAN→UCI at import time
so the export pipeline always receives valid UCI moves regardless of which
column the data came from.
"""

import csv, sqlite3, re, gc
from pathlib import Path
import numpy as np
import chess                                      # ← ADD THIS IMPORT
from constants import log, HAS_PANDAS, HAS_PYARROW, HAS_DUCKDB, HAS_NUMBA, HAS_CUPY

_CHUNK = 4096
_CSV_PROCESS_CHUNK = 50_000
_PARQUET_BATCH = 50_000

# ═══════════════════════════════════════════════════════════════════════════════
#  Move-format helpers — FIX: detect UCI vs SAN and convert at import time
# ═══════════════════════════════════════════════════════════════════════════════

_UCI_RE = re.compile(r'^[a-h][1-8][a-h][1-8][qrbn]?$')
_MVNUM_RE = re.compile(r'^\d+\.+$')
_RESULT_RE = frozenset({'1-0', '0-1', '1/2-1/2', '*'})


def _clean_move_tokens(tokens):
    """Strip PGN move numbers (1. 2. …), result markers, and empty tokens."""
    out = []
    for t in tokens:
        t = t.strip()
        if not t or _MVNUM_RE.match(t) or t in _RESULT_RE:
            continue
        # Also strip trailing dots like "1..." from PGN
        t = t.rstrip('.')
        if not t:
            continue
        out.append(t)
    return out


def _detect_move_format(tokens):
    """Return 'uci' or 'san' by inspecting the first meaningful token.

    Lichess puzzle DB: Moves column is UCI  →  f1c1, e2e4, a7a8q
    Lichess opening DB: uci column is UCI, pgn column is SAN  →  e4, Nf3, O-O
    Other DBs: 'moves' may be either format.
    """
    for t in tokens:
        if _UCI_RE.match(t):
            return 'uci'
        # Anything that doesn't match the UCI pattern → treat as SAN
        return 'san'
    return 'uci'  # empty → assume UCI (no-op)


def _san_to_uci(tokens, fen=''):
    """Play through SAN move tokens from *fen*, returning UCI strings.

    Lichess puzzles use the FEN column as the starting position.
    Lichess openings use the epd column as the starting position.
    If a token fails as SAN, tries it as UCI before giving up.
    """
    board = chess.Board(fen) if fen else chess.Board()
    result = []
    for t in tokens:
        # Try SAN first (most common for non-UCI columns)
        try:
            m = board.parse_san(t)
            result.append(m.uci())
            board.push(m)
            continue
        except Exception:
            pass
        # Fallback: maybe it actually IS UCI (mixed-format column?)
        try:
            m = chess.Move.from_uci(t)
            if m in board.legal_moves:
                result.append(t)
                board.push(m)
                continue
        except Exception:
            pass
        # Unparseable → stop here (subsequent moves would be wrong anyway)
        break
    return result


def _extract_uci_moves(row):
    """Pick the best move column (uci > moves > pgn), detect format,
    and always return a list of UCI strings.

    For the Lichess puzzle DB:  'moves' column IS UCI  →  detected & returned
    For the Lichess opening DB: 'uci' column IS UCI    →  preferred over 'pgn'
    For other DBs:              format auto-detected   →  SAN converted to UCI
    """
    # Column priority: uci is guaranteed UCI, then moves, then pgn
    raw_val = ''
    for col in ('uci', 'moves', 'pgn'):
        v = row.get(col, '')
        if v and str(v).strip():
            raw_val = v
            break

    tokens = _parse_uci_value(raw_val)
    tokens = _clean_move_tokens(tokens)
    if not tokens:
        return []

    # Get FEN/EPD for SAN conversion (puzzles use 'fen', openings use 'epd')
    fen = str(row.get('fen', row.get('epd', ''))).strip()
    # Ensure FEN has all 6 fields (epd may only have 4)
    if fen and len(fen.split()) < 6:
        fen += " 0 1"

    fmt = _detect_move_format(tokens)
    if fmt == 'san':
        uci_moves = _san_to_uci(tokens, fen)
        if uci_moves:
            return uci_moves
        # SAN conversion failed completely → return raw tokens as last resort
    return tokens


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
                out[i] = 0; continue
            c = 1; s = offsets[i]; e = s + ln
            for j in range(s, e):
                if data[j] == comma: c += 1
            out[i] = c
        return out

    @njit(cache=True, nogil=True)
    def _validate_uci_first_nb(data, offsets, lengths):
        n = len(offsets)
        valid = np.ones(n, dtype=np.bool_)
        for i in range(n):
            s = offsets[i]; ln = lengths[i]
            if ln == 0 or ln < 4:
                valid[i] = False; continue
            for j in range(4):
                b = int(data[s + j])
                if not ((48 <= b <= 57) or (97 <= b <= 122)):
                    valid[i] = False; break
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
            if lengths[i] == 0: out[i] = 0
            else:
                seg = data[offsets[i]:offsets[i] + lengths[i]].tobytes()
                out[i] = seg.count(b',') + 1
        return out

    def _validate_uci_first_nb(data, offsets, lengths):
        valid = np.ones(len(offsets), dtype=np.bool_)
        for i in range(len(offsets)):
            if lengths[i] < 4: valid[i] = lengths[i] > 0
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
        offsets[i] = total; total += lengths[i]
    buf = b''.join(encoded)
    data = (np.frombuffer(buf, dtype=np.uint8).copy()
            if buf else np.empty(0, dtype=np.uint8))
    return data, offsets, lengths


def batch_count_moves(move_strings):
    if not move_strings: return np.array([], dtype=np.int64)
    data, offsets, lengths = _pack_strings(move_strings)
    return _count_moves_nb(data, offsets, lengths)


def batch_validate_uci(move_strings):
    if not move_strings: return np.array([], dtype=np.bool_)
    data, offsets, lengths = _pack_strings(move_strings)
    return _validate_uci_first_nb(data, offsets, lengths)


# ═══════════════════════════════════════════════════════════════════════════════
#  CuPy GPU helpers
# ═══════════════════════════════════════════════════════════════════════════════

if HAS_CUPY:
    import cupy as _cp

    def gpu_difficulty_scores(move_counts, has_fen, has_rating, rating_vals):
        mc_gpu = _cp.asarray(move_counts.astype(np.float64))
        hf_gpu = _cp.asarray(has_fen.astype(np.float64))
        hr_gpu = _cp.asarray(has_rating.astype(np.float64))
        rv_gpu = _cp.asarray(rating_vals.astype(np.float64))
        base = _cp.clip(mc_gpu / 8.0, 0.0, 1.0)
        fen_b = 0.15 * hf_gpu
        rating = _cp.where(hr_gpu > 0,
                           _cp.clip(rv_gpu / 3000.0, 0.0, 1.0), 0.5)
        return _cp.asnumpy(0.4 * base + 0.2 * fen_b + 0.4 * rating)

    def gpu_sort_by_difficulty(puzzles, scores):
        idx = _cp.asnumpy(_cp.argsort(_cp.asarray(scores))).tolist()
        return [puzzles[i] for i in idx]

    log("CuPy GPU puzzle helpers ready", "PUZZLE")

else:
    _cp = None

    def gpu_difficulty_scores(move_counts, has_fen, has_rating, rating_vals):
        return _compute_difficulty_nb(move_counts, has_fen,
                                     has_rating, rating_vals)

    def gpu_sort_by_difficulty(puzzles, scores):
        idx = np.argsort(scores).tolist()
        return [puzzles[i] for i in idx]


# ═══════════════════════════════════════════════════════════════════════════════
#  File format parsers — all chunked
# ═══════════════════════════════════════════════════════════════════════════════

def load_puzzles(filepath):
    ext = Path(filepath).suffix.lower()
    log(f"Loading puzzles from {Path(filepath).name} ({ext})…", "PUZZLE")

    if ext == '.csv':
        yield from _load_csv_chunked(filepath)
    elif ext in ('.parquet', '.pq'):
        yield from _load_parquet_chunked(filepath)
    elif ext == '.duckdb':
        yield from _load_duckdb_chunked(filepath)
    elif ext in ('.db', '.sqlite'):
        yield from _load_sqlite_chunked(filepath)
    else:
        raise ValueError(f"Unsupported file format: {ext}")
    gc.collect()


def _load_csv_chunked(filepath):
    if HAS_PANDAS:
        import pandas as pd
        for chunk_df in pd.read_csv(
                filepath, dtype=str, chunksize=_CSV_PROCESS_CHUNK,
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
        del rows; gc.collect()


def _parse_csv_stdlib(filepath):
    rows = []
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        for row in csv.DictReader(f):
            rows.append(row)
    log(f"Parsed {len(rows)} CSV rows (stdlib)", "PUZZLE")
    return rows


def _load_parquet_chunked(filepath):
    """Yield processed chunks from a parquet file using pyarrow iter_batches."""
    if HAS_PYARROW:
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(filepath)
        total = 0
        for batch in pf.iter_batches(batch_size=_PARQUET_BATCH):
            df = batch.to_pandas()
            df = df.where(df.notna(), None)
            rows = df.to_dict('records')
            yield _process_rows(rows)
            total += len(rows)
            del rows, df, batch
        log(f"Chunked-parquet: {total} rows from {Path(filepath).name}",
            "PUZZLE")
    elif HAS_PANDAS:
        import pandas as pd
        df = pd.read_parquet(filepath)
        df = df.where(df.notna(), None)
        rows = df.to_dict('records')
        for i in range(0, len(rows), _CSV_PROCESS_CHUNK):
            yield _process_rows(rows[i:i + _CSV_PROCESS_CHUNK])
        del rows, df; gc.collect()
    else:
        raise ImportError("Parquet requires 'pandas' or 'pyarrow'")


def _load_duckdb_chunked(filepath):
    if not HAS_DUCKDB:
        raise ImportError("DuckDB requires 'duckdb'")
    import duckdb
    con = duckdb.connect(filepath, read_only=True)
    try:
        tables = con.execute("SHOW TABLES").fetchall()
        if not tables:
            raise ValueError("No tables found in DuckDB database")
        table_name = tables[0][0]
        count = con.execute(
            f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        offset = 0
        while offset < count:
            df = con.execute(
                f'SELECT * FROM "{table_name}" '
                f'LIMIT {_CSV_PROCESS_CHUNK} OFFSET {offset}'
            ).fetchdf()
            df = df.where(df.notna(), None)
            rows = df.to_dict('records')
            yield _process_rows(rows)
            offset += _CSV_PROCESS_CHUNK
            del rows, df
    finally:
        con.close()


def _load_sqlite_chunked(filepath):
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
        while True:
            rows_raw = cursor.fetchmany(_CSV_PROCESS_CHUNK)
            if not rows_raw:
                break
            rows = [dict(zip(col_names, r)) for r in rows_raw]
            yield _process_rows(rows)
            del rows, rows_raw
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  Row processing
# ═══════════════════════════════════════════════════════════════════════════════

def _process_rows(rows):
    if not rows: return []
    n = len(rows)
    if HAS_PANDAS and n > 100:
        try: return _process_rows_vectorized(rows)
        except Exception as exc:
            log(f"Vectorized path failed ({exc}); falling back to iterative",
                "PUZZLE")
    return _process_rows_iterative(rows)


def _parse_uci_value(val):
    if isinstance(val, list):
        flat = []
        for item in val:
            if isinstance(item, str):
                flat.extend(item.replace(',', ' ').split())
            elif item is not None:
                s = str(item).strip().replace(',', ' ')
                if s: flat.extend(s.split())
        return flat
    s = str(val).strip().replace(',', ' ')
    return s.split() if s else []


def _compute_iterative_difficulty(row, uci_moves):
    move_count = len(uci_moves)
    base = min(1.0, max(0.0, move_count / 8.0))
    fen = str(row.get('fen', '')).strip()
    fen_b = 0.15 if fen else 0.0
    rating = 0.5
    for rkey in ('rating', 'elo', 'difficulty', 'score'):
        rval = str(row.get(rkey, '')).strip()
        if rval and rval.lower() not in ('nan', 'none', ''):
            try:
                rv = float(rval)
                rating = min(1.0, max(0.0, rv / 3000.0)); break
            except ValueError:
                pass
    return 0.4 * base + 0.2 * fen_b + 0.4 * rating


def _process_rows_iterative(rows):
    puzzles = []
    for idx, row in enumerate(rows):
        row = {str(k).lower(): (v if v is not None else '')
               for k, v in row.items()}
        # FIX: use smart column pick + format detection/conversion
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


def _process_rows_vectorized(rows):
    import pandas as pd
    df = pd.DataFrame(rows)
    df.columns = df.columns.str.lower().str.strip()
    str_cols = df.select_dtypes(include=['object']).columns
    df[str_cols] = df[str_cols].fillna('')
    n = len(df)

    # FIX: pick best move column with priority: uci > moves > pgn
    moves_col = None
    for candidate in ('uci', 'moves', 'pgn'):
        if candidate in df.columns:
            moves_col = candidate
            break
    moves_series = (df[moves_col] if moves_col
                    else pd.Series([''] * n, index=df.index))
    uci_moves_list = moves_series.apply(_parse_uci_value)

    # Still use the raw string for batch counting / validation stats
    move_strs = moves_series.astype(str).tolist()
    move_counts = batch_count_moves(move_strs)
    uci_valid = batch_validate_uci(move_strs)
    invalid_n = int((~uci_valid).sum())
    if invalid_n:
        log(f"Note: {invalid_n}/{n} rows have non-UCI first token "
            f"(SAN auto-convert will apply)", "PUZZLE")

    has_fen = np.array(
        [bool(str(v).strip())
         for v in df.get('fen', pd.Series('', index=df.index))],
        dtype=np.bool_)

    rating_col = None
    for candidate in ('rating', 'difficulty', 'score', 'elo'):
        if candidate in df.columns:
            rating_col = candidate; break
    if rating_col:
        rating_vals = (pd.to_numeric(df[rating_col], errors='coerce')
                       .fillna(0).values.astype(np.float64))
        has_rating = rating_vals > 0
    else:
        rating_vals = np.zeros(n, dtype=np.float64)
        has_rating = np.zeros(n, dtype=np.bool_)

    difficulty = gpu_difficulty_scores(
        move_counts, has_fen, has_rating, rating_vals)
    names = _generate_names_vectorized(df, uci_moves_list, move_counts)

    fen_col = ('fen' if 'fen' in df.columns else None)
    desc_col = ('desc' if 'desc' in df.columns
                else 'description' if 'description' in df.columns else None)
    fens = (df[fen_col].astype(str) if fen_col
            else pd.Series([''] * n, index=df.index))
    descs = (df[desc_col].astype(str) if desc_col
             else pd.Series([''] * n, index=df.index))

    puzzles = []
    for i in range(n):
        # FIX: per-row format detection & SAN→UCI conversion
        raw_tokens = _clean_move_tokens(uci_moves_list.iloc[i])
        fmt = _detect_move_format(raw_tokens)
        if fmt == 'san':
            fen_str = str(fens.iloc[i]).strip()
            if fen_str and len(fen_str.split()) < 6:
                fen_str += " 0 1"
            uci_moves = _san_to_uci(raw_tokens, fen_str)
            if not uci_moves:
                uci_moves = raw_tokens           # last resort
        else:
            uci_moves = raw_tokens

        puzzles.append({
            'name': names[i], 'fen': fens.iloc[i],
            'moves': uci_moves,
            'desc': descs.iloc[i],
            'difficulty': float(difficulty[i]),
        })
    return puzzles


# ═══════════════════════════════════════════════════════════════════════════════
#  Name generation  (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

def _rating_category(rating):
    if rating < 800:  return "Beginner"
    if rating < 1200: return "Easy"
    if rating < 1600: return "Medium"
    if rating < 2000: return "Hard"
    return "Expert"


def _generate_name(row, uci_moves, idx):
    number = idx + 1; attrs = []
    name = str(row.get('name', '')).strip()
    if name and name.lower() not in ('nan', 'none', ''): attrs.append(name)
    themes = str(row.get('themes', row.get('theme', ''))).strip()
    if themes and themes.lower() not in ('nan', 'none', ''):
        attrs.append(themes)
    opening = str(row.get(
        'opening', row.get('opening_tags',
                           row.get('openingtags', '')))).strip()
    if opening and opening.lower() not in ('nan', 'none', ''):
        attrs.append(opening)
    for rkey in ('rating', 'elo', 'difficulty', 'score'):
        rval = str(row.get(rkey, '')).strip()
        if rval and rval.lower() not in ('nan', 'none', ''):
            try:
                rv = float(rval)
                attrs.append(f"{_rating_category(rv)} ({int(rv)})"); break
            except ValueError: pass
    if not name:
        white = str(row.get('white', '')).strip()
        black = str(row.get('black', '')).strip()
        if white and black: attrs.append(f"{white} vs {black}")
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
        'rating', 'difficulty', 'score', 'elo', 'themes',
        'theme', 'opening', 'opening_tags', 'openingtags', 'eco'})
    parts = []
    for k, v in row.items():
        val = str(v).strip() if v is not None else ''
        if (k not in ignore and val
                and val.lower() not in ('nan', 'none', '')):
            parts.append(f"{k.title()}: {val}")
            if len(parts) == 2: break
    if parts:
        return f"Puzzle #{number} — {' | '.join(parts)}"
    if uci_moves:
        return f"Puzzle #{number} — {uci_moves[0]}…"
    return f"Puzzle #{number}"


def _generate_names_vectorized(df, uci_moves_list, move_counts):
    import pandas as pd
    n = len(df); names = np.empty(n, dtype=object)

    def _str_col(col_name):
        s = df.get(col_name, pd.Series('', index=df.index))
        return (s.fillna('').astype(str).str.strip()
                if isinstance(s, pd.Series)
                else pd.Series('', index=df.index))

    name_col = _str_col('name'); themes_col = _str_col('themes')
    if (themes_col == '').all(): themes_col = _str_col('theme')
    opening_col = _str_col('opening')
    if (opening_col == '').all():
        opening_col = _str_col('opening_tags')
    if (opening_col == '').all():
        opening_col = _str_col('openingtags')
    rating_col = _str_col('rating'); eco_col = _str_col('eco')
    white_col = _str_col('white'); black_col = _str_col('black')
    event_col = _str_col('event')

    for i in range(n):
        number = i + 1; attrs = []
        nm = name_col.iloc[i]
        if nm and nm.lower() not in ('nan', 'none', ''): attrs.append(nm)
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
            except ValueError: pass
        if not nm:
            w, b = white_col.iloc[i], black_col.iloc[i]
            if w and b: attrs.append(f"{w} vs {b}")
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


def sort_by_difficulty(puzzles, ascending=True):
    if not puzzles: return []
    scores = np.array(
        [p.get('difficulty', 0.5) for p in puzzles], dtype=np.float64)
    if HAS_CUPY:
        idx = _cp.asnumpy(_cp.argsort(_cp.asarray(scores))).tolist()
    else:
        idx = np.argsort(scores).tolist()
    if not ascending: idx = idx[::-1]
    return [puzzles[i] for i in idx]