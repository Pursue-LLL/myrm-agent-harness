"""Tests for stream_recovery.py — escalation, transient retry, iteration limit, empty response.

Covers:
- _handle_escalation (full flow + edge cases)
- _handle_transient_retry (backoff, exhaustion, cancel)
- _handle_iteration_limit (GraphRecursionError detection)
- _handle_empty_response (injection, exhaustion, resume mode)
- _is_escalation_marker_message (helper function)
- _extract_retry_after_ms edge cases (invalid header values)
- _handle_overflow stage 2 (retries==1)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor
from myrm_agent_harness.agent.streaming.stream_recovery import (
    _extract_retry_after_ms,
    _is_escalation_marker_message,
)
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


def _make_executor(
    ctx: StreamContext,
    fallback_llm: object | None = None,
    safety_fallback_llm: object | None = None,
) -> StreamExecutor:
    executor = StreamExecutor(
        ctx=ctx,
        fallback_llm=fallback_llm,
        safety_fallback_llm=safety_fallback_llm,
        rebuild_agent_fn=MagicMock(),
    )
    executor._compactor = FakeCompactor()
    return executor


# ─── _is_escalation_marker_message ───────────────────────────────────────────


class TestIsEscalationMarkerMessage:
    def test_ai_message_with_marker(self):
        msg = AIMessage(content="<<<NEEDS_PRO>>>")
        assert _is_escalation_marker_message(msg) is True

    def test_ai_message_with_marker_and_whitespace(self):
        msg = AIMessage(content="  <<<NEEDS_PRO>>>  \n")
        assert _is_escalation_marker_message(msg) is True

    def test_ai_message_with_reason(self):
        msg = AIMessage(content="<<<NEEDS_PRO: complex math>>>")
        assert _is_escalation_marker_message(msg) is True

    def test_ai_message_normal_content(self):
        msg = AIMessage(content="Hello, how can I help?")
        assert _is_escalation_marker_message(msg) is False

    def test_human_message_with_marker(self):
        msg = HumanMessage(content="<<<NEEDS_PRO>>>")
        assert _is_escalation_marker_message(msg) is False

    def test_ai_message_list_content(self):
        msg = AIMessage(content=[{"type": "text", "text": "hello"}])
        assert _is_escalation_marker_message(msg) is False

    def test_ai_message_empty(self):
        msg = AIMessage(content="")
        assert _is_escalation_marker_message(msg) is False


# ─── _extract_retry_after_ms edge cases ─────────────────────────────────────


class TestExtractRetryAfterEdgeCases:
    def test_invalid_header_value_nan(self):
        exc = Exception("error")
        exc.headers = {"Retry-After": "not-a-number"}
        assert _extract_retry_after_ms(exc) is None

    def test_overflow_header_value(self):
        exc = Exception("error")
        exc.headers = {"Retry-After": "1e999"}
        assert _extract_retry_after_ms(exc) is None

    def test_empty_headers_dict(self):
        exc = Exception("error")
        exc.headers = {}
        assert _extract_retry_after_ms(exc) is None


# ─── _handle_overflow stage 2 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overflow_stage2_truncation(ctx):
    """Stage 2 (retries==1) goes directly to truncation."""
    executor = _make_executor(ctx)
    exc = RuntimeError("context length exceeded")

    with (
        patch(
            "myrm_agent_harness.agent.streaming.stream_recovery.is_context_overflow",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.streaming.stream_recovery._truncate_oldest_rounds",
            return_value=300,
        ) as truncate_mock,
    ):
        result = await executor._handle_overflow(exc, 1)

    assert result is True
    truncate_mock.assert_called_once()


# ─── _handle_escalation ──────────────────────────────────────────────────────


class TestHandleEscalation:
    @pytest.fixture
    def escalation_ctx(self, ctx):
        target_llm = MagicMock()
        target_llm.model_name = "gpt-4o"
        ctx.escalation_target_llm = target_llm
        ctx.llm_info = {"model_name": "gpt-4o-mini"}
        return ctx

    @pytest.mark.asyncio
    async def test_escalation_success(self, escalation_ctx):
        """Full escalation flow: scrubber detected → switch model → emit event."""
        rebuild_fn = MagicMock()
        executor = StreamExecutor(
            ctx=escalation_ctx,
            fallback_llm=None,
            safety_fallback_llm=None,
            rebuild_agent_fn=rebuild_fn,
        )
        executor._compactor = FakeCompactor()

        scrubber = MagicMock()
        scrubber.detected = True
        scrubber.reason = "complex task"
        executor._escalation_scrubber = scrubber

        collected = [
            HumanMessage(content="Solve this"),
            AIMessage(content="<<<NEEDS_PRO>>>"),
        ]

        result = await executor._handle_escalation(collected)

        assert result is True
        assert executor._escalation_used is True
        rebuild_fn.assert_called_once_with(escalation_ctx.escalation_target_llm)
        events = executor._compactor.events
        escalation_events = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == AgentEventType.MODEL_ESCALATED.value
        ]
        assert len(escalation_events) == 1
        assert escalation_events[0]["data"]["from_model"] == "gpt-4o-mini"
        assert escalation_events[0]["data"]["to_model"] == "gpt-4o"
        scrubber.reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_escalation_not_detected(self, escalation_ctx):
        """Scrubber has not detected marker → returns False."""
        executor = _make_executor(escalation_ctx)
        scrubber = MagicMock()
        scrubber.detected = False
        executor._escalation_scrubber = scrubber

        result = await executor._handle_escalation([])
        assert result is False

    @pytest.mark.asyncio
    async def test_escalation_no_target(self, ctx):
        """No escalation_target_llm → returns False."""
        ctx.escalation_target_llm = None
        executor = _make_executor(ctx)
        scrubber = MagicMock()
        scrubber.detected = True
        executor._escalation_scrubber = scrubber

        result = await executor._handle_escalation([])
        assert result is False

    @pytest.mark.asyncio
    async def test_escalation_already_used(self, escalation_ctx):
        """Escalation already used → returns False."""
        executor = _make_executor(escalation_ctx)
        executor._escalation_used = True
        scrubber = MagicMock()
        scrubber.detected = True
        executor._escalation_scrubber = scrubber

        result = await executor._handle_escalation([])
        assert result is False

    @pytest.mark.asyncio
    async def test_escalation_same_model(self, ctx):
        """Same model as target → returns False."""
        target_llm = MagicMock()
        target_llm.model_name = "gpt-4o-mini"
        ctx.escalation_target_llm = target_llm
        ctx.llm_info = {"model_name": "gpt-4o-mini"}

        executor = _make_executor(ctx)
        scrubber = MagicMock()
        scrubber.detected = True
        executor._escalation_scrubber = scrubber

        result = await executor._handle_escalation([])
        assert result is False

    @pytest.mark.asyncio
    async def test_escalation_resume_mode(self, escalation_ctx):
        """Resume mode (Command) → returns False."""
        escalation_ctx.agent_input = Command(resume="val")
        executor = _make_executor(escalation_ctx)
        scrubber = MagicMock()
        scrubber.detected = True
        executor._escalation_scrubber = scrubber

        result = await executor._handle_escalation([])
        assert result is False

    @pytest.mark.asyncio
    async def test_escalation_filters_marker_message(self, escalation_ctx):
        """Marker messages are filtered out from replayed messages."""
        rebuild_fn = MagicMock()
        executor = StreamExecutor(
            ctx=escalation_ctx,
            fallback_llm=None,
            safety_fallback_llm=None,
            rebuild_agent_fn=rebuild_fn,
        )
        executor._compactor = FakeCompactor()

        scrubber = MagicMock()
        scrubber.detected = True
        scrubber.reason = None
        executor._escalation_scrubber = scrubber

        collected = [
            HumanMessage(content="Hello"),
            AIMessage(content="<<<NEEDS_PRO>>>"),
            HumanMessage(content="Another message"),
        ]

        await executor._handle_escalation(collected)

        messages = escalation_ctx.agent_input["messages"]
        for msg in messages:
            if isinstance(msg, AIMessage):
                assert "<<<NEEDS_PRO" not in msg.content


# ─── _handle_transient_retry ─────────────────────────────────────────────────


class TestHandleTransientRetry:
    @pytest.mark.asyncio
    async def test_non_transient_error(self, ctx):
        """Non-transient error → returns False."""
        executor = _make_executor(ctx)

        from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind

        with patch(
            "myrm_agent_harness.agent.streaming.stream_recovery.classify_error",
            return_value=ErrorKind.AUTH,
        ):
            result = await executor._handle_transient_retry(RuntimeError("auth"), 0)
        assert result is False

    @pytest.mark.asyncio
    async def test_transient_rate_limit_retry(self, ctx):
        """Rate limit triggers retry with backoff."""
        executor = _make_executor(ctx)

        from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind

        with (
            patch(
                "myrm_agent_harness.agent.streaming.stream_recovery.classify_error",
                return_value=ErrorKind.RATE_LIMIT,
            ),
            patch(
                "myrm_agent_harness.agent.streaming.stream_recovery.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await executor._handle_transient_retry(RuntimeError("rate limited"), 0)
        assert result is True
        events = executor._compactor.events
        retry_events = [
            e for e in events
            if isinstance(e, dict) and e.get("step_key") == "transient_retry"
        ]
        assert len(retry_events) == 1

    @pytest.mark.asyncio
    async def test_transient_exhausted(self, ctx):
        """Retries exhausted → returns False."""
        executor = _make_executor(ctx)

        from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind

        with patch(
            "myrm_agent_harness.agent.streaming.stream_recovery.classify_error",
            return_value=ErrorKind.RATE_LIMIT,
        ):
            result = await executor._handle_transient_retry(RuntimeError("rate limited"), 15)
        assert result is False

    @pytest.mark.asyncio
    async def test_transient_cancelled(self, ctx):
        """Cancel token cancels the retry."""
        cancel = MagicMock()
        cancel.is_cancelled = True
        ctx.cancel_token = cancel

        executor = _make_executor(ctx)

        from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind

        with (
            patch(
                "myrm_agent_harness.agent.streaming.stream_recovery.classify_error",
                return_value=ErrorKind.TIMEOUT,
            ),
            patch(
                "myrm_agent_harness.agent.streaming.stream_recovery.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await executor._handle_transient_retry(RuntimeError("timeout"), 0)
        assert result is False

    @pytest.mark.asyncio
    async def test_transient_overloaded(self, ctx):
        """OVERLOADED error is transient."""
        executor = _make_executor(ctx)

        from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind

        with (
            patch(
                "myrm_agent_harness.agent.streaming.stream_recovery.classify_error",
                return_value=ErrorKind.OVERLOADED,
            ),
            patch(
                "myrm_agent_harness.agent.streaming.stream_recovery.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await executor._handle_transient_retry(RuntimeError("overloaded"), 0)
        assert result is True


# ─── _handle_iteration_limit ─────────────────────────────────────────────────


class TestHandleIterationLimit:
    @pytest.mark.asyncio
    async def test_graph_recursion_error(self, ctx):
        """GraphRecursionError triggers iteration limit handling + grace call."""
        from langgraph.errors import GraphRecursionError

        executor = _make_executor(ctx)
        ctx.run_config["recursion_limit"] = 25
        ctx.stats.node_execution_count = 24

        exc = GraphRecursionError("limit reached")
        msgs = [HumanMessage(content="test")]
        result = await executor._handle_iteration_limit(exc, msgs)

        assert result is True
        events = executor._compactor.events
        limit_events = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == AgentEventType.ITERATION_LIMIT_REACHED.value
        ]
        assert len(limit_events) == 1
        assert limit_events[0]["data"]["limit"] == 25
        assert limit_events[0]["data"]["nodes_completed"] == 24

    @pytest.mark.asyncio
    async def test_non_recursion_error(self, ctx):
        """Non-GraphRecursionError → returns False."""
        executor = _make_executor(ctx)
        msgs = [HumanMessage(content="test")]
        result = await executor._handle_iteration_limit(RuntimeError("other"), msgs)
        assert result is False


# ─── _handle_empty_response ──────────────────────────────────────────────────


class TestHandleEmptyResponse:
    @pytest.mark.asyncio
    async def test_empty_ai_response_injects_prompt(self, ctx):
        """Empty AI response triggers recovery prompt injection."""
        executor = _make_executor(ctx)
        collected = [
            HumanMessage(content="Hello"),
            AIMessage(content=""),
        ]

        result = await executor._handle_empty_response(collected, retries=0)

        assert result is True
        messages = ctx.agent_input["messages"]
        last_msg = messages[-1]
        assert isinstance(last_msg, HumanMessage)
        assert "empty" in last_msg.content.lower()

    @pytest.mark.asyncio
    async def test_non_empty_response_no_injection(self, ctx):
        """AI response with content → returns False."""
        executor = _make_executor(ctx)
        collected = [
            HumanMessage(content="Hello"),
            AIMessage(content="Here is my response"),
        ]

        result = await executor._handle_empty_response(collected, retries=0)
        assert result is False

    @pytest.mark.asyncio
    async def test_tool_call_response_no_injection(self, ctx):
        """AI response with tool calls → returns False."""
        executor = _make_executor(ctx)
        msg = AIMessage(content="")
        msg.tool_calls = [{"name": "search", "args": {}, "id": "tc1"}]
        collected = [HumanMessage(content="search"), msg]

        result = await executor._handle_empty_response(collected, retries=0)
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_response_exhausted_raises(self, ctx):
        """Retries exhausted → raises MyrmLLMError."""
        from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError

        executor = _make_executor(ctx)
        collected = [
            HumanMessage(content="Hello"),
            AIMessage(content=""),
        ]

        with pytest.raises(MyrmLLMError):
            await executor._handle_empty_response(collected, retries=2)

    @pytest.mark.asyncio
    async def test_empty_response_resume_mode(self, ctx):
        """Resume mode → returns False."""
        ctx.agent_input = Command(resume="val")
        executor = _make_executor(ctx)
        collected = [AIMessage(content="")]

        result = await executor._handle_empty_response(collected, retries=0)
        assert result is False

    @pytest.mark.asyncio
    async def test_no_ai_message_returns_false(self, ctx):
        """No AI message in collected → returns False."""
        executor = _make_executor(ctx)
        collected = [HumanMessage(content="hello")]

        result = await executor._handle_empty_response(collected, retries=0)
        assert result is False
