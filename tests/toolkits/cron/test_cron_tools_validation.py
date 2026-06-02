"""Unit tests for cron tools helper functions and guards."""

from __future__ import annotations

from myrm_agent_harness.toolkits.cron.cron_agent_tools import (
    _IN_CRON_EXECUTION,
    _build_active_hours,
    _build_schedule,
    enter_cron_execution_context,
    exit_cron_execution_context,
)
from myrm_agent_harness.toolkits.cron.types import ScheduleKind

# ---------------------------------------------------------------------------
# _build_active_hours
# ---------------------------------------------------------------------------


class TestBuildActiveHours:
    def test_valid_input(self):
        ah = _build_active_hours("09:00", "18:00", "Asia/Shanghai")
        assert ah is not None
        assert ah.start == "09:00"
        assert ah.end == "18:00"
        assert ah.tz == "Asia/Shanghai"

    def test_empty_start(self):
        assert _build_active_hours("", "18:00", "UTC") is None

    def test_empty_end(self):
        assert _build_active_hours("09:00", "", "UTC") is None

    def test_both_empty(self):
        assert _build_active_hours("", "", "") is None

    def test_whitespace_only(self):
        assert _build_active_hours("  ", "  ", "  ") is None

    def test_default_tz(self):
        ah = _build_active_hours("09:00", "18:00", "")
        assert ah is not None
        assert ah.tz == "UTC"

    def test_strips_whitespace(self):
        ah = _build_active_hours(" 09:00 ", " 18:00 ", " UTC ")
        assert ah is not None
        assert ah.start == "09:00"
        assert ah.end == "18:00"
        assert ah.tz == "UTC"


# ---------------------------------------------------------------------------
# _build_schedule
# ---------------------------------------------------------------------------


class TestBuildSchedule:
    def test_cron_expr(self):
        err, schedule = _build_schedule("0 9 * * *", 0, "", "Asia/Shanghai")
        assert err is None
        assert schedule is not None
        assert schedule.kind == ScheduleKind.CRON
        assert schedule.expr == "0 9 * * *"

    def test_every_minutes(self):
        err, schedule = _build_schedule("", 10, "", "")
        assert err is None
        assert schedule is not None
        assert schedule.kind == ScheduleKind.INTERVAL
        assert schedule.interval_ms == 600_000

    def test_no_schedule_params(self):
        err, schedule = _build_schedule("", 0, "", "")
        assert err is not None
        assert schedule is None

    def test_min_interval_rejected(self):
        err, _schedule = _build_schedule("", 2, "", "")
        assert err is not None
        assert "5" in err  # mentions minimum


# ---------------------------------------------------------------------------
# Cron Self-Scheduling Guard (ContextVar)
# ---------------------------------------------------------------------------


class TestCronSelfSchedulingGuard:
    def test_default_not_in_cron(self):
        assert _IN_CRON_EXECUTION.get() is False

    def test_enter_and_exit(self):
        token = enter_cron_execution_context()
        assert _IN_CRON_EXECUTION.get() is True
        exit_cron_execution_context(token)
        assert _IN_CRON_EXECUTION.get() is False

    def test_nested_context(self):
        token1 = enter_cron_execution_context()
        assert _IN_CRON_EXECUTION.get() is True
        exit_cron_execution_context(token1)
        assert _IN_CRON_EXECUTION.get() is False
