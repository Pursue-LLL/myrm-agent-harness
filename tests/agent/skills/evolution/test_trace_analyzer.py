from typing import Any

import pytest

from myrm_agent_harness.agent.event_log.types import (
    EventPayload,
    SessionAnalytics,
    StructuredEvent,
    ToolUsageStats,
)
from myrm_agent_harness.agent.skills.evolution.pipeline.trace_analyzer import (
    TraceAnalyzer,
)


class MockEventLogBackend:
    def __init__(self, events: list[StructuredEvent]):
        self.events = events

    async def get_events(
        self, session_id: str, event_filter: Any = None
    ) -> list[StructuredEvent]:
        # Simple mock that just returns the events
        return self.events

    async def append(self, events: list[StructuredEvent]) -> None:
        pass

    async def get_all_session_ids(self) -> list[str]:
        return []

    async def close(self) -> None:
        pass


@pytest.fixture
def mock_backend():
    # Create some mock events
    events = [
        StructuredEvent(
            sequence=1,
            timestamp=1000.0,
            event_type="tool_start",
            session_id="test_session",
            data=EventPayload(tool_name="test_tool", tool_args={}),
        ),
        StructuredEvent(
            sequence=2,
            timestamp=1001.0,
            event_type="tool_error",
            session_id="test_session",
            data=EventPayload(tool_name="test_tool", error="Permission denied"),
        ),
        StructuredEvent(
            sequence=3,
            timestamp=1002.0,
            event_type="session_end",
            session_id="test_session",
            data=EventPayload(summary={"duration_ms": 2000}),
        ),
    ]
    return MockEventLogBackend(events)


@pytest.mark.asyncio
async def test_extract_trajectory(mock_backend):
    analyzer = TraceAnalyzer(mock_backend)
    result = await analyzer.extract_trajectory("test_session", "test_skill")

    assert "会话概览 (Session Overview)" in result
    assert "根因分析 (Per-task Analysis)" in result
    assert "工具统计 (Tool Stats)" in result
    assert "关键错误详情 (Error Details)" in result
    assert "全局概览 (Benchmark-level Overview)" in result

    # Check if permission error was detected
    assert "permission" in result or "Permission denied" in result


@pytest.mark.asyncio
async def test_analyze_failure_mode_timeout():
    analyzer = TraceAnalyzer(None)  # type: ignore

    # Mock summary and stats
    summary = SessionAnalytics(
        session_id="test",
        duration_ms=1000,
        tool_breakdown=[],
        events_timeline=[],
        task_metrics={},
    )

    tool_stats = []

    error_events = [
        StructuredEvent(
            sequence=1,
            timestamp=1000.0,
            event_type="tool_timeout",
            session_id="test",
            data=EventPayload(),
        )
        for _ in range(4)
    ]

    mode = analyzer._analyze_failure_mode(summary, tool_stats, error_events)
    assert mode == "timeout"


@pytest.mark.asyncio
async def test_analyze_failure_mode_permission():
    analyzer = TraceAnalyzer(None)  # type: ignore

    summary = SessionAnalytics(
        session_id="test",
        duration_ms=1000,
        tool_breakdown=[],
        events_timeline=[],
        task_metrics={},
    )

    tool_stats = [
        ToolUsageStats(
            tool_name="test",
            total_calls=1,
            success_count=0,
            failure_count=1,
            timeout_count=0,
            retry_count=0,
            avg_duration_ms=100,
            failure_reasons={"Permission denied": 1},
        )
    ]

    error_events = []

    mode = analyzer._analyze_failure_mode(summary, tool_stats, error_events)
    assert mode == "permission"


@pytest.mark.asyncio
async def test_cluster_similar_errors():
    analyzer = TraceAnalyzer(None)  # type: ignore

    error_events = [
        StructuredEvent(
            sequence=1,
            timestamp=1000.0,
            event_type="tool_error",
            session_id="test",
            data=EventPayload(error="Connection refused to 10.0.0.1"),
        ),
        StructuredEvent(
            sequence=2,
            timestamp=1001.0,
            event_type="tool_error",
            session_id="test",
            data=EventPayload(error="Connection refused to 10.0.0.2"),
        ),
        StructuredEvent(
            sequence=3,
            timestamp=1002.0,
            event_type="tool_error",
            session_id="test",
            data=EventPayload(error="File not found: /tmp/a"),
        ),
    ]

    clusters = analyzer._cluster_similar_errors(error_events)
    # Should cluster the two connection refused errors together
    assert len(clusters) == 2


@pytest.mark.asyncio
async def test_analyze_slice():
    events = [
        StructuredEvent(
            sequence=1,
            timestamp=1000.0,
            event_type="pre_tool_use",
            session_id="test_session",
            data=EventPayload(tool_call_id="call_1", tool_name="test_tool", tool_args={}),
        ),
        StructuredEvent(
            sequence=2,
            timestamp=1001.0,
            event_type="post_tool_use",
            session_id="test_session",
            data=EventPayload(tool_call_id="call_1", tool_name="test_tool", result="success"),
        ),
        StructuredEvent(
            sequence=3,
            timestamp=1002.0,
            event_type="pre_tool_use",
            session_id="test_session",
            data=EventPayload(tool_call_id="call_unrelated", tool_name="test_tool2", tool_args={}),
        ),
    ]
    mock_backend = MockEventLogBackend(events)
    analyzer = TraceAnalyzer(mock_backend)

    slice_result = await analyzer.analyze_slice("test_session", ["call_1"])
    assert slice_result is not None
    assert getattr(slice_result, "is_coherent", False) is True
    # Verify that the formatted_trace only contains test_tool
    assert "test_tool" in slice_result.formatted_trace
    assert "test_tool2" not in slice_result.formatted_trace

    # Test incoherent
    events_incoherent = [
        StructuredEvent(
            sequence=1,
            timestamp=1000.0,
            event_type="pre_tool_use",
            session_id="test_session",
            data=EventPayload(tool_call_id="call_2", tool_name="test_tool", tool_args={}),
        ),
        StructuredEvent(
            sequence=2,
            timestamp=1001.0,
            event_type="post_tool_use_failure",
            session_id="test_session",
            data=EventPayload(tool_call_id="call_2", tool_name="test_tool", error="fail"),
        ),
    ]
    mock_backend_incoherent = MockEventLogBackend(events_incoherent)
    analyzer_incoherent = TraceAnalyzer(mock_backend_incoherent)
    slice_result_incoherent = await analyzer_incoherent.analyze_slice("test_session", ["call_2"])
    assert slice_result_incoherent is not None
    assert getattr(slice_result_incoherent, "is_coherent", False) is False
