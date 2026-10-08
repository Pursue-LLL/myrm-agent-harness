"""Agent core module — public API."""

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    "BaseAgent": ("myrm_agent_harness.agent.base_agent", "BaseAgent"),
    "SkillAgent": ("myrm_agent_harness.agent.skill_agent", "SkillAgent"),
    "create_skill_agent": (
        "myrm_agent_harness.agent.skill_agent.factory",
        "create_skill_agent",
    ),
    "LLMConfig": ("myrm_agent_harness.agent.config", "LLMConfig"),
    "AgentRuntimeConfig": ("myrm_agent_harness.agent.types", "AgentRuntimeConfig"),
    "SubagentConfig": ("myrm_agent_harness.agent.types", "SubagentConfig"),
    "SUBAGENT_CONFIGS": ("myrm_agent_harness.agent.types", "SUBAGENT_CONFIGS"),
    "register_subagent_configs": (
        "myrm_agent_harness.agent.types",
        "register_subagent_configs",
    ),
    "register_subagent_configs_from_directory": (
        "myrm_agent_harness.agent.types",
        "register_subagent_configs_from_directory",
    ),
    "auto_register_subagent_configs": (
        "myrm_agent_harness.agent.types",
        "auto_register_subagent_configs",
    ),
    "SubAgentStatus": ("myrm_agent_harness.agent.types", "SubAgentStatus"),
    "SubAgentResult": ("myrm_agent_harness.agent.types", "SubAgentResult"),
    "HookEvent": ("myrm_agent_harness.agent.hooks", "HookEvent"),
    "HookRegistry": ("myrm_agent_harness.agent.hooks", "HookRegistry"),
    "HookExecutor": ("myrm_agent_harness.agent.hooks", "HookExecutor"),
    "fire_hook": ("myrm_agent_harness.agent.hooks", "fire_hook"),
    "AgentEventType": ("myrm_agent_harness.agent.types", "AgentEventType"),
    "AgentRunStatistics": ("myrm_agent_harness.agent.types", "AgentRunStatistics"),
    "CompletionStatus": ("myrm_agent_harness.agent.types", "CompletionStatus"),
    "map_to_completion_status": (
        "myrm_agent_harness.agent.types",
        "map_to_completion_status",
    ),
    "TokenUsage": ("myrm_agent_harness.utils.token_economics.tracker", "TokenUsage"),
    "EventLogBackend": (
        "myrm_agent_harness.agent.event_log.protocols",
        "EventLogBackend",
    ),
    "FileEventLogBackend": (
        "myrm_agent_harness.agent.event_log.backends.file_backend",
        "FileEventLogBackend",
    ),
    "GracefulShutdownManager": (
        "myrm_agent_harness.agent.hooks.graceful_shutdown",
        "GracefulShutdownManager",
    ),
    "get_shutdown_manager": (
        "myrm_agent_harness.agent.hooks.graceful_shutdown",
        "get_shutdown_manager",
    ),
    "DurableAgentRuntime": (
        "myrm_agent_harness.agent.durable",
        "DurableAgentRuntime",
    ),
    "InMemoryDurableStorage": (
        "myrm_agent_harness.agent.durable",
        "InMemoryDurableStorage",
    ),
    "SqliteDurableStorage": (
        "myrm_agent_harness.agent.durable",
        "SqliteDurableStorage",
    ),
    "IntentExecutionEngine": (
        "myrm_agent_harness.agent.durable",
        "IntentExecutionEngine",
    ),
    "LaneMutationLine": (
        "myrm_agent_harness.agent.durable",
        "LaneMutationLine",
    ),
    "ReplaySafetyAuditor": (
        "myrm_agent_harness.agent.durable",
        "ReplaySafetyAuditor",
    ),
    "ManualDriveEffectsGate": (
        "myrm_agent_harness.agent.durable",
        "ManualDriveEffectsGate",
    ),
    "SpilloverEngine": (
        "myrm_agent_harness.agent.context_guard",
        "SpilloverEngine",
    ),
    "EphemeralTransientSweeper": (
        "myrm_agent_harness.agent.context_guard",
        "EphemeralTransientSweeper",
    ),
    "ContextGuardConfig": (
        "myrm_agent_harness.agent.context_guard",
        "ContextGuardConfig",
    ),
    "SpilloverResult": (
        "myrm_agent_harness.agent.context_guard",
        "SpilloverResult",
    ),
    "SpilloverPayload": (
        "myrm_agent_harness.agent.context_guard",
        "SpilloverPayload",
    ),
    "ProactiveAgentKernelSuite": (
        "myrm_agent_harness.agent.proactive_kernel",
        "ProactiveAgentKernelSuite",
    ),
    "ProactiveAgentKernelContractAndInstinctiveProactivityLoopSuite": (
        "myrm_agent_harness.agent.proactive_kernel",
        "ProactiveAgentKernelContractAndInstinctiveProactivityLoopSuite",
    ),
    "HeartbeatManifestParser": (
        "myrm_agent_harness.agent.proactive_kernel",
        "HeartbeatManifestParser",
    ),
    "OpportunitySensingEngine": (
        "myrm_agent_harness.agent.proactive_kernel",
        "OpportunitySensingEngine",
    ),
    "ZeroNagDiscretionGate": (
        "myrm_agent_harness.agent.proactive_kernel",
        "ZeroNagDiscretionGate",
    ),
    "CanonicalScaffoldingSuite": (
        "myrm_agent_harness.agent.workspace_rules.canonical_scaffolding",
        "CanonicalScaffoldingSuite",
    ),
    "CanonicalAgentWorkspaceScaffoldingAndZeroFrictionHandoverSuite": (
        "myrm_agent_harness.agent.workspace_rules.canonical_scaffolding",
        "CanonicalAgentWorkspaceScaffoldingAndZeroFrictionHandoverSuite",
    ),
    "TopologyValidator": (
        "myrm_agent_harness.agent.workspace_rules.canonical_scaffolding",
        "TopologyValidator",
    ),
    "HeterogeneousWorkspaceSnifferAndWizard": (
        "myrm_agent_harness.agent.workspace_rules.canonical_scaffolding",
        "HeterogeneousWorkspaceSnifferAndWizard",
    ),
    "SandboxedSafeWorkspaceEncapsulator": (
        "myrm_agent_harness.agent.workspace_rules.canonical_scaffolding",
        "SandboxedSafeWorkspaceEncapsulator",
    ),
    "CrossHarnessSuite": (
        "myrm_agent_harness.agent.context_management",
        "CrossHarnessSuite",
    ),
    "CrossHarnessContextStateASTAndLosslessRehydrationSuite": (
        "myrm_agent_harness.agent.context_management",
        "CrossHarnessContextStateASTAndLosslessRehydrationSuite",
    ),
    "HeterogeneousContextHydrationBridge": (
        "myrm_agent_harness.agent.context_management",
        "HeterogeneousContextHydrationBridge",
    ),
    "ArtifactContinuityGateway": (
        "myrm_agent_harness.agent.context_management",
        "ArtifactContinuityGateway",
    ),
    "SessionStateASTEngine": (
        "myrm_agent_harness.agent.context_management",
        "SessionStateASTEngine",
    ),
    "BilateralSovereigntyArchiveHub": (
        "myrm_agent_harness.agent.context_management",
        "BilateralSovereigntyArchiveHub",
    ),
    "ZeroLockinUniversalContextPortabilitySuite": (
        "myrm_agent_harness.agent.context_management",
        "ZeroLockinUniversalContextPortabilitySuite",
    ),
    "UniversalArchiveSpecEngine": (
        "myrm_agent_harness.agent.context_management",
        "UniversalArchiveSpecEngine",
    ),
    "CrossPlatformTranscriptNormalizer": (
        "myrm_agent_harness.agent.context_management",
        "CrossPlatformTranscriptNormalizer",
    ),
    "OfflineMemoryProfileHydrationEngine": (
        "myrm_agent_harness.agent.context_management",
        "OfflineMemoryProfileHydrationEngine",
    ),
    "DecoupledMemoryConsolidationSuite": (
        "myrm_agent_harness.agent.context_management",
        "DecoupledMemoryConsolidationSuite",
    ),
    "DecoupledMemoryConsolidationDreamingEngineAndServerlessStateSyncSuite": (
        "myrm_agent_harness.agent.context_management",
        "DecoupledMemoryConsolidationDreamingEngineAndServerlessStateSyncSuite",
    ),
    "DirectMemoryDriveChannel": (
        "myrm_agent_harness.agent.context_management",
        "DirectMemoryDriveChannel",
    ),
    "NightlyDreamingPipeline": (
        "myrm_agent_harness.agent.context_management",
        "NightlyDreamingPipeline",
    ),
    "LockFreeSnapshotBroadcaster": (
        "myrm_agent_harness.agent.context_management",
        "LockFreeSnapshotBroadcaster",
    ),
    "DeterministicPersonaMemoryDriftAuditSuite": (
        "myrm_agent_harness.agent.context_management",
        "DeterministicPersonaMemoryDriftAuditSuite",
    ),
    "DeterministicPersonaMemoryDriftAuditAndLineByLineReconciliationSuite": (
        "myrm_agent_harness.agent.context_management",
        "DeterministicPersonaMemoryDriftAuditAndLineByLineReconciliationSuite",
    ),
    "LineByLineRealityReconciler": (
        "myrm_agent_harness.agent.context_management",
        "LineByLineRealityReconciler",
    ),
    "PurificationDiffEngine": (
        "myrm_agent_harness.agent.context_management",
        "PurificationDiffEngine",
    ),
    "EndToEndSealedDecisionHandoffSuite": (
        "myrm_agent_harness.agent.context_management",
        "EndToEndSealedDecisionHandoffSuite",
    ),
    "DecisionSealPacker": (
        "myrm_agent_harness.agent.context_management",
        "DecisionSealPacker",
    ),
    "DecisionInvalidationGraph": (
        "myrm_agent_harness.agent.context_management",
        "DecisionInvalidationGraph",
    ),
    "PreSealSecretMasker": (
        "myrm_agent_harness.agent.context_management",
        "PreSealSecretMasker",
    ),
    "TwoStageRankedSnippetAndSelectiveDeepExtractSuite": (
        "myrm_agent_harness.agent.context_management",
        "TwoStageRankedSnippetAndSelectiveDeepExtractSuite",
    ),
}

