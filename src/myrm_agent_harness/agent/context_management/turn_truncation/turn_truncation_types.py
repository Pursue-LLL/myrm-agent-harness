"""Strongly typed contracts for In-Flight Turn State Truncation and Prefix Cache Stability Gate.

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- TurnExecutionState: Lifecycle phase of an active execution turn.
- IntermediateTrialKind: Classification of discarded in-flight trial attempts.
- TrialStepRecord: Audit trace of an in-flight trial-and-error action.
- TruncationPolicy: Rules governing how in-flight failures are pruned prior to turn commit.
- CanonicalTurnCommit: Structured, finalized turn payload guaranteed safe for prefix caching.
- PrefixCacheStabilityReport: Predictive audit of cache hit probability and reclaimed tokens.

[POS]
Defines data structures powering KV cache-aligned turn pruning,
canonical turn commits, and provider prompt cache preservation.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class TurnExecutionState(str, enum.Enum):
    """Lifecycle phase of a single conversation turn."""

    IN_FLIGHT = "in_flight"
    COMMITTED = "committed"
    TRUNCATED_AND_COMMITTED = "truncated_and_committed"
    ROLLED_BACK = "rolled_back"


class IntermediateTrialKind(str, enum.Enum):
    """Classification of ephemeral trial-and-error intermediate states."""

    PROBE = "probe"
    SYNTAX_ERROR_RETRY = "syntax_error_retry"
    FAILED_TOOL_CALL = "failed_tool_call"
    REDUNDANT_DISCOVERY = "redundant_discovery"


@dataclass(frozen=True, slots=True)
class TrialStepRecord:
    """Audit footprint of an in-flight intermediate trial step."""

    step_index: int
    kind: IntermediateTrialKind
    tool_name: str
    error_message: str
    raw_char_count: int
    timestamp: float = field(default_factory=time.time)


class TruncationPolicy(str, enum.Enum):
    """Policy dictating how intermediate in-flight trials are cleansed."""

    PRUNE_ALL_FAILURES_KEEP_CANONICAL = "prune_all_failures_keep_canonical"
    FOLD_FAILURES_TO_ONE_LINE = "fold_failures_to_one_line"
    PASSTHROUGH_DIRTY = "passthrough_dirty"


@dataclass(slots=True)
class CanonicalTurnCommit:
    """Authoritative, cleansed turn payload safely committed to session history."""

    turn_id: str
    canonical_messages: list[dict[str, object]]
    pruned_trials_count: int
    reclaimed_tokens_estimate: int
    prefix_cache_safe: bool
    state: TurnExecutionState
    committed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes canonical commit to a JSON-compatible dictionary."""
        return {
            "turn_id": self.turn_id,
            "pruned_trials_count": self.pruned_trials_count,
            "reclaimed_tokens_estimate": self.reclaimed_tokens_estimate,
            "prefix_cache_safe": self.prefix_cache_safe,
            "state": self.state.value,
            "message_count": len(self.canonical_messages),
            "committed_at": self.committed_at,
        }


@dataclass(slots=True)
class PrefixCacheStabilityReport:
    """Predictive diagnostic of session prefix stability and provider KV cache hit likelihood."""

    total_turns: int
    canonical_turns: int
    prefix_digest: str
    cache_hit_likelihood_pct: float
    total_reclaimed_tokens: int
    is_prefix_stable: bool

    def to_dict(self) -> dict[str, object]:
        """Serializes stability report into a dictionary."""
        return {
            "total_turns": self.total_turns,
            "canonical_turns": self.canonical_turns,
            "prefix_digest": self.prefix_digest,
            "cache_hit_likelihood_pct": self.cache_hit_likelihood_pct,
            "total_reclaimed_tokens": self.total_reclaimed_tokens,
            "is_prefix_stable": self.is_prefix_stable,
        }
