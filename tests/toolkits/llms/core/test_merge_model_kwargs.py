"""Tests for llm.py core functions.

Covers _merge_model_kwargs_to_extra_body, _resolve_web_search_options, and
create_litellm_model factory — the key parameter pipeline for reasoning_effort
and other model_kwargs passthrough.
"""

from unittest.mock import MagicMock, patch

from myrm_agent_harness.toolkits.llms.core.llm import (
    _merge_model_kwargs_to_extra_body,
    _resolve_web_search_options,
    create_litellm_model,
)


class TestMergeModelKwargsToExtraBody:
    """Tests for _merge_model_kwargs_to_extra_body."""

    def test_reasoning_effort_merged_to_extra_body(self) -> None:
        """reasoning_effort should appear in extra_body for provider passthrough."""
        llm_kwargs: dict = {"model": "anthropic/claude-4-sonnet"}
        model_kwargs = {"reasoning_effort": "high", "temperature": 0.7}
        _merge_model_kwargs_to_extra_body(llm_kwargs, model_kwargs)

        assert llm_kwargs["extra_body"]["reasoning_effort"] == "high"
        assert llm_kwargs["extra_body"]["temperature"] == 0.7

    def test_none_model_kwargs_noop(self) -> None:
        """None model_kwargs should not modify llm_kwargs."""
        llm_kwargs: dict = {"model": "openai/gpt-4o"}
        _merge_model_kwargs_to_extra_body(llm_kwargs, None)

        assert "extra_body" not in llm_kwargs

    def test_empty_model_kwargs_noop(self) -> None:
        """Empty dict model_kwargs should not add extra_body."""
        llm_kwargs: dict = {"model": "openai/gpt-4o"}
        _merge_model_kwargs_to_extra_body(llm_kwargs, {})

        assert "extra_body" not in llm_kwargs

    def test_existing_extra_body_not_overwritten(self) -> None:
        """Pre-existing extra_body keys should not be overwritten."""
        llm_kwargs: dict = {
            "model": "anthropic/claude-4-sonnet",
            "extra_body": {"reasoning_effort": "low"},
        }
        model_kwargs = {"reasoning_effort": "max"}
        _merge_model_kwargs_to_extra_body(llm_kwargs, model_kwargs)

        assert llm_kwargs["extra_body"]["reasoning_effort"] == "low"

    def test_creates_extra_body_when_absent(self) -> None:
        """extra_body should be created if not present."""
        llm_kwargs: dict = {"model": "openai/o3"}
        model_kwargs = {"reasoning_effort": "medium"}
        _merge_model_kwargs_to_extra_body(llm_kwargs, model_kwargs)

        assert "extra_body" in llm_kwargs
        assert llm_kwargs["extra_body"]["reasoning_effort"] == "medium"

    def test_custom_budget_token_value(self) -> None:
        """Custom numeric budget values (from ThinkingIntensity custom input) should pass through."""
        llm_kwargs: dict = {"model": "anthropic/claude-4-sonnet"}
        model_kwargs = {"reasoning_effort": "16384"}
        _merge_model_kwargs_to_extra_body(llm_kwargs, model_kwargs)

        assert llm_kwargs["extra_body"]["reasoning_effort"] == "16384"

    def test_multiple_kwargs_merged(self) -> None:
        """All model_kwargs should be merged, not just reasoning_effort."""
        llm_kwargs: dict = {"model": "openai/gpt-4o"}
        model_kwargs = {"reasoning_effort": "high", "top_p": 0.9, "seed": 42}
        _merge_model_kwargs_to_extra_body(llm_kwargs, model_kwargs)

        extra = llm_kwargs["extra_body"]
        assert extra["reasoning_effort"] == "high"
        assert extra["top_p"] == 0.9
        assert extra["seed"] == 42

    def test_non_dict_extra_body_replaced(self) -> None:
        """If extra_body is somehow not a dict, it should be replaced."""
        llm_kwargs: dict = {"model": "test", "extra_body": "invalid"}
        model_kwargs = {"reasoning_effort": "low"}
        _merge_model_kwargs_to_extra_body(llm_kwargs, model_kwargs)

        assert isinstance(llm_kwargs["extra_body"], dict)
        assert llm_kwargs["extra_body"]["reasoning_effort"] == "low"

    def test_partial_merge_with_existing_extra_body(self) -> None:
        """New keys should be added while existing keys are preserved."""
        llm_kwargs: dict = {
            "model": "openai/o3",
            "extra_body": {"existing_key": "value"},
        }
        model_kwargs = {"reasoning_effort": "high", "existing_key": "new_value"}
        _merge_model_kwargs_to_extra_body(llm_kwargs, model_kwargs)

        assert llm_kwargs["extra_body"]["existing_key"] == "value"
        assert llm_kwargs["extra_body"]["reasoning_effort"] == "high"


