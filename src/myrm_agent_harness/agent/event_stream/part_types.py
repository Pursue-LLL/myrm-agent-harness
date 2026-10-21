"""Strongly typed atomic part data contracts for multi-part event streams.

Decomposes monolithic assistant turns into granular, strongly-typed lifecycle parts:
- ReasoningPart: Internal chain-of-thought and self-critique traces.
- TextPart: User-facing synthesized natural language output.
- ToolInvocationPart: Tool call intent with strict serialized parameters.
- ToolResultPart: Concrete execution receipts and return values.
- FilePatchPart: Unified file diffs and mutations generated during the turn.
- CompactionPart: Context compaction and summary milestones.

[OUTPUT]
- PartKind: Classification of conversational message parts.
- PartStatus: Lifecycle status of an individual part.
- EventKind: Event type for streaming deltas and completions.
- ReasoningPart, TextPart, ToolInvocationPart, ToolResultPart, FilePatchPart, CompactionPart.
- PartEvent: Immutable event envelope for event-bus dispatch and SQLite projection.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- PartKind
- PartStatus
- EventKind
- ReasoningPart
- TextPart
- ToolInvocationPart
- ToolResultPart
- FilePatchPart
- CompactionPart
- AtomicPart

[POS]
Strongly typed atomic part data contracts for multi-part event streams.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class PartKind(StrEnum):
    """Discriminator for decomposed message parts."""

    REASONING = "reasoning"
    TEXT = "text"
    TOOL_INVOCATION = "tool_invocation"
    TOOL_RESULT = "tool_result"
    FILE_PATCH = "file_patch"
    COMPACTION = "compaction"


class PartStatus(StrEnum):
    """Lifecycle progress of an individual message part."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class EventKind(StrEnum):
    """Granular event types emitted during part streaming."""

    PART_APPEND = "part_append"
    PART_DELTA = "part_delta"
    PART_COMPLETE = "part_complete"


@dataclass(frozen=True)
class ReasoningPart:
    """Internal reasoning and reflective chain-of-thought part."""

    part_id: str
    message_id: str
    session_id: str
    thought_content: str
    duration_ms: float = 0.0
    status: PartStatus = PartStatus.IN_PROGRESS
    kind: PartKind = PartKind.REASONING


@dataclass(frozen=True)
class TextPart:
    """User-facing synthesized natural language text part."""

    part_id: str
    message_id: str
    session_id: str
    text_content: str
    status: PartStatus = PartStatus.IN_PROGRESS
    kind: PartKind = PartKind.TEXT


@dataclass(frozen=True)
class ToolInvocationPart:
    """Tool invocation intent emitted by the model."""

    part_id: str
    message_id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    arguments: str
    status: PartStatus = PartStatus.IN_PROGRESS
    kind: PartKind = PartKind.TOOL_INVOCATION


@dataclass(frozen=True)
class ToolResultPart:
    """Execution receipt and structured payload of an executed tool."""

    part_id: str
    message_id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    result_content: str
    is_error: bool = False
    duration_ms: float = 0.0
    status: PartStatus = PartStatus.COMPLETED
    kind: PartKind = PartKind.TOOL_RESULT


@dataclass(frozen=True)
class FilePatchPart:
    """Granular code or configuration patch applied to the filesystem."""

    part_id: str
    message_id: str
    session_id: str
    target_file: str
    diff_content: str
    status: PartStatus = PartStatus.COMPLETED
    kind: PartKind = PartKind.FILE_PATCH


@dataclass(frozen=True)
class CompactionPart:
    """Milestone summary and context compaction boundary."""

    part_id: str
    message_id: str
    session_id: str
    summary_content: str
    compacted_turn_range: str
    status: PartStatus = PartStatus.COMPLETED
    kind: PartKind = PartKind.COMPACTION


AtomicPart = (
    ReasoningPart
    | TextPart
    | ToolInvocationPart
    | ToolResultPart
    | FilePatchPart
    | CompactionPart
)


@dataclass(frozen=True)
class PartEvent:
    """Immutable event payload propagated across event streams and SQLite projectors."""

    event_id: str
    session_id: str
    message_id: str
    part_id: str
    part_kind: PartKind
    event_kind: EventKind
    sequence_number: int
    delta: str = ""
    payload: dict[str, str | float | bool] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
