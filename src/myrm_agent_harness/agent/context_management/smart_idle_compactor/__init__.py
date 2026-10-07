"""Smart idle cache-preserving auto-compactor package."""

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
