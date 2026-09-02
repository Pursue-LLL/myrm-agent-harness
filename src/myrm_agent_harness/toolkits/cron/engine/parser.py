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
- parse_natural_interval: Parse natural language interval (e.g. '10m', '1h', 'every 30s') into milliseconds.
- parse_loop_command_input: Parse full `/loop` slash command arguments into (interval_ms, prompt).

[POS]
Cron expression parsing and next-run calculation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter

from myrm_agent_harness.toolkits.cron.types import Schedule, ScheduleKind


def compute_prev_run(
    schedule: Schedule, reference: datetime | None = None
) -> datetime | None:
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


def compute_next_run(
    schedule: Schedule, reference: datetime | None = None
) -> datetime | None:
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
# Natural language interval parsing
# ---------------------------------------------------------------------------

_DEFAULT_LOOP_INTERVAL_MS = 600_000  # 10m
_MIN_LOOP_INTERVAL_MS = 60_000  # 1m


def parse_natural_interval(
    text: str, default_ms: int = _DEFAULT_LOOP_INTERVAL_MS
) -> int:
    """Parse natural language duration string into milliseconds.

    Supports:
    - Short formats: ``10m``, ``1h``, ``30s``, ``2d``, ``10min``, ``2hours``
    - Prefix formats: ``every 10m``, ``every 2 hours``, ``every 30 seconds``
    - Integer only (defaults to minutes): ``10`` -> 10 minutes

    Enforces minimum granularity of 1 minute (60,000ms), rounding smaller values up.
    Returns ``default_ms`` if parsing fails.
    """
    import re

    cleaned = text.strip().lower()
    if not cleaned:
        return default_ms

    cleaned = re.sub(r"^(?:every|each)\s+", "", cleaned).strip()

    pattern = r"^(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)?$"
    match = re.match(pattern, cleaned)
    if not match:
        return default_ms

    val = int(match.group(1))
    unit = match.group(2) or "m"

    if unit.startswith("s"):
        ms = val * 1_000
    elif unit.startswith("m"):
        ms = val * 60_000
    elif unit.startswith("h"):
        ms = val * 3_600_000
    elif unit.startswith("d"):
        ms = val * 86_400_000
    else:
        ms = val * 60_000

    return max(ms, _MIN_LOOP_INTERVAL_MS)


def parse_loop_command_input(raw_input: str) -> tuple[int, str]:
    """Parse a `/loop` command input string into (interval_ms, prompt).

    Supports:
    - Prefix interval: ``/loop 5m 检查构建状态`` -> (300000, "检查构建状态")
    - Prefix with 'every': ``/loop every 20m review pr`` -> (1200000, "review pr")
    - Suffix interval: ``/loop check deploy every 2 hours`` -> (7200000, "check deploy")
    - No interval (defaults to 10m): ``/loop 帮我盯竞品动态`` -> (600000, "帮我盯竞品动态")
    - Empty prompt: ``/loop`` -> (600000, "")
    """
    import re

    args = re.sub(r"^/loop\s*", "", raw_input.strip(), flags=re.IGNORECASE).strip()
    if not args:
        return (_DEFAULT_LOOP_INTERVAL_MS, "")

    # 1. Try prefix interval: e.g. "5m do something" or "every 2 hours do something"
    prefix_match = re.match(
        r"^(?:every\s+)?(\d+\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days))\s+(.+)$",
        args,
        re.IGNORECASE,
    )
    if prefix_match:
        interval_str = prefix_match.group(1)
        prompt = prefix_match.group(2).strip()
        return (parse_natural_interval(interval_str), prompt)

    # 2. Try prefix pure digits: e.g. "10 check something"
    prefix_digit_match = re.match(r"^(\d+)\s+(.+)$", args)
    if prefix_digit_match:
        val = int(prefix_digit_match.group(1))
        # If val is reasonable interval (1-1440 minutes), treat as interval
        if 1 <= val <= 1440:
            return (val * 60_000, prefix_digit_match.group(2).strip())

    # 3. Try suffix interval: e.g. "check something every 2 hours" or "check something every 10m"
    suffix_match = re.search(
        r"\s+every\s+(\d+\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days))\s*$",
        args,
        re.IGNORECASE,
    )
    if suffix_match:
        interval_str = suffix_match.group(1)
        prompt = args[: suffix_match.start()].strip()
        return (parse_natural_interval(interval_str), prompt)

    # 4. Fallback: treat whole text as prompt with default interval
    return (_DEFAULT_LOOP_INTERVAL_MS, args)


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
