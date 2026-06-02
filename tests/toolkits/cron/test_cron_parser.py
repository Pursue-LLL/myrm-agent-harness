"""Unit tests for engine/parser.py — covers compute_next_run, validate, describe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.cron.engine.parser import (
    compute_next_run,
    describe_schedule,
    validate_cron_expr,
    validate_timezone,
)
from myrm_agent_harness.toolkits.cron.types import Schedule, ScheduleKind

_NOW = datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC)


class TestComputeNextRun:
    def test_cron(self) -> None:
        sched = Schedule(kind=ScheduleKind.CRON, expr="0 * * * *")
        result = compute_next_run(sched, _NOW)
        assert result is not None
        assert result > _NOW

    def test_interval(self) -> None:
        sched = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000)
        result = compute_next_run(sched, _NOW)
        assert result is not None
        assert result == _NOW + timedelta(milliseconds=300_000)

    def test_once_future(self) -> None:
        future = _NOW + timedelta(hours=1)
        sched = Schedule(kind=ScheduleKind.ONCE, run_at=future)
        result = compute_next_run(sched, _NOW)
        assert result == future

    def test_once_past(self) -> None:
        past = _NOW - timedelta(hours=1)
        sched = Schedule(kind=ScheduleKind.ONCE, run_at=past)
        result = compute_next_run(sched, _NOW)
        assert result is None

    def test_cron_with_timezone(self) -> None:
        sched = Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *", tz="Asia/Shanghai")
        result = compute_next_run(sched, _NOW)
        assert result is not None


class TestValidateCronExpr:
    def test_valid(self) -> None:
        assert validate_cron_expr("0 9 * * *") is True

    def test_invalid(self) -> None:
        assert validate_cron_expr("not a cron") is False


class TestValidateTimezone:
    def test_valid(self) -> None:
        assert validate_timezone("Asia/Shanghai") is True

    def test_invalid(self) -> None:
        assert validate_timezone("Not/A/Timezone") is False


class TestDescribeSchedule:
    def test_cron(self) -> None:
        sched = Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *")
        assert "cron:" in describe_schedule(sched)

    def test_cron_with_tz(self) -> None:
        sched = Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *", tz="Asia/Shanghai")
        desc = describe_schedule(sched)
        assert "Asia/Shanghai" in desc

    def test_interval_seconds(self) -> None:
        sched = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=30_000)
        assert describe_schedule(sched) == "every 30s"

    def test_interval_minutes(self) -> None:
        sched = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=300_000)
        assert describe_schedule(sched) == "every 5m"

    def test_interval_hours(self) -> None:
        sched = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3_600_000)
        assert describe_schedule(sched) == "every 1h"

    def test_interval_hours_minutes(self) -> None:
        sched = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=5_400_000)
        assert describe_schedule(sched) == "every 1h30m"

    def test_interval_days(self) -> None:
        sched = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=86_400_000)
        assert describe_schedule(sched) == "every 1d"

    def test_once(self) -> None:
        sched = Schedule(kind=ScheduleKind.ONCE, run_at=_NOW)
        assert "once at" in describe_schedule(sched)
