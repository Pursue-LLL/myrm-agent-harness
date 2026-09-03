"""Task Friction Telemetry Type Contracts.

[INPUT]
- None (Standard library dataclasses, enum, typing)

[OUTPUT]
- FrictionCategory: Enum of standard agent task friction categories
- TaskFrictionEvent: Immutable event record representing a detected friction point
- FrictionSummary: Aggregated statistical metrics for task friction points

[POS]
Type definitions and data structures for agent execution friction telemetry and Eval Lab co-evolution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class FrictionCategory(str, Enum):
    """Categorization of agent execution friction points."""

    FORMAT_ERROR = "FORMAT_ERROR"          # Tool input JSON/schema parse failure, retry needed
    SPILL_OVERFLOW = "SPILL_OVERFLOW"      # Tool or command output exceeded buffer/context limit
    TOOL_TIMEOUT = "TOOL_TIMEOUT"          # Tool execution exceeded time budget
    PERMISSION_DENIED = "PERMISSION_DENIED"# Sandbox/filesystem permission or security violation
    LOOP_STUCK = "LOOP_STUCK"              # Repetitive tool calls or cyclic reasoning stuck state
    TOOL_FAULT = "TOOL_FAULT"              # General unhandled exception raised by underlying tool


@dataclass(frozen=True)
class TaskFrictionEvent:
    """Detailed record of a single task execution friction point.

    Attributes:
        id: Unique UUID string for this friction event.
        category: FrictionCategory classification.
        session_id: ID of the session where friction occurred.
        tool_name: Name of the offending tool or system component.
        message: Human-readable error description or reason.
        trace_id: Optional execution trace ID.
        fault_side: Attributed fault side (e.g. MODEL, HARNESS, ENV).
        input_payload: Optional sanitized snippet of tool arguments or user input.
        output_payload: Optional sanitized error output or exception trace.
        retry_count: Number of consecutive retries triggered by this friction.
        occurred_at: Timestamp when the friction was detected.
        metadata: Additional arbitrary contextual key-value pairs.
    """

    category: FrictionCategory
    session_id: str
    tool_name: str
    message: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str | None = None
    fault_side: str = "MODEL"
    input_payload: str | None = None
    output_payload: str | None = None
    retry_count: int = 0
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FrictionSummary:
    """Aggregated metrics and breakdown of task frictions across sessions."""

    total_frictions: int
    by_category: dict[str, int]
    by_tool: dict[str, int]
    by_fault_side: dict[str, int]
    top_frequent_tools: list[tuple[str, int]]
    high_friction_sessions: list[str]
