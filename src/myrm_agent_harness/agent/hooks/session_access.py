"""Session-scoped hook access API.

ContextVar-based session access for the hook executor plus convenience
helpers, split from ``executor.py`` so the execution engine stays focused
on dispatching. ``executor.py`` re-exports these names, so existing
``from ...hooks.executor import fire_hook`` call sites keep working.

[OUTPUT]
- get/set_hook_executor: ContextVar accessors
- fire_hook: fire a hook event on the current session's executor
- payload_from_dataclass: frozen-dataclass payload → dict conversion
- bootstrap_hook_registry: get-or-create the session-scoped registry
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast

from myrm_agent_harness.agent.hooks.types import EMPTY_RESULT, AggregatedHookResult

if TYPE_CHECKING:
    from myrm_agent_harness.agent.hooks.executor import HookExecutor, HookRegistry

_executor_var: ContextVar[HookExecutor | None] = ContextVar("hook_executor", default=None)


def get_hook_executor() -> HookExecutor | None:
    """Get the session-scoped HookExecutor, or None if not configured."""
    return _executor_var.get()


def set_hook_executor(executor: HookExecutor | None) -> None:
    """Set the session-scoped HookExecutor."""
    _executor_var.set(executor)


async def fire_hook(event: str, payload: dict[str, object]) -> AggregatedHookResult:
    """Fire a hook event on the current session's executor.

    Returns EMPTY_RESULT if no executor is configured — zero overhead when
    hooks are not used.
    """
    executor = _executor_var.get()
    if executor is None:
        return EMPTY_RESULT
    return await executor.execute(event, payload)


def payload_from_dataclass(obj: object) -> dict[str, object]:
    """Convert a frozen dataclass payload to dict for hook execution."""
    return cast(dict[str, object], asdict(cast(Any, obj)))


def bootstrap_hook_registry() -> HookRegistry:
    """Get or create the session-scoped HookRegistry.

    Ensures that the registry is a singleton per session and avoids
    duplicate registration of core framework hooks.
    """
    from myrm_agent_harness.agent.hooks.executor import HookExecutor, HookRegistry

    executor = get_hook_executor()
    if executor is not None:
        return executor.registry

    registry = HookRegistry()
    set_hook_executor(HookExecutor(registry))
    return registry
