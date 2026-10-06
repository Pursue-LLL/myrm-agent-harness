"""Type definitions for internal/external message separation and context transformation pipeline.

Defines the rich 7-kind domain AgentMessage union, external LlmMessage protocol,
transformation configuration options, and pipeline execution metrics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class AgentMessageKind(StrEnum):
    """Rich domain classification for internal agent events."""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL_EXECUTION = "tool_execution"
    SYSTEM_NOTIFICATION = "system_notification"
    CONFIG_MUTATION = "config_mutation"
    BRANCH_MARKER = "branch_marker"
    HUMAN_APPROVAL_GATE = "human_approval_gate"


@dataclass(frozen=True)
class AgentMessage:
    """Internal rich-metadata domain event message."""

    message_id: str
    kind: AgentMessageKind
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, str] = field(default_factory=dict)
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: str | None = None
    is_error: bool = False
    is_streaming_incomplete: bool = False
    reasoning_content: str | None = None


@dataclass(frozen=True)
class LlmToolCall:
    """Standard tool call payload in external LLM protocol."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class LlmMessage:
    """External standardized protocol message targeting LLM endpoints."""

    role: str  # "user", "assistant", "tool", "system"
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[LlmToolCall] | None = None


@dataclass(frozen=True)
class TransformPipelineOptions:
    """Configurable options for the context transformation and conversion pipeline."""

    max_tool_output_chars: int = 2000
    drop_incomplete_streaming: bool = True
    allow_system_notifications: bool = False
    truncate_head_ratio: float = 0.4
    truncate_tail_ratio: float = 0.4


@dataclass(frozen=True)
class TransformPipelineMetrics:
    """Execution metrics and audit statistics of context transformation."""

    input_internal_count: int
    output_llm_count: int
    pruned_meta_events_count: int
    dropped_incomplete_count: int
    truncated_tool_chars: int
    tokens_saved_estimate: int
