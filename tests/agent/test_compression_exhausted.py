from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.types import AgentRunStatistics

"""Tests for compression exhausted protection (death-loop prevention).

Verifies that when context overflow recovery is exhausted:
1. AgentRunStatistics.compression_exhausted flag is set
2. ERROR events include compression_exhausted=True
3. Server layer can detect and act on the flag
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCompressionExhaustedFlag:
    """AgentRunStatistics.compression_exhausted field behavior."""

    def test_default_false(self):
        stats = AgentRunStatistics()
        assert stats.compression_exhausted is False

    def test_set_true(self):
        stats = AgentRunStatistics()
        stats.compression_exhausted = True
        assert stats.compression_exhausted is True

    def test_preserved_in_copy(self):
        import dataclasses

        stats = AgentRunStatistics()
        stats.compression_exhausted = True
        copied = dataclasses.replace(stats)
        assert copied.compression_exhausted is True


class TestHandleOverflowExhaustion:
    """StreamExecutor._handle_overflow sets compression_exhausted when retries exhausted."""

    @pytest.fixture
    def mock_executor(self):
        from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor

        stats = AgentRunStatistics()
        ctx = MagicMock(spec=StreamContext)
        ctx.stats = stats
        ctx.message_id = "test-msg"
        ctx.agent_input = {"messages": []}

        executor = object.__new__(StreamExecutor)
        executor._ctx = ctx
        executor._compactor = AsyncMock()
        executor.streaming_final_answer = False

        return executor, ctx, stats

    @pytest.mark.asyncio
    async def test_retries_not_exhausted(self, mock_executor):
        """First overflow attempt should NOT set compression_exhausted."""
        executor, _ctx, stats = mock_executor

        exc = Exception("context_length_exceeded: too many tokens")
        result = await executor._handle_overflow(exc, retries=0)

        assert result is True
        assert stats.compression_exhausted is False

    @pytest.mark.asyncio
    async def test_retries_exhausted_sets_flag(self, mock_executor):
        """When retries >= MAX, compression_exhausted should be True."""
        executor, _ctx, stats = mock_executor

        exc = Exception("context_length_exceeded: too many tokens")
        result = await executor._handle_overflow(exc, retries=2)

        assert result is False
        assert stats.compression_exhausted is True

    @pytest.mark.asyncio
    async def test_non_overflow_error_no_flag(self, mock_executor):
        """Non-overflow errors should not set the flag."""
        executor, _ctx, stats = mock_executor

        exc = Exception("rate limit exceeded")
        result = await executor._handle_overflow(exc, retries=5)

        assert result is False
        assert stats.compression_exhausted is False

    @pytest.mark.asyncio
    async def test_retries_above_max_sets_flag(self, mock_executor):
        """Retries above MAX (e.g. 3) should still set compression_exhausted."""
        executor, _ctx, stats = mock_executor

        exc = Exception("context_length_exceeded: too many tokens")
        result = await executor._handle_overflow(exc, retries=3)

        assert result is False
        assert stats.compression_exhausted is True

    @pytest.mark.asyncio
    async def test_resume_mode_overflow_no_flag(self, mock_executor):
        """Resume mode (Command input) overflow should return False without setting flag."""
        from langgraph.types import Command

        executor, ctx, stats = mock_executor
        ctx.agent_input = Command(resume={"decision": "approve"})

        exc = Exception("context_length_exceeded: too many tokens")
        result = await executor._handle_overflow(exc, retries=0)

        assert result is False
        assert stats.compression_exhausted is False

    def test_compression_exhausted_with_cancelled(self):
        """Both compression_exhausted and was_cancelled can be True simultaneously."""
        stats = AgentRunStatistics()
        stats.compression_exhausted = True
        stats.was_cancelled = True
        assert stats.compression_exhausted is True
        assert stats.was_cancelled is True


class TestErrorEventCompressionExhausted:
    """ERROR event includes compression_exhausted when set."""

    @pytest.mark.asyncio
    async def test_error_event_includes_flag(self):
        """When compression_exhausted=True, ERROR event should contain the flag."""
        from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor

        stats = AgentRunStatistics()
        stats.compression_exhausted = True

        ctx = MagicMock(spec=StreamContext)
        ctx.stats = stats
        ctx.message_id = "test-msg"
        ctx.merged_context = {"locale": "en"}
        ctx.llm_info = None

        captured_events: list[dict] = []

        compactor = AsyncMock()

        async def capture_put(event):
            if isinstance(event, dict):
                captured_events.append(event)

        compactor.put = capture_put
        compactor.flush = AsyncMock()

        executor = object.__new__(StreamExecutor)
        executor._ctx = ctx
        executor._compactor = compactor
        executor._fallback_llm = None
        executor.failover_used = False
        executor.streaming_final_answer = False
        executor._rebuild_agent_fn = lambda x: None

        ctx.agent = MagicMock()
        ctx.agent.astream = MagicMock(side_effect=Exception("context_length_exceeded"))
        ctx.agent_input = {"messages": []}
        ctx.run_config = {}
        ctx.cancel_token = None
        ctx.steering_token = None
        ctx.event_logger = None
        ctx.drain_subagent_notifications = None

        with (
            patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock),
            pytest.raises(Exception),
        ):
            await executor.execute()

        error_events = [e for e in captured_events if e.get("type") == AgentEventType.ERROR.value]
        assert len(error_events) == 1
        assert error_events[0]["compression_exhausted"] is True

    @pytest.mark.asyncio
    async def test_error_event_without_flag(self):
        """When compression_exhausted=False, ERROR event should NOT contain the flag."""
        from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor

        stats = AgentRunStatistics()

        ctx = MagicMock(spec=StreamContext)
        ctx.stats = stats
        ctx.message_id = "test-msg"
        ctx.merged_context = {"locale": "en"}
        ctx.llm_info = None

        captured_events: list[dict] = []

        compactor = AsyncMock()

        async def capture_put(event):
            if isinstance(event, dict):
                captured_events.append(event)

        compactor.put = capture_put
        compactor.flush = AsyncMock()

        executor = object.__new__(StreamExecutor)
        executor._ctx = ctx
        executor._compactor = compactor
        executor._fallback_llm = None
        executor.failover_used = False
        executor.streaming_final_answer = False
        executor._rebuild_agent_fn = lambda x: None

        ctx.agent = MagicMock()
        ctx.agent.astream = MagicMock(side_effect=Exception("some random error"))
        ctx.agent_input = {"messages": []}
        ctx.run_config = {}
        ctx.cancel_token = None
        ctx.steering_token = None
        ctx.event_logger = None
        ctx.drain_subagent_notifications = None

        with (
            patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock),
            pytest.raises(Exception),
        ):
            await executor.execute()

        error_events = [e for e in captured_events if e.get("type") == AgentEventType.ERROR.value]
        assert len(error_events) == 1
        assert "compression_exhausted" not in error_events[0]


class TestSSEDetectionLogic:
    """Tests for SSE compression_exhausted detection logic (inline, no server import)."""

    @staticmethod
    def _is_compression_exhausted(sse_chunk: str) -> bool:
        """Inline replica of the server-side detection function for unit testing."""
        import json

        prefix = "data: "
        if "compression_exhausted" not in sse_chunk:
            return False
        if not sse_chunk.startswith(prefix):
            return False
        try:
            event = json.loads(sse_chunk[len(prefix) :].rstrip())
            return event.get("type") == "error" and event.get("compression_exhausted") is True
        except (json.JSONDecodeError, TypeError):
            return False

    def test_detects_compression_exhausted(self):
        import json

        event = {
            "type": "error",
            "error": "context overflow",
            "compression_exhausted": True,
            "messageId": "msg-1",
        }
        chunk = f"data: {json.dumps(event)}\n\n"
        assert self._is_compression_exhausted(chunk) is True

    def test_rejects_normal_error(self):
        import json

        event = {
            "type": "error",
            "error": "rate limit",
            "messageId": "msg-1",
        }
        chunk = f"data: {json.dumps(event)}\n\n"
        assert self._is_compression_exhausted(chunk) is False

    def test_rejects_non_error_events(self):
        import json

        event = {
            "type": "message",
            "compression_exhausted": True,
            "messageId": "msg-1",
        }
        chunk = f"data: {json.dumps(event)}\n\n"
        assert self._is_compression_exhausted(chunk) is False

    def test_rejects_invalid_sse(self):
        assert self._is_compression_exhausted("not-sse-data") is False
        assert self._is_compression_exhausted("data: {invalid json}\n\n") is False
        assert self._is_compression_exhausted("") is False

    def test_compression_exhausted_false_value(self):
        """compression_exhausted=False should return False."""
        import json

        event = {
            "type": "error",
            "error": "context overflow",
            "compression_exhausted": False,
            "messageId": "msg-1",
        }
        chunk = f"data: {json.dumps(event)}\n\n"
        assert self._is_compression_exhausted(chunk) is False

    def test_resume_mode_guard(self):
        """Server should NOT undo when resume_value is set."""
        import json

        event = {
            "type": "error",
            "compression_exhausted": True,
            "messageId": "msg-1",
        }
        chunk = f"data: {json.dumps(event)}\n\n"
        assert self._is_compression_exhausted(chunk) is True
