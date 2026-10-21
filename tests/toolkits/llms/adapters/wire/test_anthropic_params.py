"""Tests for anthropic messages wire param overrides."""

from myrm_agent_harness.toolkits.llms.adapters.wire.anthropic_params import apply_anthropic_messages_params


def test_apply_anthropic_messages_params_rewrites_model() -> None:
    merged = apply_anthropic_messages_params({"model": "openai/qwen3.6-plus", "stream": True})
    assert merged["model"] == "anthropic/qwen3.6-plus"
    assert merged["custom_llm_provider"] == "anthropic"
    assert merged["stream"] is True
