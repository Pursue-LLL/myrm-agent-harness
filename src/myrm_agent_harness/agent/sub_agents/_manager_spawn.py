"""Subagent spawn and execution operations for SubagentManager.

[INPUT]
- types::SubagentConfig, SubAgentResult, SubAgentStatus
- executor::SubagentExecutor (POS: Retry logic and actual agent execution)
- streaming.types::AgentEventType (POS: SSE event types)
- runtime.events.system_events::SubagentLifecycleData, to_json_object

[OUTPUT]
- SubagentSpawnMixin: Mixin providing _run_subagent, _run_subagent_inner,
  _run_subagent_core, and spawn_child

[POS]
Spawn and execution lifecycle for SubagentManager.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.runtime.events.system_events import (
    SubagentLifecycleData,
    to_json_object,
)
from myrm_agent_harness.utils.runtime.progress_sink import (
    ToolProgressSink,
    get_tool_progress_sink,
)
from myrm_agent_harness.utils.runtime.steering import SteeringToken

if TYPE_CHECKING:
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

    from .manager import SubagentTask

logger = logging.getLogger(__name__)

_HARD_TIMEOUT_MULTIPLIER = 3
"""Hard execution timeout = config.timeout_seconds * this multiplier.

The wait-level timeout (config.timeout_seconds) returns control to the parent
non-fatally.  The hard timeout is a safety net that terminates truly runaway
agents while still giving them enough headroom to finish after a wait timeout.
"""


class SubagentSpawnMixin:
    """Spawn, execution, and result handling for SubagentManager."""

    # These attributes are provided by SubagentManager.__init__
    _semaphore: asyncio.Semaphore
    _executor: object  # SubagentExecutor
    _parent_agent: object  # BaseAgent (weakref-resolved)
    _children: dict[str, SubagentTask]
    _children_types: dict[str, str]
    _children_descriptions: dict[str, str]
    _children_configs: dict[str, SubagentConfig]
    _children_steering: dict[str, SteeringToken]
    _children_observability: dict[str, dict[str, object]]
    _children_agents: dict[str, object]
    _cancel_flags: dict[str, bool]

    async def _run_subagent(
        self,
        task_id: str,
        agent_type: str,
        task_description: str,
        config: SubagentConfig,
        context: dict[str, object],
        tool_registry_getter: Callable[[], list[BaseTool]],
        trace_id: str = "",
        steering_token: SteeringToken | None = None,
        cancel_token: CancellationToken | None = None,
        resume_command: object | None = None,
        parent_progress_sink: ToolProgressSink | None = None,
        complexity_tier: str | None = None,
    ) -> SubAgentResult:
        hard_timeout = config.timeout_seconds * _HARD_TIMEOUT_MULTIPLIER
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    self._run_subagent_inner(
                        task_id,
                        agent_type,
                        task_description,
                        config,
                        context,
                        tool_registry_getter,
                        trace_id,
                        steering_token,
                        cancel_token=cancel_token,
                        resume_command=resume_command,
                        parent_progress_sink=parent_progress_sink,
                        complexity_tier=complexity_tier,
                    ),
                    timeout=hard_timeout,
                )
            except TimeoutError:
                logger.warning(
                    "[subagent:%s] Hard timeout after %ss (config timeout=%ss)",
                    task_id, hard_timeout, config.timeout_seconds,
                )
                return SubAgentResult(
                    success=False,
                    task_id=task_id,
                    agent_type=agent_type,
                    error=f"Hard timeout after {hard_timeout}s",
                    completed_at=time.time(),
                    status=SubAgentStatus.TIMED_OUT,
                    trace_id=trace_id,
                )

    async def _run_subagent_inner(
        self,
        task_id: str,
        agent_type: str,
        task_description: str,
        config: SubagentConfig,
        context: dict[str, object],
        tool_registry_getter: Callable[[], list[BaseTool]],
        trace_id: str = "",
        steering_token: SteeringToken | None = None,
        cancel_token: CancellationToken | None = None,
        resume_command: object | None = None,
        parent_progress_sink: ToolProgressSink | None = None,
        complexity_tier: str | None = None,
    ) -> SubAgentResult:
        import contextlib

        from myrm_agent_harness.agent.skills.evolution.execution.executor_context import ExecutorContextManager
        from myrm_agent_harness.agent.sub_agents.types import WorkspacePolicy
        from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor
        from myrm_agent_harness.toolkits.code_execution.executors.readonly_proxy import ReadonlyExecutorProxy

        context_manager = contextlib.nullcontext()
        if config.workspace_policy == WorkspacePolicy.READ_ONLY_SANDBOX:
            current_executor = get_executor()
            if current_executor and not isinstance(current_executor, ReadonlyExecutorProxy):
                context_manager = ExecutorContextManager(ReadonlyExecutorProxy(current_executor))

        with context_manager:
            return await self._run_subagent_core(
                task_id,
                agent_type,
                task_description,
                config,
                context,
                tool_registry_getter,
                trace_id,
                steering_token,
                cancel_token,
                resume_command,
                parent_progress_sink,
                complexity_tier,
            )

    async def _run_subagent_core(
        self,
        task_id: str,
        agent_type: str,
        task_description: str,
        config: SubagentConfig,
        context: dict[str, object],
        tool_registry_getter: Callable[[], list[BaseTool]],
        trace_id: str = "",
        steering_token: SteeringToken | None = None,
        cancel_token: CancellationToken | None = None,
        resume_command: object | None = None,
        parent_progress_sink: ToolProgressSink | None = None,
        complexity_tier: str | None = None,
    ) -> SubAgentResult:
        """Execute subagent with retry logic and workspace isolation."""
        try:
            return await self._executor.run_with_retry(  # type: ignore[union-attr]
                task_id=task_id,
                agent_type=agent_type,
                task_description=task_description,
                config=config,
                context=context,
                tool_registry_getter=tool_registry_getter,
                start_time=time.time(),
                parent_agent=self._parent_agent,
                cancel_flags=self._cancel_flags,
                children_agents=self._children_agents,
                children_steering=self._children_steering,
                trace_id=trace_id,
                steering_token=steering_token,
                cancel_token=cancel_token,
                resume_command=resume_command,
                parent_progress_sink=parent_progress_sink,
                complexity_tier=complexity_tier,
            )
        finally:
            self._cancel_flags.pop(task_id, None)
            child = self._children_agents.pop(task_id, None)
            if child is not None:
                try:
                    child.cancel_all_children()  # type: ignore[union-attr]
                except Exception:
                    logger.debug(
                        "[subagent:%s] Cascade cancel in finally failed",
                        task_id,
                        exc_info=True,
                    )

    async def spawn_child(
        self,
        task_id: str,
        agent_type: str,
        task_description: str,
        config: SubagentConfig,
        context: dict[str, object],
        tool_registry_getter: Callable[[], list[BaseTool]],
        wait: bool,
        parent_type: str | None = None,
        cancel_token: CancellationToken | None = None,
        resume_command: object | None = None,
        complexity_tier: str | None = None,
    ) -> SubAgentResult | dict[str, object]:
        if self._task_id_exists(task_id):  # type: ignore[attr-defined]
            return SubAgentResult(
                success=False,
                task_id=task_id,
                agent_type=agent_type,
                error=f"Task id '{task_id}' already exists",
                completed_at=time.time(),
                status=SubAgentStatus.FAILED,
            )

        depth_error = self._validate_depth(task_id, config)  # type: ignore[attr-defined]
        if depth_error is not None:
            return depth_error

        capacity_error = self._validate_capacity(task_id, agent_type, config)  # type: ignore[attr-defined]
        if capacity_error is not None:
            return capacity_error

        parent_trace = str(context.get("trace_id", "")) if context else ""
        trace_id = parent_trace or uuid.uuid4().hex[:16]
        parent_task_id = str(context.get("task_id", "")) if context else ""

        steering_token = SteeringToken()
        self._children_steering[task_id] = steering_token

        from .manager import ACTIVE_SUBAGENTS

        ACTIVE_SUBAGENTS[task_id] = self  # type: ignore[assignment]
        parent_progress_sink = get_tool_progress_sink()

        task = asyncio.create_task(
            self._run_subagent(
                task_id=task_id,
                agent_type=agent_type,
                task_description=task_description,
                config=config,
                context=context,
                tool_registry_getter=tool_registry_getter,
                trace_id=trace_id,
                steering_token=steering_token,
                cancel_token=cancel_token,
                resume_command=resume_command,
                parent_progress_sink=parent_progress_sink,
                complexity_tier=complexity_tier,
            )
        )
        self._children[task_id] = task
        self._children_types[task_id] = agent_type
        self._children_descriptions[task_id] = task_description
        self._children_configs[task_id] = config
        self._children_observability[task_id] = self._build_observability_metadata(config)  # type: ignore[attr-defined]
        task.add_done_callback(lambda t: self._cleanup_child(task_id, t))  # type: ignore[attr-defined]

        session_id = str(context.get("session_id", "")) if context else ""
        if not session_id:
            parent_ctx = getattr(self._parent_agent, "_last_context", None)
            if isinstance(parent_ctx, dict):
                session_id = str(parent_ctx.get("session_id", "") or "")

        if session_id:
            from .manager import ACTIVE_SUBAGENT_SESSIONS

            ACTIVE_SUBAGENT_SESSIONS[task_id] = session_id
            from myrm_agent_harness.agent.coordination.mailbox import register_active_teammate

            workspace_path = str(context.get("workspace_path", "") or "") or None
            await register_active_teammate(session_id, workspace_path, task_id, agent_type)

        observability_metadata = self._child_observability_metadata(task_id)  # type: ignore[attr-defined]
        budget_payload = observability_metadata.get("budget")

        from .manager import _emit_global_subagent_event

        _emit_global_subagent_event(
            "spawn",
            task_id,
            session_id,
            SubagentLifecycleData(
                agent_type=agent_type,
                description=task_description,
                role=config.delegation_role.value,
                control_scope=config.control_scope.value,
                budget=to_json_object(budget_payload if isinstance(budget_payload, dict) else None),
            ),
        )

        sink = get_tool_progress_sink()
        if sink:
            await sink.emit(
                {
                    "type": AgentEventType.SUBAGENT_START.value,
                    "data": {
                        "task_id": task_id,
                        "parent_task_id": parent_task_id,
                        "agent_type": agent_type,
                        "description": task_description,
                        "role": config.delegation_role.value,
                        "control_scope": config.control_scope.value,
                        "budget": budget_payload if isinstance(budget_payload, dict) else {},
                    },
                }
            )

        if wait:
            done, _pending = await asyncio.wait(
                {task}, timeout=config.timeout_seconds,
            )
            if done:
                result = task.result()
                if sink:
                    notif_text = self.drain_notifications()  # type: ignore[attr-defined]
                    if notif_text:
                        await sink.emit(
                            {
                                "type": AgentEventType.SUBAGENT_COMPLETION.value,
                                "data": notif_text,
                            }
                        )
                return result

            logger.info(
                "[subagent:%s] Wait timeout after %ss — agent continues in background",
                task_id, config.timeout_seconds,
            )
            return SubAgentResult(
                success=False,
                task_id=task_id,
                agent_type=agent_type,
                error=(
                    f"Timeout after {config.timeout_seconds}s, agent still running in background. "
                    "Use list_subagents to check progress, or cancel_subagent to stop it."
                ),
                completed_at=0.0,
                status=SubAgentStatus.TIMED_OUT,
                still_running=True,
                trace_id=trace_id,
            )

        return {
            "task_id": task_id,
            "status": SubAgentStatus.RUNNING.value,
            "agent_type": agent_type,
            "role": config.delegation_role.value,
            "control_scope": config.control_scope.value,
            "budget": budget_payload if isinstance(budget_payload, dict) else {},
        }
