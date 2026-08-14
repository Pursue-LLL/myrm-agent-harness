"""Orchestrator-scoped kanban tools — task lifecycle management.

5 tools: add_task, list_tasks, unblock, cancel_task, retry_task.
Board/task field edits and delete use server REST/GUI only — not LLM tools.

[INPUT]
- .types::TaskStatus, TaskPriority, TaskEventKind, TaskRunOutcome, KanbanTask, KANBAN_SOURCE_CHAT_METADATA_KEY (POS: Kanban domain types.)
- .protocols::KanbanStore (POS: Protocols for the kanban toolkit.)
- .dispatcher::KanbanDispatcher (POS: Event-driven multi-task scheduler.)
- .kanban_agent_tools::KANBAN_LIST_DEFAULT_LIMIT, KANBAN_LIST_MAX_LIMIT, find_task_by_idempotency_key (POS: Facade and shared helpers.)

[OUTPUT]
- build_orchestrator_tools: Factory that returns 5 orchestrator-scoped tools.

[POS]
Orchestrator-scoped kanban LLM tools (5 tools) for task lifecycle management.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.toolkits.kanban.kanban_agent_tools import (
    KANBAN_LIST_DEFAULT_LIMIT,
    KANBAN_LIST_MAX_LIMIT,
    find_task_by_idempotency_key,
)
from myrm_agent_harness.toolkits.kanban.types import (
    KANBAN_SOURCE_CHAT_METADATA_KEY,
    KanbanTask,
    TaskEventKind,
    TaskPriority,
    TaskRunOutcome,
    TaskStatus,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
    from myrm_agent_harness.toolkits.kanban.protocols import KanbanStore

logger = get_agent_logger(__name__)


def build_orchestrator_tools(
    store: KanbanStore,
    dispatcher: KanbanDispatcher | None,
    *,
    default_board_id: str | None = None,
    agent_id: str | None = None,
    source_chat_id: str | None = None,
) -> list[BaseTool]:
    """Build orchestrator-scoped tools (5 tools)."""

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
        model: str = "",
        require_approval: bool = False,
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
            skills: Comma-separated extra skills for this task only (e.g. "translation,security-audit").
            model: Per-task model override in 'provider/model' form (e.g. "anthropic/claude-sonnet-4"). Empty = inherit the agent profile default.
            require_approval: When true, the task lands in in_review after verification and waits for a human approve/reject before completion.
        """
        resolved_board_id = board_id or default_board_id or ""
        if not resolved_board_id:
            return json.dumps({"error": "board_id is required"})
        if not title:
            return json.dumps({"error": "title is required"})

        if idempotency_key:
            existing = await find_task_by_idempotency_key(
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
            max_runtime_seconds=(max_runtime_seconds if max_runtime_seconds > 0 else None),
            max_retries=max_retries,
            extra_skill_ids=parsed_skills,
            model_override=model or None,
            require_approval=require_approval,
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
                    logger.warning(
                        "Skipped dependency %s -> %s (parent not found)",
                        parent_id,
                        saved.task_id,
                    )
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
            dispatcher.emit("task_created", saved)
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
        """List tasks on a board, or read a single task by ``task_id``.

        Filters: status_filter, agent_id_filter. Set include_stats=true for per-status counts.
        Default 50 tasks (max 200); ``truncated: true`` when capped.
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

        board = await store.get_board(task.board_id)
        block_limit = board.settings.block_recurrence_limit if board else 2

        old_status = task.status
        if task.block_cycle_count >= block_limit:
            task.status = TaskStatus.TRIAGE
            task.blocked_reason = None
            task.block_kind = None
            task.scheduled_until = None
            task.consecutive_failures = 0
            task.error = f"Escalated to triage after {task.block_cycle_count} block cycles (limit {block_limit})"
            saved = await store.save_task(task)
            await store.append_event(
                task_id,
                TaskEventKind.UNBLOCKED,
                payload={
                    "from": old_status.value,
                    "to": TaskStatus.TRIAGE.value,
                    "source": "orchestrator",
                    "outcome": "escalated_to_triage",
                    "block_cycle_count": task.block_cycle_count,
                    **({"reason": reason.strip()} if reason.strip() else {}),
                },
            )
            if dispatcher:
                dispatcher.emit("task_escalated", saved)
                dispatcher.wake()
            return json.dumps(
                {
                    "status": "escalated_to_triage",
                    "block_cycle_count": task.block_cycle_count,
                    "task": saved.to_dict(),
                }
            )

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
            dispatcher.emit("task_unblocked", saved)
            dispatcher.wake()

        return json.dumps(
            {
                "status": outcome,
                "dependencies_met": dependencies_met,
                "task": saved.to_dict(),
            }
        )

    @tool("kanban_cancel_task")
    async def kanban_cancel_task(task_id: str, reason: str = "") -> str:
        """Cancel a task by moving it to ARCHIVED.

        Cancels READY, BACKLOG, BLOCKED, or FAILED tasks immediately.
        For RUNNING tasks, also stops the worker execution.
        Cannot cancel COMPLETED, ARCHIVED, or tasks awaiting human review.

        Args:
            task_id: ID of the task to cancel (required).
            reason: Why this task is being cancelled.
        """
        if not task_id:
            return json.dumps({"error": "task_id is required"})

        task = await store.get_task(task_id)
        if task is None:
            return json.dumps({"error": f"Task {task_id} not found"})

        if task.status in (
            TaskStatus.COMPLETED,
            TaskStatus.ARCHIVED,
            TaskStatus.IN_REVIEW,
        ):
            return json.dumps({"error": f"Cannot cancel task in {task.status.value} state"})

        was_running = task.status == TaskStatus.RUNNING
        if was_running and dispatcher:
            await dispatcher.cancel_execution(task_id)

        old_status = task.status
        task.status = TaskStatus.ARCHIVED
        task.completed_at = datetime.now(UTC)
        saved = await store.save_task(task)

        if was_running:
            runs = await store.list_runs(task_id)
            for r in reversed(runs):
                if not r.is_finished:
                    await store.complete_run(
                        r.run_id,
                        TaskRunOutcome.RECLAIMED,
                        error="Cancelled by orchestrator",
                    )
                    break

        promoted_ids: list[str] = []
        for child_id in await store.list_children(task_id):
            child = await store.get_task(child_id)
            if child is None or child.status != TaskStatus.BACKLOG:
                continue
            if await store.are_dependencies_met(child_id):
                child.status = TaskStatus.READY
                await store.save_task(child)
                await store.append_event(
                    child_id,
                    TaskEventKind.PROMOTED,
                    payload={"trigger_task_id": task_id},
                )
                promoted_ids.append(child_id)

        event_payload: dict[str, object] = {
            "from": old_status.value,
            "source": "orchestrator",
            "was_running": was_running,
        }
        if reason.strip():
            event_payload["reason"] = reason.strip()
        await store.append_event(task_id, TaskEventKind.ARCHIVED, payload=event_payload)

        if dispatcher:
            dispatcher.emit("task_archived", saved)
            dispatcher.wake()

        result_payload: dict[str, object] = {
            "status": "cancelled",
            "was_running": was_running,
            "task": saved.to_dict(),
        }
        if promoted_ids:
            result_payload["promoted_children"] = promoted_ids

        return json.dumps(result_payload)

    @tool("kanban_retry_task")
    async def kanban_retry_task(
        task_id: str,
        description: str = "",
        reason: str = "",
    ) -> str:
        """Retry a FAILED task by resetting it to READY for re-execution.

        Clears failure counters and error state. Optionally update the
        description to give the worker better instructions.

        Args:
            task_id: ID of the failed task to retry (required).
            description: New description to replace the old one (optional).
            reason: Why this task is being retried.
        """
        if not task_id:
            return json.dumps({"error": "task_id is required"})

        task = await store.get_task(task_id)
        if task is None:
            return json.dumps({"error": f"Task {task_id} not found"})

        if task.status != TaskStatus.FAILED:
            return json.dumps({"error": f"Only FAILED tasks can be retried (current: {task.status.value})"})

        task.status = TaskStatus.READY
        task.error = ""
        task.retry_count = 0
        task.consecutive_failures = 0
        task.block_cycle_count = 0
        task.completed_at = None
        task.progress_note = None
        if description.strip():
            task.description = description.strip()

        saved = await store.save_task(task)

        event_payload: dict[str, object] = {
            "from": TaskStatus.FAILED.value,
            "to": TaskStatus.READY.value,
            "source": "orchestrator",
        }
        if reason.strip():
            event_payload["reason"] = reason.strip()
        await store.append_event(task_id, TaskEventKind.RETRYING, payload=event_payload)

        if dispatcher:
            dispatcher.emit("task_retrying", saved)
            dispatcher.wake()

        return json.dumps({"status": "retried", "task": saved.to_dict()})

    return [
        kanban_add_task,
        kanban_list_tasks,
        kanban_unblock,
        kanban_cancel_task,
        kanban_retry_task,
    ]
