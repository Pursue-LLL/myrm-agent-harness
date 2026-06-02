"""Tool concurrency safety dispatcher middleware.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- agent.security.tool_registry::resolve_safety_metadata (POS: 工具安全元数据查询)
- langchain.agents.middleware::wrap_tool_call (POS: 工具调用中间件装饰器)
- langgraph.prebuilt.tool_node::ToolCallRequest (POS: 工具调用请求)

[OUTPUT]
- create_safety_dispatcher: 创建安全调度中间件的工厂函数

[POS]
Tool concurrency safety dispatcher middleware. Queries resolve_safety_metadata
(three-level fallback: built-in → MCP dynamic → fail-closed) for the
is_concurrent_safe attribute to route concurrent vs. sequential execution.

"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from myrm_agent_harness.agent.security.tool_registry import resolve_safety_metadata
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


def _get_batch_id(request: ToolCallRequest) -> int | None:
    """Extract the unique ID of the AIMessage that generated this tool call."""
    state = request.state
    messages = []
    if isinstance(state, list):
        messages = state
    elif isinstance(state, dict):
        messages = state.get("messages", [])
    elif hasattr(state, "messages"):
        messages = getattr(state, "messages", [])

    tool_call_id = request.tool_call.get("id")
    if not tool_call_id:
        return None

    for m in reversed(messages):
        if isinstance(m, AIMessage) and hasattr(m, "tool_calls"):
            for tc in m.tool_calls:
                if tc.get("id") == tool_call_id:
                    return id(m)
    return None


def create_safety_dispatcher():
    """Create safety dispatcher middleware for tool concurrency control.

    Safe tools (``is_concurrent_safe=True``) execute concurrently via ToolNode's
    ``asyncio.gather``.  Unsafe tools acquire a shared ``asyncio.Lock`` so they
    run one at a time, preventing filesystem and state race conditions.

    Additionally, if an unsafe tool fails, subsequent unsafe tools in the same
    batch (from the same AIMessage) will be skipped to preserve partial results
    and prevent cascading failures.

    Returns:
        Middleware function for ``wrap_tool_call``.
    """
    unsafe_lock = asyncio.Lock()
    batch_failures: dict[int, float] = {}

    @wrap_tool_call  # type: ignore[arg-type]
    async def safety_dispatcher_middleware(
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        tool_name: str = request.tool_call.get("name", "")  # type: ignore[assignment]
        metadata = resolve_safety_metadata(tool_name)

        if metadata.is_concurrent_safe or request.tool_call.get("__smart_concurrent_safe__"):
            return await handler(request)

        batch_id = _get_batch_id(request)

        logger.info(" Serializing unsafe tool: %s", tool_name)
        async with unsafe_lock:
            # Cleanup old batch failures (older than 5 minutes) to prevent memory leaks
            now = time.time()
            expired_keys = [k for k, v in batch_failures.items() if now - v > 300]
            for k in expired_keys:
                del batch_failures[k]

            if batch_id and batch_id in batch_failures:
                logger.warning(
                    " Skipping %s because a previous tool in the same batch failed",
                    tool_name,
                )
                return ToolMessage(
                    content="[SKIPPED] This tool was skipped because a previous tool in the same batch failed. The partial results of the successful tools have been preserved.",
                    name=tool_name,
                    tool_call_id=request.tool_call.get("id", ""),
                    status="error",
                )

            result = await handler(request)

            if hasattr(result, "status") and result.status == "error" and batch_id:
                batch_failures[batch_id] = time.time()

            return result

    return safety_dispatcher_middleware
