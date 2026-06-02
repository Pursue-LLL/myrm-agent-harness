"""stream_recovery.py 的 overflow / failover / steering / subagent 测试。

补充覆盖 stream_recovery.py 中 _handle_overflow、_handle_failover、
_handle_steering、_handle_subagent_notifications 等方法。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor
from myrm_agent_harness.agent.streaming.stream_recovery import _extract_retry_after_ms
from myrm_agent_harness.agent.streaming.types import AgentEventType
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
        agent_input={"messages": [HumanMessage(content="test")]},
        merged_context={"locale": "en"},
        run_config={},
        stats=stats,
        message_id="recovery_test",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
    )


def _make_executor(ctx: StreamContext) -> StreamExecutor:
    executor = StreamExecutor(
        ctx=ctx, fallback_llm=None, safety_fallback_llm=None, rebuild_agent_fn=MagicMock()
    )
    executor._compactor = FakeCompactor()
    return executor


# ─── _extract_retry_after_ms ─────────────────────────────────────────────────

class TestExtractRetryAfterMs:
    def test_from_header(self):
        exc = Exception("rate limited")
        exc.headers = {"Retry-After": "30"}
        assert _extract_retry_after_ms(exc) == 30000

    def test_from_response_headers(self):
        exc = Exception("rate limited")
        exc.response_headers = {"retry-after": "5.5"}
        assert _extract_retry_after_ms(exc) == 5500

    def test_from_error_message(self):
        exc = Exception("Please retry after 10 seconds")
        assert _extract_retry_after_ms(exc) == 10000

    def test_no_retry_info(self):
        exc = Exception("random error")
        assert _extract_retry_after_ms(exc) is None


# ─── _handle_overflow ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_overflow_not_overflow_error(ctx):
    """Non-overflow errors are not handled."""
    executor = _make_executor(ctx)
    exc = RuntimeError("not overflow")

    with patch(
        "myrm_agent_harness.agent.streaming.stream_recovery.is_context_overflow",
        return_value=False,
    ):
        result = await executor._handle_overflow(exc, 0)

    assert result is False


@pytest.mark.asyncio
async def test_overflow_retries_exhausted(ctx):
    """When retries >= MAX, marks compression_exhausted."""
    executor = _make_executor(ctx)
    exc = RuntimeError("context length exceeded")

    with patch(
        "myrm_agent_harness.agent.streaming.stream_recovery.is_context_overflow",
        return_value=True,
    ):
        result = await executor._handle_overflow(exc, 2)

    assert result is False
    assert ctx.stats.compression_exhausted is True


@pytest.mark.asyncio
async def test_overflow_stage1_compact(ctx):
    """Stage 1 (retries=0): calls _emergency_compact."""
    executor = _make_executor(ctx)
    exc = RuntimeError("context length exceeded")

    with (
        patch(
            "myrm_agent_harness.agent.streaming.stream_recovery.is_context_overflow",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.streaming.stream_recovery._emergency_compact",
            new_callable=AsyncMock,
            return_value=500,
        ) as compact_mock,
    ):
        result = await executor._handle_overflow(exc, 0)

    assert result is True
    compact_mock.assert_called_once()
    events = executor._compactor.events
    status_events = [e for e in events if isinstance(e, dict) and e.get("step_key") == "context_compaction"]
    assert len(status_events) == 1


@pytest.mark.asyncio
async def test_overflow_stage1_fallthrough_to_truncate(ctx):
    """Stage 1 with saved=0 falls through to truncation."""
    executor = _make_executor(ctx)
    exc = RuntimeError("context length exceeded")

    with (
        patch(
            "myrm_agent_harness.agent.streaming.stream_recovery.is_context_overflow",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.streaming.stream_recovery._emergency_compact",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "myrm_agent_harness.agent.streaming.stream_recovery._truncate_oldest_rounds",
            return_value=200,
        ) as truncate_mock,
    ):
        result = await executor._handle_overflow(exc, 0)

    assert result is True
    truncate_mock.assert_called_once()
    events = executor._compactor.events
    status_events = [e for e in events if isinstance(e, dict) and e.get("step_key") == "context_truncation"]
    assert len(status_events) == 1


@pytest.mark.asyncio
async def test_overflow_resume_mode_rejected(ctx):
    """Resume mode (Command) cannot be compacted."""
    ctx.agent_input = Command(resume="some_value")
    executor = _make_executor(ctx)
    exc = RuntimeError("context length exceeded")

    with patch(
        "myrm_agent_harness.agent.streaming.stream_recovery.is_context_overflow",
        return_value=True,
    ):
        result = await executor._handle_overflow(exc, 0)

    assert result is False


# ─── _handle_failover ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failover_no_fallback(ctx):
    """No fallback LLM → failover not triggered."""
    executor = _make_executor(ctx)
    exc = RuntimeError("model error")

    from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind

    with patch(
        "myrm_agent_harness.agent.streaming.stream_recovery.classify_error",
        return_value=ErrorKind.RATE_LIMIT,
    ):
        result = await executor._handle_failover(exc)

    assert result is False


@pytest.mark.asyncio
async def test_failover_success(ctx):
    """Failover with available fallback LLM succeeds."""
    fallback_llm = MagicMock()
    fallback_llm.model_name = "gpt-4o-mini"
    rebuild_fn = MagicMock()

    executor = StreamExecutor(
        ctx=ctx, fallback_llm=fallback_llm, safety_fallback_llm=None, rebuild_agent_fn=rebuild_fn
    )
    executor._compactor = FakeCompactor()

    exc = RuntimeError("model error")

    from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind

    with patch(
        "myrm_agent_harness.agent.streaming.stream_recovery.classify_error",
        return_value=ErrorKind.RATE_LIMIT,
    ):
        result = await executor._handle_failover(exc)

    assert result is True
    assert executor.failover_used is True
    rebuild_fn.assert_called_once_with(fallback_llm)

    events = executor._compactor.events
    failover_events = [e for e in events if isinstance(e, dict) and e.get("step_key") == "model_failover"]
    assert len(failover_events) == 1
    assert failover_events[0]["fallback_model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_failover_already_used(ctx):
    """Failover cannot be used twice."""
    fallback_llm = MagicMock()
    executor = StreamExecutor(
        ctx=ctx, fallback_llm=fallback_llm, safety_fallback_llm=None, rebuild_agent_fn=MagicMock()
    )
    executor._compactor = FakeCompactor()
    executor.failover_used = True

    from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind

    with patch(
        "myrm_agent_harness.agent.streaming.stream_recovery.classify_error",
        return_value=ErrorKind.RATE_LIMIT,
    ):
        result = await executor._handle_failover(RuntimeError("error"))

    assert result is False


@pytest.mark.asyncio
async def test_safety_fallback(ctx):
    """Safety block error triggers safety_fallback_llm."""
    safety_llm = MagicMock()
    safety_llm.model_name = "claude-safe"
    rebuild_fn = MagicMock()

    executor = StreamExecutor(
        ctx=ctx, fallback_llm=None, safety_fallback_llm=safety_llm, rebuild_agent_fn=rebuild_fn
    )
    executor._compactor = FakeCompactor()

    from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind

    with patch(
        "myrm_agent_harness.agent.streaming.stream_recovery.classify_error",
        return_value=ErrorKind.SAFETY_BLOCK,
    ):
        result = await executor._handle_failover(RuntimeError("content blocked"))

    assert result is True
    rebuild_fn.assert_called_once_with(safety_llm)
    events = executor._compactor.events
    assert any(e.get("step_key") == "safety_fallback_active" for e in events if isinstance(e, dict))


# ─── _handle_steering ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_steering_injection(ctx):
    """Steering token with pending messages injects new HumanMessage."""
    steering = MagicMock()
    steering.steering_applied = True
    steering.has_pending = True
    steering.collect_all_steering_messages.return_value = ["Do this instead"]
    ctx.steering_token = steering

    executor = _make_executor(ctx)
    collected = [AIMessage(content="previous response")]

    result = await executor._handle_steering(collected)

    assert result is True
    messages = ctx.agent_input["messages"]
    assert any(isinstance(m, HumanMessage) and "Do this instead" in m.content for m in messages)


@pytest.mark.asyncio
async def test_steering_no_pending(ctx):
    """No pending steering → returns False."""
    steering = MagicMock()
    steering.steering_applied = False
    steering.has_pending = False
    ctx.steering_token = steering

    executor = _make_executor(ctx)
    result = await executor._handle_steering([])

    assert result is False


@pytest.mark.asyncio
async def test_steering_resume_mode(ctx):
    """Resume mode (Command) rejects steering."""
    ctx.agent_input = Command(resume="val")
    steering = MagicMock()
    steering.steering_applied = True
    steering.has_pending = True
    steering.collect_all_steering_messages.return_value = ["msg"]
    ctx.steering_token = steering

    executor = _make_executor(ctx)
    result = await executor._handle_steering([])

    assert result is False


# ─── _handle_subagent_notifications ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_subagent_notifications_emits_event(ctx):
    """Subagent notification emits SUBAGENT_COMPLETION event."""
    ctx.drain_subagent_notifications = lambda: "Task done: summary"

    executor = _make_executor(ctx)
    result = await executor._handle_subagent_notifications([])

    assert result is False  # Does not trigger new iteration
    events = executor._compactor.events
    subagent_events = [
        e for e in events if isinstance(e, dict) and e.get("type") == AgentEventType.SUBAGENT_COMPLETION.value
    ]
    assert len(subagent_events) == 1


@pytest.mark.asyncio
async def test_subagent_notifications_none_returns_false(ctx):
    """No notification data → returns False without emitting."""
    ctx.drain_subagent_notifications = lambda: None

    executor = _make_executor(ctx)
    result = await executor._handle_subagent_notifications([])

    assert result is False
    assert len(executor._compactor.events) == 0


@pytest.mark.asyncio
async def test_subagent_notifications_no_callback(ctx):
    """No drain callback → returns False."""
    ctx.drain_subagent_notifications = None

    executor = _make_executor(ctx)
    result = await executor._handle_subagent_notifications([])

    assert result is False


@pytest.mark.asyncio
async def test_subagent_notifications_resume_mode(ctx):
    """Resume mode (Command) → returns False."""
    ctx.agent_input = Command(resume="val")
    ctx.drain_subagent_notifications = lambda: "something"

    executor = _make_executor(ctx)
    result = await executor._handle_subagent_notifications([])

    assert result is False


# ─── _emit_recovery_event ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_recovery_event(ctx):
    """_emit_recovery_event puts a STATUS dict into compactor."""
    executor = _make_executor(ctx)
    await executor._emit_recovery_event("test_step", extra_field="value")

    events = executor._compactor.events
    assert len(events) == 1
    assert events[0]["type"] == AgentEventType.STATUS.value
    assert events[0]["step_key"] == "test_step"
    assert events[0]["extra_field"] == "value"
