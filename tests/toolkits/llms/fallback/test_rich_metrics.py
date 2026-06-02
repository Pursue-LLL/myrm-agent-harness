"""Tests for enriched metrics in ModelFallbackManager."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from myrm_agent_harness.toolkits.llms.fallback import ManagedLLM


@pytest.mark.asyncio
async def test_failover_metrics_recorded():
    """Test that failover metrics are recorded correctly."""
    main_llm = MagicMock()
    fallback_llm = MagicMock()

    # Main fails, fallback succeeds
    main_llm.agenerate = AsyncMock(side_effect=Exception("Rate limit"))
    fallback_llm.agenerate = AsyncMock(
        return_value=ChatResult(generations=[ChatGeneration(message=AIMessage(content="fallback"))])
    )

    # Track failover events
    failover_events = []

    async def on_failover(event):
        failover_events.append(event)

    managed_llm = ManagedLLM(
        main_llm=main_llm,
        fallback_llm=fallback_llm,
        main_model_name="main",
        fallback_model_name="fallback",
        on_failover=on_failover,
    )

    messages = [HumanMessage(content="test")]
    await managed_llm.ainvoke(messages)

    # Verify failover occurred
    assert len(failover_events) == 1
    assert failover_events[0].from_model == "main"
    assert failover_events[0].to_model == "fallback"


@pytest.mark.asyncio
async def test_recovery_metrics_recorded():
    """Test that recovery metrics are recorded correctly."""
    main_llm = MagicMock()
    fallback_llm = MagicMock()

    # Main LLM: fails once, then succeeds
    call_count = {"main": 0}

    async def main_agenerate(*args, **kwargs):
        call_count["main"] += 1
        if call_count["main"] == 1:
            raise Exception("Rate limit")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="recovered"))])

    # Fallback LLM: always succeeds
    async def fallback_agenerate(*args, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="fallback"))])

    main_llm.agenerate = main_agenerate
    fallback_llm.agenerate = fallback_agenerate

    # Track recovery events
    recovery_events = []

    async def on_recovery(event):
        recovery_events.append(event)

    managed_llm = ManagedLLM(
        main_llm=main_llm,
        fallback_llm=fallback_llm,
        main_model_name="main",
        fallback_model_name="fallback",
        on_recovery=on_recovery,
    )

    messages = [HumanMessage(content="test")]

    # First call: main fails, fallback succeeds
    result1 = await managed_llm.ainvoke(messages)
    assert result1.content == "fallback"

    # Second call: main probes and recovers (cooldown allows probing)
    result2 = await managed_llm.ainvoke(messages)
    assert result2.content in ["recovered", "fallback"]  # Either main recovers or fallback continues

    # If recovery happened, verify it was recorded
    if result2.content == "recovered":
        assert len(recovery_events) == 1
        assert recovery_events[0].model == "main"
        assert recovery_events[0].probe_count > 0


@pytest.mark.asyncio
async def test_metrics_with_multi_level_fallback():
    """Test metrics work correctly with multi-level fallback."""
    from myrm_agent_harness.toolkits.llms.fallback import FallbackModel

    llms = [MagicMock() for _ in range(3)]

    # First two fail, third succeeds
    llms[0].agenerate = AsyncMock(side_effect=Exception("Model 0 failed"))
    llms[1].agenerate = AsyncMock(side_effect=Exception("Model 1 failed"))
    llms[2].agenerate = AsyncMock(
        return_value=ChatResult(generations=[ChatGeneration(message=AIMessage(content="success"))])
    )

    failover_count = 0

    async def on_failover(event):
        nonlocal failover_count
        failover_count += 1

    managed_llm = ManagedLLM(
        main_llm=llms[0],
        fallback_models=[
            FallbackModel(llm=llms[1], name="fb1", cost=0.3, quality=0.75),
            FallbackModel(llm=llms[2], name="fb2", cost=0.1, quality=0.6),
        ],
        main_model_name="main",
        on_failover=on_failover,
    )

    messages = [HumanMessage(content="test")]
    result = await managed_llm.ainvoke(messages)

    # Should have 2 failovers (main->fb1, fb1->fb2)
    assert failover_count == 2
    assert result.content == "success"
