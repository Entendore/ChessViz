"""
helpers.py — Pure utility functions.
"""

import re, ast, base64, json
from PySide6.QtGui import QImage

_SAFE_FS = re.compile(r'[\\/*?:"<>|]')

def sanitize_filename(name, max_len=120):
    s = _SAFE_FS.sub('_', name).strip('. ')
    return s[:max_len] if s else "untitled"

def parse_opening_image(img_val):
    img_dict = None
    if isinstance(img_val, dict):
        img_dict = img_val
    elif isinstance(img_val, str) and img_val.strip().startswith("{"):
        try:
            safe = img_val
            safe = re.sub(r'\bnull\b', 'None', safe)
            safe = re.sub(r'\btrue\b', 'True', safe)
            safe = re.sub(r'\bfalse\b', 'False', safe)
            safe = re.sub(r'\bNaN\b', 'None', safe)
            safe = re.sub(r'\bundefined\b', 'None', safe)
            img_dict = ast.literal_eval(safe)
        except Exception: pass
    if img_dict:
        try:
            bytes_val = img_dict.get('bytes'); actual_bytes = None
            if isinstance(bytes_val, bytes):
                actual_bytes = bytes_val
            elif isinstance(bytes_val, str):
                try: actual_bytes = base64.b64decode(bytes_val)
                except Exception: pass
                if actual_bytes is None:
                    try: actual_bytes = bytes(bytes_val, "utf-8").decode("unicode_escape").encode("latin1")
                    except Exception: pass
            if actual_bytes:
                img = QImage(); img.loadFromData(actual_bytes); return img
        except Exception: pass
    return None

def _ease_out_cubic(t):
    return 1.0 - (1.0 - t) ** 3

def _sanitize_for_json(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    elif isinstance(obj, bytes):
        return base64.b64encode(obj).decode('ascii')
    elif isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    else:
        return str(obj)