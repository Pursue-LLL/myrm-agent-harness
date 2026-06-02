"""Subagent execution logic.

[INPUT]
- agent.types::SubagentConfig, SubAgentResult, SubAgentStatus, AgentHandoverState, DelegationCapabilityManifest (POS: Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.)
- agent.base_agent::BaseAgent (POS: Agent base class that owns a SubagentManager instance)
- agent.middlewares._session_context::set_is_subagent (POS: ContextVar management, marks subagent context)
- agent.artifacts.vault::ArtifactVault (POS: Oversized result vault, vault:// pointer protocol)
- utils.token_economics.tracker::TokenTracker (POS: Token usage tracking service)
- .builder::_HANDOVER_PROTOCOL_PROMPT, build_child_agent, filter_tools, merge_child_stats, truncate_result (POS: Subagent construction helpers. Prepare child agents without business-layer dependencies.)
- .event_forwarder::SubagentEventForwarder (POS: Subagent event forwarder)
- agent.security.guards.taint_tracker::get_taint_tracker (POS: Session-level information-flow taint tracking. Propagates taint labels from child to parent and adds inbound security warnings for tainted results.)

[OUTPUT]
- SubagentExecutor: Executes child agents with role-scoped delegation tools, retry logic, workspace isolation, event handling, cascade cancellation, and approval deadlock protection.
- _cascade_cancel_descendants: Recursively cancels all descendant subagents when a child is cancelled
- _auto_vault_or_truncate: Stores oversized results in ArtifactVault and returns summary plus vault:// pointer
- _parse_handover_state: Parses the <handover> JSON block.

[POS]
Subagent executor. Runs child agents and injects delegation tools only for trusted orchestrator roles.

"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.security.guards.taint_tracker import get_taint_tracker
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.runtime.progress_sink import ToolProgressSink
from myrm_agent_harness.utils.runtime.steering import SteeringToken
from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

from .builder import (
    _HANDOVER_PROTOCOL_PROMPT,
    build_child_agent,
    filter_tools,
    merge_child_stats,
    truncate_result,
)
from .event_forwarder import SubagentEventForwarder
from .types import (
    DELEGATION_CAPABILITY_MANIFEST,
    AgentHandoverState,
    DelegateRole,
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


class SubagentExecutor:
    """Execute subagent with retry, workspace isolation, and event forwarding."""

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

        # Workspace isolation: ISOLATED_COPY creates a hardlinked clone

        isolation_ctx = None
        if config.workspace_policy == WorkspacePolicy.ISOLATED_COPY:
            parent_ws = context.get("workspace_path")
            if parent_ws:
                from myrm_agent_harness.agent.sub_agents.workspace_isolation import (
                    isolated_workspace,
                )

                isolation_ctx = isolated_workspace(str(parent_ws))
                child_ws, sync_back = await isolation_ctx.__aenter__()
                context["workspace_path"] = str(child_ws)
                context["_workspace_sync_back"] = sync_back

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
                    # Expose sync_back function for ISOLATED_COPY
                    if isolation_ctx and result.success:
                        sync_back_fn = context.get("_workspace_sync_back")
                        if sync_back_fn:
                            from dataclasses import replace as dc_replace

                            extra = (
                                dict(result.result)
                                if isinstance(result.result, dict)
                                else {"text": result.result}
                            )
                            extra["_workspace_sync_back"] = sync_back_fn
                            result = dc_replace(result, result=extra)
                    return result
                except TimeoutError:
                    retries_left -= 1
                    logger.warning(
                        "[subagent:%s] Timeout, retries_left=%d", task_id, retries_left
                    )
                    if retries_left > 0:
                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue
                    now = time.time()
                    return SubAgentResult(
                        success=False,
                        task_id=task_id,
                        agent_type=agent_type,
                        error=f"Timeout after {config.timeout_seconds}s",
                        duration_seconds=now - start_time,
                        completed_at=now,
                        status=SubAgentStatus.TIMED_OUT,
                        trace_id=trace_id,
                    )
                except SubagentBudgetExceededError as error:
                    now = time.time()
                    return SubAgentResult(
                        success=False,
                        task_id=task_id,
                        agent_type=agent_type,
                        error=str(error),
                        duration_seconds=now - start_time,
                        completed_at=now,
                        status=SubAgentStatus.CANCELLED_BY_BUDGET,
                        trace_id=trace_id,
                    )
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
                    err_result = SubAgentResult(
                        success=False,
                        task_id=task_id,
                        agent_type=agent_type,
                        error=f"{type(error).__name__}: {error}",
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
                    await isolation_ctx.__aexit__(None, None, None)
                except Exception as e:
                    logger.warning(
                        "[subagent:%s] Workspace isolation cleanup failed: %s",
                        task_id,
                        e,
                    )
            logger.debug("[subagent:%s] Resource cleanup complete", task_id)

    async def _inherit_parent_context(
        self, context: dict[str, object], task_id: str, parent_agent: BaseAgent
    ) -> dict[str, object]:
        """Ensure child context inherits essential fields from parent agent's last run context."""
        parent_ctx = getattr(parent_agent, "_last_context", None) or {}
        inherited_keys = ("session_id", "workspace_path", "approval_session_key")
        merged = dict(context)
        for key in inherited_keys:
            if key not in merged and key in parent_ctx:
                merged[key] = parent_ctx[key]
        return merged

    async def _run_single_attempt(
        self,
        task_id: str,
        agent_type: str,
        task_description: str,
        config: SubagentConfig,
        context: dict[str, object],
        tool_registry_getter: Callable[[], list[BaseTool]],
        start_time: float,
        parent_tracker: object,
        parent_taint: object,
        parent_agent: BaseAgent,
        cancel_flags: dict[str, bool],
        children_agents: dict[str, BaseAgent],
        fire_hook: Callable[..., object],
        hook_event_cls: type,
        trace_id: str = "",
        steering_token: SteeringToken | None = None,
        cancel_token: CancellationToken | None = None,
        resume_command: object | None = None,
        parent_progress_sink: ToolProgressSink | None = None,
        complexity_tier: str | None = None,
    ) -> SubAgentResult:
        """Execute one child-agent attempt. Raises on failure for retry."""
        parent_tools = tool_registry_getter()
        filtered_tools = filter_tools(config, parent_tools)
        if not filtered_tools and config.tools:
            logger.warning(
                "[subagent:%s] No tools after filtering for '%s'", task_id, agent_type
            )

        parent_manager = getattr(parent_agent, "_subagent_manager", None)
        current_depth = int(getattr(parent_manager, "current_depth", 0))
        child_agent = await build_child_agent(
            config,
            filtered_tools,
            task_description,
            parent_agent,
            current_depth,
            complexity_tier=complexity_tier,
        )
        await self._attach_child_delegation_tools(
            child_agent=child_agent,
            agent_type=agent_type,
            config=config,
        )
        children_agents[task_id] = child_agent
        messages: list[str] = []

        # Ensure subagent uses its own thread_id for checkpointing
        context["approval_session_key"] = task_id

        # Create event forwarder for progress tracking and event routing
        event_forwarder = SubagentEventForwarder(
            task_id,
            agent_type,
            config,
            start_time,
            parent_progress_sink=parent_progress_sink,
        )

        # Critical: Mark execution context as subagent to prevent approval deadlocks
        from myrm_agent_harness.agent.middlewares._session_context import (
            set_is_subagent,
            set_subagent_task_id,
        )
        from myrm_agent_harness.agent.streaming.types import AgentEventType

        set_is_subagent(True)
        set_subagent_task_id(task_id)
        logger.debug(
            "[subagent:%s] Context marked as subagent for approval safety", task_id
        )

        chat_history = []
        if config.context_mode == "fork" and getattr(
            parent_agent, "checkpointer", None
        ):
            try:
                parent_session_id = context.get("session_id") or getattr(
                    parent_agent, "session_id", None
                )
                if parent_session_id:
                    parent_state = await parent_agent.checkpointer.aget(
                        {"configurable": {"thread_id": parent_session_id}}
                    )
                    if parent_state and hasattr(parent_state, "values"):
                        raw_msgs = parent_state.values.get("messages", [])
                        if raw_msgs:
                            from langchain_core.messages import AIMessage

                            # 10/10 Scheme: Slice off the final AIMessage to prevent 'orphaned tool' 400 errors,
                            # while preserving all earlier messages identically to guarantee 100% Prefix Cache Hit.
                            chat_history = (
                                raw_msgs[:-1]
                                if isinstance(raw_msgs[-1], AIMessage)
                                else raw_msgs[:]
                            )
            except Exception as e:
                logger.warning(
                    "[subagent:%s] Failed to fork parent context: %s", task_id, e
                )

        try:
            query = resume_command if resume_command is not None else task_description
            if config.context_mode == "fork" and resume_command is None:
                # 10/10 Scheme: Recency Bias System Override.
                # Since we keep the parent's SystemMessage to hit the cache, we must override the persona here.
                persona_desc = config.system_prompt or "Assistant"
                system_override = (
                    f"\n\n[System Override] Ignore previous global role settings in the history. "
                    f"Your new designated role for this task is: {persona_desc}. "
                    f"Your specific task is: {task_description}\n\n"
                    + _HANDOVER_PROTOCOL_PROMPT
                )
                query = system_override

            async for event in child_agent.run(
                query=query,
                chat_history=chat_history,
                context=context,
                steering_token=steering_token,
                cancel_token=cancel_token,
            ):
                if cancel_flags.get(task_id, False):
                    logger.info(
                        "[subagent:%s] Cancel flag detected, exiting gracefully",
                        task_id,
                    )
                    await fire_hook(
                        hook_event_cls.SUBAGENT_CANCEL_START,
                        {
                            "task_id": task_id,
                            "agent_type": agent_type,
                            "elapsed_seconds": time.time() - start_time,
                            "trace_id": trace_id,
                        },
                    )
                    raise asyncio.CancelledError()

                event_type = event.get("type")

                if event_type == AgentEventType.MESSAGE.value:
                    content = event.get("data", "")
                    messages.append(
                        content if isinstance(content, str) else str(content)
                    )
                elif event_type == AgentEventType.ERROR.value:
                    raise RuntimeError(
                        f"Subagent error: {event.get('error', 'Unknown error')}"
                    )
                else:
                    await event_forwarder.handle_event(event)

                event_forwarder.check_budget()

            raw_result = "".join(messages)
        finally:
            set_is_subagent(False)
            set_subagent_task_id(None)
            logger.debug("[subagent:%s] Context reset (is_subagent=False)", task_id)

        # Check if child was interrupted (e.g. for approval)
        is_interrupted = False
        payload = None
        if getattr(child_agent, "checkpointer", None):
            try:
                state = await child_agent.checkpointer.aget(
                    {"configurable": {"thread_id": task_id}}
                )
                if state and getattr(state, "next", None):
                    is_interrupted = True
                    for task in getattr(state, "tasks", []):
                        for intr in getattr(task, "interrupts", []):
                            val = getattr(intr, "value", None)
                            if val:
                                payload = val
                                break
                        if payload:
                            break
            except Exception as e:
                logger.warning(
                    "[subagent:%s] Failed to check interrupt state: %s", task_id, e
                )

        duration = time.time() - start_time
        child_usage = (
            child_agent.last_run_stats.token_usage
            if child_agent.last_run_stats
            else None
        )

        if is_interrupted:
            action_type = (
                payload.get("action_type") if isinstance(payload, dict) else None
            )

            if action_type == "swarm_fission":
                logger.info(
                    "[subagent:%s] Yielded for Swarm Fission via GraphInterrupt.",
                    task_id,
                )
                return SubAgentResult(
                    success=True,
                    task_id=task_id,
                    agent_type=agent_type,
                    status=SubAgentStatus.YIELDED,
                    payload=payload,
                    checkpoint_data={"thread_id": task_id},
                    token_usage=child_usage,
                    duration_seconds=duration,
                    completed_at=time.time(),
                    trace_id=trace_id,
                )
            else:
                logger.info(
                    "[subagent:%s] Suspended for UI approval via GraphInterrupt.",
                    task_id,
                )
                return SubAgentResult(
                    success=True,
                    task_id=task_id,
                    agent_type=agent_type,
                    status=SubAgentStatus.PENDING_APPROVAL,
                    payload=payload,
                    token_usage=child_usage,
                    duration_seconds=duration,
                    completed_at=time.time(),
                    trace_id=trace_id,
                )

        # Parse handover BEFORE vault/truncate so we can strip the raw block
        # from the result string — the structured handover_state carries the data.
        handover_state = _parse_handover_state(raw_result, task_id)
        if handover_state is not None:
            raw_result = re.sub(
                r"<handover>.*?</handover>",
                "",
                raw_result,
                count=1,
                flags=re.DOTALL | re.IGNORECASE,
            ).rstrip()

        final_result = _auto_vault_or_truncate(
            raw_result,
            config,
            context,
            task_id,
            agent_type,
        )

        if parent_tracker and child_agent.last_run_stats:
            merge_child_stats(parent_tracker, child_agent.last_run_stats)

        child_taint = get_taint_tracker()
        if child_taint.is_tainted:
            for label in child_taint.labels:
                parent_taint.record(label)
            logger.debug(
                "[subagent:%s] Propagated taint labels to parent: %s",
                task_id,
                sorted(child_taint.labels),
            )

            taint_warning = (
                f"[SECURITY WARNING] This subagent operated in a tainted context "
                f"(labels: {', '.join(sorted(child_taint.labels))}). "
                f"Verify the following result independently before acting on it.\n\n"
            )
            final_result = taint_warning + final_result

        result = SubAgentResult(
            success=True,
            task_id=task_id,
            agent_type=agent_type,
            result=final_result,
            token_usage=child_usage,
            duration_seconds=duration,
            completed_at=time.time(),
            status=SubAgentStatus.COMPLETED,
            trace_id=trace_id,
            handover_state=handover_state,
        )
        await fire_hook(
            hook_event_cls.SUBAGENT_STOP,
            {
                "task_id": task_id,
                "agent_type": agent_type,
                "success": True,
                "result": final_result,
                "duration_seconds": duration,
                "trace_id": trace_id,
            },
        )
        total_tokens = child_usage.total_tokens if child_usage else 0
        logger.info(
            "[subagent:%s] Completed in %.1fs, tokens=%d, tools_called=%d",
            task_id,
            duration,
            total_tokens,
            event_forwarder.tool_count,
        )
        return result

    async def _attach_child_delegation_tools(
        self,
        *,
        child_agent: BaseAgent,
        agent_type: str,
        config: SubagentConfig,
    ) -> None:
        """Attach delegation tools that are scoped to the child agent's manager."""
        if config.delegation_role != DelegateRole.ORCHESTRATOR:
            return
        if config.delegation_catalog is None:
            logger.warning(
                "[subagent:%s] Orchestrator role requested but no delegation catalog is available",
                agent_type,
            )
            return

        from myrm_agent_harness.agent.meta_tools.spawn_subagent import (
            create_batch_delegate_tasks_tool,
            create_cancel_subagent_tool,
            create_delegate_parallel_tasks_tool,
            create_delegate_task_tool,
            create_list_subagents_tool,
            create_send_teammate_message_tool,
            create_steer_subagent_tool,
            update_delegate_task_description,
        )

        def child_tool_registry_getter() -> list[object]:
            return list(child_agent._cached_tools or child_agent.user_tools)

        allowed_types = (
            sorted(config.delegation_allowed_types)
            if config.delegation_allowed_types is not None
            else None
        )
        delegate_tool = create_delegate_task_tool(
            child_agent,
            tool_registry_getter=child_tool_registry_getter,
            catalog=config.delegation_catalog,
            parent_type=agent_type,
            allowed_types=allowed_types,
        )
        await update_delegate_task_description(
            delegate_tool, config.delegation_catalog, allowed_types
        )
        child_tool_by_name = {
            "delegate_task_tool": delegate_tool,
            "batch_delegate_tasks_tool": create_batch_delegate_tasks_tool(
                child_agent,
                tool_registry_getter=child_tool_registry_getter,
                catalog=config.delegation_catalog,
                parent_type=agent_type,
                allowed_types=allowed_types,
                delegate_tool=delegate_tool,
            ),
            "delegate_parallel_tasks_tool": create_delegate_parallel_tasks_tool(
                child_agent,
                tool_registry_getter=child_tool_registry_getter,
                catalog=config.delegation_catalog,
                parent_type=agent_type,
                allowed_types=allowed_types,
            ),
            "list_subagents_tool": create_list_subagents_tool(child_agent),
            "cancel_subagent_tool": create_cancel_subagent_tool(child_agent),
            "steer_subagent_tool": create_steer_subagent_tool(child_agent),
            "send_teammate_message_tool": create_send_teammate_message_tool(child_agent),
        }
        child_agent.add_tools(
            [
                child_tool_by_name[tool_name]
                for tool_name in DELEGATION_CAPABILITY_MANIFEST.orchestrator_child_tools
            ]
        )


