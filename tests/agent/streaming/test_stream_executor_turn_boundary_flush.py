"""Tests for StreamExecutor turn boundary and exception memory flush."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.streaming.stream_executor import (
    StreamContext,
    StreamExecutor,
)
from myrm_agent_harness.agent.types import AgentRunStatistics


@pytest.fixture
def mock_memory_manager():
    mm = MagicMock()
    session = MagicMock()
    session.buffer_size = 1
    session.flush = AsyncMock(return_value=["mem-1"])
    mm.active_session = session
    return mm


@pytest.fixture
def stream_ctx(mock_memory_manager):
    stats = AgentRunStatistics()
    ctx = StreamContext(
        agent=MagicMock(),
        agent_input={"messages": [HumanMessage(content="remember my preference")]},
        merged_context={"locale": "en"},
        run_config={},
        stats=stats,
        message_id="turn_flush_test",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
        memory_manager=mock_memory_manager,
    )
    return ctx


@pytest.mark.asyncio
async def test_stream_executor_flushes_memory_at_turn_boundary(
    stream_ctx, mock_memory_manager
):
    """Verify that StreamExecutor flushes active memory session at turn completion."""

    async def fake_astream(*args, **kwargs):
        yield ("messages", (AIMessage(content="I will remember that."), {"tags": []}))

    stream_ctx.agent.astream = fake_astream

    executor = StreamExecutor(
        ctx=stream_ctx,
        fallback_llm=None,
        safety_fallback_llm=None,
        rebuild_agent_fn=MagicMock(),
    )

    await executor.execute()

    assert mock_memory_manager.active_session.flush.called


@pytest.mark.asyncio
async def test_stream_executor_flushes_memory_on_exception_finally(
    stream_ctx, mock_memory_manager
):
    """Verify that StreamExecutor flushes memory even if an exception occurs during execution."""

    async def fake_failing_astream(*args, **kwargs):
        raise RuntimeError("Unexpected LLM stream failure")
        yield ("messages", (AIMessage(content="fail"), {}))

    stream_ctx.agent.astream = fake_failing_astream

    executor = StreamExecutor(
        ctx=stream_ctx,
        fallback_llm=None,
        safety_fallback_llm=None,
        rebuild_agent_fn=MagicMock(),
    )

    try:
        await executor.execute()
    except Exception:
        pass

    assert mock_memory_manager.active_session.flush.called


@pytest.mark.asyncio
async def test_stream_executor_skips_flush_when_buffer_empty(
    stream_ctx, mock_memory_manager
):
    """Verify that StreamExecutor skips flush if buffer is empty (0 I/O overhead)."""
    mock_memory_manager.active_session.buffer_size = 0

    async def fake_astream(*args, **kwargs):
        yield ("messages", (AIMessage(content="Hello!"), {"tags": []}))

    stream_ctx.agent.astream = fake_astream

    executor = StreamExecutor(
        ctx=stream_ctx,
        fallback_llm=None,
        safety_fallback_llm=None,
        rebuild_agent_fn=MagicMock(),
    )

    await executor.execute()

    assert not mock_memory_manager.active_session.flush.called
