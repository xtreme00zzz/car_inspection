from __future__ import annotations

from typing import Iterable, List


_BARS = " .:-=+*#%@"


def sparkline(values: Iterable[float], length: int = 60) -> str:
    vals = list(values)
    n = len(vals)
    if n == 0 or length <= 0:
        return ""
    # Downsample or upsample to fixed length
    if n == length:
        series = vals
    else:
        series: List[float] = []
        for i in range(length):
            # Map i -> original index
            idx = i * (n - 1) / (length - 1)
            lo = int(idx)
            hi = min(lo + 1, n - 1)
            t = idx - lo
            v = vals[lo] * (1 - t) + vals[hi] * t
            series.append(v)
    vmin = min(series)
    vmax = max(series)
    if vmax <= vmin:
        return _BARS[0] * length
    out_chars = []
    rng = vmax - vmin
    for v in series:
        norm = (v - vmin) / rng
        idx = int(round(norm * (len(_BARS) - 1)))
        idx = max(0, min(idx, len(_BARS) - 1))
        out_chars.append(_BARS[idx])
    return "".join(out_chars)

