"""Agent tool for scheduled task management.

Single ``cron_manage`` tool with implicit schedule detection:
fill ``cron_expr`` → cron, ``every_minutes`` → interval, ``at`` → one-shot.

Includes a ContextVar-based self-scheduling guard that blocks ``add``/``update``
when called from within a cron job execution, preventing infinite task chains.

[INPUT]
- (none)

[OUTPUT]
- enter_cron_execution_context: Mark the current async context as running inside a cron j...
- exit_cron_execution_context: Restore the previous cron execution context.
- create_cron_tools: Create a single cron management tool bound to a user.

[POS]
Agent tool for scheduled task management.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, timedelta
from datetime import datetime as dt
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.toolkits.cron.engine.name_generator import generate_job_name
from myrm_agent_harness.toolkits.cron.engine.parser import describe_schedule
from myrm_agent_harness.toolkits.cron.types import (
    ActiveHours,
    CronJobPatch,
    DeliveryConfig,
    JobType,
    Schedule,
    ScheduleKind,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.cron.manager import CronManager

logger = logging.getLogger(__name__)

_MIN_INTERVAL_MINUTES = 5

_IN_CRON_EXECUTION: ContextVar[bool] = ContextVar("_in_cron_execution", default=False)


def enter_cron_execution_context() -> Token[bool]:
    """Mark the current async context as running inside a cron job callback.

    Returns a token for ``exit_cron_execution_context``.
    """
    return _IN_CRON_EXECUTION.set(True)


def exit_cron_execution_context(token: Token[bool]) -> None:
    """Restore the previous cron execution context."""
    _IN_CRON_EXECUTION.reset(token)


def create_cron_tools(
    manager: CronManager,
    user_id: str,
    *,
    current_model: str = "",
    chat_id: str | None = None,
    agent_id: str | None = None,
) -> list[BaseTool]:
    """Create a single cron management tool bound to a user.

    ``current_model`` is the LiteLLM model name of the calling Agent session,
    used as default when the user doesn't specify a model for a new cron job.
    """

    @tool("cron_manage_tool")
    async def cron_manage(
        action: Literal["add", "list", "update", "remove", "run", "pause", "resume"],
        prompt: str = "",
        command: str = "",
        model: str = "",
        cron_expr: str = "",
        every_minutes: int = 0,
        at: str = "",
        tz: str = "",
        job_id: str = "",
        name: str = "",
        name_filter: str = "",
        webhook_url: str = "",
        failure_webhook_url: str = "",
        recurring_confirmed: bool = False,
        active_start: str = "",
        active_end: str = "",
        active_tz: str = "",
        max_fires: int = 0,
        expires_after: str = "",
        context_from: str = "",
    ) -> str:
        """Manage scheduled tasks (create, list, update, delete, trigger, pause, resume).

        Actions:
          add    - Create a task. Fill (prompt OR command) + ONE schedule param.
                   Use prompt for agent tasks, command for shell tasks.
                   Recurring schedules (cron_expr or every_minutes) require
                   recurring_confirmed=true. For one-time reminders use "at".
                   Minimum interval for every_minutes is 5 minutes.
          list   - Show all tasks. Use name_filter for fuzzy search (e.g. "backup").
          update - Modify a task. Requires job_id.
          remove - Delete a task. Requires job_id.
          run    - Trigger a task now. Requires job_id.
          pause  - Pause a task (preserves history). Requires job_id.
          resume - Resume a paused task. Requires job_id.

        Schedule (for add/update — fill exactly ONE):
          cron_expr     - Cron expression, e.g. "0 9 * * *" (daily 9am),
                          "*/30 * * * *" (every 30min), "0 9 * * 1-5" (weekdays).
          every_minutes - Recurring interval in minutes (minimum 5).
          at            - ISO 8601 one-shot time, e.g. "2026-03-01T10:00:00".

        Args:
            action: Operation to perform.
            prompt: What the agent should do when the task fires (agent task).
            command: Shell command to execute when the task fires (shell task).
                Mutually exclusive with prompt — provide exactly one.
            model: LiteLLM model name, e.g. "openai/gpt-4o-mini". Leave empty
                to use the user's default model at execution time.
            cron_expr: Cron expression (implies cron schedule).
            every_minutes: Interval in minutes (implies interval schedule).
            at: ISO 8601 datetime (implies one-shot schedule).
            tz: IANA timezone, e.g. "Asia/Shanghai" (only for cron).
            job_id: Task ID (for update/remove/run/pause/resume).
            name: Optional task name (auto-generated from prompt/command if omitted).
            name_filter: Fuzzy search filter for list action (e.g. "backup" finds
                all tasks containing "backup" in name).
            webhook_url: If set, results are POSTed to this URL (Slack/Feishu
                bot webhook). Otherwise results appear in chat.
            failure_webhook_url: If set, failure alerts are POSTed to this URL
                instead of the main delivery channel. Use for separate ops alerting.
            recurring_confirmed: Required true for recurring schedules (cron_expr
                or every_minutes). Prevents accidental creation of recurring tasks.
            active_start: Start of active hours in HH:MM format, e.g. "09:00".
                Task only runs within [active_start, active_end).
            active_end: End of active hours in HH:MM format, e.g. "18:00".
            active_tz: IANA timezone for active hours, e.g. "Asia/Shanghai".
                Defaults to UTC if omitted.
            max_fires: Max number of executions (0 = unlimited). For add/update.
                E.g. max_fires=100 means the task auto-stops after 100 runs.
            expires_after: Auto-expire duration or ISO 8601 datetime. For add/update.
                Duration: "3d" (3 days), "2w" (2 weeks), "3m" (3 months).
                Datetime: "2026-06-01T00:00:00".
            context_from: Comma-separated job IDs whose latest successful output
                will be injected into this task's prompt at execution time.
                Use to chain tasks: task A collects data, task B analyzes it.
                E.g. "abc123,def456". For add/update.
        """
        effective_model = model.strip() or current_model

        if action in ("add", "update") and _IN_CRON_EXECUTION.get():
            return (
                "Error: cannot create or modify scheduled tasks from within "
                "a cron job execution. This prevents infinite task chains."
            )

        dispatch = {
            "add": lambda: _do_add(
                manager,
                user_id,
                prompt,
                command,
                effective_model,
                cron_expr,
                every_minutes,
                at,
                tz,
                name,
                webhook_url,
                failure_webhook_url,
                recurring_confirmed,
                active_start,
                active_end,
                active_tz,
                chat_id,
                max_fires,
                expires_after,
                agent_id=agent_id,
                context_from=context_from,
            ),
            "list": lambda: _do_list(manager, user_id, name_filter),
            "update": lambda: _do_update(
                manager,
                user_id,
                job_id,
                prompt,
                command,
                model,
                cron_expr,
                every_minutes,
                at,
                tz,
                name,
                max_fires,
                expires_after,
                context_from=context_from,
            ),
            "remove": lambda: _do_remove(manager, user_id, job_id),
            "run": lambda: _do_run(manager, user_id, job_id),
            "pause": lambda: _do_pause(manager, user_id, job_id),
            "resume": lambda: _do_resume(manager, user_id, job_id),
        }
        handler = dispatch.get(action)
        if not handler:
            return f"Unknown action: {action}"
        return await handler()

    return [cron_manage]


# ---------------------------------------------------------------------------
# Schedule builder (implicit type detection)
# ---------------------------------------------------------------------------


def _build_schedule(
    cron_expr: str,
    every_minutes: int,
    at: str,
    tz: str,
) -> tuple[str | None, Schedule | None]:
    """Return (error_msg, Schedule) — exactly one will be non-None."""
    filled = sum([bool(cron_expr), every_minutes > 0, bool(at)])
    if filled == 0:
        return "Provide one of: cron_expr, every_minutes, or at.", None
    if filled > 1:
        return "Provide only ONE schedule param (cron_expr / every_minutes / at).", None

    if cron_expr:
        return None, Schedule(kind=ScheduleKind.CRON, expr=cron_expr, tz=tz or None)
    if every_minutes > 0:
        if every_minutes < _MIN_INTERVAL_MINUTES:
            return (
                f"every_minutes must be >= {_MIN_INTERVAL_MINUTES}. For one-time tasks use 'at' instead.",
                None,
            )
        return None, Schedule(kind=ScheduleKind.INTERVAL, interval_ms=every_minutes * 60_000)
    if at:
        run_at = dt.fromisoformat(at)
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=UTC)
        return None, Schedule(kind=ScheduleKind.ONCE, run_at=run_at)

    return "Could not determine schedule type.", None


def _resolve_delivery(webhook_url: str) -> DeliveryConfig:
    """Map a webhook URL to a DeliveryConfig."""
    if not webhook_url:
        return DeliveryConfig(channel="chat")

    url_lower = webhook_url.lower()
    if "open.feishu.cn" in url_lower or "open.larksuite.com" in url_lower:
        return DeliveryConfig(channel="feishu", target=webhook_url)

    return DeliveryConfig(channel="webhook", target=webhook_url)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DURATION_UNITS: dict[str, int] = {"d": 1, "w": 7, "m": 30}


def _parse_expires_after(value: str) -> dt | None:
    """Parse a human-friendly duration ("3d", "2w", "3m") or ISO 8601 datetime."""
    value = value.strip()
    if not value:
        return None
    if len(value) >= 2 and value[-1] in _DURATION_UNITS and value[:-1].isdigit():
        days = int(value[:-1]) * _DURATION_UNITS[value[-1]]
        return dt.now(UTC) + timedelta(days=days)
    parsed = dt.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------


def _build_active_hours(start: str, end: str, active_tz: str) -> ActiveHours | None:
    """Build ActiveHours if both start and end are provided."""
    if not start.strip() or not end.strip():
        return None
    return ActiveHours(start=start.strip(), end=end.strip(), tz=active_tz.strip() or "UTC")


def _parse_context_from(raw: str) -> tuple[str, ...]:
    """Parse comma-separated job IDs into a deduplicated tuple."""
    if not raw.strip():
        return ()
    ids = [s.strip() for s in raw.split(",") if s.strip()]
    seen: set[str] = set()
    unique: list[str] = []
    for ref_id in ids:
        if ref_id not in seen:
            seen.add(ref_id)
            unique.append(ref_id)
    return tuple(unique)


async def _do_add(
    mgr: CronManager,
    user_id: str,
    prompt: str,
    command: str,
    model: str,
    cron_expr: str,
    every_minutes: int,
    at: str,
    tz: str,
    name: str,
    webhook_url: str,
    failure_webhook_url: str,
    recurring_confirmed: bool,
    active_start: str,
    active_end: str,
    active_tz: str,
    chat_id: str | None = None,
    max_fires: int = 0,
    expires_after: str = "",
    agent_id: str | None = None,
    context_from: str = "",
) -> str:
    has_prompt = bool(prompt.strip())
    has_command = bool(command.strip())

    if has_prompt and has_command:
        return "Provide either prompt (agent task) or command (shell task), not both."
    if not has_prompt and not has_command:
        return "Either prompt or command is required."

    err, schedule = _build_schedule(cron_expr, every_minutes, at, tz)
    if err or not schedule:
        return err or "Schedule build failed."

    is_recurring = schedule.kind in (ScheduleKind.CRON, ScheduleKind.INTERVAL)
    if is_recurring and not recurring_confirmed:
        return (
            "Recurring schedules (cron_expr or every_minutes) require "
            "recurring_confirmed=true to prevent accidental creation. "
            "For one-time reminders, use 'at' instead."
        )

    if has_command:
        job_type = JobType.SHELL
        task_name = name.strip() or generate_job_name(command.strip())
    else:
        job_type = JobType.AGENT
        task_name = name.strip() or generate_job_name(prompt.strip())

    delivery = _resolve_delivery(webhook_url)
    failure_delivery = _resolve_delivery(failure_webhook_url) if failure_webhook_url.strip() else None
    active_hours = _build_active_hours(active_start, active_end, active_tz)

    effective_max_fires: int | None = max_fires if max_fires > 0 else None
    try:
        expires_at = _parse_expires_after(expires_after)
    except (ValueError, TypeError):
        return f"Invalid expires_after format: '{expires_after}'. Use '3d', '2w', '3m', or ISO 8601."

    parsed_context_from = _parse_context_from(context_from)

    try:
        job = await mgr.create_job(
            user_id=user_id,
            name=task_name,
            job_type=job_type,
            schedule=schedule,
            prompt=prompt.strip() or None,
            command=command.strip() or None,
            model=model.strip() or None,
            chat_id=chat_id,
            agent_id=agent_id,
            delivery=delivery,
            failure_delivery=failure_delivery,
            active_hours=active_hours,
            max_fires=effective_max_fires,
            expires_at=expires_at,
            context_from=parsed_context_from,
        )
    except ValueError as exc:
        return str(exc)

    next_run = job.next_run_at.strftime("%Y-%m-%d %H:%M UTC") if job.next_run_at else "N/A"
    type_label = "Shell" if job_type == JobType.SHELL else "Agent"

    result: dict[str, str | int | None] = {
        "status": "success",
        "action": "add",
        "job_id": job.id,
        "name": job.name,
        "job_type": type_label,
        "model": job.model,
        "schedule": describe_schedule(schedule),
        "next_run": next_run,
    }
    if job.max_fires is not None:
        result["max_fires"] = job.max_fires
    if job.expires_at is not None:
        result["expires_at"] = job.expires_at.strftime("%Y-%m-%d %H:%M UTC")
    if job.context_from:
        result["context_from"] = list(job.context_from)

    return json.dumps(result, ensure_ascii=False)


async def _do_list(mgr: CronManager, user_id: str, name_filter: str) -> str:
    jobs = await mgr.list_jobs(user_id, name_filter=name_filter.strip() or None)
    if not jobs:
        return "No scheduled tasks."

    lines: list[str] = [f"{len(jobs)} task(s):\n"]
    for j in jobs:
        next_run = j.next_run_at.strftime("%m-%d %H:%M") if j.next_run_at else "—"
        icon = ">" if j.status.value == "active" else "||"
        type_tag = "[shell]" if j.job_type == JobType.SHELL else ""
        model_tag = f" ({j.model})" if j.model else ""
        fires_tag = f" [{j.fire_count}/{j.max_fires}]" if j.max_fires else ""
        ctx_tag = f" ←[{','.join(j.context_from)}]" if j.context_from else ""
        lines.append(
            f"  {icon} [{j.id}] {j.name}{type_tag}{model_tag}{fires_tag}{ctx_tag}"
            f" | {j.status.value} | next: {next_run}"
        )
    return "\n".join(lines)


async def _do_update(
    mgr: CronManager,
    user_id: str,
    job_id: str,
    prompt: str,
    command: str,
    model: str,
    cron_expr: str,
    every_minutes: int,
    at: str,
    tz: str,
    name: str,
    max_fires: int = 0,
    expires_after: str = "",
    context_from: str = "",
) -> str:
    if not job_id:
        return "job_id required. Use action='list' first."

    new_schedule: Schedule | None = None
    if any([cron_expr, every_minutes > 0, at]):
        err, new_schedule = _build_schedule(cron_expr, every_minutes, at, tz)
        if err:
            return err

    effective_max_fires: int | None = max_fires if max_fires > 0 else None
    try:
        expires_at = _parse_expires_after(expires_after)
    except (ValueError, TypeError):
        return f"Invalid expires_after format: '{expires_after}'. Use '3d', '2w', '3m', or ISO 8601."

    parsed_context_from = _parse_context_from(context_from) if context_from.strip() else None

    patch = CronJobPatch(
        name=name.strip() or None,
        prompt=prompt.strip() or None,
        command=command.strip() or None,
        model=model.strip() or None,
        schedule=new_schedule,
        max_fires=effective_max_fires,
        expires_at=expires_at,
        context_from=parsed_context_from,
    )

    try:
        job = await mgr.update_job(job_id, user_id, patch)
    except ValueError as exc:
        return str(exc)

    if not job:
        return f"Task {job_id} not found."

    next_run = job.next_run_at.strftime("%Y-%m-%d %H:%M UTC") if job.next_run_at else "N/A"
    type_label = "Shell" if job.job_type == JobType.SHELL else "Agent"

    result: dict[str, str | int | None] = {
        "status": "success",
        "action": "update",
        "job_id": job.id,
        "name": job.name,
        "job_type": type_label,
        "model": job.model,
        "schedule": describe_schedule(job.schedule),
        "next_run": next_run,
    }
    if job.max_fires is not None:
        result["max_fires"] = job.max_fires
        result["fire_count"] = job.fire_count
    if job.expires_at is not None:
        result["expires_at"] = job.expires_at.strftime("%Y-%m-%d %H:%M UTC")
    if job.context_from:
        result["context_from"] = list(job.context_from)

    return json.dumps(result, ensure_ascii=False)


async def _do_remove(mgr: CronManager, user_id: str, job_id: str) -> str:
    if not job_id:
        return "job_id required. Use action='list' to find IDs."
    deleted = await mgr.delete_job(job_id, user_id)
    return f"Task {job_id} deleted." if deleted else f"Task {job_id} not found."


async def _do_run(mgr: CronManager, user_id: str, job_id: str) -> str:
    if not job_id:
        return "job_id required. Use action='list' to find IDs."
    triggered = await mgr.trigger_now(job_id, user_id)
    return f"Task {job_id} triggered." if triggered else f"Task {job_id} not found or not active."


async def _do_pause(mgr: CronManager, user_id: str, job_id: str) -> str:
    if not job_id:
        return "job_id required. Use action='list' to find IDs."
    job = await mgr.pause_job(job_id, user_id)
    if not job:
        return f"Task {job_id} not found."
    return json.dumps(
        {"status": "success", "action": "pause", "job_id": job.id, "name": job.name},
        ensure_ascii=False,
    )


async def _do_resume(mgr: CronManager, user_id: str, job_id: str) -> str:
    if not job_id:
        return "job_id required. Use action='list' to find IDs."
    job = await mgr.resume_job(job_id, user_id)
    if not job:
        return f"Task {job_id} not found."
    next_run = job.next_run_at.strftime("%Y-%m-%d %H:%M UTC") if job.next_run_at else "N/A"
    return json.dumps(
        {"status": "success", "action": "resume", "job_id": job.id, "name": job.name, "next_run": next_run},
        ensure_ascii=False,
    )
