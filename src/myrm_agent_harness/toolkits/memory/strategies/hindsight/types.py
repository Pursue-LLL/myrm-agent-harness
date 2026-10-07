"""Type definitions and contracts for Hindsight Experience Replay and Reflection Buffer.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- FailureTurn: Represents a single step in a failed task trajectory.
- FailureTrajectory: Ordered sequence of execution turns culminating in task failure.
- HindsightRule: Actionable counterfactual rule extracted from a failed trajectory.
- PreExecutionWarning: Proactive cautionary directive to inject prior to task execution.
- ReflectionBufferConfig: Operational limits and thresholds for retrospective reflection buffer.

[POS]
Type definitions and contracts for Hindsight Experience Replay and Reflection Buffer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FailureTurn:
    """Represents a single step in a failed task trajectory."""

    turn_index: int
    tool_name: str
    tool_input: dict[str, str | int | float | bool]
    tool_output: str
    error_message: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class FailureTrajectory:
    """Ordered sequence of execution turns culminating in task failure."""

    task_id: str
    task_goal: str
    turns: list[FailureTurn]
    terminal_error: str


@dataclass(frozen=True)
class HindsightRule:
    """Actionable counterfactual rule extracted from a failed trajectory."""

    rule_id: str
    task_pattern: str
    mistake_signature: str
    correction_advice: str
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    hit_count: int = 1
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class PreExecutionWarning:
    """Proactive cautionary directive to inject prior to task execution."""

    rule_id: str
    task_pattern: str
    warning_text: str
    recommended_action: str
    confidence: float


@dataclass(frozen=True)
class ReflectionBufferConfig:
    """Operational limits and thresholds for retrospective reflection buffer."""

    max_capacity: int = 500
    min_confidence: float = 0.5
    max_history_turns: int = 5
