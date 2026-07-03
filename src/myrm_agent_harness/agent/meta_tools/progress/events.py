"""Progress SSE helpers — emit `tasks_steps` for ProgressSteps UI.

[INPUT]
- progress.schemas::TodoItem, TodoStatus, TodoStore (POS: todo models)
- langchain_core.callbacks.manager::dispatch_custom_event (POS: SSE bridge)

[OUTPUT]
- emit_todo_progress_events: Dispatch tasks_steps custom events for UI

[POS]
Emits LangGraph custom events consumed by server SSE → ProgressSteps UI.
"""

from __future__ import annotations

import logging

from langchain_core.callbacks.manager import dispatch_custom_event

from myrm_agent_harness.agent.meta_tools.progress.schemas import TodoItem, TodoStatus, TodoStore

logger = logging.getLogger(__name__)

PROGRESS_ROOT_STEP_KEY = "progress_root"


def _ui_status(status: TodoStatus) -> str:
    if status == TodoStatus.IN_PROGRESS:
        return "running"
    if status == TodoStatus.COMPLETED:
        return "success"
    if status == TodoStatus.CANCELLED:
        return "skipped"
    return "pending"


def emit_todo_progress_events(store: TodoStore) -> None:
    """Emit root + child steps so chat ProgressSteps can render a tree."""
    try:
        root_label = store.goal or "Task progress"
        dispatch_custom_event(
            "tasks_steps",
            {
                "step_key": PROGRESS_ROOT_STEP_KEY,
                "is_plan": True,
                "status": "in_progress",
                "data": [{"text": root_label}],
            },
        )

        for item in store.todos:
            _emit_todo_step(item)
    except Exception as exc:
        logger.warning("Failed to emit todo progress events: %s", exc)


def _emit_todo_step(item: TodoItem) -> None:
    dispatch_custom_event(
        "tasks_steps",
        {
            "step_key": f"todo_step_{item.id}",
            "parent_step_key": PROGRESS_ROOT_STEP_KEY,
            "is_plan": True,
            "status": _ui_status(item.status),
            "data": [{"text": item.content}],
        },
    )
