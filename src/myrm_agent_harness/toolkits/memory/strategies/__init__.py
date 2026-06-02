"""Optional memory strategies: forgetting, extraction, deduplication, consolidation."""

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

__all__ = [
    "ConsolidationStats",
    "DeduplicationDecision",
    "ExtractedMemory",
    "ExtractionConfig",
    "ExtractionResult",
    "ForgettingConfig",
    "ForgettingResult",
    "ForgettingStrategy",
    "HashCacheMetrics",
    "MemoryExtractor",
    "RetentionScore",
    "SmartDeduplicator",
    "extract_memories_from_conversation",
    "run_consolidation",
    "should_consolidate",
]
