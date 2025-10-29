from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple


def parse_mismatch_line(line: str) -> Tuple[str, str, str, str, str] | None:
    try:
        fname, rest = line.split('[', 1)
        sec, tail = rest.split(']', 1)
        opt = tail.split(':', 1)[0].strip()
        sub = ''
        ref = ''
        if "submitted=" in tail and "ref=" in tail:
            after = tail.split(':', 1)[1]
            parts = after.split("ref=")
            sub = parts[0].strip().replace("submitted=", '').strip(" '")
            ref = parts[1].strip().strip(" '")
        return fname.strip(), sec.strip(), opt, sub, ref
    except Exception:
        return None


def build_diffs_html(submitted_car_root: Path, reference_root: Path, matched_key: str, mismatches: List[str]) -> str:
    rows: List[Tuple[str, str, str, str, str]] = []
    for m in mismatches:
        parsed = parse_mismatch_line(m)
        if parsed:
            rows.append(parsed)
    rows.sort(key=lambda x: (x[0], x[1], x[2]))
    title = f"Diffs for {submitted_car_root.name} vs reference {matched_key}"
    # Simple HTML table
    html = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'/><title>Diffs</title>",
        "<style>body{font-family:Segoe UI,Arial,sans-serif;background:#ECECEB;color:#000}.wrap{max-width:1100px;margin:16px auto;background:#fff;border-radius:8px;padding:12px}table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #eee;padding:6px 8px;text-align:left}th{background:#f7f7f7}tr:hover{background:#fafafa}.ref{color:#10316B}.sub{color:#E25822}.h{color:#E25822;font-weight:bold}</style>",
        "</head><body><div class='wrap'>",
        f"<h2 class='h'>{title}</h2>",
        "<table>",
        "<tr><th>File</th><th>Section</th><th>Option</th><th class='sub'>Submitted</th><th class='ref'>Reference</th></tr>",
    ]
    for fname, sec, opt, sub, ref in rows:
        html.append(f"<tr><td>{fname}</td><td>{sec}</td><td>{opt}</td><td class='sub'>{sub}</td><td class='ref'>{ref}</td></tr>")
    html.extend(["</table>", "</div></body></html>"])
    return "".join(html)

