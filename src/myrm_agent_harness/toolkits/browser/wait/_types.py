"""Wait strategy types, metrics, and runtime statistics.


[INPUT]
- dataclasses::dataclass, field (POS: Python dataclass)
- threading::Lock (POS: thread lock)
- enum::StrEnum (POS: string enum)
- typing::Literal, TypedDict (POS: type definitions)

[OUTPUT]
- ReasonType: completion reason type alias
- DOMStableResult: DOM stability detection JavaScript return result
- WaitStrategy: wait strategy enum (4 types)
- WaitMetrics: wait metrics (frozen dataclass, full observability)
- WaitStrategyStats: runtime statistics class (thread-safe)
- get_wait_strategy_stats: retrieve global statistics
- reset_wait_strategy_stats: reset statistics (for testing)

[POS]
Wait strategy type definitions and runtime statistics module.
Provides shared type foundation for wait/__init__.py and wait/_impl.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock
from typing import Literal, TypedDict

# Reason type alias
ReasonType = Literal[
    "quiet", "capped", "network_only", "dom_only", "both", "first_completed"
]


class DOMStableResult(TypedDict):
    """Result returned by the DOM stability detection JavaScript."""

    reason: str
    elapsed_ms: int
    mutation_count: int
    reset_count: int
    shadow_count: int


class WaitStrategy(StrEnum):
    """Available wait strategy types."""

    NETWORKIDLE = "networkidle"  # Network idle only
    DOM_STABLE = "dom_stable"  # DOM stability only
    HYBRID = "hybrid"  # DOM + network combined
    SMART = "smart"  # Adaptive (networkidle fast path, hybrid fallback)
    SPA_STABLE = "spa_stable"  # SPA stability (network noise filter + MutationObserver)


@dataclass(frozen=True, slots=True)
class WaitMetrics:
    """Wait metrics (full observability).

    Attributes:
        strategy: Wait strategy used
        reason: Completion reason
            - quiet: DOM became stable normally
            - capped: Timed out
            - network_only: Only network idle completed
            - dom_only: Only DOM stability completed
            - both: Both DOM and network completed
            - first_completed: Returned as soon as either completed
        elapsed_ms: Actual wait duration (ms)
        network_idle_ms: Network idle duration (None if not completed or not used)
        dom_stable_ms: DOM stability duration (None if not completed or not used)
        dom_mutation_count: Total DOM mutations
        dom_reset_count: Number of quiet-window resets
        shadow_dom_count: Number of observed Shadow DOM roots
    """

    strategy: WaitStrategy
    reason: ReasonType
    elapsed_ms: int
    network_idle_ms: int | None = None
    dom_stable_ms: int | None = None
    dom_mutation_count: int = 0
    dom_reset_count: int = 0
    shadow_dom_count: int = 0

    def to_log_dict(self) -> dict[str, object]:
        """Convert to a JSON-friendly logging dict."""
        return {
            "strategy": self.strategy,
            "reason": self.reason,
            "elapsed_ms": self.elapsed_ms,
            "network_idle_ms": self.network_idle_ms,
            "dom_stable_ms": self.dom_stable_ms,
            "dom_mutation_count": self.dom_mutation_count,
            "dom_reset_count": self.dom_reset_count,
            "shadow_dom_count": self.shadow_dom_count,
        }


@dataclass
class _HybridTaskResult:
    """Intermediate result for hybrid detection (internal use)."""

    dom_result: dict[str, object] | None = None
    dom_elapsed_ms: int | None = None
    network_elapsed_ms: int | None = None
    reason: ReasonType = "first_completed"


@dataclass
class WaitStrategyStats:
    """Runtime statistics for wait strategies (thread-safe).

    Provides production observability to drive data-based optimization.
    """

    # Strategy usage counts
    strategy_counts: dict[str, int] = field(default_factory=dict)

    # SMART strategy statistics
    smart_fast_path_hits: int = 0  # Fast path succeeded (networkidle)
    smart_fast_path_misses: int = 0  # Fast path failed, fell back to hybrid

    # HYBRID strategy statistics
    hybrid_both_completed: int = 0  # Both detections completed
    hybrid_first_completed: int = 0  # Only one completed

    # Overall statistics
    total_calls: int = 0
    total_elapsed_ms: float = 0.0

    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def record_call(
        self,
        strategy: WaitStrategy,
        reason: ReasonType,
        elapsed_ms: int,
    ) -> None:
        """Record a single wait call."""
        with self._lock:
            self.total_calls += 1
            self.total_elapsed_ms += elapsed_ms

            strategy_name = str(strategy.value)
            self.strategy_counts[strategy_name] = (
                self.strategy_counts.get(strategy_name, 0) + 1
            )

            if strategy == WaitStrategy.SMART:
                if reason == "network_only":
                    self.smart_fast_path_hits += 1
                elif reason in ("both", "first_completed", "dom_only"):
                    self.smart_fast_path_misses += 1

            elif strategy == WaitStrategy.HYBRID:
                if reason == "both":
                    self.hybrid_both_completed += 1
                elif reason == "first_completed":
                    self.hybrid_first_completed += 1

    def get_stats(self) -> dict[str, object]:
        """Get statistics data (thread-safe)."""
        with self._lock:
            stats: dict[str, object] = {
                "total_calls": self.total_calls,
                "avg_elapsed_ms": (
                    self.total_elapsed_ms / self.total_calls
                    if self.total_calls > 0
                    else 0
                ),
                "strategy_usage": dict(self.strategy_counts),
            }

            smart_total = self.smart_fast_path_hits + self.smart_fast_path_misses
            if smart_total > 0:
                stats["smart_fast_path_hit_rate"] = (
                    self.smart_fast_path_hits / smart_total
                )
                stats["smart_fast_path_hits"] = self.smart_fast_path_hits
                stats["smart_fast_path_misses"] = self.smart_fast_path_misses

            hybrid_total = self.hybrid_both_completed + self.hybrid_first_completed
            if hybrid_total > 0:
                stats["hybrid_both_rate"] = self.hybrid_both_completed / hybrid_total
                stats["hybrid_both_completed"] = self.hybrid_both_completed
                stats["hybrid_first_completed"] = self.hybrid_first_completed

            return stats

    def reset(self) -> None:
        """Reset statistics (thread-safe)."""
        with self._lock:
            self.strategy_counts.clear()
            self.smart_fast_path_hits = 0
            self.smart_fast_path_misses = 0
            self.hybrid_both_completed = 0
            self.hybrid_first_completed = 0
            self.total_calls = 0
            self.total_elapsed_ms = 0


# Global statistics instance
_global_stats = WaitStrategyStats()


def get_wait_strategy_stats() -> dict[str, object]:
    """Get global wait strategy statistics.

    Returns:
        Statistics dict containing:
        - total_calls: Total call count
        - avg_elapsed_ms: Average wait duration
        - strategy_usage: Per-strategy usage count
        - smart_fast_path_hit_rate: SMART strategy fast path hit rate
        - hybrid_both_rate: HYBRID strategy both-completed rate

    Examples:
        >>> stats = get_wait_strategy_stats()
        >>> print(f"Fast path hit rate: {stats.get('smart_fast_path_hit_rate', 0):.1%}")
    """
    return _global_stats.get_stats()


def reset_wait_strategy_stats() -> None:
    """Reset global wait strategy statistics (for testing)."""
    _global_stats.reset()
