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

    def test_chinese_intervals(self) -> None:
        assert parse_natural_interval("10分钟") == 600_000
        assert parse_natural_interval("2小时") == 7_200_000
        assert parse_natural_interval("半小时") == 1_800_000
        assert parse_natural_interval("1个半小时") == 5_400_000
        assert parse_natural_interval("每天") == 86_400_000
        assert parse_natural_interval("每隔15分钟") == 900_000
        assert parse_natural_interval("每2小时") == 7_200_000


class TestParseLoopCommandInput:
    def test_prefix_interval(self) -> None:
        ms, prompt = parse_loop_command_input("/loop 5m 检查构建状态")
        assert ms == 300_000
        assert prompt == "检查构建状态"

    def test_prefix_chinese_interval(self) -> None:
        ms, prompt = parse_loop_command_input("/loop 10分钟 检查PR列表")
        assert ms == 600_000
        assert prompt == "检查PR列表"

    def test_prefix_chinese_phrase(self) -> None:
        ms, prompt = parse_loop_command_input("/loop 每隔半小时 监控服务健康")
        assert ms == 1_800_000
        assert prompt == "监控服务健康"

    def test_prefix_every(self) -> None:
        ms, prompt = parse_loop_command_input("/loop every 20m review pr")
        assert ms == 1_200_000
        assert prompt == "review pr"

    def test_suffix_every(self) -> None:
        ms, prompt = parse_loop_command_input("/loop check deploy every 2 hours")
        assert ms == 7_200_000
        assert prompt == "check deploy"

    def test_suffix_chinese_interval(self) -> None:
        ms, prompt = parse_loop_command_input("/loop 抓取竞品数据 每隔2小时")
        assert ms == 7_200_000
        assert prompt == "抓取竞品数据"

    def test_suffix_plain_interval(self) -> None:
        ms, prompt = parse_loop_command_input("/loop 检查构建 10分钟")
        assert ms == 600_000
        assert prompt == "检查构建"

    def test_default_interval(self) -> None:
        ms, prompt = parse_loop_command_input("/loop 帮我盯竞品动态")
        assert ms == 600_000
        assert prompt == "帮我盯竞品动态"

    def test_multiline_prompt(self) -> None:
        ms, prompt = parse_loop_command_input("/loop 15m 检查构建状态:\n1. unit test\n2. e2e test")
        assert ms == 900_000
        assert "unit test" in prompt

    def test_empty(self) -> None:
        ms, prompt = parse_loop_command_input("/loop")
        assert ms == 600_000
        assert prompt == ""

    def test_pure_interval_without_prompt(self) -> None:
        ms1, p1 = parse_loop_command_input("/loop 5m")
        assert ms1 == 300_000
        assert p1 == ""

        ms2, p2 = parse_loop_command_input("/loop every 2h")
        assert ms2 == 7_200_000
        assert p2 == ""

        ms3, p3 = parse_loop_command_input("/loop 半小时")
        assert ms3 == 1_800_000
        assert p3 == ""

        ms4, p4 = parse_loop_command_input("/loop 每天")
        assert ms4 == 86_400_000
        assert p4 == ""

        ms5, p5 = parse_loop_command_input("/loop 15")
        assert ms5 == 900_000
        assert p5 == ""

    def test_command_aliases(self) -> None:
        ms_rep, p_rep = parse_loop_command_input("/repeat 10m check deploy")
        assert ms_rep == 600_000
        assert p_rep == "check deploy"

        ms_cron, p_cron = parse_loop_command_input("/cron 30m monitor logs")
        assert ms_cron == 1_800_000
        assert p_cron == "monitor logs"

        ms_empty, p_empty = parse_loop_command_input("/repeat 5m")
        assert ms_empty == 300_000
        assert p_empty == ""

    def test_enclosing_quotes_stripped(self) -> None:
        ms_dbl, p_dbl = parse_loop_command_input('/loop 5m "检查 PR 状态"')
        assert ms_dbl == 300_000
        assert p_dbl == "检查 PR 状态"

        ms_sgl, p_sgl = parse_loop_command_input("/loop 1h 'monitor service'")
        assert ms_sgl == 3_600_000
        assert p_sgl == "monitor service"

        ms_sfx, p_sfx = parse_loop_command_input('/loop "检查部署" every 10m')
        assert ms_sfx == 600_000
        assert p_sfx == "检查部署"
