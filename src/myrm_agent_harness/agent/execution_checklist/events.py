"""SSE tasks_steps emission for execution checklist UI.

[INPUT]
- execution_checklist.state::ExecutionChecklistState, ChecklistItem (POS: checklist models)

[OUTPUT]
- emit_checklist_events(): dispatch tasks_steps custom events for ProgressSteps UI

[POS]
Bridges checklist state mutations to LangChain custom SSE events (`is_plan=false`).
"""

from __future__ import annotations

import logging

from langchain_core.callbacks import dispatch_custom_event

from myrm_agent_harness.agent.execution_checklist.state import (
    ExecutionChecklistState,
    incomplete_checklist_items,
)

logger = logging.getLogger(__name__)

CHECKLIST_ROOT_KEY = "checklist_root"


def build_checklist_sse_events(
    state: ExecutionChecklistState,
    *,
    message_id: str = "",
) -> list[dict[str, object]]:
    """Build tasks_steps payloads for checklist UI (stream-safe, no LangChain callback)."""
    completed = sum(1 for i in state.items if i.status == "completed")
    total = len(state.items)
    summary = f"Execution checklist ({completed}/{total} done)" if total else "Execution checklist"

    events: list[dict[str, object]] = [
        {
            "type": "tasks_steps",
            "step_key": CHECKLIST_ROOT_KEY,
            "is_plan": False,
            "status": "in_progress" if incomplete_checklist_items(state) else "success",
            "data": [{"text": summary}],
            **({"messageId": message_id} if message_id else {}),
        }
    ]

    for item in state.items:
        events.append(
            {
                "type": "tasks_steps",
                "step_key": f"checklist_{item.id}",
                "parent_step_key": CHECKLIST_ROOT_KEY,
                "is_plan": False,
                "status": _map_status(item.status),
                "data": [{"text": item.content}],
                **({"messageId": message_id} if message_id else {}),
            }
        )
    return events


def emit_checklist_events(state: ExecutionChecklistState) -> None:
    """Emit tasks_steps events so ProgressSteps renders checklist progress."""
    try:
        for payload in build_checklist_sse_events(state):
            dispatch_custom_event("tasks_steps", {k: v for k, v in payload.items() if k not in {"type", "messageId"}})
    except Exception as exc:
        logger.warning("Failed to emit checklist events: %s", exc)


def _map_status(status: str) -> str:
    if status == "in_progress":
        return "running"
    if status == "completed":
        return "success"
    if status == "cancelled":
        return "skipped"
    return "pending"
