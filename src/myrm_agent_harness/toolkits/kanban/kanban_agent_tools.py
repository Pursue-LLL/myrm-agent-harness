"""Agent tools for kanban task management — modular per-action design.

Tools are grouped by role (Worker / Orchestrator / Full) for security and token
efficiency.

[INPUT]
- .types::TaskStatus, TaskPriority (POS: Kanban domain types.)
- .protocols::KanbanStore (POS: Protocols for the kanban toolkit.)

[OUTPUT]
- create_kanban_tools: Factory that returns role-scoped tool sets.
- get_worker_lifecycle_guidance: Pure function returning lifecycle guidance text for worker system prompts.
- KanbanToolMode: Literal type for role selection.

[POS]
Agent tools for kanban task management — modular per-action, role-scoped.
"""

from __future__ import annotations

import contextlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.toolkits.kanban.types import (
    BlockKind,
    KanbanTask,
    TaskEventKind,
    TaskPriority,
    TaskStatus,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
    from myrm_agent_harness.toolkits.kanban.protocols import KanbanStore

logger = get_agent_logger(__name__)

KanbanToolMode = Literal["worker", "orchestrator", "full"]

_DURATION_RE = re.compile(
    r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$",
    re.IGNORECASE,
)


def _parse_until(value: str) -> datetime | None:
    """Parse an ISO-8601 datetime or shorthand duration (e.g. '30m', '2h') into UTC datetime."""
    value = value.strip()
    if not value:
        return None
    m = _DURATION_RE.match(value)
    if m and any(m.groups()):
        days = int(m.group(1) or 0)
        hours = int(m.group(2) or 0)
        minutes = int(m.group(3) or 0)
        seconds = int(m.group(4) or 0)
        return datetime.now(UTC) + timedelta(
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
        )
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


_STATUS_TO_EVENT_KIND: dict[TaskStatus, TaskEventKind] = {
    TaskStatus.BLOCKED: TaskEventKind.BLOCKED,
    TaskStatus.ARCHIVED: TaskEventKind.ARCHIVED,
    TaskStatus.COMPLETED: TaskEventKind.COMPLETED,
    TaskStatus.FAILED: TaskEventKind.FAILED,
}

# Status values that only the dispatcher should set (not agents)
_DISPATCHER_ONLY_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.RUNNING})


