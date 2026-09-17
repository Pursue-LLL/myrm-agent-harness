"""Optional memory strategies: forgetting, extraction, deduplication, consolidation."""

from myrm_agent_harness.toolkits.memory.strategies.behavioral_measurement import (
    BehavioralMessage,
    BehavioralStatsOptions,
    RoutineMeasurement,
    compute_routine_measurement,
    generate_behavioral_profile_candidates,
    percentile,
)
from myrm_agent_harness.toolkits.memory.strategies.blind_spot import (
    BlindSpotCandidate,
    BlindSpotKnowledgePatch,
    BlindSpotReport,
    PatchTargetType,
    extract_blind_spot_patches,
)
from myrm_agent_harness.toolkits.memory.strategies.conflict_merger import (
    ConflictDetail,
    MergeAction,
    MergeRelation,
    MergeResult,
    classify_relation,
    merge_evidence_references,
    merge_memory_candidate,
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
from myrm_agent_harness.toolkits.memory.strategies.distillation_guards import (
    DistillationCandidate,
    DistillationGuardRejectionError,
    DistillationGuardResult,
    DistillationOrigin,
    DistillationRejectionCode,
    EvidenceReference,
    SelfIdentityState,
    assert_distillable,
    assert_has_evidence,
    check_distillable,
    filter_distillable_messages,
    filter_memories_with_evidence,
    is_valid_evidence_reference,
)
from myrm_agent_harness.toolkits.memory.strategies.dynamic_preference import (
    DynamicPreferenceFitter,
    DynamicPreferenceVector,
    FeedbackAction,
    PreferenceDimension,
)
from myrm_agent_harness.toolkits.memory.strategies.exact_fact import (
    ExactFactClassifier,
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
from myrm_agent_harness.toolkits.memory.strategies.gravity_decay import (
    GravityDecayConfig,
    GravityDecayScorer,
    compute_gravity_decay,
)
from myrm_agent_harness.toolkits.memory.strategies.implicit_feedback import (
    CorrectionAction,
    CorrectionProposal,
    ImplicitFeedbackResult,
    detect_implicit_feedback,
    plan_memory_corrections,
)
from myrm_agent_harness.toolkits.memory.strategies.incremental_transcript import (
    IncrementalTranscriptParser,
    TranscriptIncrementalChunk,
    TranscriptTurn,
)
from myrm_agent_harness.toolkits.memory.strategies.merger import (
    ConfidenceEvolutionEngine,
    ConflictItem,
    DeterministicThreeStateMerger,
    MergeDecision,
    MergeState,
)
from myrm_agent_harness.toolkits.memory.strategies.sparse_mutation import (
    MinimalOverwritePipeline,
    SparseSemanticMaskGenerator,
    apply_sparse_mutation,
)
from myrm_agent_harness.toolkits.memory.strategies.sparse_parser import (
    SemanticSlotParser,
)
from myrm_agent_harness.toolkits.memory.strategies.sparse_types import (
    SemanticSlot,
    SlotAction,
    SlotKind,
    SparseMaskItem,
    SparseMutationResult,
)

__all__ = [
    "BehavioralMessage",
    "BehavioralStatsOptions",
    "BlindSpotCandidate",
    "BlindSpotKnowledgePatch",
    "BlindSpotReport",
    "ConflictDetail",
    "ConsolidationStats",
    "CorrectionAction",
    "CorrectionProposal",
    "DeduplicationDecision",
    "DistillationCandidate",
    "DistillationGuardRejectionError",
    "DistillationGuardResult",
    "DistillationOrigin",
    "DistillationRejectionCode",
    "EvidenceReference",
    "ExactFactClassifier",
    "ExtractedMemory",
    "ExtractionConfig",
    "ExtractionResult",
    "ForgettingConfig",
    "ForgettingResult",
    "ForgettingStrategy",
    "HashCacheMetrics",
    "ImplicitFeedbackResult",
    "IncrementalTranscriptParser",
    "MemoryExtractor",
    "MergeAction",
    "MergeRelation",
    "MergeResult",
    "PatchTargetType",
    "RetentionScore",
    "RoutineMeasurement",
    "SelfIdentityState",
    "SmartDeduplicator",
    "TranscriptIncrementalChunk",
    "TranscriptTurn",
    "assert_distillable",
    "assert_has_evidence",
    "check_distillable",
    "classify_relation",
    "compute_routine_measurement",
    "detect_implicit_feedback",
    "extract_blind_spot_patches",
    "extract_memories_from_conversation",
    "filter_distillable_messages",
    "filter_memories_with_evidence",
    "generate_behavioral_profile_candidates",
    "is_valid_evidence_reference",
    "merge_evidence_references",
    "merge_memory_candidate",
    "percentile",
    "plan_memory_corrections",
    "run_consolidation",
    "should_consolidate",
    "ConfidenceEvolutionEngine",
    "ConflictItem",
    "DeterministicThreeStateMerger",
    "DynamicPreferenceFitter",
    "DynamicPreferenceVector",
    "FeedbackAction",
    "GravityDecayConfig",
    "GravityDecayScorer",
    "MergeDecision",
    "MergeState",
    "MinimalOverwritePipeline",
    "PreferenceDimension",
    "SemanticSlot",
    "SemanticSlotParser",
    "SlotAction",
    "SlotKind",
    "SparseMaskItem",
    "SparseMutationResult",
    "SparseSemanticMaskGenerator",
    "apply_sparse_mutation",
    "compute_gravity_decay",
]
