from __future__ import annotations

import asyncio
import os
import pytest

from myrm_agent_harness.core.security.egress.sentinel import (
    SentinelManager,
    StreamingSentinelScanner,
    is_sentinel_voucher,
)
from myrm_agent_harness.core.security.egress.proxy_server import (
    EphemeralCaManager,
    LoopbackEgressProxy,
)
from myrm_agent_harness.toolkits.code_execution.security.env_isolation import (
    is_non_inheritable_env_var,
    sanitize_env,
)


def test_sentinel_manager_create_and_resolve() -> None:
    mgr = SentinelManager()
    raw_secret = "ghp_realSecretToken1234567890abcdef"
    sentinel = mgr.create_sentinel(raw_secret, metadata={"key": "GITHUB_TOKEN"})

    assert is_sentinel_voucher(sentinel)
    assert sentinel.startswith("myrm-sent-v1.")
    assert sentinel.endswith(".end")
    assert raw_secret not in sentinel

    # Same secret in same manager returns cached voucher
    sentinel2 = mgr.create_sentinel(raw_secret)
    assert sentinel == sentinel2

    # Resolved successfully
    resolved = mgr.resolve_sentinel(sentinel)
    assert resolved == raw_secret

    # Invalid / forged voucher returns None
    assert mgr.resolve_sentinel("myrm-sent-v1.forgedpayload.end") is None
    assert mgr.resolve_sentinel("not-a-sentinel") is None


def test_sentinel_manager_substitute_text_and_bytes() -> None:
    mgr = SentinelManager()
    sec1 = "sec_alpha_999"
    sec2 = "sec_beta_888"
    v1 = mgr.create_sentinel(sec1)
    v2 = mgr.create_sentinel(sec2)

    text = f"Authorization: Bearer {v1}; X-Api-Key: {v2}"
    replaced_text = mgr.substitute_text(text)
    assert replaced_text == f"Authorization: Bearer {sec1}; X-Api-Key: {sec2}"

    data = f"payload={v1}&alt={v2}".encode("utf-8")
    replaced_bytes = mgr.substitute_bytes(data)
    assert replaced_bytes == f"payload={sec1}&alt={sec2}".encode("utf-8")


def test_streaming_sentinel_scanner_cross_chunk() -> None:
    mgr = SentinelManager()
    raw = "super_secret_github_token"
    voucher = mgr.create_sentinel(raw)

    payload = f"header_prefix_{voucher}_tail_suffix".encode("utf-8")
    split_idx = payload.find(b"myrm-sent-v1.") + 8

    chunk1 = payload[:split_idx]
    chunk2 = payload[split_idx:]

    scanner = StreamingSentinelScanner(mgr)
    emitted1 = scanner.feed(chunk1)
    emitted2 = scanner.feed(chunk2)
    emitted_final = scanner.flush()

    total = emitted1 + emitted2 + emitted_final
    assert total == f"header_prefix_{raw}_tail_suffix".encode("utf-8")


def test_env_isolation_permits_sentinel_vouchers() -> None:
    mgr = SentinelManager()
    raw_token = "ghp_1234567890abcdef"
    sentinel_token = mgr.create_sentinel(raw_token)

    # 1. Plain secret is stripped as non-inheritable
    assert is_non_inheritable_env_var("GITHUB_TOKEN", raw_token) is True
    assert is_non_inheritable_env_var("MY_API_KEY", raw_token) is True

    # 2. Ephemeral sentinel voucher is permitted
    assert is_non_inheritable_env_var("GITHUB_TOKEN", sentinel_token) is False
    assert is_non_inheritable_env_var("MY_API_KEY", sentinel_token) is False

    # 3. sanitize_env preserves sentinel token but drops plain secret
    source_env = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_TOKEN": sentinel_token,
        "LEAKED_SECRET": raw_token,
    }
    sanitized = sanitize_env(source_env)
    assert sanitized.get("GITHUB_TOKEN") == sentinel_token
    assert "LEAKED_SECRET" not in sanitized


def test_ephemeral_ca_manager_lifecycle() -> None:
    ca_mgr = EphemeralCaManager()
    bundle_path = ca_mgr.ca_bundle_path
    assert os.path.exists(bundle_path)
    assert bundle_path.endswith(".crt")

    # Generate leaf context for a domain
    ctx = ca_mgr.get_server_ssl_context("api.github.com")
    assert ctx is not None

    # Cleanup unlinks file
    ca_mgr.cleanup()
    assert not os.path.exists(bundle_path)


@pytest.mark.asyncio
async def test_loopback_egress_proxy_http_substitution() -> None:
    mgr = SentinelManager()
    real_key = "sk-live-production-secret-999"
    sentinel_key = mgr.create_sentinel(real_key)

    received_headers: dict[str, str] = {}
    received_body: bytes = b""

    # 1. Start a mock upstream server
    async def _mock_upstream_handler(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        nonlocal received_headers, received_body
        first_line = await reader.readline()
        while True:
            line = await reader.readline()
            if not line or line in (b"\r\n", b"\n"):
                break
            h_str = line.decode("latin1").strip()
            if ":" in h_str:
                k, v = h_str.split(":", 1)
                received_headers[k.strip().lower()] = v.strip()

        cl = int(received_headers.get("content-length", "0"))
        if cl > 0:
            received_body = await reader.read(cl)

        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream = await asyncio.start_server(_mock_upstream_handler, host="127.0.0.1", port=0)
    upstream_port = upstream.sockets[0].getsockname()[1]

    # 2. Start loopback proxy
    proxy = LoopbackEgressProxy(sentinel_manager=mgr, port=0, enable_tls_interception=False)
    proxy_url = await proxy.start()
    proxy_port = proxy._assigned_port

    try:
        # 3. Client connects through proxy to mock upstream
        c_reader, c_writer = await asyncio.open_connection("127.0.0.1", proxy_port)

        req_body = f'{{"auth": "{sentinel_key}"}}'.encode("utf-8")
        raw_req = (
            f"POST http://127.0.0.1:{upstream_port}/api HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{upstream_port}\r\n"
            f"Authorization: Bearer {sentinel_key}\r\n"
            f"Content-Length: {len(req_body)}\r\n\r\n"
        ).encode("latin1") + req_body

        c_writer.write(raw_req)
        await c_writer.drain()

        resp_line = await c_reader.readline()
        assert b"200 OK" in resp_line

        c_writer.close()
        await c_writer.wait_closed()

        # 4. Verify mock upstream received the real secret, NOT the sentinel
        assert received_headers.get("authorization") == f"Bearer {real_key}"
        assert real_key.encode("utf-8") in received_body
        assert sentinel_key.encode("utf-8") not in received_body
    finally:
        await proxy.stop()
        upstream.close()
        await upstream.wait_closed()
