"""Strongly typed contracts for Live Response Steering and Mid-Generation Correction Channel (Item 219).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- SteerSeverity: Priority and disruption classification of a steering directive.
- SteerChannelMode: Transmission gateway mechanism (duplex socket, seam intercept, observation).
- LiveSteerStatus: Lifecycle states of a mid-generation steering instruction.
- ToolSeamAnchor: Execution seam coordinates where tool execution pauses or transitions.
- LiveSteeringInstruction: Strongly typed in-flight user steering payload.
- LiveSteeringInjectionResult: Structured outcome of intercepting and mounting an instruction.
- LiveSteeringReconciledHistory: Deterministic causally aligned conversational history.
- LiveSteeringConfig: Tunable limits and policy switches for in-flight steering.

[POS]
- Solves the dilemma of aborting long runs vs. burning tokens unchecked, providing
- non-blocking mid-flight user correction channels and causal history reconciliation.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class SteerSeverity(str, enum.Enum):
    """Classification of steering directive urgency and disruption scope."""

    ADVISORY = "advisory"
    COURSE_CORRECTION = "course_correction"
    ABORT_BRANCH = "abort_branch"
    URGENT_INTERRUPT = "urgent_interrupt"


class SteerChannelMode(str, enum.Enum):
    """Delivery mechanism for injecting in-flight steering directives."""

    DUPLEX_SOCKET = "duplex_socket"
    TOOL_SEAM_INTERCEPT = "tool_seam_intercept"
    STEP_OBSERVATION = "step_observation"


class LiveSteerStatus(str, enum.Enum):
    """Lifecycle phase of an in-flight steering instruction."""

    QUEUED = "queued"
    APPLIED_AT_SEAM = "applied_at_seam"
    ACTIVE_IN_CONTEXT = "active_in_context"
    SUPERSEDED = "superseded"
    DISCARDED = "discarded"


@dataclass(frozen=True, slots=True)
class ToolSeamAnchor:
    """Coordinates identifying an execution seam between tool calls or generation steps."""

    step_index: int
    completed_tool_name: str | None = None
    pending_tool_count: int = 0


@dataclass(slots=True)
class LiveSteeringInstruction:
    """Strongly typed user steering directive submitted during active generation."""

    instruction_id: str
    session_id: str
    turn_id: str
    content: str
    severity: SteerSeverity = SteerSeverity.COURSE_CORRECTION
    channel_mode: SteerChannelMode = SteerChannelMode.TOOL_SEAM_INTERCEPT
    target_step_index: int | None = None
    tool_call_id_context: str | None = None
    status: LiveSteerStatus = LiveSteerStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    applied_at: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def mark_applied(self, step_index: int) -> None:
        """Transitions instruction status to APPLIED_AT_SEAM."""
        self.status = LiveSteerStatus.APPLIED_AT_SEAM
        self.target_step_index = step_index
        self.applied_at = time.time()

    def mark_superseded(self) -> None:
        """Transitions status to SUPERSEDED when replaced by a fresher directive."""
        self.status = LiveSteerStatus.SUPERSEDED

    def mark_discarded(self) -> None:
        """Transitions status to DISCARDED."""
        self.status = LiveSteerStatus.DISCARDED

    def to_dict(self) -> dict[str, object]:
        """Serializes steering instruction to dictionary."""
        return {
            "instruction_id": self.instruction_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "content": self.content,
            "severity": self.severity.value,
            "channel_mode": self.channel_mode.value,
            "target_step_index": self.target_step_index,
            "tool_call_id_context": self.tool_call_id_context,
            "status": self.status.value,
            "created_at": self.created_at,
            "applied_at": self.applied_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class LiveSteeringInjectionResult:
    """Outcome of intercepting and mounting an in-flight steering directive at a seam."""

    applied: bool
    instruction_id: str | None
    seam_step_index: int
    injected_prompt_content: str
    suppressed_tool_ids: list[str]
    causal_tag: str
    applied_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes injection result to dictionary."""
        return {
            "applied": self.applied,
            "instruction_id": self.instruction_id,
            "seam_step_index": self.seam_step_index,
            "injected_prompt_content": self.injected_prompt_content,
            "suppressed_tool_ids": list(self.suppressed_tool_ids),
            "causal_tag": self.causal_tag,
            "applied_timestamp": self.applied_timestamp,
        }


@dataclass(frozen=True, slots=True)
class LiveSteeringReconciledHistory:
    """Deterministically ordered conversational history incorporating in-flight steers."""

    session_id: str
    turn_id: str
    total_steers_applied: int
    reconciled_messages: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        """Serializes reconciled history to dictionary."""
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "total_steers_applied": self.total_steers_applied,
            "reconciled_messages": list(self.reconciled_messages),
        }


@dataclass(frozen=True, slots=True)
class LiveSteeringConfig:
    """Configuration governing in-flight response steering limits and policies."""

    max_pending_queue_size: int = 8
    allow_directive_supersede: bool = True
    max_steering_content_length: int = 4000
    enable_tool_suppression: bool = True
