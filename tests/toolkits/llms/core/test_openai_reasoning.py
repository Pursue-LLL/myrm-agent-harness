"""Unit tests for OpenAI reasoning effort mapping and normalization adapter.

Validates:
1. Model detection: prefix, substring, host matching; OpenRouter/DeepSeek exclusion.
2. Reasoning model categorization: o1, o3, o4, gpt-5.6 vs gpt-4o, gpt-4o-mini.
3. Effort mapping: 'minimal'/'min' -> 'low', 'max'/'xhigh' -> 'high', 'standard' -> 'medium'.
4. Unsupported 'off' value stripping for OpenAI reasoning models.
5. Stripping reasoning_effort for non-reasoning OpenAI models (gpt-4o) to prevent 400.
6. Non-OpenAI models remain untouched.
7. End-to-end integration via create_litellm_model.
"""

from unittest.mock import MagicMock, patch

from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model
from myrm_agent_harness.toolkits.llms.core.openai_reasoning import (
    apply_openai_reasoning_effort,
    is_openai_model,
    is_openai_reasoning_model,
)


class TestOpenAIModelDetection:
    """Tests for is_openai_model and is_openai_reasoning_model."""

    def test_direct_openai_prefixes_and_names(self) -> None:
        assert is_openai_model("openai/gpt-4o") is True
        assert is_openai_model("openai/o3-mini") is True
        assert is_openai_model("openai/gpt-5.6") is True
        assert is_openai_model("o1-preview") is True
        assert is_openai_model("gpt-4o-mini") is True

    def test_host_based_detection(self) -> None:
        assert is_openai_model("custom-model", base_url="https://api.openai.com/v1") is True

    def test_excluded_providers(self) -> None:
        assert is_openai_model("openrouter/openai/gpt-4o") is False
        assert is_openai_model("deepseek/deepseek-chat") is False
        assert is_openai_model("anthropic/claude-3-5-sonnet") is False

    def test_reasoning_model_identification(self) -> None:
        assert is_openai_reasoning_model("openai/o1") is True
        assert is_openai_reasoning_model("openai/o3-mini") is True
        assert is_openai_reasoning_model("openai/o4") is True
        assert is_openai_reasoning_model("openai/gpt-5.6") is True
        assert is_openai_reasoning_model("openai/gpt-5-mini") is True
        assert is_openai_reasoning_model("o1-preview") is True
        assert is_openai_reasoning_model("o3") is True
        # Non-reasoning models
        assert is_openai_reasoning_model("openai/gpt-4o") is False
        assert is_openai_reasoning_model("openai/gpt-4o-mini") is False
        assert is_openai_reasoning_model("gpt-3.5-turbo") is False


class TestOpenAIReasoningEffortRemap:
    """Tests for apply_openai_reasoning_effort remap logic."""

    def test_minimal_remapped_to_low(self) -> None:
        kwargs: dict = {"reasoning_effort": "minimal"}
        apply_openai_reasoning_effort("openai/gpt-5.6", kwargs)
        assert kwargs["reasoning_effort"] == "low"
        assert kwargs["extra_body"]["reasoning_effort"] == "low"

    def test_min_remapped_to_low(self) -> None:
        kwargs: dict = {"reasoning_effort": "min"}
        apply_openai_reasoning_effort("openai/o3-mini", kwargs)
        assert kwargs["reasoning_effort"] == "low"
        assert kwargs["extra_body"]["reasoning_effort"] == "low"

    def test_max_remapped_to_high(self) -> None:
        kwargs: dict = {"reasoning_effort": "max"}
        apply_openai_reasoning_effort("openai/o1", kwargs)
        assert kwargs["reasoning_effort"] == "high"
        assert kwargs["extra_body"]["reasoning_effort"] == "high"

    def test_xhigh_remapped_to_high(self) -> None:
        kwargs: dict = {"reasoning_effort": "xhigh"}
        apply_openai_reasoning_effort("openai/o3", kwargs)
        assert kwargs["reasoning_effort"] == "high"
        assert kwargs["extra_body"]["reasoning_effort"] == "high"

    def test_standard_remapped_to_medium(self) -> None:
        kwargs: dict = {"reasoning_effort": "standard"}
        apply_openai_reasoning_effort("openai/gpt-5.6", kwargs)
        assert kwargs["reasoning_effort"] == "medium"
        assert kwargs["extra_body"]["reasoning_effort"] == "medium"

    def test_valid_levels_preserved(self) -> None:
        for level in ("low", "medium", "high"):
            kwargs: dict = {"reasoning_effort": level}
            apply_openai_reasoning_effort("openai/o3-mini", kwargs)
            assert kwargs["reasoning_effort"] == level
            assert kwargs["extra_body"]["reasoning_effort"] == level

    def test_off_values_stripped(self) -> None:
        for val in ("off", "none", "disabled", "0"):
            kwargs: dict = {"reasoning_effort": val}
            apply_openai_reasoning_effort("openai/o3-mini", kwargs)
            assert "reasoning_effort" not in kwargs
            assert "reasoning_effort" not in kwargs.get("extra_body", {})

    def test_non_reasoning_openai_model_strips_reasoning_effort(self) -> None:
        """gpt-4o rejects reasoning_effort: passing it causes HTTP 400."""
        kwargs: dict = {"reasoning_effort": "high"}
        apply_openai_reasoning_effort("openai/gpt-4o", kwargs)
        assert "reasoning_effort" not in kwargs
        assert "reasoning_effort" not in kwargs.get("extra_body", {})

    def test_non_openai_model_untouched(self) -> None:
        kwargs: dict = {"reasoning_effort": "minimal"}
        apply_openai_reasoning_effort("anthropic/claude-3-5-sonnet", kwargs)
        assert kwargs["reasoning_effort"] == "minimal"


class TestCreateLiteLLMModelOpenAIIntegration:
    """Integration test via create_litellm_model factory."""

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    def test_gpt56_minimal_remapped_to_low(self, mock_cls: MagicMock) -> None:
        create_litellm_model("openai/gpt-5.6", reasoning_effort="minimal")
        assert mock_cls.call_count == 1
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["reasoning_effort"] == "low"
        assert call_kwargs["extra_body"]["reasoning_effort"] == "low"

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    def test_o3_mini_max_remapped_to_high(self, mock_cls: MagicMock) -> None:
        create_litellm_model("openai/o3-mini", reasoning_effort="max")
        assert mock_cls.call_count == 1
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["reasoning_effort"] == "high"
        assert call_kwargs["extra_body"]["reasoning_effort"] == "high"

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    def test_gpt4o_strips_reasoning_effort(self, mock_cls: MagicMock) -> None:
        create_litellm_model("openai/gpt-4o", reasoning_effort="low")
        assert mock_cls.call_count == 1
        call_kwargs = mock_cls.call_args[1]
        assert "reasoning_effort" not in call_kwargs
        assert "reasoning_effort" not in call_kwargs.get("extra_body", {})
