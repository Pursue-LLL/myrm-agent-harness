"""Unit tests for engine/parser.py — covers compute_next_run, validate, describe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.cron.engine.parser import (
    compute_next_run,
    describe_schedule,
    parse_loop_command_input,
    parse_natural_interval,
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


class TestParseNaturalInterval:
    def test_short_formats(self) -> None:
        assert parse_natural_interval("10m") == 600_000
        assert parse_natural_interval("1h") == 3_600_000
        assert parse_natural_interval("2d") == 172_800_000
        assert parse_natural_interval("30s") == 60_000  # min 1m bound

    def test_prefix_formats(self) -> None:
        assert parse_natural_interval("every 20m") == 1_200_000
        assert parse_natural_interval("every 2 hours") == 7_200_000
        assert parse_natural_interval("each 5 minutes") == 300_000

    def test_pure_digits(self) -> None:
        assert parse_natural_interval("15") == 900_000


class TestParseLoopCommandInput:
    def test_prefix_interval(self) -> None:
        ms, prompt = parse_loop_command_input("/loop 5m 检查构建状态")
        assert ms == 300_000
        assert prompt == "检查构建状态"

    def test_prefix_every(self) -> None:
        ms, prompt = parse_loop_command_input("/loop every 20m review pr")
        assert ms == 1_200_000
        assert prompt == "review pr"

    def test_suffix_every(self) -> None:
        ms, prompt = parse_loop_command_input("/loop check deploy every 2 hours")
        assert ms == 7_200_000
        assert prompt == "check deploy"

    def test_default_interval(self) -> None:
        ms, prompt = parse_loop_command_input("/loop 帮我盯竞品动态")
        assert ms == 600_000
        assert prompt == "帮我盯竞品动态"

    def test_empty(self) -> None:
        ms, prompt = parse_loop_command_input("/loop")
        assert ms == 600_000
        assert prompt == ""
