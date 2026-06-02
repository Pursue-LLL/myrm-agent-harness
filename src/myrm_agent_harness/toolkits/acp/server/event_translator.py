"""AgentEvent → ACP SessionNotification translation.

Pure translation layer: maps myrm agent streaming events to ACP protocol
notifications. No business logic, no state management.

[INPUT]
- (none)

[OUTPUT]
- translate_agent_event: Translate a single agent streaming event to an ACP Sessio...

[POS]
AgentEvent → ACP SessionNotification translation.
"""

from __future__ import annotations

from acp import (
    session_notification,
    start_tool_call,
    update_agent_message_text,
    update_agent_thought_text,
    update_tool_call,
)
from acp.schema import SessionNotification, ToolCallStatus

_STATUS_MAP: dict[str, ToolCallStatus] = {
    "running": "in_progress",
    "completed": "completed",
    "error": "failed",
}

_TOOL_CALL_EVENTS = frozenset({"tool_start", "tasks_steps"})
_TEXT_EVENTS = frozenset({"message"})
_THINKING_EVENTS = frozenset({"reasoning"})
_SKIP_EVENTS = frozenset(
    {
        "message_end",
        "sources",
        "artifacts",
        "artifacts_ready",
        "artifact_content",
        "ui_update",
        "token_usage",
        "status",
        "steering",
        "tool_approval_request",
    }
)


def translate_agent_event(
    session_id: str,
    event: dict[str, object],
    active_tool_calls: set[str],
) -> SessionNotification | None:
    """Translate a single agent streaming event to an ACP SessionNotification.

    Args:
        session_id: ACP session ID for the notification envelope.
        event: Raw agent event dict from BaseAgent.run().
        active_tool_calls: Mutable set tracking tool_call_ids that have been
            started (to distinguish start vs progress).

    Returns:
        ACP SessionNotification, or None if the event should be skipped.
    """
    event_type = str(event.get("type", ""))

    if event_type in _SKIP_EVENTS:
        return None

    if event_type in _TEXT_EVENTS:
        return _translate_text(session_id, event)

    if event_type in _THINKING_EVENTS:
        return _translate_thinking(session_id, event)

    if event_type in _TOOL_CALL_EVENTS:
        return _translate_tool_call(session_id, event, active_tool_calls)

    return None


def _translate_text(session_id: str, event: dict[str, object]) -> SessionNotification | None:
    data = event.get("data")
    if not data or not isinstance(data, str):
        return None
    return session_notification(session_id, update_agent_message_text(data))


def _translate_thinking(session_id: str, event: dict[str, object]) -> SessionNotification | None:
    data = event.get("data")
    if not data or not isinstance(data, str):
        return None
    return session_notification(session_id, update_agent_thought_text(data))


def _translate_tool_call(
    session_id: str,
    event: dict[str, object],
    active_tool_calls: set[str],
) -> SessionNotification | None:
    tool_name = event.get("tool_name")
    if not tool_name or not isinstance(tool_name, str):
        return None

    step_key = str(event.get("step_key", tool_name))
    tool_call_id = f"tc_{step_key}"

    status_str = str(event.get("status", "running"))
    acp_status = _STATUS_MAP.get(status_str, "in_progress")

    if tool_call_id not in active_tool_calls:
        active_tool_calls.add(tool_call_id)
        update = start_tool_call(
            tool_call_id=tool_call_id,
            title=tool_name,
            status=acp_status,
        )
    else:
        update = update_tool_call(
            tool_call_id=tool_call_id,
            title=tool_name,
            status=acp_status,
        )

    return session_notification(session_id, update)
