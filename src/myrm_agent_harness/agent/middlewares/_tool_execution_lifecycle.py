"""Tool execution lifecycle helpers for the interception middleware.

Handles dynamic tool resolution, heartbeat emission during long-running
executions, and structured error / cancellation handling.

[INPUT]
- langgraph.prebuilt.tool_node::ToolCallRequest
- agent.middlewares._session_context (POS: active tool registry)
- agent.middlewares._tool_helpers (POS: error formatting)

[OUTPUT]
- resolve_dynamic_tool: Resolve ToolNode misses via the active agent ToolRegistry
- emit_tool_heartbeat: Periodic heartbeat for long-running tools
- handle_cancellation: Structured cancellation handling
- handle_execution_error: Structured error handling with ToolStuckException support

[POS]
Tool execution lifecycle management — invocation dispatch, result capture,
error handling, and telemetry emission for the tool interceptor middleware.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from myrm_agent_harness.agent.middlewares._tool_helpers import (
    format_tool_error,
    make_error_msg,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = get_agent_logger(__name__)


# ---------------------------------------------------------------------------
# Dynamic tool resolution
# ---------------------------------------------------------------------------


def resolve_dynamic_tool(request: ToolCallRequest) -> ToolCallRequest:
    """Resolve ToolNode misses via the active agent ToolRegistry."""
    if request.tool is not None:
        return request

    from myrm_agent_harness.agent.middlewares._session_context import (
        get_active_resolved_tools,
        get_active_tool_registry,
    )

    call_name = str(request.tool_call.get("name", ""))
    registry = get_active_tool_registry()
    candidate_names = {call_name}
    if not call_name.endswith("_tool"):
        candidate_names.add(f"{call_name}_tool")
    else:
        candidate_names.add(call_name.removesuffix("_tool"))

    search_pool: list[BaseTool] = []
    resolved_tools = get_active_resolved_tools()
    if resolved_tools:
        search_pool.extend(resolved_tools)
    if registry is not None:
        search_pool.extend(registry.resolve())
        search_pool.extend(registry.get_deferred_tools())

    seen: set[str] = set()
    for resolved_tool in search_pool:
        if resolved_tool.name in seen:
            continue
        seen.add(resolved_tool.name)
        if resolved_tool.name in candidate_names:
            logger.warning(
                "Dynamic tool resolve: matched '%s' -> '%s'",
                call_name,
                resolved_tool.name,
            )
            return request.override(tool=resolved_tool)

    if registry is None:
        logger.warning("Dynamic tool resolve: no active ToolRegistry for '%s'", call_name)
    else:
        logger.warning(
            "Dynamic tool resolve: no match for '%s' among %d tools",
            call_name,
            len(seen),
        )
    return request


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


async def emit_tool_heartbeat(tool_name: str, tool_call_id: str, start_time: float) -> None:
    """Emit periodic heartbeat events for long-running tools."""
    from myrm_agent_harness.agent.streaming.types import AgentEventType
    from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

    await asyncio.sleep(3.0)

    while True:
        try:
            sink = get_tool_progress_sink()
            if sink:
                elapsed_ms = int((time.time() - start_time) * 1000)
                await sink.emit(
                    {
                        "type": AgentEventType.TOOL_HEARTBEAT.value,
                        "step_key": f"{tool_name}_heartbeat",
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                        "elapsed_ms": elapsed_ms,
                    }
                )
        except Exception as e:
            logger.debug("Failed to emit tool heartbeat: %s", e)

        await asyncio.sleep(3.0)


# ---------------------------------------------------------------------------
# Cancellation handling
# ---------------------------------------------------------------------------


async def handle_cancellation(
    e: asyncio.CancelledError,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, object],
    start_time: float,
) -> ToolMessage:
    """Handle tool cancellation with hooks and event emission."""
    from myrm_agent_harness.agent.hooks.executor import fire_hook
    from myrm_agent_harness.agent.hooks.types import HookEvent
    from myrm_agent_harness.agent.streaming.types import AgentEventType
    from myrm_agent_harness.toolkits.mcp.errors import reraise_if_genuine_cancel

    reraise_if_genuine_cancel(e)

    error_msg = str(e) if e.args else ""
    if "timeout" in error_msg.lower():
        cancel_reason = "timeout"
    elif "user" in error_msg.lower():
        cancel_reason = "user_cancelled"
    elif "session" in error_msg.lower():
        cancel_reason = "session_ended"
    else:
        cancel_reason = "user_cancelled"

    logger.warning("Tool cancelled [%s]: %s", tool_name, cancel_reason)

    await fire_hook(
        HookEvent.POST_TOOL_USE_CANCELLED,
        {
            "tool_name": tool_name,
            "tool_input": tool_args,
            "tool_call_id": tool_call_id,
            "cancel_reason": cancel_reason,
        },
    )

    try:
        from myrm_agent_harness.utils.runtime.progress_sink import (
            get_tool_progress_sink,
        )

        sink = get_tool_progress_sink()
        if sink:
            duration_ms = int((time.time() - start_time) * 1000)
            await sink.emit(
                {
                    "type": AgentEventType.TOOL_CANCELLED.value,
                    "data": {
                        "tool_name": tool_name,
                        "cancel_reason": cancel_reason,
                        "duration_ms": duration_ms,
                    },
                }
            )
    except Exception as exc:
        logger.warning("Failed to emit TOOL_CANCELLED event: %s", exc)

    return make_error_msg(
        tool_name,
        tool_call_id,
        f"{tool_name} was cancelled ({cancel_reason})",
        error_category="tool_cancelled",
    )


# ---------------------------------------------------------------------------
# Execution error handling
# ---------------------------------------------------------------------------


async def handle_execution_error(
    e: Exception, tool_name: str, tool_call_id: str, tool_args: dict[str, object]
) -> ToolMessage:
    """Handle unexpected execution errors with hooks."""
    from langgraph.errors import GraphInterrupt

    if isinstance(e, (GraphInterrupt, InterruptedError)):
        raise e

    from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException

    if isinstance(e, ToolStuckException):
        from langgraph.types import interrupt

        logger.warning(
            "ToolStuckException → GraphInterrupt [%s]: %s",
            tool_name,
            str(e)[:200],
        )
        interrupt(
            {
                "action_type": "tool_stuck",
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "error_message": str(e),
            }
        )

    error_type = type(e).__name__
    error_msg = str(e)
    logger.warning(
        "Tool execution error [%s]: %s: %s",
        tool_name,
        error_type,
        error_msg[:200],
        exc_info=e,
    )

    from myrm_agent_harness.agent.hooks.executor import fire_hook
    from myrm_agent_harness.agent.hooks.types import HookEvent

    await fire_hook(
        HookEvent.POST_TOOL_USE_FAILURE,
        {
            "tool_name": tool_name,
            "tool_input": tool_args,
            "error": f"{error_type}: {error_msg}",
            "tool_call_id": tool_call_id,
        },
    )

    from myrm_agent_harness.agent.middlewares._mutation_verifier import (
        record_mutation_result,
    )

    record_mutation_result(
        tool_name=tool_name,
        tool_args=dict(tool_args),
        is_error=True,
        error_content=f"{error_type}: {error_msg}"[:200],
    )

    error_category: str | None = (
        getattr(e, "diagnostic_info", {}).get("error_category") if hasattr(e, "diagnostic_info") else None
    )
    return make_error_msg(
        tool_name,
        tool_call_id,
        format_tool_error(e, tool_name),
        error_category=error_category,
    )
