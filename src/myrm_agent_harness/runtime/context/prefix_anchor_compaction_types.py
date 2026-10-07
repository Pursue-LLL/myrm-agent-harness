"""Types and schemas for prefix-anchor-preserving non-linear context compaction.

[INPUT]
Chat history message sequences, token budgets, and anchor tier boundary configurations.

[OUTPUT]
Type-safe anchored descriptors, non-linear compaction plans,
and prefix continuity validation outcomes.

[POS]
Item 124 in topic_06 roadmap: preserves Turn-1 and KV cache topology continuity across compactions.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class AnchorLockTier(StrEnum):
    """Protection tier for an individual message in the context sequence."""
    TURN1_IMMUTABLE = "turn1_immutable"                 # Permanent anchor bearing wall (System + Turn 1)
    RECENT_WINDOW_PRESERVED = "recent_window_preserved" # Tail window preserved for immediate context
    INTERMEDIATE_COMPACTIBLE = "intermediate_compactible" # Mid-session tool payloads eligible for in-place folding


class MessageRoleKind(StrEnum):
    """Canonical role classification for conversational messages."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class AnchoredMessageDescriptor:
    """Representation of a context message with topological anchor metadata."""
    message_id: str
    turn_index: int
    role: MessageRoleKind
    content: str
    token_count: int
    tier: AnchorLockTier = AnchorLockTier.INTERMEDIATE_COMPACTIBLE
    is_turn1_anchor: bool = False
    is_protected: bool = False
    is_folded: bool = False


@dataclass(frozen=True)
class CompactionPlan:
    """Calculated compaction actions to meet the specified token budget."""
    total_input_tokens: int
    target_budget_tokens: int
    tokens_to_prune: int
    preserved_anchor_tokens: int
    foldable_tool_count: int


@dataclass(frozen=True)
class PrefixAnchorCompactionResult:
    """Outcome of non-linear compaction maintaining prefix anchor topology."""
    compacted_messages: tuple[AnchoredMessageDescriptor, ...]
    original_tokens: int
    compacted_tokens: int
    tokens_reclaimed: int
    prefix_overlap_ratio: float  # Fraction of initial tokens identical to pre-compaction prefix (0.0 .. 1.0)
    turn1_preserved: bool
    folded_tool_count: int
    executed_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
