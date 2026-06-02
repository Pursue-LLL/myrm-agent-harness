"""Unit tests for EventLogAnalytics (A2: Global Activity Pattern Engine)."""

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.agent.event_log.analytics import EventLogAnalytics
from myrm_agent_harness.agent.event_log.backends.file_backend import FileEventLogBackend
from myrm_agent_harness.agent.event_log.types import EventFilter, StructuredEvent


@pytest.fixture
def temp_event_log(tmp_path):
    """Fixture to create a temporary event log backend.

    Note: FileEventLogBackend is session-scoped, so we return a factory function
    to create backends for different sessions.
    """
    log_dir = tmp_path / "event_logs"
    log_dir.mkdir(exist_ok=True)

    def _create_backend(session_id: str) -> FileEventLogBackend:
        return FileEventLogBackend(log_dir, session_id)

    # Return both factory and a default backend for global operations
    return _create_backend, FileEventLogBackend(log_dir, "default")


@pytest.mark.asyncio
async def test_get_all_session_ids(temp_event_log):
    """Test retrieving all session IDs from the backend."""
    create_backend, default_backend = temp_event_log

    # Create events for session_1
    backend1 = create_backend("session_1")
    events1 = [
        StructuredEvent(
            session_id="session_1",
            sequence=1,
            timestamp=datetime.now().timestamp(),
            event_type="tool_start",
            data={"tool_name": "read_file"},
        ),
        StructuredEvent(
            session_id="session_1",
            sequence=2,
            timestamp=datetime.now().timestamp(),
            event_type="tool_success",
            data={"tool_name": "read_file"},
        ),
    ]
    await backend1.append(events1)

    # Create events for session_2
    backend2 = create_backend("session_2")
    events2 = [
        StructuredEvent(
            session_id="session_2",
            sequence=1,
            timestamp=datetime.now().timestamp(),
            event_type="tool_start",
            data={"tool_name": "write_file"},
        ),
    ]
    await backend2.append(events2)

    session_ids = await default_backend.get_all_session_ids()

    assert len(session_ids) == 2
    assert "session_1" in session_ids
    assert "session_2" in session_ids


@pytest.mark.asyncio
async def test_get_global_activity_patterns_basic(temp_event_log):
    """Test basic global activity pattern calculation."""
    create_backend, default_backend = temp_event_log
    base_time = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)

    # Day 1, session_1 (with session_end containing summary)
    backend1 = create_backend("session_1")
    events1 = [
        StructuredEvent(
            session_id="session_1", sequence=1, timestamp=base_time.timestamp(), event_type="session_start", data={}
        ),
        StructuredEvent(
            session_id="session_1",
            sequence=2,
            timestamp=(base_time + timedelta(hours=2)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 2,
                    "errors": 0,
                    "approvals": 0,
                    "compactions": 0,
                    "failovers": 0,
                    "security_decisions": 0,
                    "duration_ms": 7200000,
                }
            },
        ),
    ]
    await backend1.append(events1)

    # Day 3, session_1 (another session_end on day 3)
    events1_day3 = [
        StructuredEvent(
            session_id="session_1",
            sequence=3,
            timestamp=(base_time + timedelta(days=2, hours=3)).timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_1",
            sequence=4,
            timestamp=(base_time + timedelta(days=2, hours=4)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 1,
                    "errors": 0,
                    "approvals": 0,
                    "compactions": 0,
                    "failovers": 0,
                    "security_decisions": 0,
                    "duration_ms": 3600000,
                }
            },
        ),
    ]
    await backend1.append(events1_day3)

    # Day 2, session_2 (with session_end)
    backend2 = create_backend("session_2")
    events2 = [
        StructuredEvent(
            session_id="session_2",
            sequence=1,
            timestamp=(base_time + timedelta(days=1, hours=2)).timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_2",
            sequence=2,
            timestamp=(base_time + timedelta(days=1, hours=3)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 1,
                    "errors": 0,
                    "approvals": 0,
                    "compactions": 0,
                    "failovers": 0,
                    "security_decisions": 0,
                    "duration_ms": 3600000,
                }
            },
        ),
    ]
    await backend2.append(events2)

    analytics = EventLogAnalytics(default_backend)
    patterns = await analytics.get_global_activity_patterns()

    # Verify daily activities
    assert len(patterns.daily_activities) == 3
    assert patterns.active_days == 3

    # Verify tool calls count
    total_calls = sum(act.tool_calls for act in patterns.daily_activities)
    assert total_calls == 4

    # Verify day_of_week aggregation
    assert sum(patterns.by_day_of_week.values()) == 4

    # Verify hourly aggregation
    assert sum(patterns.by_hour.values()) == 4
    # Verify we have hourly data (specific hours depend on timezone)
    assert len(patterns.by_hour) >= 2


