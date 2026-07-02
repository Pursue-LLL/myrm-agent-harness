"""Unit tests for tool usage analytics (A1).

Tests for:
- EventLogger.get_tool_usage_stats()
- EventLogger.get_activity_patterns()
"""

import asyncio
import time
from collections.abc import AsyncGenerator

import pytest

from myrm_agent_harness.agent.event_log.logger import EventLogger
from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
from myrm_agent_harness.agent.event_log.types import EventFilter, StructuredEvent


class MockEventLogBackend(EventLogBackend):
    """Mock backend for testing."""

    def __init__(self) -> None:
        self.events: list[StructuredEvent] = []
        self.session_events: dict[str, list[StructuredEvent]] = {}

    async def append(self, events: list[StructuredEvent]) -> None:
        """Append events to mock storage."""
        for event in events:
            self.events.append(event)
            if event.session_id not in self.session_events:
                self.session_events[event.session_id] = []
            self.session_events[event.session_id].append(event)

    async def get_events(
        self, session_id: str, event_filter: object | None = None
    ) -> AsyncGenerator[StructuredEvent]:
        """Get events from mock storage with filtering."""
        events = self.session_events.get(session_id, [])

        # Apply filters if provided
        if event_filter is not None and isinstance(event_filter, EventFilter):
            for event in events:
                # Filter by event types
                if event_filter.event_types is not None and event.event_type not in event_filter.event_types:
                    continue

                # Filter by start time
                if event_filter.start_time is not None and event.timestamp < event_filter.start_time:
                    continue

                # Filter by end time
                if event_filter.end_time is not None and event.timestamp > event_filter.end_time:
                    continue

                yield event
        else:
            for event in events:
                yield event

    async def close(self) -> None:
        """Close mock backend."""
        pass


@pytest.fixture
async def event_logger() -> AsyncGenerator[EventLogger]:
    """Create EventLogger with mock backend."""
    backend = MockEventLogBackend()
    logger = EventLogger(backend, "test_session")
    await logger.start()
    yield logger
    await logger.close()


@pytest.mark.asyncio
async def test_get_tool_usage_stats_basic(event_logger: EventLogger) -> None:
    """Test basic tool usage statistics."""
    base_time = time.time()

    # Record tool events
    await event_logger.log("tool_start", {"tool_name": "file_read", "timestamp": base_time})
    await event_logger.log("tool_end", {"tool_name": "file_read", "duration_ms": 100})

    await event_logger.log("tool_start", {"tool_name": "bash_code_execute_tool", "timestamp": base_time + 1})
    await event_logger.log(
        "tool_failure",
        {
            "tool_name": "bash_code_execute_tool",
            "duration_ms": 500,
            "error_code": "TIMEOUT",
        },
    )

    await event_logger.log("tool_start", {"tool_name": "file_read", "timestamp": base_time + 2})
    await event_logger.log("tool_end", {"tool_name": "file_read", "duration_ms": 150})

    # Wait for buffer to flush
    await asyncio.sleep(1.0)

    # Query statistics
    stats = await event_logger.get_tool_usage_stats()

    # Assertions
    assert len(stats) == 2

    # Check file_read stats
    file_read_stats = next(s for s in stats if s.tool_name == "file_read")
    assert file_read_stats.total_calls == 2
    assert file_read_stats.success_count == 2
    assert file_read_stats.failure_count == 0
    assert file_read_stats.avg_duration_ms == 125.0  # (100 + 150) / 2

    # Check bash_tool stats
    bash_stats = next(s for s in stats if s.tool_name == "bash_code_execute_tool")
    assert bash_stats.total_calls == 1
    assert bash_stats.success_count == 0
    assert bash_stats.failure_count == 1
    assert bash_stats.avg_duration_ms == 500.0
    assert bash_stats.failure_reasons == {"TIMEOUT": 1}


@pytest.mark.asyncio
async def test_get_tool_usage_stats_with_timeout_retry(event_logger: EventLogger) -> None:
    """Test statistics with timeout and retry events."""
    base_time = time.time()

    # Record tool events with timeout and retry
    await event_logger.log("tool_start", {"tool_name": "browser_click", "timestamp": base_time})
    await event_logger.log("tool_timeout", {"tool_name": "browser_click"})
    await event_logger.log("tool_retry", {"tool_name": "browser_click"})
    await event_logger.log("tool_end", {"tool_name": "browser_click", "duration_ms": 2000})

    # Wait for buffer to flush
    await asyncio.sleep(1.0)

    # Query statistics
    stats = await event_logger.get_tool_usage_stats()

    # Assertions
    assert len(stats) == 1
    browser_stats = stats[0]
    assert browser_stats.tool_name == "browser_click"
    assert browser_stats.total_calls == 1
    assert browser_stats.success_count == 1
    assert browser_stats.timeout_count == 1
    assert browser_stats.retry_count == 1


