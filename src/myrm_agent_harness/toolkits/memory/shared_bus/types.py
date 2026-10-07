"""跨 Agent 共享记忆总线、并发连接池、背压守卫与方案否决账本的核心类型定义。

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- DecisionVetoSeverity: 否决严重度。
- NegativeDecisionEntry: 方案否决/禁忌决策专属账本条目。
- NegativeDecisionCheckResult: 否决决策前置冲突拦截筛查结果。
- ConcurrencyPoolConfig: 多 Agent 并发连接池与背压守卫配置。
- BackpressureStatus: 当前并发连接池与内存背压健康状态。
- ReinforcedDecayConfig: 命中频次强化与半衰期衰减评分配置。
- ScoredMemoryItem: 经过自学习强化与衰减计算后的记忆条目。

[POS]
跨 Agent 共享记忆总线、并发连接池、背压守卫与方案否决账本的核心类型定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class DecisionVetoSeverity(StrEnum):
    """否决严重度。"""

    HARD_BLOCK = "hard_block"  # 绝对禁忌，严禁采纳
    WARNING = "warning"  # 强烈警示，需附带强力反证才可突破
    ADVISORY = "advisory"  # 参考建议


@dataclass(frozen=True)
class NegativeDecisionEntry:
    """方案否决/禁忌决策专属账本条目。"""

    decision_id: str
    decision_subject: str  # 否决的方案主题/名称 (如 "使用 Redis 缓存向量")
    veto_reason: str  # 为何否决 (如 "增加外部组件依赖且单机沙箱无需分布式缓存")
    alternative_chosen: str  # 最终替代方案 (如 "使用本地 SQLite + 内存 LRU")
    context_summary: str = ""  # 当时的决策上下文与技术代价背景
    severity: DecisionVetoSeverity = DecisionVetoSeverity.HARD_BLOCK
    scope: str = "global"  # 作用域: global / project / agent_role
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class NegativeDecisionCheckResult:
    """否决决策前置冲突拦截筛查结果。"""

    is_blocked: bool
    matched_entries: list[NegativeDecisionEntry] = field(default_factory=list)
    guard_prompt_slice: str = ""
    rejection_summary: str = ""


@dataclass(frozen=True)
class ConcurrencyPoolConfig:
    """多 Agent 并发连接池与背压守卫配置。"""

    max_concurrent_readers: int = 16
    max_concurrent_writers: int = 1
    max_queue_depth: int = 64
    acquire_timeout_seconds: float = 30.0
    memory_rss_threshold_mb: float = 2048.0  # 内存背压警戒线 (MB)
    enable_memory_guard: bool = True


@dataclass(frozen=True)
class BackpressureStatus:
    """当前并发连接池与内存背压健康状态。"""

    active_readers: int
    active_writers: int
    queued_tasks: int
    current_rss_mb: float
    is_throttled: bool
    status_message: str


@dataclass(frozen=True)
class ReinforcedDecayConfig:
    """命中频次强化与半衰期衰减评分配置。"""

    base_weight: float = 1.0
    hit_reinforcement_alpha: float = 0.35  # 对数强化系数: 1 + alpha * ln(1 + hits)
    half_life_days: float = 30.0  # 半衰期天数
    min_score_floor: float = 0.05  # 最低保底分


@dataclass(frozen=True)
class ScoredMemoryItem:
    """经过自学习强化与衰减计算后的记忆条目。"""

    memory_id: str
    content: str
    base_weight: float
    hit_count: int
    last_accessed_at: str
    composite_score: float
    decay_factor: float
    reinforcement_factor: float
