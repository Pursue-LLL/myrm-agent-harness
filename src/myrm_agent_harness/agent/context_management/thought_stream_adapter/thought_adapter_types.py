"""Domain models and contracts for agent thought streaming and dual-mode external client adapter.

[INPUT]
- None (Self-contained domain models and contracts).

[OUTPUT]
- ClientReasoningMode: Client negotiation mode (REASONING_CONTENT, THINK_TAG_FALLBACK, SILENT).
- ThoughtActionType: Categorization of internal agent reasoning and actions.
- ThoughtStepDescriptor: Structured metadata and state for an in-flight or completed thought step.
- ThoughtStreamChunk: Atomic streaming chunk delivered to external clients with SSE typing.
- ThoughtAdapterConfig: Configuration governing reasoning mode defaults, keep-alive intervals, and tags.

[POS]
Domain contract layer for thought stream adaptation and external client bridge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class ClientReasoningMode(str, Enum):
    """Reasoning delivery mode determined by client negotiation."""

    REASONING_CONTENT = "reasoning_content"
    THINK_TAG_FALLBACK = "think_tag_fallback"
    SILENT = "silent"


class ThoughtActionType(str, Enum):
    """Classification of an intermediate agent step or cognition action."""

    THINKING = "thinking"
    PLANNING = "planning"
    TOOL_EXECUTION = "tool_execution"
    TOOL_RESULT = "tool_result"
    OBSERVATION = "observation"


@dataclass(frozen=True)
class ThoughtStepDescriptor:
    """Descriptor snapshot of an individual thought or execution step."""

    step_id: str
    action_type: ThoughtActionType
    title: str
    content: str = ""
    status: str = "running"
    elapsed_ms: float = 0.0
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ThoughtStreamChunk:
    """Standardized event chunk ready to be written to client SSE stream."""

    chunk_type: str
    text: str
    is_heartbeat: bool = False
    step_id: str | None = None


@dataclass(frozen=True)
class ThoughtAdapterConfig:
    """Configuration parameters governing thought stream adaptation and keep-alive."""

    default_mode: ClientReasoningMode = ClientReasoningMode.REASONING_CONTENT
    heartbeat_interval_seconds: float = 1.5
    enable_heartbeat: bool = True
    include_tool_details_in_thought: bool = True
    think_tag_open: str = "<think>\n"
    think_tag_close: str = "\n</think>\n"
    format_action_headers: bool = True
    max_tool_summary_chars: int = 250
