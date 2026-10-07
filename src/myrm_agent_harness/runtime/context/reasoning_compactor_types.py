"""Type definitions for reasoning-preserving context compactor and token compression governor.

Inspired by OpenAI Codex Harness ARC-AGI-3 core mechanisms.
Provides data models for reasoning retention anchors, tiered budgets, and compaction results.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ReasoningPreservationMode: Modes for preserving cross-turn reasoning streams.
- CompactionTier: Compaction hierarchy tiers applied adaptively based on token budget.
- TieredTokenBudget: Multi-dimensional token budget configuration for text, reasoning, and multimodal
  content.
- ReasoningChainAnchor: Condensed architectural and logical deduction anchor preserved across turns.
- UnifiedCompactedTurn: A sanitized turn post-governance compaction.
- GovernanceCompactionResult: Comprehensive diagnostic result from the tiered token compression governor.

[POS]
Type definitions for reasoning-preserving context compactor and token compression governor.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class ReasoningPreservationMode(StrEnum):
    """Modes for preserving cross-turn reasoning streams."""

    FULL_RETENTION = "full_retention"
    CONDENSED_ANCHORS = "condensed_anchors"
    STRIP_ALL = "strip_all"


class CompactionTier(StrEnum):
    """Compaction hierarchy tiers applied adaptively based on token budget."""

    TIER_1_TOOLS = "tier_1_tools"
    TIER_2_IMAGES = "tier_2_images"
    TIER_3_REASONING = "tier_3_reasoning"
    TIER_4_TEXT_CUT = "tier_4_text_cut"


@dataclass(frozen=True)
class TieredTokenBudget:
    """Multi-dimensional token budget configuration for text, reasoning, and multimodal content."""

    max_total_tokens: int = 32768
    max_text_tokens: int = 20000
    max_reasoning_tokens: int = 6000
    max_image_tokens: int = 4000
    retain_recent_turns: int = 2


@dataclass(frozen=True)
class ReasoningChainAnchor:
    """Condensed architectural and logical deduction anchor preserved across turns."""

    turn_index: int
    core_hypothesis: str
    key_counter_arguments: str
    finalized_deduction: str
    original_tokens_est: int
    condensed_tokens_est: int


@dataclass(frozen=True)
class UnifiedCompactedTurn:
    """A sanitized turn post-governance compaction."""

    turn_index: int
    role: str
    content: str
    reasoning_anchor: ReasoningChainAnchor | None = None
    tool_calls_summary: str | None = None
    is_image_degraded: bool = False


@dataclass(frozen=True)
class GovernanceCompactionResult:
    """Comprehensive diagnostic result from the tiered token compression governor."""

    original_total_tokens: int
    final_total_tokens: int
    compressed_tokens: int
    tiers_applied: list[CompactionTier]
    reasoning_anchors_count: int
    native_server_side_eligible: bool
    compacted_turns: list[UnifiedCompactedTurn] = field(default_factory=list)
