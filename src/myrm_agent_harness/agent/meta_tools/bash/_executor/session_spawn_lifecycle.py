"""Session-scoped bash spawn lifecycle tracking.

When ``bash_code_execute_tool`` spawns a background job, the session records
``bash_process_tool`` so ``BackgroundProcessRegistry`` can auto-clear spawn
markers when all shell jobs exit.

[INPUT]
- None (in-process session → tool-name set)

[OUTPUT]
- activate_session_spawn_tool: Record spawn for session lifecycle cleanup
- get_session_spawn_tool_names: Read session spawn markers
- clear_session_spawn_tools: Drop markers (session cleanup)

[POS]
Bash-tool runtime helper. Thread-safe in-process store for spawn/cleanup coordination.
"""

from __future__ import annotations

from threading import Lock

_lock = Lock()
_session_activations: dict[str, set[str]] = {}


def activate_session_spawn_tool(session_id: str, tool_name: str) -> None:
    """Record ``tool_name`` spawn for ``session_id`` (auto-clear when jobs exit)."""
    if not session_id or not tool_name:
        return
    with _lock:
        bucket = _session_activations.setdefault(session_id, set())
        bucket.add(tool_name)


def get_session_spawn_tool_names(session_id: str) -> frozenset[str]:
    """Return spawn-marked tool names for ``session_id`` (empty if none)."""
    if not session_id:
        return frozenset()
    with _lock:
        return frozenset(_session_activations.get(session_id, ()))


def clear_session_spawn_tools(session_id: str) -> None:
    """Remove all spawn markers for ``session_id``."""
    if not session_id:
        return
    with _lock:
        _session_activations.pop(session_id, None)


def reset_spawn_lifecycle_for_tests() -> None:
    """Clear all activations (tests only)."""
    with _lock:
        _session_activations.clear()


__all__ = [
    "activate_session_spawn_tool",
    "clear_session_spawn_tools",
    "get_session_spawn_tool_names",
    "reset_spawn_lifecycle_for_tests",
]
