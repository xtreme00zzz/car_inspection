"""Local HTTP server to capture Discord OAuth callback."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse


class OAuthCallbackServer(HTTPServer):
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int]):
        super().__init__(address, _CallbackHandler)
        self._result: Optional[Dict[str, str]] = None
        self._event = threading.Event()

    def wait_for_result(self, timeout: float = 300.0) -> Optional[Dict[str, str]]:
        if self._event.wait(timeout):
            return self._result
        return None

    def set_result(self, data: Dict[str, str]) -> None:
        self._result = data
        self._event.set()


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/callback":
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            self.server.set_result(params)  # type: ignore[attr-defined]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:Segoe UI,Arial,sans-serif;'>"
                b"<h2>Authentication complete</h2>"
                b"<p>You may return to the application.</p>"
                b"</body></html>"
            )
        elif parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def log_message(self, format: str, *args):  # noqa: D401
        # Silence the default HTTP server logging to avoid cluttering stdout.
        return
