"""Unit tests for EventLogger.get_session_summary() - B2 Session Analytics."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from myrm_agent_harness.agent.context_management.tracking.task_metrics import clear_task_metrics, create_task_metrics
from myrm_agent_harness.agent.event_log import EventLogger, SessionAnalytics
from myrm_agent_harness.agent.event_log.backends.file_backend import FileEventLogBackend
from myrm_agent_harness.agent.event_log.types import EventPayload, StructuredEvent
from myrm_agent_harness.utils.token_economics.tracker import init_token_tracker, reset_token_tracker


def _evt(seq: int, ts: float, event_type: str, session_id: str, data: dict) -> StructuredEvent:
    return StructuredEvent(
        sequence=seq, timestamp=ts, event_type=event_type, session_id=session_id, data=EventPayload(**data)
    )


@pytest.mark.asyncio
async def test_get_session_summary_basic():
    """Test basic session summary aggregation."""
    with TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir)
        session_id = "test-session-basic"

        backend = FileEventLogBackend(log_dir=log_dir, session_id=session_id)
        logger = EventLogger(backend=backend, session_id=session_id)

        # Create sample events
        events = [
            StructuredEvent(sequence=1, timestamp=1000.0, event_type="session_start", session_id=session_id, data={}),
            StructuredEvent(
                sequence=2, timestamp=1001.0, event_type="tool_start", session_id=session_id, data={"tool_name": "Read"}
            ),
            StructuredEvent(
                sequence=3,
                timestamp=1002.0,
                event_type="tool_end",
                session_id=session_id,
                data={"tool_name": "Read", "duration_ms": 500},
            ),
            StructuredEvent(
                sequence=4,
                timestamp=1003.0,
                event_type="session_end",
                session_id=session_id,
                data={"summary": {"duration_ms": 3000}},
            ),
        ]

        # Write events to backend
        await backend.append(events)

        # Get session summary
        summary = await logger.get_session_summary()

        # Assertions
        assert isinstance(summary, SessionAnalytics)
        assert summary.session_id == session_id
        assert summary.duration_ms == 3000
        assert len(summary.tool_breakdown) == 1
        assert summary.tool_breakdown[0].tool_name == "Read"
        assert summary.tool_breakdown[0].call_count == 1
        assert summary.tool_breakdown[0].total_duration_ms == 500
        assert len(summary.events_timeline) == 4


@pytest.mark.asyncio
async def test_get_session_summary_multiple_tools():
    """Test session summary with multiple tool calls."""
    with TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir)
        session_id = "test-session-multi-tools"

        backend = FileEventLogBackend(log_dir=log_dir, session_id=session_id)
        logger = EventLogger(backend=backend, session_id=session_id)

        # Create sample events with multiple tool calls
        events = [
            _evt(1, 1000.0, "session_start", session_id, {}),
            # Tool 1: Read (3 calls)
            _evt(2, 1001.0, "tool_start", session_id, {"tool_name": "Read"}),
            _evt(3, 1002.0, "tool_end", session_id, {"tool_name": "Read", "duration_ms": 100}),
            _evt(4, 1003.0, "tool_start", session_id, {"tool_name": "Read"}),
            _evt(5, 1004.0, "tool_end", session_id, {"tool_name": "Read", "duration_ms": 150}),
            _evt(6, 1005.0, "tool_start", session_id, {"tool_name": "Read"}),
            _evt(7, 1006.0, "tool_end", session_id, {"tool_name": "Read", "duration_ms": 200}),
            # Tool 2: Shell (2 calls)
            _evt(8, 1007.0, "tool_start", session_id, {"tool_name": "Shell"}),
            _evt(9, 1008.0, "tool_end", session_id, {"tool_name": "Shell", "duration_ms": 500}),
            _evt(10, 1009.0, "tool_start", session_id, {"tool_name": "Shell"}),
            _evt(11, 1010.0, "tool_end", session_id, {"tool_name": "Shell", "duration_ms": 600}),
            _evt(12, 1011.0, "session_end", session_id, {"summary": {"duration_ms": 11000}}),
        ]

        await backend.append(events)

        # Get session summary
        summary = await logger.get_session_summary()

        # Assertions
        assert summary.duration_ms == 11000
        assert len(summary.tool_breakdown) == 2

        # Find Read tool
        read_tool = next((t for t in summary.tool_breakdown if t.tool_name == "Read"), None)
        assert read_tool is not None
        assert read_tool.call_count == 3
        assert read_tool.total_duration_ms == 450  # 100 + 150 + 200

        # Find Shell tool
        shell_tool = next((t for t in summary.tool_breakdown if t.tool_name == "Shell"), None)
        assert shell_tool is not None
        assert shell_tool.call_count == 2
        assert shell_tool.total_duration_ms == 1100  # 500 + 600


@pytest.mark.asyncio
async def test_get_session_summary_unpaired_tool_start():
    """Test session summary handles unpaired tool_start events (Bug防护)."""
    with TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir)
        session_id = "test-session-unpaired"

        backend = FileEventLogBackend(log_dir=log_dir, session_id=session_id)
        logger = EventLogger(backend=backend, session_id=session_id)

        # Create events with unpaired tool_start (simulating crash/timeout)
        events = [
            _evt(1, 1000.0, "session_start", session_id, {}),
            _evt(2, 1001.0, "tool_start", session_id, {"tool_name": "Read"}),
            _evt(3, 1002.0, "tool_end", session_id, {"tool_name": "Read", "duration_ms": 100}),
            # Unpaired tool_start (no corresponding tool_end)
            _evt(4, 1003.0, "tool_start", session_id, {"tool_name": "Shell"}),
            _evt(5, 1004.0, "session_end", session_id, {"summary": {"duration_ms": 4000}}),
        ]

        await backend.append(events)

        # Get session summary
        summary = await logger.get_session_summary()

        # Assertions
        assert summary.duration_ms == 4000
        assert len(summary.tool_breakdown) == 2

        # Read tool should be complete
        read_tool = next((t for t in summary.tool_breakdown if t.tool_name == "Read"), None)
        assert read_tool.call_count == 1
        assert read_tool.total_duration_ms == 100

        # Shell tool should have call_count but zero duration (unpaired)
        shell_tool = next((t for t in summary.tool_breakdown if t.tool_name == "Shell"), None)
        assert shell_tool.call_count == 1
        assert shell_tool.total_duration_ms == 0  # No tool_end, so duration = 0


@pytest.mark.asyncio
async def test_get_session_summary_empty_log():
    """Test session summary with empty EventLog (Graceful degradation)."""
    with TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir)
        session_id = "test-session-empty"

        backend = FileEventLogBackend(log_dir=log_dir, session_id=session_id)
        logger = EventLogger(backend=backend, session_id=session_id)

        # Get session summary without any events
        summary = await logger.get_session_summary()

        # Assertions
        assert summary.session_id == session_id
        assert summary.duration_ms == 0
        assert len(summary.tool_breakdown) == 0
        assert len(summary.events_timeline) == 0
        assert isinstance(summary.task_metrics, dict)


@pytest.mark.asyncio
async def test_get_session_summary_events_limit():
    """Timeline loading should respect events_limit without truncating tool aggregation."""
    with TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir)
        session_id = "test-session-limit"

        backend = FileEventLogBackend(log_dir=log_dir, session_id=session_id)
        logger = EventLogger(backend=backend, session_id=session_id)

        # Create 200 events
        events = [
            StructuredEvent(
                sequence=i,
                timestamp=float(1000 + i),
                event_type="tool_start",
                session_id=session_id,
                data={"tool_name": f"Tool{i}"},
            )
            for i in range(1, 201)
        ]

        await backend.append(events)

        # Get session summary with limit=50
        summary = await logger.get_session_summary(events_limit=50, timeline_limit=20)

        # Assertions: Should only expose 20 events in timeline
        assert len(summary.events_timeline) <= 20
        # Tool breakdown still aggregates all tool_start events
        assert len(summary.tool_breakdown) == 200


@pytest.mark.asyncio
async def test_event_logger_close_persists_runtime_metrics():
    """SESSION_END should persist token usage and compaction task metrics."""
    with TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir)
        session_id = "test-session-runtime-metrics"

        backend = FileEventLogBackend(log_dir=log_dir, session_id=session_id)
        logger = EventLogger(backend=backend, session_id=session_id)

        tracker = init_token_tracker()
        tracker.record(
            {
                "prompt_tokens": 1200,
                "completion_tokens": 300,
                "total_tokens": 1500,
                "prompt_tokens_details": {
                    "cached_tokens": 700,
                    "cache_creation_input_tokens": 150,
                },
            },
            model_name="openai/gpt-5.4-mini",
        )
        metrics = create_task_metrics(session_id)
        metrics.record_compression(900, compression_type="compress", dedup_tokens_saved=120, integrity_skipped=1)

        try:
            await logger.start()
            await logger.close()

            summary = await logger.get_session_summary()
        finally:
            clear_task_metrics(session_id)
            reset_token_tracker()

        assert summary.task_metrics["compression_count"] == 1
        assert summary.task_metrics["total_tokens_saved"] == 900

        events = await backend.get_events(session_id)
        session_end = next(event for event in events if event.event_type == "session_end")
        persisted = session_end.data["summary"]

        token_econ = persisted["token_economics"]
        assert token_econ["usage"]["prompt_tokens"] == 1200
        assert token_econ["usage"]["completion_tokens"] == 300
        assert token_econ["usage"]["cached_tokens"] == 700
        assert token_econ["usage"]["cache_write_tokens"] == 150
        assert persisted["task_metrics"]["compression_count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
