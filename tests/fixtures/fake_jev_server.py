"""A local HTTP server that plays the JEV endpoint from a script of responses."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

Scripted = tuple[int, bytes, float]
"""``(status, body, delay_seconds)``; the last scripted response repeats."""


class RecordedRequest:
    def __init__(self, headers: dict[str, str], body: Any) -> None:
        self.headers = headers
        self.body = body


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, script: Sequence[Scripted]) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.script = list(script)
        self.requests: list[RecordedRequest] = []
        self._lock = threading.Lock()

    def next_response(self, request: RecordedRequest) -> Scripted:
        with self._lock:
            index = min(len(self.requests), len(self.script) - 1)
            self.requests.append(request)
            return self.script[index]


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        headers = {name.lower(): value for name, value in self.headers.items()}
        status, body, delay = self.server.next_response(RecordedRequest(headers, json.loads(raw)))
        time.sleep(delay)
        try:
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, format: str, *args: Any) -> None:
        return None


class FakeJev:
    def __init__(self, server: _Server) -> None:
        self._server = server
        self.url = f"http://127.0.0.1:{server.server_address[1]}/v1/systemone"

    @property
    def requests(self) -> list[RecordedRequest]:
        return self._server.requests


@contextmanager
def fake_jev(script: Sequence[Scripted]) -> Iterator[FakeJev]:
    server = _Server(script)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield FakeJev(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
