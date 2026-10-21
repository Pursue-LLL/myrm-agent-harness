"""Tests for StreamExecutor._handle_iteration_limit with grace-call summary."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.streaming.stream_executor import (
    StreamContext,
    StreamExecutor,
)
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

    await executor._handle_iteration_limit(GraphRecursionError("Recursion limit reached"), list(_SAMPLE_MESSAGES))
    await executor._compactor.flush()

    events: list[dict[str, object]] = []
    while not ctx.output_queue.empty():
        events.append(await ctx.output_queue.get())

    limit_events = [e for e in events if e["type"] == AgentEventType.ITERATION_LIMIT_REACHED.value]
    assert len(limit_events) == 1
    assert limit_events[0]["data"]["limit"] == 80
    assert limit_events[0]["data"]["nodes_completed"] == 35
    # Recursion limit is an engine pipeline guard, not a tool/model failure.
    assert limit_events[0]["data"]["fault_side"] == "harness_pipeline"

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

    await executor._handle_iteration_limit(GraphRecursionError("limit"), list(_SAMPLE_MESSAGES))
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

    await executor._handle_iteration_limit(GraphRecursionError("limit"), list(_SAMPLE_MESSAGES))
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

    result = await executor._handle_iteration_limit(ValueError("some other error"), list(_SAMPLE_MESSAGES))
    assert result is False

    result = await executor._handle_iteration_limit(RuntimeError("runtime error"), list(_SAMPLE_MESSAGES))
    assert result is False

    assert ctx.output_queue.empty()


@pytest.mark.asyncio
async def test_grace_fallback_zh_locale():
    """Chinese locale should produce Chinese fallback text."""
    from langgraph.errors import GraphRecursionError

    ctx = _make_ctx(recursion_limit=50, node_count=49, locale="zh-CN")
    executor = _make_executor(ctx)

    await executor._handle_iteration_limit(GraphRecursionError("limit"), list(_SAMPLE_MESSAGES))
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


@pytest.mark.asyncio
async def test_grace_call_repairs_dangling_tool_calls_before_llm_invoke():
    """Grace summary must patch dangling tool_calls (MiniMax 2013 without repair)."""
    from langchain_core.messages import ToolMessage
    from langgraph.errors import GraphRecursionError

    dangling_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_dangle_1",
                "name": "bash_code_execute_tool",
                "args": {"command": "ls"},
            }
        ],
    )
    messages_with_dangling: list[HumanMessage | AIMessage | ToolMessage] = [
        HumanMessage(content="query tickets"),
        dangling_ai,
    ]

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="Progress summary with G1234 train info.")

    ctx = _make_ctx(recursion_limit=50, node_count=49, llm=mock_llm)
    executor = _make_executor(ctx)

    await executor._handle_iteration_limit(GraphRecursionError("limit"), list(messages_with_dangling))

    mock_llm.ainvoke.assert_awaited_once()
    sent_messages = mock_llm.ainvoke.await_args.args[0]
    tool_messages = [m for m in sent_messages if getattr(m, "type", None) == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call_dangle_1"


@pytest.mark.asyncio
async def test_grace_call_drops_leading_orphan_tool_in_tail_slice():
    """Tail slice must drop leading ToolMessages whose AIMessage was truncated away."""
    from langchain_core.messages import ToolMessage
    from langgraph.errors import GraphRecursionError

    prefix = [HumanMessage(content=f"turn-{idx}") for idx in range(18)]
    owner_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_orphan_tool",
                "name": "file_read_tool",
                "args": {"paths": ["/a.md"]},
            }
        ],
    )
    orphan_tool = ToolMessage(content="ok", tool_call_id="call_orphan_tool", name="file_read_tool")
    suffix = [HumanMessage(content=f"tail-{idx}") for idx in range(19)]
    messages = [*prefix, owner_ai, orphan_tool, *suffix]

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="Tail summary.")

    ctx = _make_ctx(recursion_limit=50, node_count=49, llm=mock_llm)
    executor = _make_executor(ctx)

    await executor._handle_iteration_limit(GraphRecursionError("limit"), messages)

    sent_messages = mock_llm.ainvoke.await_args.args[0]
    assert all(getattr(m, "type", None) != "tool" for m in sent_messages[:-1])
    assert sent_messages[-1].type == "human"


@pytest.mark.asyncio
async def test_grace_prompt_preserves_prior_external_results():
    """Grace prompt must instruct the LLM to faithfully summarize prior MCP/web
    results instead of denying they were called."""
    from langgraph.errors import GraphRecursionError

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="Summary.")

    ctx = _make_ctx(recursion_limit=50, node_count=49, llm=mock_llm)
    executor = _make_executor(ctx)

    await executor._handle_iteration_limit(GraphRecursionError("limit"), list(_SAMPLE_MESSAGES))

    sent_messages = mock_llm.ainvoke.await_args.args[0]
    grace_prompt = sent_messages[-1]
    content = grace_prompt.content if isinstance(grace_prompt.content, str) else ""
    assert "maximum iteration limit" in content
    assert "Do NOT call any tools" in content
    assert "successful MCP, web search" in content
    assert "do not claim tools were not called" in content


@pytest.mark.asyncio
async def test_grace_prompt_locale_driven_language_instruction():
    """Grace prompt must ask for the same language as the conversation."""
    from langgraph.errors import GraphRecursionError

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="总结。")

    ctx = _make_ctx(recursion_limit=50, node_count=49, llm=mock_llm)
    executor = _make_executor(ctx)

    await executor._handle_iteration_limit(GraphRecursionError("limit"), list(_SAMPLE_MESSAGES))

    sent_messages = mock_llm.ainvoke.await_args.args[0]
    content = sent_messages[-1].content
    assert isinstance(content, str)
    assert "same language as the conversation" in content
