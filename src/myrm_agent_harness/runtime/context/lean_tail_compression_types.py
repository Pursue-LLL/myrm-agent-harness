"""Data types and schemas for Lean-Tail compression and reasoning trace stripping.

Strictly typed, 0 Any. Defines fixed-interval tail bounds, reasoning strip kinds,
and sub-512k threshold floor rules.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ReasoningTagKind: Known reasoning and chain-of-thought XML tags.
- LeanTailConfig: Configuration for Lean-Tail compaction with fixed tail preservation.
- LeanTailWindowBudget: Computed context budget and tail allocation.
- StrippedMessageResult: Outcome of reasoning trace stripping on a message.
- LeanTailCompactionPlan: Computed plan for lean-tail compaction.

[POS]
Data types and schemas for Lean-Tail compression and reasoning trace stripping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ReasoningTagKind(StrEnum):
    """Known reasoning and chain-of-thought XML tags."""

    THINK = "think"
    THOUGHT = "thought"
    REASONING = "reasoning"
    INTERNAL_COT = "internal_cot"


@dataclass(frozen=True)
class LeanTailConfig:
    """Configuration for Lean-Tail compaction with fixed tail preservation."""

    floor_tokens: int = 10_000
    cap_tokens: int = 25_000
    target_summary_tokens: int = 2_000
    sub_512k_threshold_floor: float = 0.75
    default_trigger_threshold: float = 0.80
    target_tags: set[ReasoningTagKind] = field(
        default_factory=lambda: {
            ReasoningTagKind.THINK,
            ReasoningTagKind.THOUGHT,
            ReasoningTagKind.REASONING,
            ReasoningTagKind.INTERNAL_COT,
        }
    )


@dataclass(frozen=True)
class LeanTailWindowBudget:
    """Computed context budget and tail allocation."""

    context_window_size: int
    effective_threshold: float
    trigger_tokens: int
    protected_tail_tokens: int
    is_floored_to_75_percent: bool


@dataclass(frozen=True)
class StrippedMessageResult:
    """Outcome of reasoning trace stripping on a message."""

    role: str
    cleaned_content: str
    stripped_chars_count: int
    tags_removed_count: int


@dataclass(frozen=True)
class LeanTailCompactionPlan:
    """Computed plan for lean-tail compaction."""

    total_tokens: int
    budget: LeanTailWindowBudget
    needs_compaction: bool
    messages_to_compact_count: int
    protected_tail_messages_count: int
    summarizer_prompt_instructions: str