# ---------------------------------------------------------------------------
# Cascade cancellation
# ---------------------------------------------------------------------------


def _cascade_cancel_descendants(child_agent: BaseAgent | None) -> None:
    """Cancel all descendant subagents when a child agent is cancelled.

    Without this, grandchild tasks spawned by an orchestrator-role child
    would continue running (and consuming tokens) after their parent is
    cancelled, since asyncio.Task.cancel() does not propagate to sibling
    tasks created via create_task().
    """
    if child_agent is None:
        return
    try:
        cancelled = child_agent.cancel_all_children()
        if cancelled > 0:
            logger.info(
                "[subagent] Cascade-cancelled %d descendant task(s)", cancelled,
            )
    except Exception:
        logger.debug("[subagent] Cascade cancel failed", exc_info=True)


# ---------------------------------------------------------------------------
# Result post-processing helpers
# ---------------------------------------------------------------------------

_SUMMARY_HEAD_CHARS = 2000
_SUMMARY_TAIL_CHARS = 1000


def _auto_vault_or_truncate(
    raw_result: str,
    config: SubagentConfig,
    context: dict[str, object],
    task_id: str,
    agent_type: str,
) -> str:
    """Store oversized subagent output in ArtifactVault; fall back to truncation.

    When ``config.auto_vault_threshold`` is set and the result exceeds it,
    the full output is persisted to the vault and a compact summary with a
    ``vault://`` pointer is returned so the parent agent (and frontend)
    can reference it without inflating context.
    """
    threshold = config.auto_vault_threshold
    if threshold is None or len(raw_result) <= threshold:
        return truncate_result(raw_result, config.max_result_tokens)

    workspace_path = context.get("workspace_path")
    if not workspace_path or not isinstance(workspace_path, str):
        logger.debug(
            "[subagent:%s] No workspace_path - falling back to truncation", task_id
        )
        return truncate_result(raw_result, config.max_result_tokens)

    try:
        from myrm_agent_harness.agent.artifacts.vault import ArtifactVault

        vault = ArtifactVault(workspace_path)
        pointer = vault.put(
            raw_result,
            f"subagent_{task_id}.md",
            "text/markdown",
            f"{agent_type} task result ({len(raw_result)} chars)",
        )

        head = raw_result[:_SUMMARY_HEAD_CHARS]
        tail_start = max(_SUMMARY_HEAD_CHARS, len(raw_result) - _SUMMARY_TAIL_CHARS)
        tail = raw_result[tail_start:]
        omitted = tail_start - _SUMMARY_HEAD_CHARS

        if omitted > 0:
            summary = f"{head}\n\n... ({omitted} chars omitted) ...\n\n{tail}"
        else:
            summary = head

        logger.info(
            "[subagent:%s] Result auto-vaulted (%d chars → %s)",
            task_id,
            len(raw_result),
            pointer,
        )
        return f"{summary}\n\n[Full result stored in vault: {pointer}]"
    except Exception:
        logger.warning(
            "[subagent:%s] Auto-vault failed, falling back to truncation",
            task_id,
            exc_info=True,
        )
        return truncate_result(raw_result, config.max_result_tokens)


def _parse_handover_state(raw_result: str, task_id: str) -> AgentHandoverState | None:
    """Extract ``<handover>...</handover>`` JSON block from raw subagent output."""
    match = re.search(
        r"<handover>(.*?)</handover>", raw_result, re.DOTALL | re.IGNORECASE
    )
    if not match:
        return None

    try:
        json_str = match.group(1).strip()
        if json_str.startswith("```json"):
            json_str = json_str[7:]
        elif json_str.startswith("```"):
            json_str = json_str[3:]
        if json_str.endswith("```"):
            json_str = json_str[:-3]
        json_str = json_str.strip()

        data = json.loads(json_str)
        return AgentHandoverState.from_dict(data)
    except Exception as e:
        logger.warning("[subagent:%s] Failed to parse handover state: %s", task_id, e)
        return None
