"""Tests for StreamExecutor._handle_iteration_limit with grace-call summary."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.types import AgentRunStatistics

_SAMPLE_MESSAGES: list[HumanMessage | AIMessage] = [
    HumanMessage(content="Find me a train ticket"),
    AIMessage(content="Searching for trains..."),
]


def _make_ctx(
    recursion_limit: int = 100,
    node_count: int = 42,
    *,
    llm: AsyncMock | None = None,
    locale: str = "en",
) -> StreamContext:
    """Build a minimal StreamContext for iteration-limit tests."""
    queue: asyncio.Queue[dict[str, object] | object] = asyncio.Queue()
    stats = AgentRunStatistics()
    stats.node_execution_count = node_count

    return StreamContext(
        agent=MagicMock(),
        agent_input={"messages": []},
        merged_context={"locale": locale},
        run_config={"recursion_limit": recursion_limit},
        stats=stats,
        message_id="test-msg-1",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=queue,
        llm=llm,
    )


def _make_executor(ctx: StreamContext) -> StreamExecutor:
    return StreamExecutor(
        ctx=ctx,
        fallback_llm=None,
        rebuild_agent_fn=MagicMock(),
        safety_fallback_llm=None,
    )


@pytest.mark.asyncio
async def test_handle_iteration_limit_recognizes_graph_recursion_error():
    """GraphRecursionError should be recognized and return True."""
    from langgraph.errors import GraphRecursionError

    ctx = _make_ctx(recursion_limit=100, node_count=42)
    executor = _make_executor(ctx)

    result = await executor._handle_iteration_limit(
        GraphRecursionError("Recursion limit reached"), list(_SAMPLE_MESSAGES)
    )
    assert result is True


@pytest.mark.asyncio
async def test_handle_iteration_limit_emits_event_and_grace_fallback():
    """ITERATION_LIMIT_REACHED + grace fallback events when no LLM is available."""
    from langgraph.errors import GraphRecursionError

    ctx = _make_ctx(recursion_limit=80, node_count=35)
    executor = _make_executor(ctx)

    await executor._handle_iteration_limit(
        GraphRecursionError("Recursion limit reached"), list(_SAMPLE_MESSAGES)
    )
    await executor._compactor.flush()

    events: list[dict[str, object]] = []
    while not ctx.output_queue.empty():
        events.append(await ctx.output_queue.get())

    limit_events = [e for e in events if e["type"] == AgentEventType.ITERATION_LIMIT_REACHED.value]
    assert len(limit_events) == 1
    assert limit_events[0]["data"]["limit"] == 80
    assert limit_events[0]["data"]["nodes_completed"] == 35

    msg_events = [e for e in events if e["type"] == AgentEventType.MESSAGE.value]
    assert len(msg_events) == 1
    assert "iteration limit" in msg_events[0]["data"].lower()


@pytest.mark.asyncio
async def test_grace_call_uses_llm_summary():
    """When LLM is available, grace call should produce an LLM-generated summary."""
    from langgraph.errors import GraphRecursionError

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="Here is a summary of progress so far.")

    ctx = _make_ctx(recursion_limit=50, node_count=49, llm=mock_llm)
    executor = _make_executor(ctx)

    await executor._handle_iteration_limit(
        GraphRecursionError("limit"), list(_SAMPLE_MESSAGES)
    )
    await executor._compactor.flush()

    events: list[dict[str, object]] = []
    while not ctx.output_queue.empty():
        events.append(await ctx.output_queue.get())

    msg_events = [e for e in events if e["type"] == AgentEventType.MESSAGE.value]
    assert len(msg_events) == 1
    assert msg_events[0]["data"] == "Here is a summary of progress so far."

    mock_llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_grace_call_falls_back_on_llm_error():
    """If LLM invocation fails, fallback message should be emitted."""
    from langgraph.errors import GraphRecursionError

    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = RuntimeError("LLM unavailable")

    ctx = _make_ctx(recursion_limit=50, node_count=49, llm=mock_llm)
    executor = _make_executor(ctx)

    await executor._handle_iteration_limit(
        GraphRecursionError("limit"), list(_SAMPLE_MESSAGES)
    )
    await executor._compactor.flush()

    events: list[dict[str, object]] = []
    while not ctx.output_queue.empty():
        events.append(await ctx.output_queue.get())

    msg_events = [e for e in events if e["type"] == AgentEventType.MESSAGE.value]
    assert len(msg_events) == 1
    assert "iteration limit" in msg_events[0]["data"].lower()


@pytest.mark.asyncio
async def test_handle_iteration_limit_ignores_other_exceptions():
    """Non-GraphRecursionError exceptions should return False."""
    ctx = _make_ctx()
    executor = _make_executor(ctx)

    result = await executor._handle_iteration_limit(
        ValueError("some other error"), list(_SAMPLE_MESSAGES)
    )
    assert result is False

    result = await executor._handle_iteration_limit(
        RuntimeError("runtime error"), list(_SAMPLE_MESSAGES)
    )
    assert result is False

    assert ctx.output_queue.empty()


@pytest.mark.asyncio
async def test_grace_fallback_zh_locale():
    """Chinese locale should produce Chinese fallback text."""
    from langgraph.errors import GraphRecursionError

    ctx = _make_ctx(recursion_limit=50, node_count=49, locale="zh-CN")
    executor = _make_executor(ctx)

    await executor._handle_iteration_limit(
        GraphRecursionError("limit"), list(_SAMPLE_MESSAGES)
    )
    await executor._compactor.flush()

    events: list[dict[str, object]] = []
    while not ctx.output_queue.empty():
        events.append(await ctx.output_queue.get())

    msg_events = [e for e in events if e["type"] == AgentEventType.MESSAGE.value]
    assert len(msg_events) == 1
    assert "迭代上限" in msg_events[0]["data"]


@pytest.mark.asyncio
async def test_iteration_limit_reached_event_type_exists():
    """Verify ITERATION_LIMIT_REACHED is a valid AgentEventType."""
    assert hasattr(AgentEventType, "ITERATION_LIMIT_REACHED")
    assert AgentEventType.ITERATION_LIMIT_REACHED.value == "iteration_limit_reached"
