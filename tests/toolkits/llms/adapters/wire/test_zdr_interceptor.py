"""Tests for Zero Data Retention (ZDR) wire outbound interceptor.

[INPUT]
- pytest (POS: 测试执行框架)
- myrm_agent_harness.toolkits.llms.adapters.wire.zdr_interceptor
  (POS: ZDR wire 出站合规拦截器)

[OUTPUT]
- Test suite verifying compliance headers, store=False injection,
  pure functional immutability, and 100% Prompt Cache preservation.
"""

from __future__ import annotations

import copy

from myrm_agent_harness.toolkits.llms.adapters.wire.zdr_interceptor import (
    apply_zdr_outbound_params,
    is_zdr_eligible_provider,
)


def test_is_zdr_eligible_provider() -> None:
    """Verify provider eligibility checks across major enterprise model vendors."""
    assert is_zdr_eligible_provider("openai/gpt-4o") is True
    assert is_zdr_eligible_provider("azure/gpt-4o-mini") is True
    assert is_zdr_eligible_provider("anthropic/claude-3-5-sonnet") is True
    assert is_zdr_eligible_provider("bedrock/anthropic.claude-v2") is True
    assert is_zdr_eligible_provider("deepseek/deepseek-chat") is True
    assert is_zdr_eligible_provider("minimax/abab6.5s-chat") is True
    assert is_zdr_eligible_provider("qwen/qwen-2.5-72b") is True

    # Empty or unrelated providers
    assert is_zdr_eligible_provider("") is False
    assert is_zdr_eligible_provider("random_unknown_local_mock") is False


def test_apply_zdr_disabled() -> None:
    """Verify that disabled ZDR returns a clean copy with no alterations."""
    original: dict[str, object] = {
        "model": "gpt-4o",
        "temperature": 0.2,
        "messages": [{"role": "user", "content": "secret data"}],
    }
    result = apply_zdr_outbound_params(original, enabled=False)
    assert result == original
    assert result is not original  # Shallow copied


def test_apply_zdr_openai_vendor() -> None:
    """Verify store=False and X-OpenAI-Store header injection for OpenAI/Azure."""
    original: dict[str, object] = {
        "model": "openai/gpt-4o",
        "messages": [{"role": "user", "content": "confidential financial draft"}],
        "temperature": 0.0,
    }
    enriched = apply_zdr_outbound_params(original, provider="openai")

    # 1. Top-level store flag
    assert enriched["store"] is False

    # 2. Header assertion
    extra_headers = enriched.get("extra_headers")
    assert isinstance(extra_headers, dict)
    assert extra_headers.get("X-OpenAI-Store") == "false"

    # 3. Extra body audit marker
    extra_body = enriched.get("extra_body")
    assert isinstance(extra_body, dict)
    assert extra_body.get("zdr_retention_policy") == "zero_data_retention"

    # 4. Prompt Cache preservation: messages untouched
    assert enriched["messages"] == original["messages"]
    assert enriched["messages"] is original["messages"]


def test_apply_zdr_anthropic_vendor() -> None:
    """Verify Anthropic-Zero-Data-Retention header injection for Anthropic."""
    original: dict[str, object] = {
        "model": "anthropic/claude-3-5-sonnet-20241022",
        "messages": [{"role": "user", "content": "patient health record"}],
        "extra_headers": {"X-Custom-Tracking": "req-123"},
    }
    enriched = apply_zdr_outbound_params(original, provider="anthropic")

    assert enriched["store"] is False
    extra_headers = enriched.get("extra_headers")
    assert isinstance(extra_headers, dict)
    assert extra_headers.get("Anthropic-Zero-Data-Retention") == "true"
    # Preserves existing headers
    assert extra_headers.get("X-Custom-Tracking") == "req-123"


def test_apply_zdr_bedrock_vendor() -> None:
    """Verify Amazon Bedrock Zero Data Retention header injection."""
    original: dict[str, object] = {
        "model": "bedrock/claude-3-haiku",
        "messages": [{"role": "user", "content": "merger contract clause"}],
    }
    enriched = apply_zdr_outbound_params(original, provider="bedrock")

    assert enriched["store"] is False
    extra_headers = enriched.get("extra_headers")
    assert isinstance(extra_headers, dict)
    assert extra_headers.get("x-amzn-bedrock-zero-data-retention") == "true"


def test_apply_zdr_immutability() -> None:
    """Ensure the original params dictionary is never mutated."""
    original: dict[str, object] = {
        "model": "gpt-4o",
        "extra_headers": {"Accept": "application/json"},
        "extra_body": {"stream_options": {"include_usage": True}},
    }
    original_snapshot = copy.deepcopy(original)

    _ = apply_zdr_outbound_params(original, provider="openai")

    assert original == original_snapshot
