"""Tooling subsystem — single interception point for all tool calls.

The interceptor orchestrates stateless guards and lifecycle hooks; each guard
is an independent module. Public API:

- ``tool_interceptor_middleware``: single middleware entry for every tool call
- ``get_loop_guard`` / ``reset_loop_guard`` / ``notify_loop_guard_compaction``:
  LoopGuard lifecycle accessors (ContextVar-safe across HITL resume)

[INPUT]
- langchain_core.messages (message models)
- langchain_core.tools (tool invocation request)
- agent.middlewares._session_context (shared ContextVars)

[OUTPUT]
- tool_interceptor_middleware: the interception middleware
- LoopGuard accessors
"""

from myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware import (
    get_loop_guard,
    notify_loop_guard_compaction,
    reset_loop_guard,
    tool_interceptor_middleware,
)

__all__ = [
    "get_loop_guard",
    "notify_loop_guard_compaction",
    "reset_loop_guard",
    "tool_interceptor_middleware",
]
