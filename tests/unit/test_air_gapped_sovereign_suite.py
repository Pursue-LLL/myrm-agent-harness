"""Unit tests for Air-Gapped Sovereign Intelligence and Zero-Egress Compliance suite.

[POS]
Harness core security test suite verifying loopback-only zero-egress enforcement,
cryptographic assertion proofs, and offline model metadata registry.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.air_gapped import (
    EgressControlTier,
    ExternalEgressBlockedError,
    OfflineModelMetadata,
    OfflineModelRegistry,
    ZeroEgressGuard,
)


def test_zero_egress_guard_sovereign_air_gapped_tier() -> None:
    guard = ZeroEgressGuard(tier=EgressControlTier.AIR_GAPPED_SOVEREIGN)

    # 1. Loopback destinations are permitted
    rec_local1 = guard.record_and_assert("127.0.0.1", 11434, "http")
    assert rec_local1.allowed is True

    rec_local2 = guard.record_and_assert("localhost", 8080, "tcp")
    assert rec_local2.allowed is True

    # 2. External destinations are strictly blocked
    with pytest.raises(ExternalEgressBlockedError) as exc_info:
        guard.record_and_assert("api.openai.com", 443, "https")
    assert "strictly forbidden" in exc_info.value.reason
    assert exc_info.value.host == "api.openai.com"

    with pytest.raises(ExternalEgressBlockedError):
        guard.record_and_assert("8.8.8.8", 53, "udp")

    # 3. Cryptographic zero-egress assertion
    assertion = guard.assert_zero_egress()
    assert assertion.total_attempts == 4
    assert assertion.blocked_attempts == 2
    assert assertion.external_egress_count == 0
    assert assertion.is_zero_egress_compliant is True
    assert len(assertion.assertion_hash) == 64


def test_zero_egress_guard_conservative_and_standard_tiers() -> None:
    guard = ZeroEgressGuard(
        tier=EgressControlTier.CONSERVATIVE,
        allowlist_domains={"vault.internal.corp"},
    )

    # 1. Private RFC1918 network allowed in conservative
    rec_priv = guard.record_and_assert("192.168.1.100", 9000)
    assert rec_priv.allowed is True

    # 2. Explicitly allowlisted domain permitted
    rec_allow = guard.record_and_assert("vault.internal.corp", 443)
    assert rec_allow.allowed is True

    # 3. Non-allowlisted external domain held fail-closed
    with pytest.raises(ExternalEgressBlockedError):
        guard.record_and_assert("untrusted-cdn.com", 443)

    # 4. Switch to standard tier
    guard.set_tier(EgressControlTier.STANDARD)
    rec_std = guard.record_and_assert("untrusted-cdn.com", 443)
    assert rec_std.allowed is True


def test_offline_model_registry() -> None:
    registry = OfflineModelRegistry()

    # 1. Built-in models available without network query
    meta_deepseek = registry.get_metadata("deepseek-r1")
    assert meta_deepseek is not None
    assert meta_deepseek.context_window == 65536
    assert meta_deepseek.is_offline_ready is True

    meta_qwen = registry.get_metadata("qwen2.5-coder-32b")
    assert meta_qwen is not None
    assert meta_qwen.context_window == 131072

    # 2. Substring matching
    meta_fuzzy = registry.get_metadata("llama-3.3-70b-instruct")
    assert meta_fuzzy is not None
    assert meta_fuzzy.model_id == "llama-3.3-70b"

    # 3. Custom offline model registration
    custom_meta = OfflineModelMetadata(
        model_id="custom-sovereign-llm",
        context_window=16384,
        max_output_tokens=2048,
        tokenizer_type="custom_bpe",
        is_offline_ready=True,
    )
    registry.register_offline_model(custom_meta)
    retrieved = registry.get_metadata("custom-sovereign-llm")
    assert retrieved is not None
    assert retrieved.context_window == 16384

    models = registry.list_models()
    assert len(models) >= 7
