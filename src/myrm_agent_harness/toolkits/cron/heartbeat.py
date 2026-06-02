"""Heartbeat — convenience layer over CronManager for periodic agent self-checks.

Provides enable/disable/status semantics for a single well-known
cron job (name ``__heartbeat__``) per owner.  Supports both fixed-interval
and cron-based (time-of-day) scheduling.  All scheduling, retry,
delivery, and execution logic is delegated to the existing cron engine.

Usage (framework-only, no business coupling)::

    from myrm_agent_harness.toolkits.cron.heartbeat import enable_heartbeat
    from myrm_agent_harness.toolkits.cron.types import Schedule, ScheduleKind

    # Fixed interval (legacy)
    job = await enable_heartbeat(manager, owner_id)

    # Time-of-day (cron)
    job = await enable_heartbeat(
        manager, owner_id,
        schedule=Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *", tz="Asia/Shanghai"),
    )

[INPUT]
- (none)

[OUTPUT]
- HeartbeatStatus: Find the owner's heartbeat job by convention name.
- enable_heartbeat: Enable the heartbeat.  Idempotent: creates or resumes the...
- disable_heartbeat: Disable (pause) the heartbeat.  Returns False if no heart...
- get_heartbeat_status: Return the current heartbeat state.

[POS]
Heartbeat — convenience layer over CronManager for periodic agent self-checks.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NamedTuple

from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    CronJobPatch,
    DeliveryConfig,
    JobStatus,
    JobType,
    Schedule,
    ScheduleKind,
    SessionTarget,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.cron.manager import CronManager

logger = logging.getLogger(__name__)

HEARTBEAT_JOB_NAME = "__heartbeat__"

_DEFAULT_INTERVAL_MS = 30 * 60 * 1000  # 30 minutes
_DEFAULT_TIMEOUT = 120
_DEFAULT_PROMPT = (
    "[Agent Self-Check]\n"
    "You are performing a periodic autonomous check.  Please:\n"
    "1. Review your memory for any pending tasks, reminders, or follow-ups.\n"
    "2. Check if there are actionable items based on the current date/time.\n"
    "3. If you find anything that needs attention, take appropriate action "
    "and report your findings.\n"
    "4. If nothing requires attention, respond with exactly `[SILENT]`."
)


class HeartbeatStatus(NamedTuple):
    enabled: bool
    job: CronJob | None


async def _find_heartbeat(manager: CronManager, owner_id: str) -> CronJob | None:
    """Find the owner's heartbeat job by convention name."""
    jobs = await manager.list_jobs(owner_id, limit=200)
    return next((j for j in jobs if j.name == HEARTBEAT_JOB_NAME), None)


def _build_schedule(
    schedule: Schedule | None,
    interval_ms: int,
) -> Schedule:
    """Build the Schedule from explicit schedule or legacy interval_ms."""
    if schedule is not None:
        return schedule
    return Schedule(kind=ScheduleKind.INTERVAL, interval_ms=interval_ms)


async def enable_heartbeat(
    manager: CronManager,
    owner_id: str,
    *,
    interval_ms: int = _DEFAULT_INTERVAL_MS,
    schedule: Schedule | None = None,
    prompt: str | None = None,
    model: str | None = None,
) -> CronJob:
    """Enable the heartbeat.  Idempotent: creates or resumes the job.

    When *schedule* is provided it takes precedence over *interval_ms*.
    This allows callers to pass a CRON-based schedule for time-of-day
    triggering (e.g. ``Schedule(kind=ScheduleKind.CRON, expr="0 9 * * *",
    tz="Asia/Shanghai")``).
    """
    sched = _build_schedule(schedule, interval_ms)
    existing = await _find_heartbeat(manager, owner_id)

    if existing is not None:
        patch = CronJobPatch(
            status=JobStatus.ACTIVE,
            schedule=sched,
            prompt=prompt or existing.prompt or _DEFAULT_PROMPT,
            model=model,
        )
        updated = await manager.update_job(existing.id, owner_id, patch)
        if updated is not None:
            return updated
        return existing

    return await manager.create_job(
        user_id=owner_id,
        name=HEARTBEAT_JOB_NAME,
        job_type=JobType.AGENT,
        schedule=sched,
        prompt=prompt or _DEFAULT_PROMPT,
        model=model,
        delivery=DeliveryConfig(channel="chat"),
        session_target=SessionTarget.ISOLATED,
        timeout_seconds=_DEFAULT_TIMEOUT,
        deduplicate=True,
    )


async def disable_heartbeat(manager: CronManager, owner_id: str) -> bool:
    """Disable (pause) the heartbeat.  Returns False if no heartbeat exists."""
    existing = await _find_heartbeat(manager, owner_id)
    if existing is None:
        return False
    result = await manager.pause_job(existing.id, owner_id)
    return result is not None


async def get_heartbeat_status(manager: CronManager, owner_id: str) -> HeartbeatStatus:
    """Return the current heartbeat state."""
    existing = await _find_heartbeat(manager, owner_id)
    if existing is None:
        return HeartbeatStatus(enabled=False, job=None)
    return HeartbeatStatus(
        enabled=existing.status == JobStatus.ACTIVE,
        job=existing,
    )
