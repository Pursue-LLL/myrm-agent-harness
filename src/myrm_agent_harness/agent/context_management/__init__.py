"""Context management module.

提供上下文过滤、压缩、摘要等功能，用于管理 Agent 的上下文窗口。

核心组件：
1. schemas: 紧凑格式和摘要模式定义
2. filter: 大型工具结果过滤（任务感知的混合过滤策略）
   - 结构化数据（JSON/XML/代码）：使用 StructuralFilter
   - 非结构化数据（HTML/Markdown/纯文本）：使用 SemanticFilter + LLM
3. compactor: 统一压缩逻辑（合并 Context Editing + Compact）
4. summarizer: 上下文摘要逻辑（最后手段）
5. filters: 过滤器子模块
   - StructuralFilter: 结构化数据过滤器
   - SemanticFilter: 语义过滤器（使用 LLM）
6. pipeline: Pipeline 架构的上下文处理
   - ContextPipeline: 管道引擎
   - 统一 builder: build_default_processors / create_default_pipeline
   - 处理器: ThinkingBlockCleaner, FilterProcessor, CompressProcessor,
     SessionNotesProcessor, SummarizeProcessor, ExplicitCacheProcessor

设计理念（来自 Manus + Anthropic）：
- 过滤 (Filtering) 是立即的：大结果截断 + 智能预览
- 压缩 (Compression)：三级策略（Dedup/Truncate/Remove）；通过 ContextCompressOffloadCallback 落盘后再紧凑化（Manus "有损但可追溯"原则）
  - 工具特定模板（保留标识符和元信息）
  - 最小清理保护（避免小清理破坏 Prompt Cache）
- 摘要 (Summarization) 是不可逆的：原始消息结构被替换，无法恢复
- 保留最近 N 次工具调用的完整格式，作为 few-shot 示例
"""

from .context import AgentContext
from .infra.archive_reference import ContextArchiveReference
from .infra.cache_policy import CacheTtlPrunePolicy, resolve_cache_ttl_prune_policy
from .infra.schemas import (
    BUILTIN_PROTECTED_TOOLS,
    DEFAULT_BUSINESS_PROTECTED_TOOLS,
    DEFAULT_CONTEXT_CONFIG,
    DEFAULT_SOFT_ONLY_TOOLS,
    TOOL_PROTECTION_CONFIG,
    CacheUsageFeedback,
    CompactToolCall,
    CompressionIntent,
    ContextCompressOffloadCallback,
    ContextConfig,
    ContextOffloadResult,
    ContextSnapshotCallback,
    StructuredSummary,
    ToolProtectionConfig,
    ToolPruneMode,
)
from .infra.session_lock import (
    acquire_context_lock,
    clear_all_locks,
    get_active_session_count,
    get_current_chat_id,
    get_locked_session_count,
    get_session_lock,
    reset_current_chat_id,
    set_current_chat_id,
)

