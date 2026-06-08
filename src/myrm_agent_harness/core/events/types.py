"""Streaming event types and enums — framework-agnostic.

Provides AgentEventType (all event enums) and AgentStreamEvent (typed wrapper).
Usable by both agent/ and toolkits/ without coupling to the agent runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass
class AgentStreamEvent:
    """Strongly typed wrapper for agent stream events.

    Supports arbitrary extra fields via ``extra_data`` for backward compatibility
    with diverse SSE dictionary shapes.
    """

    type: AgentEventType | str
    data: Any = None
    messageId: str | None = None  # noqa: N815  frontend SSE camelCase contract
    error: str | None = None
    error_type: str | None = None
    compression_exhausted: bool | None = None
    extra_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentStreamEvent:
        """Create an event from a raw dictionary, preserving all extra fields."""
        known_keys = {
            "type",
            "data",
            "messageId",
            "error",
            "error_type",
            "compression_exhausted",
            "extra_data",
        }
        event = cls(
            type=raw.get("type", "unknown"),
            data=raw.get("data"),
            messageId=raw.get("messageId"),
            error=raw.get("error"),
            error_type=raw.get("error_type"),
            compression_exhausted=raw.get("compression_exhausted"),
        )
        for k, v in raw.items():
            if k not in known_keys:
                event.extra_data[k] = v
        return event

    def get(self, key: str, default: Any = None) -> Any:
        """Backward compatibility for dict.get()"""
        if hasattr(self, key):
            return getattr(self, key)
        return self.extra_data.get(key, default)

    def __getitem__(self, item: str) -> Any:
        """Backward compatibility for dict subscripting"""
        if hasattr(self, item):
            return getattr(self, item)
        if item in self.extra_data:
            return self.extra_data[item]
        raise KeyError(item)

    def to_dict(self) -> dict[str, Any]:
        """Convert to raw dictionary for final SSE serialization."""
        d: dict[str, Any] = {"type": (self.type.value if isinstance(self.type, AgentEventType) else self.type)}
        if self.data is not None:
            d["data"] = self.data
        if self.messageId is not None:
            d["messageId"] = self.messageId
        if self.error is not None:
            d["error"] = self.error
        if self.error_type is not None:
            d["error_type"] = self.error_type
        if self.compression_exhausted is not None:
            d["compression_exhausted"] = self.compression_exhausted

        if self.extra_data:
            d.update(self.extra_data)

        return d


class AgentEventType(StrEnum):
    """Agent event types for streaming responses."""

    TASKS_STEPS = "tasks_steps"
    TOOL_HEARTBEAT = "tool_heartbeat"
    SOURCES = "sources"
    MESSAGE = "message"
    MESSAGE_END = "message_end"
    ERROR = "error"
    CANCELLED = "cancelled"
    ARTIFACTS = "artifacts"
    ARTIFACTS_READY = "artifacts_ready"
    UI_UPDATE = "ui_update"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TOOL_FAILURE = "tool_failure"
    TOOL_STDOUT_CHUNK = "tool_stdout_chunk"
    TOOL_EVICTED_REF = "tool_evicted_ref"
    TOOL_CANCELLED = "tool_cancelled"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_RETRY = "tool_retry"
    TOOL_TOKEN_USAGE = "tool_token_usage"
    ARTIFACT_CONTENT = "artifact_content"
    TOKEN_USAGE = "token_usage"
    APPROVAL_INTERCEPTED = "approval_intercepted"
    REASONING = "reasoning"
    STEERING = "steering"
    TOOL_APPROVAL_REQUEST = "tool_approval_request"
    STATUS = "status"
    TOOLS_SNAPSHOT = "tools_snapshot"
    ASYNC_WAKEUP = "async_wakeup"
    PRIVACY_LEVEL = "privacy_level"
    PRIVACY_ROUTE = "privacy_route"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_PROGRESS = "subagent_progress"
    SUBAGENT_LOG = "subagent_log"
    BASH_COMMAND_EXECUTED = "bash_command_executed"
    SUBAGENT_COMPLETION = "subagent_completion"
    CONTEXT_SNAPSHOT = "context_snapshot"
    ITERATION_LIMIT_REACHED = "iteration_limit_reached"
    APPROVAL_REQUIRED = "approval_required"
    CLARIFICATION_REQUIRED = "clarification_required"
    COGNITIVE_CONSOLIDATION = "cognitive_consolidation"
    GOAL_STATUS = "goal_status"
    ENGINE_LIMIT_REACHED = "engine_limit_reached"
    CLIENT_ACTION = "client_action"
    FILE_DIFF = "file_diff"
    CAPTCHA_DETECTED = "captcha_detected"
    CAPTCHA_RESOLVED = "captcha_resolved"
    CAPTCHA_TIMEOUT = "captcha_timeout"
    MODEL_ESCALATED = "model_escalated"
    FILE_MUTATION_FAILED = "file_mutation_failed"
    TOOL_IMAGE_OUTPUT = "tool_image_output"
    BROWSER_VIEW_UPDATE = "browser_view_update"
    DESKTOP_VIEW_UPDATE = "desktop_view_update"
    PTC_NOTIFY = "ptc_notify"
    LOCATOR_SELF_HEALED = "locator_self_healed"
    BROWSER_TAKEOVER_REQUESTED = "browser_takeover_requested"
    BROWSER_TAKEOVER_COMPLETED = "browser_takeover_completed"


@dataclass
class ContextBudgetSnapshot:
    """Lightweight snapshot of context window usage for frontend visualization.

    Uses actual prompt_tokens from the LLM provider (more accurate than estimation).
    health_status mirrors ContextHealthStatus from context_management but avoids
    coupling to the full ContextBudget infrastructure.
    """

    current_tokens: int
    max_context_tokens: int
    usage_percent: float
    health_status: str  # "healthy" | "warning" | "critical"

    def to_dict(self) -> dict[str, int | float | str]:
        return {
            "current_tokens": self.current_tokens,
            "max_context_tokens": self.max_context_tokens,
            "usage_percent": round(self.usage_percent, 1),
            "health_status": self.health_status,
        }


@dataclass(frozen=True, slots=True)
class ApprovalInterceptedEventData:
    """Strongly typed payload for AgentEventType.APPROVAL_INTERCEPTED."""

    decision: str
    original_text: str | None = None
    visual_context: dict[str, Any] | None = field(default=None)
    action_description: str | None = field(default=None)
