"""跨 Agent 共享记忆总线、并发连接池与方案否决账本模块。

[INPUT]
- toolkits.memory.shared_bus.bus::MultiAgentSharedMemoryBus (POS: 跨 Agent
  共享记忆总线中枢，集成方案否决账本、并发连接池、背压守卫与强化衰减打分器。)
- toolkits.memory.shared_bus.concurrency_pool::MemoryBackpressureGuard, SharedMemoryConcurrencyPool (POS: 多
  Agent 共享并发连接池与内存背压守卫，保障高并发读写不锁死、内存不击穿。)
- toolkits.memory.shared_bus.decay_scorer::ReinforcedDecayScorer (POS:
  命中频次正向强化与时间半衰期衰减联合打分器，实现常用常新、长期未用平滑遗忘。)
- toolkits.memory.shared_bus.negative_ledger::NegativeDecisionLedger (POS:
  方案否决与禁忌决策专属账本，前置拦截已被废弃的方案，彻底杜绝 AI 重复踩坑。)
- toolkits.memory.shared_bus.types::BackpressureStatus, ConcurrencyPoolConfig, DecisionVetoSeverity,
  NegativeDecisionCheckResult, NegativeDecisionEntry, ReinforcedDecayConfig, ScoredMemoryItem (POS: 跨 Agent
  共享记忆总线、并发连接池、背压守卫与方案否决账本的核心类型定义。)

[OUTPUT]
- Package facade re-exporting 12 public names: BackpressureStatus, ConcurrencyPoolConfig,
  DecisionVetoSeverity, MemoryBackpressureGuard, MultiAgentSharedMemoryBus, NegativeDecisionCheckResult,
  NegativeDecisionEntry, NegativeDecisionLedger, ReinforcedDecayConfig, ReinforcedDecayScorer,
  ScoredMemoryItem, SharedMemoryConcurrencyPool

[POS]
跨 Agent 共享记忆总线、并发连接池与方案否决账本模块。
"""

from myrm_agent_harness.toolkits.memory.shared_bus.bus import (
    MultiAgentSharedMemoryBus,
)
from myrm_agent_harness.toolkits.memory.shared_bus.concurrency_pool import (
    MemoryBackpressureGuard,
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
    DecisionVetoSeverity,
    NegativeDecisionCheckResult,
    NegativeDecisionEntry,
    ReinforcedDecayConfig,
    ScoredMemoryItem,
)

__all__ = [
    "BackpressureStatus",
    "ConcurrencyPoolConfig",
    "DecisionVetoSeverity",
    "MemoryBackpressureGuard",
    "MultiAgentSharedMemoryBus",
    "NegativeDecisionCheckResult",
    "NegativeDecisionEntry",
    "NegativeDecisionLedger",
    "ReinforcedDecayConfig",
    "ReinforcedDecayScorer",
    "ScoredMemoryItem",
    "SharedMemoryConcurrencyPool",
]
