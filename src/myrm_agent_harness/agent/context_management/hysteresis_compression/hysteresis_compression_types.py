"""Type definitions and contracts for Hysteresis Compression and Cooldown Ladder Suite.

Defines dual-watermark hysteresis levels, cooldown ladder lifecycle states,
critical memory sanctuary boundaries, and execution reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class WatermarkTier(StrEnum):
    """Context utilization tier relative to hysteresis boundaries."""

    NORMAL = "normal"  # Under low watermark (< 50%)
    IN_GAP = "in_gap"  # In operational hysteresis buffer zone (50% ~ 85%)
    HIGH_WATERMARK = "high_watermark"  # Hit trigger watermark (>= 85%), needs deep compaction
    EMERGENCY_OVERFLOW = "emergency_overflow"  # Hit emergency barrier (>= 95%), override cooldown


class SanctuaryCategory(StrEnum):
    """Categorical classification of immutable, non-compressible memory blocks."""

    GENESIS_PROMPT = "genesis_prompt"  # Initial user instruction and system anchor
    ACTIVE_TODO = "active_todo"  # Incomplete tasks, checklist items, and active plans
    DIFF_ANCHOR = "diff_anchor"  # Uncommitted or critical code diff hunks
    INVARIANT_CONTRACT = "invariant_contract"  # Architectural rules and invariant constraints
    USER_EXPLICIT = "user_explicit"  # Explicitly marked immutable by user or developer


@dataclass(frozen=True)
class SanctuaryBlock:
    """An immutable, non-compressible sanctuary block protected from summarization."""

    block_id: str
    category: SanctuaryCategory
    content: str
    estimated_tokens: int
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class CooldownStatus:
    """Snapshot of adaptive cooldown ladder status."""

    is_in_cooldown: bool
    remaining_turns: int
    current_ladder_step: int
    ladder_cooldown_turns: int


@dataclass(frozen=True)
class HysteresisEvaluation:
    """Evaluation result assessing whether context compaction should be triggered."""

    should_compress: bool
    tier: WatermarkTier
    current_tokens: int
    max_context_tokens: int
    usage_ratio: float
    target_reclaim_tokens: int
    is_emergency: bool
    cooldown_suppressed: bool
    decision_reason: str


@dataclass(frozen=True)
class HysteresisConfig:
    """Configuration governing dual-watermark hysteresis and cooldown ladders."""

    high_watermark_ratio: float = 0.85
    low_watermark_ratio: float = 0.50
    emergency_watermark_ratio: float = 0.95
    base_cooldown_turns: int = 5
    ladder_escalation_step: int = 2
    max_cooldown_turns: int = 15
    max_context_tokens: int = 128000
    bytes_per_token_estimate: float = 4.0


@dataclass(frozen=True)
class HysteresisExecutionReport:
    """Execution telemetry emitted after applying hysteresis-aware compaction."""

    original_tokens: int
    reclaimed_tokens: int
    final_tokens: int
    sanctuary_tokens_preserved: int
    sanctuary_blocks_count: int
    cooldown_activated_turns: int
    ladder_stage: int
    executed_at: float = field(default_factory=time.time)
