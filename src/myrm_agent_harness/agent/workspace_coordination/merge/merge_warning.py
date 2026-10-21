"""Per-turn workspace merge failure tracker for completion_status warning SSE.

[INPUT]
- None (self-contained ContextVar state)

[OUTPUT]
- reset_workspace_merge_warning: Clear per-turn merge error list at turn start
- record_workspace_merge_failure: Append merge error message for the current turn
- has_workspace_merge_warning: Query whether any merge failure occurred
- format_workspace_merge_failures: Structured payload for WORKSPACE_MERGE_FAILED SSE

[POS]
Per-turn tracker bridging batch_merge and immediate sync_back failures to post_run_events SSE.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_MAX_DISPLAY_ERRORS = 10

_merge_errors_var: ContextVar[list[str] | None] = ContextVar("workspace_merge_errors", default=None)


def _current_errors() -> list[str]:
    state = _merge_errors_var.get(None)
    return state if state is not None else []


def reset_workspace_merge_warning() -> None:
    """Reset per-turn merge warning state. Call at the start of each agent turn."""
    _merge_errors_var.set([])


def record_workspace_merge_failure(message: str) -> None:
    """Record a workspace merge failure message for the current turn."""
    text = message.strip()
    if not text:
        return
    errors = list(_current_errors())
    errors.append(text)
    _merge_errors_var.set(errors)


def has_workspace_merge_warning() -> bool:
    """Return True if any workspace merge failed during the current turn."""
    return bool(_current_errors())


def format_workspace_merge_failures() -> dict[str, Any] | None:
    """Format merge failures into a structured event payload."""
    errors = _current_errors()
    if not errors:
        return None

    items = [{"message": msg} for msg in errors[:_MAX_DISPLAY_ERRORS]]
    payload: dict[str, Any] = {
        "failed_count": len(errors),
        "errors": items,
    }
    if len(errors) > _MAX_DISPLAY_ERRORS:
        payload["truncated"] = len(errors) - _MAX_DISPLAY_ERRORS
    return payload
