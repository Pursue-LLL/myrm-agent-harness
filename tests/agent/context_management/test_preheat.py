"""Tests for prefix cache preheat utility.

[INPUT]
- agent.context_management.preheat::preheat_prefix_cache (POS: Prefix cache preheat utility for idle compression pipeline.)
- agent.context_management.preheat::needs_explicit_preheat (POS: Prefix cache preheat utility for idle compression pipeline.)

[OUTPUT]
- Tests for provider detection and cache warming probe.

[POS]
Unit tests for preheat.py — provider detection logic and async cache warming.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.context_management.preheat import (
    needs_explicit_preheat,
    preheat_prefix_cache,
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

    async def test_successful_preheat(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.return_value = MagicMock()
        messages = [MagicMock(), MagicMock()]

        result = await preheat_prefix_cache(llm, messages, "anthropic/claude-3-5-sonnet")
        assert result is True
        llm.ainvoke.assert_awaited_once_with(messages, max_tokens=1)

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