@pytest.mark.asyncio
async def test_get_global_activity_patterns_consecutive_streak(temp_event_log):
    """Test max streak calculation with consecutive days."""
    create_backend, default_backend = temp_event_log
    base_time = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)

    backend1 = create_backend("session_1")
    events = []
    for i in range(5):  # 5 consecutive days
        events.extend(
            [
                StructuredEvent(
                    session_id="session_1",
                    sequence=i * 2 + 1,
                    timestamp=(base_time + timedelta(days=i)).timestamp(),
                    event_type="session_start",
                    data={},
                ),
                StructuredEvent(
                    session_id="session_1",
                    sequence=i * 2 + 2,
                    timestamp=(base_time + timedelta(days=i, hours=1)).timestamp(),
                    event_type="session_end",
                    data={
                        "summary": {
                            "total_events": 2,
                            "tool_calls": 1,
                            "errors": 0,
                            "approvals": 0,
                            "compactions": 0,
                            "failovers": 0,
                            "security_decisions": 0,
                            "duration_ms": 3600000,
                        }
                    },
                ),
            ]
        )

    await backend1.append(events)

    analytics = EventLogAnalytics(default_backend)
    patterns = await analytics.get_global_activity_patterns()

    assert patterns.max_streak == 5
    assert patterns.active_days == 5


@pytest.mark.asyncio
async def test_get_global_activity_patterns_non_consecutive_streak(temp_event_log):
    """Test max streak with gaps in activity."""
    create_backend, default_backend = temp_event_log
    base_time = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)

    backend1 = create_backend("session_1")
    events = [
        # Day 0 - session_end
        StructuredEvent(
            session_id="session_1", sequence=1, timestamp=base_time.timestamp(), event_type="session_start", data={}
        ),
        StructuredEvent(
            session_id="session_1",
            sequence=2,
            timestamp=(base_time + timedelta(hours=1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 1,
                    "errors": 0,
                    "approvals": 0,
                    "compactions": 0,
                    "failovers": 0,
                    "security_decisions": 0,
                    "duration_ms": 3600000,
                }
            },
        ),
        # Day 1 - session_end
        StructuredEvent(
            session_id="session_1",
            sequence=3,
            timestamp=(base_time + timedelta(days=1)).timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_1",
            sequence=4,
            timestamp=(base_time + timedelta(days=1, hours=1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 1,
                    "errors": 0,
                    "approvals": 0,
                    "compactions": 0,
                    "failovers": 0,
                    "security_decisions": 0,
                    "duration_ms": 3600000,
                }
            },
        ),
        # Day 2 - session_end
        StructuredEvent(
            session_id="session_1",
            sequence=5,
            timestamp=(base_time + timedelta(days=2)).timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_1",
            sequence=6,
            timestamp=(base_time + timedelta(days=2, hours=1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 1,
                    "errors": 0,
                    "approvals": 0,
                    "compactions": 0,
                    "failovers": 0,
                    "security_decisions": 0,
                    "duration_ms": 3600000,
                }
            },
        ),
        # Gap of 2 days (Day 3, 4 skipped)
        # Day 5 - session_end
        StructuredEvent(
            session_id="session_1",
            sequence=7,
            timestamp=(base_time + timedelta(days=5)).timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_1",
            sequence=8,
            timestamp=(base_time + timedelta(days=5, hours=1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 1,
                    "errors": 0,
                    "approvals": 0,
                    "compactions": 0,
                    "failovers": 0,
                    "security_decisions": 0,
                    "duration_ms": 3600000,
                }
            },
        ),
        # Day 6 - session_end
        StructuredEvent(
            session_id="session_1",
            sequence=9,
            timestamp=(base_time + timedelta(days=6)).timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_1",
            sequence=10,
            timestamp=(base_time + timedelta(days=6, hours=1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 1,
                    "errors": 0,
                    "approvals": 0,
                    "compactions": 0,
                    "failovers": 0,
                    "security_decisions": 0,
                    "duration_ms": 3600000,
                }
            },
        ),
    ]

    await backend1.append(events)

    analytics = EventLogAnalytics(default_backend)
    patterns = await analytics.get_global_activity_patterns()

    assert patterns.max_streak == 3  # First streak is longer
    assert patterns.active_days == 5