__all__ = [
    "ArtifactContinuityGateway",
    "BilateralSovereigntyArchiveHub",
    "CanonicalAgentWorkspaceScaffoldingAndZeroFrictionHandoverSuite",
    "CanonicalScaffoldingSuite",
    "CrossHarnessContextStateASTAndLosslessRehydrationSuite",
    "CrossHarnessSuite",
    "CrossPlatformTranscriptNormalizer",
    "DecoupledMemoryConsolidationDreamingEngineAndServerlessStateSyncSuite",
    "DecoupledMemoryConsolidationSuite",
    "DecisionInvalidationGraph",
    "DecisionSealPacker",
    "DeterministicPersonaMemoryDriftAuditAndLineByLineReconciliationSuite",
    "DeterministicPersonaMemoryDriftAuditSuite",
    "DirectMemoryDriveChannel",
    "EndToEndSealedDecisionHandoffSuite",
    "HeartbeatManifestParser",
    "HeterogeneousContextHydrationBridge",
    "HeterogeneousWorkspaceSnifferAndWizard",
    "LineByLineRealityReconciler",
    "LockFreeSnapshotBroadcaster",
    "NightlyDreamingPipeline",
    "OfflineMemoryProfileHydrationEngine",
    "OpportunitySensingEngine",
    "ProactiveAgentKernelContractAndInstinctiveProactivityLoopSuite",
    "ProactiveAgentKernelSuite",
    "PreSealSecretMasker",
    "PurificationDiffEngine",
    "SandboxedSafeWorkspaceEncapsulator",
    "TwoStageRankedSnippetAndSelectiveDeepExtractSuite",
    "UniversalArchiveSpecEngine",
    "ZeroLockinUniversalContextPortabilitySuite",
    "SessionStateASTEngine",
    "TopologyValidator",
    "SUBAGENT_CONFIGS",
    "AgentEventType",
    "AgentRunStatistics",
    "AgentRuntimeConfig",
    "BaseAgent",
    "CompletionStatus",
    "ContextGuardConfig",
    "DurableAgentRuntime",
    "EphemeralTransientSweeper",
    "EventLogBackend",
    "FileEventLogBackend",
    "GracefulShutdownManager",
    "HookEvent",
    "HookExecutor",
    "HookRegistry",
    "InMemoryDurableStorage",
    "IntentExecutionEngine",
    "LLMConfig",
    "LaneMutationLine",
    "ManualDriveEffectsGate",
    "ReplaySafetyAuditor",
    "SkillAgent",
    "SpilloverEngine",
    "SpilloverPayload",
    "SpilloverResult",
    "SqliteDurableStorage",
    "SubAgentResult",
    "SubAgentStatus",
    "SubagentConfig",
    "TokenUsage",
    "ZeroNagDiscretionGate",
    "auto_register_subagent_configs",
    "create_skill_agent",
    "fire_hook",
    "get_shutdown_manager",
    "map_to_completion_status",
    "register_subagent_configs",
    "register_subagent_configs_from_directory",
]


def __getattr__(name: str) -> object:
    """Lazily resolve public exports to keep agent package import lightweight."""
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__ + [name for name in globals() if not name.startswith("_")]))
