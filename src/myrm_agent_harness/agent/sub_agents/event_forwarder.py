"""Subagent event forwarding and progress tracking.

[INPUT]
- agent.types::AgentEventType (POS: Agent事件类型枚举)
- agent.sub_agents.types::SubagentBudgetExceededError, SubagentConfig (POS: 子Agent配置与异常类型)
- utils.runtime.progress_sink (POS: 工具进度事件sink)
- utils.logger_utils (POS: 日志工具)

[OUTPUT]
- SubagentEventForwarder: 子agent事件转发器(14种事件类型自动转发及预算拦截, staleness检测)
- Running token_usage projection via SUBAGENT_PROGRESS + optional observability callback
- Staleness detection: is_stale(), _check_and_emit_stale(), SUBAGENT_STALE event emission

[POS]
Subagent event forwarder. Translates subagent event types into SUBAGENT_PROGRESS, SUBAGENT_LOG, SUBAGENT_STALE, UI_UPDATE, and ARTIFACT_CONTENT events. Includes staleness detection with configurable thresholds.

"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.sub_agents.types import SubagentBudgetExceededError, SubagentConfig
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.runtime.progress_sink import ToolProgressSink, get_tool_progress_sink

if TYPE_CHECKING:
    pass

logger = get_agent_logger(__name__)


class SubagentEventForwarder:
    """Forward subagent events to parent context with progress tracking."""

    def __init__(
        self,
        task_id: str,
        agent_type: str,
        config: SubagentConfig,
        start_time: float,
        parent_progress_sink: ToolProgressSink | None = None,
        on_running_token_usage: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self.task_id = task_id
        self.agent_type = agent_type
        self.config = config
        self.start_time = start_time
        # Subagent runs in a child task: ContextVar sink targets the child queue; SSE uses the parent queue.
        self._parent_progress_sink = parent_progress_sink
        self._on_running_token_usage = on_running_token_usage

        # Progress tracking state
        self.cumulative_tokens = 0
        self.tool_count = 0
        self.last_progress = -1.0
        self.last_emit_time = 0.0
        self.current_tool_name: str | None = None
        self.token_history: list[tuple[float, int]] = []

        # Staleness detection
        self._last_effective_progress_at: float = start_time
        self._in_tool: bool = False
        self._stale_emitted: bool = False

    def _mark_progress(self) -> None:
        """Record that effective progress (token growth or tool completion) occurred."""
        self._last_effective_progress_at = time.time()
        self._stale_emitted = False

    def is_stale(self) -> bool:
        """Check whether this subagent appears stalled (no token/tool progress)."""
        threshold = self.config.stale_after_seconds
        if self._in_tool:
            threshold *= self.config.in_tool_stale_multiplier
        return (time.time() - self._last_effective_progress_at) > threshold

    def _active_sink(self) -> ToolProgressSink | None:
        if self._parent_progress_sink is not None:
            return self._parent_progress_sink
        return get_tool_progress_sink()

    async def handle_event(self, event: dict[str, object]) -> None:
        """Handle a single event from child agent.

        Dispatches to specific handlers based on event type.
        """
        event_type = event.get("type")

        if event_type == AgentEventType.TOKEN_USAGE.value:
            await self._handle_token_usage(event)
        elif event_type == AgentEventType.TOOL_START.value:
            await self._handle_tool_start(event)
        elif event_type == AgentEventType.TOOL_END.value:
            await self._handle_tool_end(event)
        elif event_type == AgentEventType.TOOL_FAILURE.value:
            await self._handle_tool_failure(event)
        elif event_type == AgentEventType.TOOL_CANCELLED.value:
            await self._handle_tool_cancelled(event)
        elif event_type == AgentEventType.TOOL_TIMEOUT.value:
            await self._handle_tool_timeout(event)
        elif event_type == AgentEventType.TOOL_RETRY.value:
            await self._handle_tool_retry(event)
        elif event_type == AgentEventType.REASONING.value:
            await self._handle_reasoning(event)
        elif event_type == AgentEventType.TASKS_STEPS.value:
            await self._handle_tasks_steps(event)
        elif event_type == AgentEventType.UI_UPDATE.value:
            await self._handle_ui_update(event)
        elif event_type == AgentEventType.ARTIFACT_CONTENT.value:
            await self._handle_artifact_content(event)
        elif event_type == AgentEventType.STATUS.value:
            await self._handle_status(event)

    async def _handle_token_usage(self, event: dict[str, object]) -> None:
        """Handle TOKEN_USAGE event and emit progress updates."""
        usage_dict: dict[str, object] = {}
        prev_tokens = self.cumulative_tokens
        token_data = event.get("data")
        if isinstance(token_data, dict):
            raw_usage = token_data.get("usage")
            if isinstance(raw_usage, dict):
                usage_dict = raw_usage
                self.cumulative_tokens = int(raw_usage.get("total_tokens", self.cumulative_tokens) or 0)
                self.total_cost_usd = raw_usage.get("total_cost_usd", getattr(self, "total_cost_usd", 0.0))

        if self.cumulative_tokens > prev_tokens:
            self._mark_progress()

        running_usage = self._build_running_token_usage(usage_dict)

        sink = self._active_sink()

        current_time = time.time()
        elapsed_seconds = current_time - self.start_time

        self.token_history.append((current_time, self.cumulative_tokens))
        if len(self.token_history) > 20:
            self.token_history.pop(0)

        if self.config.progress_calculator:
            progress_data = self.config.progress_calculator.calculate_progress(
                current_tokens=self.cumulative_tokens,
                budget_tokens=self.config.budget_tokens,
                tool_count=self.tool_count,
                elapsed_seconds=elapsed_seconds,
            )
            progress = float(progress_data.get("progress", 0.0))
        else:
            progress, progress_data = self._calculate_default_progress(elapsed_seconds)

        time_delta = current_time - self.last_emit_time

        if progress == self.last_progress:
            should_emit = time_delta >= 1.0
        else:
            progress_delta = abs(progress - self.last_progress)
            should_emit = progress_delta >= 0.05 or time_delta >= 1.0

        if should_emit or self.last_progress < 0:
            if running_usage is not None and self._on_running_token_usage is not None:
                self._on_running_token_usage(running_usage)
            if not sink:
                self.last_progress = progress
                self.last_emit_time = current_time
                return
            try:
                event_data = {
                    "task_id": self.task_id,
                    "agent_type": self.agent_type,
                    "message": f"{int(progress * 100)}%",
                }
                event_data.update(progress_data)
                if running_usage is not None:
                    event_data["token_usage"] = running_usage

                await sink.emit(
                    {
                        "type": AgentEventType.SUBAGENT_PROGRESS.value,
                        "data": event_data,
                    }
                )
                self.last_progress = progress
                self.last_emit_time = current_time
            except Exception as exc:
                logger.warning("Failed to emit SUBAGENT_PROGRESS for %s: %s", self.task_id, exc)

        await self._check_and_emit_stale(sink)

    async def _check_and_emit_stale(self, sink: ToolProgressSink | None) -> None:
        """Emit SUBAGENT_STALE once when no effective progress for configured threshold."""
        if self._stale_emitted or not self.is_stale():
            return
        self._stale_emitted = True
        elapsed_s = round(time.time() - self.start_time, 1)
        stale_duration_s = round(time.time() - self._last_effective_progress_at, 1)
        stale_data = {
            "task_id": self.task_id,
            "agent_type": self.agent_type,
            "stale_duration_seconds": stale_duration_s,
            "elapsed_seconds": elapsed_s,
            "wasted_tokens": self.cumulative_tokens,
            "wasted_cost_usd": getattr(self, "total_cost_usd", 0.0),
            "current_tool": self.current_tool_name,
            "auto_cancel": self.config.stale_auto_cancel,
        }
        logger.warning(
            "[subagent:%s] Stale detected: no progress for %.0fs (elapsed=%.0fs, tokens=%d)",
            self.task_id, stale_duration_s, elapsed_s, self.cumulative_tokens,
        )
        if sink:
            try:
                await sink.emit({
                    "type": AgentEventType.SUBAGENT_STALE.value,
                    "data": stale_data,
                })
            except Exception as exc:
                logger.warning("Failed to emit SUBAGENT_STALE for %s: %s", self.task_id, exc)

        self._publish_stale_lifecycle_event(stale_data)

    def _publish_stale_lifecycle_event(self, stale_data: dict[str, object]) -> None:
        """Publish stale event to global lifecycle bus for IM notification bridging."""
        try:
            from myrm_agent_harness.agent.sub_agents.manager import ACTIVE_SUBAGENT_SESSIONS
            from myrm_agent_harness.runtime.events import SubagentLifecycleEvent, get_event_bus
            from myrm_agent_harness.runtime.events.system_events import SubagentLifecycleData

            session_id = ACTIVE_SUBAGENT_SESSIONS.get(self.task_id, "")
            if not session_id:
                return
            get_event_bus().publish(
                SubagentLifecycleEvent(
                    event_name="stale",
                    task_id=self.task_id,
                    session_id=session_id,
                    data=SubagentLifecycleData(
                        agent_type=self.agent_type,
                        extra=stale_data,
                    ),
                )
            )
        except Exception as exc:
            logger.debug("Failed to publish stale lifecycle event: %s", exc)

    def _build_running_token_usage(self, usage_dict: dict[str, object]) -> dict[str, object] | None:
        if self.cumulative_tokens <= 0:
            return None
        payload: dict[str, object] = {"total_tokens": self.cumulative_tokens}
        for key in ("input_tokens", "output_tokens", "total_cost_usd", "cached_tokens"):
            value = usage_dict.get(key)
            if value is not None:
                payload[key] = value
        return payload

    def _calculate_default_progress(self, elapsed_seconds: float) -> tuple[float, dict[str, object]]:
        """Calculate default progress using token-based or tool-based estimation."""
        if self.config.budget_tokens:
            progress = min(1.0, self.cumulative_tokens / self.config.budget_tokens)
            is_estimated = False
        else:
            progress = min(1.0, self.tool_count / 8.0)
            is_estimated = True

        eta_seconds = None
        if self.config.budget_tokens and len(self.token_history) >= 2:
            time_delta = self.token_history[-1][0] - self.token_history[0][0]
            token_delta = self.token_history[-1][1] - self.token_history[0][1]
            if time_delta > 0 and token_delta > 0:
                tokens_per_second = token_delta / time_delta
                remaining_tokens = self.config.budget_tokens - self.cumulative_tokens
                if remaining_tokens > 0 and tokens_per_second > 0:
                    eta_seconds = int(remaining_tokens / tokens_per_second)

        progress_data = {
            "progress": progress,
            "current_tokens": self.cumulative_tokens,
            "budget_tokens": self.config.budget_tokens,
            "tool_count": self.tool_count,
            "is_estimated": is_estimated,
            "current_step": self.current_tool_name,
        }
        if eta_seconds is not None:
            progress_data["eta_seconds"] = eta_seconds
            mins = eta_seconds // 60
            secs = eta_seconds % 60
            progress_data["eta_readable"] = f"{mins}m{secs}s" if mins > 0 else f"{secs}s"

        return progress, progress_data

    async def _handle_tool_start(self, event: dict[str, object]) -> None:
        """Handle TOOL_START event."""
        tool_name = event.get("data", {}).get("tool_name", "unknown")
        self.current_tool_name = tool_name
        self._in_tool = True

        sink = self._active_sink()
        if not sink:
            return

        try:
            await sink.emit(
                {
                    "type": AgentEventType.SUBAGENT_LOG.value,
                    "data": {
                        "task_id": self.task_id,
                        "agent_type": self.agent_type,
                        "agent_instance": f"{self.agent_type}-{self.task_id[:4]}",
                        "level": "INFO",
                        "message": "calling_tool",
                        "tool_name": tool_name,
                    },
                }
            )
        except Exception as exc:
            logger.warning("Failed to emit SUBAGENT_LOG for %s: %s", self.task_id, exc)

    async def _handle_tool_end(self, event: dict[str, object]) -> None:
        """Handle TOOL_END event."""
        self.tool_count += 1
        self._in_tool = False
        self._mark_progress()

        sink = self._active_sink()
        if not sink:
            return

        tool_name = event.get("data", {}).get("tool_name", "unknown")
        duration_ms = event.get("duration_ms", 0)

        try:
            await sink.emit(
                {
                    "type": AgentEventType.SUBAGENT_LOG.value,
                    "data": {
                        "task_id": self.task_id,
                        "agent_type": self.agent_type,
                        "agent_instance": f"{self.agent_type}-{self.task_id[:4]}",
                        "level": "INFO",
                        "message": "tool_execution_completed",
                        "tool_name": tool_name,
                        "duration_ms": duration_ms,
                    },
                }
            )
        except Exception as exc:
            logger.warning("Failed to emit SUBAGENT_LOG for %s: %s", self.task_id, exc)

    async def _handle_tool_failure(self, event: dict[str, object]) -> None:
        """Handle TOOL_FAILURE event."""
        self._in_tool = False
        sink = self._active_sink()
        if not sink:
            return

        tool_name = event.get("data", {}).get("tool_name", "unknown")
        error_msg = event.get("data", {}).get("error", "Unknown error")

        try:
            await sink.emit(
                {
                    "type": AgentEventType.SUBAGENT_LOG.value,
                    "data": {
                        "task_id": self.task_id,
                        "agent_type": self.agent_type,
                        "agent_instance": f"{self.agent_type}-{self.task_id[:4]}",
                        "level": "ERROR",
                        "message": f"Tool failed: {tool_name} - {error_msg}",
                        "tool_name": tool_name,
                        "error": error_msg,
                    },
                }
            )
        except Exception as exc:
            logger.warning("Failed to emit TOOL_ERROR log for %s: %s", self.task_id, exc)

    async def _handle_tool_cancelled(self, event: dict[str, object]) -> None:
        """Handle TOOL_CANCELLED event."""
        self._in_tool = False
        sink = self._active_sink()
        if not sink:
            return

        tool_name = event.get("data", {}).get("tool_name", "unknown")
        cancel_reason = event.get("data", {}).get("cancel_reason", "unknown")
        duration_ms = event.get("data", {}).get("duration_ms", 0)

        try:
            await sink.emit(
                {
                    "type": AgentEventType.SUBAGENT_LOG.value,
                    "data": {
                        "task_id": self.task_id,
                        "agent_type": self.agent_type,
                        "agent_instance": f"{self.agent_type}-{self.task_id[:4]}",
                        "level": "WARNING",
                        "message": f"Tool cancelled: {tool_name} ({cancel_reason}) - {duration_ms}ms",
                        "tool_name": tool_name,
                        "cancel_reason": cancel_reason,
                        "duration_ms": duration_ms,
                    },
                }
            )
        except Exception as exc:
            logger.warning("Failed to emit TOOL_CANCELLED log for %s: %s", self.task_id, exc)

    async def _handle_tool_timeout(self, event: dict[str, object]) -> None:
        """Handle TOOL_TIMEOUT event."""
        self._in_tool = False
        sink = self._active_sink()
        if not sink:
            return

        tool_name = event.get("data", {}).get("tool_name", "unknown")
        timeout_seconds = event.get("data", {}).get("timeout_seconds", 0)
        attempt = event.get("data", {}).get("attempt", 1)
        elapsed_ms = event.get("data", {}).get("elapsed_ms", 0)

        try:
            await sink.emit(
                {
                    "type": AgentEventType.SUBAGENT_LOG.value,
                    "data": {
                        "task_id": self.task_id,
                        "agent_type": self.agent_type,
                        "agent_instance": f"{self.agent_type}-{self.task_id[:4]}",
                        "level": "WARNING",
                        "message": f"Tool timeout: {tool_name} (attempt {attempt}, {timeout_seconds}s limit) - {elapsed_ms}ms",
                        "tool_name": tool_name,
                        "timeout_seconds": timeout_seconds,
                        "attempt": attempt,
                        "elapsed_ms": elapsed_ms,
                    },
                }
            )
        except Exception as exc:
            logger.warning("Failed to emit TOOL_TIMEOUT log for %s: %s", self.task_id, exc)

    async def _handle_tool_retry(self, event: dict[str, object]) -> None:
        """Handle TOOL_RETRY event."""
        sink = self._active_sink()
        if not sink:
            return

        tool_name = event.get("data", {}).get("tool_name", "unknown")
        attempt = event.get("data", {}).get("attempt", 1)
        max_attempts = event.get("data", {}).get("max_attempts", 2)
        reason = event.get("data", {}).get("reason", "unknown")
        backoff_seconds = event.get("data", {}).get("backoff_seconds", 0)

        try:
            await sink.emit(
                {
                    "type": AgentEventType.SUBAGENT_LOG.value,
                    "data": {
                        "task_id": self.task_id,
                        "agent_type": self.agent_type,
                        "agent_instance": f"{self.agent_type}-{self.task_id[:4]}",
                        "level": "INFO",
                        "message": f"Tool retry: {tool_name} (attempt {attempt}/{max_attempts}, reason: {reason}) - retry in {backoff_seconds:.1f}s",
                        "tool_name": tool_name,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "reason": reason,
                        "backoff_seconds": backoff_seconds,
                    },
                }
            )
        except Exception as exc:
            logger.warning("Failed to emit TOOL_RETRY log for %s: %s", self.task_id, exc)

    async def _handle_reasoning(self, event: dict[str, object]) -> None:
        """Handle REASONING event."""
        sink = self._active_sink()
        if not sink:
            return

        content = event.get("data", "")
        content_str = str(content)

        try:
            await sink.emit(
                {
                    "type": AgentEventType.SUBAGENT_LOG.value,
                    "data": {
                        "task_id": self.task_id,
                        "agent_type": self.agent_type,
                        "agent_instance": f"{self.agent_type}-{self.task_id[:4]}",
                        "level": "DEBUG",
                        "message": f" Thinking: {content_str[:100]}{'...' if len(content_str) > 100 else ''}",
                        "reasoning_content": content_str,
                    },
                }
            )
        except Exception as exc:
            logger.warning("Failed to emit REASONING log for %s: %s", self.task_id, exc)

    async def _handle_tasks_steps(self, event: dict[str, object]) -> None:
        """Handle TASKS_STEPS event."""
        sink = self._active_sink()
        if not sink:
            return

        step_key = event.get("step_key", "unknown")
        tool_name = event.get("tool_name")
        is_error = event.get("status") == "error"
        err = event.get("error")

        payload: dict[str, object] = {
            "task_id": self.task_id,
            "agent_type": self.agent_type,
            "agent_instance": f"{self.agent_type}-{self.task_id[:4]}",
            "level": "ERROR" if is_error else "INFO",
            "message": step_key,
            "step_key": step_key,
            "tool_name": tool_name,
        }

        if self.config.display_name:
            payload["display_name"] = self.config.display_name

        if self.config.theme_color:
            payload["theme_color"] = self.config.theme_color

        if is_error and err is not None:
            payload["error"] = err

        try:
            await sink.emit(
                {
                    "type": AgentEventType.SUBAGENT_LOG.value,
                    "data": payload,
                }
            )
        except Exception as exc:
            logger.warning("Failed to emit TASKS_STEPS log for %s: %s", self.task_id, exc)

    async def _handle_ui_update(self, event: dict[str, object]) -> None:
        """Handle UI_UPDATE event.

        Strips child-agent messageId so the parent sink injects the correct
        parent messageId via ``setdefault``, ensuring the frontend can locate
        the owning assistant message.
        """
        sink = self._active_sink()
        if not sink:
            return

        try:
            event.pop("messageId", None)
            await sink.emit(event)
        except Exception as exc:
            logger.warning("Failed to emit UI_UPDATE for %s: %s", self.task_id, exc)

    async def _handle_artifact_content(self, event: dict[str, object]) -> None:
        """Handle ARTIFACT_CONTENT event (live file preview from child agent).

        Strips child-agent messageId so the parent sink injects the correct
        parent messageId, enabling real-time streaming preview on the frontend.
        """
        sink = self._active_sink()
        if not sink:
            return

        try:
            event.pop("messageId", None)
            await sink.emit(event)
        except Exception as exc:
            logger.warning("Failed to emit ARTIFACT_CONTENT for %s: %s", self.task_id, exc)

    async def _handle_status(self, event: dict[str, object]) -> None:
        """Handle STATUS event."""
        sink = self._active_sink()
        if not sink:
            return

        status_data = event.get("data", {})
        if isinstance(status_data, dict):
            message = status_data.get("message", "")
        else:
            message = str(status_data)

        try:
            await sink.emit(
                {
                    "type": AgentEventType.SUBAGENT_LOG.value,
                    "data": {
                        "task_id": self.task_id,
                        "agent_type": self.agent_type,
                        "agent_instance": f"{self.agent_type}-{self.task_id[:4]}",
                        "level": "INFO",
                        "message": f"ℹ {message}",
                    },
                }
            )
        except Exception as exc:
            logger.warning("Failed to emit STATUS log for %s: %s", self.task_id, exc)

    def check_budget(self) -> None:
        """Check if token or USD budget is exceeded and raise error."""
        if self.config.budget_tokens and self.cumulative_tokens > self.config.budget_tokens:
            raise SubagentBudgetExceededError(
                f"[subagent:{self.task_id}] Budget exceeded: {self.cumulative_tokens}/{self.config.budget_tokens} tokens"
            )

        if self.config.max_cost_usd and getattr(self, "total_cost_usd", 0.0) > self.config.max_cost_usd:
            raise SubagentBudgetExceededError(
                f"[subagent:{self.task_id}] Budget exceeded: {getattr(self, 'total_cost_usd', 0.0):.4f}/{self.config.max_cost_usd} USD"
            )