# Pipeline 架构
from .pipeline import (
    BaseProcessor,
    CompressProcessor,
    ContextPipeline,
    ExplicitCacheProcessor,
    FilterProcessor,
    ProcessorContext,
    ReasoningAnchorProcessor,
    SessionNotesProcessor,
    SummarizeProcessor,
    ThinkingBlockCleaner,
    build_default_processors,
    create_default_pipeline,
)
from .strategies.compactor import (
    COMPACT_RULES,
    compress_messages_async,
    compress_tool_message_async,
)
from .strategies.filter import (
    FILTER_TOKEN_THRESHOLD,
    FilteredResult,
    create_filtered_result,
    format_filtered_message,
    should_filter,
)
from .strategies.filters import BaseFilter, FilterContext, FilterResult, SemanticFilter, StructuralFilter
from .strategies.filters.base import SEMANTIC_CONTENT_TYPES, STRUCTURAL_CONTENT_TYPES, detect_content_type
from .strategies.summary.summarizer import generate_structured_summary, should_summarize
from .tracking.artifact_tracker import (
    ArtifactAction,
    ArtifactRecord,
    ArtifactTracker,
    clear_artifact_tracker,
    create_artifact_tracker,
    get_all_active_trackers,
    get_artifact_tracker,
    get_or_create_artifact_tracker,
)
from .tracking.task_metrics import (
    ArchiveRestoreBlockEvent,
    CompressionEvent,
    RefetchEvent,
    TaskMetrics,
    clear_task_metrics,
    create_task_metrics,
    get_all_active_metrics,
    get_or_create_task_metrics,
    get_task_metrics,
    record_archive_refetch_for_path,
)
from .active_compression import (
    ActiveCompressionConfig,
    ActiveCompressionResult,
    ActiveContextCompressionEngine,
    CompressTriggerKind,
    TokenPressureGauge,
    TokenPressureLevel,
    TokenPressureSnapshot,
)
from .ambiguity_probe import (
    AmbiguityClarificationProbe,
    AmbiguityLevel,
    BacktrackedContextDossier,
    ClarificationProbeResult,
    ClarificationQuestion,
    EntityGraphMatch,
)
from .canvas_deeplink import (
    CanvasAssetRegistry,
    CanvasDeepLinkParser,
    CanvasDeepLinkUri,
    CanvasDesignAsset,
    CanvasDesignTokens,
    CanvasLayerKind,
    CanvasLayerNode,
    CanvasTunnelingEngine,
    ProStudioPlatform,
    ProStudioSyncPayload,
)
from .clean_pod_archival import (
    CleanPodArchivalConfig,
    CleanPodArchivalEngine,
    EphemeralCleanPodDescriptor,
    NightlyArchivalJob,
    NightlyArchivalStatus,
    PodLifecycleState,
    TaskDeliverableContract,
)
from .context_diet import (
    ComponentTokenAuditItem,
    ContextComponentKind,
    ContextDietBudgetBill,
    ContextDietConfig,
    ContextDietEngine,
    DistilledSkillCard,
)
from .demand_hydration import (
    DemandHydrationConfig,
    HydratedContextEnvelope,
    HydrationDecision,
    HydrationTriggerMode,
    OnDemandContextHydrator,
    ProfileCardCategory,
    UserMemoryCard,
)
from .branch_summary import (
    BranchFileOperations,
    BranchFileOperationsTracker,
    BranchMergeConflictWarning,
    BranchSelectiveMergeEngine,
    BranchSummaryResult,
    FileActionKind,
    SelectiveMergePolicy,
    TrackedFileOperation,
)
from .dual_branching import (
    BranchDescriptor,
    BranchingPosture,
    DualBranchingSessionEngine,
    ForkCloneResult,
    TreeNodeMessage,
    VersionNavigationInfo,
)
from .dual_loop_steering import (
    DualLoopQueueSnapshot,
    DualLoopSessionQueueLedger,
    InnerLoopSteeringInterceptor,
    KeyStrokeIntent,
    LoopSteeringKind,
    SteeringDirective,
    SteeringDirectiveStatus,
)
from .dual_track_interjection import (
    DualTrackInterventionConfig,
    DualTrackInterventionCoordinator,
    InterventionStatus,
    InterventionTrack,
    PreemptionQueueSnapshot,
    StepBoundaryInjectionResult,
    UserInterventionDirective,
)
from .emergent_attention import (
    ActionTraceEvent,
    EmergentAttentionDossier,
    EmergentAttentionEngine,
    EmergentAttentionItem,
    InboundNotification,
    IntentionActionDiffItem,
    IntentionActionDiffReport,
    NotificationSieveResult,
    SieveDecision,
    StatedIntention,
    UserActionTraceKind,
)
from .harness_tax import (
    CompactWorkingMemoryProjector,
    CompactWorkingMemoryView,
    HarnessTaxAuditReport,
    HarnessTaxConfig,
    ResourceLoadBundle,
    ToolDescriptor,
    ToolExposurePolicy,
)
from .inbound_shield import (
    InboundMessageOverflowShield,
    InboundMountedDocument,
    InboundPayloadClassification,
    InboundShieldConfig,
    InboundShieldResult,
)
from .million_token_ceiling import (
    CompactionTierAction,
    CompactionTrackType,
    ContextBudgetForecast,
    MillionTokenCeilingConfig,
    MillionTokenCompactionResult,
    MillionTokenCeilingGovernor,
    OffloadedToolArtifact,
)
from .multibot_governor import (
    BotTurnEvent,
    CognitiveValueEvaluation,
    GovernorAction,
    GovernorDecision,
    GroupTurnArbitrator,
    IncrementalCognitiveValueEvaluator,
    MessageSenderRole,
    MultiBotChatterGovernor,
    MultiBotGovernorConfig,
    MutexAcquireResult,
)
from .owner_fencing import (
    AdmissionDecision,
    AdmissionStatus,
    DurableSessionOwnerFencer,
    FencingConfig,
    SessionOwnerLease,
    SessionQuiesceState,
)
from .privacy_mode import (
    ConversationPrivacyGateEngine,
    PrivacyBoundToolSet,
    PrivacyModeLevel,
    PrivacyModeSessionConfig,
    ToolCallInterceptRecord,
    ToolHardGateAction,
)
from .project_container import (
    DragDropIngestionEvent,
    ProjectAssetItem,
    ProjectAssetKind,
    ProjectContainerWorkspace,
    SessionVisibilityStatus,
    SilentArchivingResult,
    UnifiedProjectContainerEngine,
)
from .rule_lifecycle import (
    AgentRuleLifecycleAuditor,
    RuleAuditItem,
    RuleConflictPair,
    RuleConflictType,
    RuleLifecycleConfig,
    RuleLifecycleReport,
    RuleLifecycleState,
)
from .session_commit import (
    CommitJobStatus,
    CommitTriggerReason,
    ExperienceLearningItem,
    Phase1SnapshotResult,
    ProjectGuidelineItem,
    SessionCommitJob,
    SessionCommitPolicyConfig,
    TriDimensionalDistillationResult,
    TwoPhaseSessionCommitEngine,
    UserPreferenceItem,
)
from .session_dom import (
    RewindLifecycleAction,
    RewindLifecycleWorklist,
    SessionDomNode,
    SessionDomNodeKind,
    SessionDomPatch,
    SessionDomPatchOp,
    SessionDomTree,
    UniversalEventSourcedSessionDomEngine,
)
from .session_roaming import (
    CollaborationRole,
    DeviceAgnosticSessionRoamingEngine,
    DevicePlatform,
    ExecutableTeamShareBundle,
    ForkAndContinueResult,
    SandboxWarmMirrorSpec,
    SessionRoamingBreakpoint,
)
from .shareable_fork import (
    InteractiveShareableForkEngine,
    LosslessForkResult,
    ShareAccessPermission,
    ShareTokenPayload,
    ShareableForkConfig,
    SharedSessionPerspective,
)
from .worktree_isolation import (
    SessionWorktreeBinding,
    WorktreeDescriptor,
    WorktreeHygieneReport,
    WorktreeHygieneStatus,
    WorktreeRemovalPolicy,
    WorktreeRemovalResult,
    WorktreeSessionIsolationEngine,
)
from .working_memory import (
    LocalWorkingMemoryBlock,
    LocalWorkingState,
    SubtaskItem,
    SubtaskStatus,
    TrapRecord,
)
from .workspace_guard import (
    ExplorationDecisionStatus,
    ExplorationGuardDecision,
    PromptCrawlSuppressionFilter,
    WorkspaceAccessPolicy,
    WorkspaceExplorationGuardEngine,
    WorkspaceGuardConfig,
)
from .subagent_scratchpad import (
    EphemeralSubagentDossier,
    FactCategory,
    MultiAgentSharedScratchpadEngine,
    ScratchpadQueryFilter,
    SharedScratchpadFact,
    SubagentLifecycleStatus,
)
from .visual_pruner import (
    PrunedFrameFootprint,
    VisualFramePruningEngine,
    VisualPruningConfig,
    VisualPruningMode,
    VisualPruningResult,
)
from .desktop_repl import (
    DesktopApiSdk,
    DesktopElementMock,
    DesktopReplSessionSnapshot,
    PersistentDesktopReplEngine,
    ReplExecutionResult,
    ReplExecutionStatus,
    ReplRuntimeKind,
    ReplScriptCommand,
)
from .turn_truncation import (
    CanonicalTurnCommit,
    IntermediateTrialKind,
    PrefixCacheStabilityReport,
    TrialStepRecord,
    TruncationPolicy,
    TurnExecutionState,
    TurnStateTruncationEngine,
)
from .revocation_eviction import (
    RevocationDirective,
    RevocationEvictionEngine,
    RevocationScopeKind,
    SanitizationOutcome,
    TaintedContentBlock,
)
from .midflight_steering import (
    MidFlightDirective,
    MidFlightSteeringCoordinator,
    SteeringDirectiveStatus,
    SteeringExecutionTelemetry,
    SteeringInjectionEnvelope,
    SteeringIntentKind,
)
from .session_search import (
    SearchRoleFilter,
    SessionHistoryFTS5SearchEngine,
    SessionSearchHit,
    SessionSearchQuery,
    SessionSearchResult,
    SessionSearchScope,
)
from .context_pivot import (
    ArchivedContextSnapshot,
    ContextPivotConfig,
    ContextPivotResult,
    HandoffScratchpad,
    LosslessContextPivotEngine,
    PivotTriggerKind,
)
from .proactive_recall import (
    ContextGapAutoProbeEngine,
    ContextGapDetection,
    EntityType,
    PrunedEntityRecord,
    ProactiveRecallNudgeConfig,
    ProactiveRecallProbeResult,
)
from .session_bridge import (
    BridgeMessageItem,
    ExportBridgeResult,
    ExternalHarnessFormat,
    FullStateHandoffBundle,
    SessionWorkspaceState,
    ToolExecutionTrace,
    UniversalSessionBridgeEngine,
    UniversalSessionDescriptor,
)
from .skill_immunity import (
    ActiveSkillImmunityEngine,
    ActiveSkillSpec,
    ReAnchorAnchorPosition,
    ReAnchorOutcome,
    SkillImmunityConfig,
    SkillImmunityScope,
)
from .mvp_distiller import (
    ComplexProjectMvpDistillerEngine,
    DistillationOutcome,
    ModuleSpec,
    MvpDistillerConfig,
    MvpPhaseLifecycleState,
    PhaseScopePlan,
    ProjectComplexityLevel,
)
from .cron_mirroring import (
    ContinuableCronSessionMirrorEngine,
    ContinuableJobSpec,
    CronDeliveryRecord,
    CronMirrorConfig,
    CronMirrorRoleMode,
    CronMirroringOutcome,
)
from .ipc_clamping import (
    IpcClampingAction,
    IpcClampingConfig,
    IpcClampingOutcome,
    IpcMessageClampingAndSpilloverEngine,
    SpilloverArtifactSpec,
)
from .dual_file_decoupling import (
    DualFileContextEnvelope,
    DualFileDecouplingConfig,
    DualFileProjectContextDecouplingEngine,
    DynamicOverviewSections,
    ProjectRuleInvariantSpec,
)
from .project_handoff import (
    HandoffHandshakeResponse,
    ProjectHandoffConfig,
    ProjectHandoffStatus,
    ProjectWorkspaceDossier,
    TenSecondProjectHandoffEngine,
)
from .live_steering import (
    LiveResponseSteeringEngine,
    LiveSteerStatus,
    LiveSteeringConfig,
    LiveSteeringInjectionResult,
    LiveSteeringInstruction,
    LiveSteeringReconciledHistory,
    SteerChannelMode,
    SteerSeverity,
    ToolSeamAnchor,
)
from .token_governor import (
    BurnRateTelemetry,
    BurnRateZone,
    LeanToolPruningDecision,
    RateLimitBackoffDecision,
    TokenBurnRateGovernorEngine,
    TokenGovernorConfig,
    TokenUsageRecord,
    ToolLeanMode,
)
from .sandbox_reduction import (
    ActionKind,
    ActionLedgerEntry,
    InSandboxDataReductionEngine,
    LedgerQueryResult,
    ReducedOutputEnvelope,
    ReductionKind,
    SandboxReductionConfig,
)
from .prompt_cache_clock import (
    CacheTierKind,
    ClockBucketResolution,
    ContextClockSpec,
    PromptCacheClockConfig,
    PromptCacheClockGovernorEngine,
    PromptCacheTierBlock,
    TieredAssemblyResult,
    ToolChoiceMode,
)
from .fallback_buffer_notebook import (
    BufferWatermarkSnapshot,
    BufferWatermarkState,
    CompactionConsequenceAlert,
    FallbackBufferConfig,
    FallbackBufferNotebookEngine,
    TeamNotebookEntry,
    TeamNotebookSnapshot,
)
from .migratable_session import (
    DecoupledMigratableSessionEngine,
    MigratableSessionBundle,
    MigratableSessionConfig,
    SessionAccessRole,
    SessionForkOutcome,
    SessionLiveStatus,
    SessionLocationKind,
    SessionShareGrant,
    WorkspaceHotSeedSpec,
)
from .session_antidote import (
    AntidoteReceipt,
    ConfigDriftDetail,
    ConfigMutationProposal,
    FlagScope,
    GenesisConfigSnapshot,
    PoisonDiagnosisReport,
    PoisonSeverity,
    SessionAntiPoisoningEngine,
    SessionAntidoteConfig,
)

