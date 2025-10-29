"""
Configuration helpers for Discord authentication.

Values are sourced from environment variables so deployments can inject
their own credentials without hard-coding sensitive data.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


def _env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    val = os.getenv(name)
    if val is None or val == "":
        if required and default is None:
            return None
        return default
    return val


DISCORD_CLIENT_ID: str = _env("DISCORD_CLIENT_ID", "1432541090346696848") or "1432541090346696848"
DISCORD_REDIRECT_URI: str = _env("DISCORD_REDIRECT_URI", "http://127.0.0.1:53123/callback") or "http://127.0.0.1:53123/callback"
DISCORD_SCOPE: str = _env("DISCORD_SCOPE", "identify guilds guilds.members.read") or "identify guilds guilds.members.read"
DISCORD_GUILD_ID: str = _env("DISCORD_GUILD_ID", "1100943674667442178") or "1100943674667442178"
_raw_roles = _env("DISCORD_ROLE_IDS", None)
if _raw_roles:
    DISCORD_ROLE_IDS = [r.strip() for r in _raw_roles.split(',') if r.strip()]
else:
    # Legacy support: single role env var or default roles
    single_role = _env("DISCORD_ROLE_ID", "1244781023217062010") or "1244781023217062010"
    DISCORD_ROLE_IDS = [single_role, "1190784296533884938", "1216904330506932305"]
if not DISCORD_ROLE_IDS:
    DISCORD_ROLE_IDS = ["1244781023217062010", "1190784296533884938", "1216904330506932305"]
PRIMARY_DISCORD_ROLE_ID: str = DISCORD_ROLE_IDS[0]
DISCORD_ROLE_ID: str = PRIMARY_DISCORD_ROLE_ID  # backward compatibility
DISCORD_INVITE_URL: str | None = _env("DISCORD_INVITE_URL", "https://discord.gg/efdrift")

def _default_cache_root() -> Path:
    """Return a user-writable cache directory for this app.

    - On Windows: %LocalAppData%/eF Drift Car Scrutineer Alpha
    - On macOS: ~/Library/Caches/eF Drift Car Scrutineer Alpha
    - On Linux: $XDG_CACHE_HOME/ef-drift-scrutineer-alpha or ~/.cache/ef-drift-scrutineer-alpha
    """
    app_dir_name_win = "eF Drift Car Scrutineer Alpha"
    app_dir_name_unix = "ef-drift-scrutineer-alpha"

    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / app_dir_name_win
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / app_dir_name_win
    # Linux/Unix
    xdg = os.getenv("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / app_dir_name_unix
    return Path.home() / ".cache" / app_dir_name_unix


# Base cache directory (override with APP_CACHE_DIR if set)
CACHE_ROOT: Path = Path(_env("APP_CACHE_DIR", "") or _default_cache_root())

# Session/JWT configuration
# Allow override of the secret file location via env; otherwise use CACHE_ROOT
SESSION_SECRET_FILE: Path = Path(_env("SESSION_SECRET_FILE", str(CACHE_ROOT / "session_secret.txt")))


def _load_or_create_session_secret() -> str:
    env_secret = _env("SESSION_SECRET", None)
    if env_secret:
        return env_secret
    if SESSION_SECRET_FILE.exists():
        try:
            secret = SESSION_SECRET_FILE.read_text(encoding="utf-8").strip()
            if secret:
                return secret
        except OSError:
            pass
    SESSION_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    try:
        SESSION_SECRET_FILE.write_text(secret, encoding="utf-8")
    except OSError:
        pass
    return secret


SESSION_SECRET: str = _load_or_create_session_secret()
SESSION_TTL_SECONDS: int = int(_env("SESSION_TTL_SECONDS", "900"))  # 15 minutes
SESSION_RECHECK_SECONDS: int = int(_env("SESSION_RECHECK_SECONDS", "300"))  # 5 minutes

# Where we persist the session details and JWT token on disk
SESSION_STORAGE_PATH: Path = Path(_env("SESSION_STORAGE_PATH", str(CACHE_ROOT / "discord_session.json")))
ALLOWLIST_PATH: Path = Path(_env("ALLOWLIST_PATH", str(CACHE_ROOT / "allowlist.json")))

# Discord API endpoints
DISCORD_API_BASE: str = _env("DISCORD_API_BASE", "https://discord.com/api/v10")
DISCORD_TOKEN_URL: str = _env("DISCORD_TOKEN_URL", "https://discord.com/api/oauth2/token")
DISCORD_AUTH_URL: str = _env("DISCORD_AUTH_URL", "https://discord.com/api/oauth2/authorize")


def validate_config() -> list[str]:
    """Return a list of missing configuration variables."""
    return []
