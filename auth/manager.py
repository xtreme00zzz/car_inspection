"""High-level authentication manager coordinating Discord login and session checks."""

from __future__ import annotations

import json
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from typing import Callable, Dict, Optional
import urllib.parse

import requests

from . import config
from . import allowlist
from .callback_server import OAuthCallbackServer
from .discord_oauth import (
    OAuthTokens,
    build_authorization_url,
    exchange_code_for_tokens,
    fetch_current_user,
    fetch_member,
    fetch_user_guilds,
    generate_pkce_pair,
    refresh_token,
)
from .session import SessionError, decode_jwt, encode_jwt


class AuthError(Exception):
    """Raised when authentication fails or the session is invalid."""


@dataclass
class AuthSession:
    token: str
    access_token: str
    refresh_token: Optional[str]
    token_expires_at: float
    discord_user_id: str
    username: str
    roles: list[str]
    checked_at: float


class AuthManager:
    def __init__(self, status_callback: Optional[Callable[[str], None]] = None):
        self._status_callback = status_callback
        self._session: Optional[AuthSession] = None
        self._lock = threading.RLock()
        allowlist.cleanup()
        self._load_existing_session()

    # ------------------------------------------------------------------ helpers
    def _notify(self, message: str) -> None:
        if self._status_callback:
            try:
                self._status_callback(message)
            except Exception:
                pass

    def _load_existing_session(self) -> None:
        path = config.SESSION_STORAGE_PATH
        if not path.exists():
            return
        if not config.SESSION_SECRET:
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            token = data.get("token")
            if not token:
                return
            payload = decode_jwt(token, config.SESSION_SECRET)
            self._session = AuthSession(
                token=token,
                access_token=data.get("access_token", ""),
                refresh_token=data.get("refresh_token"),
                token_expires_at=float(data.get("token_expires_at", 0)),
                discord_user_id=str(payload.get("sub")),
                username=str(payload.get("username", "")),
                roles=list(payload.get("roles", [])),
                checked_at=float(payload.get("checked_at", 0)),
            )
            expires_at = float(payload.get("exp", time.time() + config.SESSION_TTL_SECONDS))
            allowlist.add(self._session.discord_user_id, expires_at, self._session.roles)
            self._notify(f"Authenticated as {self._session.username}")
        except (json.JSONDecodeError, SessionError, OSError, ValueError):
            path.unlink(missing_ok=True)
            self._session = None

    def _persist_session(self) -> None:
        if not self._session:
            return
        path = config.SESSION_STORAGE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "token": self._session.token,
            "access_token": self._session.access_token,
            "refresh_token": self._session.refresh_token,
            "token_expires_at": self._session.token_expires_at,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _clear_session(self) -> None:
        user_id = self._session.discord_user_id if self._session else None
        self._session = None
        try:
            config.SESSION_STORAGE_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        if user_id:
            allowlist.remove(user_id)

    # ------------------------------------------------------------------ properties
    @property
    def is_authenticated(self) -> bool:
        return self._session is not None

    @property
    def current_user(self) -> Optional[str]:
        return self._session.username if self._session else None

    # ------------------------------------------------------------------ public API
    def ensure_configuration(self) -> None:
        missing = config.validate_config()
        if missing:
            raise AuthError(f"Missing required configuration values: {', '.join(missing)}")

    def require_authenticated(self) -> None:
        with self._lock:
            allowlist.cleanup()
            if not self._session:
                raise AuthError("Please log in with Discord to continue.")
            if not config.SESSION_SECRET:
                self._clear_session()
                raise AuthError("SESSION_SECRET is not configured on this system.")
            allow_entry = allowlist.get(self._session.discord_user_id)
            try:
                payload = decode_jwt(self._session.token, config.SESSION_SECRET)
            except SessionError as exc:
                self._clear_session()
                raise AuthError(f"Session expired. Please log in again. ({exc})") from exc
            now = time.time()
            checked_at = float(payload.get("checked_at", 0))
            if allow_entry is None or now - checked_at > config.SESSION_RECHECK_SECONDS:
                self._revalidate_session()

    def login(self) -> Dict[str, str]:
        with self._lock:
            self.ensure_configuration()
            state = secrets.token_urlsafe(24)
            code_verifier, code_challenge = generate_pkce_pair()
            auth_url = build_authorization_url(state, code_challenge)

            parsed = urllib.parse.urlparse(config.DISCORD_REDIRECT_URI)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 53145

            try:
                server = OAuthCallbackServer((host, port))
            except OSError as exc:
                raise AuthError(f"Unable to bind local callback server on {host}:{port}: {exc}") from exc

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            webbrowser.open(auth_url)
            self._notify("Waiting for Discord authentication...")
            result = server.wait_for_result(timeout=300)
            server.shutdown()
            thread.join(timeout=1)
            server.server_close()

            if not result:
                raise AuthError("Discord login timed out.")
            if result.get("state") != state:
                raise AuthError("Invalid OAuth state received.")
            if "error" in result:
                description = result.get("error_description") or result.get("error")
                raise AuthError(f"Discord authorization error: {description}")

            code = result.get("code")
            if not code:
                raise AuthError("Discord authorization code missing.")

            tokens = exchange_code_for_tokens(code, code_verifier)
            user_info = self._verify_membership(tokens)
            self._issue_session(tokens, user_info)
            self._notify(f"Authenticated as {user_info['username']}")
            return user_info

    def logout(self) -> None:
        with self._lock:
            self._clear_session()
        self._notify("Not authenticated")

    # ------------------------------------------------------------------ internals
    def _issue_session(self, tokens: OAuthTokens, user_info: Dict[str, str]) -> None:
        if not config.SESSION_SECRET:
            raise AuthError("SESSION_SECRET is not configured.")
        now = time.time()
        payload = {
            "sub": user_info["user_id"],
            "username": user_info["username"],
            "roles": user_info.get("roles", []),
            "checked_at": now,
            "guild_id": config.DISCORD_GUILD_ID,
            "exp": now + config.SESSION_TTL_SECONDS,
            "iat": now,
        }
        token = encode_jwt(payload, config.SESSION_SECRET)
        self._session = AuthSession(
            token=token,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            token_expires_at=tokens.expires_at,
            discord_user_id=user_info["user_id"],
            username=user_info["username"],
            roles=list(user_info.get("roles", [])),
            checked_at=now,
        )
        allowlist.add(user_info["user_id"], now + config.SESSION_TTL_SECONDS, list(user_info.get("roles", [])))
        self._persist_session()

    def _verify_membership(self, tokens: OAuthTokens) -> Dict[str, str]:
        access_token = tokens.access_token
        try:
            user = fetch_current_user(access_token)
            guilds = fetch_user_guilds(access_token)
            member = fetch_member(access_token, config.DISCORD_GUILD_ID)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 'unknown'
            raise AuthError(f"Discord API error (status {status}). Please try again.") from exc
        user_id = user.get("id")
        if not user_id:
            raise AuthError("Unable to determine Discord user id.")
        if not any(g.get("id") == config.DISCORD_GUILD_ID for g in guilds):
            allowlist.remove(user_id)
            raise AuthError("You must join the authorized Discord server to use this tool.")
        roles = member.get("roles") or []
        if not any(role_id in roles for role_id in config.DISCORD_ROLE_IDS):
            allowlist.remove(user_id)
            raise AuthError("Required Discord role missing. Access denied.")

        username = (
            member.get("user", {}).get("global_name")
            or member.get("user", {}).get("username")
            or user.get("global_name")
            or f"{user.get('username', 'unknown')}#{user.get('discriminator', '0000')}"
        )
        return {"user_id": user_id, "username": username, "roles": roles}

    def _refresh_access_token_if_needed(self) -> None:
        if not self._session or not self._session.refresh_token:
            return
        if self._session.token_expires_at - time.time() > 60:
            return
        try:
            tokens = refresh_token(self._session.refresh_token)
        except requests.HTTPError:
            self._clear_session()
            raise AuthError("Discord session expired. Please log in again.")
        self._session.access_token = tokens.access_token
        self._session.refresh_token = tokens.refresh_token
        self._session.token_expires_at = tokens.expires_at
        self._persist_session()

    def _revalidate_session(self) -> None:
        if not self._session:
            raise AuthError("Session missing.")
        self._refresh_access_token_if_needed()
        tokens = OAuthTokens(
            access_token=self._session.access_token,
            refresh_token=self._session.refresh_token,
            expires_at=self._session.token_expires_at,
            scope=config.DISCORD_SCOPE,
            token_type="Bearer",
        )
        user_info = self._verify_membership(tokens)
        self._issue_session(tokens, user_info)
