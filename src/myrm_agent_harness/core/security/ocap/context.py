"""ContextVar management for active capability handle during agent execution.

[INPUT]
- .types::CapabilityHandle
- contextvars::ContextVar

[OUTPUT]
- get_current_capability: Retrieve active capability handle in current async task
- capability_scope: Context manager for scoped capability binding

[POS]
Binds the capability handle to the current asyncio task. Tasks created inside a binding copy it, so a
child run (including a detached one) keeps the handle it was spawned under after the binding exits.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.core.security.ocap.types import CapabilityHandle

_ACTIVE_CAPABILITY_VAR: ContextVar[CapabilityHandle | None] = ContextVar(
    "_ACTIVE_CAPABILITY_VAR",
    default=None,
)


def get_current_capability() -> CapabilityHandle | None:
    """Retrieve the currently active CapabilityHandle in the execution context."""
    return _ACTIVE_CAPABILITY_VAR.get()


@contextmanager
def capability_scope(handle: CapabilityHandle | None) -> Iterator[None]:
    """Execute block within the context of a specific capability handle."""
    token = _ACTIVE_CAPABILITY_VAR.set(handle)
    try:
        yield
    finally:
        _ACTIVE_CAPABILITY_VAR.reset(token)
