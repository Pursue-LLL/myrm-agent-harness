"""Dynamic Replan Loop Middleware.

Acts as a ReplanNode that catches ToolExecutionErrors and feeds them back
to the LLM for self-correction instead of crashing the agent loop.

[INPUT]
- (none)

[OUTPUT]
- ReplanMiddleware: Catches tool execution errors and triggers a replan loop.

[POS]
Dynamic Replan Loop Middleware. Per-tool error counting prevents unrelated
tool successes from resetting the counter for a persistently failing tool.
"""

import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)

_per_tool_errors_var: ContextVar[dict[str, int] | None] = ContextVar("replan_per_tool_errors", default=None)


def reset_replan_attempts() -> None:
    """Reset the per-tool replan attempts counter."""
    _per_tool_errors_var.set({})


class ReplanMiddleware(AgentMiddleware[Any, Any]):
    """Catches tool execution errors and triggers a replan loop.

    Error counting is per-tool: only that tool's own success resets its counter.
    This prevents patterns like ``skill_select(OK) → bash(FAIL) → skill_select(OK)``
    from resetting bash's failure count.
    """

    name = "replan_middleware"

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        raise NotImplementedError("ReplanMiddleware does not support synchronous wrap_tool_call")

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tool_name = request.tool_call.get("name", "unknown")
        try:
            result = await handler(request)
            counters = (_per_tool_errors_var.get() or {}).copy()
            if tool_name in counters:
                del counters[tool_name]
                _per_tool_errors_var.set(counters)
            return result
        except Exception as e:
            counters = (_per_tool_errors_var.get() or {}).copy()
            attempts = counters.get(tool_name, 0) + 1
            counters[tool_name] = attempts
            _per_tool_errors_var.set(counters)

            if attempts > self.max_attempts:
                logger.warning(
                    "ReplanNode limit exceeded for '%s' (%d attempts)",
                    tool_name,
                    attempts,
                )
                error_content = f"ToolExecutionError: {e}\n\nEngine limit reached: max_replan_attempts exceeded ({self.max_attempts}). Stop trying to use this tool."
                return ToolMessage(
                    content=error_content,
                    name=tool_name,
                    tool_call_id=request.tool_call["id"],
                    status="error",
                )

            tool_args = request.tool_call.get("args", {})
            target = str(tool_args.get("path", tool_args.get("url", tool_args.get("command", ""))))[:200]
            logger.warning("ReplanNode caught tool error in '%s': %s", tool_name, e)

            from myrm_agent_harness.agent._internals.agent_recovery import (
                build_error_context,
            )
            from myrm_agent_harness.agent.security.guards.loop_suggestions.core import (
                get_tool_suggestion,
            )

            suggestion = get_tool_suggestion(tool_name)
            error_context = build_error_context(
                operation=tool_name,
                target=target or "unknown",
                error=str(e),
            )

            error_content = f"ToolExecutionError: {e}\n\n{error_context}\n\nDiagnostic Hint: {suggestion}"

            return ToolMessage(
                content=error_content,
                name=tool_name,
                tool_call_id=request.tool_call["id"],
                status="error",
            )
