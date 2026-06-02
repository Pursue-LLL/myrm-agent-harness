"""Tests for llms/utils/model_utils — model introspection utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from myrm_agent_harness.toolkits.llms.utils.model_utils import get_model_context_limit


class TestGetModelContextLimit:
    def test_n_ctx_attribute(self) -> None:
        llm = MagicMock()
        llm.n_ctx = 4096
        assert get_model_context_limit(llm) == 4096

    def test_model_max_context_length(self) -> None:
        llm = MagicMock(spec=[])
        llm.model_max_context_length = 8192
        assert get_model_context_limit(llm) == 8192

    def test_max_input_tokens(self) -> None:
        llm = MagicMock(spec=[])
        llm.max_input_tokens = 128000
        assert get_model_context_limit(llm) == 128000

    def test_returns_none_when_no_attr(self) -> None:
        llm = MagicMock(spec=[])
        llm.model_name = ""
        llm.model = ""
        result = get_model_context_limit(llm)
        assert result is None

    def test_litellm_fallback(self) -> None:
        llm = MagicMock(spec=[])
        llm.model_name = "gpt-4o"
        llm.model = "gpt-4o"
        mock_litellm = MagicMock()
        mock_litellm.get_model_info.return_value = {"max_input_tokens": 128000}
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            assert get_model_context_limit(llm) == 128000

    def test_litellm_exception_returns_none(self) -> None:
        llm = MagicMock(spec=[])
        llm.model_name = "unknown-model"
        llm.model = "unknown-model"
        mock_litellm = MagicMock()
        mock_litellm.get_model_info.side_effect = Exception("not found")
        with patch.dict("sys.modules", {"litellm": mock_litellm}):
            assert get_model_context_limit(llm) is None

    def test_zero_value_skipped(self) -> None:
        llm = MagicMock(spec=[])
        llm.n_ctx = 0
        llm.model_max_context_length = 0
        llm.max_input_tokens = 0
        llm.model_name = ""
        llm.model = ""
        assert get_model_context_limit(llm) is None

    def test_negative_value_skipped(self) -> None:
        llm = MagicMock(spec=[])
        llm.n_ctx = -1
        llm.model_max_context_length = -100
        llm.max_input_tokens = 4096
        assert get_model_context_limit(llm) == 4096
