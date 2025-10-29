"""Persistent allowlist cache for authorized Discord users."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional

from . import config


_cache: Dict[str, Dict[str, object]] = {}
_loaded = False


def _path() -> Path:
    return config.ALLOWLIST_PATH


def _load() -> None:
    global _loaded, _cache
    if _loaded:
        return
    _loaded = True
    path = _path()
    if not path.exists():
        _cache = {}
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _cache = data
        else:
            _cache = {}
    except (json.JSONDecodeError, OSError):
        _cache = {}
        path.unlink(missing_ok=True)
    _cleanup(explicit_save=True)


def _save() -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_cache, indent=2), encoding="utf-8")


def _cleanup(*, explicit_save: bool = False) -> None:
    now = time.time()
    removed = False
    for user_id in list(_cache.keys()):
        entry = _cache.get(user_id) or {}
        exp = entry.get("expires_at")
        if not isinstance(exp, (int, float)) or exp < now:
            _cache.pop(user_id, None)
            removed = True
    if removed or explicit_save:
        _save()


def cleanup() -> None:
    _load()
    _cleanup()


def add(user_id: str, expires_at: float, roles: list[str]) -> None:
    _load()
    _cache[user_id] = {
        "expires_at": float(expires_at),
        "roles": list(roles),
    }
    _save()


def get(user_id: str) -> Optional[Dict[str, object]]:
    _load()
    entry = _cache.get(user_id)
    if not entry:
        return None
    exp = entry.get("expires_at")
    if not isinstance(exp, (int, float)) or exp < time.time():
        _cache.pop(user_id, None)
        _save()
        return None
    return entry


def remove(user_id: str) -> None:
    _load()
    if user_id in _cache:
        _cache.pop(user_id, None)
        _save()

