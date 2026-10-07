"""Types and data contracts for prompt cache break prevention shield and smart session branching.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- CacheRiskLevel: Risk severity classification for in-flight parameter mutation.
- CacheParameterKind: Categories of runtime parameters altering provider cache keys.
- CacheBreakEvaluation: Structural assessment of prompt cache destruction risk.
- CachePreservingForkResult: Result of non-destructive branch forking retaining antecedent cache.
- CacheRewindResult: Result of tail-only rewind operation maintaining prompt cache prefix match.

[POS]
Data contracts for cache break interception, cost impact evaluation, and smart cache branching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class CacheRiskLevel(str, Enum):
    """Risk severity classification for in-flight parameter mutation."""

    SAFE = "safe"  # Mutation does not invalidate upstream provider prompt cache
    LOW = "low"  # Minimal cache invalidation under threshold tokens
    MEDIUM = "medium"  # Thinking level or effort changed on long context
    HIGH = "high"  # Model switched mid-session, completely wiping prompt cache
    CRITICAL = "critical"  # Massive token cache destroyed; high cost penalty


class CacheParameterKind(str, Enum):
    """Categories of runtime parameters altering provider cache keys."""

    MODEL = "model"
    THINKING_LEVEL = "thinking_level"
    SYSTEM_PROMPT = "system_prompt"
    TOOL_SET = "tool_set"


@dataclass(frozen=True, slots=True)
class CacheBreakEvaluation:
    """Structural assessment of prompt cache destruction risk.

    Provides user-friendly advice and economic penalty estimates when
    a mid-session configuration change would cause massive cache misses.
    """

    risk_level: CacheRiskLevel
    parameter_kind: CacheParameterKind
    old_value: str
    new_value: str
    cached_tokens_at_risk: int
    estimated_cost_multiplier_penalty: float
    warning_message: str
    recommended_action: str  # 'fork_branch' | 'apply_in_place' | 'cancel'
    is_blocking_alert: bool = False


@dataclass(frozen=True, slots=True)
class CachePreservingForkResult:
    """Result of non-destructive branch forking retaining antecedent cache."""

    new_branch_id: str
    source_branch_id: str
    fork_anchor_turn: int
    preserved_cache_tokens: int
    transition_summary: str
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class CacheRewindResult:
    """Result of tail-only rewind operation maintaining prompt cache prefix match.

    By strictly dropping subsequent turns from the tail without altering
    historical prefix byte order, 100% of the upstream prompt cache remains intact.
    """

    session_id: str
    dropped_turns_count: int
    retained_turns_count: int
    cache_prefix_intact: bool
    retained_cache_tokens_estimate: int
