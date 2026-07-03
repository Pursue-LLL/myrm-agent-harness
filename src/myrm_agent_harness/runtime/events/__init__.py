from .bus import BaseEvent, EventBus, get_event_bus
from .idle_events import IdleTaskProgressEvent
from .skill_events import SkillFailureCandidate, SkillFailureEvent
from .system_events import (
    DelegationPolicyDecision,
    JsonObject,
    JsonValue,
    LocatorSelfHealedEvent,
    MCPAuthExpiredEvent,
    ResourceMetricsEvent,
    SubagentLifecycleData,
    SubagentLifecycleEvent,
    to_json_object,
)

__all__ = [
    "BaseEvent",
    "DelegationPolicyDecision",
    "EventBus",
    "IdleTaskProgressEvent",
    "JsonObject",
    "JsonValue",
    "LocatorSelfHealedEvent",
    "MCPAuthExpiredEvent",
    "ResourceMetricsEvent",
    "SkillFailureCandidate",
    "SkillFailureEvent",
    "SubagentLifecycleData",
    "SubagentLifecycleEvent",
    "get_event_bus",
    "to_json_object",
]


def _wire_mcp_auth_expired_handler() -> None:
    from myrm_agent_harness.toolkits.mcp.auth_notify import register_mcp_auth_expired_handler

    from .system_events import MCPAuthExpiredEvent

    def _publish_auth_expired(server_name: str, error_detail: str) -> None:
        get_event_bus().publish(
            MCPAuthExpiredEvent(server_name=server_name, error_detail=error_detail)
        )

    register_mcp_auth_expired_handler(_publish_auth_expired)


_wire_mcp_auth_expired_handler()
