"""Chess Video Maker Pro — Constants, Themes, and Configuration"""
import os
import shutil
import platform
import logging
import chess
from PySide6.QtGui import QColor

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

logger = logging.getLogger("ChessVideoMaker.Constants")

PIECE_SYM = {
    (chess.PAWN, chess.WHITE): "♙", (chess.PAWN, chess.BLACK): "♟",
    (chess.KNIGHT, chess.WHITE): "♘", (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.WHITE): "♗", (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK, chess.WHITE): "♖", (chess.ROOK, chess.BLACK): "♜",
    (chess.QUEEN, chess.WHITE): "♕", (chess.QUEEN, chess.BLACK): "♛",
    (chess.KING, chess.WHITE): "♔", (chess.KING, chess.BLACK): "♚",
}

AI_MAP = {0: "Minimax (Alpha-Beta)", 1: "MCTS (Monte Carlo)", 2: "Stockfish (UCI)"}

SOUND_THEMES = ["Classic", "Digital", "Tournament", "Silent"]
SOUND_DESIGNS = ["Default", "Warm", "Crisp", "Retro", "Cinematic", "Minimal"]
SOUND_TYPES = ["move", "capture", "check", "checkmate", "castle",
               "illegal", "new_game", "promotion", "ui_click"]
ANIM_EASINGS = ["OutCubic", "Linear", "InOutCubic", "OutBack", "OutBounce", "InCubic"]

GAME_NORMAL = "normal"
GAME_CHECKMATE = "checkmate"
GAME_STALEMATE = "stalemate"
GAME_DRAW = "draw"
GAME_INSUFFICIENT = "insufficient"

QUALITY_PRESETS = {
    "Low": {
        "resolution_index": 1, "fps": 24, "capture_fps": 24,
        "hold": 1.0, "disk_cache": True,
        "label": "🐢 Low — 720p · 24 fps · disk cache",
    },
    "Medium": {
        "resolution_index": 0, "fps": 30, "capture_fps": 30,
        "hold": 1.5, "disk_cache": False,
        "label": "⚖️ Medium — 1080p · 30 fps · balanced",
    },
    "High": {
        "resolution_index": 0, "fps": 60, "capture_fps": 60,
        "hold": 1.5, "disk_cache": False,
        "label": "🚀 High — 1080p · 60 fps · best quality",
    },
}

LOW_RAM_THRESHOLD = 8.0
MED_RAM_THRESHOLD = 16.0
MAX_FRAMES_IN_MEMORY = 1500

RESOLUTION_SIZES = {
    "1920×1080": (1920, 1080),
    "1280×720": (1280, 720),
}
RESOLUTION_LIST = ["1920×1080", "1280×720"]


def get_system_ram_gb():
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        pass
    try:
        if platform.system() == "Windows":
            import ctypes
            class _MEMSTAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = _MEMSTAT()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)
        elif platform.system() == "Linux":
            with open('/proc/meminfo') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        return int(line.split()[1]) / (1024 ** 2)
        elif platform.system() == "Darwin":
            import subprocess
            r = subprocess.run(['sysctl', '-n', 'hw.memsize'],
                               capture_output=True, text=True, timeout=5)
            return int(r.stdout.strip()) / (1024 ** 3)
    except Exception:
        pass
    return 8.0


def get_gpu_info():
    try:
        if platform.system() == "Windows":
            import subprocess
            r = subprocess.run(
                ['wmic', 'path', 'win32_VideoController', 'get', 'Name,AdapterRAM'],
                capture_output=True, text=True, timeout=5)
            for line in r.stdout.strip().split('\n')[1:]:
                parts = line.strip().split()
                if not parts:
                    continue
                try:
                    return ' '.join(parts[:-1]), int(parts[-1]) / (1024 ** 3)
                except (ValueError, IndexError):
                    return ' '.join(parts), 0.0
        elif platform.system() == "Linux":
            import subprocess
            r = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.total',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.strip().split('\n')[0].split(',')
                name = parts[0].strip() if len(parts) > 0 else "Unknown"
                vram = float(parts[1].strip()) / 1024 if len(parts) > 1 else 0.0
                return name, vram
    except Exception:
        pass
    return "Unknown", 0.0


def get_recommended_preset():
    ram = get_system_ram_gb()
    gpu_name, vram = get_gpu_info()
    if ram < LOW_RAM_THRESHOLD or (0 < vram < 4):
        return "Low"
    elif ram < MED_RAM_THRESHOLD or (0 < vram <= 8):
        return "Medium"
    return "High"


def estimate_memory_gb(resolution_str, fps, hold_seconds, move_count):
    res = RESOLUTION_SIZES.get(resolution_str, (1920, 1080))
    w, h = res
    frame_bytes = w * h * 4
    total_frames = max(1, int(hold_seconds * fps)) * max(1, move_count + 1)
    return (total_frames * frame_bytes) / (1024 ** 3)


def find_stockfish():
    p = shutil.which("stockfish")
    if p:
        return p
    for d in ["/usr/games/stockfish", "/usr/local/bin/stockfish",
              r"C:\Stockfish\stockfish.exe"]:
        if os.path.isfile(d):
            return d
    return None


class BoardTheme:
    def __init__(self, name="Classic", light=(240, 217, 181), dark=(181, 136, 99),
                 border=(48, 26, 7), highlight=(255, 255, 0, 100),
                 last_move=(155, 199, 0, 100), arrow=(220, 50, 47, 200)):
        self.name = name
        self.light_sq = QColor(*light)
        self.dark_sq = QColor(*dark)
        self.border = QColor(*border)
        self.highlight = QColor(*highlight)
        self.last_move = QColor(*last_move)
        self.arrow_clr = QColor(*arrow)
        self.bg = QColor(32, 32, 36)
        self.coord = QColor(180, 160, 130)


THEMES = {
    "Classic": BoardTheme(),
    "Blue": BoardTheme("Blue", (208, 224, 243), (116, 150, 194), (40, 50, 70)),
    "Green": BoardTheme("Green", (238, 238, 210), (118, 150, 86), (50, 60, 40)),
    "Brown": BoardTheme("Brown", (222, 197, 165), (170, 120, 70), (60, 35, 15)),
}