class TestResolveWebSearchOptions:
    """Tests for _resolve_web_search_options tri-state logic."""

    def test_explicit_web_search_options_returned(self) -> None:
        """Explicit web_search_options takes highest priority."""
        opts = {"search_context_size": "high"}
        result = _resolve_web_search_options("openai/gpt-4o", None, opts)
        assert result == opts

    def test_native_tools_contains_web_search(self) -> None:
        """native_tools with web_search should return empty dict (enable)."""
        result = _resolve_web_search_options("openai/gpt-4o", {"web_search"}, None)
        assert result == {}

    def test_native_tools_empty_set_disables(self) -> None:
        """Empty native_tools set should disable (return None)."""
        result = _resolve_web_search_options("openai/gpt-4o", set(), None)
        assert result is None

    def test_native_tools_without_web_search(self) -> None:
        """native_tools without web_search should disable."""
        result = _resolve_web_search_options("openai/gpt-4o", {"other_tool"}, None)
        assert result is None

    def test_auto_detect_supported(self) -> None:
        """Auto-detect (native_tools=None) should call litellm.supports_web_search."""
        mock_litellm = MagicMock()
        mock_litellm.supports_web_search.return_value = True
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            result = _resolve_web_search_options("openai/gpt-4o-search", None, None)
        assert result == {}

    def test_auto_detect_not_supported(self) -> None:
        """Auto-detect should return None when model doesn't support web search."""
        mock_litellm = MagicMock()
        mock_litellm.supports_web_search.return_value = False
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            result = _resolve_web_search_options("anthropic/claude-4-sonnet", None, None)
        assert result is None

    def test_auto_detect_import_error(self) -> None:
        """ImportError during auto-detect should gracefully return None."""
        with patch.dict("sys.modules", {"litellm": None}):
            result = _resolve_web_search_options("some-model", None, None)
        assert result is None


class TestCreateLitellmModel:
    """Tests for create_litellm_model factory — verifies kwargs assembly."""

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    def test_basic_creation(self, mock_cls: MagicMock) -> None:
        """Basic model creation with minimal args."""
        create_litellm_model("openai/gpt-4o")
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model"] == "openai/gpt-4o"

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    def test_temperature_passed(self, mock_cls: MagicMock) -> None:
        """Temperature should be included in kwargs."""
        create_litellm_model("openai/gpt-4o", temperature=0.5)
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["temperature"] == 0.5

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    def test_base_url_mapped_to_api_base(self, mock_cls: MagicMock) -> None:
        """base_url should be mapped to api_base for LiteLLM."""
        create_litellm_model("openai/gpt-4o", base_url="https://custom.api.com")
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["api_base"] == "https://custom.api.com"

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    def test_reasoning_effort_in_extra_body(self, mock_cls: MagicMock) -> None:
        """reasoning_effort kwarg should end up in extra_body."""
        create_litellm_model("anthropic/claude-4-sonnet", reasoning_effort="high")
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["extra_body"]["reasoning_effort"] == "high"

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    def test_streaming_flag(self, mock_cls: MagicMock) -> None:
        """streaming=True should be passed through."""
        create_litellm_model("openai/gpt-4o", streaming=True)
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["streaming"] is True

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    def test_api_key_passed(self, mock_cls: MagicMock) -> None:
        """api_key should be passed to ChatLiteLLM."""
        create_litellm_model("openai/gpt-4o", api_key="sk-test-key")
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["api_key"] == "sk-test-key"

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    def test_none_temperature_excluded(self, mock_cls: MagicMock) -> None:
        """None temperature should not appear in kwargs."""
        create_litellm_model("openai/gpt-4o", temperature=None)
        call_kwargs = mock_cls.call_args[1]
        assert "temperature" not in call_kwargs

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    def test_native_tools_web_search_creates_wso(self, mock_cls: MagicMock) -> None:
        """native_tools={'web_search'} should add web_search_options."""
        create_litellm_model("openai/gpt-4o", native_tools={"web_search"})
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["web_search_options"] == {}