@pytest.mark.asyncio
async def test_get_tool_usage_stats_with_tokens(event_logger: EventLogger) -> None:
    """Test statistics with token usage."""
    base_time = time.time()

    # Record tool events with token usage
    await event_logger.log("tool_start", {"tool_name": "skill_foo", "timestamp": base_time})
    await event_logger.log("tool_token_usage", {"tool_name": "skill_foo", "tokens": 1000})
    await event_logger.log("tool_end", {"tool_name": "skill_foo", "duration_ms": 5000})

    await event_logger.log("tool_start", {"tool_name": "skill_foo", "timestamp": base_time + 10})
    await event_logger.log("tool_token_usage", {"tool_name": "skill_foo", "tokens": 1500})
    await event_logger.log("tool_end", {"tool_name": "skill_foo", "duration_ms": 6000})

    # Wait for buffer to flush
    await asyncio.sleep(1.0)

    # Query statistics
    stats = await event_logger.get_tool_usage_stats()

    # Assertions
    assert len(stats) == 1
    skill_stats = stats[0]
    assert skill_stats.tool_name == "skill_foo"
    assert skill_stats.total_calls == 2
    assert skill_stats.total_tokens == 2500  # 1000 + 1500
    assert skill_stats.avg_tokens == 1250.0  # 2500 / 2


@pytest.mark.asyncio
async def test_get_activity_patterns_basic(event_logger: EventLogger) -> None:
    """Test basic activity pattern analysis.

    Note: This test records all events in the same hour (current hour),
    as StructuredEvent.timestamp uses actual recording time, not custom timestamps.
    The test verifies that activity patterns can aggregate tool calls correctly.
    """
    # Record multiple tool calls
    await event_logger.log("tool_start", {"tool_name": "file_read"})
    await event_logger.log("tool_end", {"tool_name": "file_read", "duration_ms": 100})

    await event_logger.log("tool_start", {"tool_name": "bash_code_execute_tool"})
    await event_logger.log("tool_end", {"tool_name": "bash_code_execute_tool", "duration_ms": 200})

    await event_logger.log("tool_start", {"tool_name": "file_read"})
    await event_logger.log("tool_end", {"tool_name": "file_read", "duration_ms": 150})

    await event_logger.log("tool_start", {"tool_name": "file_read"})
    await event_logger.log("tool_end", {"tool_name": "file_read", "duration_ms": 200})

    await event_logger.log("tool_start", {"tool_name": "bash_code_execute_tool"})
    await event_logger.log("tool_end", {"tool_name": "bash_code_execute_tool", "duration_ms": 300})

    # Wait for buffer to flush
    await asyncio.sleep(1.0)

    # Query patterns
    patterns = await event_logger.get_activity_patterns()

    # Assertions
    assert len(patterns.hourly_breakdown) > 0
    assert patterns.peak_tool == "file_read"  # file_read has most calls (3 vs 2)

    # Verify tool counts in breakdown
    tool_counts: dict[str, int] = {}
    for usage in patterns.hourly_breakdown:
        tool_counts[usage.tool_name] = tool_counts.get(usage.tool_name, 0) + usage.call_count

    assert tool_counts["file_read"] == 3
    assert tool_counts["bash_code_execute_tool"] == 2


@pytest.mark.asyncio
async def test_get_tool_usage_stats_time_range(event_logger: EventLogger) -> None:
    """Test statistics with time range filter.

    Note: This test verifies that time_range_seconds parameter is accepted
    and query executes successfully. Actual time-based filtering requires
    real time delays which are impractical for unit tests.
    """
    # Record some events
    await event_logger.log("tool_start", {"tool_name": "test_tool"})
    await event_logger.log("tool_end", {"tool_name": "test_tool", "duration_ms": 100})

    await event_logger.log("tool_start", {"tool_name": "test_tool"})
    await event_logger.log("tool_end", {"tool_name": "test_tool", "duration_ms": 200})

    # Wait for buffer to flush
    await asyncio.sleep(1.0)

    # Query with time range - should not raise error
    stats_with_range = await event_logger.get_tool_usage_stats(time_range_seconds=3600)
    stats_without_range = await event_logger.get_tool_usage_stats()

    # Both queries should return same results (all events are recent)
    assert len(stats_with_range) == len(stats_without_range) == 1
    assert stats_with_range[0].tool_name == "test_tool"
    assert stats_with_range[0].total_calls == 2


@pytest.mark.asyncio
async def test_get_tool_usage_stats_empty(event_logger: EventLogger) -> None:
    """Test statistics with no tool events."""
    stats = await event_logger.get_tool_usage_stats()
    assert stats == []


@pytest.mark.asyncio
async def test_get_activity_patterns_empty(event_logger: EventLogger) -> None:
    """Test activity patterns with no events."""
    patterns = await event_logger.get_activity_patterns()
    assert patterns.hourly_breakdown == []
    assert patterns.peak_hour == 0
    assert patterns.peak_tool == ""
