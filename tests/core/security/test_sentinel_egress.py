"""Unit & integration tests for Sentinel Vouchers and Loopback Egress Proxy.

[INPUT]
- myrm_agent_harness.core.security.egress.sentinel::SentinelManager, StreamingSentinelScanner
- myrm_agent_harness.core.security.egress.proxy_server::LoopbackEgressProxy, EphemeralCaManager
- myrm_agent_harness.core.security.safe_exec::credential_env_overrides

[OUTPUT]
- test_sentinel_encryption_roundtrip: verifies AES-256-GCM voucher create and resolve
- test_sentinel_replacement_in_headers_and_body: verifies string and bytes substitution
- test_streaming_scanner_cross_chunk_boundary: verifies Overlap Buffer reassembly across chunk splits
- test_credential_env_overrides_sentinel_wrapping: verifies user credentials injected as vouchers
- test_proxy_server_start_stop_and_env: verifies loopback proxy lifecycle and env vars

[POS]
Harness core security test suite for topic_03 Roadmap item #25 (AgentSentinelEgressGuard).
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.egress.proxy_server import (
    EphemeralCaManager,
    LoopbackEgressProxy,
)
from myrm_agent_harness.core.security.egress.sentinel import (
    SentinelManager,
    StreamingSentinelScanner,
)
from myrm_agent_harness.core.security.safe_exec import credential_env_overrides
from myrm_agent_harness.core.security.types import EphemeralUserCredential


def test_sentinel_encryption_roundtrip() -> None:
    """Verify raw secrets are encrypted into vouchers and decrypt accurately."""
    mgr = SentinelManager()
    raw_key = "sk-proj-super-secret-1234567890abcdef"
    sentinel = mgr.create_sentinel(raw_key, metadata={"service": "openai"})

    assert sentinel.startswith("myrm-sent-v1.")
    assert sentinel.endswith(".end")
    assert raw_key not in sentinel

    # Same secret returns identical cached voucher within the process
    assert mgr.create_sentinel(raw_key) == sentinel

    # Roundtrip resolution
    resolved = mgr.resolve_sentinel(sentinel)
    assert resolved == raw_key

    # Invalid / forged vouchers return None
    assert mgr.resolve_sentinel("myrm-sent-v1.forgedpayload.end") is None
    assert mgr.resolve_sentinel("invalid-token") is None


def test_sentinel_replacement_in_headers_and_body() -> None:
    """Verify string and bytes replacement in HTTP headers and request bodies."""
    mgr = SentinelManager()
    key_a = "ghp_1234567890abcdefghij"
    key_b = "xoxb-9876543210-abcdef"

    sentinel_a = mgr.create_sentinel(key_a)
    sentinel_b = mgr.create_sentinel(key_b)

    # Text substitution
    raw_header = f"Authorization: Bearer {sentinel_a}\nOther: {sentinel_b}"
    replaced_header = mgr.substitute_text(raw_header)
    assert replaced_header == f"Authorization: Bearer {key_a}\nOther: {key_b}"

    # Bytes substitution
    raw_bytes = f'{{"token": "{sentinel_a}", "slack": "{sentinel_b}"}}'.encode("utf-8")
    replaced_bytes = mgr.substitute_bytes(raw_bytes)
    assert replaced_bytes == f'{{"token": "{key_a}", "slack": "{key_b}"}}'.encode("utf-8")


def test_streaming_scanner_cross_chunk_boundary() -> None:
    """Verify Overlap Buffer correctly catches vouchers split across TCP/HTTP stream chunks."""
    mgr = SentinelManager()
    secret = "sk-live-secret-token-999"
    sentinel = mgr.create_sentinel(secret)
    sentinel_bytes = sentinel.encode("utf-8")

    scanner = StreamingSentinelScanner(mgr)

    # Split the sentinel right in the middle across 2 chunks
    split_pos = len(sentinel_bytes) // 2
    part1 = b"Prefix payload with token=" + sentinel_bytes[:split_pos]
    part2 = sentinel_bytes[split_pos:] + b"&suffix=done"

    emitted1 = scanner.feed(part1)
    emitted2 = scanner.feed(part2)
    flushed = scanner.flush()

    total_emitted = emitted1 + emitted2 + flushed
    assert sentinel_bytes not in total_emitted
    assert secret.encode("utf-8") in total_emitted
    assert b"Prefix payload with token=" + secret.encode("utf-8") + b"&suffix=done" == total_emitted


def test_credential_env_overrides_sentinel_wrapping() -> None:
    """Verify credential_env_overrides wraps secrets in sentinels when use_sentinel=True."""
    cred = EphemeralUserCredential(
        issuer="github",
        user_id="user-1",
        token="ghp_real_secret_token_123",
        scope="repo",
    )

    overrides = credential_env_overrides((cred,), use_sentinel=True)
    assert "GITHUB_TOKEN" in overrides
    voucher = overrides["GITHUB_TOKEN"]

    assert voucher.startswith("myrm-sent-v1.")
    assert voucher.endswith(".end")
    assert "ghp_real_secret_token_123" not in voucher


@pytest.mark.asyncio
async def test_proxy_server_lifecycle_and_env() -> None:
    """Verify loopback egress proxy starts, generates env overrides, and shuts down safely."""
    mgr = SentinelManager()

    proxy = LoopbackEgressProxy(
        sentinel_manager=mgr,
        host="127.0.0.1",
        port=0,
        enable_tls_interception=True,
    )

    async with proxy:
        url = proxy.proxy_url
        port = int(url.split(":")[-1])
        assert port > 0
        overrides = proxy.get_env_overrides()
        assert "http_proxy" in overrides
        assert "https_proxy" in overrides
        assert f"http://127.0.0.1:{port}" == overrides["http_proxy"]
        assert "REQUESTS_CA_BUNDLE" in overrides
        assert "SSL_CERT_FILE" in overrides
        assert "NODE_EXTRA_CA_CERTS" in overrides
        assert "NO_PROXY" in overrides
        assert "127.0.0.1" in overrides["NO_PROXY"]
