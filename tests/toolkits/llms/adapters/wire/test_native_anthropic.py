"""Tests for first-party Anthropic Messages API detection."""

import pytest

from myrm_agent_harness.toolkits.llms.adapters.wire.native_anthropic import is_native_anthropic_wire


@pytest.mark.parametrize(
    ("model", "api_base", "custom_llm_provider"),
    [
        ("anthropic/claude-sonnet-4-20250514", None, None),
        ("claude-sonnet-4-20250514", None, None),
        ("claude-sonnet-4-20250514", "https://anthropic-proxy.example.com", None),
        ("anthropic/claude-sonnet-4-20250514", "http://127.0.0.1:8080", None),
        ("claude-sonnet-4-20250514", None, "anthropic"),
    ],
)
def test_first_party_anthropic_calls_are_native(
    model: str, api_base: str | None, custom_llm_provider: str | None
) -> None:
    assert is_native_anthropic_wire(model, api_base, custom_llm_provider) is True


@pytest.mark.parametrize(
    ("model", "api_base"),
    [
        ("openai/claude-sonnet-4", "https://gateway.example.com/v1"),
        ("openrouter/anthropic/claude-sonnet-4", None),
        ("bedrock/anthropic.claude-sonnet-4-20250514-v1:0", None),
        ("vertex_ai/claude-sonnet-4@20250514", None),
        ("gpt-4o", None),
        ("a-model-litellm-does-not-know", None),
        ("", None),
    ],
)
def test_other_providers_and_unknown_models_are_not_native(model: str, api_base: str | None) -> None:
    assert is_native_anthropic_wire(model, api_base) is False
