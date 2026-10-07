"""Type definitions for Dual-Tier Micro/Full Adaptive Compactor, Mid-Task Steering,
and Tool Loop Tracker Watchdog.

Reference: Alibaba Qianwen App Office Mode (query2() loop, ToolLoopTracker, steer queue).
Strict 0 Any, immutable frozen dataclasses for deterministic execution.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- CompactorTierKind: Enumeration of compaction tiers.
- MicroFoldedItem: Record of an individual folded tool result.
- DualTierCompactorDecision: Outcome report of dual-tier adaptive compaction.
- SteerInstruction: User mid-task steering instruction safely queued for the next step.
- ToolCallSignature: Fingerprint of a tool call used to detect repetition and oscillation.
- ToolLoopCircuitState: Status emitted by the ToolLoopTracker circuit breaker.

[POS]
Type definitions for Dual-Tier Micro/Full Adaptive Compactor, Mid-Task Steering, and Tool Loop Tracker
Watchdog.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CompactorTierKind(StrEnum):
    """Enumeration of compaction tiers."""

    NONE = "none"
    MICRO = "micro"  # Rule-based tool output folding (0 LLM cost)
    FULL = "full"    # Deep semantic restructuring


@dataclass(frozen=True)
class MicroFoldedItem:
    """Record of an individual folded tool result."""

    index: int
    tool_name: str
    original_chars: int
    folded_chars: int
    saved_tokens: int


@dataclass(frozen=True)
class DualTierCompactorDecision:
    """Outcome report of dual-tier adaptive compaction."""

    tier: CompactorTierKind
    triggered: bool
    tokens_before: int
    tokens_after: int
    saved_tokens: int
    folded_items: tuple[MicroFoldedItem, ...]
    details: str


@dataclass(frozen=True)
class SteerInstruction:
    """User mid-task steering instruction safely queued for the next step."""

    instruction_id: str
    content: str
    timestamp: float
    priority: int = 1


@dataclass(frozen=True)
class ToolCallSignature:
    """Fingerprint of a tool call used to detect repetition and oscillation."""

    tool_name: str
    canonical_args_hash: str
    is_error: bool = False


@dataclass(frozen=True)
class ToolLoopCircuitState:
    """Status emitted by the ToolLoopTracker circuit breaker."""

    is_tripped: bool
    trip_reason: str
    repeated_count: int
    tool_name: str
    remediation_directive: str = ""
