import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor
from myrm_agent_harness.agent.types import AgentRunStatistics


class DummyCancellationToken:
    def __init__(self, cancelled=False):
        self._cancelled = cancelled

    @property
    def is_cancelled(self):
        return self._cancelled


class DummyCompactor:
    def __init__(self):
        self.events = []

    async def put(self, event):
        self.events.append(event)

    async def flush(self):
        pass


@pytest.fixture
def mock_context():
    stats = AgentRunStatistics()
    ctx = StreamContext(
        agent=None,
        agent_input={},
        merged_context={},
        run_config={},
        stats=stats,
        message_id="test_msg_id",
        cancel_token=DummyCancellationToken(),
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
    )
    return ctx


@pytest.mark.asyncio
async def test_handle_transient_retry_rate_limit(mock_context):
    executor = StreamExecutor(ctx=mock_context, fallback_llm=None, rebuild_agent_fn=None, safety_fallback_llm=None)
    executor._compactor = DummyCompactor()

    # Rate limit exception
    exc = Exception("rate limit exceeded, please retry after 2 seconds")

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        # retries = 0 -> should return True
        should_retry = await executor._handle_transient_retry(exc, retries=0)
        assert should_retry is True

        # Check event emitted
        assert len(executor._compactor.events) == 1
        event = executor._compactor.events[0]
        assert event["type"] == "status"
        assert event["step_key"] == "transient_retry"
        assert event["error_kind"] == "rate_limit"
        assert event["attempt"] == 1
        assert "delay_ms" in event

        # Sleep should be called
        mock_sleep.assert_called()


@pytest.mark.asyncio
async def test_handle_transient_retry_exhausted(mock_context):
    executor = StreamExecutor(ctx=mock_context, fallback_llm=None, rebuild_agent_fn=None, safety_fallback_llm=None)
    executor._compactor = DummyCompactor()

    exc = Exception("timeout")

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        # retries = 15 (max) -> should return False
        should_retry = await executor._handle_transient_retry(exc, retries=15)
        assert should_retry is False
        assert len(executor._compactor.events) == 0
        mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_handle_transient_retry_not_transient(mock_context):
    executor = StreamExecutor(ctx=mock_context, fallback_llm=None, rebuild_agent_fn=None, safety_fallback_llm=None)
    executor._compactor = DummyCompactor()

    # Not a transient error, e.g., missing parameter format error
    exc = Exception("InvalidParameter format error")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        should_retry = await executor._handle_transient_retry(exc, retries=0)
        assert should_retry is False
        assert len(executor._compactor.events) == 0


@pytest.mark.asyncio
async def test_handle_transient_retry_cancellation(mock_context):
    mock_context.cancel_token = DummyCancellationToken(cancelled=True)
    executor = StreamExecutor(ctx=mock_context, fallback_llm=None, rebuild_agent_fn=None, safety_fallback_llm=None)
    executor._compactor = DummyCompactor()

    exc = Exception("timeout")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        should_retry = await executor._handle_transient_retry(exc, retries=0)
        # Should return False because it's cancelled during the wait loop
        assert should_retry is False
