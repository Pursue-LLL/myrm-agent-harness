"""Pluggable memory system for AI agents.

Protocol-first design: the framework defines only interfaces (Protocols)
and orchestration logic. Concrete storage backends are provided by the
application layer via dependency injection.

This facade re-exports only the names production code imports; every other
symbol is imported from the submodule that defines it.
"""

from myrm_agent_harness.toolkits.memory._internal.embedding_cache import EmbeddingCache
from myrm_agent_harness.toolkits.memory._internal.memory_scanner import get_scan_metrics
from myrm_agent_harness.toolkits.memory._internal.storage import (
    InvalidPendingEditError,
    MemoryError,
    MemoryNotFoundError,
    PendingTargetChangedError,
)
from myrm_agent_harness.toolkits.memory.budget_packing import (
    BilledTokenBudget,
    BudgetRecallPackingOrchestrator,
    DroppedCandidateItem,
    MarginalValueMetrics,
    PackedCandidateItem,
    PackedRecallResult,
    RecallCandidate,
    TokenAccountingReport,
    estimate_tokens,
)
from myrm_agent_harness.toolkits.memory.chunking import (
    ChunkingConfig,
    ChunkSourceHydrator,
    IncrementalDiffReport,
    IncrementalIndexingPipeline,
    MarkdownChunk,
    MarkdownSlidingWindowChunker,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.domain_types import MemoryDomain, infer_domain_and_category
from myrm_agent_harness.toolkits.memory.hermes_bridge import import_hermes_bundle
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.mem_cube import (
    CubeMemoryRecord,
    CubeQueryRequest,
    CubeQueryResult,
    CubeScopeType,
    CubeWriteRequest,
    CubeWriteResult,
    MemoryCube,
    MemoryCubeOrchestrator,
    MountPolicy,
)
from myrm_agent_harness.toolkits.memory.metrics import get_search_metrics
from myrm_agent_harness.toolkits.memory.observability import (
    MemoryInfluenceRef,
    MemoryOperationEvent,
    MemoryOperationKind,
    MemoryOperationStatus,
    MemoryRecallRoiGrade,
    MemorySpaceKind,
)
from myrm_agent_harness.toolkits.memory.onboarding import (
    FirstEncounterReport,
    MultiSourceOnboardingSampler,
    OnboardingInsightDistiller,
    OnboardingSampleOptions,
    OnboardingSourceRegistry,
)
from myrm_agent_harness.toolkits.memory.private_notebook import ModelPrivateNotebookManager
from myrm_agent_harness.toolkits.memory.reliability import (
    MemoryArchiveManifest,
    MemoryArchivePayload,
    MemoryArchiveRestoreDryRunResult,
    MemoryArchiveRestoreItemStatus,
    MemoryArchiveRestoreMutationRef,
    MemoryArchiveRestorePlan,
    MemoryArchiveRestoreResult,
    MemoryArchiveRestoreRollbackPreview,
    MemoryArchiveRestoreRollbackResult,
    MemoryArchiveRestoreSectionPlan,
    MemoryArchiveRestoreSecurityFinding,
    MemoryArchiveRestoreSecurityVerdict,
    MemoryArchiveRestoreStatus,
    MemoryArchiveSection,
    MemoryArchiveSectionName,
    MemoryImportDryRunResult,
    MemoryImportDryRunSummary,
    MemoryImportMappingItem,
    MemoryImportPlan,
    MemoryImportPlanItem,
    MemoryImportSource,
    MemoryRecallBenchmarkCase,
    MemoryRecallBenchmarkResult,
    MemoryReliabilityStatus,
    MemoryRepairExecutionResult,
    summarize_recall_benchmark,
)
from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager
from myrm_agent_harness.toolkits.memory.strategies import (
    DynamicPreferenceFitter,
    DynamicPreferenceVector,
    PreferenceDimension,
)
from myrm_agent_harness.toolkits.memory.tool_guidance import ToolGuidanceItem, synthesize_tool_guidance
from myrm_agent_harness.toolkits.memory.two_layer_dialectic import (
    BaseContextPayload,
    DialecticConflictCandidate,
    DialecticReconciliationConfig,
    DialecticReconciliationResult,
    MultiPassDialecticReconciler,
    TwoLayerContextInjectionResult,
    TwoLayerContextInjector,
)
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemoryStatus,
    MemoryType,
    ProceduralMemory,
    ProfileAttributeSnapshot,
    SemanticMemory,
)