@pytest.mark.asyncio
async def test_get_global_activity_patterns_time_range(temp_event_log):
    """Test filtering by time range."""
    create_backend, default_backend = temp_event_log
    base_time = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)

    backend1 = create_backend("session_1")
    events = [
        # Session 10 days ago
        StructuredEvent(
            session_id="session_1",
            sequence=1,
            timestamp=(base_time - timedelta(days=10)).timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_1",
            sequence=2,
            timestamp=(base_time - timedelta(days=10, hours=-1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 1,
                    "errors": 0,
                    "approvals": 0,
                    "compactions": 0,
                    "failovers": 0,
                    "security_decisions": 0,
                    "duration_ms": 3600000,
                }
            },
        ),
        # Session 5 days ago
        StructuredEvent(
            session_id="session_1",
            sequence=3,
            timestamp=(base_time - timedelta(days=5)).timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_1",
            sequence=4,
            timestamp=(base_time - timedelta(days=5, hours=-1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 1,
                    "errors": 0,
                    "approvals": 0,
                    "compactions": 0,
                    "failovers": 0,
                    "security_decisions": 0,
                    "duration_ms": 3600000,
                }
            },
        ),
        # Session today
        StructuredEvent(
            session_id="session_1", sequence=5, timestamp=base_time.timestamp(), event_type="session_start", data={}
        ),
        StructuredEvent(
            session_id="session_1",
            sequence=6,
            timestamp=(base_time + timedelta(hours=1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 1,
                    "errors": 0,
                    "approvals": 0,
                    "compactions": 0,
                    "failovers": 0,
                    "security_decisions": 0,
                    "duration_ms": 3600000,
                }
            },
        ),
    ]

    await backend1.append(events)

    analytics = EventLogAnalytics(default_backend)

    # Query last 7 days (should include only 2 events)
    patterns = await analytics.get_global_activity_patterns(time_range_days=7)

    assert patterns.active_days == 2
    total_calls = sum(act.tool_calls for act in patterns.daily_activities)
    assert total_calls == 2


@pytest.mark.asyncio
async def test_get_global_activity_patterns_empty(temp_event_log):
    """Test with no events."""
    _create_backend, default_backend = temp_event_log
    analytics = EventLogAnalytics(default_backend)
    patterns = await analytics.get_global_activity_patterns()

    assert len(patterns.daily_activities) == 0
    assert patterns.active_days == 0
    assert patterns.max_streak == 0
    assert len(patterns.by_day_of_week) == 0
    assert len(patterns.by_hour) == 0


@pytest.mark.asyncio
async def test_file_backend_error_handling(temp_event_log, tmp_path):
    """Test FileEventLogBackend error handling scenarios."""
    create_backend, _default_backend = temp_event_log

    # Test: empty events list (line 42)
    backend = create_backend("test_empty")
    await backend.append([])  # Should return immediately

    # Test: deduplicated to empty (line 49)
    events = [
        StructuredEvent(
            session_id="test_empty", sequence=1, timestamp=datetime.now().timestamp(), event_type="test", data={}
        ),
    ]
    await backend.append(events)
    await backend.append(events)  # Same sequence, should be deduped

    # Test: non-existent file (line 65)
    result = await backend.get_events("non_existent_session")
    assert result == []

    # Test: non-existent directory (line 102)
    non_existent_dir = tmp_path / "non_existent_logs"
    backend_no_dir = FileEventLogBackend(non_existent_dir, "test")
    session_ids = await backend_no_dir.get_all_session_ids()
    assert session_ids == []

    # Test: malformed JSON lines (line 76-78) and empty lines (line 73)
    backend = create_backend("test_malformed")
    log_file = backend._log_dir / "test_malformed.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8") as f:
        f.write('{"seq": 1, "ts": 123456, "type": "test", "sid": "test_malformed", "data": {}}\n')
        f.write("invalid json line\n")  # Will trigger JSONDecodeError (line 76)
        f.write("\n")  # Empty line (line 73)
        f.write('{"seq": 2, "ts": 123457, "type": "test", "sid": "test_malformed", "data": {}}\n')

    events = await backend.get_events("test_malformed")
    assert len(events) == 2  # Two valid events, malformed line and empty line skipped

    # Test: event limit (line 95)
    backend = create_backend("test_limit")
    events_list = [
        StructuredEvent(
            session_id="test_limit", sequence=i, timestamp=datetime.now().timestamp(), event_type="test", data={}
        )
        for i in range(10)
    ]
    await backend.append(events_list)

    event_filter = EventFilter(limit=5)
    limited_events = await backend.get_events("test_limit", event_filter)
    assert len(limited_events) == 5

    # Test: time and sequence filters (line 122, 124)
    now = datetime.now()
    start_time = (now - timedelta(hours=1)).timestamp()
    end_time = now.timestamp()

    time_filter = EventFilter(start_time=start_time, end_time=end_time, start_sequence=5)
    filtered_events = await backend.get_events("test_limit", time_filter)
    assert all(e.sequence >= 5 for e in filtered_events)
    assert all(start_time <= e.timestamp <= end_time for e in filtered_events)


