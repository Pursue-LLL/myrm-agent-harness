"""stream_dispatcher.py (StreamDispatcherMixin) 测试。

覆盖：
- _dispatch_chunk 路由（AgentStreamEvent / updates / messages / custom）
- _emit_event 写入 compactor + event_logger
- _dispatch_custom 的三种 event_name
- _dispatch_updates 处理 __interrupt__
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor
from myrm_agent_harness.agent.streaming.types import AgentEventType, AgentStreamEvent
from myrm_agent_harness.agent.types import AgentRunStatistics


class FakeCompactor:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def put(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        pass


@pytest.fixture
def ctx():
    stats = AgentRunStatistics()
    return StreamContext(
        agent=MagicMock(),
        agent_input={"messages": []},
        merged_context={"locale": "en"},
        run_config={},
        stats=stats,
        message_id="disp_test",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
        event_logger=None,
    )


def _make_executor(ctx: StreamContext) -> StreamExecutor:
    executor = StreamExecutor(
        ctx=ctx, fallback_llm=None, safety_fallback_llm=None, rebuild_agent_fn=MagicMock()
    )
    executor._compactor = FakeCompactor()
    return executor


@pytest.mark.asyncio
async def test_dispatch_chunk_agent_stream_event(ctx):
    """AgentStreamEvent objects are routed to _emit_event directly."""
    executor = _make_executor(ctx)
    event = AgentStreamEvent(type=AgentEventType.STATUS, messageId="disp_test")

    await executor._dispatch_chunk(event, ctx, [])

    assert len(executor._compactor.events) == 1


@pytest.mark.asyncio
async def test_dispatch_chunk_tuple_with_agent_stream_event(ctx):
    """Tuple (stream_mode, AgentStreamEvent) routes to _emit_event."""
    executor = _make_executor(ctx)
    event = AgentStreamEvent(type=AgentEventType.TOKEN_USAGE, messageId="disp_test")
    chunk = ("messages", event)

    await executor._dispatch_chunk(chunk, ctx, [])

    assert len(executor._compactor.events) == 1


@pytest.mark.asyncio
async def test_dispatch_custom_tool_stdout(ctx):
    """Custom event with name='tool_stdout_chunk' dispatches TOOL_STDOUT_CHUNK."""
    executor = _make_executor(ctx)
    data = {"name": "tool_stdout_chunk", "data": {"chunk": "hello output"}}
    chunk = ("custom", data)

    await executor._dispatch_chunk(chunk, ctx, [])

    events = executor._compactor.events
    assert len(events) >= 1
    event = events[0]
    assert isinstance(event, AgentStreamEvent)
    assert event.type == AgentEventType.TOOL_STDOUT_CHUNK


@pytest.mark.asyncio
async def test_dispatch_custom_tasks_steps(ctx):
    """Custom event with name='tasks_steps' dispatches TASKS_STEPS."""
    executor = _make_executor(ctx)
    data = {"name": "tasks_steps", "data": {"steps": ["step1"]}}
    chunk = ("custom", data)

    await executor._dispatch_chunk(chunk, ctx, [])

    events = executor._compactor.events
    assert any(isinstance(e, AgentStreamEvent) and e.type == AgentEventType.TASKS_STEPS for e in events)


@pytest.mark.asyncio
async def test_dispatch_custom_agent_status(ctx):
    """Custom event with name='agent_status' dispatches STATUS."""
    executor = _make_executor(ctx)
    data = {"name": "agent_status", "data": {"step_key": "custom_step"}}
    chunk = ("custom", data)

    await executor._dispatch_chunk(chunk, ctx, [])

    events = executor._compactor.events
    assert any(isinstance(e, AgentStreamEvent) and e.type == AgentEventType.STATUS for e in events)


@pytest.mark.asyncio
async def test_dispatch_custom_capability_gap(ctx):
    """Custom event with name='capability_gap' dispatches CAPABILITY_GAP."""
    executor = _make_executor(ctx)
    payload = {"tool_id": "browser", "tool_group": "browser"}
    data = {"name": "capability_gap", "data": payload}
    chunk = ("custom", data)

    await executor._dispatch_chunk(chunk, ctx, [])

    events = executor._compactor.events
    gap_events = [
        e for e in events if isinstance(e, AgentStreamEvent) and e.type == AgentEventType.CAPABILITY_GAP
    ]
    assert len(gap_events) == 1
    assert gap_events[0].data == payload


@pytest.mark.asyncio
async def test_dispatch_custom_skill_gap(ctx):
    """Custom event with name='skill_gap' dispatches SKILL_GAP."""
    executor = _make_executor(ctx)
    payload = {"skill_id": "github_pr_skill"}
    data = {"name": "skill_gap", "data": payload}
    chunk = ("custom", data)

    await executor._dispatch_chunk(chunk, ctx, [])

    events = executor._compactor.events
    gap_events = [
        e for e in events if isinstance(e, AgentStreamEvent) and e.type == AgentEventType.SKILL_GAP
    ]
    assert len(gap_events) == 1
    assert gap_events[0].data == payload


@pytest.mark.asyncio
async def test_emit_event_with_event_logger(ctx):
    """_emit_event logs to event_logger when present."""
    mock_logger = AsyncMock()
    mock_logger.log = AsyncMock()
    ctx.event_logger = mock_logger

    executor = _make_executor(ctx)
    event = {"type": AgentEventType.STATUS.value, "step_key": "test_step", "messageId": "disp_test"}

    await executor._emit_event(event, ctx)

    mock_logger.log.assert_called_once()
    call_args = mock_logger.log.call_args
    assert call_args[0][0] == AgentEventType.STATUS.value


@pytest.mark.asyncio
async def test_dispatch_updates_interrupt(ctx):
    """__interrupt__ in updates data dispatches APPROVAL_REQUIRED."""
    executor = _make_executor(ctx)

    interrupt_obj = MagicMock()
    interrupt_obj.value = {"tool_name": "dangerous_tool", "args": {}}
    data = {"__interrupt__": (interrupt_obj,)}
    chunk = ("updates", data)

    await executor._dispatch_chunk(chunk, ctx, [])

    events = executor._compactor.events
    assert any(isinstance(e, AgentStreamEvent) and e.type == AgentEventType.APPROVAL_REQUIRED for e in events)


@pytest.mark.asyncio
async def test_dispatch_updates_interrupt_clarification(ctx):
    """__interrupt__ with type='ask_question' dispatches CLARIFICATION_REQUIRED."""
    executor = _make_executor(ctx)

    interrupt_obj = MagicMock()
    interrupt_obj.value = {
        "type": "ask_question",
        "form": {
            "title": "Research Direction",
            "questions": [
                {
                    "id": "q1",
                    "prompt": "Which area to focus?",
                    "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                }
            ],
        },
    }
    data = {"__interrupt__": (interrupt_obj,)}
    chunk = ("updates", data)

    await executor._dispatch_chunk(chunk, ctx, [])

    events = executor._compactor.events
    clarify_events = [
        e for e in events
        if isinstance(e, AgentStreamEvent) and e.type == AgentEventType.CLARIFICATION_REQUIRED
    ]
    assert len(clarify_events) == 1
    event_data = clarify_events[0].to_dict().get("data", {})
    assert event_data.get("type") == "ask_question"


@pytest.mark.asyncio
async def test_dispatch_updates_interrupt_empty_tuple(ctx):
    """Empty __interrupt__ tuple is silently ignored."""
    executor = _make_executor(ctx)

    data = {"__interrupt__": ()}
    chunk = ("updates", data)

    await executor._dispatch_chunk(chunk, ctx, [])

    assert len(executor._compactor.events) == 0


@pytest.mark.asyncio
async def test_dispatch_updates_interrupt_non_dict_value(ctx):
    """__interrupt__ with non-dict value dispatches APPROVAL_REQUIRED (default branch)."""
    executor = _make_executor(ctx)

    interrupt_obj = MagicMock()
    interrupt_obj.value = "string_value"
    data = {"__interrupt__": (interrupt_obj,)}
    chunk = ("updates", data)

    await executor._dispatch_chunk(chunk, ctx, [])

    assert len(executor._compactor.events) == 0


@pytest.mark.asyncio
async def test_dispatch_messages_token_events(ctx):
    """Messages stream mode + pending token events dispatches TOKEN_USAGE."""
    executor = _make_executor(ctx)

    msg_mock = AIMessage(content="hi")
    metadata_mock = MagicMock()
    metadata_mock.tags = []
    chunk = ("messages", (msg_mock, metadata_mock))

    token_event = {"input_tokens": 100, "output_tokens": 50}

    with (
        patch(
            "myrm_agent_harness.agent.streaming.stream_dispatcher.process_messages_chunk",
            return_value=[
                ({"type": AgentEventType.MESSAGE.value, "data": "hi", "messageId": "disp_test"}, False)
            ],
        ),
        patch(
            "myrm_agent_harness.agent.streaming.stream_dispatcher.get_pending_token_events",
            return_value=[token_event],
        ),
        patch(
            "myrm_agent_harness.agent.streaming.stream_dispatcher.get_pending_privacy_event",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.streaming.stream_dispatcher.get_pending_route_event",
            return_value=None,
        ),
    ):
        await executor._dispatch_chunk(chunk, ctx, [])

    events = executor._compactor.events
    token_usage_events = [e for e in events if isinstance(e, AgentStreamEvent) and e.type == AgentEventType.TOKEN_USAGE]
    assert len(token_usage_events) >= 1
