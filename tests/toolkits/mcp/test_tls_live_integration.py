"""Live TLS / mTLS handshake regression for MCP HTTP transports.

The unit tests only inspect the ``ssl.SSLContext`` the client builds. These tests
drive a *real* MCP server over a real HTTPS listener (private CA, strict X.509
verification) through the production ``MCPSessionActor`` for both HTTP
transports, proving the TLS settings actually decide whether a handshake
succeeds:

- custom CA bundle: trusted CA connects, unknown CA and wrong CA are rejected,
  ``ssl_verify=False`` opts out;
- mTLS: a server that demands a client certificate rejects clients without one
  and accepts clients presenting a certificate (plain or passphrase-encrypted key).

Negative cases assert the *TLS-layer* failure text, so they cannot pass because of
an unrelated connection error, and every negative has a positive control against
the same server.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from urllib.parse import urlparse

import pytest

from myrm_agent_harness.toolkits.mcp.session_actor import MCPSessionActor
from tests.support.mcp_live_server import error_chain_text, serve_probe_mcp
from tests.support.mcp_tls_pki import ABORTED_CONNECTION_MARKERS, VERIFY_FAILURE_MARKERS, TlsPki

_CONNECT_TIMEOUT_SEC = 10.0
_TRANSPORTS = ("streamable_http", "sse")


def _actor(transport: str, url: str, tls: dict[str, object]) -> MCPSessionActor:
    conn: dict[str, object] = {"transport": transport, "url": url, **tls}
    return MCPSessionActor("tls-probe", conn, connect_timeout=_CONNECT_TIMEOUT_SEC)


async def _assert_echo_roundtrip(transport: str, url: str, tls: dict[str, object]) -> None:
    actor = _actor(transport, url, tls)
    await actor.start()
    try:
        assert actor.is_healthy() is True
        assert "echo:ping" in str(await actor.call("echo", {"text": "ping"}))
    finally:
        await actor.close()


async def _connect_failure_text(transport: str, url: str, tls: dict[str, object]) -> str:
    actor = _actor(transport, url, tls)
    try:
        # The exception type is transport specific (ExceptionGroup / RuntimeError wrappers); the TLS-layer text is asserted.
        with pytest.raises(Exception) as excinfo:
            await actor.start()
    finally:
        await actor.close()
    return error_chain_text(excinfo.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_https_handshake_succeeds_with_custom_ca(pki: TlsPki, transport: str) -> None:
    async with serve_probe_mcp(transport, tls=pki) as url:
        await _assert_echo_roundtrip(transport, url, {"ssl_verify": str(pki.ca_cert)})


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_https_rejected_when_server_certificate_is_not_trusted(pki: TlsPki, transport: str) -> None:
    async with serve_probe_mcp(transport, tls=pki) as url:
        failure = await _connect_failure_text(transport, url, {})
        assert any(marker in failure for marker in VERIFY_FAILURE_MARKERS), failure
        # Positive control: the very same server works once the private CA is trusted.
        await _assert_echo_roundtrip(transport, url, {"ssl_verify": str(pki.ca_cert)})


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_https_rejected_when_pinned_to_the_wrong_ca(pki: TlsPki, transport: str) -> None:
    async with serve_probe_mcp(transport, tls=pki) as url:
        failure = await _connect_failure_text(transport, url, {"ssl_verify": str(pki.rogue_ca_cert)})
        assert any(marker in failure for marker in VERIFY_FAILURE_MARKERS), failure


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_https_verification_can_be_disabled_explicitly(pki: TlsPki, transport: str) -> None:
    async with serve_probe_mcp(transport, tls=pki) as url:
        await _assert_echo_roundtrip(transport, url, {"ssl_verify": False})


def _raw_tls_http_exchange(port: int, context: ssl.SSLContext) -> bytes:
    """Send one HTTP request over a raw TLS socket; return the first response bytes (``b""`` when the server drops us)."""
    with (
        socket.create_connection(("127.0.0.1", port), timeout=5.0) as raw,
        context.wrap_socket(raw, server_hostname="127.0.0.1") as tls,
    ):
        tls.sendall(b"GET /mcp HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        try:
            return tls.recv(64)
        except (ssl.SSLError, ConnectionError):
            return b""


@pytest.mark.asyncio
async def test_mtls_listener_only_answers_clients_presenting_a_certificate(pki: TlsPki) -> None:
    """Raw TLS probe: the listener itself enforces client auth, independent of any HTTP client's error mapping."""
    async with serve_probe_mcp("streamable_http", tls=pki, require_client_cert=True) as url:
        port = urlparse(url).port
        assert port is not None
        anonymous = ssl.create_default_context(cafile=str(pki.ca_cert))
        authenticated = ssl.create_default_context(cafile=str(pki.ca_cert))
        authenticated.load_cert_chain(str(pki.client_cert), str(pki.client_key))
        # Blocking sockets run in worker threads so the in-process server keeps serving on the event loop.
        assert await asyncio.to_thread(_raw_tls_http_exchange, port, anonymous) == b""
        assert (await asyncio.to_thread(_raw_tls_http_exchange, port, authenticated)).startswith(b"HTTP/1.1")


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_mtls_server_rejects_client_without_certificate(pki: TlsPki, transport: str) -> None:
    async with serve_probe_mcp(transport, tls=pki, require_client_cert=True) as url:
        failure = await _connect_failure_text(transport, url, {"ssl_verify": str(pki.ca_cert)})
        assert any(marker in failure for marker in ABORTED_CONNECTION_MARKERS), failure
        # Positive control: the same listener accepts the client once it presents a certificate.
        await _assert_echo_roundtrip(
            transport,
            url,
            {
                "ssl_verify": str(pki.ca_cert),
                "client_cert": str(pki.client_cert),
                "client_key": str(pki.client_key),
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_mtls_handshake_succeeds_with_client_certificate(pki: TlsPki, transport: str) -> None:
    async with serve_probe_mcp(transport, tls=pki, require_client_cert=True) as url:
        await _assert_echo_roundtrip(
            transport,
            url,
            {
                "ssl_verify": str(pki.ca_cert),
                "client_cert": str(pki.client_cert),
                "client_key": str(pki.client_key),
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", _TRANSPORTS)
async def test_mtls_handshake_succeeds_with_passphrase_encrypted_client_key(pki: TlsPki, transport: str) -> None:
    async with serve_probe_mcp(transport, tls=pki, require_client_cert=True) as url:
        await _assert_echo_roundtrip(
            transport,
            url,
            {
                "ssl_verify": str(pki.ca_cert),
                "client_cert": str(pki.client_cert),
                "client_key": str(pki.client_key_encrypted),
                "client_key_password": pki.client_key_passphrase,
            },
        )
