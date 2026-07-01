"""SubagentExecutor single-attempt execution APIs.

[INPUT]
- .executor_helpers (POS: fork filter, vault, handover parsing)
- .builder, .event_forwarder (POS: child construction and event routing)

[OUTPUT]
- SubagentExecutorAttemptMixin._inherit_parent_context
- SubagentExecutorAttemptMixin._run_single_attempt

[POS]
One child-agent run attempt including fork context and result post-processing.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.security.guards.taint_tracker import get_taint_tracker
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.runtime.progress_sink import ToolProgressSink
from myrm_agent_harness.utils.runtime.steering import SteeringToken

from .builder import (
    _HANDOVER_PROTOCOL_PROMPT,
    build_child_agent,
    filter_tools,
    merge_child_stats,
)
from .event_forwarder import SubagentEventForwarder
from .executor_helpers import (
    _auto_vault_or_truncate,
    _filter_fork_messages,
    _parse_handover_state,
)
from .types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.utils import CancellationToken

logger = get_agent_logger(__name__)


class SubagentExecutorAttemptMixin:
    """Execute a single subagent attempt."""

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
            logger.warning("[subagent:%s] No tools after filtering for '%s'", task_id, agent_type)

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
        logger.debug("[subagent:%s] Context marked as subagent for approval safety", task_id)

        chat_history = []
        if config.context_mode == "fork" and getattr(parent_agent, "checkpointer", None):
            try:
                parent_session_id = context.get("session_id") or getattr(parent_agent, "session_id", None)
                if parent_session_id:
                    parent_state = await parent_agent.checkpointer.aget(
                        {"configurable": {"thread_id": parent_session_id}}
                    )
                    if parent_state and hasattr(parent_state, "values"):
                        raw_msgs = parent_state.values.get("messages", [])
                        if raw_msgs:
                            raw_count = len(raw_msgs)
                            chat_history = _filter_fork_messages(raw_msgs, config.max_fork_tokens)
                            logger.info(
                                "[subagent:%s] Fork context filtered: %d → %d messages",
                                task_id, raw_count, len(chat_history),
                            )
            except Exception as e:
                logger.warning("[subagent:%s] Failed to fork parent context: %s", task_id, e)

        try:
            query = resume_command if resume_command is not None else task_description
            if config.context_mode == "fork" and resume_command is None:
                # 10/10 Scheme: Recency Bias System Override.
                # Since we keep the parent's SystemMessage to hit the cache, we must override the persona here.
                persona_desc = config.system_prompt or "Assistant"
                system_override = (
                    f"\n\n[System Override] Ignore previous global role settings in the history. "
                    f"Your new designated role for this task is: {persona_desc}. "
                    f"Your specific task is: {task_description}\n\n" + _HANDOVER_PROTOCOL_PROMPT
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
                    messages.append(content if isinstance(content, str) else str(content))
                elif event_type == AgentEventType.ERROR.value:
                    raise RuntimeError(f"Subagent error: {event.get('error', 'Unknown error')}")
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
                state = await child_agent.checkpointer.aget({"configurable": {"thread_id": task_id}})
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
                logger.warning("[subagent:%s] Failed to check interrupt state: %s", task_id, e)

        duration = time.time() - start_time
        child_usage = child_agent.last_run_stats.token_usage if child_agent.last_run_stats else None

        if is_interrupted:
            action_type = payload.get("action_type") if isinstance(payload, dict) else None

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
