"""Session-scoped deferred tool activation for background bash spawn.

When ``bash_code_execute_tool`` spawns a background job, ``bash_process_tool``
must appear in the model's bind_tools on subsequent turns without requiring
``discover_capability``. Activations are keyed by ``session_id`` and merged
into ``DeferredToolMiddleware`` alongside discover AutoMount names.

[INPUT]
- None (in-process session → tool-name set)

[OUTPUT]
- activate_session_deferred_tool: Record a deferred tool for a chat session
- get_session_deferred_tool_names: Read activations for middleware AutoMount
- clear_session_deferred_tools: Drop activations (e.g. session cleanup)

[POS]
PTC-adjacent runtime helper. Bash-tool package only; thread-safe in-process store.
"""

from __future__ import annotations

from threading import Lock

_lock = Lock()
_session_activations: dict[str, set[str]] = {}


def activate_session_deferred_tool(session_id: str, tool_name: str) -> None:
    """Mark ``tool_name`` as AutoMount-eligible for ``session_id``."""
    if not session_id or not tool_name:
        return
    with _lock:
        bucket = _session_activations.setdefault(session_id, set())
        bucket.add(tool_name)


def get_session_deferred_tool_names(session_id: str) -> frozenset[str]:
    """Return deferred tool names activated for ``session_id`` (empty if none)."""
    if not session_id:
        return frozenset()
    with _lock:
        return frozenset(_session_activations.get(session_id, ()))


def clear_session_deferred_tools(session_id: str) -> None:
    """Remove all deferred activations for ``session_id``."""
    if not session_id:
        return
    with _lock:
        _session_activations.pop(session_id, None)


def reset_deferred_activation_for_tests() -> None:
    """Clear all activations (tests only)."""
    with _lock:
        _session_activations.clear()