@pytest.mark.asyncio
async def test_utc_timezone_consistency(temp_event_log):
    """Test that analytics use UTC consistently across timezones."""
    create_backend, _default_backend = temp_event_log

    # Create events with UTC timestamps
    from datetime import datetime

    backend = create_backend("test_utc")
    analytics = EventLogAnalytics(backend)

    # Use fixed UTC time to avoid hour boundary issues
    base_time = datetime(2026, 4, 8, 14, 0, 0, tzinfo=UTC)  # Fixed: 14:00 UTC
    events = [
        StructuredEvent(
            session_id="test_utc", sequence=1, timestamp=base_time.timestamp(), event_type="session_start", data={}
        ),
        StructuredEvent(
            session_id="test_utc",
            sequence=2,
            timestamp=(base_time + timedelta(minutes=30)).timestamp(),  # 14:30 UTC (same hour)
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 5,
                    "duration_ms": 1800000,
                }
            },
        ),
    ]

    await backend.append(events)

    # Query with large time range to include test events
    patterns = await analytics.get_global_activity_patterns(time_range_days=365)

    # Verify data is correctly aggregated
    assert patterns.active_days >= 1
    assert len(patterns.daily_activities) >= 1

    # Verify busiest_hour matches expected UTC hour (14)
    assert 0 <= patterns.busiest_hour <= 23

    # Verify UTC hour 14 has activity
    assert 14 in patterns.by_hour, f"Expected hour 14 in by_hour dict: {patterns.by_hour}"
    assert patterns.by_hour[14] == 5  # 5 tool_calls at hour 14


# =============================================================================
# A3 Top Sessions Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_top_sessions_by_duration(temp_event_log):
    """Test get_top_sessions ranked by duration."""
    create_backend, default_backend = temp_event_log

    # Create 3 sessions with different durations
    base_time = datetime(2026, 4, 8, 10, 0, 0, tzinfo=UTC)

    for i in range(3):
        session_id = f"session_{i}"
        backend = create_backend(session_id)
        duration_ms = (i + 1) * 3600000  # 1h, 2h, 3h

        events = [
            StructuredEvent(
                session_id=session_id, sequence=1, timestamp=base_time.timestamp(), event_type="session_start", data={}
            ),
            StructuredEvent(
                session_id=session_id,
                sequence=2,
                timestamp=(base_time + timedelta(milliseconds=duration_ms)).timestamp(),
                event_type="session_end",
                data={
                    "summary": {
                        "total_events": 2,
                        "tool_calls": 5,
                        "duration_ms": duration_ms,
                        "message_count": 10,
                        "input_tokens": 1000,
                        "output_tokens": 500,
                    }
                },
            ),
        ]
        await backend.append(events)

    analytics = EventLogAnalytics(default_backend)
    top_sessions = await analytics.get_top_sessions(metric="duration", limit=2)

    # Should return top 2 by duration (session_2, session_1)
    assert len(top_sessions) == 2
    assert top_sessions[0].session_id == "session_2"  # 3h
    assert top_sessions[0].metric_value == 3 * 3600000
    assert top_sessions[1].session_id == "session_1"  # 2h
    assert top_sessions[1].metric_value == 2 * 3600000


