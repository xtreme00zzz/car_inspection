from __future__ import annotations

import configparser
from pathlib import Path
from typing import Any, Dict


def read_ini(path: Path) -> configparser.ConfigParser:
    """
    Read an INI file preserving option case and allowing ';' comments.
    Returns the ConfigParser; duplicate section warnings are stored on
    parser._warnings. Missing files raise FileNotFoundError.
    """
    if not path.exists():
        raise FileNotFoundError(str(path))
    parser = configparser.ConfigParser(interpolation=None,
                                       inline_comment_prefixes=(';',),
                                       strict=False)
    parser.optionxform = str  # preserve case
    with path.open('r', encoding='utf-8-sig', errors='ignore') as f:
        content = f.read()
    idx = content.find('[')
    if idx > 0:
        content = content[idx:]
    warnings: list[str] = []
    seen_sections: set[str] = set()
    filtered_lines: list[str] = []
    for line in content.splitlines():
        ls = line.lstrip()
        if ls.startswith('['):
            stripped = ls.strip()
            if stripped.endswith(']') and len(stripped) > 2:
                name = stripped[1:-1].strip()
                if name:
                    key = name.lower()
                    if key in seen_sections:
                        warnings.append(f"Duplicate section: {name}")
                    else:
                        seen_sections.add(key)
        if not ls or ls.startswith('[') or ('=' in ls) or ls.startswith(';') or ls.startswith('#'):
            filtered_lines.append(line)
    parser.read_string('\n'.join(filtered_lines))
    setattr(parser, '_warnings', warnings)
    return parser


def get_float(parser: configparser.ConfigParser, section: str, option: str, default: float | None = None) -> float | None:
    try:
        return parser.getfloat(section, option)
    except Exception:
        return default


def get_int(parser: configparser.ConfigParser, section: str, option: str, default: int | None = None) -> int | None:
    try:
        return parser.getint(section, option)
    except Exception:
        return default


def get_str(parser: configparser.ConfigParser, section: str, option: str, default: str | None = None) -> str | None:
    try:
        return parser.get(section, option)
    except Exception:
        return default


def get_tuple_of_floats(parser: configparser.ConfigParser, section: str, option: str, n: int | None = None, default: tuple[float, ...] | None = None) -> tuple[float, ...] | None:
    val = get_str(parser, section, option)
    if val is None:
        return default
    try:
        parts = [p.strip() for p in val.split(',')]
        floats = tuple(float(p) for p in parts if p)
        if n is not None and len(floats) != n:
            return default
        return floats
    except Exception:
        return default


def read_json(path: Path) -> Any:
    import json
    with path.open('r', encoding='utf-8', errors='ignore') as f:
        return json.load(f)


def list_kn5_files(car_root: Path) -> list[Path]:
    return [p for p in car_root.glob('*.kn5') if p.is_file()]


def folder_size_bytes(path: Path) -> int:
    total = 0
    for p in path.rglob('*'):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total
