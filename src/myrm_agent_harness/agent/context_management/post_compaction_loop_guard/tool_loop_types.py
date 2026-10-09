# [INPUT]: None (Pure domain types and contracts)
# [OUTPUT]: LoopDetectionAction, ToolCallSignature, CompactionBoundaryLedger, LoopGuardDecision, PostCompactionGuardConfig, RepeatedToolLoopError
# [POS]: myrm_agent_harness.agent.context_management.post_compaction_loop_guard.tool_loop_types
"""Strongly-typed contracts for Post-Compaction Tool Loop Guard (Item 331).

Defines tool signatures, compaction boundary ledgers, loop detection decisions,
and deterministic circuit-breaker errors.
"""

from __future__ import annotations

from enum import Enum
from typing import Final
from pydantic import BaseModel, Field


class LoopDetectionAction(str, Enum):
    """Action to take upon evaluating a tool invocation against boundary ledger."""

    ALLOW = "allow"
    REMIND_IN_CONTEXT = "remind_in_context"
    TRIPPED_CIRCUIT_BREAKER = "tripped_circuit_breaker"


class ToolCallSignature(BaseModel):
    """Deterministic cryptographic fingerprint of a completed tool execution."""

    tool_name: str = Field(..., description="Name of the invoked tool")
    arguments_hash: str = Field(..., description="SHA-256 fingerprint of normalized argument payload")
    normalized_args_json: str = Field(..., description="Canonical JSON string of tool arguments")
    result_digest: str = Field(..., description="Truncated or hashed summary of tool execution result")
    call_index: int = Field(..., description="Chronological invocation index in original context")
    timestamp_iso: str = Field(..., description="ISO 8601 UTC timestamp of execution")


class CompactionBoundaryLedger(BaseModel):
    """Immutable ledger of recent tool call signatures captured at context compaction boundary."""

    session_id: str = Field(..., description="Conversation session identifier")
    compaction_turn_index: int = Field(..., description="Turn index at which compaction occurred")
    signatures: list[ToolCallSignature] = Field(
        default_factory=list, description="Recent tool execution signatures preserved across compaction"
    )
    ledger_digest: str = Field(..., description="SHA-256 integrity hash of entire ledger payload")


class LoopGuardDecision(BaseModel):
    """Verdict for whether a post-compaction tool invocation is allowed, warned, or blocked."""

    action: LoopDetectionAction = Field(..., description="Action decision for this tool call")
    tool_name: str = Field(..., description="Target tool name")
    arguments_hash: str = Field(..., description="Computed argument hash")
    repeat_count: int = Field(0, description="Number of times this identical signature was called post-compaction")
    injected_reminder: str = Field(
        "", description="System guidance message to inject into context when remind_in_context trips"
    )
    is_circuit_broken: bool = Field(
        False, description="True if identical calls exceeded hard threshold and loop was broken"
    )


class PostCompactionGuardConfig(BaseModel):
    """Configuration governing post-compaction tool loop detection thresholds."""

    max_retained_signatures: int = Field(
        10, description="Maximum recent tool calls retained in boundary ledger"
    )
    soft_remind_threshold: int = Field(
        1, description="Repeat count triggering non-blocking system reminder injection"
    )
    hard_trip_threshold: int = Field(
        3, description="Repeat count triggering hard circuit breaker termination"
    )
    protect_window_turns: int = Field(
        3, description="Number of turns after compaction where ledger guard remains strictly active"
    )


class RepeatedToolLoopError(RuntimeError):
    """Raised when an agent gets trapped in a repeated tool loop after context compaction."""

    def __init__(self, tool_name: str, args_hash: str, repeat_count: int, message: str) -> None:
        super().__init__(message)
        self.tool_name: Final[str] = tool_name
        self.args_hash: Final[str] = args_hash
        self.repeat_count: Final[int] = repeat_count


DEFAULT_MAX_SIGNATURES: Final[int] = 10
DEFAULT_HARD_TRIP_LIMIT: Final[int] = 3
