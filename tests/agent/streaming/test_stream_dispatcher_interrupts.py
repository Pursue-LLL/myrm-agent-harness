"""stream_dispatcher.py (StreamDispatcherMixin) 对 __interrupt__ 分片的处理测试。

覆盖：
- 不同形态的中断分发为对应事件（工具审批 / 审批 / 澄清）；空元组与非 dict 值被忽略
- 同一分片里的每个中断各带自己的卡片 id；恢复运行按 `AddressedResume` 给出的轮次盖章，未寻址的恢复不带 id
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from langgraph.types import Command

from myrm_agent_harness.agent.streaming.interrupt_identity import AddressedResume
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
def ctx():
    return StreamContext(
        agent=MagicMock(),
        agent_input={"messages": []},
        merged_context={"locale": "en"},
        run_config={},
        stats=AgentRunStatistics(),
        message_id="disp_interrupt_test",
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
async def test_dispatch_updates_interrupt_tool_approval(ctx):
    """__interrupt__ with actionRequests dispatches TOOL_APPROVAL_REQUEST."""
    executor = _make_executor(ctx)

    interrupt_obj = MagicMock()
    interrupt_obj.value = {
        "actionRequests": [
            {
                "action": "bash_code_execute_tool",
                "args": {"command": "curl example.com"},
            }
        ],
        "reviewConfigs": [{"type": "shell_exec"}],
        "extensions": {"approval": {"requestId": "req-1"}},
    }
    data = {"__interrupt__": (interrupt_obj,)}
    chunk = ("updates", data)

    await executor._dispatch_chunk(chunk, ctx, [])

    events = executor._compactor.events
    assert any(isinstance(e, AgentStreamEvent) and e.type == AgentEventType.TOOL_APPROVAL_REQUEST for e in events)


@pytest.mark.asyncio
async def test_dispatch_updates_announces_every_interrupt_of_a_chunk_with_its_id(ctx):
    """Parallel tool calls that each ask for approval are each a card the client can answer on its own."""
    executor = _make_executor(ctx)
    first = MagicMock(value={"actionRequests": [{"action": "alpha"}]}, id="id-a")
    second = MagicMock(value={"actionRequests": [{"action": "beta"}]}, id="id-b")

    await executor._dispatch_chunk(("updates", {"__interrupt__": (first, second)}), ctx, [])

    announced = [
        (e.data["actionRequests"][0]["action"], e.extra_data["interruptId"]) for e in executor._compactor.events
    ]
    assert announced == [("alpha", "id-a.0"), ("beta", "id-b.0")]


@pytest.mark.asyncio
async def test_dispatch_updates_stamps_the_rounds_the_resume_was_addressed_at(ctx):
    """A resumed run announces the pause its answer unlocked one round later than the one it answered."""
    ctx.agent_input = AddressedResume(resume={}, announce_rounds={"id-a": 2, "id-b": 1})
    executor = _make_executor(ctx)
    first = MagicMock(value={"actionRequests": [{"action": "alpha"}]}, id="id-a")
    second = MagicMock(value={"actionRequests": [{"action": "beta"}]}, id="id-b")
    new_task = MagicMock(value={"actionRequests": [{"action": "gamma"}]}, id="id-c")

    await executor._dispatch_chunk(("updates", {"__interrupt__": (first, second, new_task)}), ctx, [])

    assert [e.extra_data["interruptId"] for e in executor._compactor.events] == ["id-a.2", "id-b.1", "id-c.0"]


@pytest.mark.asyncio
async def test_dispatch_updates_gives_no_card_id_when_the_resume_was_not_addressed(ctx):
    ctx.agent_input = Command(resume={"answer": "yes"})
    executor = _make_executor(ctx)
    pause = MagicMock(value={"actionRequests": [{"action": "alpha"}]}, id="id-a")

    await executor._dispatch_chunk(("updates", {"__interrupt__": (pause,)}), ctx, [])

    assert "interruptId" not in executor._compactor.events[0].extra_data


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
        e for e in events if isinstance(e, AgentStreamEvent) and e.type == AgentEventType.CLARIFICATION_REQUIRED
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
