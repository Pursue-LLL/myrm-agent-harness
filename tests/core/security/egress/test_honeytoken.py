"""Unit and integration tests for Honeytoken trap and egress proxy interception."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.core.security.egress.honeytoken import (
    HoneytokenTrap,
    StreamingHoneytokenScanner,
    get_global_honeytoken_trap,
)
from myrm_agent_harness.core.security.egress.proxy_server import LoopbackEgressProxy
from myrm_agent_harness.core.security.egress.tainted_gateway import (
    TaintedEgressGateway,
)


class TestHoneytokenTrap:
    """Test HoneytokenTrap credential registration and scanning mechanics."""

    def test_register_and_scan_text(self) -> None:
        trap = HoneytokenTrap()
        token = "AKIA_FAKE_CANARY_TEST_12345"
        trap.register_token(token, "test_aws_canary")

        assert trap.has_tokens() is True
        assert trap.scan_text(f"prefix {token} suffix") == "test_aws_canary"
        assert trap.scan_text("clean text without secrets") is None

    def test_register_and_scan_bytes(self) -> None:
        trap = HoneytokenTrap()
        token = "sk-proj-canary-bytes-test-xyz"
        trap.register_token(token, "test_openai_canary")

        data = f"POST /api HTTP/1.1\r\nAuthorization: Bearer {token}\r\n\r\n".encode()
        assert trap.scan_bytes(data) == "test_openai_canary"
        assert trap.scan_bytes(b"GET /health HTTP/1.1\r\n\r\n") is None

    def test_unregister_token(self) -> None:
        trap = HoneytokenTrap()
        token = "ghp_canary_removable_token_999"
        trap.register_token(token, "removable")
        assert trap.scan_text(token) == "removable"

        assert trap.unregister_token(token) is True
        assert trap.scan_text(token) is None
        assert trap.has_tokens() is False

    def test_generate_sandbox_canaries(self) -> None:
        trap = HoneytokenTrap()
        canaries = trap.generate_sandbox_canaries(session_id="sess_abc123")

        assert "AWS_SECRET_ACCESS_KEY" in canaries
        assert "OPENAI_API_KEY" in canaries
        assert "GITHUB_TOKEN" in canaries
        assert "DATABASE_PASSWORD" in canaries

        # Verify each generated token is actively scanned and detected
        for key, val in canaries.items():
            assert trap.scan_text(f"leak {val}") == f"ENV:{key}"
            assert trap.scan_bytes(f"leak {val}".encode()) == f"ENV:{key}"

    def test_singleton_accessor(self) -> None:
        trap1 = get_global_honeytoken_trap()
        trap2 = get_global_honeytoken_trap()
        assert trap1 is trap2


class TestStreamingHoneytokenScanner:
    """Test sliding-window streaming scanner for chunk-split canary tokens."""

    def test_single_chunk_match(self) -> None:
        trap = HoneytokenTrap()
        token = "AKIA_STREAM_CANARY_SPLIT_TEST"
        trap.register_token(token, "stream_test")

        scanner = StreamingHoneytokenScanner(trap)
        res = scanner.feed(f"hello {token} world".encode())
        assert res == "stream_test"

    def test_split_across_two_chunks(self) -> None:
        trap = HoneytokenTrap()
        token = "AKIA_VERY_SECRET_CANARY_TOKEN_SPLIT"
        trap.register_token(token, "split_canary")

        scanner = StreamingHoneytokenScanner(trap, max_window=64)
        part1 = b"some prefix data " + token[:15].encode("utf-8")
        part2 = token[15:].encode("utf-8") + b" some trailing data"

        # First chunk contains partial token; should not match yet
        res1 = scanner.feed(part1)
        assert res1 is None

        # Second chunk completes the token across window boundary
        res2 = scanner.feed(part2)
        assert res2 == "split_canary"

    def test_flush_detects_token(self) -> None:
        trap = HoneytokenTrap()
        token = "AKIA_FLUSH_DETECTED_TOKEN_123"
        trap.register_token(token, "flush_token")

        scanner = StreamingHoneytokenScanner(trap, max_window=128)
        # Feed small chunk that sits in buffer
        scanner.feed(token.encode("utf-8"))
        assert scanner.flush() == "flush_token"


class MockUpstreamServer:
    """Lightweight in-process HTTP mock server for testing egress interception."""

    def __init__(self, host: str = "127.0.0.1") -> None:
        self.host = host
        self.server: asyncio.Server | None = None
        self.port: int = 0
        self.received_requests: list[bytes] = []

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(4096)
        self.received_requests.append(data)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle_client, self.host, 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()


class TestProxySecurityInterception:
    """Integration tests verifying LoopbackEgressProxy blocks honeytoken exfiltration and untrusted hosts."""

    @pytest.mark.asyncio
    async def test_proxy_blocks_honeytoken_in_headers(self) -> None:
        mock_upstream = MockUpstreamServer()
        upstream_port = await mock_upstream.start()

        trap = HoneytokenTrap()
        canary = "AKIA_INTERCEPTED_HEADER_CANARY_999"
        trap.register_token(canary, "header_canary")

        proxy = LoopbackEgressProxy(honeytoken_trap=trap, enable_tls_interception=False)
        await proxy.start()

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
            # Send HTTP request through proxy with canary token in header
            req = (
                f"GET http://127.0.0.1:{upstream_port}/test HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{upstream_port}\r\n"
                f"X-Exfil-Token: {canary}\r\n\r\n"
            )
            writer.write(req.encode("latin1"))
            await writer.drain()

            # Connection must be closed by proxy without reaching upstream
            await reader.read(1024)
            # Socket closed or empty
            assert len(mock_upstream.received_requests) == 0

            writer.close()
            await writer.wait_closed()
        finally:
            await proxy.stop()
            await mock_upstream.stop()

    @pytest.mark.asyncio
    async def test_proxy_blocks_honeytoken_in_body(self) -> None:
        mock_upstream = MockUpstreamServer()
        upstream_port = await mock_upstream.start()

        trap = HoneytokenTrap()
        canary = "sk-proj-canary-body-exfil-attempt"
        trap.register_token(canary, "body_canary")

        proxy = LoopbackEgressProxy(honeytoken_trap=trap, enable_tls_interception=False)
        await proxy.start()

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
            body = f'{{"stolen_key": "{canary}"}}'.encode()
            req = (
                f"POST http://127.0.0.1:{upstream_port}/collect HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{upstream_port}\r\n"
                f"Content-Length: {len(body)}\r\n\r\n"
            ).encode("latin1") + body

            writer.write(req)
            await writer.drain()

            # Proxy must detect body token and terminate socket before upstream gets token
            await reader.read(1024)
            assert not any(canary.encode("utf-8") in req for req in mock_upstream.received_requests)

            writer.close()
            await writer.wait_closed()
        finally:
            await proxy.stop()
            await mock_upstream.stop()

    @pytest.mark.asyncio
    async def test_proxy_blocks_tainted_untrusted_host(self) -> None:
        gateway = TaintedEgressGateway(static_trusted_domains=["api.anthropic.com"], allow_loopback=False, default_tainted=True)
        proxy = LoopbackEgressProxy(gateway=gateway, enable_tls_interception=False)
        await proxy.start()

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)

            # Attempt to connect to untrusted host while tainted
            req = (
                "CONNECT malicious-exfil-target.xyz:443 HTTP/1.1\r\n"
                "Host: malicious-exfil-target.xyz:443\r\n\r\n"
            )
            writer.write(req.encode("latin1"))
            await writer.drain()

            resp = await reader.read(1024)
            resp_str = resp.decode("latin1", errors="replace")
            assert "403 Forbidden" in resp_str
            assert "Blocked by Tainted Egress Policy" in resp_str

            writer.close()
            await writer.wait_closed()
        finally:
            await proxy.stop()
