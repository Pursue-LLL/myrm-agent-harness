"""Tests for cron three-phase startup recovery helpers.

Covers ``is_stale_run``, ``is_in_error_backoff``, and ``compute_prev_run``
— all pure functions with no I/O.
"""

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.cron.engine.helpers import (
    is_in_error_backoff,
    is_stale_run,
)
from myrm_agent_harness.toolkits.cron.engine.parser import compute_prev_run
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    JobType,
    RunStatus,
    Schedule,
    ScheduleKind,
)


def _make_job(
    *,
    next_run_at: datetime | None = None,
    last_run_at: datetime | None = None,
    last_status: RunStatus | None = None,
    consecutive_failures: int = 0,
    timeout_seconds: int = 300,
    retry_backoff_ms: int = 30_000,
    schedule: Schedule | None = None,
) -> CronJob:
    return CronJob(
        id="test-job",
        user_id="u1",
        name="Test Job",
        job_type=JobType.AGENT,
        schedule=schedule or Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *"),
        next_run_at=next_run_at,
        last_run_at=last_run_at,
        last_status=last_status,
        consecutive_failures=consecutive_failures,
        timeout_seconds=timeout_seconds,
        retry_backoff_ms=retry_backoff_ms,
    )


# ── is_stale_run ─────────────────────────────────────────────────────


class TestIsStaleRun:
    def test_stale_when_past_timeout_plus_margin(self) -> None:
        now = datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
        job = _make_job(
            next_run_at=None,
            last_run_at=datetime(2025, 1, 1, 9, 0, tzinfo=UTC),
            timeout_seconds=300,
        )
        assert is_stale_run(job, now) is True

    def test_not_stale_when_within_timeout(self) -> None:
        now = datetime(2025, 1, 1, 9, 4, tzinfo=UTC)
        job = _make_job(
            next_run_at=None,
            last_run_at=datetime(2025, 1, 1, 9, 0, tzinfo=UTC),
            timeout_seconds=300,
        )
        assert is_stale_run(job, now) is False

    def test_not_stale_when_next_run_set(self) -> None:
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        job = _make_job(
            next_run_at=datetime(2025, 1, 1, 13, 0, tzinfo=UTC),
            last_run_at=datetime(2025, 1, 1, 9, 0, tzinfo=UTC),
        )
        assert is_stale_run(job, now) is False

    def test_not_stale_when_never_run(self) -> None:
        now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        job = _make_job(next_run_at=None, last_run_at=None)
        assert is_stale_run(job, now) is False

    def test_handles_naive_last_run_at(self) -> None:
        now = datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
        job = _make_job(
            next_run_at=None,
            last_run_at=datetime(2025, 1, 1, 9, 0),  # naive
            timeout_seconds=300,
        )
        assert is_stale_run(job, now) is True


# ── is_in_error_backoff ──────────────────────────────────────────────


class TestIsInErrorBackoff:
    def test_in_backoff(self) -> None:
        now = datetime(2025, 1, 1, 9, 0, 10, tzinfo=UTC)
        job = _make_job(
            last_status=RunStatus.ERROR,
            last_run_at=datetime(2025, 1, 1, 9, 0, tzinfo=UTC),
            consecutive_failures=1,
            retry_backoff_ms=30_000,
        )
        assert is_in_error_backoff(job, now) is True

    def test_backoff_expired(self) -> None:
        now = datetime(2025, 1, 1, 9, 1, tzinfo=UTC)
        job = _make_job(
            last_status=RunStatus.ERROR,
            last_run_at=datetime(2025, 1, 1, 9, 0, tzinfo=UTC),
            consecutive_failures=1,
            retry_backoff_ms=30_000,
        )
        assert is_in_error_backoff(job, now) is False

    def test_not_in_backoff_when_ok(self) -> None:
        now = datetime(2025, 1, 1, 9, 0, 10, tzinfo=UTC)
        job = _make_job(
            last_status=RunStatus.OK,
            last_run_at=datetime(2025, 1, 1, 9, 0, tzinfo=UTC),
        )
        assert is_in_error_backoff(job, now) is False

    def test_not_in_backoff_when_no_last_run(self) -> None:
        now = datetime(2025, 1, 1, 9, 0, tzinfo=UTC)
        job = _make_job(last_status=RunStatus.ERROR, last_run_at=None)
        assert is_in_error_backoff(job, now) is False

    def test_exponential_backoff_grows(self) -> None:
        base = datetime(2025, 1, 1, 9, 0, tzinfo=UTC)
        job = _make_job(
            last_status=RunStatus.ERROR,
            last_run_at=base,
            consecutive_failures=3,
            retry_backoff_ms=30_000,
        )
        # 30s * 2^(3-1) = 120s
        at_90s = base + timedelta(seconds=90)
        assert is_in_error_backoff(job, at_90s) is True
        at_130s = base + timedelta(seconds=130)
        assert is_in_error_backoff(job, at_130s) is False


# ── compute_prev_run ─────────────────────────────────────────────────


class TestComputePrevRun:
    def test_cron_prev_slot(self) -> None:
        schedule = Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *")
        ref = datetime(2025, 1, 15, 10, 30, tzinfo=UTC)
        prev = compute_prev_run(schedule, ref)
        assert prev is not None
        assert prev.hour == 9
        assert prev.day == 15

    def test_cron_prev_slot_before_todays_fire(self) -> None:
        schedule = Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *")
        ref = datetime(2025, 1, 15, 8, 0, tzinfo=UTC)
        prev = compute_prev_run(schedule, ref)
        assert prev is not None
        assert prev.day == 14
        assert prev.hour == 9

    def test_interval_returns_none(self) -> None:
        schedule = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600_000)
        prev = compute_prev_run(schedule, datetime(2025, 1, 1, tzinfo=UTC))
        assert prev is None

    def test_once_returns_none(self) -> None:
        schedule = Schedule(
            kind=ScheduleKind.ONCE,
            run_at=datetime(2025, 1, 1, 9, 0, tzinfo=UTC),
        )
        prev = compute_prev_run(schedule, datetime(2025, 1, 1, 10, 0, tzinfo=UTC))
        assert prev is None

    def test_cron_with_timezone(self) -> None:
        schedule = Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *", tz="Asia/Shanghai")
        ref = datetime(2025, 1, 15, 3, 0, tzinfo=UTC)  # 11:00 Shanghai
        prev = compute_prev_run(schedule, ref)
        assert prev is not None
        assert prev.astimezone(UTC).hour == 1  # 9:00 Shanghai = 01:00 UTC

    @pytest.mark.parametrize(
        "expr",
        ["*/15 * * * *", "0 */2 * * *", "30 8 * * 1-5"],
    )
    def test_various_cron_expressions(self, expr: str) -> None:
        schedule = Schedule(kind=ScheduleKind.CRON, expr=expr)
        ref = datetime(2025, 6, 15, 12, 0, tzinfo=UTC)
        prev = compute_prev_run(schedule, ref)
        assert prev is not None
        assert prev < ref
