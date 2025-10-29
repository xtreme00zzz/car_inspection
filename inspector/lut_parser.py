from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


def read_lut(path: Path) -> List[Tuple[float, float]]:
    """
    Parses a standard AC .lut file: two columns (x y), comments allowed starting with ';' or '#'.
    Returns list of (x, y) pairs as floats, sorted by x.
    Missing files raise FileNotFoundError.
    """
    if not path.exists():
        raise FileNotFoundError(str(path))
    pairs: List[Tuple[float, float]] = []
    with path.open('r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(';') or line.startswith('#'):
                continue
            # Allow comma, pipe or whitespace separators
            for sep in [',', '|']:
                line = line.replace(sep, ' ')
            parts = [p for p in line.split() if p]
            if len(parts) >= 2:
                try:
                    x = float(parts[0])
                    y = float(parts[1])
                    pairs.append((x, y))
                except ValueError:
                    continue
    pairs.sort(key=lambda t: t[0])
    return pairs


def peak_values(curve: List[Tuple[float, float]]) -> Tuple[float, float]:
    """
    Return (x_at_peak, y_peak) for maximum y.
    If curve empty, returns (0.0, 0.0).
    """
    if not curve:
        return 0.0, 0.0
    x, y = max(curve, key=lambda t: t[1])
    return x, y
