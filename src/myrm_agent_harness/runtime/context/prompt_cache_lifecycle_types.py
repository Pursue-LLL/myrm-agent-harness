"""Prompt-cache aware session lifecycle and prefix preserving router types.

Defines cache prefix fingerprints, in-session mutation risks, rewind pruning
receipts, and pre-idle compaction schedules for Prompt Cache optimization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CacheMutationRiskLevel(StrEnum):
    """Risk severity of in-session mutations on Prompt Cache invalidation."""

    SAFE = "safe"  # Append-only message turns; 100% prefix cache hit
    WARNING = "warning"  # Effort level or minor parameter tuning causing potential cache miss
    DANGEROUS = "dangerous"  # Model switch, system prompt mutation, or tool reordering (100% cache flush)


class CompactionTimingUrgency(StrEnum):
    """Urgency level for scheduling pre-idle cache-preserving compaction."""

    IMMEDIATE = "immediate"  # Cache nearing expiration (<5 min left in TTL window)
    OPPORTUNISTIC = "opportunistic"  # Idle threshold reached within safe TTL window (>15 min left)
    NOT_NEEDED = "not_needed"  # Session active or already compacted


@dataclass(frozen=True)
class CachePrefixFingerprint:
    """Deterministic cryptographic fingerprint representing the immutable prefix chain."""

    tool_registry_hash: str
    system_prompt_hash: str
    persona_hash: str
    prefix_token_count: int
    combined_fingerprint: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class InSessionMutationRiskReport:
    """Audit report assessing the economic impact of parameter or model changes."""

    risk_level: CacheMutationRiskLevel
    is_mutation_destructive: bool
    current_model: str
    proposed_model: str
    cached_prefix_tokens: int
    wasted_prefill_tokens: int
    estimated_cost_multiplier: float  # e.g., 10x~30x cost increase on cache miss
    recommendation: str


@dataclass(frozen=True)
class RewindPruneReceipt:
    """Receipt tracking tail message trimming without destroying prefix cache."""

    original_turn_count: int
    pruned_turn_count: int
    remaining_turn_count: int
    preserved_prefix_tokens: int
    pruned_tail_tokens: int
    cache_preserved: bool
    summary: str


@dataclass(frozen=True)
class PreIdleCompactionPlan:
    """Execution plan for compacting session before cloud cache TTL expires."""

    urgency: CompactionTimingUrgency
    session_idle_seconds: float
    cache_ttl_remaining_seconds: float
    estimated_compaction_cost_tokens: int
    should_execute: bool
    strategy: str
