"""Tests for prefix cache preheat utility.

[INPUT]
- agent.context_management.preheat::preheat_prefix_cache (POS: Prefix cache preheat utility.)
- agent.context_management.preheat::needs_explicit_preheat (POS: Prefix cache preheat utility.)
- agent.context_management.preheat::schedule_init_preheat (POS: Prefix cache preheat utility.)

[OUTPUT]
- Tests for provider detection, cache warming probe, and init preheat scheduling.

[POS]
Unit tests for preheat.py — provider detection, async cache warming, and init preheat.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.context_management.preheat import (
    _MIN_PREHEAT_TOKENS,
    needs_explicit_preheat,
    preheat_prefix_cache,
    schedule_init_preheat,
)


class TestNeedsExplicitPreheat:
    """Tests for provider detection logic."""

    @pytest.mark.parametrize(
        ("model_name", "expected"),
        [
            ("anthropic/claude-3-5-sonnet", True),
            ("claude-3-opus", True),
            ("qwen-max", True),
            ("dashscope/qwen-turbo", True),
            ("openai/qwen-plus", True),
            ("gpt-4o", False),
            ("deepseek-v3", False),
            ("gemini-1.5-pro", False),
            ("", False),
        ],
    )
    def test_provider_detection(self, model_name: str, expected: bool) -> None:
        assert needs_explicit_preheat(model_name) == expected

    def test_case_insensitive(self) -> None:
        assert needs_explicit_preheat("Anthropic/Claude-3") is True
        assert needs_explicit_preheat("QWEN-MAX") is True


@pytest.mark.asyncio
class TestPreheatPrefixCache:
    """Tests for the async preheat_prefix_cache function."""

    async def test_skip_auto_cache_provider(self) -> None:
        llm = AsyncMock()
        messages = [MagicMock()]
        result = await preheat_prefix_cache(llm, messages, "gpt-4o")
        assert result is False
        llm.ainvoke.assert_not_called()

    async def test_skip_empty_messages(self) -> None:
        llm = AsyncMock()
        result = await preheat_prefix_cache(llm, [], "anthropic/claude-3")
        assert result is False
        llm.ainvoke.assert_not_called()

    async def test_successful_preheat_uses_max_tokens_zero(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.return_value = MagicMock()
        messages = [MagicMock(), MagicMock()]

        result = await preheat_prefix_cache(llm, messages, "anthropic/claude-3-5-sonnet")
        assert result is True
        llm.ainvoke.assert_awaited_once_with(messages, max_tokens=0)

    async def test_fallback_to_max_tokens_one_on_value_error(self) -> None:
        """When max_tokens=0 is rejected, fall back to max_tokens=1."""
        llm = AsyncMock()
        llm.ainvoke.side_effect = [ValueError("max_tokens must be > 0"), MagicMock()]
        messages = [MagicMock()]

        result = await preheat_prefix_cache(llm, messages, "anthropic/claude-3")
        assert result is True
        assert llm.ainvoke.await_count == 2
        llm.ainvoke.assert_awaited_with(messages, max_tokens=1)

    async def test_preheat_failure_returns_false(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.side_effect = RuntimeError("API error")
        messages = [MagicMock()]

        result = await preheat_prefix_cache(llm, messages, "anthropic/claude-3")
        assert result is False

    async def test_preheat_with_qwen(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.return_value = MagicMock()
        messages = [MagicMock()]

        result = await preheat_prefix_cache(llm, messages, "qwen-max")
        assert result is True
        llm.ainvoke.assert_awaited_once()


class TestScheduleInitPreheat:
    """Tests for fire-and-forget init preheat scheduling."""

    def test_skip_when_no_system_prompt(self) -> None:
        llm = MagicMock()
        schedule_init_preheat(llm, None, "anthropic/claude-3")
        schedule_init_preheat(llm, "", "anthropic/claude-3")

    def test_skip_when_non_explicit_provider(self) -> None:
        llm = MagicMock()
        schedule_init_preheat(llm, "A long system prompt " * 200, "gpt-4o")

    @patch("myrm_agent_harness.utils.token_estimation.estimate_content_tokens", return_value=500)
    def test_skip_when_tokens_below_minimum(self, mock_est: MagicMock) -> None:
        llm = MagicMock()
        schedule_init_preheat(llm, "Short prompt", "anthropic/claude-3")

    @patch("myrm_agent_harness.utils.token_estimation.estimate_content_tokens", return_value=_MIN_PREHEAT_TOKENS + 100)
    @patch("asyncio.get_running_loop")
    def test_schedules_task_when_eligible(self, mock_loop: MagicMock, mock_est: MagicMock) -> None:
        mock_loop.return_value.create_task = MagicMock()
        llm = MagicMock()

        schedule_init_preheat(llm, "A " * 2000, "anthropic/claude-3-5-sonnet")

        mock_loop.return_value.create_task.assert_called_once()

    @patch("myrm_agent_harness.utils.token_estimation.estimate_content_tokens", return_value=_MIN_PREHEAT_TOKENS + 100)
    def test_no_running_loop_does_not_raise(self, mock_est: MagicMock) -> None:
        llm = MagicMock()
        schedule_init_preheat(llm, "A " * 2000, "anthropic/claude-3")
