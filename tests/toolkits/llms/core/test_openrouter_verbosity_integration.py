"""Integration tests for OpenRouter reasoning_effort rewrite — full create_litellm_model path.

Validates that create_litellm_model correctly propagates reasoning_effort
into extra_body.reasoning.effort for OpenRouter models, and that non-OpenRouter
models retain reasoning_effort untouched.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model


class TestOpenrouterVerbosityIntegration:
    """Full-path integration: create_litellm_model → ChatLiteLLM with OpenRouter reasoning rewrite."""

    @pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
    def test_openrouter_model_reasoning_effort_rewritten(self, effort: str) -> None:
        """OpenRouter model with reasoning_effort should have extra_body.reasoning.effort."""
        llm = create_litellm_model(
            "openrouter/anthropic/claude-4.6-opus",
            api_key="sk-test",
            reasoning_effort=effort,
        )
        params = llm._default_params
        assert "reasoning_effort" not in params
        assert params["extra_body"]["reasoning"]["effort"] == effort

    def test_openrouter_model_effort_none_disables(self) -> None:
        """effort='none' must be explicitly sent to OpenRouter to disable reasoning."""
        llm = create_litellm_model(
            "openrouter/anthropic/claude-4.7-opus",
            api_key="sk-test",
            reasoning_effort="none",
        )
        params = llm._default_params
        assert "reasoning_effort" not in params
        assert params["extra_body"]["reasoning"]["effort"] == "none"

    @pytest.mark.parametrize("model", [
        "anthropic/claude-4.6-opus",
        "openai/gpt-4o",
        "deepseek/deepseek-r1",
    ])
    def test_non_openrouter_model_keeps_reasoning_effort(self, model: str) -> None:
        """Non-OpenRouter model retains top-level reasoning_effort untouched."""
        llm = create_litellm_model(model, api_key="sk-test", reasoning_effort="low")
        params = llm._default_params
        eb = params.get("extra_body", {})
        assert "reasoning" not in eb or "effort" not in eb.get("reasoning", {})

    def test_openrouter_model_no_effort_no_reasoning(self) -> None:
        """OpenRouter model without reasoning_effort should have no reasoning in extra_body."""
        llm = create_litellm_model(
            "openrouter/anthropic/claude-4.6-opus",
            api_key="sk-test",
        )
        params = llm._default_params
        eb = params.get("extra_body", {})
        assert "reasoning" not in eb

    def test_openrouter_streaming_preserves_rewrite(self) -> None:
        """Streaming mode should not interfere with reasoning rewrite."""
        llm = create_litellm_model(
            "openrouter/deepseek/deepseek-r1",
            api_key="sk-test",
            streaming=True,
            reasoning_effort="medium",
        )
        assert llm.streaming is True
        params = llm._default_params
        assert params["extra_body"]["reasoning"]["effort"] == "medium"
        assert "reasoning_effort" not in params

    def test_openrouter_with_temperature_and_max_tokens(self) -> None:
        """Additional kwargs should survive alongside reasoning rewrite.

        claude-fable-5 is a thinking model with effort=xhigh → headroom
        floor=65536, so max_tokens=4096 is raised to 65536.
        """
        llm = create_litellm_model(
            "openrouter/anthropic/claude-fable-5",
            api_key="sk-test",
            temperature=0.3,
            max_tokens=4096,
            reasoning_effort="xhigh",
        )
        params = llm._default_params
        assert params["extra_body"]["reasoning"]["effort"] == "xhigh"
        assert params["temperature"] == 0.3
        assert params["max_tokens"] == 65536


class TestOpenrouterVerbosityLLMManagerPath:
    """Validates reasoning rewrite propagation through LLMManager → create_litellm_model."""

    @pytest.mark.asyncio
    async def test_manager_openrouter_reasoning_rewrite(self) -> None:
        """LLMManager.get_llm with OpenRouter model should apply reasoning rewrite."""
        from myrm_agent_harness.toolkits.llms.core.manager import LLMManager

        llm = await LLMManager.get_llm(
            model="openrouter/anthropic/claude-4.6-opus",
            api_key="sk-test",
            streaming=True,
            reasoning_effort="high",
        )
        params = llm._default_params  # type: ignore[union-attr]
        assert params["extra_body"]["reasoning"]["effort"] == "high"
        assert "reasoning_effort" not in params

    @pytest.mark.asyncio
    async def test_manager_non_openrouter_no_rewrite(self) -> None:
        """LLMManager.get_llm with non-OpenRouter model should not rewrite reasoning."""
        from myrm_agent_harness.toolkits.llms.core.manager import LLMManager

        llm = await LLMManager.get_llm(
            model="anthropic/claude-4.6-opus",
            api_key="sk-test",
            streaming=True,
            reasoning_effort="high",
        )
        params = llm._default_params  # type: ignore[union-attr]
        eb = params.get("extra_body", {})
        assert "reasoning" not in eb or "effort" not in eb.get("reasoning", {})


class TestOpenrouterVerbosityCoexistence:
    """Validates reasoning rewrite coexists with other LLM features without conflict."""

    def test_openrouter_deepseek_r1_has_reasoning_timeout_and_rewrite(self) -> None:
        """OpenRouter DeepSeek-R1 should have both elevated timeout and reasoning rewrite."""
        llm = create_litellm_model(
            "openrouter/deepseek/deepseek-r1",
            api_key="sk-test",
            reasoning_effort="high",
        )
        params = llm._default_params
        assert params["extra_body"]["reasoning"]["effort"] == "high"
        assert llm.request_timeout == 600.0

    def test_openrouter_claude_no_timeout_elevation(self) -> None:
        """OpenRouter Claude 4.6 should not get reasoning timeout but should get rewrite."""
        llm = create_litellm_model(
            "openrouter/anthropic/claude-4.6-opus",
            api_key="sk-test",
            reasoning_effort="medium",
        )
        params = llm._default_params
        assert params["extra_body"]["reasoning"]["effort"] == "medium"
        assert llm.request_timeout == 300.0

    def test_bind_path_preserves_reasoning_effort_for_openrouter(self) -> None:
        """llm.bind(reasoning_effort=...) after creation adds it to _default_params.

        The bind path does not re-run apply_openrouter_reasoning_effort, but
        _inject_allowed_params whitelists it so it won't be dropped by LiteLLM.
        OpenRouter accepts top-level reasoning_effort as a legacy compat path.
        """
        llm = create_litellm_model(
            "openrouter/anthropic/claude-4.6-opus",
            api_key="sk-test",
        )
        bound = llm.bind(reasoning_effort="low")
        assert bound.kwargs.get("reasoning_effort") == "low"
