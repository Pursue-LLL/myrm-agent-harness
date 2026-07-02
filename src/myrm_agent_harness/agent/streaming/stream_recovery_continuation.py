"""Streaming steering, subagent, and goal continuation mixin.

[INPUT]
- agent.goals.continuation::check_continuation (POS: goal continuation verdict builder)
- agent.streaming.types::AgentEventType (POS: streaming event type constants)

[OUTPUT]
- StreamContinuationRecoveryMixin: handles steering, teammate P2P drain, subagent completion events, and goal continuation.

[POS]
Streaming continuation layer. Handles external steering, subagent notifications, and goal lifecycle continuation without changing prompt-cache behavior.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.messages import AnyMessage, BaseMessage

    from myrm_agent_harness.agent.goals.types import Goal, GoalExecutionSummary
    from myrm_agent_harness.agent.streaming.stream_compactor import StreamCompactor
    from myrm_agent_harness.agent.streaming.stream_executor import StreamContext

logger = get_agent_logger(__name__)

_BACKGROUND_RECOVERY_TASKS: set[asyncio.Future[None]] = set()


def _track_background_recovery_task(task: asyncio.Future[None]) -> None:
    """Keep recovery side-effect tasks alive and report their failures."""
    _BACKGROUND_RECOVERY_TASKS.add(task)
    task.add_done_callback(_handle_background_recovery_task_done)


def _handle_background_recovery_task_done(task: asyncio.Future[None]) -> None:
    _BACKGROUND_RECOVERY_TASKS.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Stream recovery background task failed")


class StreamContinuationRecoveryMixin:
    """Continuation-related stream recovery handlers."""

    _ctx: StreamContext
    _compactor: StreamCompactor
    streaming_final_answer: bool

    async def _check_and_emit_trace_slice(self, force_flush: bool = False) -> None:
        """Type hint stub; implementation provided by StreamExecutor."""
        pass

    async def _handle_steering(self, collected_messages: list[BaseMessage]) -> bool:
        """Handle steering injection and trigger a new turn when needed."""
        ctx = self._ctx
        if ctx.stats.was_cancelled or ctx.steering_token is None:
            return False

        if not (ctx.steering_token.steering_applied or ctx.steering_token.has_pending):
            return False

        all_steering = ctx.steering_token.collect_all_steering_messages()
        if not all_steering:
            return False

        if isinstance(ctx.agent_input, Command):
            logger.warning(" Resume mode cannot inject steering — skipping")
            return False

        assert not isinstance(ctx.agent_input, Command)
        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))

        logger.warning(
            " Steering: injecting %d message(s) for new turn",
            len(all_steering),
        )
        messages.clear()
        messages.extend(collected_messages)
        for msg_text in all_steering:
            messages.append(HumanMessage(content=msg_text))

        messages_dict["messages"] = cast("list[AnyMessage]", messages)
        self.streaming_final_answer = False
        truncated = [m[:200] for m in all_steering]
        await self._compactor.put(
            {
                "type": AgentEventType.STEERING.value,
                "data": {
                    "count": len(all_steering),
                    "messages": truncated,
                },
                "messageId": ctx.message_id,
            }
        )
        return True

    async def _handle_teammate_messages(self, collected_messages: list[BaseMessage]) -> bool:
        """Drain P2P teammate inbox into the next subagent turn and emit SSE."""
        ctx = self._ctx
        if ctx.stats.was_cancelled or ctx.drain_teammate_messages is None:
            return False
        if isinstance(ctx.agent_input, Command):
            return False

        injection = ctx.drain_teammate_messages()
        if not injection:
            return False

        from myrm_agent_harness.agent.middlewares._session_context import (
            get_subagent_task_id,
        )

        task_id = get_subagent_task_id() or ""
        from myrm_agent_harness.agent.coordination.mailbox import (
            get_last_drained_messages,
        )

        drained = get_last_drained_messages(task_id)
        session_id = str(ctx.merged_context.get("session_id", ""))

        assert not isinstance(ctx.agent_input, Command)
        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))
        messages.clear()
        messages.extend(collected_messages)
        messages.append(HumanMessage(content=injection))
        messages_dict["messages"] = cast("list[AnyMessage]", messages)
        self.streaming_final_answer = False

        for msg in drained:
            await self._compactor.put(
                {
                    "type": "teammate_message",
                    "data": {
                        **msg.to_dict(),
                        "chat_id": session_id,
                    },
                    "messageId": ctx.message_id,
                }
            )
        return True

    async def _handle_subagent_notifications(self, collected_messages: list[BaseMessage]) -> bool:
        """Drain subagent completion notifications and emit SSE event."""
        ctx = self._ctx
        if ctx.stats.was_cancelled or ctx.drain_subagent_notifications is None:
            return False

        if isinstance(ctx.agent_input, Command):
            return False

        merged_text = ctx.drain_subagent_notifications()
        if not merged_text:
            return False

        logger.info(
            " Subagent completion detected - emitting SSE event only",
            extra={"notification_preview": merged_text[:100]},
        )

        await self._compactor.put(
            {
                "type": AgentEventType.SUBAGENT_COMPLETION.value,
                "data": merged_text,
                "messageId": ctx.message_id,
            }
        )
        return False

    async def _handle_goal_continuation(
        self,
        collected_messages: list[BaseMessage],
        tools_called_this_turn: bool,
        net_tokens_this_turn: int,
        cost_this_turn: float,
        time_this_turn_seconds: int,
    ) -> bool:
        """Check if the active goal should automatically continue to the next turn."""
        ctx = self._ctx
        goal_provider = ctx.goal_provider

        if not goal_provider:
            return False

        if isinstance(ctx.agent_input, Command):
            return False

        from myrm_agent_harness.agent.goals.continuation import check_continuation

        session_id = str(ctx.merged_context.get("chat_id", ctx.merged_context.get("session_id", ctx.message_id)))
        decision = await check_continuation(
            goal_provider=goal_provider,
            session_id=session_id,
            cancel_token=ctx.cancel_token,
            steering_token=ctx.steering_token,
            collected_messages=collected_messages,
            tools_called_this_turn=tools_called_this_turn,
            net_tokens_this_turn=net_tokens_this_turn,
            cost_this_turn=cost_this_turn,
            time_this_turn_seconds=time_this_turn_seconds,
        )

        goal = None
        if decision.verdict != "no_goal":
            goal = await goal_provider.get_latest_goal(session_id)
            goal_data: dict[str, object] = {}
            summary: GoalExecutionSummary | None = None
            if goal:
                if decision.verdict in ("done", "budget", "convergence"):
                    summary = self._assemble_execution_summary(goal)
                    goal.metadata["execution_summary"] = summary.to_dict()
                goal_data = goal.to_dict()
            goal_data["verdict"] = decision.verdict
            goal_data["reason"] = decision.reason
            goal_data["should_continue"] = decision.should_continue

            await self._compactor.put(
                {
                    "type": AgentEventType.GOAL_STATUS.value,
                    "data": goal_data,
                    "messageId": ctx.message_id,
                }
            )

        if decision.verdict in ("done", "budget", "convergence") and hasattr(self, "_check_and_emit_trace_slice"):
            _track_background_recovery_task(asyncio.create_task(self._check_and_emit_trace_slice(force_flush=True)))

        if decision.should_continue:
            messages_dict = ctx.agent_input
            messages = cast(list["BaseMessage"], messages_dict.get("messages", []))
            messages.clear()
            messages.extend(collected_messages)
            messages_dict["messages"] = cast("list[AnyMessage]", messages)
            self.streaming_final_answer = False
            return True

        if decision.verdict in ("done", "budget", "convergence") and ctx.on_goal_terminal and goal and summary:
            _track_background_recovery_task(
                asyncio.create_task(ctx.on_goal_terminal(goal, list(collected_messages), summary))
            )

        # loop_restart: trigger a new agent stream with fresh context
        if decision.verdict == "loop_restart" and goal and ctx.on_loop_restart:
            _track_background_recovery_task(
                asyncio.create_task(ctx.on_loop_restart(session_id, goal))
            )

        return False

    def _assemble_execution_summary(self, goal: Goal) -> GoalExecutionSummary:
        """Assemble GoalExecutionSummary from LoopGuard records and Goal accounting."""
        from myrm_agent_harness.agent.goals.types import GoalExecutionSummary
        from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
            get_loop_guard,
        )
        from myrm_agent_harness.agent.security.guards.loop_guard_types import (
            TOOL_SEMANTIC_MAP,
            SuccessLevel,
            ToolGroup,
            VerificationCategory,
        )

        guard = get_loop_guard()
        records = list(guard._window)

        files: set[str] = set()
        verifications: list[dict[str, object]] = []
        browser_checks = 0

        for rec in records:
            group = TOOL_SEMANTIC_MAP.get(rec.tool_name, ToolGroup.OTHER)

            if group == ToolGroup.WRITE:
                path = str(rec.args.get("path", ""))
                if path:
                    files.add(path)
            elif group == ToolGroup.BROWSER:
                browser_checks += 1
            elif rec.verification_type is not None:
                cmd = str(rec.args.get("command", rec.tool_name))
                if rec.success_level == SuccessLevel.EMPTY_OK and rec.verification_type == VerificationCategory.TEST:
                    passed = False
                    cmd += " (empty: no tests executed)"
                else:
                    passed = rec.success_level is not None and rec.success_level != SuccessLevel.FAILURE
                verifications.append({"cmd": cmd, "passed": passed})

        return GoalExecutionSummary(
            files_modified=tuple(sorted(files)),
            verifications=tuple(verifications),
            browser_checks=browser_checks,
            total_tokens=goal.tokens_used,
            total_cost_usd=goal.cost_usd,
            execution_duration_s=float(goal.time_used_seconds),
            turns_used=goal.turns_used,
        )


__all__ = ["StreamContinuationRecoveryMixin"]
