"""Tests for OpenRouter reasoning_effort → reasoning.effort rewrite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.core.openrouter_verbosity import (
    apply_openrouter_reasoning_effort,
)

_OR_CLAUDE_46 = "openrouter/anthropic/claude-4.6-opus"
_OR_CLAUDE_47 = "openrouter/anthropic/claude-4.7-opus"
_OR_FABLE_5 = "openrouter/anthropic/claude-fable-5"
_OR_DEEPSEEK = "openrouter/deepseek/deepseek-r1"
_DIRECT_ANTHROPIC = "anthropic/claude-4.6-opus"
_DIRECT_OPENAI = "openai/gpt-4o"


class TestApplyOpenrouterReasoningEffort:
    """Core mapping behaviour."""

    @pytest.mark.parametrize(
        "model",
        [_OR_CLAUDE_46, _OR_CLAUDE_47, _OR_FABLE_5, _OR_DEEPSEEK],
    )
    @pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
    def test_rewrites_top_level_reasoning_effort(self, model: str, effort: str) -> None:
        kwargs: dict = {"reasoning_effort": effort, "temperature": 0.7}
        apply_openrouter_reasoning_effort(model, kwargs)

        assert "reasoning_effort" not in kwargs
        assert kwargs["extra_body"]["reasoning"]["effort"] == effort
        assert kwargs["temperature"] == 0.7

    @pytest.mark.parametrize("model", [_OR_CLAUDE_46, _OR_DEEPSEEK])
    def test_rewrites_extra_body_reasoning_effort(self, model: str) -> None:
        kwargs: dict = {"extra_body": {"reasoning_effort": "low", "other": 1}}
        apply_openrouter_reasoning_effort(model, kwargs)

        assert "reasoning_effort" not in kwargs["extra_body"]
        assert kwargs["extra_body"]["reasoning"]["effort"] == "low"
        assert kwargs["extra_body"]["other"] == 1

    def test_top_level_takes_priority_over_extra_body(self) -> None:
        kwargs: dict = {
            "reasoning_effort": "high",
            "extra_body": {"reasoning_effort": "low"},
        }
        apply_openrouter_reasoning_effort(_OR_CLAUDE_46, kwargs)

        assert kwargs["extra_body"]["reasoning"]["effort"] == "high"
        assert "reasoning_effort" not in kwargs["extra_body"]

    def test_none_effort_disables_reasoning(self) -> None:
        kwargs: dict = {"reasoning_effort": "none", "temperature": 0.7}
        apply_openrouter_reasoning_effort(_OR_CLAUDE_46, kwargs)

        assert kwargs["extra_body"]["reasoning"]["effort"] == "none"
        assert "reasoning_effort" not in kwargs
        assert kwargs["temperature"] == 0.7

    def test_absent_effort_is_noop(self) -> None:
        kwargs: dict = {"temperature": 0.7}
        apply_openrouter_reasoning_effort(_OR_CLAUDE_46, kwargs)

        assert kwargs == {"temperature": 0.7}

    def test_preserves_existing_reasoning_object(self) -> None:
        kwargs: dict = {
            "reasoning_effort": "high",
            "extra_body": {"reasoning": {"enabled": True, "max_tokens": 2000}},
        }
        apply_openrouter_reasoning_effort(_OR_CLAUDE_46, kwargs)

        reasoning = kwargs["extra_body"]["reasoning"]
        assert reasoning["effort"] == "high"
        assert reasoning["enabled"] is True
        assert reasoning["max_tokens"] == 2000


class TestNonOpenrouterModelsUnchanged:
    """Non-OpenRouter models must not be affected."""

    @pytest.mark.parametrize("model", [_DIRECT_ANTHROPIC, _DIRECT_OPENAI, "gpt-4o"])
    def test_non_openrouter_model_untouched(self, model: str) -> None:
        kwargs: dict = {"reasoning_effort": "low", "temperature": 0.5}
        apply_openrouter_reasoning_effort(model, kwargs)

        assert kwargs["reasoning_effort"] == "low"
        assert "extra_body" not in kwargs


class TestEdgeCases:
    """Edge cases and robustness."""

    def test_empty_kwargs(self) -> None:
        kwargs: dict = {}
        apply_openrouter_reasoning_effort(_OR_CLAUDE_46, kwargs)
        assert kwargs == {}

    def test_extra_body_not_dict_replaced(self) -> None:
        kwargs: dict = {"reasoning_effort": "low", "extra_body": "invalid"}
        apply_openrouter_reasoning_effort(_OR_CLAUDE_46, kwargs)

        assert isinstance(kwargs["extra_body"], dict)
        assert kwargs["extra_body"]["reasoning"]["effort"] == "low"

    def test_does_not_mutate_caller_dict(self) -> None:
        original_extra = {"other_key": "value"}
        kwargs: dict = {"reasoning_effort": "medium", "extra_body": original_extra}
        apply_openrouter_reasoning_effort(_OR_CLAUDE_46, kwargs)

        assert kwargs["extra_body"]["reasoning"]["effort"] == "medium"
        assert kwargs["extra_body"]["other_key"] == "value"
