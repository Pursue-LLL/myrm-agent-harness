"""Smart idle cache-preserving auto-compactor package.

[INPUT]
- agent.context_management.smart_idle_compactor.idle_compactor_types::CacheWindowStatus,
  CompactedCheckpointArchive, IdleCompactionAction, IdleCompactionEvaluation, IdleCompactorConfig,
  OpportunisticCompactionResult, ZeroWaitWakeupEvent (POS: Data contracts and type definitions for smart idle
  cache auto-compaction.)
- agent.context_management.smart_idle_compactor.idle_eligibility_evaluator::IdleEligibilityEvaluator (POS:
  Idle eligibility evaluator for opportunistic prompt cache pre-compaction.)
- agent.context_management.smart_idle_compactor.opportunistic_compactor_engine::OpportunisticCompactorEngine
  (POS: Opportunistic Compactor Engine executing silent background pre-compaction.)
-
  agent.context_management.smart_idle_compactor.smart_idle_compactor_suite::SmartIdleCachePreservingAutoCompactorSuite
  (POS: Smart Idle Cache-Preserving Auto-Compactor Suite.)

[OUTPUT]
- Re-exports: CacheWindowStatus, CompactedCheckpointArchive, IdleCompactionAction, IdleCompactionEvaluation,
  IdleCompactorConfig, IdleEligibilityEvaluator, OpportunisticCompactorEngine, OpportunisticCompactionResult,
  SmartIdleCachePreservingAutoCompactorSuite, ZeroWaitWakeupEvent

[POS]
Smart idle cache-preserving auto-compactor package.
"""

from .idle_compactor_types import (
    CacheWindowStatus,
    CompactedCheckpointArchive,
    IdleCompactionAction,
    IdleCompactionEvaluation,
    IdleCompactorConfig,
    OpportunisticCompactionResult,
    ZeroWaitWakeupEvent,
)
from .idle_eligibility_evaluator import IdleEligibilityEvaluator
from .opportunistic_compactor_engine import OpportunisticCompactorEngine
from .smart_idle_compactor_suite import SmartIdleCachePreservingAutoCompactorSuite

__all__ = [
    "CacheWindowStatus",
    "CompactedCheckpointArchive",
    "IdleCompactionAction",
    "IdleCompactionEvaluation",
    "IdleCompactorConfig",
    "IdleEligibilityEvaluator",
    "OpportunisticCompactorEngine",
    "OpportunisticCompactionResult",
    "SmartIdleCachePreservingAutoCompactorSuite",
    "ZeroWaitWakeupEvent",
]
