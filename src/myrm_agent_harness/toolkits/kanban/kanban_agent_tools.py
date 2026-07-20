"""Agent tools for kanban task management — modular per-action design.

Tools are grouped by role (Worker / Orchestrator) for security and token efficiency.
Board CRUD and task field edits use REST/GUI only — not LLM tools.

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

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.toolkits.kanban.types import (
    BlockKind,
    KANBAN_SOURCE_CHAT_METADATA_KEY,
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

KanbanToolMode = Literal["worker", "orchestrator"]

KanbanTaskAttachFn = Callable[
    [str, Literal["path", "url"], str],
    Awaitable[dict[str, object]],
]

KANBAN_LIST_DEFAULT_LIMIT = 50
KANBAN_LIST_MAX_LIMIT = 200

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
    mode: KanbanToolMode = "orchestrator",
    default_board_id: str | None = None,
    agent_id: str | None = None,
    current_task_id: str | None = None,
    attach_task_file: KanbanTaskAttachFn | None = None,
    source_chat_id: str | None = None,
) -> list[BaseTool]:
    """Create kanban tools scoped by role.

    Modes:
        worker: 6 tools (show/complete/block/heartbeat/comment/attach).
        orchestrator: 3 tools (add_task/list_tasks/unblock).

    When mode='worker', tools auto-bind to ``current_task_id`` and enforce
    ownership — the agent cannot operate on other tasks (except comments,
    which are intentionally unrestricted for cross-task coordination).
    """
    if mode == "worker":
        return _build_worker_tools(
            store,
            dispatcher,
            current_task_id=current_task_id,
            agent_id=agent_id,
            attach_task_file=attach_task_file,
        )
    return _build_orchestrator_tools(
        store,
        dispatcher,
        default_board_id=default_board_id,
        agent_id=agent_id,
        source_chat_id=source_chat_id,
    )


# ---------------------------------------------------------------------------
# Worker tools — minimal surface, ownership-enforced
# ---------------------------------------------------------------------------


def _build_worker_tools(
    store: KanbanStore,
    dispatcher: KanbanDispatcher | None,
    *,
    current_task_id: str | None = None,
    agent_id: str | None = None,
    attach_task_file: KanbanTaskAttachFn | None = None,
) -> list[BaseTool]:
    """Build worker-scoped tools (6 tools)."""

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

    @tool("kanban_attach")
    async def kanban_attach(source: Literal["path", "url"], value: str, task_id: str = "") -> str:
        """Attach a sandbox file path or HTTPS URL to your task for downstream workers.

        Args:
            source: ``path`` for a workspace file, ``url`` for a remote HTTPS resource.
            value: File path or URL (required).
            task_id: Defaults to your assigned task.
        """
        if not value or not value.strip():
            return json.dumps({"error": "value is required"})
        if attach_task_file is None:
            return json.dumps({"error": "Task attachments are not configured for this agent run"})
        resolved_id = task_id or current_task_id or ""
        if not resolved_id:
            return json.dumps({"error": "task_id is required"})
        task, err = await _validate_task_ownership(resolved_id)
        if err:
            return json.dumps({"error": err})
        assert task is not None

        try:
            payload = await attach_task_file(resolved_id, source, value.strip())
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        except Exception:
            logger.exception("kanban_attach failed for task %s", resolved_id[:8])
            return json.dumps({"error": "Failed to attach file to task"})

        return json.dumps({"status": "attached", "task_id": resolved_id, **payload})

    return [kanban_show, kanban_complete, kanban_block, kanban_heartbeat, kanban_comment, kanban_attach]


# ---------------------------------------------------------------------------
# Orchestrator tools — task lifecycle management
# ---------------------------------------------------------------------------


def _build_orchestrator_tools(
    store: KanbanStore,
    dispatcher: KanbanDispatcher | None,
    *,
    default_board_id: str | None = None,
    agent_id: str | None = None,
    source_chat_id: str | None = None,
) -> list[BaseTool]:
    """Build orchestrator-scoped tools (3 tools)."""

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

        if source_chat_id:
            if task.metadata is None:
                task.metadata = {}
            task.metadata[KANBAN_SOURCE_CHAT_METADATA_KEY] = source_chat_id

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
        limit: int = KANBAN_LIST_DEFAULT_LIMIT,
        include_stats: bool = False,
    ) -> str:
        """List tasks on a board, optionally filtered by status or agent.

        When ``task_id`` is set, returns that single task (read-only) with
        parent/child dependency IDs and ``dependencies_met`` status.

        Set ``include_stats=true`` on board listings to include per-status counts.

        Board listings default to 50 tasks (max 200). When truncated, the
        response includes ``truncated: true`` — use ``status_filter`` or raise
        ``limit`` to see more.
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

        if limit < 1:
            return json.dumps({"error": "limit must be >= 1"})
        if limit > KANBAN_LIST_MAX_LIMIT:
            return json.dumps({"error": f"limit must be <= {KANBAN_LIST_MAX_LIMIT}"})

        status: TaskStatus | None = None
        if status_filter:
            try:
                status = TaskStatus(status_filter)
            except ValueError:
                return json.dumps({"error": f"Invalid status_filter: {status_filter}"})

        rows = await store.list_tasks(
            resolved_board_id,
            status=status,
            agent_id=agent_id_filter or None,
            source_chat_id=source_chat_id,
            limit=limit + 1,
        )
        truncated = len(rows) > limit
        tasks = rows[:limit]
        payload: dict[str, object] = {
            "tasks": [t.to_dict() for t in tasks],
            "count": len(tasks),
            "limit": limit,
            "truncated": truncated,
        }
        if include_stats:
            board = await store.get_board(resolved_board_id)
            if board is None:
                return json.dumps({"error": f"Board {resolved_board_id} not found"})
            status_counts = await store.count_tasks_grouped(resolved_board_id)
            payload["board"] = board.to_dict()
            payload["task_counts"] = status_counts
            payload["total_tasks"] = sum(status_counts.values())
        return json.dumps(payload)

    @tool("kanban_unblock")
    async def kanban_unblock(task_id: str, reason: str = "") -> str:
        """Unblock a BLOCKED task after human approval or external resolution.

        Clears block metadata and sets READY when dependencies are met. When
        dependencies are still open, the task moves to BACKLOG and the response
        uses ``status: waiting_on_dependencies`` (check ``dependencies_met``).

        For timed blocks, prefer dispatcher auto-unblock when ``scheduled_until`` is set.
        """
        if not task_id:
            return json.dumps({"error": "task_id is required"})

        task = await store.get_task(task_id)
        if task is None:
            return json.dumps({"error": f"Task {task_id} not found"})
        if task.status != TaskStatus.BLOCKED:
            return json.dumps({"error": f"Task is not blocked (status={task.status.value})"})

        old_status = task.status
        task.status = TaskStatus.READY
        task.blocked_reason = None
        task.block_kind = None
        task.scheduled_until = None
        task.consecutive_failures = 0
        task.error = ""
        if not await store.are_dependencies_met(task_id):
            task.status = TaskStatus.BACKLOG

        saved = await store.save_task(task)
        dependencies_met = await store.are_dependencies_met(task_id)
        outcome = "unblocked" if saved.status == TaskStatus.READY else "waiting_on_dependencies"
        event_payload: dict[str, object] = {
            "from": old_status.value,
            "to": saved.status.value,
            "source": "orchestrator",
            "dependencies_met": dependencies_met,
            "outcome": outcome,
        }
        if reason.strip():
            event_payload["reason"] = reason.strip()
        await store.append_event(task_id, TaskEventKind.UNBLOCKED, payload=event_payload)

        if dispatcher:
            dispatcher.wake()

        return json.dumps(
            {
                "status": outcome,
                "dependencies_met": dependencies_met,
                "task": saved.to_dict(),
            }
        )

    return [kanban_add_task, kanban_list_tasks, kanban_unblock]


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
