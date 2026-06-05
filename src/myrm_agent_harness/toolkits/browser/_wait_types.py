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
Provides shared type foundation for wait_strategies.py and _wait_impl.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock
from typing import Literal, TypedDict

# Type别名
ReasonType = Literal["quiet", "capped", "network_only", "dom_only", "both", "first_completed"]


class DOMStableResult(TypedDict):
    """DOMstable检测JavaScriptReturnResult."""

    reason: str
    elapsed_ms: int
    mutation_count: int
    reset_count: int
    shadow_count: int


class WaitStrategy(StrEnum):
    """WaitStrategyType."""

    NETWORKIDLE = "networkidle"  # Only网络Empty闲
    DOM_STABLE = "dom_stable"  # OnlyDOMstable
    HYBRID = "hybrid"  # 混合检测（DOM + 网络）
    SMART = "smart"  # 自适应检测（优先networkidlefastPath，Timeout则 using hybrid）
    SPA_STABLE = "spa_stable"  # SPA稳态检测（智能网络噪音过滤+MutationObserver）


@dataclass(frozen=True, slots=True)
class WaitMetrics:
    """WaitMetrics（complete可观测性）.

    Attributes:
        strategy:  using  WaitStrategy
        reason: Completeoriginal因
            - quiet: DOMnormalstable
            - capped: Timeout
            - network_only: Only网络Empty闲Complete
            - dom_only: OnlyDOMstableComplete
            - both: DOM and 网络都Complete
            - first_completed: 任一Completei.e.Return
        elapsed_ms: 实际Wait时长（毫秒）
        network_idle_ms: 网络Empty闲耗时（None表示 not yet Complete or  not yet  using ）
        dom_stable_ms: DOMstable耗时（None表示 not yet Complete or  not yet  using ）
        dom_mutation_count: DOM变更总数
        dom_reset_count: 静默期Reset次数
        shadow_dom_count: 监听 Shadow DOMCount
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
        """Convert is LogDict."""
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
    """混合检测 in 间Result（Internal using ）."""

    dom_result: dict[str, object] | None = None
    dom_elapsed_ms: int | None = None
    network_elapsed_ms: int | None = None
    reason: ReasonType = "first_completed"


@dataclass
class WaitStrategyStats:
    """WaitStrategy运行时Statistics（thread-safe）.

    provides生产环境可观测性， for Data驱动optimized。
    """

    # Strategy using 次数
    strategy_counts: dict[str, int] = field(default_factory=dict)

    # SMARTStrategyStatistics
    smart_fast_path_hits: int = 0  # fastPathSuccess（networkidle）
    smart_fast_path_misses: int = 0  # fastPath not yet Success， using hybrid

    # HYBRIDStrategyStatistics
    hybrid_both_completed: int = 0  # 双检测都Complete
    hybrid_first_completed: int = 0  # Only一个Complete

    # 总体Statistics
    total_calls: int = 0
    total_elapsed_ms: float = 0.0

    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def record_call(
        self,
        strategy: WaitStrategy,
        reason: ReasonType,
        elapsed_ms: int,
    ) -> None:
        """Record一次Call."""
        with self._lock:
            self.total_calls += 1
            self.total_elapsed_ms += elapsed_ms

            strategy_name = str(strategy.value)
            self.strategy_counts[strategy_name] = self.strategy_counts.get(strategy_name, 0) + 1

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
        """GetStatisticsData（thread-safe）."""
        with self._lock:
            stats: dict[str, object] = {
                "total_calls": self.total_calls,
                "avg_elapsed_ms": (self.total_elapsed_ms / self.total_calls if self.total_calls > 0 else 0),
                "strategy_usage": dict(self.strategy_counts),
            }

            smart_total = self.smart_fast_path_hits + self.smart_fast_path_misses
            if smart_total > 0:
                stats["smart_fast_path_hit_rate"] = self.smart_fast_path_hits / smart_total
                stats["smart_fast_path_hits"] = self.smart_fast_path_hits
                stats["smart_fast_path_misses"] = self.smart_fast_path_misses

            hybrid_total = self.hybrid_both_completed + self.hybrid_first_completed
            if hybrid_total > 0:
                stats["hybrid_both_rate"] = self.hybrid_both_completed / hybrid_total
                stats["hybrid_both_completed"] = self.hybrid_both_completed
                stats["hybrid_first_completed"] = self.hybrid_first_completed

            return stats

    def reset(self) -> None:
        """ResetStatistics（thread-safe）."""
        with self._lock:
            self.strategy_counts.clear()
            self.smart_fast_path_hits = 0
            self.smart_fast_path_misses = 0
            self.hybrid_both_completed = 0
            self.hybrid_first_completed = 0
            self.total_calls = 0
            self.total_elapsed_ms = 0


# GlobalStatisticsInstance
_global_stats = WaitStrategyStats()


def get_wait_strategy_stats() -> dict[str, object]:
    """GetGlobalWaitStrategyStatistics.

    Returns:
        StatisticsDataDict，Contains：
        - total_calls: 总Call次数
        - avg_elapsed_ms: 平均Wait时长
        - strategy_usage: 各Strategy using 次数
        - smart_fast_path_hit_rate: SMARTStrategyfastPath命 in 率
        - hybrid_both_rate: HYBRIDStrategy双Complete率

    Examples:
        >>> stats = get_wait_strategy_stats()
        >>> print(f"Fast path hit rate: {stats.get('smart_fast_path_hit_rate', 0):.1%}")
    """
    return _global_stats.get_stats()


def reset_wait_strategy_stats() -> None:
    """ResetGlobalWaitStrategyStatistics（ for 测试）."""
    _global_stats.reset()
