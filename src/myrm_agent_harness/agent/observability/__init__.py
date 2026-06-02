"""Observability subsystem for real-time agent event broadcasting.

[INPUT]
- agent.hooks (POS: Hook lifecycle events)
- agent.event_log.types (POS: StructuredEvent)

[OUTPUT]
- EventBus: Async event bus with backpressure
- ToolCallBroadcaster: Hook listener that publishes tool call events
- ToolCallEventData: Immutable tool call event data

[POS]
Framework-level observability layer. Business layer subscribes to EventBus
for transport-specific adapters (SSE/Tauri/WebSocket).
"""

from myrm_agent_harness.agent.observability.event_bus import EventBus
from myrm_agent_harness.agent.observability.tool_call_broadcaster import ToolCallBroadcaster
from myrm_agent_harness.agent.observability.types import ToolCallEventData

__all__ = ["EventBus", "ToolCallBroadcaster", "ToolCallEventData"]
