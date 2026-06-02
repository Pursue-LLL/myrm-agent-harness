"""Session → RunnableConfig registry for PTC ``tools.notify`` dispatch.

``tools.notify`` runs inside the IPC handler task, which has its own asyncio
context and therefore cannot read the caller's ``var_child_runnable_config``
ContextVar. This tiny registry lets the bash tool publish its RunnableConfig
under the session_id while a code execution is in flight, so the IPC handler
can look it up by session_id (carried in :class:`IPCCallContext`) and route
the notify event into LangGraph's custom stream.

Lifetime is strictly bounded by the tool call: ``bash_tool`` registers on
entry and unregisters in ``finally`` to keep the registry small and to avoid
leaking RunnableConfig references between sessions.

[INPUT]
- (none)

[OUTPUT]
- register_session_config: Make a RunnableConfig discoverable by session_id.
- pop_session_config: Drop the registration; idempotent.
- get_session_config: Lookup the registered RunnableConfig (None if absent).
- session_scope: Async context manager wrapping register + pop_session_config.

[POS]
Backbone for ``tools.notify`` cross-process delivery. Pure framework concern;
business layer is unaffected.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig


_registry: dict[str, RunnableConfig] = {}
_lock = Lock()


def register_session_config(session_id: str, config: RunnableConfig) -> None:
    """Publish *config* under *session_id* (overwrites any prior entry)."""
    with _lock:
        _registry[session_id] = config


def pop_session_config(session_id: str) -> None:
    """Forget the registration for *session_id* (no-op when absent)."""
    with _lock:
        _registry.pop(session_id, None)


def get_session_config(session_id: str) -> RunnableConfig | None:
    """Return the RunnableConfig registered for *session_id*, or None."""
    with _lock:
        return _registry.get(session_id)


@asynccontextmanager
async def session_scope(
    session_id: str | None, config: RunnableConfig | None
) -> AsyncIterator[None]:
    """Register ``config`` for the duration of an async block.

    Both arguments are tolerated as None so call sites do not need to guard
    against optional contexts (the registry simply skips no-op pairs).
    """
    if not session_id or config is None:
        yield
        return
    register_session_config(session_id, config)
    try:
        yield
    finally:
        pop_session_config(session_id)


__all__ = [
    "get_session_config",
    "pop_session_config",
    "register_session_config",
    "session_scope",
]