def get_worker_lifecycle_guidance(
    zombie_timeout_seconds: int = 120,
    max_runtime_seconds: int | None = None,
) -> str:
    """Return lifecycle guidance text for kanban worker agents.

    Designed to be injected into the worker's system prompt so the LLM knows
    how to correctly use kanban tools: complete/block at end, heartbeat
    frequency, and retry diagnostics.

    Args:
        zombie_timeout_seconds: Board's zombie reclaim timeout.
        max_runtime_seconds: Task-level runtime limit (None = board default).
    """
    heartbeat_interval = max(30, zombie_timeout_seconds // 2)
    runtime_note = (
        f"Your task has a runtime limit of {max_runtime_seconds}s. Plan accordingly and do not exceed it."
        if max_runtime_seconds
        else ""
    )

    return (
        "\n\n[Kanban Worker Lifecycle]\n"
        "You are executing a kanban task. Follow these rules strictly:\n"
        "1. You MUST end by calling kanban_complete(summary=...) or "
        "kanban_block(reason=...). kanban_block accepts an optional `until` param "
        "(e.g. '30m', '2h', ISO-8601) for timed blocks that auto-unblock.\n"
        f"2. For tasks longer than {heartbeat_interval}s, call kanban_heartbeat(note=...) "
        f"every ~{heartbeat_interval}s with progress info. Without heartbeat, your task "
        "will be reclaimed as a zombie.\n"
        "3. If you see 'Prior attempts' in your context, read the outcome/error carefully "
        "and change your approach — do not repeat the same failing strategy.\n"
        "4. Write a clear summary (1-3 sentences) in kanban_complete describing what you "
        "accomplished. Include structured metadata JSON (changed_files, verification commands, "
        "etc.) — it will be automatically injected into downstream workers' context.\n"
        "5. Use kanban_comment(task_id, body) to share findings, flag issues, or coordinate "
        "with sibling tasks. Comments are visible to other workers via their context.\n"
        f"{runtime_note}"
    )


def create_kanban_tools(
    store: KanbanStore,
    dispatcher: KanbanDispatcher | None = None,
    *,
    mode: KanbanToolMode = "full",
    default_board_id: str | None = None,
    agent_id: str | None = None,
    current_task_id: str | None = None,
) -> list[BaseTool]:
    """Create kanban tools scoped by role.

    Modes:
        worker: 5 tools (show/complete/block/heartbeat/comment) — bound to current_task_id.
        orchestrator: 7 tools (add_task/list_tasks/update_task/move_task/
                     delete_task/board_summary/link).
        full: worker + orchestrator (12 tools). Board CRUD uses REST/GUI, not LLM tools.

    When mode='worker', tools auto-bind to ``current_task_id`` and enforce
    ownership — the agent cannot operate on other tasks (except comments,
    which are intentionally unrestricted for cross-task coordination).
    """
    tools: list[BaseTool] = []

    if mode in ("worker", "full"):
        tools.extend(
            _build_worker_tools(
                store,
                dispatcher,
                current_task_id=current_task_id,
                agent_id=agent_id,
            )
        )

    if mode in ("orchestrator", "full"):
        tools.extend(
            _build_orchestrator_tools(
                store,
                dispatcher,
                default_board_id=default_board_id,
                agent_id=agent_id,
            )
        )

    return tools


# ---------------------------------------------------------------------------
# Worker tools — minimal surface, ownership-enforced
# ---------------------------------------------------------------------------


def _build_worker_tools(
    store: KanbanStore,
    dispatcher: KanbanDispatcher | None,
    *,
    current_task_id: str | None = None,
    agent_id: str | None = None,
) -> list[BaseTool]:
    """Build worker-scoped tools (5 tools: show, complete, block, heartbeat, comment)."""

    async def _validate_task_ownership(task_id: str) -> tuple[KanbanTask | None, str | None]:
        """Validate task exists and worker has ownership."""
        if current_task_id and task_id != current_task_id:
            return None, f"Permission denied: you can only operate on your assigned task ({current_task_id})"
        task = await store.get_task(task_id)
        if task is None:
            return None, f"Task {task_id} not found"
        return task, None

    @tool("kanban_show")
    async def kanban_show(task_id: str = "") -> str:
        """Show your current task fields (title, description, status, result, errors, metadata)."""
        resolved_id = task_id or current_task_id or ""
        if not resolved_id:
            return json.dumps({"error": "task_id is required"})
        task, err = await _validate_task_ownership(resolved_id)
        if err:
            return json.dumps({"error": err})
        assert task is not None
        return json.dumps({"task": task.to_dict()})

    @tool("kanban_complete")
    async def kanban_complete(summary: str, metadata: str = "", task_id: str = "") -> str:
        """Mark your task as completed with a structured handoff.

        Args:
            summary: 1-3 sentences describing what was accomplished (required).
            metadata: JSON string with machine-readable facts auto-injected into
                downstream workers' context, e.g. '{"changed_files": ["x.py"], "tests_run": 5}'.
            task_id: Defaults to your assigned task.
        """
        if not summary:
            return json.dumps({"error": "summary is required — describe what was accomplished"})
        resolved_id = task_id or current_task_id or ""
        if not resolved_id:
            return json.dumps({"error": "task_id is required"})
        task, err = await _validate_task_ownership(resolved_id)
        if err:
            return json.dumps({"error": err})
        assert task is not None

        if task.is_terminal:
            return json.dumps({"error": f"Task already in terminal state ({task.status})"})

        parsed_metadata: dict[str, object] | None = None
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
                if not isinstance(parsed_metadata, dict):
                    return json.dumps({"error": "metadata must be a JSON object"})
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid metadata JSON: {e}"})

        old_status = task.status
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(UTC)
        task.progress_note = None
        task.result = summary
        if parsed_metadata:
            task.metadata = {**task.metadata, "handoff": parsed_metadata}
        saved = await store.save_task(task)

        await store.append_event(
            resolved_id,
            TaskEventKind.COMPLETED,
            payload={"from": old_status.value, "to": "completed", "summary": summary},
        )

        if dispatcher:
            dispatcher.wake()

        return json.dumps({"status": "completed", "task": saved.to_dict()})

    @tool("kanban_block")
    async def kanban_block(reason: str, until: str = "", task_id: str = "") -> str:
        """Block your task when you cannot proceed.

        Args:
            reason: Clear reason for the blockage (required).
            until: Optional ISO-8601 datetime or duration (e.g. '30m', '2h', '2026-06-01T04:00:00Z')
                for auto-unblock. When set, the dispatcher will automatically unblock the task
                when the time arrives. Omit for human-intervention blocks.
            task_id: Defaults to your assigned task.
        """
        if not reason:
            return json.dumps({"error": "reason is required"})
        resolved_id = task_id or current_task_id or ""
        if not resolved_id:
            return json.dumps({"error": "task_id is required"})
        task, err = await _validate_task_ownership(resolved_id)
        if err:
            return json.dumps({"error": err})
        assert task is not None

        if task.is_terminal:
            return json.dumps({"error": f"Task already in terminal state ({task.status})"})

        scheduled_until: datetime | None = None
        if until:
            scheduled_until = _parse_until(until)
            if scheduled_until is None:
                return json.dumps(
                    {
                        "error": f"Invalid 'until' format: {until!r}. "
                        "Use ISO-8601 (e.g. '2026-06-01T04:00:00Z') or duration (e.g. '30m', '2h', '1d').",
                    }
                )
        block_kind = BlockKind.SCHEDULED if scheduled_until else BlockKind.HUMAN

        old_status = task.status
        task.status = TaskStatus.BLOCKED
        task.blocked_reason = reason
        task.block_kind = block_kind
        task.scheduled_until = scheduled_until
        task.progress_note = None
        task.block_cycle_count += 1
        saved = await store.save_task(task)

        await store.append_event(
            resolved_id,
            TaskEventKind.BLOCKED,
            payload={
                "from": old_status.value,
                "reason": reason,
                "block_kind": block_kind.value,
                **({"scheduled_until": scheduled_until.isoformat()} if scheduled_until else {}),
            },
        )

        if dispatcher:
            dispatcher.emit("task_blocked", saved)

        return json.dumps({"status": "blocked", "task": saved.to_dict()})

    @tool("kanban_heartbeat")
    async def kanban_heartbeat(note: str, task_id: str = "") -> str:
        """Report progress on your running task. Use to show real-time status updates."""
        if not note:
            return json.dumps({"error": "note is required"})
        resolved_id = task_id or current_task_id or ""
        if not resolved_id:
            return json.dumps({"error": "task_id is required"})
        task, err = await _validate_task_ownership(resolved_id)
        if err:
            return json.dumps({"error": err})
        assert task is not None

        if task.status != TaskStatus.RUNNING:
            return json.dumps({"error": f"Task is not running (status={task.status})"})

        await store.update_heartbeat(resolved_id, note=note)
        await store.append_event(
            resolved_id,
            TaskEventKind.HEARTBEAT,
            payload={"note": note},
        )

        if dispatcher:
            dispatcher.emit("heartbeat_progress", task)

        return json.dumps({"status": "heartbeat_ok", "task_id": resolved_id})

    @tool("kanban_comment")
    async def kanban_comment(task_id: str, body: str) -> str:
        """Leave a comment on any task's thread for cross-task coordination.

        Unlike other worker tools, this does NOT enforce ownership — workers
        can comment on sibling or parent tasks to share intermediate findings,
        flag issues, or coordinate with other workers.

        Args:
            task_id: Target task ID (may be your own or another task's).
            body: Comment text (markdown supported).
        """
        if not task_id:
            return json.dumps({"error": "task_id is required"})
        if not body or not body.strip():
            return json.dumps({"error": "body is required"})

        target = await store.get_task(task_id)
        if target is None:
            return json.dumps({"error": f"Task {task_id} not found"})

        author = agent_id or "worker"
        event = await store.append_event(
            task_id,
            TaskEventKind.USER_COMMENT,
            payload={"body": body.strip(), "author": author},
        )
        return json.dumps(
            {
                "status": "comment_added",
                "task_id": task_id,
                "event_id": event.event_id,
            }
        )

    return [kanban_show, kanban_complete, kanban_block, kanban_heartbeat, kanban_comment]


# ---------------------------------------------------------------------------
# Orchestrator tools — task lifecycle management
# ---------------------------------------------------------------------------


def _build_orchestrator_tools(
    store: KanbanStore,
    dispatcher: KanbanDispatcher | None,
    *,
    default_board_id: str | None = None,
    agent_id: str | None = None,
) -> list[BaseTool]:
    """Build orchestrator-scoped tools (7 tools)."""

    @tool("kanban_add_task")
    async def kanban_add_task(
        title: str,
        board_id: str = "",
        description: str = "",
        priority: str = "normal",
        parent_task_id: str = "",
        depends_on: str = "",
        max_retries: int = 3,
        max_runtime_seconds: int = 0,
        assign_agent_id: str = "",
        idempotency_key: str = "",
        skills: str = "",
    ) -> str:
        """Add a new task to the kanban board.

        Args:
            title: Task title (required).
            board_id: Target board (uses default if empty).
            description: Detailed task description.
            priority: urgent/high/normal/low.
            parent_task_id: Parent task for hierarchy.
            depends_on: Comma-separated task IDs this task depends on.
            max_retries: Max retry attempts on failure.
            max_runtime_seconds: Per-task timeout in seconds (0 = system default).
            assign_agent_id: Agent to assign this task to.
            idempotency_key: Unique key to prevent duplicate creation on retry.
            skills: Comma-separated skill names to load for this task only (e.g. "translation,security-audit"). These are appended to the agent profile's default skills.
        """
        resolved_board_id = board_id or default_board_id or ""
        if not resolved_board_id:
            return json.dumps({"error": "board_id is required"})
        if not title:
            return json.dumps({"error": "title is required"})

        # Idempotency check
        if idempotency_key:
            existing = await _find_task_by_idempotency_key(
                store,
                resolved_board_id,
                idempotency_key,
            )
            if existing:
                return json.dumps({"status": "already_exists", "task": existing.to_dict()})

        board = await store.get_board(resolved_board_id)
        if board is None:
            return json.dumps({"error": f"Board {resolved_board_id} not found"})

        try:
            task_priority = TaskPriority(priority)
        except ValueError:
            task_priority = TaskPriority.NORMAL

        dep_ids = [d.strip() for d in depends_on.split(",") if d.strip()] if depends_on else []
        initial_status = TaskStatus.BACKLOG if dep_ids else TaskStatus.READY

        parsed_skills: list[str] = (
            list(dict.fromkeys(s for raw in skills.split(",") if (s := raw.strip()))) if skills else []
        )

        task = KanbanTask(
            task_id=uuid.uuid4().hex[:12],
            board_id=resolved_board_id,
            title=title,
            description=description,
            status=initial_status,
            priority=task_priority,
            agent_id=assign_agent_id or agent_id,
            parent_task_id=parent_task_id or None,
            max_runtime_seconds=max_runtime_seconds if max_runtime_seconds > 0 else None,
            max_retries=max_retries,
            extra_skill_ids=parsed_skills,
        )

        if idempotency_key:
            if task.metadata is None:
                task.metadata = {}
            task.metadata["idempotency_key"] = idempotency_key

        saved = await store.save_task(task)
        await store.append_event(saved.task_id, TaskEventKind.CREATED)

        if dep_ids:
            valid_deps: list[str] = []
            for parent_id in dep_ids:
                parent = await store.get_task(parent_id)
                if parent is None:
                    logger.warning("Skipped dependency %s -> %s (parent not found)", parent_id, saved.task_id)
                    continue
                valid_deps.append(parent_id)
            for parent_id in valid_deps:
                try:
                    await store.add_edge(parent_id, saved.task_id)
                except ValueError as exc:
                    logger.warning("Skipped dependency %s -> %s: %s", parent_id, saved.task_id, exc)
            if not valid_deps and dep_ids:
                saved.status = TaskStatus.READY
                await store.save_task(saved)

        if dispatcher:
            dispatcher.wake()
        return json.dumps({"status": "added", "task": saved.to_dict()})

    @tool("kanban_list_tasks")
    async def kanban_list_tasks(
        board_id: str = "",
        status_filter: str = "",
        agent_id_filter: str = "",
        task_id: str = "",
    ) -> str:
        """List tasks on a board, optionally filtered by status or agent.

        When ``task_id`` is set, returns that single task (read-only) with
        parent/child dependency IDs and ``dependencies_met`` status.
        """
        resolved_task_id = task_id.strip()
        if resolved_task_id:
            task = await store.get_task(resolved_task_id)
            if task is None:
                return json.dumps({"error": f"Task {resolved_task_id} not found"})
            parents = await store.list_parents(resolved_task_id)
            children = await store.list_children(resolved_task_id)
            deps_met = await store.are_dependencies_met(resolved_task_id)
            return json.dumps(
                {
                    "tasks": [task.to_dict()],
                    "count": 1,
                    "parents": parents,
                    "children": children,
                    "dependencies_met": deps_met,
                }
            )

        resolved_board_id = board_id or default_board_id or ""
        if not resolved_board_id:
            return json.dumps({"error": "board_id is required"})

        status: TaskStatus | None = None
        if status_filter:
            try:
                status = TaskStatus(status_filter)
            except ValueError:
                return json.dumps({"error": f"Invalid status_filter: {status_filter}"})

        tasks = await store.list_tasks(
            resolved_board_id,
            status=status,
            agent_id=agent_id_filter or None,
        )
        return json.dumps({"tasks": [t.to_dict() for t in tasks], "count": len(tasks)})

    @tool("kanban_update_task")
    async def kanban_update_task(
        task_id: str,
        title: str = "",
        description: str = "",
        priority: str = "",
        max_runtime_seconds: int = -1,
        assign_agent_id: str = "",
        skills: str = "",
    ) -> str:
        """Update task fields (title, description, priority, timeout, assignment, or skills).

        Args:
            task_id: ID of the task to update (required).
            title: New title (unchanged if empty).
            description: New description (unchanged if empty).
            priority: New priority urgent/high/normal/low (unchanged if empty).
            max_runtime_seconds: Per-task timeout in seconds. 0 = reset to system default, -1 = unchanged.
            assign_agent_id: New agent assignment (unchanged if empty).
            skills: Comma-separated skill names to replace task-level skills. Pass "CLEAR" to remove all task-level skills.
        """
        if not task_id:
            return json.dumps({"error": "task_id is required"})
        task = await store.get_task(task_id)
        if task is None:
            return json.dumps({"error": f"Task {task_id} not found"})

        if title:
            task.title = title
        if description:
            task.description = description
        if priority:
            with contextlib.suppress(ValueError):
                task.priority = TaskPriority(priority)
        if max_runtime_seconds == 0:
            task.max_runtime_seconds = None
        elif max_runtime_seconds > 0:
            task.max_runtime_seconds = max_runtime_seconds
        if assign_agent_id:
            task.agent_id = assign_agent_id
        if skills:
            if skills.strip().upper() == "CLEAR":
                task.extra_skill_ids = []
            else:
                task.extra_skill_ids = list(dict.fromkeys(s for raw in skills.split(",") if (s := raw.strip())))

        saved = await store.save_task(task)
        return json.dumps({"status": "updated", "task": saved.to_dict()})

    @tool("kanban_move_task")
    async def kanban_move_task(task_id: str, status: str) -> str:
        """Change task status (backlog/ready/blocked/archived). Cannot set to running — that is dispatcher-only."""
        if not task_id:
            return json.dumps({"error": "task_id is required"})
        if not status:
            return json.dumps({"error": "status is required"})

        task = await store.get_task(task_id)
        if task is None:
            return json.dumps({"error": f"Task {task_id} not found"})

        try:
            new_status = TaskStatus(status)
        except ValueError:
            return json.dumps({"error": f"Invalid status: {status}"})

        if new_status in _DISPATCHER_ONLY_STATUSES:
            return json.dumps({"error": f"Cannot set status to {new_status.value} — managed by dispatcher only"})

        if task.is_terminal and new_status != TaskStatus.ARCHIVED:
            return json.dumps({"error": f"Cannot move terminal task (status={task.status}) to {new_status}"})

        old_status = task.status
        task.status = new_status
        if new_status == TaskStatus.READY:
            task.blocked_reason = None
            task.block_kind = None
            task.scheduled_until = None
            if old_status == TaskStatus.BLOCKED:
                task.consecutive_failures = 0
                task.error = ""
            if not await store.are_dependencies_met(task_id):
                task.status = TaskStatus.BACKLOG
        if new_status == TaskStatus.BLOCKED and task.block_kind is None:
            task.block_kind = BlockKind.HUMAN
        if new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.ARCHIVED):
            task.completed_at = datetime.now(UTC)

        saved = await store.save_task(task)

        event_kind = _STATUS_TO_EVENT_KIND.get(saved.status)
        if old_status == TaskStatus.BLOCKED and saved.status == TaskStatus.READY:
            event_kind = TaskEventKind.UNBLOCKED
        if event_kind:
            payload: dict[str, object] = {"from": old_status.value, "to": new_status.value}
            if old_status == TaskStatus.BLOCKED and saved.status == TaskStatus.READY:
                payload["source"] = "manual"
            await store.append_event(
                task_id,
                event_kind,
                payload=payload,
            )

        if dispatcher:
            dispatcher.wake()
        return json.dumps({"status": "moved", "task": saved.to_dict()})

    @tool("kanban_delete_task")
    async def kanban_delete_task(task_id: str) -> str:
        """Delete a task from the board."""
        if not task_id:
            return json.dumps({"error": "task_id is required"})
        children_ids = await store.list_children(task_id)
        deleted = await store.delete_task(task_id)
        if deleted and children_ids:
            for child_id in children_ids:
                child = await store.get_task(child_id)
                if child is None or child.status != TaskStatus.BACKLOG:
                    continue
                if await store.are_dependencies_met(child_id):
                    child.status = TaskStatus.READY
                    await store.save_task(child)
                    await store.append_event(
                        child_id,
                        TaskEventKind.PROMOTED,
                        payload={"reason": "parent_deleted", "deleted_task_id": task_id},
                    )
        return json.dumps({"status": "deleted" if deleted else "not_found", "task_id": task_id})

    @tool("kanban_board_summary")
    async def kanban_board_summary(board_id: str = "") -> str:
        """Get board statistics including task counts by status."""
        resolved_board_id = board_id or default_board_id or ""
        if not resolved_board_id:
            return json.dumps({"error": "board_id is required"})
        board = await store.get_board(resolved_board_id)
        if board is None:
            return json.dumps({"error": f"Board {resolved_board_id} not found"})

        status_counts = await store.count_tasks_grouped(resolved_board_id)
        total = sum(status_counts.values())
        return json.dumps(
            {
                "board": board.to_dict(),
                "task_counts": status_counts,
                "total_tasks": total,
            }
        )

    @tool("kanban_link")
    async def kanban_link(task_id: str, dependency_task_id: str, action: str = "add") -> str:
        """Add or remove a DAG dependency edge (parent must complete before child).

        Args:
            task_id: Child task that depends on the parent.
            dependency_task_id: Parent task that must complete first.
            action: ``add`` to create the edge, ``remove`` to delete it.
        """
        if not task_id or not dependency_task_id:
            return json.dumps({"error": "task_id and dependency_task_id are required"})

        normalized_action = action.strip().lower()
        if normalized_action == "add":
            try:
                edge = await store.add_edge(dependency_task_id, task_id)
            except ValueError as exc:
                return json.dumps({"error": str(exc)})

            child = await store.get_task(task_id)
            if child and child.status == TaskStatus.READY:
                deps_met = await store.are_dependencies_met(task_id)
                if not deps_met:
                    child.status = TaskStatus.BACKLOG
                    await store.save_task(child)

            return json.dumps({"status": "dependency_added", "edge": edge.to_dict()})

        if normalized_action == "remove":
            removed = await store.remove_edge(dependency_task_id, task_id)
            if not removed:
                return json.dumps({"error": "Dependency not found"})

            child = await store.get_task(task_id)
            if child and child.status == TaskStatus.BACKLOG:
                deps_met = await store.are_dependencies_met(task_id)
                if deps_met:
                    child.status = TaskStatus.READY
                    await store.save_task(child)
                    await store.append_event(
                        task_id,
                        TaskEventKind.PROMOTED,
                        payload={"reason": "all_dependencies_met"},
                    )

            return json.dumps({"status": "dependency_removed", "task_id": task_id})

        return json.dumps({"error": f"Invalid action: {action}. Use 'add' or 'remove'."})

    return [
        kanban_add_task,
        kanban_list_tasks,
        kanban_update_task,
        kanban_move_task,
        kanban_delete_task,
        kanban_board_summary,
        kanban_link,
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _find_task_by_idempotency_key(
    store: KanbanStore,
    board_id: str,
    idempotency_key: str,
) -> KanbanTask | None:
    """Find an existing task with the given idempotency key on the board."""
    tasks = await store.list_tasks(board_id)
    for t in tasks:
        if t.metadata and t.metadata.get("idempotency_key") == idempotency_key:
            return t
    return None