__all__ = [
    "ModelPrivateNotebookManager",
    "DynamicPreferenceFitter",
    "DynamicPreferenceVector",
    "EmbeddingCache",
    "EpisodicMemory",
    "import_hermes_bundle",
    "infer_domain_and_category",
    "MemoryDomain",
    "MemoryArchiveManifest",
    "MemoryArchivePayload",
    "MemoryArchiveRestoreDryRunResult",
    "MemoryArchiveRestoreItemStatus",
    "MemoryArchiveRestoreMutationRef",
    "MemoryArchiveRestorePlan",
    "MemoryArchiveRestoreResult",
    "MemoryArchiveRestoreRollbackPreview",
    "MemoryArchiveRestoreRollbackResult",
    "MemoryArchiveRestoreSectionPlan",
    "MemoryArchiveRestoreSecurityFinding",
    "MemoryArchiveRestoreSecurityVerdict",
    "MemoryArchiveRestoreStatus",
    "MemoryArchiveSection",
    "MemoryArchiveSectionName",
    "MemoryConfig",
    "InvalidPendingEditError",
    "PendingTargetChangedError",
    "MemoryError",
    "MemoryImportDryRunResult",
    "MemoryImportDryRunSummary",
    "MemoryImportMappingItem",
    "MemoryImportPlan",
    "MemoryImportPlanItem",
    "MemoryImportSource",
    "MemoryInfluenceRef",
    "MemoryManager",
    "MemoryNotFoundError",
    "MemoryOperationEvent",
    "MemoryOperationKind",
    "MemoryOperationStatus",
    "MemoryRecallBenchmarkCase",
    "MemoryRecallBenchmarkResult",
    "MemoryRecallRoiGrade",
    "MemoryReliabilityStatus",
    "MemoryRepairExecutionResult",
    "MemorySpaceKind",
    "MemoryStatus",
    "MemoryType",
    "ProceduralMemory",
    "PreferenceDimension",
    "ProfileAttributeSnapshot",
    "SemanticMemory",
    "ToolGuidanceItem",
    "synthesize_tool_guidance",
    "create_local_memory_manager",
    "get_scan_metrics",
    "get_search_metrics",
    "summarize_recall_benchmark",
    "FirstEncounterReport",
    "MultiSourceOnboardingSampler",
    "OnboardingInsightDistiller",
    "OnboardingSampleOptions",
    "OnboardingSourceRegistry",
    "BaseContextPayload",
    "DialecticConflictCandidate",
    "DialecticReconciliationConfig",
    "DialecticReconciliationResult",
    "MultiPassDialecticReconciler",
    "TwoLayerContextInjectionResult",
    "TwoLayerContextInjector",
    "BilledTokenBudget",
    "BudgetRecallPackingOrchestrator",
    "DroppedCandidateItem",
    "MarginalValueMetrics",
    "PackedCandidateItem",
    "PackedRecallResult",
    "RecallCandidate",
    "TokenAccountingReport",
    "estimate_tokens",
    "CubeMemoryRecord",
    "CubeQueryRequest",
    "CubeQueryResult",
    "CubeScopeType",
    "CubeWriteRequest",
    "CubeWriteResult",
    "MemoryCube",
    "MemoryCubeOrchestrator",
    "MountPolicy",
    "ChunkSourceHydrator",
    "ChunkingConfig",
    "IncrementalDiffReport",
    "IncrementalIndexingPipeline",
    "MarkdownChunk",
    "MarkdownSlidingWindowChunker",
]
