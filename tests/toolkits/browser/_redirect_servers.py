"""Loopback HTTP servers with scripted replies for real-Chromium navigation tests.

[INPUT]
- stdlib http.server (POS: in-process HTTP server)

[OUTPUT]
- Reply / redirect: scripted response specs
- serve: context manager yielding a ``Site`` (base URL + every request the server received)

[POS]
Test support for browser integration tests that need real redirect chains. Every request is
recorded as ``(method, path)``, so a test can prove how many times — and whether at all — the
server was reached instead of trusting the browser-side outcome.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = "text/html; charset=utf-8"


@dataclass(frozen=True, slots=True)
class Reply:
    """One scripted response."""

    status: int = 200
    body: bytes = b""
    content_type: str = HTML
    headers: tuple[tuple[str, str], ...] = ()


def page(text: str) -> Reply:
    """An HTML document whose visible text is ``text``."""
    return Reply(body=f"<!DOCTYPE html><html><head></head><body>{text}</body></html>".encode())


def redirect(location: str, *, status: int = 302, headers: tuple[tuple[str, str], ...] = ()) -> Reply:
    return Reply(status=status, headers=(("Location", location), *headers))


@dataclass(slots=True)
class Site:
    base_url: str
    hits: list[tuple[str, str]] = field(default_factory=list)

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def paths(self, method: str | None = None) -> list[str]:
        return [path for hit_method, path in self.hits if method is None or hit_method == method]


@contextmanager
def serve(routes: Mapping[str, Reply], *, host: str = "127.0.0.1") -> Iterator[Site]:
    """Serve ``routes`` (path -> Reply, query ignored) on a free loopback port."""
    site = Site(base_url="")

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            pass

        def _reply(self, method: str) -> None:
            path = self.path.split("?", 1)[0]
            site.hits.append((method, path))
            reply = routes.get(path, Reply(status=404, body=b"not found"))
            self.send_response(reply.status)
            self.send_header("Content-Type", reply.content_type)
            self.send_header("Content-Length", str(len(reply.body)))
            for name, value in reply.headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(reply.body)

        def do_GET(self) -> None:
            self._reply("GET")

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self._reply("POST")

    server = ThreadingHTTPServer((host, 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    site.base_url = f"http://{host}:{server.server_address[1]}"
    try:
        yield site
    finally:
        server.shutdown()
        server.server_close()
