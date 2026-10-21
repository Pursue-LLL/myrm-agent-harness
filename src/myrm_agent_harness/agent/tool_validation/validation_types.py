"""Strongly typed data contracts for mixed batch tool validation and role alternation guard.

[OUTPUT]
- ToolValidationAction: Actions returned by batch validation verdict.
- ToolCallEnvelope: Normalized representation of an inbound tool call.
- ToolCallResult: Canonical role="tool" result for conversation message streams.
- ToolValidationVerdict: Complete outcome of tool-call batch analysis.
- RoleAlternationViolationError: Raised when conversation message invariants are violated.

[INPUT]
- __future__
- dataclasses
- enum

[OUTPUT]
- ToolValidationAction
- ToolCallEnvelope
- ToolCallResult
- ToolValidationVerdict
- RoleAlternationViolationError

[POS]
Strongly typed data contracts for mixed batch tool validation and role alternation guard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ToolValidationAction(StrEnum):
    """Action decision for an evaluated batch of tool calls."""

    OK = "ok"
    """All tool calls in the batch are valid and ready for normal dispatch."""

    SPLIT_EXECUTE = "split_execute"
    """Mixed batch: valid calls are executed, while invalid calls receive synthetic tool error results."""

    RETRY_MODEL = "retry_model"
    """Entire batch is invalid or malformed; agent loop should re-prompt the LLM with error feedback."""

    TERMINAL_PARTIAL_EXIT = "terminal_partial_exit"
    """Irrecoverable condition (3-strike limit exceeded or stream truncation); turn ends as partial."""


@dataclass(frozen=True)
class ToolCallEnvelope:
    """Canonical representation of an LLM tool call."""

    id: str
    name: str
    arguments: str
    index: int = 0


@dataclass(frozen=True)
class ToolCallResult:
    """Canonical role='tool' message element adhering to LLM API alternation invariants."""

    tool_call_id: str
    name: str
    content: str
    role: str = "tool"
    is_error: bool = False

    def to_message_dict(self) -> dict[str, str]:
        """Convert to standard message structure accepted by LLM API providers."""
        return {
            "role": self.role,
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "content": self.content,
        }


@dataclass(frozen=True)
class ToolValidationVerdict:
    """Outcome of validating a batch of tool calls before dispatch."""

    action: ToolValidationAction
    executable_calls: tuple[ToolCallEnvelope, ...] = field(default_factory=tuple)
    synthetic_results: tuple[ToolCallResult, ...] = field(default_factory=tuple)
    is_mixed_batch: bool = False
    strike_count: int = 0
    failure_reason: str | None = None
    repaired_names: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class RoleAlternationViolationError(RuntimeError):
    """Raised when conversation history violates strict assistant -> tool -> assistant alternation."""
