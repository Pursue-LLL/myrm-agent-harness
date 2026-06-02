"""Tool call broadcaster — Hook listener that publishes tool call events.

[INPUT]
- agent.hooks.types::HookEvent (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- agent.hooks.types::HookResult (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- observability.event_bus::EventBus (POS: Framework-level event bus. Business layer subscribes for transport adapters.)

[OUTPUT]
- ToolCallBroadcaster: Hook listener that broadcasts tool calls to EventBus
- register_to_hook_registry(): Helper to register broadcaster

[POS]
Framework-level Hook listener. Automatically publishes tool call events to EventBus
whenever tools are executed. Integrates with EventLog for persistence.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.hooks.types import HookResult
from myrm_agent_harness.agent.observability.event_bus import EventBus
from myrm_agent_harness.agent.observability.types import ToolCallEventData, _truncate_for_event
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.backends.skills.protocols import resolved_skill_versions_var
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.agent.event_log.logger import EventLogger
    from myrm_agent_harness.agent.hooks.registry import HookRegistry

logger = get_agent_logger(__name__)


class ToolCallBroadcaster:
    """Hook listener that broadcasts tool call events to EventBus.

    Lifecycle:
    1. PRE_TOOL_USE → publish "started" event
    2. POST_TOOL_USE → publish "completed" event
    3. POST_TOOL_USE_FAILURE → publish "failed" event

    Also writes to EventLog for persistence.
    """

    def __init__(self, event_logger: EventLogger | None = None) -> None:
        """Initialize broadcaster.

        Args:
            event_logger: Optional EventLogger for persistence.
        """
        self._event_logger = event_logger
        self._pending_calls: dict[str, float] = {}  # tool_call_id -> start_time
        self._event_bus: EventBus | None = None

    async def _ensure_event_bus(self) -> EventBus:
        """Lazy-init EventBus (singleton)."""
        if self._event_bus is None:
            self._event_bus = await EventBus.get_instance()
        return self._event_bus

    async def on_pre_tool_use(self, event_type: str, payload: dict[str, object]) -> HookResult:
        """Handle PRE_TOOL_USE hook (tool execution start).

        Args:
            event_type: "pre_tool_use"
            payload: {tool_name, tool_input, tool_call_id, session_id, message_id}

        Returns:
            HookResult with success=True.
        """
        tool_name = str(payload.get("tool_name", "unknown"))
        tool_call_id = str(payload.get("tool_call_id", ""))
        start_time = time.time()

        self._pending_calls[tool_call_id] = start_time

        event_data = ToolCallEventData(
            tool_name=tool_name,
            status="started",
            start_time=start_time,
            args=payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else None,
            session_id=str(payload.get("session_id")) if payload.get("session_id") else None,
            message_id=str(payload.get("message_id")) if payload.get("message_id") else None,
            tool_call_id=tool_call_id if tool_call_id else None,
            version=(resolved_skill_versions_var.get() or {}).get(tool_name),
        )

        bus = await self._ensure_event_bus()
        await bus.publish(event_data)

        if self._event_logger:
            await self._event_logger.log(AgentEventType.TOOL_START.value, event_data.to_dict())

        logger.debug("Tool started: %s (id=%s)", tool_name, tool_call_id)
        return HookResult(hook_type="tool_call_broadcaster", success=True)

    async def on_post_tool_use(self, event_type: str, payload: dict[str, object]) -> HookResult:
        """Handle POST_TOOL_USE hook (tool execution completed).

        Args:
            event_type: "post_tool_use"
            payload: {tool_name, tool_output, tool_call_id, session_id, message_id}

        Returns:
            HookResult with success=True.
        """
        tool_name = str(payload.get("tool_name", "unknown"))
        tool_call_id = str(payload.get("tool_call_id", ""))
        end_time = time.time()

        start_time = self._pending_calls.pop(tool_call_id, end_time)
        duration_ms = int((end_time - start_time) * 1000)

        event_data = ToolCallEventData(
            tool_name=tool_name,
            status="completed",
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            result=_truncate_for_event(payload.get("tool_output")),
            session_id=str(payload.get("session_id")) if payload.get("session_id") else None,
            message_id=str(payload.get("message_id")) if payload.get("message_id") else None,
            tool_call_id=tool_call_id if tool_call_id else None,
            version=(resolved_skill_versions_var.get() or {}).get(tool_name),
        )

        bus = await self._ensure_event_bus()
        await bus.publish(event_data)

        if self._event_logger:
            await self._event_logger.log(AgentEventType.TOOL_END.value, event_data.to_dict())

        logger.debug("Tool completed: %s (id=%s, duration=%dms)", tool_name, tool_call_id, duration_ms)
        return HookResult(hook_type="tool_call_broadcaster", success=True)

    async def on_post_tool_use_failure(self, event_type: str, payload: dict[str, object]) -> HookResult:
        """Handle POST_TOOL_USE_FAILURE hook (tool execution failed).

        Args:
            event_type: "post_tool_use_failure"
            payload: {tool_name, error, tool_call_id, session_id, message_id}

        Returns:
            HookResult with success=True.
        """
        tool_name = str(payload.get("tool_name", "unknown"))
        tool_call_id = str(payload.get("tool_call_id", ""))
        end_time = time.time()

        start_time = self._pending_calls.pop(tool_call_id, end_time)
        duration_ms = int((end_time - start_time) * 1000)

        event_data = ToolCallEventData(
            tool_name=tool_name,
            status="failed",
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            error=_truncate_for_event(str(payload.get("error", "Unknown error"))),
            session_id=str(payload.get("session_id")) if payload.get("session_id") else None,
            message_id=str(payload.get("message_id")) if payload.get("message_id") else None,
            tool_call_id=tool_call_id if tool_call_id else None,
            version=(resolved_skill_versions_var.get() or {}).get(tool_name),
        )

        bus = await self._ensure_event_bus()
        await bus.publish(event_data)

        if self._event_logger:
            await self._event_logger.log(AgentEventType.TOOL_FAILURE.value, event_data.to_dict())

        logger.warning("Tool failed: %s (id=%s, duration=%dms)", tool_name, tool_call_id, duration_ms)
        return HookResult(hook_type="tool_call_broadcaster", success=True)

    async def on_post_tool_use_cancelled(self, event_type: str, payload: dict[str, object]) -> HookResult:
        """Handle POST_TOOL_USE_CANCELLED hook (tool execution cancelled).

        Args:
            event_type: "post_tool_use_cancelled"
            payload: {tool_name, tool_call_id, session_id, message_id, cancel_reason}

        Returns:
            HookResult with success=True.
        """
        tool_name = str(payload.get("tool_name", "unknown"))
        tool_call_id = str(payload.get("tool_call_id", ""))
        cancel_reason = str(payload.get("cancel_reason", "unknown")) if payload.get("cancel_reason") else None
        end_time = time.time()

        start_time = self._pending_calls.pop(tool_call_id, end_time)
        duration_ms = int((end_time - start_time) * 1000)

        event_data = ToolCallEventData(
            tool_name=tool_name,
            status="cancelled",
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            error="Tool execution was cancelled",
            session_id=str(payload.get("session_id")) if payload.get("session_id") else None,
            message_id=str(payload.get("message_id")) if payload.get("message_id") else None,
            tool_call_id=tool_call_id if tool_call_id else None,
            cancel_reason=cancel_reason,
            version=(resolved_skill_versions_var.get() or {}).get(tool_name),
        )

        bus = await self._ensure_event_bus()
        await bus.publish(event_data)

        if self._event_logger:
            await self._event_logger.log(AgentEventType.TOOL_CANCELLED.value, event_data.to_dict())

        logger.warning(
            "Tool cancelled: %s (id=%s, duration=%dms, reason=%s)",
            tool_name,
            tool_call_id,
            duration_ms,
            cancel_reason or "unknown",
        )
        return HookResult(hook_type="tool_call_broadcaster", success=True)


def register_to_hook_registry(
    hook_registry: HookRegistry, event_logger: EventLogger | None = None
) -> ToolCallBroadcaster:
    """Register ToolCallBroadcaster to HookRegistry.

    Args:
        hook_registry: Agent's hook registry.
        event_logger: Optional event logger for persistence.

    Returns:
        Broadcaster instance.
    """
    from myrm_agent_harness.agent.hooks.types import CallableHookDefinition, HookEvent

    broadcaster = ToolCallBroadcaster(event_logger=event_logger)

    hook_registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=broadcaster.on_pre_tool_use))
    hook_registry.register(HookEvent.POST_TOOL_USE, CallableHookDefinition(fn=broadcaster.on_post_tool_use))
    hook_registry.register(
        HookEvent.POST_TOOL_USE_FAILURE, CallableHookDefinition(fn=broadcaster.on_post_tool_use_failure)
    )
    hook_registry.register(
        HookEvent.POST_TOOL_USE_CANCELLED, CallableHookDefinition(fn=broadcaster.on_post_tool_use_cancelled)
    )

    logger.info("ToolCallBroadcaster registered to HookRegistry")
    return broadcaster
