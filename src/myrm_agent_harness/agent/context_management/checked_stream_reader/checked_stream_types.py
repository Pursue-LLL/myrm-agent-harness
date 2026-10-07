"""Data contracts and schemas for checked session reply stream readers and anti-slop governance.

Defines typed stream chunk frames, reader state machine transitions, anti-slop violations,
and streaming telemetry metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class StreamChunkKind(StrEnum):
    """Semantic category of a streaming response delta chunk."""

    TEXT = "text"
    REASONING = "reasoning"
    TOOL_CALL_DELTA = "tool_call_delta"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    DONE = "done"


class StreamReaderState(StrEnum):
    """Lifecycle status of the checked streaming reader state machine."""

    IDLE = "idle"
    STREAMING = "streaming"
    HEALING = "healing"
    COMPLETED = "completed"
    BROKEN = "broken"


class AntiSlopViolationKind(StrEnum):
    """Types of undesirable noise, raw template bleed-through, or malformed slop in chunks."""

    EMPTY_PAYLOAD = "empty_payload"
    EXCESSIVE_NEWLINES = "excessive_newlines"
    RAW_TEMPLATE_TAG = "raw_template_tag"
    REPETITIVE_PADDING = "repetitive_padding"


@dataclass(frozen=True)
class StreamChunkFrame:
    """Strongly typed atomic stream frame with sequential integrity metadata."""

    sequence_id: int
    kind: StreamChunkKind
    content: str
    session_id: str
    timestamp_ms: int = 0
    is_synthesized: bool = False


@dataclass(frozen=True)
class AntiSlopFilterResult:
    """Outcome of evaluating and sanitizing a stream chunk against anti-slop rules."""

    is_valid: bool
    cleaned_content: str
    violations: list[AntiSlopViolationKind] = field(default_factory=list)


@dataclass(frozen=True)
class StreamReaderMetrics:
    """Cumulative telemetry tracking stream health and anti-slop interventions."""

    frames_processed: int
    frames_discarded: int
    healed_gaps: int
    total_characters_delivered: int
    violations_detected: dict[str, int] = field(default_factory=dict)
