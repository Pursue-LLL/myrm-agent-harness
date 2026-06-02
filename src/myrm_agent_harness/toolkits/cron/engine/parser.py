"""Cron expression parsing and next-run calculation.

Wraps ``croniter`` for cron expressions, provides simple arithmetic for
interval and one-shot schedules.  Pure functions — no I/O.

[INPUT]
- toolkits.cron.types::Schedule, (POS: Cron job domain types.)

[OUTPUT]
- compute_prev_run: Return the most recent fire time **before** *reference* (...
- compute_next_run: Return the next fire time **after** *reference* (defaults...
- validate_cron_expr: Return ``True`` when *expr* is a syntactically valid cron...
- validate_timezone: Return ``True`` when *tz_name* is a valid IANA timezone.
- describe_schedule: Human-readable summary of a schedule (for UI tooltips).

[POS]
Cron expression parsing and next-run calculation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter

from myrm_agent_harness.toolkits.cron.types import Schedule, ScheduleKind


def compute_prev_run(schedule: Schedule, reference: datetime | None = None) -> datetime | None:
    """Return the most recent fire time **before** *reference* (defaults to now UTC).

    Returns ``None`` for ONCE schedules or when no prior occurrence can be
    determined (e.g. an interval schedule with no anchor).
    """
    now = _ensure_aware(reference or datetime.now(UTC))

    if schedule.kind == ScheduleKind.CRON:
        return _prev_cron(schedule, now)

    if schedule.kind == ScheduleKind.INTERVAL:
        # Interval schedules have no fixed anchor in the domain model,
        # so we cannot compute a deterministic previous slot.
        return None

    return None


def compute_next_run(schedule: Schedule, reference: datetime | None = None) -> datetime | None:
    """Return the next fire time **after** *reference* (defaults to now UTC).

    Returns ``None`` when the schedule has no future occurrence (e.g. a
    one-shot whose time has passed).
    """
    now = _ensure_aware(reference or datetime.now(UTC))

    if schedule.kind == ScheduleKind.CRON:
        return _next_cron(schedule, now)

    if schedule.kind == ScheduleKind.INTERVAL:
        assert schedule.interval_ms
        return now + timedelta(milliseconds=schedule.interval_ms)

    if schedule.kind == ScheduleKind.ONCE:
        assert schedule.run_at
        run_at = _ensure_aware(schedule.run_at)
        return run_at if run_at > now else None

    return None


def validate_cron_expr(expr: str) -> bool:
    """Return ``True`` when *expr* is a syntactically valid cron expression."""
    try:
        croniter(expr)
        return True
    except (ValueError, KeyError):
        return False


def validate_timezone(tz_name: str) -> bool:
    """Return ``True`` when *tz_name* is a valid IANA timezone."""
    try:
        ZoneInfo(tz_name)
        return True
    except (KeyError, Exception):
        return False


def describe_schedule(schedule: Schedule) -> str:
    """Human-readable summary of a schedule (for UI tooltips)."""
    if schedule.kind == ScheduleKind.CRON:
        tz_part = f" ({schedule.tz})" if schedule.tz else ""
        return f"cron: {schedule.expr}{tz_part}"

    if schedule.kind == ScheduleKind.INTERVAL:
        assert schedule.interval_ms
        return _format_interval(schedule.interval_ms)

    if schedule.kind == ScheduleKind.ONCE:
        assert schedule.run_at
        return f"once at {schedule.run_at.isoformat()}"

    return "unknown"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_aware(dt: datetime) -> datetime:
    """Attach UTC tzinfo to naive datetimes, pass aware ones through."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _prev_cron(schedule: Schedule, now: datetime) -> datetime:
    assert schedule.expr
    tz = ZoneInfo(schedule.tz) if schedule.tz else UTC
    base = now.astimezone(tz)
    cron = croniter(schedule.expr, base)
    prev_dt: datetime = cron.get_prev(datetime)
    return prev_dt.astimezone(UTC)


def _next_cron(schedule: Schedule, now: datetime) -> datetime:
    assert schedule.expr
    tz = ZoneInfo(schedule.tz) if schedule.tz else UTC
    base = now.astimezone(tz)
    cron = croniter(schedule.expr, base)
    next_dt: datetime = cron.get_next(datetime)
    return next_dt.astimezone(UTC)


def _format_interval(ms: int) -> str:
    seconds = ms // 1000
    if seconds < 60:
        return f"every {seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"every {minutes}m"
    hours = minutes // 60
    if hours < 24:
        remaining_m = minutes % 60
        return f"every {hours}h{remaining_m}m" if remaining_m else f"every {hours}h"
    days = hours // 24
    return f"every {days}d"
