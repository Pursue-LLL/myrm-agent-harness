# INPUT: SentinelManager, EphemeralUserCredential, LoopbackEgressProxy, StreamingSentinelScanner
# OUTPUT: Test cases for secret voucher encoding, decoding, stream-boundary reconstruction, and safe_exec integration
# POS: Harness core security tests. Verifies process-ephemeral sentinel vouchers and egress proxy behavior.

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.core.security.egress.sentinel import (
    SENTINEL_PREFIX,
    SENTINEL_SUFFIX,
    SentinelManager,
    StreamingSentinelScanner,
    get_global_sentinel_manager,
)
from myrm_agent_harness.core.security.safe_exec import credential_env_overrides
from myrm_agent_harness.core.security.types import EphemeralUserCredential


def test_sentinel_manager_create_and_resolve() -> None:
    """Test creating and resolving sentinel vouchers."""
    mgr = SentinelManager()
    raw_secret = "sk-proj-super-secret-api-key-1234567890"

    sentinel = mgr.create_sentinel(raw_secret, metadata={"issuer": "openai"})
    assert sentinel.startswith(SENTINEL_PREFIX)
    assert sentinel.endswith(SENTINEL_SUFFIX)

    # Resolution recovers exact secret
    resolved = mgr.resolve_sentinel(sentinel)
    assert resolved == raw_secret

    # Same secret yields same cached sentinel
    cached = mgr.create_sentinel(raw_secret)
    assert cached == sentinel


def test_sentinel_forged_or_invalid_resolution() -> None:
    """Test that invalid or forged sentinels return None."""
    mgr = SentinelManager()
    assert mgr.resolve_sentinel("not-a-sentinel") is None
    assert mgr.resolve_sentinel("myrm-sent-v1.forged.end") is None


def test_sentinel_text_and_bytes_substitution() -> None:
    """Test batch substitution in strings and byte chunks."""
    mgr = SentinelManager()
    k1 = "secret-token-alpha"
    k2 = "secret-token-beta"

    s1 = mgr.create_sentinel(k1)
    s2 = mgr.create_sentinel(k2)

    text = f"curl -H 'Authorization: Bearer {s1}' https://api.com?key={s2}"
    substituted_text = mgr.substitute_text(text)
    assert substituted_text == f"curl -H 'Authorization: Bearer {k1}' https://api.com?key={k2}"

    data_bytes = f"payload={s1}&signature={s2}".encode("utf-8")
    substituted_bytes = mgr.substitute_bytes(data_bytes)
    assert substituted_bytes == f"payload={k1}&signature={k2}".encode("utf-8")


def test_streaming_sentinel_scanner_chunk_boundary() -> None:
    """Test that streaming scanner reconstructs sentinels split across TCP/HTTP chunks."""
    mgr = SentinelManager()
    real_key = "ghp_abcdef1234567890secret"
    sentinel = mgr.create_sentinel(real_key)

    full_payload = f"POST /v1/chat HTTP/1.1\r\nAuthorization: Bearer {sentinel}\r\n\r\nBody".encode("utf-8")

    # Split the payload right in the middle of the sentinel token
    split_idx = full_payload.find(b"myrm-sent-v1.") + 15
    chunk1 = full_payload[:split_idx]
    chunk2 = full_payload[split_idx:]

    scanner = StreamingSentinelScanner(mgr)
    out1 = scanner.feed(chunk1)
    out2 = scanner.feed(chunk2)
    out_final = scanner.flush()

    reconstructed = out1 + out2 + out_final
    assert real_key.encode("utf-8") in reconstructed
    assert b"myrm-sent-v1." not in reconstructed


def test_credential_env_overrides_sentinel_wrapping() -> None:
    """Test that safe_exec.credential_env_overrides uses sentinels when use_sentinel=True."""
    creds = (
        EphemeralUserCredential(issuer="github", token="ghp_realtoken123"),
        EphemeralUserCredential(issuer="xai", token="xai_realtoken456"),
    )

    # With sentinel wrapping (default)
    env = credential_env_overrides(creds, use_sentinel=True)
    assert env["GITHUB_TOKEN"].startswith(SENTINEL_PREFIX)
    assert env["GITHUB_TOKEN"].endswith(SENTINEL_SUFFIX)
    assert "ghp_realtoken123" not in env["GITHUB_TOKEN"]

    # Resolution check
    mgr = get_global_sentinel_manager()
    assert mgr.resolve_sentinel(env["GITHUB_TOKEN"]) == "ghp_realtoken123"

    # Without sentinel wrapping
    raw_env = credential_env_overrides(creds, use_sentinel=False)
    assert raw_env["GITHUB_TOKEN"] == "ghp_realtoken123"
