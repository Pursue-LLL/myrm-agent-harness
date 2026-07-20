"""Cron job domain types.

Pure data definitions — no I/O, safe to import anywhere.
Consumed by scheduler, manager, tools, and application adapters.

[INPUT]
- infra.incremental.types::MonitorConfig (POS: Domain types for incremental monitoring.)

[OUTPUT]
- ScheduleKind: Classifies transient errors for smart retry decisions.
- JobType: class — Job Type
- JobStatus: class — Job Status
- RunStatus: class — Run Status
- TransientErrorKind: class — Transient Error Kind

[POS]
Cron job domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from myrm_agent_harness.infra.incremental.types import MonitorConfig
    from myrm_agent_harness.toolkits.cron.triggers import TriggerConfig


class ScheduleKind(StrEnum):
    CRON = "cron"
    INTERVAL = "interval"
    ONCE = "once"


class JobType(StrEnum):
    AGENT = "agent"
    SHELL = "shell"
    ROUTER = "router"
    REMINDER = "reminder"


class JobStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class RunStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    SKIPPED = "skipped"


class TransientErrorKind(StrEnum):
    """Classifies transient errors for smart retry decisions."""

    RATE_LIMIT = "rate_limit"
    OVERLOADED = "overloaded"
    NETWORK = "network"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"


class SessionTarget(StrEnum):
    """Controls whether a cron job runs in an isolated or shared session.

    - ``ISOLATED``: each execution starts with a blank context.
    - ``MAIN``: reuses the bound web-chat session's history.
    - ``DAILY``: same-day executions share context via injected history;
      a fresh context is started each calendar day.
    """

    ISOLATED = "isolated"
    MAIN = "main"
    DAILY = "daily"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActiveHours:
    """Optional window restricting when a job may execute.

    Times are in ``HH:MM`` 24-hour format.  Cross-midnight ranges
    (e.g. ``start="22:00", end="06:00"``) are supported.
    ``tz`` is an IANA timezone name (defaults to UTC).
    """

    start: str  # "09:00"
    end: str  # "18:00"
    tz: str = "UTC"


@dataclass(frozen=True, slots=True)
class DeliveryConfig:
    """How to deliver task execution results.

    ``channel`` is a plain string — the application layer defines valid values
    (e.g. "chat", "webhook", "feishu").  ``target`` carries an address when
    the channel requires one (webhook URL, phone number, etc.).

    ``secret`` is auto-generated for webhook channels, used as HMAC key.
    """

    channel: str = "chat"
    target: str | None = None
    secret: str | None = None


@dataclass(frozen=True, slots=True)
class FailureAlertConfig:
    """Per-job or global failure alerting configuration.

    When used as a global default, ``enabled`` controls the master switch.
    Per-job configs on ``CronJob.failure_alert`` ignore ``enabled`` (use
    ``Literal[False]`` to explicitly disable for a single job).
    """

    enabled: bool = True
    after: int = 3
    cooldown_seconds: int = 300
    delivery: DeliveryConfig | None = None


@dataclass(frozen=True, slots=True)
class CronConfig:
    """Global scheduler configuration.

    Single configuration object for ``CronScheduler`` and ``JobExecutor``.
    All fields have sensible defaults — zero-config is valid.
    """

    max_concurrent: int = 5
    max_per_user: int = 3
    failure_delivery: DeliveryConfig | None = None
    failure_alert: FailureAlertConfig | None = None

    def __post_init__(self) -> None:
        if self.max_concurrent > 100:
            raise ValueError("max_concurrent must be <= 100 to prevent resource exhaustion")
        if self.max_per_user > 100:
            raise ValueError("max_per_user must be <= 100 to prevent resource exhaustion")


@dataclass(frozen=True, slots=True)
class Schedule:
    """Immutable schedule definition.

    ``stagger_ms`` adds a random delay in [0, stagger_ms) before each
    execution, preventing thundering-herd when many jobs share the same
    cron expression (e.g. ``0 * * * *``).  ``None`` means "use smart
    default" (auto-set for top-of-hour cron); ``0`` means exact timing.
    """

    kind: ScheduleKind
    expr: str | None = None
    tz: str | None = None
    interval_ms: int | None = None
    run_at: datetime | None = None
    stagger_ms: int | None = None

    def __post_init__(self) -> None:
        if self.kind == ScheduleKind.CRON and not self.expr:
            raise ValueError("cron schedule requires 'expr'")
        if self.kind == ScheduleKind.INTERVAL and (not self.interval_ms or self.interval_ms < 100):
            raise ValueError("interval_ms must be >= 100 to prevent CPU storms")
        if self.kind == ScheduleKind.ONCE and not self.run_at:
            raise ValueError("once schedule requires 'run_at'")
        if self.tz and self.kind != ScheduleKind.CRON:
            raise ValueError("'tz' only applies to cron schedules")
        if self.stagger_ms is not None and self.stagger_ms < 0:
            object.__setattr__(self, "stagger_ms", 0)


@dataclass(slots=True)
class CronJob:
    """In-memory representation of a cron job."""

    id: str
    user_id: str
    name: str
    job_type: JobType
    schedule: Schedule
    status: JobStatus = JobStatus.ACTIVE

    prompt: str | None = None
    model: str | None = None
    chat_id: str | None = None
    agent_id: str | None = None

    command: str | None = None

    context_from: tuple[str, ...] = ()

    required_capabilities: tuple[str, ...] = ()
    allowed_roots: tuple[str, ...] = ()
    tools_allowed: tuple[str, ...] | None = None

    max_retries: int = 2
    retry_backoff_ms: int = 30_000
    timeout_seconds: int = 300
    misfire_grace_seconds: int = 300
    cooldown_seconds: int = 0
    max_fires: int | None = None
    expires_at: datetime | None = None
    fire_count: int = 0
    session_target: SessionTarget = SessionTarget.ISOLATED

    delivery: DeliveryConfig = field(default_factory=DeliveryConfig)
    failure_delivery: DeliveryConfig | None = None
    failure_alert: FailureAlertConfig | Literal[False] | None = None
    active_hours: ActiveHours | None = None
    delete_after_run: bool = False
    run_retention_days: int = 30
    deduplicate: bool = False
    skip_if_active: bool = False
    last_output_hash: str | None = None
    monitor_config: MonitorConfig | None = None
    triggers: TriggerConfig | None = None
    pre_condition_script: str | None = None

    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_status: RunStatus | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    last_failure_alert_at: datetime | None = None

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.timeout_seconds < 10:
            raise ValueError("timeout_seconds must be >= 10 to prevent alert storms")
        if self.retry_backoff_ms < 100:
            raise ValueError("retry_backoff_ms must be >= 100 to prevent service overload")
        if self.max_retries > 10:
            raise ValueError("max_retries must be <= 10 to prevent resource waste")
        if self.max_fires is not None and self.max_fires < 1:
            raise ValueError("max_fires must be >= 1")


@dataclass(frozen=True, slots=True)
class CronJobPatch:
    """Partial update descriptor — only non-None fields are applied."""

    name: str | None = None
    status: JobStatus | None = None
    schedule: Schedule | None = None
    prompt: str | None = None
    model: str | None = None
    agent_id: str | None = None
    command: str | None = None

    context_from: tuple[str, ...] | None = None
    clear_context_from: bool = False
    pre_condition_script: str | None = None
    clear_pre_condition_script: bool = False

    required_capabilities: tuple[str, ...] | None = None
    allowed_roots: tuple[str, ...] | None = None
    tools_allowed: tuple[str, ...] | None = None
    clear_tools_allowed: bool = False
    delivery: DeliveryConfig | None = None
    failure_delivery: DeliveryConfig | None = None
    clear_failure_delivery: bool = False
    failure_alert: FailureAlertConfig | Literal[False] | None = None
    clear_failure_alert: bool = False
    active_hours: ActiveHours | None = None
    clear_active_hours: bool = False
    max_retries: int | None = None
    retry_backoff_ms: int | None = None
    timeout_seconds: int | None = None
    misfire_grace_seconds: int | None = None
    cooldown_seconds: int | None = None
    max_fires: int | None = None
    clear_max_fires: bool = False
    expires_at: datetime | None = None
    clear_expires_at: bool = False
    session_target: SessionTarget | None = None
    chat_id: str | None = None
    clear_chat_id: bool = False
    delete_after_run: bool | None = None
    run_retention_days: int | None = None
    deduplicate: bool | None = None
    skip_if_active: bool | None = None
    monitor_config: MonitorConfig | None = None
    clear_monitor_config: bool = False
    triggers: TriggerConfig | None = None
    clear_triggers: bool = False


class DeliveryStatus(StrEnum):
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class CronRunRecord:
    """Immutable record of a single job execution.

    ``metadata`` carries structured data collected during execution
    (e.g. securityAudit, progressSteps, sources).

    ``integrity_hash`` and ``prev_hash`` form a per-job Merkle chain
    that detects tampering of historical run records.
    """

    id: str
    job_id: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    status: RunStatus
    output: str | None = None
    error: str | None = None
    model: str | None = None
    usage_input_tokens: int | None = None
    usage_output_tokens: int | None = None
    usage_total_tokens: int | None = None
    trigger_source: str | None = None
    delivery_status: DeliveryStatus | None = None
    delivery_error: str | None = None
    metadata: dict[str, object] | None = None
    integrity_hash: str = ""
    prev_hash: str = ""


@dataclass(frozen=True, slots=True)
class JobResult:
    """Return value from a job runner.

    ``metadata`` carries structured data collected during execution
    (e.g. progressSteps, sources) for delivery alongside the text output.

    ``exit_code`` follows Unix conventions:
    - 0: success, no new content (skip delivery)
    - 1: success, new content found (trigger delivery)
    - 2+: error (trigger failure delivery)

    ``incremental_delta`` contains only the new/changed content when
    incremental monitoring is enabled. Empty string means no changes.

    When ``skipped`` is True, the runner determined that execution
    should be bypassed (e.g. no actionable content for heartbeat).
    The executor records this as ``RunStatus.SKIPPED`` without
    running delivery or incrementing failure counters.
    """

    success: bool
    output: str = ""
    error: str | None = None
    metadata: dict[str, object] | None = None
    exit_code: int = 0
    incremental_delta: str = ""
    skipped: bool = False
    skip_reason: str | None = None


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def dict_to_active_hours(d: dict[str, str] | None) -> ActiveHours | None:
    """Convert a JSON dict to ``ActiveHours``, or None if missing/empty."""
    if not d:
        return None
    start = d.get("start", "")
    end = d.get("end", "")
    if not start or not end:
        return None
    return ActiveHours(start=start, end=end, tz=d.get("tz", "UTC"))


def active_hours_to_dict(ah: ActiveHours | None) -> dict[str, str] | None:
    """Serialise ``ActiveHours`` to a JSON-safe dict."""
    if ah is None:
        return None
    return {"start": ah.start, "end": ah.end, "tz": ah.tz}


def dict_to_delivery(d: dict[str, str | None] | None) -> DeliveryConfig | None:
    """Convert a JSON dict to ``DeliveryConfig``, or None if missing/empty."""
    if not d:
        return None
    return DeliveryConfig(
        channel=str(d.get("channel", "chat")),
        target=d.get("target"),
        secret=d.get("secret"),
    )


def delivery_to_dict(dc: DeliveryConfig | None) -> dict[str, str | None] | None:
    """Serialise ``DeliveryConfig`` to a JSON-safe dict, or None."""
    if dc is None:
        return None
    d: dict[str, str | None] = {"channel": dc.channel, "target": dc.target}
    if dc.secret:
        d["secret"] = dc.secret
    return d


def dict_to_failure_alert(
    d: dict[str, object] | bool | None,
) -> FailureAlertConfig | Literal[False] | None:
    """Convert a JSON value to ``FailureAlertConfig``, ``False``, or ``None``."""
    if d is None:
        return None
    if d is False:
        return False
    if not isinstance(d, dict):
        return None
    return FailureAlertConfig(
        enabled=bool(d.get("enabled", True)),
        after=int(d.get("after", 3)),  # type: ignore[arg-type]
        cooldown_seconds=int(d.get("cooldown_seconds", 300)),  # type: ignore[arg-type]
        delivery=dict_to_delivery(d.get("delivery")),  # type: ignore[arg-type]
    )


def failure_alert_to_dict(
    fa: FailureAlertConfig | Literal[False] | None,
) -> dict[str, object] | Literal[False] | None:
    """Serialise ``FailureAlertConfig`` to a JSON-safe value."""
    if fa is None:
        return None
    if fa is False:
        return False
    d: dict[str, object] = {
        "enabled": fa.enabled,
        "after": fa.after,
        "cooldown_seconds": fa.cooldown_seconds,
    }
    if fa.delivery:
        d["delivery"] = delivery_to_dict(fa.delivery)
    return d


def dict_to_schedule(d: dict[str, str | int | None]) -> Schedule:
    """Convert a JSON-serialised schedule dict to a ``Schedule`` domain object."""
    run_at = None
    raw_run_at = d.get("run_at")
    if raw_run_at and isinstance(raw_run_at, str):
        run_at = datetime.fromisoformat(raw_run_at)
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=UTC)

    raw_stagger = d.get("stagger_ms")
    stagger_ms = int(raw_stagger) if raw_stagger is not None else None

    return Schedule(
        kind=ScheduleKind(str(d["kind"])),
        expr=str(d["expr"]) if d.get("expr") else None,
        tz=str(d["tz"]) if d.get("tz") else None,
        interval_ms=int(d["interval_ms"]) if d.get("interval_ms") else None,
        run_at=run_at,
        stagger_ms=stagger_ms,
    )


def schedule_to_dict(s: Schedule) -> dict[str, str | int]:
    """Serialise a ``Schedule`` to a JSON-safe dict."""
    d: dict[str, str | int] = {"kind": s.kind}
    if s.expr:
        d["expr"] = s.expr
    if s.tz:
        d["tz"] = s.tz
    if s.interval_ms:
        d["interval_ms"] = s.interval_ms
    if s.run_at:
        d["run_at"] = s.run_at.isoformat()
    if s.stagger_ms is not None:
        d["stagger_ms"] = s.stagger_ms
    return d
