"""Shared fixtures, path setup, and QApplication for all tests."""

import sys
import os
import json
import tempfile

import pytest

# ── Add source directory to sys.path ────────────────────────────────────────
SOURCE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SOURCE_DIR not in sys.path:
    sys.path.insert(0, SOURCE_DIR)


# ── Session-scoped QApplication ─────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    """Provide a single QApplication for the entire test session."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


# ── Sample puzzle data fixtures ─────────────────────────────────────────────

@pytest.fixture
def sample_lichess_puzzle():
    """A single Lichess-format puzzle dict."""
    return {
        "PuzzleId": "testPuzzle001",
        "FEN": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "Moves": "e7e5 d2d4 e5d4",
        "Rating": 1500,
        "RatingDeviation": 80,
        "Popularity": 90,
        "NbPlays": 5000,
        "Themes": "opening fork",
        "GameUrl": "https://lichess.org/test",
        "OpeningTags": "Kings Pawn",
    }


@pytest.fixture
def sample_puzzles_csv(tmp_path):
    """Create a small CSV file with Lichess-format puzzle data."""
    csv_content = (
        "PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags\n"
        "puz001,rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1,e7e5 d2d4,1200,50,85,3000,opening,https://lichess.org/1,Sicilian\n"
        "puz002,r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3,d2d4 e5d4 e4e5,900,40,70,1500,mateIn2 fork,https://lichess.org/2,Qh4\n"
        "puz003,rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1,e2e4 e7e5 g1f3,600,30,60,800,endgame,https://lichess.org/3,Italian\n"
        "puz004,8/5k2/8/8/8/8/4K3/4R3 w - - 0 1,e1e7 f7f6 e7f7,2000,100,95,10000,rookEndgame,https://lichess.org/4,,\n"
    )
    path = tmp_path / "test_puzzles.csv"
    path.write_text(csv_content, encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_puzzles_json(tmp_path):
    """Create a small JSON file with puzzle data."""
    data = [
        {
            "id": "json001",
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            "moves": "e7e5",
            "rating": 1100,
            "themes": "opening",
        },
        {
            "id": "json002",
            "fen": "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
            "moves": "d2d4 e5d4",
            "rating": 1400,
            "themes": "fork",
        },
    ]
    path = tmp_path / "test_puzzles.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_pgn(tmp_path):
    """Create a small PGN file."""
    pgn_content = (
        '[Event "Test Game"]\n'
        '[Site "Test"]\n'
        '[Date "2024.01.01"]\n'
        '[White "Player1"]\n'
        '[Black "Player2"]\n'
        '[Result "1-0"]\n'
        '[Opening "Kings Pawn"]\n\n'
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 1-0\n\n"
    )
    path = tmp_path / "test_game.pgn"
    path.write_text(pgn_content, encoding="utf-8")
    return str(path)


@pytest.fixture
def temp_export_dir(tmp_path):
    """Provide a temporary directory for export outputs."""
    d = tmp_path / "exports"
    d.mkdir()
    return str(d)


@pytest.fixture
def fresh_engine():
    """Provide a fresh ChessEngine for each test."""
    from chess_engine import ChessEngine
    return ChessEngine()


@pytest.fixture
def autosave_dir(tmp_path):
    """Provide a temporary autosave directory and patch config."""
    import config
    original_dir = config.AUTOSAVE_DIR
    original_path = config.AUTOSAVE_PATH
    config.AUTOSAVE_DIR = str(tmp_path / ".chess_puzzle_studio")
    config.AUTOSAVE_PATH = str(tmp_path / ".chess_puzzle_studio" / "state.json")
    os.makedirs(config.AUTOSAVE_DIR, exist_ok=True)
    yield config.AUTOSAVE_PATH
    config.AUTOSAVE_DIR = original_dir
    config.AUTOSAVE_PATH = original_path
