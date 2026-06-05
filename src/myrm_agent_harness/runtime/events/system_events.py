"""Typed system-level runtime events.

[INPUT]
- runtime.events.bus::BaseEvent (POS: Event Bus Implementation)

[OUTPUT]
- JsonValue: JSON-compatible event payload value type.
- DelegationPolicyDecision: Typed policy-admission result for subagent delegation.
- SubagentLifecycleData: Typed subagent lifecycle event payload.
- SubagentLifecycleEvent: Event emitted when a subagent changes lifecycle state.
- ResourceMetricsEvent: Event emitted with current resource usage metrics.
- to_json_object: Convert arbitrary mapping data into JSON-compatible event payloads.

[POS]
Framework-level system event DTOs. They keep lifecycle and resource payloads typed without
business-layer, GUI, approval, or tenant dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .bus import BaseEvent

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]


def _to_json_value(value: object) -> JsonValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_to_json_value(item) for item in value]
    return str(value)


def to_json_object(data: Mapping[str, object] | None) -> JsonObject:
    """Convert mapping-like event data into a JSON-compatible payload object."""
    if data is None:
        return {}
    return {str(key): _to_json_value(value) for key, value in data.items()}


@dataclass(frozen=True, slots=True)
class DelegationPolicyDecision:
    """Decision produced by delegation policy admission."""

    allowed: bool
    reason: str
    requested_role: str
    effective_scope: str
    agent_type: str = ""
    details: str = ""

    def to_dict(self) -> JsonObject:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "requested_role": self.requested_role,
            "effective_scope": self.effective_scope,
            "agent_type": self.agent_type,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class SubagentLifecycleData:
    """Typed subagent lifecycle event payload."""

    agent_type: str = ""
    description: str = ""
    role: str = ""
    control_scope: str = ""
    budget: JsonObject = field(default_factory=dict)
    status: str = ""
    result: JsonObject = field(default_factory=dict)
    policy: DelegationPolicyDecision | None = None
    extra: JsonObject = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "agent_type": self.agent_type,
            "description": self.description,
            "role": self.role,
            "control_scope": self.control_scope,
            "budget": self.budget,
            "status": self.status,
            "result": self.result,
            "extra": self.extra,
        }
        if self.policy is not None:
            payload["policy"] = self.policy.to_dict()
        return payload


@dataclass(slots=True)
class SubagentLifecycleEvent(BaseEvent):
    """Event emitted when a subagent changes lifecycle state."""

    event_name: str
    task_id: str
    session_id: str
    data: SubagentLifecycleData = field(default_factory=SubagentLifecycleData)

    vault_uri: str | None = None
    thread_id: str | None = None
    created_at: float = 0.0

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "message_id": self.message_id,
            "from_task_id": self.from_task_id,
            "to_task_id": self.to_task_id,
            "from_agent_type": self.from_agent_type,
            "body": self.body,
            "created_at": self.created_at,
        }
        if self.vault_uri:
            payload["vault_uri"] = self.vault_uri
        if self.thread_id:
            payload["thread_id"] = self.thread_id
        return payload


@dataclass(slots=True)
class ResourceMetricsEvent(BaseEvent):
    """Event emitted periodically with current resource usage metrics."""

    metrics: JsonObject
    history: list[JsonObject]


@dataclass(slots=True)
class LocatorSelfHealedEvent(BaseEvent):
    """Event emitted when a broken locator is self-healed by the fingerprint engine."""

    ref: str
    old_name: str
    new_name: str
    url: str
    role: str
    distance: float

    def to_dict(self) -> JsonObject:
        return {
            "ref": self.ref,
            "old_name": self.old_name,
            "new_name": self.new_name,
            "url": self.url,
            "role": self.role,
            "distance": self.distance,
        }
