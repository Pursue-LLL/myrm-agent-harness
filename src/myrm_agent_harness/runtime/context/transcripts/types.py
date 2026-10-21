"""Canonical transcript turn and event definitions for cross-tool session import.

[INPUT]
- standard library dataclasses, enum, typing

[OUTPUT]
- CanonicalTurnRole: Enum for speaker role in a turn.
- CanonicalToolCall: Normalized tool invocation entity.
- CanonicalTranscriptTurn: High-fidelity normalized conversational turn.
- TranscriptParseResult: Aggregated session parse result.

[POS]
runtime/context/transcripts/types.py
Data contracts for framework-neutral external transcript parsing and remapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CanonicalTurnRole(StrEnum):
    """Normalized role identifier for dialogue turns."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class CanonicalToolCall:
    """Normalized tool call with structured arguments and output."""

    call_id: str
    tool_name: str
    arguments: dict[str, object]
    output: str | None = None
    exit_code: int = 0
    is_error: bool = False
    compacted: bool = False
    original_size_bytes: int = 0


@dataclass(frozen=True, slots=True)
class CanonicalTranscriptTurn:
    """High-fidelity representation of a conversational turn across any external agent."""

    turn_id: str
    role: CanonicalTurnRole
    content: str
    thinking_trace: str | None = None
    tool_calls: list[CanonicalToolCall] = field(default_factory=list)
    timestamp: float = 0.0
    source_event_type: str = "message"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TranscriptParseResult:
    """Aggregated result of parsing a full session transcript."""

    session_id: str
    title: str
    turns: list[CanonicalTranscriptTurn]
    source_platform: str
    created_at: float
    updated_at: float
    detected_workspace_hint: str | None = None
    total_tool_calls: int = 0
    total_tokens_approx: int = 0
