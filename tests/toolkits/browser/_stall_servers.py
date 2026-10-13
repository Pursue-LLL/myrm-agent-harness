"""Local HTTP servers that misbehave the way real sites do, for real-browser integration tests.

[INPUT]
- asyncio (POS: raw TCP servers, so the stall behaviour is exact)

[OUTPUT]
- StallServers: async context manager exposing `ok`, `slow`, `silent`, `headers_only`, `stalled_subresource` and `spinning` URLs, and `wait_for_request` to learn when the browser really reached a URL

[POS]
A real Chromium navigation hangs in specific ways that no mock reproduces: a server that accepts the
connection and never answers (`silent`), one that sends headers and then stalls the body
(`headers_only`), and a page whose subresource never arrives (`stalled_subresource`, recoverable).
`spinning` commits a document whose script never ends, which wedges the renderer mid-load.
`ok` and `slow` are the control group proving the same code paths work against a healthy server.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import TracebackType
from urllib.parse import urlparse

_BODY = b"<html><head><title>{title}</title></head><body><h1>hello</h1>{extra}</body></html>"
_RESPONSE_HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: "
_STALL_FOREVER_S = 300.0


def _page(title: str, extra: str = "") -> bytes:
    return _BODY.replace(b"{title}", title.encode()).replace(b"{extra}", extra.encode())


class StallServers:
    """One loopback server per behaviour; every handler is torn down on exit."""

    def __init__(self, slow_delay_s: float = 2.0) -> None:
        self._slow_delay_s = slow_delay_s
        self._server: asyncio.Server | None = None
        self._port = 0
        self._writers: set[asyncio.StreamWriter] = set()
        self._requested_paths: list[str] = []
        self._request_arrived = asyncio.Event()

    async def __aenter__(self) -> StallServers:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self._port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        assert self._server is not None
        self._server.close()
        for writer in list(self._writers):
            writer.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self._port}/{path}"

    async def wait_for_request(self, url: str, timeout_s: float = 30.0) -> None:
        """Return once the browser has really requested `url`, so a test never races a slow start-up."""
        path = urlparse(url).path
        async with asyncio.timeout(timeout_s):
            while path not in self._requested_paths:
                self._request_arrived.clear()
                await self._request_arrived.wait()

    @property
    def ok(self) -> str:
        return self._url("ok")

    @property
    def slow(self) -> str:
        """Answers normally, but only after `slow_delay_s` (a realistic slow first byte)."""
        return self._url("slow")

    @property
    def silent(self) -> str:
        """Accepts the connection and never answers (main-frame navigation stall)."""
        return self._url("silent")

    @property
    def headers_only(self) -> str:
        """Sends headers promising a body, then stalls (main-frame navigation stall)."""
        return self._url("headers-only")

    @property
    def stalled_subresource(self) -> str:
        """A page that renders, whose image never arrives (recoverable, the document commits)."""
        return self._url("with-stalled-image")

    @property
    def spinning(self) -> str:
        """A document whose inline script never ends: it commits, then the renderer is wedged."""
        return self._url("spinning")

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            request = await reader.read(65536)
            path = request.split(b" ", 2)[1].decode() if request else "/"
            self._requested_paths.append(path)
            self._request_arrived.set()
            await self._respond(path, writer)
        except (asyncio.CancelledError, ConnectionError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    async def _respond(self, path: str, writer: asyncio.StreamWriter) -> None:
        if path == "/silent" or path == "/stalled-image.png":
            await asyncio.sleep(_STALL_FOREVER_S)
        elif path == "/headers-only":
            writer.write(_RESPONSE_HEAD + b"1000\r\n\r\n<html><body>")
            await writer.drain()
            await asyncio.sleep(_STALL_FOREVER_S)
        elif path == "/slow":
            await asyncio.sleep(self._slow_delay_s)
            await self._send(writer, _page("Slow"))
        elif path == "/spinning":
            await self._send(writer, _page("Spin", "<script>while (true) {}</script>"))
        elif path == "/with-stalled-image":
            await self._send(writer, _page("Partial", '<img src="/stalled-image.png">'))
        else:
            await self._send(writer, _page("Good"))

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, body: bytes) -> None:
        writer.write(_RESPONSE_HEAD + str(len(body)).encode() + b"\r\n\r\n" + body)
        await writer.drain()
