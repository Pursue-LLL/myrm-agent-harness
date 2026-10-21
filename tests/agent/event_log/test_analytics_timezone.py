"""Unit tests for EventLogAnalytics timezone-aware bucketing.

[INPUT]
- EventLogAnalytics from myrm_agent_harness.agent.event_log.analytics
- FileEventLogBackend from myrm_agent_harness.agent.event_log.backends.file_backend
- StructuredEvent from myrm_agent_harness.agent.event_log.types

[OUTPUT]
- Pytest test cases verifying UTC, Asia/Shanghai, and invalid timezone bucketing

[POS]
- tests/agent/event_log/test_analytics_timezone.py: Harness layer observability regression tests
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from myrm_agent_harness.agent.event_log.analytics import EventLogAnalytics
from myrm_agent_harness.agent.event_log.backends.file_backend import FileEventLogBackend
from myrm_agent_harness.agent.event_log.types import StructuredEvent


@pytest.fixture
def temp_backend_factory(tmp_path: Path):
    log_dir = tmp_path / "event_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    def _create(session_id: str) -> FileEventLogBackend:
        return FileEventLogBackend(log_dir, session_id)

    return _create, FileEventLogBackend(log_dir, "default")


@pytest.mark.asyncio
async def test_get_global_activity_patterns_default_utc(temp_backend_factory) -> None:
    create_backend, default_backend = temp_backend_factory
    b1 = create_backend("s1")

    # 2026-10-12 10:00:00 UTC
    ts_utc = datetime(2026, 10, 12, 10, 0, 0, tzinfo=UTC).timestamp()
    await b1.append(
        [
            StructuredEvent(
                session_id="s1",
                sequence=1,
                timestamp=ts_utc,
                event_type="session_end",
                data={"summary": {"tool_calls": 5, "duration_ms": 1000.0}},
            )
        ]
    )

    analytics = EventLogAnalytics(default_backend)
    res = await analytics.get_global_activity_patterns()

    assert res.timezone == "UTC"
    assert len(res.daily_activities) == 1
    assert res.daily_activities[0].date == "2026-10-12"
    assert res.daily_activities[0].tool_calls == 5
    assert res.busiest_hour == 10
    assert res.by_hour.get(10) == 5


@pytest.mark.asyncio
async def test_get_global_activity_patterns_cross_midnight_asia_shanghai(temp_backend_factory) -> None:
    create_backend, default_backend = temp_backend_factory
    b1 = create_backend("s1")
    b2 = create_backend("s2")

    # Event 1: 2026-10-12 15:50:00 UTC -> 2026-10-12 23:50:00 Asia/Shanghai
    ts1 = datetime(2026, 10, 12, 15, 50, 0, tzinfo=UTC).timestamp()
    await b1.append(
        [
            StructuredEvent(
                session_id="s1",
                sequence=1,
                timestamp=ts1,
                event_type="session_end",
                data={"summary": {"tool_calls": 3, "duration_ms": 500.0}},
            )
        ]
    )

    # Event 2: 2026-10-12 16:10:00 UTC -> 2026-10-13 00:10:00 Asia/Shanghai (next day in Shanghai!)
    ts2 = datetime(2026, 10, 12, 16, 10, 0, tzinfo=UTC).timestamp()
    await b2.append(
        [
            StructuredEvent(
                session_id="s2",
                sequence=1,
                timestamp=ts2,
                event_type="session_end",
                data={"summary": {"tool_calls": 7, "duration_ms": 800.0}},
            )
        ]
    )

    analytics = EventLogAnalytics(default_backend)

    # When querying with UTC: both events fall on 2026-10-12
    utc_res = await analytics.get_global_activity_patterns(timezone="UTC")
    assert utc_res.timezone == "UTC"
    assert len(utc_res.daily_activities) == 1
    assert utc_res.daily_activities[0].date == "2026-10-12"
    assert utc_res.daily_activities[0].tool_calls == 10
    assert utc_res.by_hour.get(15) == 3
    assert utc_res.by_hour.get(16) == 7

    # When querying with Asia/Shanghai: events are split into 2 consecutive days!
    shanghai_res = await analytics.get_global_activity_patterns(timezone="Asia/Shanghai")
    assert shanghai_res.timezone == "Asia/Shanghai"
    assert len(shanghai_res.daily_activities) == 2
    assert shanghai_res.daily_activities[0].date == "2026-10-12"
    assert shanghai_res.daily_activities[0].tool_calls == 3
    assert shanghai_res.daily_activities[1].date == "2026-10-13"
    assert shanghai_res.daily_activities[1].tool_calls == 7

    # Shanghai local hours: 23 and 0
    assert shanghai_res.by_hour.get(23) == 3
    assert shanghai_res.by_hour.get(0) == 7
    assert shanghai_res.busiest_hour == 0  # 7 calls at hour 0
    assert shanghai_res.active_days == 2
    assert shanghai_res.max_streak == 2


@pytest.mark.asyncio
async def test_get_global_activity_patterns_invalid_timezone_fallback(temp_backend_factory) -> None:
    create_backend, default_backend = temp_backend_factory
    b1 = create_backend("s1")

    ts = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC).timestamp()
    await b1.append(
        [
            StructuredEvent(
                session_id="s1",
                sequence=1,
                timestamp=ts,
                event_type="session_end",
                data={"summary": {"tool_calls": 2, "duration_ms": 100.0}},
            )
        ]
    )

    analytics = EventLogAnalytics(default_backend)
    res = await analytics.get_global_activity_patterns(timezone="NonExistent/Invalid_TZ")
    assert res.timezone == "UTC"
    assert len(res.daily_activities) == 1
    assert res.daily_activities[0].date == "2026-10-12"
