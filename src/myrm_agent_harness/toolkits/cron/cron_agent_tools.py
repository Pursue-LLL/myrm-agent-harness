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
from collections.abc import Callable
from contextvars import ContextVar, Token
from datetime import UTC, timedelta
from datetime import datetime as dt
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.infra.incremental.types import MonitorConfig
from myrm_agent_harness.toolkits.cron.engine.name_generator import generate_job_name
from myrm_agent_harness.toolkits.cron.engine.parser import describe_schedule
from myrm_agent_harness.toolkits.cron.types import (
    ActiveHours,
    CronJobPatch,
    DeliveryConfig,
    JobType,
    Schedule,
    ScheduleKind,
    SessionTarget,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.cron.manager import CronManager

# Blueprint filler: (blueprint_id, values_dict, tz) -> (schedule_dict, prompt, name) | None
BlueprintFiller = Callable[[str, dict[str, str], str | None], tuple[dict[str, str | int | None], str, str] | None]
DeliveryResolver = Callable[[str], DeliveryConfig]

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
    blueprint_catalog: str = "",
    blueprint_filler: BlueprintFiller | None = None,
    delivery_resolver: DeliveryResolver | None = None,
) -> list[BaseTool]:
    """Create a single cron management tool bound to a user.

    ``current_model`` is the LiteLLM model name of the calling Agent session,
    used as default when the user doesn't specify a model for a new cron job.

    ``blueprint_catalog`` is a pre-rendered text snippet describing available
    blueprints, appended to the tool description for LLM awareness.

    ``blueprint_filler`` is a callable that fills a blueprint by ID and slot
    values, returning (schedule_dict, prompt, name) or None if unknown.

    ``delivery_resolver`` maps webhook URLs to ``DeliveryConfig``. When omitted,
    non-empty URLs use generic ``webhook`` delivery (no channel-specific heuristics).
    """
    _blueprint_suffix = f"\n\n{blueprint_catalog}" if blueprint_catalog else ""

    def _resolve_delivery(webhook_url: str) -> DeliveryConfig:
        if delivery_resolver is not None:
            return delivery_resolver(webhook_url)
        if not webhook_url.strip():
            return DeliveryConfig(channel="chat")
        return DeliveryConfig(channel="webhook", target=webhook_url)

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
        blueprint: str = "",
        blueprint_values: str = "",
        monitor_type: str = "",
        monitor_enabled: bool = False,
        session_mode: str = "",
    ) -> str:
        """Manage scheduled tasks (create, list, update, delete, trigger, pause, resume).

        Actions:
          add    - Create a task. Fill (prompt OR command) + ONE schedule param.
                   Use prompt for agent tasks, command for shell tasks.
                   Recurring schedules (cron_expr or every_minutes) require
                   recurring_confirmed=true. For one-time reminders use "at".
                   Minimum interval for every_minutes is 5 minutes.
                   OR use blueprint + blueprint_values for template-based creation
                   (automatically fills prompt, schedule, and name).
          list   - Show all tasks. Use name_filter for fuzzy search (e.g. "backup").
          update - Modify a task. Requires job_id.
          remove - Delete a task. Requires job_id.
          run    - Trigger a task now. Requires job_id.
          pause  - Pause a task (preserves history). Requires job_id.
          resume - Resume a paused task. Requires job_id.

        Schedule (for add/update — fill exactly ONE, unless using blueprint):
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
            blueprint: Blueprint ID for template-based task creation (for add).
                When set, the blueprint's tuned prompt template and schedule
                logic are used. Slot values are provided via blueprint_values.
                This ensures consistent quality between GUI and Agent creation.
            blueprint_values: JSON object of slot values for the blueprint.
                E.g. '{"time": "08:00", "weekdays": "weekdays"}'.
                Only used when blueprint is set.
            monitor_type: Incremental monitoring type. "set" (detect new items
                in line-delimited output), "hash", or "timeseries". For add/update.
                When set with monitor_enabled=true, the task only delivers
                results when output changes (e.g. new prices, new articles).
                Use "off" to disable monitoring on an existing task (update only).
            monitor_enabled: Enable incremental monitoring. For add/update.
                Use when the user wants to track changes and only be notified
                on new content (e.g. "notify me only when the price changes").
            session_mode: Session context mode for agent tasks. For add/update.
                "" or "isolated" — each execution starts with a blank context
                    (default, good for independent tasks).
                "main" — reuses the bound chat session's history, so the task
                    remembers previous results and can compare changes
                    (good for monitoring/polling within a conversation).
                "daily" — same-day executions share context; fresh each day
                    (good for daily briefings that build up during the day).
        """
        effective_model = model.strip() or current_model

        if action in ("add", "update") and _IN_CRON_EXECUTION.get():
            return (
                "Error: cannot create or modify scheduled tasks from within "
                "a cron job execution. This prevents infinite task chains."
            )

        # Blueprint-based creation: fill prompt/schedule from blueprint template
        bp_prompt = prompt
        bp_cron_expr = cron_expr
        bp_every_minutes = every_minutes
        bp_at = at
        bp_tz = tz
        bp_name = name

        if action == "add" and blueprint.strip() and blueprint_filler:
            bp_values: dict[str, str] = {}
            if blueprint_values.strip():
                try:
                    bp_values = json.loads(blueprint_values)
                except (json.JSONDecodeError, TypeError):
                    return "Error: blueprint_values must be valid JSON object, e.g. '{\"time\": \"08:00\"}'."

            fill_result = blueprint_filler(blueprint.strip(), bp_values, tz.strip() or None)
            if fill_result is None:
                return f"Error: unknown blueprint '{blueprint.strip()}'. Use list action or check available blueprints."

            sched_dict, filled_prompt, filled_name = fill_result
            bp_prompt = filled_prompt
            bp_name = bp_name or filled_name

            sched_kind = sched_dict.get("kind", "")
            if sched_kind == "cron" and sched_dict.get("expr"):
                bp_cron_expr = str(sched_dict["expr"])
                bp_tz = str(sched_dict.get("tz") or tz or "")
            elif sched_kind == "interval" and sched_dict.get("interval_ms"):
                bp_every_minutes = int(sched_dict["interval_ms"]) // 60_000

        dispatch = {
            "add": lambda: _do_add(
                manager,
                user_id,
                bp_prompt,
                command,
                effective_model,
                bp_cron_expr,
                bp_every_minutes,
                bp_at,
                bp_tz,
                bp_name,
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
                monitor_type=monitor_type,
                monitor_enabled=monitor_enabled,
                session_mode=session_mode,
                resolve_delivery=_resolve_delivery,
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
                monitor_type=monitor_type,
                monitor_enabled=monitor_enabled,
                session_mode=session_mode,
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

    if _blueprint_suffix:
        cron_manage.description = (cron_manage.description or "") + _blueprint_suffix

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


_VALID_MONITOR_TYPES = {"set", "hash", "timeseries"}


def _build_monitor_config(
    monitor_type: str, monitor_enabled: bool,
) -> tuple[str | None, MonitorConfig | None, bool]:
    """Build MonitorConfig from tool parameters.

    Returns (error_msg, config, should_clear).  When ``monitor_type`` is
    ``"off"``, ``should_clear=True`` signals that monitoring should be removed.
    """
    mt = monitor_type.strip().lower()
    if mt == "off":
        return None, None, True
    if not monitor_enabled and not mt:
        return None, None, False
    if not monitor_enabled:
        return "Set monitor_enabled=true to enable monitoring.", None, False
    mt = mt or "set"
    if mt not in _VALID_MONITOR_TYPES:
        valid = ", ".join(sorted(_VALID_MONITOR_TYPES))
        return f"Invalid monitor_type '{monitor_type}'. Must be one of: {valid}.", None, False
    return None, MonitorConfig(monitor_type=mt, enabled=True), False


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


_SESSION_MODE_MAP: dict[str, SessionTarget] = {
    "isolated": SessionTarget.ISOLATED,
    "main": SessionTarget.MAIN,
    "daily": SessionTarget.DAILY,
}


def _parse_session_mode(raw: str) -> tuple[str | None, SessionTarget]:
    """Parse session_mode string into SessionTarget enum.

    Returns (error_msg, SessionTarget). error_msg is None on success.
    """
    cleaned = raw.strip().lower()
    if not cleaned:
        return None, SessionTarget.ISOLATED
    target = _SESSION_MODE_MAP.get(cleaned)
    if target is None:
        valid = ", ".join(sorted(_SESSION_MODE_MAP))
        return f"Invalid session_mode '{raw}'. Must be one of: {valid}.", SessionTarget.ISOLATED
    return None, target


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
    monitor_type: str = "",
    monitor_enabled: bool = False,
    session_mode: str = "",
    *,
    resolve_delivery: DeliveryResolver,
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

    delivery = resolve_delivery(webhook_url)
    failure_delivery = resolve_delivery(failure_webhook_url) if failure_webhook_url.strip() else None
    active_hours = _build_active_hours(active_start, active_end, active_tz)

    effective_max_fires: int | None = max_fires if max_fires > 0 else None
    try:
        expires_at = _parse_expires_after(expires_after)
    except (ValueError, TypeError):
        return f"Invalid expires_after format: '{expires_after}'. Use '3d', '2w', '3m', or ISO 8601."

    parsed_context_from = _parse_context_from(context_from)
    mon_err, monitor_config, _clear = _build_monitor_config(monitor_type, monitor_enabled)
    if mon_err:
        return mon_err

    sm_err, session_target = _parse_session_mode(session_mode)
    if sm_err:
        return sm_err

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
            session_target=session_target,
            max_fires=effective_max_fires,
            expires_at=expires_at,
            context_from=parsed_context_from,
            monitor_config=monitor_config,
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
    if job.monitor_config and job.monitor_config.enabled:
        result["monitor"] = job.monitor_config.monitor_type

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
        mon_tag = f" [Δ{j.monitor_config.monitor_type}]" if j.monitor_config and j.monitor_config.enabled else ""
        lines.append(
            f"  {icon} [{j.id}] {j.name}{type_tag}{model_tag}{fires_tag}{ctx_tag}{mon_tag} | {j.status.value} | next: {next_run}"
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
    monitor_type: str = "",
    monitor_enabled: bool = False,
    session_mode: str = "",
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
    mon_err, monitor_config, clear_monitor = _build_monitor_config(monitor_type, monitor_enabled)
    if mon_err:
        return mon_err

    parsed_session_target: SessionTarget | None = None
    if session_mode.strip():
        sm_err, parsed_session_target = _parse_session_mode(session_mode)
        if sm_err:
            return sm_err

    patch = CronJobPatch(
        name=name.strip() or None,
        prompt=prompt.strip() or None,
        command=command.strip() or None,
        model=model.strip() or None,
        schedule=new_schedule,
        max_fires=effective_max_fires,
        expires_at=expires_at,
        context_from=parsed_context_from,
        monitor_config=monitor_config,
        clear_monitor_config=clear_monitor,
        session_target=parsed_session_target,
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
    if job.monitor_config and job.monitor_config.enabled:
        result["monitor"] = job.monitor_config.monitor_type

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
