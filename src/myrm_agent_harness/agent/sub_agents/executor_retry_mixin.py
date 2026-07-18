"""SubagentExecutor retry loop and workspace isolation.

[INPUT]
- .executor_helpers::_cascade_cancel_descendants, _compact_error_message (POS: Pure helper functions for SubagentExecutor mixins and external callers.)
- .types::SubagentBudgetExceededError, SubagentConfig, SubAgentResult, SubAgentStatus, WorkspacePolicy (POS: Subagent subsystem core type definitions.)
- toolkits.llms.errors.exceptions::MyrmLLMError (POS: Standardized LLM Error thrown by the Harness framework.)
- agent.hooks.executor::fire_hook (POS: Hook execution layer. Manages hook registration and execution with ContextVar-based session isolation.)

[OUTPUT]
- SubagentExecutorRetryMixin.run_with_retry

[POS]
Retry loop with workspace isolation, hooks, and graceful cancellation.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.security.guards.taint_tracker import get_taint_tracker
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.runtime.progress_sink import ToolProgressSink
from myrm_agent_harness.utils.runtime.steering import SteeringToken
from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

from myrm_agent_harness.toolkits.llms.errors.exceptions import MyrmLLMError

from .executor_helpers import _cascade_cancel_descendants, _compact_error_message
from .types import (
    SubagentBudgetExceededError,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
    WorkspacePolicy,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.utils import CancellationToken

logger = get_agent_logger(__name__)


class SubagentExecutorRetryMixin:
    """Run subagents with retries and workspace isolation."""

    async def run_with_retry(
        self,
        task_id: str,
        agent_type: str,
        task_description: str,
        config: SubagentConfig,
        context: dict[str, object],
        tool_registry_getter: Callable[[], list[BaseTool]],
        start_time: float,
        parent_agent: BaseAgent,
        cancel_flags: dict[str, bool],
        children_agents: dict[str, BaseAgent],
        children_steering: dict[str, SteeringToken],
        trace_id: str = "",
        steering_token: SteeringToken | None = None,
        cancel_token: CancellationToken | None = None,
        resume_command: object | None = None,
        parent_progress_sink: ToolProgressSink | None = None,
        complexity_tier: str | None = None,
    ) -> SubAgentResult:
        """Execute subagent with retry logic and workspace isolation."""
        retries_left = config.max_retries
        backoff_seconds = config.retry_backoff_seconds

        if steering_token is None:
            steering_token = SteeringToken()
            children_steering[task_id] = steering_token

        context = await self._inherit_parent_context(context, task_id, parent_agent)
        context["trace_id"] = trace_id

        # Workspace isolation: ISOLATED_COPY creates a COW clone via shutil.copytree

        isolation_ctx = None
        isolated_parent_ws: str | None = None
        if config.workspace_policy == WorkspacePolicy.ISOLATED_COPY:
            parent_ws = context.get("workspace_path")
            if parent_ws:
                from myrm_agent_harness.agent.sub_agents.workspace_isolation import (
                    isolated_workspace,
                )

                isolated_parent_ws = str(parent_ws)
                isolation_ctx = isolated_workspace(isolated_parent_ws)
                child_ws, sync_back = await isolation_ctx.__aenter__()
                context["workspace_path"] = str(child_ws)
                context["_workspace_sync_back"] = sync_back
                context["_isolated_parent_workspace"] = isolated_parent_ws

        from myrm_agent_harness.agent.hooks.executor import fire_hook
        from myrm_agent_harness.agent.hooks.types import HookEvent

        await fire_hook(
            HookEvent.SUBAGENT_START,
            {
                "task_id": task_id,
                "agent_type": agent_type,
                "task_description": task_description,
                "trace_id": trace_id,
            },
        )

        parent_tracker = get_token_tracker()
        parent_taint = get_taint_tracker()
        isolation_succeeded = False
        pending_sync_back: object | None = None

        try:
            while retries_left > 0:
                try:
                    result = await self._run_single_attempt(
                        task_id,
                        agent_type,
                        task_description,
                        config,
                        context,
                        tool_registry_getter,
                        start_time,
                        parent_tracker,
                        parent_taint,
                        parent_agent,
                        cancel_flags,
                        children_agents,
                        fire_hook,
                        HookEvent,
                        trace_id,
                        steering_token,
                        cancel_token=cancel_token,
                        resume_command=resume_command,
                        parent_progress_sink=parent_progress_sink,
                    )
                    if isolation_ctx and result.success:
                        isolation_succeeded = True
                        sync_back_fn = context.get("_workspace_sync_back")
                        if sync_back_fn:
                            pending_sync_back = sync_back_fn
                            if context.get("_defer_workspace_merge"):
                                from dataclasses import replace as dc_replace

                                extra = (
                                    dict(result.result) if isinstance(result.result, dict) else {"text": result.result}
                                )
                                extra["_workspace_sync_back"] = sync_back_fn
                                extra["_isolated_child_workspace"] = str(context.get("workspace_path", ""))
                                if isolated_parent_ws:
                                    extra["_isolated_parent_workspace"] = isolated_parent_ws
                                result = dc_replace(result, result=extra)
                    return result
                except TimeoutError as timeout_exc:
                    retries_left -= 1
                    logger.warning("[subagent:%s] Timeout, retries_left=%d", task_id, retries_left)
                    if retries_left > 0:
                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue
                    now = time.time()
                    partial = getattr(timeout_exc, "partial_output", "") or ""
                    if partial and len(partial) > (config.max_error_chars * 2):
                        partial = partial[: config.max_error_chars * 2] + "\n…[truncated]"
                    return SubAgentResult(
                        success=False,
                        task_id=task_id,
                        agent_type=agent_type,
                        result=partial,
                        error=f"Timeout after {config.timeout_seconds}s",
                        duration_seconds=now - start_time,
                        completed_at=now,
                        status=SubAgentStatus.TIMED_OUT,
                        trace_id=trace_id,
                    )
                except MyrmLLMError as llm_exc:
                    retries_left -= 1
                    logger.warning(
                        "[subagent:%s] LLM error, retries_left=%d",
                        task_id, retries_left,
                    )
                    if retries_left > 0:
                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue
                    now = time.time()
                    partial = getattr(llm_exc, "partial_output", "") or ""
                    if partial and len(partial) > (config.max_error_chars * 2):
                        partial = partial[: config.max_error_chars * 2] + "\n…[truncated]"
                    err_result = SubAgentResult(
                        success=False,
                        task_id=task_id,
                        agent_type=agent_type,
                        result=partial,
                        error=_compact_error_message(str(llm_exc), config.max_error_chars),
                        duration_seconds=now - start_time,
                        completed_at=now,
                        status=SubAgentStatus.FAILED,
                        trace_id=trace_id,
                    )
                    await fire_hook(
                        HookEvent.SUBAGENT_STOP,
                        {
                            "task_id": task_id,
                            "agent_type": agent_type,
                            "success": False,
                            "error": err_result.error,
                            "duration_seconds": now - start_time,
                            "trace_id": trace_id,
                        },
                    )
                    return err_result
                except SubagentBudgetExceededError as error:
                    now = time.time()
                    partial = getattr(error, "partial_output", "") or ""
                    if partial and len(partial) > (config.max_error_chars * 2):
                        partial = partial[: config.max_error_chars * 2] + "\n…[truncated]"
                    err_result = SubAgentResult(
                        success=False,
                        task_id=task_id,
                        agent_type=agent_type,
                        result=partial,
                        error=str(error),
                        duration_seconds=now - start_time,
                        completed_at=now,
                        status=SubAgentStatus.CANCELLED_BY_BUDGET,
                        trace_id=trace_id,
                    )
                    await fire_hook(
                        HookEvent.SUBAGENT_STOP,
                        {
                            "task_id": task_id,
                            "agent_type": agent_type,
                            "success": False,
                            "error": err_result.error,
                            "duration_seconds": now - start_time,
                            "trace_id": trace_id,
                        },
                    )
                    return err_result
                except Exception as error:
                    retries_left -= 1
                    logger.error(
                        "[subagent:%s] Error: %s, retries_left=%d",
                        task_id,
                        error,
                        retries_left,
                        exc_info=True,
                    )
                    if retries_left > 0:
                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue
                    now = time.time()
                    raw_error = f"{type(error).__name__}: {error}"
                    partial = getattr(error, "partial_output", "") or ""
                    if partial and len(partial) > (config.max_error_chars * 2):
                        partial = partial[: config.max_error_chars * 2] + "\n…[truncated]"
                    err_result = SubAgentResult(
                        success=False,
                        task_id=task_id,
                        agent_type=agent_type,
                        result=partial,
                        error=_compact_error_message(raw_error, config.max_error_chars),
                        duration_seconds=now - start_time,
                        completed_at=now,
                        status=SubAgentStatus.FAILED,
                        trace_id=trace_id,
                    )
                    await fire_hook(
                        HookEvent.SUBAGENT_STOP,
                        {
                            "task_id": task_id,
                            "agent_type": agent_type,
                            "success": False,
                            "error": err_result.error,
                            "duration_seconds": now - start_time,
                            "trace_id": trace_id,
                        },
                    )
                    return err_result

            now = time.time()
            return SubAgentResult(
                success=False,
                task_id=task_id,
                agent_type=agent_type,
                error="Max retries exceeded",
                duration_seconds=now - start_time,
                completed_at=now,
                status=SubAgentStatus.FAILED,
                trace_id=trace_id,
            )

        except asyncio.CancelledError:
            logger.info("[subagent:%s] Cancelled, executing graceful shutdown", task_id)
            _cascade_cancel_descendants(children_agents.get(task_id))
            now = time.time()
            await fire_hook(
                HookEvent.SUBAGENT_CANCEL_COMPLETE,
                {
                    "task_id": task_id,
                    "agent_type": agent_type,
                    "duration_seconds": now - start_time,
                    "trace_id": trace_id,
                },
            )
            await fire_hook(
                HookEvent.SUBAGENT_STOP,
                {
                    "task_id": task_id,
                    "agent_type": agent_type,
                    "success": False,
                    "error": "Cancelled",
                    "duration_seconds": now - start_time,
                    "trace_id": trace_id,
                },
            )
            return SubAgentResult(
                success=False,
                task_id=task_id,
                agent_type=agent_type,
                error="Cancelled",
                duration_seconds=now - start_time,
                completed_at=now,
                status=SubAgentStatus.CANCELLED,
                trace_id=trace_id,
            )
        finally:
            if isolation_ctx:
                try:
                    if (
                        isolation_succeeded
                        and pending_sync_back is not None
                        and not context.get("_defer_workspace_merge")
                    ):
                        sync_outcome = pending_sync_back()
                        if asyncio.iscoroutine(sync_outcome):
                            await sync_outcome
                    await isolation_ctx.__aexit__(None, None, None)
                except Exception as e:
                    logger.warning(
                        "[subagent:%s] Workspace isolation cleanup failed: %s",
                        task_id,
                        e,
                    )
            logger.debug("[subagent:%s] Resource cleanup complete", task_id)
