"""Agent tools for kanban task management — modular per-action design.

Tools are grouped by role (Worker / Orchestrator) for security and token efficiency.
Board CRUD and task field edits use REST/GUI only — not LLM tools.

[INPUT]
- .types::TaskStatus, TaskPriority, TaskEventKind (POS: Kanban domain types.)
- .protocols::KanbanStore (POS: Protocols for the kanban toolkit.)
- .dispatcher::KanbanDispatcher (POS: Event-driven multi-task scheduler.)
- ._worker_tools::build_worker_tools (POS: Worker-scoped kanban LLM tools.)
- ._orchestrator_tools::build_orchestrator_tools (POS: Orchestrator-scoped kanban LLM tools.)

[OUTPUT]
- create_kanban_tools: Factory that returns role-scoped tool sets.
- get_worker_lifecycle_guidance: Pure function returning lifecycle guidance text for worker system prompts.
- KanbanToolMode: Literal type for role selection.
- KanbanTaskAttachFn: Type alias for task file attachment callback.
- KANBAN_LIST_DEFAULT_LIMIT, KANBAN_LIST_MAX_LIMIT: Pagination constants.
- find_task_by_idempotency_key: Idempotency check helper for orchestrator tools.

[POS]
Facade for kanban agent tools — routes to worker/orchestrator sub-modules and exposes shared helpers.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
    from myrm_agent_harness.toolkits.kanban.protocols import KanbanStore
    from myrm_agent_harness.toolkits.kanban.types import KanbanTask

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
        "3. If you see 'Prior attempts' or 'Review history' in your context, read the "
        "outcome/error and rejection reasons carefully and change your approach — do not "
        "repeat the same failing strategy.\n"
        "4. Write a clear summary (1-3 sentences) in kanban_complete describing what you "
        "accomplished. Include structured metadata JSON (changed_files, verification commands, "
        "etc.) — it will be automatically injected into downstream workers' context.\n"
        "5. Use kanban_comment(task_id, body) to share findings, flag issues, or coordinate "
        "with sibling tasks. Comments are visible to other workers via their context.\n"
        "6. If you produced files (code, documents, images, etc.), attach them with "
        "kanban_attach(source='path', value=<relative path or /workspace/... path>) "
        "before completing, so downstream workers and the user can access the deliverables.\n"
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
        orchestrator: 6 tools (add_task/list_tasks/unblock/cancel_task/retry_task/revise_plan).

    When mode='worker', tools auto-bind to ``current_task_id`` and enforce
    ownership — the agent cannot operate on other tasks (except comments,
    which are intentionally unrestricted for cross-task coordination).
    """
    if mode == "worker":
        from myrm_agent_harness.toolkits.kanban._worker_tools import (
            build_worker_tools,
        )

        return build_worker_tools(
            store,
            dispatcher,
            current_task_id=current_task_id,
            agent_id=agent_id,
            attach_task_file=attach_task_file,
        )

    from myrm_agent_harness.toolkits.kanban._orchestrator_tools import (
        build_orchestrator_tools,
    )

    return build_orchestrator_tools(
        store,
        dispatcher,
        default_board_id=default_board_id,
        agent_id=agent_id,
        source_chat_id=source_chat_id,
    )


async def find_task_by_idempotency_key(
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
