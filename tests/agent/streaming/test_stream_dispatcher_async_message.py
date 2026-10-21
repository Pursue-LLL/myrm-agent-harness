"""Tests for stream_dispatcher async_user_message event dispatching."""

import asyncio
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.streaming.stream_executor import (
    StreamContext,
    StreamExecutor,
)
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
def ctx() -> StreamContext:
    stats = AgentRunStatistics()
    return StreamContext(
        agent=MagicMock(),
        agent_input={"messages": []},
        merged_context={"locale": "en"},
        run_config={},
        stats=stats,
        message_id="async_msg_disp_test",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
        event_logger=None,
    )


def _make_executor(ctx: StreamContext) -> StreamExecutor:
    executor = StreamExecutor(
        ctx=ctx,
        fallback_llm=None,
        safety_fallback_llm=None,
        rebuild_agent_fn=MagicMock(),
    )
    executor._compactor = FakeCompactor()
    return executor


@pytest.mark.asyncio
async def test_dispatch_custom_async_user_message(ctx: StreamContext) -> None:
    """Custom event with name='async_user_message' dispatches ASYNC_USER_MESSAGE."""
    executor = _make_executor(ctx)
    data = {
        "name": "async_user_message",
        "data": {
            "title": "Need clarification",
            "message": "Should I proceed with delete?",
            "suggested_replies": ["Yes", "No"],
        },
    }
    chunk = ("custom", data)

    await executor._dispatch_chunk(chunk, ctx, [])

    events = executor._compactor.events
    assert len(events) >= 1
    event = events[0]
    assert isinstance(event, AgentStreamEvent)
    assert event.type == AgentEventType.ASYNC_USER_MESSAGE
    assert event.data == {
        "title": "Need clarification",
        "message": "Should I proceed with delete?",
        "suggested_replies": ["Yes", "No"],
    }
    assert event.messageId == "async_msg_disp_test"
