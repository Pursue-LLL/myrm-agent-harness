"""跨 Agent 共享记忆总线中枢，集成方案否决账本、并发连接池、背压守卫与强化衰减打分器。

[INPUT]
- toolkits.memory.shared_bus.concurrency_pool::SharedMemoryConcurrencyPool (POS: 多 Agent
  共享并发连接池与内存背压守卫，保障高并发读写不锁死、内存不击穿。)
- toolkits.memory.shared_bus.decay_scorer::ReinforcedDecayScorer (POS:
  命中频次正向强化与时间半衰期衰减联合打分器，实现常用常新、长期未用平滑遗忘。)
- toolkits.memory.shared_bus.negative_ledger::NegativeDecisionLedger (POS:
  方案否决与禁忌决策专属账本，前置拦截已被废弃的方案，彻底杜绝 AI 重复踩坑。)
- toolkits.memory.shared_bus.types::BackpressureStatus, ConcurrencyPoolConfig, NegativeDecisionCheckResult,
  NegativeDecisionEntry, ReinforcedDecayConfig, ScoredMemoryItem (POS: 跨 Agent
  共享记忆总线、并发连接池、背压守卫与方案否决账本的核心类型定义。)

[OUTPUT]
- MultiAgentSharedMemoryBus: 跨 Agent 共享记忆协同总线。

[POS]
跨 Agent 共享记忆总线中枢，集成方案否决账本、并发连接池、背压守卫与强化衰减打分器。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from myrm_agent_harness.toolkits.memory.shared_bus.concurrency_pool import (
    SharedMemoryConcurrencyPool,
)
from myrm_agent_harness.toolkits.memory.shared_bus.decay_scorer import (
    ReinforcedDecayScorer,
)
from myrm_agent_harness.toolkits.memory.shared_bus.negative_ledger import (
    NegativeDecisionLedger,
)
from myrm_agent_harness.toolkits.memory.shared_bus.types import (
    BackpressureStatus,
    ConcurrencyPoolConfig,
    NegativeDecisionCheckResult,
    NegativeDecisionEntry,
    ReinforcedDecayConfig,
    ScoredMemoryItem,
)


class MultiAgentSharedMemoryBus:
    """跨 Agent 共享记忆协同总线。"""

    def __init__(
        self,
        pool_config: ConcurrencyPoolConfig | None = None,
        decay_config: ReinforcedDecayConfig | None = None,
    ) -> None:
        self._ledger = NegativeDecisionLedger()
        self._pool = SharedMemoryConcurrencyPool(config=pool_config)
        self._scorer = ReinforcedDecayScorer(config=decay_config)

    @property
    def ledger(self) -> NegativeDecisionLedger:
        """获取方案否决账本实例。"""
        return self._ledger

    @property
    def pool(self) -> SharedMemoryConcurrencyPool:
        """获取并发连接池实例。"""
        return self._pool

    @property
    def scorer(self) -> ReinforcedDecayScorer:
        """获取自学习评分器实例。"""
        return self._scorer

    # 1. 方案否决与拦截
    def record_veto(self, entry: NegativeDecisionEntry) -> None:
        """记录被否决的禁忌方案。"""
        self._ledger.record_veto(entry)

    def check_proposal(
        self, proposal: str, scope: str = "global"
    ) -> NegativeDecisionCheckResult:
        """筛查候选提案是否违反历史否决禁忌。"""
        return self._ledger.check_veto_conflict(proposal, scope=scope)

    def list_vetoes(self, scope: str | None = None) -> list[NegativeDecisionEntry]:
        """获取历史否决记录。"""
        return self._ledger.list_vetoes(scope=scope)

    # 2. 并发读写与背压
    def read_session(self) -> AsyncIterator[None]:
        """获取共享读通道上下文。"""
        return self._pool.read_session()

    def write_session(self) -> AsyncIterator[None]:
        """获取独占写通道上下文。"""
        return self._pool.write_session()

    def get_pool_status(self) -> BackpressureStatus:
        """获取当前并发池与内存背压状态。"""
        return self._pool.get_status()

    # 3. 自学习打分与热度排序
    def score_memory(
        self,
        memory_id: str,
        content: str,
        base_weight: float = 1.0,
        hit_count: int = 0,
        last_accessed_at: str | None = None,
    ) -> ScoredMemoryItem:
        """计算单条记忆在总线中的自学习热度得分。"""
        return self._scorer.score_item(
            memory_id=memory_id,
            content=content,
            base_weight=base_weight,
            hit_count=hit_count,
            last_accessed_at=last_accessed_at,
        )

    def rank_memories(
        self, items: list[ScoredMemoryItem], reverse: bool = True
    ) -> list[ScoredMemoryItem]:
        """按总线复合得分进行降序排位。"""
        return self._scorer.rank_items(items, reverse=reverse)
