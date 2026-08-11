"""Worker-scoped kanban tools — minimal surface, ownership-enforced.

6 tools: show, complete, block, heartbeat, comment, attach.
Worker tools auto-bind to ``current_task_id`` and enforce ownership —
the agent cannot operate on other tasks (except comments, which are
intentionally unrestricted for cross-task coordination).

[INPUT]
- .types::TaskStatus, TaskEventKind, BlockKind, KanbanTask, KANBAN_COMPLETION_INTENT_KEY (POS: Kanban domain types.)
- .protocols::KanbanStore (POS: Protocols for the kanban toolkit.)
- .dispatcher::KanbanDispatcher (POS: Event-driven multi-task scheduler.)
- .kanban_agent_tools::_parse_until, KanbanTaskAttachFn (POS: Facade and shared helpers.)

[OUTPUT]
- build_worker_tools: Factory that returns 6 worker-scoped tools.

[POS]
Worker-scoped kanban LLM tools (6 tools) with ownership enforcement.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.toolkits.kanban.kanban_agent_tools import (
    KanbanTaskAttachFn,
    _parse_until,
)
from myrm_agent_harness.toolkits.kanban.types import (
    KANBAN_COMPLETION_INTENT_KEY,
    BlockKind,
    KanbanTask,
    TaskEventKind,
    TaskStatus,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
    from myrm_agent_harness.toolkits.kanban.protocols import KanbanStore

logger = get_agent_logger(__name__)


def build_worker_tools(
    store: KanbanStore,
    dispatcher: KanbanDispatcher | None,
    *,
    current_task_id: str | None = None,
    agent_id: str | None = None,
    attach_task_file: KanbanTaskAttachFn | None = None,
) -> list[BaseTool]:
    """Build worker-scoped tools (6 tools)."""

    async def _validate_task_ownership(
        task_id: str,
    ) -> tuple[KanbanTask | None, str | None]:
        """Validate task exists and worker has ownership."""
        if current_task_id and task_id != current_task_id:
            return (
                None,
                f"Permission denied: you can only operate on your assigned task ({current_task_id})",
            )
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
    async def kanban_complete(
        summary: str, metadata: str = "", task_id: str = ""
    ) -> str:
        """Mark your task as completed with a structured handoff.

        Args:
            summary: 1-3 sentences describing what was accomplished (required).
            metadata: JSON string with machine-readable facts auto-injected into
                downstream workers' context, e.g. '{"changed_files": ["x.py"], "tests_run": 5}'.
            task_id: Defaults to your assigned task.
        """
        if not summary:
            return json.dumps(
                {"error": "summary is required — describe what was accomplished"}
            )
        resolved_id = task_id or current_task_id or ""
        if not resolved_id:
            return json.dumps({"error": "task_id is required"})
        task, err = await _validate_task_ownership(resolved_id)
        if err:
            return json.dumps({"error": err})
        assert task is not None

        if task.is_terminal:
            return json.dumps(
                {"error": f"Task already in terminal state ({task.status})"}
            )

        parsed_metadata: dict[str, object] | None = None
        if metadata:
            try:
                parsed_metadata = json.loads(metadata)
                if not isinstance(parsed_metadata, dict):
                    return json.dumps({"error": "metadata must be a JSON object"})
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"Invalid metadata JSON: {e}"})

        old_status = task.status
        task.status = TaskStatus.RUNNING
        task.progress_note = None
        task.result = summary
        merged_metadata: dict[str, object] = {
            **task.metadata,
            KANBAN_COMPLETION_INTENT_KEY: True,
        }
        if parsed_metadata:
            merged_metadata["handoff"] = parsed_metadata
        task.metadata = merged_metadata
        saved = await store.save_task(task)

        await store.append_event(
            resolved_id,
            TaskEventKind.COMPLETION_REQUESTED,
            payload={"from": old_status.value, "summary": summary},
        )

        if dispatcher:
            dispatcher.wake()

        return json.dumps({"status": "completion_requested", "task": saved.to_dict()})

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
            return json.dumps(
                {"error": f"Task already in terminal state ({task.status})"}
            )

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
                **(
                    {"scheduled_until": scheduled_until.isoformat()}
                    if scheduled_until
                    else {}
                ),
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
    async def kanban_attach(
        source: Literal["path", "url"], value: str, task_id: str = ""
    ) -> str:
        """Attach a sandbox file path or HTTPS URL to your task for downstream workers.

        Args:
            source: ``path`` for a workspace file, ``url`` for a remote HTTPS resource.
            value: File path (relative to your working directory, or a /workspace/...
                path) or HTTPS URL (required).
            task_id: Defaults to your assigned task.
        """
        if not value or not value.strip():
            return json.dumps({"error": "value is required"})
        if attach_task_file is None:
            return json.dumps(
                {"error": "Task attachments are not configured for this agent run"}
            )
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

    return [
        kanban_show,
        kanban_complete,
        kanban_block,
        kanban_heartbeat,
        kanban_comment,
        kanban_attach,
    ]
