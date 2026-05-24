"""Data manager — handles lazy auto-loading of databases from the local data directory."""

import os
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from constants import log, DATA_DIR
from puzzle_loader import load_puzzles
from openings_loader import load_openings


class LazyLoadWorker(QThread):
    data_ready = Signal(str, list)

    def __init__(self, db_type, directory):
        super().__init__()
        self.db_type = db_type
        self.directory = directory

    def run(self):
        valid_exts = {'.csv', '.parquet', '.duckdb', '.db', '.sqlite'}
        loaded_items = []
        if not os.path.exists(self.directory):
            os.makedirs(self.directory, exist_ok=True)
            self.data_ready.emit(self.db_type, loaded_items)
            return

        for f in Path(self.directory).iterdir():
            if f.is_file() and f.suffix.lower() in valid_exts:
                try:
                    loader = load_puzzles if self.db_type == 'puzzles' else load_openings
                    data = loader(str(f))
                    loaded_items.extend(data)
                    log(f"Loaded {len(data)} {self.db_type} from {f.name}", "DATA")
                except Exception as e:
                    log(f"Error loading {f.name}: {e}", "DATA")
        
        self.data_ready.emit(self.db_type, loaded_items)