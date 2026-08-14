"""Tests for thinking model max_tokens headroom adjustment."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.core.thinking_headroom import (
    _extract_effort,
    _is_thinking_model,
    ensure_thinking_headroom,
)


class TestIsThinkingModel:
    """Test _is_thinking_model with various model slugs."""

    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-5",
            "anthropic/claude-opus-4-6",
            "claude-sonnet-4-20250514",
            "claude-fable-5",
            "claude-mythos-1",
            "claude-4.7-opus",
            "o1",
            "o3",
            "o3-pro",
            "o4-mini",
            "openai/o3",
            "deepseek-r1",
            "deepseek/deepseek-r1",
            "deepseek-reasoner",
            "deepseek-v4-pro",
            "gemini-2.5-pro",
            "gemini-3-ultra",
            "nemotron-3-super",
            "qwq-32b",
            "grok-4-fast-reasoning",
        ],
    )
    def test_known_thinking_models(self, model: str) -> None:
        assert _is_thinking_model(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o",
            "gpt-4o-mini",
            "claude-3.5-sonnet",
            "deepseek-v3-chat",
            "qwen2.5-72b",
            "qwen3-72b",
            "gemini-2.0-flash",
            "llama-3.1-70b",
            "mistral-large",
        ],
    )
    def test_non_thinking_models(self, model: str) -> None:
        assert _is_thinking_model(model) is False

    def test_empty_string(self) -> None:
        assert _is_thinking_model("") is False

    def test_case_insensitive(self) -> None:
        assert _is_thinking_model("OpenAI/O3") is True
        assert _is_thinking_model("DEEPSEEK-R1") is True

    def test_provider_prefix_stripped(self) -> None:
        assert _is_thinking_model("azure/o3") is True
        assert _is_thinking_model("openrouter/anthropic/claude-opus-5") is True
        assert _is_thinking_model("together_ai/qwq-32b") is True


class TestExtractEffort:
    """Test _extract_effort from all possible locations."""

    def test_top_level(self) -> None:
        assert _extract_effort({"reasoning_effort": "high"}) == "high"

    def test_extra_body_flat(self) -> None:
        kwargs: dict = {"extra_body": {"reasoning_effort": "low"}}
        assert _extract_effort(kwargs) == "low"

    def test_extra_body_nested(self) -> None:
        kwargs: dict = {"extra_body": {"reasoning": {"effort": "max"}}}
        assert _extract_effort(kwargs) == "max"

    def test_top_level_takes_precedence(self) -> None:
        kwargs: dict = {
            "reasoning_effort": "high",
            "extra_body": {"reasoning_effort": "low"},
        }
        assert _extract_effort(kwargs) == "high"

    def test_none_when_absent(self) -> None:
        assert _extract_effort({}) is None
        assert _extract_effort({"temperature": 0.7}) is None

    def test_none_when_extra_body_not_dict(self) -> None:
        assert _extract_effort({"extra_body": "invalid"}) is None

    def test_normalizes_to_lowercase(self) -> None:
        assert _extract_effort({"reasoning_effort": "HIGH"}) == "high"
        assert _extract_effort({"reasoning_effort": "Medium"}) == "medium"

    def test_numeric_effort_converted(self) -> None:
        assert _extract_effort({"reasoning_effort": 3}) == "3"


class TestEnsureThinkingHeadroom:
    """Test ensure_thinking_headroom end-to-end scenarios."""

    def test_non_thinking_model_is_noop(self) -> None:
        kwargs: dict = {"max_tokens": 4096}
        ensure_thinking_headroom("gpt-4o", kwargs)
        assert kwargs["max_tokens"] == 4096

    @pytest.mark.parametrize(
        ("effort", "expected_floor"),
        [
            ("low", 8192),
            ("medium", 16384),
            ("high", 32768),
            ("xhigh", 65536),
            ("max", 65536),
        ],
    )
    def test_thinking_model_with_effort_raises_to_floor(self, effort: str, expected_floor: int) -> None:
        kwargs: dict = {"max_tokens": 4096, "reasoning_effort": effort}
        ensure_thinking_headroom("anthropic/claude-opus-5", kwargs)
        assert kwargs["max_tokens"] == expected_floor

    def test_thinking_model_no_effort_uses_default_floor(self) -> None:
        kwargs: dict = {"max_tokens": 4096}
        ensure_thinking_headroom("anthropic/claude-opus-5", kwargs)
        assert kwargs["max_tokens"] == 16384

    def test_thinking_model_max_tokens_above_floor_unchanged(self) -> None:
        kwargs: dict = {"max_tokens": 65536, "reasoning_effort": "low"}
        ensure_thinking_headroom("o3", kwargs)
        assert kwargs["max_tokens"] == 65536

    def test_thinking_model_max_tokens_unset(self) -> None:
        kwargs: dict = {"temperature": 0.7}
        ensure_thinking_headroom("deepseek-r1", kwargs)
        assert kwargs["max_tokens"] == 16384

    def test_thinking_model_max_tokens_none(self) -> None:
        kwargs: dict = {"max_tokens": None}
        ensure_thinking_headroom("gemini-2.5-pro", kwargs)
        assert kwargs["max_tokens"] == 16384

    def test_thinking_model_max_tokens_zero(self) -> None:
        kwargs: dict = {"max_tokens": 0}
        ensure_thinking_headroom("qwq-32b", kwargs)
        assert kwargs["max_tokens"] == 16384

    def test_thinking_model_max_tokens_negative(self) -> None:
        kwargs: dict = {"max_tokens": -1}
        ensure_thinking_headroom("o3", kwargs)
        assert kwargs["max_tokens"] == 16384

    def test_unknown_effort_uses_default_floor(self) -> None:
        kwargs: dict = {"max_tokens": 4096, "reasoning_effort": "ultra"}
        ensure_thinking_headroom("claude-opus-5", kwargs)
        assert kwargs["max_tokens"] == 16384

    def test_effort_from_openrouter_rewrite(self) -> None:
        kwargs: dict = {
            "max_tokens": 4096,
            "extra_body": {"reasoning": {"effort": "high"}},
        }
        ensure_thinking_headroom("claude-opus-5", kwargs)
        assert kwargs["max_tokens"] == 32768

    def test_does_not_lower_user_value(self) -> None:
        kwargs: dict = {"max_tokens": 100000, "reasoning_effort": "high"}
        ensure_thinking_headroom("o3", kwargs)
        assert kwargs["max_tokens"] == 100000
