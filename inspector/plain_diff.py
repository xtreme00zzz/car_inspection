from __future__ import annotations

import difflib
from pathlib import Path
from typing import List


def unified_diff_text(submitted: Path, reference: Path) -> str:
    try:
        sub = submitted.read_text(encoding='utf-8', errors='ignore').splitlines()
    except Exception:
        sub = []
    try:
        ref = reference.read_text(encoding='utf-8', errors='ignore').splitlines()
    except Exception:
        ref = []
    ud = difflib.unified_diff(ref, sub, fromfile=str(reference), tofile=str(submitted), lineterm='')
    return '\n'.join(ud)