__all__ = [
    # active_compression
    "ActiveCompressionConfig",
    "ActiveCompressionResult",
    "ActiveContextCompressionEngine",
    "CompressTriggerKind",
    "TokenPressureGauge",
    "TokenPressureLevel",
    "TokenPressureSnapshot",
    # ambiguity_probe
    "AmbiguityClarificationProbe",
    "AmbiguityLevel",
    "BacktrackedContextDossier",
    "ClarificationProbeResult",
    "ClarificationQuestion",
    "EntityGraphMatch",
    # canvas_deeplink
    "CanvasAssetRegistry",
    "CanvasDeepLinkParser",
    "CanvasDeepLinkUri",
    "CanvasDesignAsset",
    "CanvasDesignTokens",
    "CanvasLayerKind",
    "CanvasLayerNode",
    "CanvasTunnelingEngine",
    "ProStudioPlatform",
    "ProStudioSyncPayload",
    # clean_pod_archival
    "CleanPodArchivalConfig",
    "CleanPodArchivalEngine",
    "EphemeralCleanPodDescriptor",
    "NightlyArchivalJob",
    "NightlyArchivalStatus",
    "PodLifecycleState",
    "TaskDeliverableContract",
    # context_diet
    "ComponentTokenAuditItem",
    "ContextComponentKind",
    "ContextDietBudgetBill",
    "ContextDietConfig",
    "ContextDietEngine",
    "DistilledSkillCard",
    # context_pivot
    "ArchivedContextSnapshot",
    "ContextPivotConfig",
    "ContextPivotResult",
    "HandoffScratchpad",
    "LosslessContextPivotEngine",
    "PivotTriggerKind",
    # demand_hydration
    "DemandHydrationConfig",
    "HydratedContextEnvelope",
    "HydrationDecision",
    "HydrationTriggerMode",
    "OnDemandContextHydrator",
    "ProfileCardCategory",
    "UserMemoryCard",
    # branch_summary
    "BranchFileOperations",
    "BranchFileOperationsTracker",
    "BranchMergeConflictWarning",
    "BranchSelectiveMergeEngine",
    "BranchSummaryResult",
    "FileActionKind",
    "SelectiveMergePolicy",
    "TrackedFileOperation",
    # dual_branching
    "BranchDescriptor",
    "BranchingPosture",
    "DualBranchingSessionEngine",
    "ForkCloneResult",
    "TreeNodeMessage",
    "VersionNavigationInfo",
    # dual_loop_steering
    "DualLoopQueueSnapshot",
    "DualLoopSessionQueueLedger",
    "InnerLoopSteeringInterceptor",
    "KeyStrokeIntent",
    "LoopSteeringKind",
    "SteeringDirective",
    "SteeringDirectiveStatus",
    # dual_track_interjection
    "DualTrackInterventionConfig",
    "DualTrackInterventionCoordinator",
    "InterventionStatus",
    "InterventionTrack",
    "PreemptionQueueSnapshot",
    "StepBoundaryInjectionResult",
    "UserInterventionDirective",
    # emergent_attention
    "ActionTraceEvent",
    "EmergentAttentionDossier",
    "EmergentAttentionEngine",
    "EmergentAttentionItem",
    "InboundNotification",
    "IntentionActionDiffItem",
    "IntentionActionDiffReport",
    "NotificationSieveResult",
    "SieveDecision",
    "StatedIntention",
    "UserActionTraceKind",
    # harness_tax
    "CompactWorkingMemoryProjector",
    "CompactWorkingMemoryView",
    "HarnessTaxAuditReport",
    "HarnessTaxConfig",
    "ResourceLoadBundle",
    "ToolDescriptor",
    "ToolExposurePolicy",
    # inbound_shield
    "InboundMessageOverflowShield",
    "InboundMountedDocument",
    "InboundPayloadClassification",
    "InboundShieldConfig",
    "InboundShieldResult",
    # million_token_ceiling
    "CompactionTierAction",
    "CompactionTrackType",
    "ContextBudgetForecast",
    "MillionTokenCeilingConfig",
    "MillionTokenCompactionResult",
    "MillionTokenCeilingGovernor",
    "OffloadedToolArtifact",
    # multibot_governor
    "BotTurnEvent",
    "CognitiveValueEvaluation",
    "GovernorAction",
    "GovernorDecision",
    "GroupTurnArbitrator",
    "IncrementalCognitiveValueEvaluator",
    "MessageSenderRole",
    "MultiBotChatterGovernor",
    "MultiBotGovernorConfig",
    "MutexAcquireResult",
    # owner_fencing
    "AdmissionDecision",
    "AdmissionStatus",
    "DurableSessionOwnerFencer",
    "FencingConfig",
    "SessionOwnerLease",
    "SessionQuiesceState",
    # privacy_mode
    "ConversationPrivacyGateEngine",
    "PrivacyBoundToolSet",
    "PrivacyModeLevel",
    "PrivacyModeSessionConfig",
    "ToolCallInterceptRecord",
    "ToolHardGateAction",
    # proactive_recall
    "ContextGapAutoProbeEngine",
    "ContextGapDetection",
    "EntityType",
    "PrunedEntityRecord",
    "ProactiveRecallNudgeConfig",
    "ProactiveRecallProbeResult",
    # project_container
    "DragDropIngestionEvent",
    "ProjectAssetItem",
    "ProjectAssetKind",
    "ProjectContainerWorkspace",
    "SessionVisibilityStatus",
    "SilentArchivingResult",
    "UnifiedProjectContainerEngine",
    # rule_lifecycle
    "AgentRuleLifecycleAuditor",
    "RuleAuditItem",
    "RuleConflictPair",
    "RuleConflictType",
    "RuleLifecycleConfig",
    "RuleLifecycleReport",
    "RuleLifecycleState",
    # session_commit
    "CommitJobStatus",
    "CommitTriggerReason",
    "ExperienceLearningItem",
    "Phase1SnapshotResult",
    "ProjectGuidelineItem",
    "SessionCommitJob",
    "SessionCommitPolicyConfig",
    "TriDimensionalDistillationResult",
    "TwoPhaseSessionCommitEngine",
    "UserPreferenceItem",
    # session_dom
    "RewindLifecycleAction",
    "RewindLifecycleWorklist",
    "SessionDomNode",
    "SessionDomNodeKind",
    "SessionDomPatch",
    "SessionDomPatchOp",
    "SessionDomTree",
    "UniversalEventSourcedSessionDomEngine",
    # session_bridge
    "BridgeMessageItem",
    "ExportBridgeResult",
    "ExternalHarnessFormat",
    "FullStateHandoffBundle",
    "SessionWorkspaceState",
    "ToolExecutionTrace",
    "UniversalSessionBridgeEngine",
    "UniversalSessionDescriptor",
    # skill_immunity
    "ActiveSkillImmunityEngine",
    "ActiveSkillSpec",
    "ReAnchorAnchorPosition",
    "ReAnchorOutcome",
    "SkillImmunityConfig",
    "SkillImmunityScope",
    # mvp_distiller
    "ComplexProjectMvpDistillerEngine",
    "DistillationOutcome",
    "ModuleSpec",
    "MvpDistillerConfig",
    "MvpPhaseLifecycleState",
    "PhaseScopePlan",
    "ProjectComplexityLevel",
    # cron_mirroring
    "ContinuableCronSessionMirrorEngine",
    "ContinuableJobSpec",
    "CronDeliveryRecord",
    "CronMirrorConfig",
    "CronMirrorRoleMode",
    "CronMirroringOutcome",
    # ipc_clamping
    "IpcClampingAction",
    "IpcClampingConfig",
    "IpcClampingOutcome",
    "IpcMessageClampingAndSpilloverEngine",
    "SpilloverArtifactSpec",
    # dual_file_decoupling
    "DualFileContextEnvelope",
    "DualFileDecouplingConfig",
    "DualFileProjectContextDecouplingEngine",
    "DynamicOverviewSections",
    "ProjectRuleInvariantSpec",
    # project_handoff
    "HandoffHandshakeResponse",
    "ProjectHandoffConfig",
    "ProjectHandoffStatus",
    "ProjectWorkspaceDossier",
    "TenSecondProjectHandoffEngine",
    # live_steering
    "LiveResponseSteeringEngine",
    "LiveSteerStatus",
    "LiveSteeringConfig",
    "LiveSteeringInjectionResult",
    "LiveSteeringInstruction",
    "LiveSteeringReconciledHistory",
    "SteerChannelMode",
    "SteerSeverity",
    "ToolSeamAnchor",
    # token_governor
    "BurnRateTelemetry",
    "BurnRateZone",
    "LeanToolPruningDecision",
    "RateLimitBackoffDecision",
    "TokenBurnRateGovernorEngine",
    "TokenGovernorConfig",
    "TokenUsageRecord",
    "ToolLeanMode",
    # sandbox_reduction
    "ActionKind",
    "ActionLedgerEntry",
    "InSandboxDataReductionEngine",
    "LedgerQueryResult",
    "ReducedOutputEnvelope",
    "ReductionKind",
    "SandboxReductionConfig",
    # prompt_cache_clock
    "CacheTierKind",
    "ClockBucketResolution",
    "ContextClockSpec",
    "PromptCacheClockConfig",
    "PromptCacheClockGovernorEngine",
    "PromptCacheTierBlock",
    "TieredAssemblyResult",
    "ToolChoiceMode",
    # fallback_buffer_notebook
    "BufferWatermarkSnapshot",
    "BufferWatermarkState",
    "CompactionConsequenceAlert",
    "FallbackBufferConfig",
    "FallbackBufferNotebookEngine",
    "TeamNotebookEntry",
    "TeamNotebookSnapshot",
    # migratable_session
    "DecoupledMigratableSessionEngine",
    "MigratableSessionBundle",
    "MigratableSessionConfig",
    "SessionAccessRole",
    "SessionForkOutcome",
    "SessionLiveStatus",
    "SessionLocationKind",
    "SessionShareGrant",
    "WorkspaceHotSeedSpec",
    # session_antidote
    "AntidoteReceipt",
    "ConfigDriftDetail",
    "ConfigMutationProposal",
    "FlagScope",
    "GenesisConfigSnapshot",
    "PoisonDiagnosisReport",
    "PoisonSeverity",
    "SessionAntiPoisoningEngine",
    "SessionAntidoteConfig",
    # session_roaming
    "CollaborationRole",
    "DeviceAgnosticSessionRoamingEngine",
    "DevicePlatform",
    "ExecutableTeamShareBundle",
    "ForkAndContinueResult",
    "SandboxWarmMirrorSpec",
    "SessionRoamingBreakpoint",
    # shareable_fork
    "InteractiveShareableForkEngine",
    "LosslessForkResult",
    "ShareAccessPermission",
    "ShareTokenPayload",
    "ShareableForkConfig",
    "SharedSessionPerspective",
    # worktree_isolation
    "SessionWorktreeBinding",
    "WorktreeDescriptor",
    "WorktreeHygieneReport",
    "WorktreeHygieneStatus",
    "WorktreeRemovalPolicy",
    "WorktreeRemovalResult",
    # workspace_guard
    "ExplorationDecisionStatus",
    "ExplorationGuardDecision",
    "PromptCrawlSuppressionFilter",
    "WorkspaceAccessPolicy",
    "WorkspaceExplorationGuardEngine",
    "WorkspaceGuardConfig",
    # subagent_scratchpad
    "EphemeralSubagentDossier",
    "FactCategory",
    "MultiAgentSharedScratchpadEngine",
    "ScratchpadQueryFilter",
    "SharedScratchpadFact",
    "SubagentLifecycleStatus",
    # visual_pruner
    "PrunedFrameFootprint",
    "VisualFramePruningEngine",
    "VisualPruningConfig",
    "VisualPruningMode",
    "VisualPruningResult",
    # desktop_repl
    "DesktopApiSdk",
    "DesktopElementMock",
    "DesktopReplSessionSnapshot",
    "PersistentDesktopReplEngine",
    "ReplExecutionResult",
    "ReplExecutionStatus",
    "ReplRuntimeKind",
    "ReplScriptCommand",
    # turn_truncation
    "CanonicalTurnCommit",
    "IntermediateTrialKind",
    "PrefixCacheStabilityReport",
    "TrialStepRecord",
    "TruncationPolicy",
    "TurnExecutionState",
    "TurnStateTruncationEngine",
    # revocation_eviction
    "RevocationDirective",
    "RevocationEvictionEngine",
    "RevocationScopeKind",
    "SanitizationOutcome",
    "TaintedContentBlock",
    # midflight_steering
    "MidFlightDirective",
    "MidFlightSteeringCoordinator",
    "SteeringDirectiveStatus",
    "SteeringExecutionTelemetry",
    "SteeringInjectionEnvelope",
    "SteeringIntentKind",
    # session_search
    "SearchRoleFilter",
    "SessionHistoryFTS5SearchEngine",
    "SessionSearchHit",
    "SessionSearchQuery",
    "SessionSearchResult",
    "SessionSearchScope",
    # schemas
    "BUILTIN_PROTECTED_TOOLS",
    "COMPACT_RULES",
    "DEFAULT_BUSINESS_PROTECTED_TOOLS",
    "DEFAULT_CONTEXT_CONFIG",
    "DEFAULT_SOFT_ONLY_TOOLS",
    # filter
    "FILTER_TOKEN_THRESHOLD",
    "SEMANTIC_CONTENT_TYPES",
    "STRUCTURAL_CONTENT_TYPES",
    "TOOL_PROTECTION_CONFIG",
    # context
    "AgentContext",
    "ArchiveRestoreBlockEvent",
    # artifact_tracker
    "ArtifactAction",
    "ArtifactRecord",
    "ArtifactTracker",
    # filters
    "BaseFilter",
    "BaseProcessor",
    "CacheTtlPrunePolicy",
    "CacheUsageFeedback",
    "CompactToolCall",
    "CompressProcessor",
    "CompressionEvent",
    "CompressionIntent",
    "ContextArchiveReference",
    "ContextCompressOffloadCallback",
    "ContextConfig",
    "ContextOffloadResult",
    # pipeline
    "ContextPipeline",
    "ContextSnapshotCallback",
    "ExplicitCacheProcessor",
    "FilterContext",
    "FilterProcessor",
    "FilterResult",
    "FilteredResult",
    "LocalWorkingMemoryBlock",
    "LocalWorkingState",
    "ProcessorContext",
    "ReasoningAnchorProcessor",
    "RefetchEvent",
    "SemanticFilter",
    "SessionNotesProcessor",
    "StructuralFilter",
    "StructuredSummary",
    "SubtaskItem",
    "SubtaskStatus",
    "SummarizeProcessor",
    # task_metrics
    "TaskMetrics",
    "ThinkingBlockCleaner",
    "ToolProtectionConfig",
    "ToolPruneMode",
    "TrapRecord",
    "acquire_context_lock",
    "build_default_processors",
    "clear_all_locks",
    "clear_artifact_tracker",
    "clear_task_metrics",
    "compress_messages_async",
    "compress_tool_message_async",
    "create_artifact_tracker",
    "create_default_pipeline",
    "create_filtered_result",
    "create_task_metrics",
    "detect_content_type",
    "format_filtered_message",
    "generate_structured_summary",
    "get_active_session_count",
    "get_all_active_metrics",
    "get_all_active_trackers",
    "get_artifact_tracker",
    "get_current_chat_id",
    "get_locked_session_count",
    "get_or_create_artifact_tracker",
    "get_or_create_task_metrics",
    # session_lock
    "get_session_lock",
    "get_task_metrics",
    "record_archive_refetch_for_path",
    "reset_current_chat_id",
    "resolve_cache_ttl_prune_policy",
    "set_current_chat_id",
    # filter
    "should_filter",
    # summarizer
    "should_summarize",
]
