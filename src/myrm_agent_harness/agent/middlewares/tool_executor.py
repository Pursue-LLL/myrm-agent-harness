"""Tool Executor with Timeout and Retry

[INPUT]
- langchain_core.messages::ToolMessage (POS: Core message type definitions)
- langgraph.prebuilt.tool_node::ToolCallRequest
- langgraph.types::Command
- agent.middlewares._tool_helpers (POS: Stateless helper functions for tool_interceptor_middleware)
- agent.middlewares._session_context (POS: Middleware session context)
- agent.streaming.types::AgentEventType (POS: Agent event type definitions)
- utils.errors::ToolError (POS: Framework-level tool errors)

[OUTPUT]
- execute_with_retry(): Execute a tool call with timeout, retry, and exponential backoff

[POS]
Tool execution engine. Encapsulates timeout/retry/backoff logic with event logging
and stream emission. Called from tool_interceptor_middleware after pre-call guards pass.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from myrm_agent_harness.agent.middlewares._session_context import (
    get_event_logger,
    get_terminal_errors,
)
from myrm_agent_harness.agent.middlewares._tool_helpers import (
    format_tool_error,
    get_tool_timeout,
    is_non_retryable,
    make_error_msg,
)
from myrm_agent_harness.utils.errors import ToolError
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


async def execute_with_retry(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    tool_name: str,
    tool_call_id: str,
    allowed_domains: list[str] | None,
) -> ToolMessage | Command:
    """Execute a tool call with timeout, retry (max 2 attempts), and exponential backoff.

    Handles:
    - Timeout with event logging and stream emission
    - Retryable vs non-retryable error classification
    - Exponential backoff with jitter
    - Terminal error circuit breaker registration
    """
    from myrm_agent_harness.observability.metrics.agent_metrics import (
        record_ttfa_first_action,
        tool_execution_failed_total,
        tool_execution_total,
    )
    from myrm_agent_harness.toolkits.network.ssrf_shield import URLAllowlistGuard

    record_ttfa_first_action()
    if tool_execution_total is not None:
        tool_execution_total.labels(tool_name=tool_name).inc()

    timeout = get_tool_timeout(tool_name)
    error_history: list[dict[str, Any]] = []
    start_time = time.time()

    for attempt in range(2):
        try:
            async with asyncio.timeout(timeout):
                with URLAllowlistGuard.apply(allowed_domains):
                    result = await handler(request)
                return result
        except TimeoutError as e:
            elapsed = (time.time() - start_time) * 1000
            error_history.append(
                {
                    "attempt": attempt + 1,
                    "error": f"TimeoutError after {timeout}s",
                    "elapsed_ms": elapsed,
                }
            )

            event_logger = get_event_logger()
            if event_logger is not None:
                await event_logger.log(
                    "TOOL_TIMEOUT",
                    {
                        "tool_name": tool_name,
                        "timeout_seconds": timeout,
                        "attempt": attempt + 1,
                        "elapsed_ms": elapsed,
                    },
                )

            await _emit_timeout_event(tool_name, timeout, attempt, elapsed)

            if attempt < 1:
                if event_logger is not None:
                    await event_logger.log(
                        "TOOL_RETRY",
                        {
                            "tool_name": tool_name,
                            "attempt": attempt + 2,
                            "reason": "timeout",
                        },
                    )
                backoff = min(2**attempt + random.uniform(0, 1), 10.0)
                logger.warning(
                    f" Timeout [{tool_name}] attempt {attempt + 1}/2, retry in {backoff:.1f}s"
                )
                await _emit_retry_event(tool_name, attempt, backoff)
                await asyncio.sleep(backoff)
            else:
                total_duration = time.time() - start_time
                error_msg = (
                    f"{tool_name} execution timed out after {attempt + 1} attempts"
                )
                user_hint = (
                    f"Timeout after {timeout}s. Tried {attempt + 1} times over {total_duration:.1f}s. "
                    "Try reducing data size or splitting the task."
                )
                logger.error("Tool timeout final failure [%s]: %s", tool_name, error_msg)
                if tool_execution_failed_total is not None:
                    tool_execution_failed_total.labels(tool_name=tool_name, error_type="timeout").inc()
                raise ToolError(
                    message=error_msg,
                    user_hint=user_hint,
                    diagnostic_info={
                        "retry_count": attempt,
                        "total_duration_seconds": total_duration,
                        "timeout_seconds": timeout,
                        "error_history": error_history,
                    },
                    error_code="TIMEOUT_MAX_RETRIES",
                ) from e

        except Exception as e:
            from langgraph.errors import GraphInterrupt

            if isinstance(e, (GraphInterrupt, InterruptedError)):
                raise

            if is_non_retryable(e, tool_name) or attempt == 1:
                if error_history:
                    total_duration = time.time() - start_time
                    error_msg = (
                        f"{tool_name} execution failed after {attempt + 1} attempts"
                    )
                    original_hint = (
                        getattr(e, "user_hint", "") if isinstance(e, ToolError) else ""
                    )
                    user_hint = f"Tried {attempt + 1} times over {total_duration:.1f}s. {original_hint}"
                    logger.error(
                        f" Tool execution final failure [{tool_name}]: {error_msg}"
                    )
                    if tool_execution_failed_total is not None:
                        tool_execution_failed_total.labels(tool_name=tool_name, error_type=type(e).__name__).inc()
                    raise ToolError(
                        message=error_msg,
                        user_hint=user_hint,
                        diagnostic_info={
                            "retry_count": attempt,
                            "total_duration_seconds": total_duration,
                            "error_history": error_history,
                            "original_error": f"{type(e).__name__}: {str(e)[:200]}",
                        },
                        error_code="MAX_RETRIES_EXCEEDED",
                    ) from e

                if isinstance(e, ToolError):
                    category = getattr(e, "error_category", None)
                    hint = getattr(e, "user_hint", None)
                    if category in ("network_blocked", "sandbox_ro"):
                        get_terminal_errors().add(category)
                        logger.info(
                            f" Circuit breaker registered terminal error: {category}"
                        )
                    if tool_execution_failed_total is not None:
                        tool_execution_failed_total.labels(tool_name=tool_name, error_type=category or "tool_error").inc()
                    return make_error_msg(
                        tool_name,
                        tool_call_id,
                        format_tool_error(e, tool_name),
                        error_category=category,
                        error_hint=hint,
                    )
                raise

            elapsed = (time.time() - start_time) * 1000
            error_history.append(
                {
                    "attempt": attempt + 1,
                    "error": f"{type(e).__name__}: {str(e)[:200]}",
                    "elapsed_ms": elapsed,
                }
            )

            event_logger = get_event_logger()
            if event_logger is not None:
                await event_logger.log(
                    "TOOL_RETRY",
                    {
                        "tool_name": tool_name,
                        "attempt": attempt + 2,
                        "reason": f"{type(e).__name__}",
                        "error": str(e)[:200],
                    },
                )

            retry_after = None
            response = getattr(e, "response", None)
            if response is not None:
                headers = getattr(response, "headers", {})
                # Some clients use case-insensitive dicts, but just in case check both
                retry_val = headers.get("retry-after") or headers.get("Retry-After")
                if retry_val is not None:
                    with contextlib.suppress(ValueError):
                        retry_after = float(retry_val)

            if retry_after is not None:
                backoff = min(retry_after + random.uniform(0, 1), 60.0)
                logger.warning(
                    f" Rate limit [{tool_name}] respects retry-after: {retry_after}s, retry in {backoff:.1f}s"
                )
            else:
                backoff = min(2**attempt + random.uniform(0, 1), 10.0)
                logger.warning(
                    f" Error [{tool_name}] {type(e).__name__}: {str(e)[:100]}, retry in {backoff:.1f}s"
                )

            await asyncio.sleep(backoff)

    raise RuntimeError(
        f"Unexpected: execute_with_retry loop completed without return for {tool_name}"
    )


async def _emit_timeout_event(
    tool_name: str, timeout: float, attempt: int, elapsed: float
) -> None:
    """Emit TOOL_TIMEOUT to stream for real-time visibility."""
    try:
        from myrm_agent_harness.agent.streaming.types import AgentEventType
        from myrm_agent_harness.utils.runtime.progress_sink import (
            get_tool_progress_sink,
        )

        sink = get_tool_progress_sink()
        if sink:
            await sink.emit(
                {
                    "type": AgentEventType.TOOL_TIMEOUT.value,
                    "data": {
                        "tool_name": tool_name,
                        "timeout_seconds": timeout,
                        "attempt": attempt + 1,
                        "elapsed_ms": int(elapsed),
                    },
                }
            )
    except Exception as exc:
        logger.debug("Failed to emit TOOL_TIMEOUT event: %s", exc)


async def _emit_retry_event(tool_name: str, attempt: int, backoff: float) -> None:
    """Emit TOOL_RETRY to stream for real-time visibility."""
    try:
        from myrm_agent_harness.agent.streaming.types import AgentEventType
        from myrm_agent_harness.utils.runtime.progress_sink import (
            get_tool_progress_sink,
        )

        sink = get_tool_progress_sink()
        if sink:
            step_data = {
                "tool_name": tool_name,
                "attempt": attempt + 2,
                "max_attempts": 2,
                "reason": "timeout",
                "backoff_seconds": backoff,
            }
            await sink.emit(
                {
                    "type": AgentEventType.TOOL_RETRY.value,
                    "data": step_data,
                }
            )
    except Exception as exc:
        logger.warning("Failed to emit TOOL_RETRY event: %s", exc)
