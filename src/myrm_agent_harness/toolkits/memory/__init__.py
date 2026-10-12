"""Pluggable memory system for AI agents.

Protocol-first design: the framework defines only interfaces (Protocols)
and orchestration logic. Concrete storage backends are provided by the
application layer via dependency injection.

Every name is re-exported with the explicit ``X as X`` form (PEP 484) instead of a
duplicated ``__all__`` list, so the import block is the single source of the public API.
"""
# isort would split every ``X as X`` re-export into its own import statement.
# ruff: noqa: I001

from myrm_agent_harness.toolkits.memory._internal.embedding_cache import (
    EmbeddingCache as EmbeddingCache,
)
from myrm_agent_harness.toolkits.memory._internal.memory_scanner import (
    ScanMetricsSnapshot as ScanMetricsSnapshot,
    get_scan_metrics as get_scan_metrics,
)
from myrm_agent_harness.toolkits.memory._internal.storage import (
    MemoryError as MemoryError,
    MemoryNotFoundError as MemoryNotFoundError,
    MemoryProtectedError as MemoryProtectedError,
)
from myrm_agent_harness.toolkits.memory.budget_curator import (
    AtomicBatchResult as AtomicBatchResult,
    AtomicOperationsCurator as AtomicOperationsCurator,
    ManagedMemoryItem as ManagedMemoryItem,
    MemoryBatchOperation as MemoryBatchOperation,
    MemoryBudgetMeter as MemoryBudgetMeter,
    MemoryBudgetSpec as MemoryBudgetSpec,
    MemoryBudgetStatus as MemoryBudgetStatus,
    MemoryOperationType as MemoryOperationType,
    ScrollAnchorRequest as ScrollAnchorRequest,
    ScrollAnchorResult as ScrollAnchorResult,
    ScrollMessageItem as ScrollMessageItem,
    SessionScrollNavigator as SessionScrollNavigator,
)
from myrm_agent_harness.toolkits.memory.cards import (
    AMemCard as AMemCard,
    AMemZettelkastenNetwork as AMemZettelkastenNetwork,
)
from myrm_agent_harness.toolkits.memory.client_partition import (
    ClientPartitionConfig as ClientPartitionConfig,
    ClientWorkspaceDescriptor as ClientWorkspaceDescriptor,
    ClientWorkspaceResolver as ClientWorkspaceResolver,
    CrossClientLeakGuard as CrossClientLeakGuard,
    CrossClientLeakViolation as CrossClientLeakViolation,
    PartitionInspectionReport as PartitionInspectionReport,
)
from myrm_agent_harness.toolkits.memory.config import (
    AgentMemoryPolicy as AgentMemoryPolicy,
    ConsolidationConfig as ConsolidationConfig,
    MemoryConfig as MemoryConfig,
    MemoryScopeLevel as MemoryScopeLevel,
    MemoryWritePolicy as MemoryWritePolicy,
    RecallMode as RecallMode,
    RetrievalConfig as RetrievalConfig,
)
from myrm_agent_harness.toolkits.memory.consolidation import (
    ConsolidationSubtask as ConsolidationSubtask,
    ConsolidationTrap as ConsolidationTrap,
    HyperConsolidator as HyperConsolidator,
    WorkingMemorySnapshot as WorkingMemorySnapshot,
    create_consolidation_cleanup_task as create_consolidation_cleanup_task,
)
from myrm_agent_harness.toolkits.memory.conversation_search import (
    CONVERSATION_SEARCH_TOOL_NAME as CONVERSATION_SEARCH_TOOL_NAME,
    ContextHighlight as ContextHighlight,
    ConversationExactSearchMatcher as ConversationExactSearchMatcher,
    ConversationSearchHit as ConversationSearchHit,
    ConversationSearchRequest as ConversationSearchRequest,
    ConversationSearchResponse as ConversationSearchResponse,
    MemoryConversationSearchProvider as MemoryConversationSearchProvider,
    create_conversation_search_tool as create_conversation_search_tool,
)
from myrm_agent_harness.toolkits.memory.cube import (
    LifecycleTier as LifecycleTier,
    MemCubeEnvelope as MemCubeEnvelope,
    MemCubeHeader as MemCubeHeader,
    StoragePolicy as StoragePolicy,
    infer_tier_and_policy as infer_tier_and_policy,
    unwrap_envelope as unwrap_envelope,
    wrap_into_envelope as wrap_into_envelope,
)
from myrm_agent_harness.toolkits.memory.dialectic import (
    DialecticCadenceConfig as DialecticCadenceConfig,
    DialecticCadenceGovernor as DialecticCadenceGovernor,
    DialecticEphemeralMind as DialecticEphemeralMind,
    DialecticReasoningEngine as DialecticReasoningEngine,
    DialecticReasoningResult as DialecticReasoningResult,
    SessionHeatState as SessionHeatState,
    UserBaseProfile as UserBaseProfile,
)
from myrm_agent_harness.toolkits.memory.domain_types import (
    DomainCategory as DomainCategory,
    MemoryDomain as MemoryDomain,
    infer_domain_and_category as infer_domain_and_category,
)
from myrm_agent_harness.toolkits.memory.dreaming import (
    DreamDiaryEntry as DreamDiaryEntry,
    DreamDiaryStatus as DreamDiaryStatus,
    DreamingTriggerReason as DreamingTriggerReason,
    DreamSessionFragment as DreamSessionFragment,
    GroundedDreamingEngine as GroundedDreamingEngine,
    GroundedDreamingScheduler as GroundedDreamingScheduler,
    MemoryProvenanceAnchor as MemoryProvenanceAnchor,
    ProjectScopeIsolationGuard as ProjectScopeIsolationGuard,
    SensitiveProvenanceGuard as SensitiveProvenanceGuard,
    SurgicalSessionMemoryUnlearner as SurgicalSessionMemoryUnlearner,
    SurgicalUnlearnReport as SurgicalUnlearnReport,
)
from myrm_agent_harness.toolkits.memory.external_bridge import (
    END_MARKER as END_MARKER,
    START_MARKER as START_MARKER,
    BaseExternalAgentTarget as BaseExternalAgentTarget,
    ClaudeCodeBridgeTarget as ClaudeCodeBridgeTarget,
    CodexBridgeTarget as CodexBridgeTarget,
    CursorBridgeTarget as CursorBridgeTarget,
    ExternalAgentSkillWriter as ExternalAgentSkillWriter,
    ExternalAgentTargetRegistry as ExternalAgentTargetRegistry,
    ExternalAgentType as ExternalAgentType,
    HermesBridgeTarget as HermesBridgeTarget,
    MemoryConflictReport as MemoryConflictReport,
    MemoryPluginConflictDetector as MemoryPluginConflictDetector,
    OpenClawBridgeTarget as OpenClawBridgeTarget,
    SkillBridgeAction as SkillBridgeAction,
    SkillInstallConfig as SkillInstallConfig,
    SkillInstallResult as SkillInstallResult,
    SkillUninstallResult as SkillUninstallResult,
)
from myrm_agent_harness.toolkits.memory.external_providers import (
    BenchmarkReport as BenchmarkReport,
    DerivedObservationRecord as DerivedObservationRecord,
    EvidenceRecord as EvidenceRecord,
    ExternalMemoryBenchmarkSuite as ExternalMemoryBenchmarkSuite,
    ExternalMemoryProviderProtocol as ExternalMemoryProviderProtocol,
    MemoryLifecycleStage as MemoryLifecycleStage,
    MemoryScopeContext as MemoryScopeContext,
    MemoryScopeType as MemoryScopeType,
    PrefetchResult as PrefetchResult,
    SingleActiveProviderScheduler as SingleActiveProviderScheduler,
    SupersedesLineageManager as SupersedesLineageManager,
    SupersedesRecord as SupersedesRecord,
)
from myrm_agent_harness.toolkits.memory.governance import (
    AssembledMemoryContext as AssembledMemoryContext,
    ConflictResolver as ConflictResolver,
    DynamicContextAssembler as DynamicContextAssembler,
    DynamicFactItem as DynamicFactItem,
    EntityGraphBridge as EntityGraphBridge,
    EventTimelineItem as EventTimelineItem,
    FactReconciliationEngine as FactReconciliationEngine,
    FactStatus as FactStatus,
    ProfileSlots as ProfileSlots,
    ReconciliationAction as ReconciliationAction,
    ReconciliationDecision as ReconciliationDecision,
)
from myrm_agent_harness.toolkits.memory.health import (
    HealthScore as HealthScore,
    MaintenanceReport as MaintenanceReport,
    MemorySnapshot as MemorySnapshot,
    NeglectedMemory as NeglectedMemory,
)
from myrm_agent_harness.toolkits.memory.hermes_bridge import (
    import_hermes_bundle as import_hermes_bundle,
    parse_hermes_json as parse_hermes_json,
    parse_hermes_markdown as parse_hermes_markdown,
)
from myrm_agent_harness.toolkits.memory.ltra import (
    AudioFactDistillationWorker as AudioFactDistillationWorker,
    AudioTimestampAnchor as AudioTimestampAnchor,
    CognitiveFactQuadruple as CognitiveFactQuadruple,
    DiarizedTranscriptSegment as DiarizedTranscriptSegment,
    FollowupTaskDraft as FollowupTaskDraft,
    FollowupTaskDraftBuilder as FollowupTaskDraftBuilder,
    SensitiveAudioFactGuard as SensitiveAudioFactGuard,
    SpeakerIdentityResolver as SpeakerIdentityResolver,
)
from myrm_agent_harness.toolkits.memory.manager import (
    MemoryManager as MemoryManager,
)
from myrm_agent_harness.toolkits.memory.metrics import (
    SearchMetrics as SearchMetrics,
    SearchSnapshot as SearchSnapshot,
    get_search_metrics as get_search_metrics,
)
from myrm_agent_harness.toolkits.memory.mirror import (
    ColdMemoryRecord as ColdMemoryRecord,
    HotColdMirrorEngine as HotColdMirrorEngine,
)
from myrm_agent_harness.toolkits.memory.observability import (
    MemoryInfluenceRef as MemoryInfluenceRef,
    MemoryOperationEvent as MemoryOperationEvent,
    MemoryOperationKind as MemoryOperationKind,
    MemoryOperationSink as MemoryOperationSink,
    MemoryOperationStatus as MemoryOperationStatus,
    MemoryRecallRoiGrade as MemoryRecallRoiGrade,
    MemoryRetrievalTrace as MemoryRetrievalTrace,
    MemorySpaceBinding as MemorySpaceBinding,
    MemorySpaceKind as MemorySpaceKind,
    MemoryTraceStep as MemoryTraceStep,
    ScalarValue as ScalarValue,
)
from myrm_agent_harness.toolkits.memory.onboarding import (
    FirstEncounterReport as FirstEncounterReport,
    InsightExtractedFact as InsightExtractedFact,
    LocalSecretRedactor as LocalSecretRedactor,
    MultiSourceOnboardingSampler as MultiSourceOnboardingSampler,
    OnboardingConversationWindow as OnboardingConversationWindow,
    OnboardingInsightDistiller as OnboardingInsightDistiller,
    OnboardingSampleOptions as OnboardingSampleOptions,
    OnboardingSourceRegistry as OnboardingSourceRegistry,
    SampledTurnMessage as SampledTurnMessage,
    ShannonEntropyInspector as ShannonEntropyInspector,
)
from myrm_agent_harness.toolkits.memory.prompt_cache_guard import (
    AtomicReplacePayload as AtomicReplacePayload,
    CapacityLimitConfig as CapacityLimitConfig,
    CapacityOverflowError as CapacityOverflowError,
    FrozenMemorySnapshot as FrozenMemorySnapshot,
    FrozenMemorySnapshotProvider as FrozenMemorySnapshotProvider,
    ReadFreeMemoryToolSuite as ReadFreeMemoryToolSuite,
    SecurityThreatBlockedError as SecurityThreatBlockedError,
    ZeroWidthAndCredentialLeakScanner as ZeroWidthAndCredentialLeakScanner,
)
from myrm_agent_harness.toolkits.memory.protocols import (
    ConversationSearchProtocol as ConversationSearchProtocol,
    EmbeddingCacheProtocol as EmbeddingCacheProtocol,
    EmbeddingProtocol as EmbeddingProtocol,
    GraphStoreProtocol as GraphStoreProtocol,
    RelationalStoreProtocol as RelationalStoreProtocol,
    VectorStoreProtocol as VectorStoreProtocol,
)
from myrm_agent_harness.toolkits.memory.provenance_batch import (
    BatchLearnItem as BatchLearnItem,
    BatchLearnNamespaceIsolator as BatchLearnNamespaceIsolator,
    BatchLearnResult as BatchLearnResult,
    ExtractionProvenanceLink as ExtractionProvenanceLink,
    NamespacedMemoryRef as NamespacedMemoryRef,
    SkillProvenanceLinker as SkillProvenanceLinker,
    ToolExecutionTrace as ToolExecutionTrace,
)
from myrm_agent_harness.toolkits.memory.reembedding import (
    AdaptiveBatcher as AdaptiveBatcher,
    CheckpointState as CheckpointState,
    DualVersionCollectionState as DualVersionCollectionState,
    ReembeddingBatch as ReembeddingBatch,
    ReembeddingCheckpointManager as ReembeddingCheckpointManager,
    ReembeddingJobConfig as ReembeddingJobConfig,
    ReembeddingProgress as ReembeddingProgress,
    ReembeddingRecord as ReembeddingRecord,
    ReembeddingStatus as ReembeddingStatus,
    ZeroDowntimeReembeddingEngine as ZeroDowntimeReembeddingEngine,
)
from myrm_agent_harness.toolkits.memory.reliability import (
    MemoryArchiveDryRunResult as MemoryArchiveDryRunResult,
    MemoryArchiveManifest as MemoryArchiveManifest,
    MemoryArchivePayload as MemoryArchivePayload,
    MemoryArchiveRestoreDryRunResult as MemoryArchiveRestoreDryRunResult,
    MemoryArchiveRestoreItemStatus as MemoryArchiveRestoreItemStatus,
    MemoryArchiveRestoreMode as MemoryArchiveRestoreMode,
    MemoryArchiveRestoreMutationRef as MemoryArchiveRestoreMutationRef,
    MemoryArchiveRestorePlan as MemoryArchiveRestorePlan,
    MemoryArchiveRestoreResult as MemoryArchiveRestoreResult,
    MemoryArchiveRestoreRollbackPreview as MemoryArchiveRestoreRollbackPreview,
    MemoryArchiveRestoreRollbackResult as MemoryArchiveRestoreRollbackResult,
    MemoryArchiveRestoreSectionPlan as MemoryArchiveRestoreSectionPlan,
    MemoryArchiveRestoreSecurityFinding as MemoryArchiveRestoreSecurityFinding,
    MemoryArchiveRestoreSecurityVerdict as MemoryArchiveRestoreSecurityVerdict,
    MemoryArchiveRestoreStatus as MemoryArchiveRestoreStatus,
    MemoryArchiveSection as MemoryArchiveSection,
    MemoryArchiveSectionName as MemoryArchiveSectionName,
    MemoryArchiveSectionStatus as MemoryArchiveSectionStatus,
    MemoryImportDryRunResult as MemoryImportDryRunResult,
    MemoryImportDryRunSummary as MemoryImportDryRunSummary,
    MemoryImportMappingItem as MemoryImportMappingItem,
    MemoryImportMappingStatus as MemoryImportMappingStatus,
    MemoryImportPlan as MemoryImportPlan,
    MemoryImportPlanItem as MemoryImportPlanItem,
    MemoryImportSource as MemoryImportSource,
    MemoryRecallBenchmarkCase as MemoryRecallBenchmarkCase,
    MemoryRecallBenchmarkResult as MemoryRecallBenchmarkResult,
    MemoryRecallBenchmarkSummary as MemoryRecallBenchmarkSummary,
    MemoryReliabilityCategory as MemoryReliabilityCategory,
    MemoryReliabilityProbeResult as MemoryReliabilityProbeResult,
    MemoryReliabilityStatus as MemoryReliabilityStatus,
    MemoryRepairExecutionResult as MemoryRepairExecutionResult,
    MemoryRepairExecutionStatus as MemoryRepairExecutionStatus,
    MemoryRepairPlan as MemoryRepairPlan,
    MemoryRepairRiskLevel as MemoryRepairRiskLevel,
    summarize_recall_benchmark as summarize_recall_benchmark,
)
from myrm_agent_harness.toolkits.memory.retriever import (
    MemoryRetriever as MemoryRetriever,
)
from myrm_agent_harness.toolkits.memory.ripplemem import (
    ActiveRecallController as ActiveRecallController,
    DualEdgeSparseGraphStore as DualEdgeSparseGraphStore,
    NormalizedEventExtractor as NormalizedEventExtractor,
    NormalizedEventUnit as NormalizedEventUnit,
    RippleRecallResult as RippleRecallResult,
    RippleSpreadBudget as RippleSpreadBudget,
)
from myrm_agent_harness.toolkits.memory.scheduler import (
    MultiTierMemoryScheduler as MultiTierMemoryScheduler,
)
from myrm_agent_harness.toolkits.memory.session import (
    MemorySession as MemorySession,
)
from myrm_agent_harness.toolkits.memory.setup import (
    create_local_memory_manager as create_local_memory_manager,
    setup_local_file_memory_sync as setup_local_file_memory_sync,
)
from myrm_agent_harness.toolkits.memory.shared_bus import (
    BackpressureStatus as BackpressureStatus,
    ConcurrencyPoolConfig as ConcurrencyPoolConfig,
    DecisionVetoSeverity as DecisionVetoSeverity,
    MemoryBackpressureGuard as MemoryBackpressureGuard,
    MultiAgentSharedMemoryBus as MultiAgentSharedMemoryBus,
    NegativeDecisionCheckResult as NegativeDecisionCheckResult,
    NegativeDecisionEntry as NegativeDecisionEntry,
    NegativeDecisionLedger as NegativeDecisionLedger,
    ReinforcedDecayConfig as ReinforcedDecayConfig,
    ReinforcedDecayScorer as ReinforcedDecayScorer,
    ScoredMemoryItem as ScoredMemoryItem,
    SharedMemoryConcurrencyPool as SharedMemoryConcurrencyPool,
)
from myrm_agent_harness.toolkits.memory.signals import (
    SignalCalculator as SignalCalculator,
)
from myrm_agent_harness.toolkits.memory.social_curator import (
    HighSignalBriefing as HighSignalBriefing,
    HighSignalSocialFeedCurator as HighSignalSocialFeedCurator,
    InformationGainScorer as InformationGainScorer,
    RawSocialPost as RawSocialPost,
    ScoredSocialInsight as ScoredSocialInsight,
    SocialInsightCategory as SocialInsightCategory,
    UserAffinityProfile as UserAffinityProfile,
    UserAffinityProfileBuilder as UserAffinityProfileBuilder,
)
from myrm_agent_harness.toolkits.memory.strategies import (
    DynamicPreferenceFitter as DynamicPreferenceFitter,
    DynamicPreferenceVector as DynamicPreferenceVector,
    ExtractedMemory as ExtractedMemory,
    ExtractionConfig as ExtractionConfig,
    ExtractionResult as ExtractionResult,
    FeedbackAction as FeedbackAction,
    ForgettingConfig as ForgettingConfig,
    ForgettingResult as ForgettingResult,
    ForgettingStrategy as ForgettingStrategy,
    GravityDecayConfig as GravityDecayConfig,
    GravityDecayScorer as GravityDecayScorer,
    MemoryExtractor as MemoryExtractor,
    PreferenceDimension as PreferenceDimension,
    RetentionScore as RetentionScore,
    compute_gravity_decay as compute_gravity_decay,
    extract_memories_from_conversation as extract_memories_from_conversation,
)
from myrm_agent_harness.toolkits.memory.strategies.pitfall_memory import (
    create_pitfall_memory as create_pitfall_memory,
)
from myrm_agent_harness.toolkits.memory.tool_capture import (
    ToolMemoryCaptureHook as ToolMemoryCaptureHook,
)
from myrm_agent_harness.toolkits.memory.tool_guidance import (
    ToolGuidanceItem as ToolGuidanceItem,
    ToolGuidanceSummary as ToolGuidanceSummary,
    filter_guidance_items as filter_guidance_items,
    synthesize_tool_guidance as synthesize_tool_guidance,
)
from myrm_agent_harness.toolkits.memory.types import (
    AnyMemory as AnyMemory,
    BaseMemory as BaseMemory,
    EpisodicMemory as EpisodicMemory,
    EpisodicRelation as EpisodicRelation,
    MemoryMutationRef as MemoryMutationRef,
    MemoryMutationResult as MemoryMutationResult,
    MemorySearchResult as MemorySearchResult,
    MemoryStatus as MemoryStatus,
    MemoryType as MemoryType,
    PendingRecord as PendingRecord,
    PendingResolutionAction as PendingResolutionAction,
    ProceduralMemory as ProceduralMemory,
    ProfileAttributeSnapshot as ProfileAttributeSnapshot,
    ProfileEntry as ProfileEntry,
    RuleSource as RuleSource,
    SemanticMemory as SemanticMemory,
    TaskDigestMemory as TaskDigestMemory,
    ToolRulePriority as ToolRulePriority,
)
from myrm_agent_harness.toolkits.memory.working_tree import (
    BoundedSummary as BoundedSummary,
    ConflictType as ConflictType,
    ConflictVerdict as ConflictVerdict,
    EvidenceNode as EvidenceNode,
    EvidenceNodeStatus as EvidenceNodeStatus,
    EvidenceSource as EvidenceSource,
    EvidenceTree as EvidenceTree,
    FastContradictionDetector as FastContradictionDetector,
    RevisionRecord as RevisionRecord,
    TreeRepairEngine as TreeRepairEngine,
    TreeRepairResult as TreeRepairResult,
)
from myrm_agent_harness.toolkits.memory.world_model import (
    L3WorldModelEngine as L3WorldModelEngine,
    L3WorldModelField as L3WorldModelField,
    L3WorldModelRecord as L3WorldModelRecord,
    MacroContextPayload as MacroContextPayload,
    ProjectEnvironmentSnapshot as ProjectEnvironmentSnapshot,
    RuntimeEnvironmentInfo as RuntimeEnvironmentInfo,
)
from myrm_agent_harness.toolkits.memory.zero_hallucination import (
    MemoryFactItem as MemoryFactItem,
    MemoryRetrievalState as MemoryRetrievalState,
    MemoryStateAssertionEvaluator as MemoryStateAssertionEvaluator,
    RetrievalErrorSeverity as RetrievalErrorSeverity,
    ZeroHallucinationPromptGuard as ZeroHallucinationPromptGuard,
    ZeroHallucinationRetrievalResult as ZeroHallucinationRetrievalResult,
)
