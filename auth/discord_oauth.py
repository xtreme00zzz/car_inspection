"""Discord OAuth2 helper utilities."""

from __future__ import annotations

import base64
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Dict, Optional

import requests

from . import config


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: Optional[str]
    expires_at: float
    scope: str
    token_type: str


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge)."""
    verifier = secrets.token_urlsafe(64)
    import hashlib

    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(state: str, code_challenge: str) -> str:
    params = {
        "client_id": config.DISCORD_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": config.DISCORD_REDIRECT_URI,
        "scope": config.DISCORD_SCOPE,
        "state": state,
        "prompt": "consent",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{config.DISCORD_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str, code_verifier: str) -> OAuthTokens:
    data = {
        "client_id": config.DISCORD_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.DISCORD_REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(config.DISCORD_TOKEN_URL, data=data, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    expires_in = payload.get("expires_in", 0)
    expires_at = time.time() + int(expires_in)
    return OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_at=expires_at,
        scope=payload.get("scope", ""),
        token_type=payload.get("token_type", "Bearer"),
    )


def refresh_token(refresh_token: str) -> OAuthTokens:
    data = {
        "client_id": config.DISCORD_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(config.DISCORD_TOKEN_URL, data=data, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    expires_in = payload.get("expires_in", 0)
    expires_at = time.time() + int(expires_in)
    return OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_at=expires_at,
        scope=payload.get("scope", ""),
        token_type=payload.get("token_type", "Bearer"),
    )


def _discord_get(access_token: str, path: str) -> Dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(f"{config.DISCORD_API_BASE}{path}", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_current_user(access_token: str) -> Dict:
    return _discord_get(access_token, "/users/@me")


def fetch_user_guilds(access_token: str) -> list[Dict]:
    data = _discord_get(access_token, "/users/@me/guilds")
    if isinstance(data, list):
        return data
    raise ValueError("Unexpected guilds response from Discord")


def fetch_member(access_token: str, guild_id: str) -> Dict:
    return _discord_get(access_token, f"/users/@me/guilds/{guild_id}/member")
