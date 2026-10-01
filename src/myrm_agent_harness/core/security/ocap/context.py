"""ContextVar management for active capability handle during agent execution.

[INPUT]
- .types::CapabilityHandle
- contextvars::ContextVar

[OUTPUT]
- get_current_capability: Retrieve active capability handle in current async task
- set_current_capability: Set active capability handle
- capability_scope: Context manager for scoped capability binding

[POS]
Provides zero-overhead implicit capability binding across async coroutines and thread contexts.
Ensures child agent execution automatically inherits its assigned attenuated capability handle.
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


def set_current_capability(handle: CapabilityHandle | None) -> object:
    """Set the active CapabilityHandle and return token for reset."""
    return _ACTIVE_CAPABILITY_VAR.set(handle)


def reset_current_capability(token: object) -> None:
    """Reset the active CapabilityHandle to its previous state."""
    _ACTIVE_CAPABILITY_VAR.reset(token)  # type: ignore[arg-type]


@contextmanager
def capability_scope(handle: CapabilityHandle | None) -> Iterator[None]:
    """Execute block within the context of a specific capability handle."""
    token = _ACTIVE_CAPABILITY_VAR.set(handle)
    try:
        yield
    finally:
        _ACTIVE_CAPABILITY_VAR.reset(token)
