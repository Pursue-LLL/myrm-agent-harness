"""Live redirect-guard regression for MCP HTTP transports.

httpx strips only ``Authorization`` (and rebuilds ``Cookie``) when a redirect leaves
the origin; API keys and tokens configured as MCP headers survive unless the MCP
redirect guard removes them. These tests drive real servers that issue real redirects
and observe, on the receiving side, exactly which headers arrive:

- client level: a guarded client strips credentials on a cross-origin hop but keeps
  benign headers, keeps everything on a same-origin hop, and blocks an https -> http
  downgrade before the request leaves; an unguarded client is the control proving the
  harness can see a leak;
- actor level: the production ``MCPSessionActor`` wiring never delivers credentials to
  a redirect target on another origin, for both HTTP transports. The MCP SDK already
  refuses to follow cross-origin redirects on its own, so this pins the observable
  guarantee (whichever layer provides it) against future SDK or wiring changes.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from myrm_agent_harness.core.security.http.redirect_guard import InsecureRedirectSecurityError
from myrm_agent_harness.toolkits.mcp.client import MCPClientManager
from myrm_agent_harness.toolkits.mcp.session_actor import MCPSessionActor
from tests.support.mcp_live_server import LiveServer, start_live_server
from tests.support.mcp_tls_pki import TlsPki

# Credential headers httpx leaves untouched on redirect but the guard classifies as sensitive.
_CREDENTIALS = {"X-API-Key": "k-live-secret", "X-Auth-Token": "t-live-secret"}
_BENIGN = {"X-Trace-Id": "trace-live-1"}
_CREDENTIAL_NAMES = ("x-api-key", "x-auth-token")
_METHODS = ["GET", "POST"]

RequestLog = list[tuple[str, dict[str, str]]]


def _record(log: RequestLog, request: Request) -> None:
    log.append((request.url.path, {name.lower(): value for name, value in request.headers.items()}))


def _recorder_app(log: RequestLog, *, status_code: int = 200) -> Starlette:
    """Record the headers of every request and answer with *status_code*."""

    async def record(request: Request) -> Response:
        _record(log, request)
        return JSONResponse({"recorded": True}, status_code=status_code)

    return Starlette(routes=[Route("/{path:path}", record, methods=_METHODS)])


def _redirector_app(log: RequestLog, target: str, *, path: str) -> Starlette:
    """Record the request, then answer ``307`` pointing at *target* (method and body preserved)."""

    async def redirect(request: Request) -> Response:
        _record(log, request)
        return RedirectResponse(target, status_code=307)

    return Starlette(routes=[Route(path, redirect, methods=_METHODS)])


def _same_origin_app(log: RequestLog) -> Starlette:
    """``/start`` redirects to ``/landing`` on the very same origin."""

    async def start(request: Request) -> Response:
        _record(log, request)
        return RedirectResponse("/landing", status_code=307)

    async def landing(request: Request) -> Response:
        _record(log, request)
        return JSONResponse({"landed": True})

    return Starlette(routes=[Route("/start", start), Route("/landing", landing)])


@asynccontextmanager
async def _running(*servers: LiveServer) -> AsyncIterator[None]:
    try:
        yield
    finally:
        for server in servers:
            await server.stop()


def _assert_credentials_present(log: RequestLog) -> None:
    for path, headers in log:
        missing = [name for name in _CREDENTIAL_NAMES if name not in headers]
        assert not missing, f"credentials {missing} missing on {path}: {headers}"


def _assert_no_credentials(log: RequestLog) -> None:
    for path, headers in log:
        leaked = [name for name in _CREDENTIAL_NAMES if name in headers]
        assert not leaked, f"credentials {leaked} leaked to {path}: {headers}"


@pytest.mark.asyncio
async def test_cross_origin_redirect_strips_credentials_but_keeps_benign_headers() -> None:
    first_hop: RequestLog = []
    second_hop: RequestLog = []
    target = await start_live_server(_recorder_app(second_hop))
    origin = await start_live_server(_redirector_app(first_hop, f"{target.base_url}/landing", path="/start"))
    start_url = f"{origin.base_url}/start"
    async with (
        _running(origin, target),
        MCPClientManager.build_streamable_http_client({**_CREDENTIALS, **_BENIGN}, url=start_url) as client,
    ):
        response = await client.get(start_url)

    assert response.status_code == 200
    _assert_credentials_present(first_hop)  # control: the credentials really were sent on the first hop
    assert len(second_hop) == 1
    _assert_no_credentials(second_hop)
    assert second_hop[0][1]["x-trace-id"] == _BENIGN["X-Trace-Id"]


@pytest.mark.asyncio
async def test_unguarded_client_leaks_credentials_across_origins() -> None:
    """Control: without the guard the very same redirect delivers the credentials to the other origin."""
    first_hop: RequestLog = []
    second_hop: RequestLog = []
    target = await start_live_server(_recorder_app(second_hop))
    origin = await start_live_server(_redirector_app(first_hop, f"{target.base_url}/landing", path="/start"))
    async with (
        _running(origin, target),
        httpx2.AsyncClient(headers=_CREDENTIALS, follow_redirects=True) as client,
    ):
        await client.get(f"{origin.base_url}/start")

    _assert_credentials_present(second_hop)


@pytest.mark.asyncio
async def test_same_origin_redirect_keeps_every_header() -> None:
    log: RequestLog = []
    origin = await start_live_server(_same_origin_app(log))
    start_url = f"{origin.base_url}/start"
    async with (
        _running(origin),
        MCPClientManager.build_streamable_http_client({**_CREDENTIALS, **_BENIGN}, url=start_url) as client,
    ):
        response = await client.get(start_url)

    assert response.status_code == 200
    assert [path for path, _ in log] == ["/start", "/landing"]
    _assert_credentials_present(log)
    assert all(headers["x-trace-id"] == _BENIGN["X-Trace-Id"] for _, headers in log)


@pytest.mark.asyncio
async def test_https_to_http_downgrade_is_blocked_before_the_request_leaves(pki: TlsPki) -> None:
    first_hop: RequestLog = []
    downgraded: RequestLog = []
    target = await start_live_server(_recorder_app(downgraded))
    origin = await start_live_server(_redirector_app(first_hop, f"{target.base_url}/landing", path="/start"), tls=pki)
    ssl_context = MCPClientManager._build_ssl_context_from_dict("downgrade-probe", {"ssl_verify": str(pki.ca_cert)})
    assert isinstance(ssl_context, ssl.SSLContext)
    start_url = f"{origin.base_url}/start"
    async with (
        _running(origin, target),
        MCPClientManager.build_streamable_http_client(_CREDENTIALS, url=start_url, ssl_context=ssl_context) as client,
    ):
        with pytest.raises(InsecureRedirectSecurityError):
            await client.get(start_url)

    assert len(first_hop) == 1, "control: the https origin must have been reached and issued the redirect"
    assert downgraded == [], "the plaintext origin must never receive a request carrying credentials"


@pytest.mark.asyncio
@pytest.mark.parametrize(("transport", "path"), [("sse", "/sse"), ("streamable_http", "/mcp")])
async def test_actor_never_delivers_credentials_to_a_redirect_target_on_another_origin(
    transport: str, path: str
) -> None:
    first_hop: RequestLog = []
    redirected: RequestLog = []
    target = await start_live_server(_recorder_app(redirected, status_code=404))
    origin = await start_live_server(_redirector_app(first_hop, f"{target.base_url}{path}", path=path))
    actor = MCPSessionActor(
        "redirect-probe",
        {"transport": transport, "url": f"{origin.base_url}{path}", "headers": {**_CREDENTIALS, **_BENIGN}},
        connect_timeout=5.0,
    )
    async with _running(origin, target):
        try:
            with pytest.raises(Exception, match=r"failed to start"):
                await actor.start()
        finally:
            await actor.close()

    assert first_hop, "control: the configured origin must have been contacted"
    _assert_credentials_present(first_hop)  # control: the credentials really were sent to the configured origin
    _assert_no_credentials(redirected)
