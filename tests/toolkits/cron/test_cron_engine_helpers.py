"""Unit tests for engine/helpers.py — covers functions not tested elsewhere."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.cron.engine.helpers import (
    BACKOFF_SCHEDULE_MS,
    _ensure_utc,
    classify_transient_error,
    compute_stagger_offset_s,
    error_backoff_ms,
    extract_telemetry,
    is_past_misfire_grace,
    is_top_of_hour_cron,
    pre_execution_check,
    resolve_failure_alert,
    resolve_stagger_ms,
    should_send_failure_alert,
)
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    DeliveryConfig,
    FailureAlertConfig,
    JobResult,
    JobStatus,
    JobType,
    Schedule,
    ScheduleKind,
)

_NOW = datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC)
_SCHED_CRON = Schedule(kind=ScheduleKind.CRON, expr="0 * * * *")
_SCHED_INTERVAL = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=60_000)
_DELIVERY = DeliveryConfig(channel="none")


def _job(**overrides: object) -> CronJob:
    defaults: dict[str, object] = {
        "id": "j1",
        "user_id": "u1",
        "name": "test",
        "job_type": JobType.SHELL,
        "command": "echo hi",
        "schedule": _SCHED_CRON,
        "delivery": _DELIVERY,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return CronJob(**defaults)  # type: ignore[arg-type]


class TestEnsureUtc:
    def test_naive_gets_utc(self) -> None:
        naive = datetime(2026, 1, 1, 12, 0, 0)
        result = _ensure_utc(naive)
        assert result.tzinfo is UTC

    def test_aware_unchanged(self) -> None:
        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert _ensure_utc(aware) is aware


class TestStagger:
    def test_explicit_zero(self) -> None:
        sched = Schedule(kind=ScheduleKind.CRON, expr="0 * * * *", stagger_ms=0)
        assert resolve_stagger_ms(_job(schedule=sched)) == 0

    def test_explicit_value(self) -> None:
        sched = Schedule(kind=ScheduleKind.CRON, expr="0 * * * *", stagger_ms=10_000)
        assert resolve_stagger_ms(_job(schedule=sched)) == 10_000

    def test_auto_top_of_hour(self) -> None:
        assert resolve_stagger_ms(_job(schedule=_SCHED_CRON)) == 5 * 60 * 1000

    def test_auto_non_top_of_hour(self) -> None:
        sched = Schedule(kind=ScheduleKind.CRON, expr="30 * * * *")
        assert resolve_stagger_ms(_job(schedule=sched)) == 0

    def test_interval_no_stagger(self) -> None:
        assert resolve_stagger_ms(_job(schedule=_SCHED_INTERVAL)) == 0


class TestIsTopOfHourCron:
    def test_top_of_hour(self) -> None:
        assert is_top_of_hour_cron("0 * * * *") is True

    def test_specific_hour(self) -> None:
        assert is_top_of_hour_cron("0 9 * * *") is False

    def test_non_zero_minute(self) -> None:
        assert is_top_of_hour_cron("30 * * * *") is False

    def test_short_expr(self) -> None:
        assert is_top_of_hour_cron("0 *") is False


class TestComputeStaggerOffsetS:
    def test_explicit(self) -> None:
        assert compute_stagger_offset_s(10_000, None) == 10.0

    def test_auto_top_of_hour(self) -> None:
        assert compute_stagger_offset_s(None, "0 * * * *") == 300.0

    def test_no_stagger(self) -> None:
        assert compute_stagger_offset_s(None, "30 * * * *") == 0.0


class TestPreExecutionCheck:
    def test_expired(self) -> None:
        job = _job(expires_at=_NOW - timedelta(hours=1))
        assert pre_execution_check(job, _NOW) == "expired"
        assert job.status == JobStatus.PAUSED

    def test_max_fires_reached(self) -> None:
        job = _job(max_fires=5, fire_count=5)
        assert pre_execution_check(job, _NOW) == "max_fires_reached"

    def test_cooldown_active(self) -> None:
        job = _job(
            cooldown_seconds=300,
            last_run_at=_NOW - timedelta(seconds=60),
        )
        assert pre_execution_check(job, _NOW) == "cooldown_active"

    def test_runnable(self) -> None:
        assert pre_execution_check(_job(), _NOW) is None


class TestIsPastMisfireGrace:
    def test_past_grace(self) -> None:
        job = _job(
            next_run_at=_NOW - timedelta(minutes=30),
            misfire_grace_seconds=60,
        )
        assert is_past_misfire_grace(job, _NOW) is True

    def test_within_grace(self) -> None:
        job = _job(
            next_run_at=_NOW - timedelta(seconds=30),
            misfire_grace_seconds=60,
        )
        assert is_past_misfire_grace(job, _NOW) is False

    def test_no_next_run(self) -> None:
        job = _job(next_run_at=None)
        assert is_past_misfire_grace(job, _NOW) is False


class TestFailureAlert:
    def test_disabled_by_false(self) -> None:
        job = _job(failure_alert=False)
        assert resolve_failure_alert(job, None) is None

    def test_per_job_config(self) -> None:
        cfg = FailureAlertConfig(enabled=True, after=2, cooldown_seconds=60)
        job = _job(failure_alert=cfg)
        result = resolve_failure_alert(job, None)
        assert result is not None
        assert result.after == 2

    def test_global_fallback(self) -> None:
        global_cfg = FailureAlertConfig(enabled=True, after=3, cooldown_seconds=120)
        job = _job()
        result = resolve_failure_alert(job, global_cfg)
        assert result is not None
        assert result.after == 3

    def test_should_send_below_threshold(self) -> None:
        cfg = FailureAlertConfig(enabled=True, after=3, cooldown_seconds=60)
        job = _job(consecutive_failures=2)
        assert should_send_failure_alert(job, cfg, _NOW) is False

    def test_should_send_above_threshold(self) -> None:
        cfg = FailureAlertConfig(enabled=True, after=3, cooldown_seconds=60)
        job = _job(consecutive_failures=3)
        assert should_send_failure_alert(job, cfg, _NOW) is True

    def test_cooldown_prevents_send(self) -> None:
        cfg = FailureAlertConfig(enabled=True, after=1, cooldown_seconds=300)
        job = _job(
            consecutive_failures=5,
            last_failure_alert_at=_NOW - timedelta(seconds=60),
        )
        assert should_send_failure_alert(job, cfg, _NOW) is False


class TestErrorClassification:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("rate_limit exceeded", "rate_limit"),
            ("429 Too Many Requests", "rate_limit"),
            ("server overloaded", "overloaded"),
            ("connection refused", "network"),
            ("request timed out", "timeout"),
            ("500 Internal Server Error", "server_error"),
        ],
    )
    def test_transient_patterns(self, text: str, expected: str) -> None:
        result = classify_transient_error(text)
        assert result is not None
        assert result.value == expected

    def test_permanent_error(self) -> None:
        assert classify_transient_error("invalid syntax") is None


class TestErrorBackoff:
    def test_first_error(self) -> None:
        assert error_backoff_ms(1) == BACKOFF_SCHEDULE_MS[0]

    def test_max_cap(self) -> None:
        assert error_backoff_ms(100) == BACKOFF_SCHEDULE_MS[-1]

    def test_zero_errors(self) -> None:
        assert error_backoff_ms(0) == BACKOFF_SCHEDULE_MS[0]


class TestExtractTelemetry:
    def test_with_usage(self) -> None:
        result = JobResult(
            success=True,
            output="ok",
            metadata={
                "model": "gpt-4",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )
        model, p, c, t = extract_telemetry(result)
        assert model == "gpt-4"
        assert p == 10
        assert c == 20
        assert t == 30

    def test_no_metadata(self) -> None:
        result = JobResult(success=True, output="ok")
        assert extract_telemetry(result) == (None, None, None, None)

    def test_no_usage(self) -> None:
        result = JobResult(success=True, output="ok", metadata={"model": "gpt-4"})
        model, p, _c, _t = extract_telemetry(result)
        assert model == "gpt-4"
        assert p is None