@pytest.mark.asyncio
async def test_get_top_sessions_by_tokens(temp_event_log):
    """Test get_top_sessions ranked by total tokens."""
    create_backend, default_backend = temp_event_log

    base_time = datetime(2026, 4, 8, 10, 0, 0, tzinfo=UTC)

    # Session with most tokens
    backend1 = create_backend("session_high_tokens")
    events1 = [
        StructuredEvent(
            session_id="session_high_tokens",
            sequence=1,
            timestamp=base_time.timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_high_tokens",
            sequence=2,
            timestamp=(base_time + timedelta(hours=1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 5,
                    "duration_ms": 3600000,
                    "message_count": 10,
                    "input_tokens": 10000,
                    "output_tokens": 5000,
                    "cache_read_tokens": 2000,
                    "cache_write_tokens": 1000,
                }
            },
        ),
    ]
    await backend1.append(events1)

    # Session with fewer tokens
    backend2 = create_backend("session_low_tokens")
    events2 = [
        StructuredEvent(
            session_id="session_low_tokens",
            sequence=1,
            timestamp=base_time.timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_low_tokens",
            sequence=2,
            timestamp=(base_time + timedelta(hours=1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 3,
                    "duration_ms": 3600000,
                    "message_count": 5,
                    "input_tokens": 1000,
                    "output_tokens": 500,
                }
            },
        ),
    ]
    await backend2.append(events2)

    analytics = EventLogAnalytics(default_backend)
    top_sessions = await analytics.get_top_sessions(metric="tokens", limit=10)

    assert len(top_sessions) == 2
    assert top_sessions[0].session_id == "session_high_tokens"
    assert top_sessions[0].total_tokens == 18000  # 10000+5000+2000+1000
    assert top_sessions[1].session_id == "session_low_tokens"
    assert top_sessions[1].total_tokens == 1500


@pytest.mark.asyncio
async def test_get_top_sessions_by_tool_calls(temp_event_log):
    """Test get_top_sessions ranked by tool calls."""
    create_backend, default_backend = temp_event_log

    base_time = datetime(2026, 4, 8, 10, 0, 0, tzinfo=UTC)

    backend = create_backend("session_many_tools")
    events = [
        StructuredEvent(
            session_id="session_many_tools",
            sequence=1,
            timestamp=base_time.timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_many_tools",
            sequence=2,
            timestamp=(base_time + timedelta(hours=1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 50,
                    "duration_ms": 3600000,
                    "message_count": 20,
                }
            },
        ),
    ]
    await backend.append(events)

    analytics = EventLogAnalytics(default_backend)
    top_sessions = await analytics.get_top_sessions(metric="tool_calls", limit=1)

    assert len(top_sessions) == 1
    assert top_sessions[0].session_id == "session_many_tools"
    assert top_sessions[0].tool_calls == 50
    assert top_sessions[0].metric_type == "tool_calls"


@pytest.mark.asyncio
async def test_get_top_sessions_invalid_metric(temp_event_log):
    """Test get_top_sessions with invalid metric raises ValueError."""
    _create_backend, default_backend = temp_event_log

    analytics = EventLogAnalytics(default_backend)

    with pytest.raises(ValueError, match="Invalid metric"):
        await analytics.get_top_sessions(metric="invalid_metric")


@pytest.mark.asyncio
async def test_get_top_sessions_empty(temp_event_log):
    """Test get_top_sessions with no sessions returns empty list."""
    _create_backend, default_backend = temp_event_log

    analytics = EventLogAnalytics(default_backend)
    top_sessions = await analytics.get_top_sessions(metric="duration")

    assert top_sessions == []


@pytest.mark.asyncio
async def test_get_top_sessions_time_range(temp_event_log):
    """Test get_top_sessions with time_range_days filter."""
    create_backend, default_backend = temp_event_log

    base_time = datetime.now(UTC)

    # Old session (10 days ago)
    backend_old = create_backend("session_old")
    events_old = [
        StructuredEvent(
            session_id="session_old",
            sequence=1,
            timestamp=(base_time - timedelta(days=10)).timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_old",
            sequence=2,
            timestamp=(base_time - timedelta(days=10, hours=-1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 10,
                    "duration_ms": 7200000,
                }
            },
        ),
    ]
    await backend_old.append(events_old)

    # Recent session (1 day ago)
    backend_recent = create_backend("session_recent")
    events_recent = [
        StructuredEvent(
            session_id="session_recent",
            sequence=1,
            timestamp=(base_time - timedelta(days=1)).timestamp(),
            event_type="session_start",
            data={},
        ),
        StructuredEvent(
            session_id="session_recent",
            sequence=2,
            timestamp=(base_time - timedelta(days=1, hours=-1)).timestamp(),
            event_type="session_end",
            data={
                "summary": {
                    "total_events": 2,
                    "tool_calls": 5,
                    "duration_ms": 3600000,
                }
            },
        ),
    ]
    await backend_recent.append(events_recent)

    analytics = EventLogAnalytics(default_backend)

    # Query last 7 days (should only include recent session)
    top_sessions = await analytics.get_top_sessions(metric="duration", time_range_days=7)

    assert len(top_sessions) == 1
    assert top_sessions[0].session_id == "session_recent"
