"""Tests for reasoning model timeout floor detection."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.core.reasoning_timeout import get_reasoning_timeout_floor


class TestGetReasoningTimeoutFloor:
    """Test get_reasoning_timeout_floor with various model slugs."""

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("o3", 600.0),
            ("o3-2025-04-16", 600.0),
            ("openai/o3", 600.0),
            ("o1", 600.0),
            ("o1-mini", 600.0),
            ("o1-preview", 600.0),
            ("o3-pro", 600.0),
            ("o3-mini", 450.0),
            ("o4-mini", 450.0),
            ("deepseek/deepseek-r1", 600.0),
            ("deepseek-r1", 600.0),
            ("deepseek-reasoner", 600.0),
            ("nemotron-3-ultra", 600.0),
            ("nemotron-3-super", 600.0),
            ("deepseek/deepseek-v4-pro", 600.0),
            ("deepseek-v4-flash", 450.0),
            ("claude-opus-4", 450.0),
            ("anthropic/claude-opus-4-6", 450.0),
            ("qwq-32b", 450.0),
            ("gemini-2.5-pro", 450.0),
            ("grok-4-fast-reasoning", 450.0),
        ],
    )
    def test_known_reasoning_models(self, model: str, expected: float) -> None:
        assert get_reasoning_timeout_floor(model) == expected

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o",
            "gpt-4o-mini",
            "claude-sonnet-4",
            "deepseek-v4-chat",
            "qwen2.5-72b",
            "qwen3-72b",
            "gemini-2.0-flash",
            "llama-3.1-70b",
            "",
        ],
    )
    def test_non_reasoning_models_return_none(self, model: str) -> None:
        assert get_reasoning_timeout_floor(model) is None

    def test_none_input(self) -> None:
        assert get_reasoning_timeout_floor("") is None

    def test_case_insensitive(self) -> None:
        assert get_reasoning_timeout_floor("OpenAI/O3") == 600.0
        assert get_reasoning_timeout_floor("DEEPSEEK-R1") == 600.0

    def test_provider_prefix_stripped(self) -> None:
        assert get_reasoning_timeout_floor("azure/o3") == 600.0
        assert get_reasoning_timeout_floor("openrouter/deepseek-r1") == 600.0
        assert get_reasoning_timeout_floor("together_ai/qwq-32b") == 450.0
