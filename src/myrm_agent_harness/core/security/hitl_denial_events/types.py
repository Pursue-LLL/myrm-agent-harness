"""Domain types and events for Human-in-the-Loop (HITL) denial lifecycle.

[INPUT]
- Typed data models representing tool call requests, approval/denial results,
  and user confirmation metadata.

[OUTPUT]
- Immutable dataclasses and enums representing explicit tool result events
  and all-tools-denied aggregate lifecycle states.

[POS]
- Core security primitive ensuring manual denials emit proper tool_result events
  with custom reasons and support configurable halt vs resume workflows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class ToolResultState(StrEnum):
    """Execution state of a tool call result."""

    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    ERROR = "ERROR"


class AllToolsDeniedPolicy(StrEnum):
    """Behavior policy when all tool calls in a reasoning step are denied."""

    HALT = "HALT"
    RESUME_WITH_FEEDBACK = "RESUME_WITH_FEEDBACK"


@dataclass(frozen=True)
class ToolUseBlock:
    """Specification of a tool call awaiting execution or human approval."""

    id: str
    name: str
    arguments: Mapping[str, str | int | float | bool | list[str] | dict[str, str]] = (
        field(default_factory=dict)
    )


@dataclass(frozen=True)
class ConfirmResult:
    """User confirmation decision for a specific tool call."""

    tool_call_id: str
    tool_name: str
    confirmed: bool
    reason: str | None = None
    modified_arguments: (
        Mapping[str, str | int | float | bool | list[str] | dict[str, str]]
        | None
    ) = None


@dataclass(frozen=True)
class ToolResultEvent:
    """Emitted event representing the outcome of a tool call (allowed or denied)."""

    event_id: str
    tool_call_id: str
    tool_name: str
    state: ToolResultState
    output_text: str
    created_at: str


@dataclass(frozen=True)
class AllToolsDeniedEvent:
    """Aggregate event emitted when every tool call in a step was denied."""

    event_id: str
    session_id: str
    step_id: str
    denied_tool_calls: Sequence[ToolUseBlock]
    denied_reasons: Mapping[str, str]
    policy_applied: AllToolsDeniedPolicy
    should_stop: bool
    stop_reason: str | None = None
    created_at: str = ""


@dataclass(frozen=True)
class HitlProcessOutcome:
    """Complete outcome of processing a batch of HITL confirmation results."""

    session_id: str
    step_id: str
    total_calls: int
    confirmed_count: int
    denied_count: int
    all_denied: bool
    tool_result_events: Sequence[ToolResultEvent]
    all_tools_denied_event: AllToolsDeniedEvent | None
    can_resume: bool
    terminal_reason: str | None = None
