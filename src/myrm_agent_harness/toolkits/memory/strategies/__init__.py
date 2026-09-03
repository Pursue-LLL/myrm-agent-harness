"""Optional memory strategies: forgetting, extraction, deduplication, consolidation."""

from myrm_agent_harness.toolkits.memory.strategies.blind_spot import (
    BlindSpotCandidate,
    BlindSpotKnowledgePatch,
    BlindSpotReport,
    PatchTargetType,
    extract_blind_spot_patches,
)
from myrm_agent_harness.toolkits.memory.strategies.consolidation import (
    ConsolidationStats,
    run_consolidation,
    should_consolidate,
)
from myrm_agent_harness.toolkits.memory.strategies.deduplicator import (
    DeduplicationDecision,
    HashCacheMetrics,
    SmartDeduplicator,
)
from myrm_agent_harness.toolkits.memory.strategies.extractor import (
    ExtractedMemory,
    ExtractionConfig,
    ExtractionResult,
    MemoryExtractor,
    extract_memories_from_conversation,
)
from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
    ForgettingConfig,
    ForgettingResult,
    ForgettingStrategy,
    RetentionScore,
)
from myrm_agent_harness.toolkits.memory.strategies.implicit_feedback import (
    CorrectionAction,
    CorrectionProposal,
    ImplicitFeedbackResult,
    detect_implicit_feedback,
    plan_memory_corrections,
)

__all__ = [
    "BlindSpotCandidate",
    "BlindSpotKnowledgePatch",
    "BlindSpotReport",
    "ConsolidationStats",
    "CorrectionAction",
    "CorrectionProposal",
    "DeduplicationDecision",
    "ExtractedMemory",
    "ExtractionConfig",
    "ExtractionResult",
    "ForgettingConfig",
    "ForgettingResult",
    "ForgettingStrategy",
    "HashCacheMetrics",
    "ImplicitFeedbackResult",
    "MemoryExtractor",
    "PatchTargetType",
    "RetentionScore",
    "SmartDeduplicator",
    "detect_implicit_feedback",
    "extract_blind_spot_patches",
    "extract_memories_from_conversation",
    "plan_memory_corrections",
    "run_consolidation",
    "should_consolidate",
]
