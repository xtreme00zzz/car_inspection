from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def write_junit_xml(path: Path, suite_name: str, cases: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    failures = sum(1 for c in cases if not c.get('passed', False))
    lines.append(f"<?xml version='1.0' encoding='UTF-8'?>")
    lines.append(f"<testsuite name=\"{suite_name}\" tests=\"{len(cases)}\" failures=\"{failures}\">")
    for c in cases:
        name = c.get('name', 'case')
        ok = c.get('passed', False)
        lines.append(f"  <testcase name=\"{name}\">")
        if not ok:
            msg = '\n'.join(c.get('violations', []) or ["Failed"]).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            lines.append(f"    <failure><![CDATA[{msg}]]></failure>")
        lines.append("  </testcase>")
    lines.append("</testsuite>")
    path.write_text('\n'.join(lines), encoding='utf-8')

