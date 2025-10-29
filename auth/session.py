"""Utility helpers for encoding/decoding signed JWT session tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict


class SessionError(Exception):
    """Raised when a session token cannot be verified."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _ensure_secret_bytes(secret: str | bytes) -> bytes:
    if isinstance(secret, bytes):
        return secret
    if isinstance(secret, str):
        return secret.encode("utf-8")
    return str(secret).encode("utf-8")


def encode_jwt(payload: Dict[str, Any], secret: str | bytes) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_json = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    segments = [_b64url_encode(header_json), _b64url_encode(payload_json)]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(_ensure_secret_bytes(secret), signing_input, hashlib.sha256).digest()
    segments.append(_b64url_encode(signature))
    return ".".join(segments)


def decode_jwt(token: str, secret: str | bytes) -> Dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise SessionError("Malformed session token") from exc
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(_ensure_secret_bytes(secret), signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(signature_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise SessionError("Invalid session signature")
    payload_json = _b64url_decode(payload_b64)
    try:
        payload = json.loads(payload_json.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise SessionError("Invalid session payload") from exc
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp < time.time():
        raise SessionError("Session token expired")
    return payload
