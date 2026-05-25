"""Data manager — streams data into SQLite cache without UI freezes."""
import os
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from constants import log, DATA_DIR
from puzzle_loader import load_puzzles
from openings_loader import load_openings
import sqlite3, json, os
from constants import log, DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "cache.sqlite")

class DataProvider:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS puzzles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, fen TEXT, moves TEXT, desc TEXT, 
                difficulty REAL, display_title TEXT
            );
            CREATE TABLE IF NOT EXISTS openings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, eco TEXT, img_raw TEXT, pgn TEXT, 
                uci_moves TEXT, epd TEXT, display_title TEXT
            );
        """)
        self.conn.commit()

    def clear_table(self, db_type):
        self.conn.execute(f"DELETE FROM {db_type}")
        self.conn.commit()

    def insert_batch(self, db_type, items):
        if db_type == 'puzzles':
            cols = "(name, fen, moves, desc, difficulty, display_title)"
            placeholders = "(?, ?, ?, ?, ?, ?)"
            rows = [
                (i.get('name', ''), i.get('fen', ''), json.dumps(i.get('moves', [])),
                 i.get('desc', ''), i.get('difficulty', 0.5), i.get('display_title', i.get('name', '')))
                for i in items
            ]
        else:
            cols = "(name, eco, img_raw, pgn, uci_moves, epd, display_title)"
            placeholders = "(?, ?, ?, ?, ?, ?, ?)"
            rows = [
                (i.get('name', ''), i.get('eco', ''), i.get('img_raw', ''),
                 i.get('pgn', ''), json.dumps(i.get('uci_moves', [])),
                 i.get('epd', ''), i.get('display_title', i.get('name', '')))
                for i in items
            ]

        self.conn.executemany(
            f"INSERT INTO {db_type} {cols} VALUES {placeholders}", rows
        )
        self.conn.commit()

    def get_count(self, db_type, filter_text=""):
        table = db_type
        if filter_text:
            query = f"SELECT COUNT(*) FROM {table} WHERE name LIKE ?"
            cur = self.conn.execute(query, (f'%{filter_text}%',))
        else:
            cur = self.conn.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]

    def get_page(self, db_type, page, page_size, filter_text=""):
        offset = page * page_size
        if filter_text:
            query = f"SELECT * FROM {db_type} WHERE name LIKE ? ORDER BY id LIMIT ? OFFSET ?"
            cur = self.conn.execute(query, (f'%{filter_text}%', page_size, offset))
        else:
            query = f"SELECT * FROM {db_type} ORDER BY id LIMIT ? OFFSET ?"
            cur = self.conn.execute(query, (page_size, offset))

        cols = [desc[0] for desc in cur.description]
        items = []
        for row in cur.fetchall():
            item = dict(zip(cols, row))
            # Deserialize JSON lists
            if 'moves' in item and isinstance(item['moves'], str):
                item['moves'] = json.loads(item['moves'])
            if 'uci_moves' in item and isinstance(item['uci_moves'], str):
                item['uci_moves'] = json.loads(item['uci_moves'])
            items.append(item)
        return items

    def get_ids_by_filter(self, db_type, filter_text=""):
        if filter_text:
            query = f"SELECT id FROM {db_type} WHERE name LIKE ?"
            cur = self.conn.execute(query, (f'%{filter_text}%',))
        else:
            cur = self.conn.execute(f"SELECT id FROM {db_type}")
        return [row[0] for row in cur.fetchall()]

    def get_items_by_ids(self, db_type, ids):
        if not ids:
            return []
        placeholders = ','.join('?' for _ in ids)
        query = f"SELECT * FROM {db_type} WHERE id IN ({placeholders})"
        cur = self.conn.execute(query, ids)

        cols = [desc[0] for desc in cur.description]
        items = []
        for row in cur.fetchall():
            item = dict(zip(cols, row))
            if 'moves' in item and isinstance(item['moves'], str):
                item['moves'] = json.loads(item['moves'])
            if 'uci_moves' in item and isinstance(item['uci_moves'], str):
                item['uci_moves'] = json.loads(item['uci_moves'])
            items.append(item)
        return items

class DataLoadWorker(QThread):
    data_ready = Signal(str, int)       # (db_type, total_count)
    load_error = Signal(str, str)       # (db_type, error_message)

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
                if self._abort: break
                try:
                    loader = load_puzzles if self.db_type == 'puzzles' else load_openings
                    # Loader now yields chunks
                    for chunk in loader(str(f)):
                        if self._abort: break
                        db.insert_batch(self.db_type, chunk)
                        total_count += len(chunk)
                except Exception as e:
                    log(f"Error loading {f.name}: {e}", "DATA")
                    self.load_error.emit(self.db_type, f"{f.name}: {e}")

            self.data_ready.emit(self.db_type, total_count)

        except Exception as e:
            log(f"Fatal load error ({self.db_type}): {e}", "DATA")
            self.load_error.emit(self.db_type, str(e))
            self.data_ready.emit(self.db_type, 0)

    def _get_files(self):
        valid_exts = {'.csv', '.parquet', '.duckdb', '.db', '.sqlite'}
        if self.single_file:
            return [Path(self.single_file)]
        
        directory = self.directory
        if not directory or not os.path.exists(directory):
            if directory: os.makedirs(directory, exist_ok=True)
            return []
            
        return sorted(Path(directory).iterdir())