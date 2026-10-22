"""A local HTTP server that plays the npm registry and the GitHub API from a path table."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

Scripted = tuple[int, bytes]
"""``(status, body)`` for one path; a path that is not scripted answers 404."""


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, routes: Mapping[str, Scripted]) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.routes = dict(routes)
        self.paths: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def do_GET(self) -> None:
        self.server.paths.append(self.path)
        status, body = self.server.routes.get(self.path, (404, b"{}"))
        try:
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, format: str, *args: Any) -> None:
        return None


class FakeRegistry:
    def __init__(self, server: _Server) -> None:
        self._server = server
        self.url = f"http://127.0.0.1:{server.server_address[1]}"

    @property
    def paths(self) -> list[str]:
        return self._server.paths


@contextmanager
def fake_registry(routes: Mapping[str, Scripted]) -> Iterator[FakeRegistry]:
    server = _Server(routes)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield FakeRegistry(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
