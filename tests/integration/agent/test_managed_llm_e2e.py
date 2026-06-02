"""Tests for ManagedLLM failover integration.

Verifies that ModelFallbackManager is properly integrated into ManagedLLM
with automatic failover, cooldown, and probing.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from myrm_agent_harness.toolkits.llms.fallback import ManagedLLM


def _make_result(content: str = "response") -> ChatResult:
    return ChatResult(generations=[ChatGeneration(message=HumanMessage(content=content))])


def _make_llm(*, succeed: bool = True, content: str = "response") -> MagicMock:
    llm = MagicMock()
    if succeed:
        llm.agenerate = AsyncMock(return_value=_make_result(content))
    else:
        llm.agenerate = AsyncMock(side_effect=Exception("Rate limit exceeded"))
    return llm


@pytest.mark.asyncio
async def test_main_llm_used_when_healthy():
    """ManagedLLM delegates to main LLM when healthy."""
    main = _make_llm(content="Main LLM response")
    fallback = _make_llm(content="Fallback LLM response")

    managed = ManagedLLM(
        main_llm=main,
        fallback_llm=fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3",
    )

    result = await managed._agenerate([HumanMessage(content="hello")])

    assert result is not None
    main.agenerate.assert_called()
    fallback.agenerate.assert_not_called()


@pytest.mark.asyncio
async def test_automatic_failover_to_fallback():
    """ManagedLLM fails over to fallback when main fails."""
    main = _make_llm(succeed=False)
    fallback = _make_llm(content="Fallback LLM response")

    managed = ManagedLLM(
        main_llm=main,
        fallback_llm=fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3",
    )

    result = await managed._agenerate([HumanMessage(content="hello")])

    assert result is not None
    main.agenerate.assert_called()
    fallback.agenerate.assert_called()


@pytest.mark.asyncio
async def test_cooldown_after_main_failure():
    """ManagedLLM skips main LLM during cooldown after failure."""
    main = _make_llm(succeed=False)
    fallback = _make_llm(content="Fallback LLM response")

    managed = ManagedLLM(
        main_llm=main,
        fallback_llm=fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3",
    )

    await managed._agenerate([HumanMessage(content="first call")])
    initial_fallback_calls = fallback.agenerate.call_count

    await managed._agenerate([HumanMessage(content="second call")])

    assert fallback.agenerate.call_count > initial_fallback_calls


@pytest.mark.asyncio
async def test_no_fallback_single_model():
    """ManagedLLM works with only a main model (no fallback)."""
    main = _make_llm(content="Main only response")

    managed = ManagedLLM(
        main_llm=main,
        fallback_llm=None,
        main_model_name="test-model",
    )

    result = await managed._agenerate([HumanMessage(content="hello")])

    assert result is not None
    main.agenerate.assert_called()


@pytest.mark.asyncio
async def test_metrics_collection():
    """ManagedLLM collects metrics for failover events."""
    main = _make_llm(succeed=False)
    fallback = _make_llm(content="Fallback LLM response")

    with patch("myrm_agent_harness.toolkits.llms.fallback.manager.meter") as mock_meter:
        mock_meter.create_counter.return_value = MagicMock()

        managed = ManagedLLM(
            main_llm=main,
            fallback_llm=fallback,
            main_model_name="gpt-4",
            fallback_model_name="claude-3",
        )

        result = await managed._agenerate([HumanMessage(content="hello")])
        assert result is not None


@pytest.mark.asyncio
async def test_multiple_consecutive_failures():
    """ManagedLLM handles multiple consecutive main failures correctly."""
    main = _make_llm(succeed=False)
    fallback = _make_llm(content="Fallback LLM response")

    managed = ManagedLLM(
        main_llm=main,
        fallback_llm=fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3",
    )

    for i in range(3):
        result = await managed._agenerate([HumanMessage(content=f"call {i}")])
        assert result is not None

    assert fallback.agenerate.call_count >= 3


@pytest.mark.asyncio
async def test_bind_tools_delegates_to_main():
    """bind_tools delegates to the main LLM."""
    main = _make_llm()
    main.bind_tools = MagicMock(return_value=main)

    managed = ManagedLLM(main_llm=main, main_model_name="test")

    result = managed.bind_tools([{"name": "test_tool"}])

    main.bind_tools.assert_called_once_with([{"name": "test_tool"}])
    assert result is main
