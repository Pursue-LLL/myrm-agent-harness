"""Data types and schemas for default lossless lean-tail conversation compaction.

Strictly typed, 0 Any. Implements message importance classification,
lossless tool reduction, and constraint anchor preservation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MessageImportanceTier(StrEnum):
    """Categorical importance level for conversation messages."""

    CRITICAL = "critical"  # System prompt, initial user prompt, explicit anchors
    HIGH = "high"          # Recent active turns, unresolved errors
    MEDIUM = "medium"      # Standard reasoning / dialogue
    VOLATILE = "volatile"  # Bulky tool outputs, verbose grep/web dumps


@dataclass(frozen=True)
class ClassifiedMessage:
    """A message tagged with importance tier and character weight."""

    index: int
    role: str
    content: str
    importance: MessageImportanceTier
    is_tool_call: bool = False
    is_tool_result: bool = False
    token_estimate: int = 0


@dataclass(frozen=True)
class ConstraintAnchor:
    """Immutable user intent or business constraint anchored across compaction."""

    anchor_id: str
    original_text: str
    source_turn: int
    tags: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class LosslessCompactorConfig:
    """Configuration for lossless lean-tail compaction."""

    tool_output_length_threshold: int = 400
    protected_recent_turns: int = 3
    always_preserve_initial_user_prompt: bool = True
    enable_tool_lean_reducer: bool = True
    enable_core_constraint_anchoring: bool = True


@dataclass(frozen=True)
class LeanReductionStats:
    """Metrics and statistics for lossless lean-tail reduction."""

    original_tokens_estimate: int
    compacted_tokens_estimate: int
    tokens_saved_estimate: int
    reduction_percentage: float
    volatile_tool_outputs_reduced: int
    anchors_preserved_count: int
