"""SSE tasks_steps emission for execution checklist UI."""

from __future__ import annotations

import logging

from langchain_core.callbacks import dispatch_custom_event

from myrm_agent_harness.agent.execution_checklist.state import (
    ChecklistItem,
    ExecutionChecklistState,
    incomplete_checklist_items,
)

logger = logging.getLogger(__name__)

CHECKLIST_ROOT_KEY = "checklist_root"


def emit_checklist_events(state: ExecutionChecklistState) -> None:
    """Emit tasks_steps events so ProgressSteps renders checklist progress."""
    try:
        completed = sum(1 for i in state.items if i.status == "completed")
        total = len(state.items)
        summary = f"Execution checklist ({completed}/{total} done)" if total else "Execution checklist"

        dispatch_custom_event(
            "tasks_steps",
            {
                "step_key": CHECKLIST_ROOT_KEY,
                "is_plan": False,
                "status": "in_progress" if incomplete_checklist_items(state) else "success",
                "data": [{"text": summary}],
            },
        )

        for item in state.items:
            _emit_item_event(item)
    except Exception as exc:
        logger.warning("Failed to emit checklist events: %s", exc)


def _emit_item_event(item: ChecklistItem) -> None:
    ui_status = _map_status(item.status)
    dispatch_custom_event(
        "tasks_steps",
        {
            "step_key": f"checklist_{item.id}",
            "parent_step_key": CHECKLIST_ROOT_KEY,
            "is_plan": False,
            "status": ui_status,
            "data": [{"text": item.content}],
        },
    )


def _map_status(status: str) -> str:
    if status == "in_progress":
        return "running"
    if status == "completed":
        return "success"
    if status == "cancelled":
        return "skipped"
    return "pending"
