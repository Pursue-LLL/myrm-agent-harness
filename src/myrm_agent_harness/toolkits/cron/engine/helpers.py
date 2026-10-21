"""[INPUT]
- toolkits.cron.types::ActiveHours, CronJob, FailureAlertConfig (POS: Cron job domain types.)

[OUTPUT]
- resolve_stagger_ms: function — resolve_stagger_ms
- is_top_of_hour_cron: Return True if *expression* fires at minute-0 every hour.
- compute_stagger_offset_s: Return the stagger upper-bound in seconds for a given sch...
- is_within_active_hours: Return True if *now* falls within the active window, or i...
- is_stale_run: Detect a zombie task whose execution was interrupted by a...

[POS]
Provides resolve_stagger_ms, is_top_of_hour_cron, compute_stagger_offset_s.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from myrm_agent_harness.toolkits.cron.types import FailureAlertConfig

"""Scheduling, alert, and error helpers for the cron engine.

All public functions are pure (no I/O) and safe to call from any context.
"""


if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.cron.types import (
        ActiveHours,
        CronJob,
        FailureAlertConfig,
        JobResult,
        TransientErrorKind,
    )

_DEFAULT_TOP_OF_HOUR_STAGGER_MS = 5 * 60 * 1000
_STALE_MARGIN_S = 60

# ---------------------------------------------------------------------------
# UTC normalisation
# ---------------------------------------------------------------------------


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# ---------------------------------------------------------------------------
# Stagger
# ---------------------------------------------------------------------------


def resolve_stagger_ms(job: CronJob) -> int:
    """Compute the effective stagger delay for a job.

    Explicit ``stagger_ms=0`` means exact timing (no delay).
    ``stagger_ms=None`` triggers smart defaults: cron expressions that
    fire at minute-0 (e.g. ``0 * * * *``, ``0 9 * * *``) get a 5-minute
    random window to avoid thundering-herd in multi-user Sandbox scenarios.
    """
    from myrm_agent_harness.toolkits.cron.types import ScheduleKind

    sched = job.schedule
    if sched.stagger_ms is not None:
        return max(0, sched.stagger_ms)

    if sched.kind != ScheduleKind.CRON or not sched.expr:
        return 0

    minute_field = sched.expr.strip().split()[0] if sched.expr.strip() else ""
    if minute_field == "0":
        return _DEFAULT_TOP_OF_HOUR_STAGGER_MS
    return 0


def is_top_of_hour_cron(expression: str) -> bool:
    """Return True if *expression* fires at minute-0 every hour.

    Matches patterns like ``0 * * * *`` or ``0 9 * * *`` where the minute
    field is exactly ``0`` and the hour field contains ``*``.
    """
    parts = expression.strip().split()
    if len(parts) < 5:
        return False
    return parts[0] == "0" and "*" in parts[1]


def compute_stagger_offset_s(schedule_stagger_ms: int | None, expr: str | None) -> float:
    """Return the stagger upper-bound in seconds for a given schedule.

    - Explicit ``stagger_ms > 0`` -> use that value.
    - ``stagger_ms is None`` + top-of-hour cron -> 5-minute default.
    - Otherwise -> 0 (exact timing).
    """
    if schedule_stagger_ms is not None:
        return max(0, schedule_stagger_ms) / 1000.0
    if expr and is_top_of_hour_cron(expr):
        return _DEFAULT_TOP_OF_HOUR_STAGGER_MS / 1000.0
    return 0.0


# ---------------------------------------------------------------------------
# Active hours
# ---------------------------------------------------------------------------


def is_within_active_hours(ah: ActiveHours | None, *, now: datetime | None = None) -> bool:
    """Return True if *now* falls within the active window, or if no window is set."""
    if ah is None:
        return True

    try:
        start_h, start_m = (int(x) for x in ah.start.split(":"))
        end_h, end_m = (int(x) for x in ah.end.split(":"))
    except (ValueError, AttributeError):
        return True

    start_min = start_h * 60 + start_m
    end_min = end_h * 60 + end_m

    if now is None:
        now = datetime.now(UTC)

    try:
        tz = ZoneInfo(ah.tz) if ah.tz else UTC
        local_now = now.astimezone(tz)
    except KeyError:
        local_now = now

    current_min = local_now.hour * 60 + local_now.minute

    if end_min > start_min:
        return start_min <= current_min < end_min
    # Cross-midnight: e.g. 22:00 -> 06:00
    return current_min >= start_min or current_min < end_min


# ---------------------------------------------------------------------------
# Pre-execution checks & state detection
# ---------------------------------------------------------------------------


def is_stale_run(job: CronJob, now: datetime) -> bool:
    """Detect a zombie task whose execution was interrupted by an unclean shutdown.

    A run is stale when the job is ACTIVE with no next_run_at (claimed for
    execution) and enough time has elapsed for the timeout + safety margin.
    """
    if job.next_run_at is not None or job.last_run_at is None:
        return False
    deadline = _ensure_utc(job.last_run_at) + timedelta(
        seconds=job.timeout_seconds + _STALE_MARGIN_S,
    )
    return now > deadline


def is_past_misfire_grace(job: CronJob, now: datetime) -> bool:
    """Return True if the job has missed its fire window beyond the grace period."""
    if job.next_run_at is None:
        return False
    grace = timedelta(seconds=job.misfire_grace_seconds)
    return (now - _ensure_utc(job.next_run_at)) > grace


def is_in_error_backoff(job: CronJob, now: datetime) -> bool:
    """Return True if the job is within an exponential-backoff window after failure.

    Used during startup recovery to avoid immediately retrying a failed task
    whose backoff period has not yet elapsed.
    """
    from myrm_agent_harness.toolkits.cron.types import RunStatus

    _max_backoff_ms = 3_600_000
    if job.last_status != RunStatus.ERROR or job.last_run_at is None:
        return False
    failures = max(job.consecutive_failures, 1)
    backoff_ms = min(job.retry_backoff_ms * (2 ** (failures - 1)), _max_backoff_ms)
    backoff_end = _ensure_utc(job.last_run_at) + timedelta(milliseconds=backoff_ms)
    return now < backoff_end


def pre_execution_check(job: CronJob, now: datetime) -> str | None:
    """Run pre-execution guards. Returns skip reason or None if runnable.

    Checks (in order): expiry -> max_fires -> cooldown.
    Side-effect: sets ``job.status = PAUSED`` for expiry / max_fires.
    """
    from myrm_agent_harness.toolkits.cron.types import JobStatus

    if job.expires_at and now >= _ensure_utc(job.expires_at):
        job.status = JobStatus.PAUSED
        return "expired"
    if job.max_fires is not None and job.fire_count >= job.max_fires:
        job.status = JobStatus.PAUSED
        return "max_fires_reached"
    if job.cooldown_seconds > 0 and job.last_run_at:
        elapsed = (now - _ensure_utc(job.last_run_at)).total_seconds()
        if elapsed < job.cooldown_seconds:
            return "cooldown_active"
    return None


# ---------------------------------------------------------------------------
# Failure alert resolution
# ---------------------------------------------------------------------------


def resolve_failure_alert(
    job: CronJob,
    global_config: FailureAlertConfig | None,
) -> FailureAlertConfig | None:
    """Merge per-job and global failure alert configs.

    Resolution order:
    1. ``job.failure_alert is False`` -> disabled, return None
    2. ``job.failure_alert`` is a config -> use it (fill missing from global)
    3. Fall back to ``global_config`` if enabled
    """

    job_cfg = job.failure_alert
    if job_cfg is False:
        return None
    if job_cfg is not None and not isinstance(job_cfg, bool):
        return FailureAlertConfig(
            enabled=True,
            after=job_cfg.after,
            cooldown_seconds=job_cfg.cooldown_seconds,
            delivery=job_cfg.delivery or (job.delivery if job.delivery.channel != "none" else None),
        )
    if global_config and global_config.enabled:
        return global_config
    return None


def should_send_failure_alert(
    job: CronJob,
    alert_config: FailureAlertConfig,
    now: datetime,
) -> bool:
    """Determine whether a failure alert should fire right now."""
    if job.consecutive_failures < alert_config.after:
        return False
    if job.last_failure_alert_at:
        elapsed = (now - _ensure_utc(job.last_failure_alert_at)).total_seconds()
        if elapsed < alert_config.cooldown_seconds:
            return False
    return True


# ---------------------------------------------------------------------------
# Error classification, backoff, telemetry
# ---------------------------------------------------------------------------

BACKOFF_SCHEDULE_MS: tuple[int, ...] = (
    30_000,
    60_000,
    300_000,
    900_000,
    3_600_000,
)

_TRANSIENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "rate_limit": ("rate_limit", "rate limit", "429", "too many requests"),
    "overloaded": ("overloaded", "capacity", "resource_exhausted"),
    "network": ("network", "connection", "dns", "unreachable"),
    "timeout": ("timeout", "timed out", "deadline"),
    "server_error": ("500", "502", "503", "internal server"),
}


def classify_transient_error(error_text: str) -> TransientErrorKind | None:
    """Identify whether an error is transient (worth retrying) or permanent.

    Returns the ``TransientErrorKind`` if a known transient pattern is found
    in *error_text*, or ``None`` for permanent / unrecognised errors.
    """
    from myrm_agent_harness.toolkits.cron.types import TransientErrorKind

    lower = error_text.lower()
    for kind_value, patterns in _TRANSIENT_PATTERNS.items():
        if any(p in lower for p in patterns):
            return TransientErrorKind(kind_value)
    return None


def error_backoff_ms(consecutive_errors: int) -> int:
    """Look up the backoff delay (ms) for the given error count.

    Uses a 5-level schedule: 30s -> 1m -> 5m -> 15m -> 60m (capped).
    """
    idx = min(max(consecutive_errors - 1, 0), len(BACKOFF_SCHEDULE_MS) - 1)
    return BACKOFF_SCHEDULE_MS[idx]


def _safe_int(val: object) -> int | None:
    """Coerce a value to int if numeric, else None."""
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    return None


def extract_telemetry(
    result: JobResult,
) -> tuple[str | None, int | None, int | None, int | None]:
    """Extract model name and token usage from JobResult metadata."""
    meta = result.metadata
    if not meta:
        return None, None, None, None

    model = str(meta["model"]) if "model" in meta else None

    usage = meta.get("usage")
    if isinstance(usage, dict):
        return (
            model,
            _safe_int(usage.get("prompt_tokens")),
            _safe_int(usage.get("completion_tokens")),
            _safe_int(usage.get("total_tokens")),
        )
    return model, None, None, None
