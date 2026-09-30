"""Public API surface for myrm-agent-harness.

External consumers (myrm-agent-server, third-party agent frameworks) should
import from ``myrm_agent_harness.api`` rather than reaching into internal
modules.  Core implementation may ship as compiled native extensions (``.so``)
in release wheels while this layer remains readable Python source.

Quick start::

    from myrm_agent_harness.api import create_skill_agent, LLMConfig

    agent = await create_skill_agent(llm_config=LLMConfig(...))
"""

from __future__ import annotations

from importlib import import_module

# Names are derived from ``_EXPORTS`` below; keep them in lockstep by construction.

_EXPORTS: dict[str, tuple[str, str]] = {
    "AdvisoryAck": ("myrm_agent_harness.backends.skills.scanning.rescan_engine", "AdvisoryAck"),
    "AdvisoryAckRegistry": ("myrm_agent_harness.backends.skills.scanning.rescan_engine", "AdvisoryAckRegistry"),
    "AgentConfig": ("myrm_agent_harness.api.config", "AgentConfig"),
    "AgentEventType": ("myrm_agent_harness.api.types", "AgentEventType"),
    "AgentProfileBackend": ("myrm_agent_harness.api.protocols", "AgentProfileBackend"),
    "AgentRuntimeConfig": ("myrm_agent_harness.api.types", "AgentRuntimeConfig"),
    "AgentRuntimeSpec": ("myrm_agent_harness.api.types", "AgentRuntimeSpec"),
    "AgentStreamEvent": ("myrm_agent_harness.api.types", "AgentStreamEvent"),
    "CompletionStatus": ("myrm_agent_harness.api.types", "CompletionStatus"),
    "ComplianceAuditEngine": ("myrm_agent_harness.runtime.diagnostics.compliance", "ComplianceAuditEngine"),
    "ComplianceOutcome": ("myrm_agent_harness.observability.audit_trail", "ComplianceOutcome"),
    "ComplianceReport": ("myrm_agent_harness.runtime.diagnostics.compliance", "ComplianceReport"),
    "ComplianceStatus": ("myrm_agent_harness.runtime.diagnostics.compliance", "ComplianceStatus"),
    "ComplianceTrailExporter": ("myrm_agent_harness.observability.audit_trail", "ComplianceTrailExporter"),
    "ComplianceViolation": ("myrm_agent_harness.runtime.diagnostics.compliance", "ComplianceViolation"),
    "CjkFtsQueryPlanner": ("myrm_agent_harness.utils.db.fts5", "CjkFtsQueryPlanner"),
    "ConfidenceEvolutionEngine": ("myrm_agent_harness.toolkits.memory.strategies.merger", "ConfidenceEvolutionEngine"),
    "ConflictItem": ("myrm_agent_harness.toolkits.memory.strategies.merger", "ConflictItem"),
    "ConfigIncompleteError": ("myrm_agent_harness.api.config", "ConfigIncompleteError"),
    "ConflictSeverity": ("myrm_agent_harness.core.artifacts.fact_check", "ConflictSeverity"),
    "ConnectorErrorCategory": ("myrm_agent_harness.toolkits.cron.engine.connector_health", "ConnectorErrorCategory"),
    "ConnectorHealthStatus": ("myrm_agent_harness.toolkits.cron.engine.connector_health", "ConnectorHealthStatus"),
    "DesktopCaptureDriver": ("myrm_agent_harness.toolkits.computer_use.recording", "DesktopCaptureDriver"),
    "DesktopRecordedEvent": ("myrm_agent_harness.toolkits.computer_use.recording", "DesktopRecordedEvent"),
    "Doctor": ("myrm_agent_harness.runtime.diagnostics.doctor", "Doctor"),
    "DualTrackAuditCollector": ("myrm_agent_harness.observability.audit_trail", "DualTrackAuditCollector"),
    "FactCheckItem": ("myrm_agent_harness.core.artifacts.fact_check", "FactCheckItem"),
    "FactCheckSheet": ("myrm_agent_harness.core.artifacts.fact_check", "FactCheckSheet"),
    "FleetQuotaItem": ("myrm_agent_harness.observability.spend_control", "FleetQuotaItem"),
    "FourTierSpendControlEngine": ("myrm_agent_harness.observability.spend_control", "FourTierSpendControlEngine"),
    "InterventionAction": ("myrm_agent_harness.observability.spend_control", "InterventionAction"),
    "SpendControlConfig": ("myrm_agent_harness.observability.spend_control", "SpendControlConfig"),
    "SpendInterventionDecision": ("myrm_agent_harness.observability.spend_control", "SpendInterventionDecision"),
    "SpendInterventionTier": ("myrm_agent_harness.observability.spend_control", "SpendInterventionTier"),
    "SubtaskStatus": ("myrm_agent_harness.agent.context_management.working_memory", "SubtaskStatus"),
    "HookEvent": ("myrm_agent_harness.api.protocols", "HookEvent"),
    "reset_denial_counter": ("myrm_agent_harness.agent.middlewares.approval.helpers", "reset_denial_counter"),
    "resolve_git_branch": ("myrm_agent_harness.infra.git", "resolve_git_branch"),
    "resolve_git_metadata": ("myrm_agent_harness.infra.git", "resolve_git_metadata"),
    "GitMetadata": ("myrm_agent_harness.infra.git", "GitMetadata"),
    "ExternalSecretResolutionError": ("myrm_agent_harness.backends.secrets", "ExternalSecretResolutionError"),
    "invalidate_external_secret": ("myrm_agent_harness.backends.secrets", "invalidate_external_secret"),
    "is_external_secret_reference": ("myrm_agent_harness.backends.secrets", "is_external_secret_reference"),
    "resolve_external_secret": ("myrm_agent_harness.backends.secrets", "resolve_external_secret"),
    "EphemeralCredential": ("myrm_agent_harness.core.security.ephemeral_credentials", "EphemeralCredential"),
    "EphemeralCredentialStore": ("myrm_agent_harness.core.security.ephemeral_credentials", "EphemeralCredentialStore"),
    "EphemeralCredentialSummary": (
        "myrm_agent_harness.core.security.ephemeral_credentials",
        "EphemeralCredentialSummary",
    ),
    "get_ephemeral_credential_store": (
        "myrm_agent_harness.core.security.ephemeral_credentials",
        "get_ephemeral_credential_store",
    ),
    "validate_credential_key": ("myrm_agent_harness.core.security.ephemeral_credentials", "validate_credential_key"),
    "SingleUseTicket": ("myrm_agent_harness.agent.security.single_use_tickets", "SingleUseTicket"),
    "SingleUseTicketManager": ("myrm_agent_harness.agent.security.single_use_tickets", "SingleUseTicketManager"),
    "TicketStatus": ("myrm_agent_harness.agent.security.single_use_tickets", "TicketStatus"),
    "TokenType": ("myrm_agent_harness.agent.security.single_use_tickets", "TokenType"),
    "compute_content_digest": ("myrm_agent_harness.agent.security.single_use_tickets", "compute_content_digest"),
    "get_single_use_ticket_manager": (
        "myrm_agent_harness.agent.security.single_use_tickets",
        "get_single_use_ticket_manager",
    ),
    "CanonicalTurnRole": ("myrm_agent_harness.runtime.context.transcripts", "CanonicalTurnRole"),
    "CanonicalToolCall": ("myrm_agent_harness.runtime.context.transcripts", "CanonicalToolCall"),
    "CanonicalTranscriptTurn": ("myrm_agent_harness.runtime.context.transcripts", "CanonicalTranscriptTurn"),
    "TranscriptParseResult": ("myrm_agent_harness.runtime.context.transcripts", "TranscriptParseResult"),
    "SandboxPathRemapper": ("myrm_agent_harness.runtime.context.transcripts", "SandboxPathRemapper"),
    "ToolOutputCompactor": ("myrm_agent_harness.runtime.context.transcripts", "ToolOutputCompactor"),
    "ClaudeTranscriptParser": ("myrm_agent_harness.runtime.context.transcripts", "ClaudeTranscriptParser"),
    "CodexTranscriptParser": ("myrm_agent_harness.runtime.context.transcripts", "CodexTranscriptParser"),
    "HookRegistryProtocol": ("myrm_agent_harness.api.protocols", "HookRegistryProtocol"),
    "IncrementalTranscriptParser": (
        "myrm_agent_harness.toolkits.memory.strategies.incremental_transcript",
        "IncrementalTranscriptParser",
    ),
    "InsecureRedirectSecurityError": (
        "myrm_agent_harness.core.security.http.redirect_guard",
        "InsecureRedirectSecurityError",
    ),
    "InstalledSkillRescanEngine": (
        "myrm_agent_harness.backends.skills.scanning.rescan_engine",
        "InstalledSkillRescanEngine",
    ),
    "IntegrationProvider": ("myrm_agent_harness.api.protocols", "IntegrationProvider"),
    "KanbanStore": ("myrm_agent_harness.api.protocols", "KanbanStore"),
    "LLMConfig": ("myrm_agent_harness.api.config", "LLMConfig"),
    "LocalWorkingMemoryBlock": (
        "myrm_agent_harness.agent.context_management.working_memory",
        "LocalWorkingMemoryBlock",
    ),
    "MCPAnnotations": ("myrm_agent_harness.core.security.tool_registry.registry", "MCPAnnotations"),
    "MissingDependencyFailClosedError": (
        "myrm_agent_harness.core.security.missing_semantics",
        "MissingDependencyFailClosedError",
    ),
    "MissingDependencyFailFastError": (
        "myrm_agent_harness.core.security.missing_semantics",
        "MissingDependencyFailFastError",
    ),
    "AttributionVerdict": ("myrm_agent_harness.eval.manifest_prediction", "AttributionVerdict"),
    "ChangePredictionManifest": ("myrm_agent_harness.eval.manifest_prediction", "ChangePredictionManifest"),
    "ManifestAttributionResult": ("myrm_agent_harness.eval.manifest_prediction", "ManifestAttributionResult"),
    "MetricAttributionDetail": ("myrm_agent_harness.eval.manifest_prediction", "MetricAttributionDetail"),
    "MetricContract": ("myrm_agent_harness.eval.metric_contract", "MetricContract"),
    "OverlayScope": ("myrm_agent_harness.agent.session_overlay.schema", "OverlayScope"),
    "OverlayShellType": ("myrm_agent_harness.agent.continual.overlay", "OverlayShellType"),
    "OverlayStatus": ("myrm_agent_harness.agent.session_overlay.schema", "OverlayStatus"),
    "OverlayTargetType": ("myrm_agent_harness.agent.session_overlay.schema", "OverlayTargetType"),
    "SessionOverlay": ("myrm_agent_harness.agent.session_overlay.schema", "SessionOverlay"),
    "MetricPrediction": ("myrm_agent_harness.eval.manifest_prediction", "MetricPrediction"),
    "MissingSemanticsBlockedError": (
        "myrm_agent_harness.core.security.missing_semantics",
        "MissingSemanticsBlockedError",
    ),
    "MissingSemanticsContract": ("myrm_agent_harness.core.security.missing_semantics", "MissingSemanticsContract"),
    "MissingSemanticsDecision": ("myrm_agent_harness.core.security.missing_semantics", "MissingSemanticsDecision"),
    "MissingSemanticsError": ("myrm_agent_harness.core.security.missing_semantics", "MissingSemanticsError"),
    "MissingSemanticsPolicy": ("myrm_agent_harness.core.security.missing_semantics", "MissingSemanticsPolicy"),
    "Origin": ("myrm_agent_harness.core.security.http.redirect_guard", "Origin"),
    "PredictionDirection": ("myrm_agent_harness.eval.manifest_prediction", "PredictionDirection"),
    "PrivacyFailClosedLadder": ("myrm_agent_harness.core.security.guards.privacy_ladder", "PrivacyFailClosedLadder"),
    "PrivacyFailClosedViolationError": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyFailClosedViolationError",
    ),
    "PrivacyLadderLevel": ("myrm_agent_harness.core.security.privacy.ladder", "PrivacyLadderLevel"),
    "PrivacyLadderScanResult": ("myrm_agent_harness.core.security.privacy.ladder", "PrivacyLadderScanResult"),
    "PrivacyLadderValidator": ("myrm_agent_harness.core.security.privacy.ladder", "PrivacyLadderValidator"),
    "PrivacyLadderViolation": ("myrm_agent_harness.core.security.privacy.ladder", "PrivacyLadderViolation"),
    "PrivacyLadderVerdict": ("myrm_agent_harness.core.security.guards.privacy_ladder", "PrivacyLadderVerdict"),
    "PrivacyLadderViolationType": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyLadderViolationType",
    ),
    "PrivacyScanVerdict": ("myrm_agent_harness.core.security.privacy.ladder", "PrivacyScanVerdict"),
    "PrivacyScope": ("myrm_agent_harness.core.security.guards.privacy_ladder", "PrivacyScope"),
    "ResolutionStatus": ("myrm_agent_harness.core.artifacts.fact_check", "ResolutionStatus"),
    "FileChecksum": ("myrm_agent_harness.core.security.integrity.seal", "FileChecksum"),
    "IntegritySealer": ("myrm_agent_harness.core.security.integrity.seal", "IntegritySealer"),
    "IntegrityStatus": ("myrm_agent_harness.core.security.integrity.seal", "IntegrityStatus"),
    "IntegrityVerificationResult": ("myrm_agent_harness.core.security.integrity.seal", "IntegrityVerificationResult"),
    "SalientToolEvidence": ("myrm_agent_harness.agent.context_management.salient_tool_filter", "SalientToolEvidence"),
    "SalientToolFilterConfig": (
        "myrm_agent_harness.agent.context_management.salient_tool_filter",
        "SalientToolFilterConfig",
    ),
    "extract_salient_tool_evidences": (
        "myrm_agent_harness.agent.context_management.salient_tool_filter",
        "extract_salient_tool_evidences",
    ),
    "strip_ansi_sequences": ("myrm_agent_harness.agent.context_management.salient_tool_filter", "strip_ansi_sequences"),
    "SEAL_FILENAME": ("myrm_agent_harness.core.security.integrity.seal", "SEAL_FILENAME"),
    "SEAL_MAGIC_HEADER": ("myrm_agent_harness.core.security.integrity.seal", "SEAL_MAGIC_HEADER"),
    "SealManifest": ("myrm_agent_harness.core.security.integrity.seal", "SealManifest"),
    "SafetyMetadata": ("myrm_agent_harness.core.security.tool_registry.registry", "SafetyMetadata"),
    "SemanticsCategory": ("myrm_agent_harness.core.security.missing_semantics", "SemanticsCategory"),
    "SkillAgent": ("myrm_agent_harness.api.factory", "SkillAgent"),
    "SkillBackend": ("myrm_agent_harness.api.protocols", "SkillBackend"),
    "SkillRescanResult": ("myrm_agent_harness.backends.skills.scanning.rescan_engine", "SkillRescanResult"),
    "SourceClaim": ("myrm_agent_harness.core.artifacts.fact_check", "SourceClaim"),
    "SynthesizedSkillDraft": ("myrm_agent_harness.toolkits.computer_use.recording", "SynthesizedSkillDraft"),
    "TaskSpecialty": ("myrm_agent_harness.toolkits.llms.routing.specialty_router", "TaskSpecialty"),
    "TranscriptIncrementalChunk": (
        "myrm_agent_harness.toolkits.memory.strategies.incremental_transcript",
        "TranscriptIncrementalChunk",
    ),
    "TranscriptTurn": ("myrm_agent_harness.toolkits.memory.strategies.incremental_transcript", "TranscriptTurn"),
    "DEFAULT_ALLOWED_TOOLS": ("myrm_agent_harness.backends.skills.workflow_compiler", "DEFAULT_ALLOWED_TOOLS"),
    "RecordedActionType": ("myrm_agent_harness.toolkits.computer_use.recording.types", "RecordedActionType"),
    "is_secure_role": ("myrm_agent_harness.toolkits.computer_use.dref.types", "is_secure_role"),
    "WorkflowIntentPlan": ("myrm_agent_harness.backends.skills.workflow_compiler", "WorkflowIntentPlan"),
    "WorkflowSkillCompiler": ("myrm_agent_harness.backends.skills.workflow_compiler", "WorkflowSkillCompiler"),
    "build_parent_delegatable_toolkit": ("myrm_agent_harness.api.subagents", "build_parent_delegatable_toolkit"),
    "cluster_and_debounce_events": (
        "myrm_agent_harness.toolkits.computer_use.recording",
        "cluster_and_debounce_events",
    ),
    "cleanup_orphan_processes": ("myrm_agent_harness.toolkits.browser.doctor.orphans", "cleanup_orphan_processes"),
    "find_orphan_automation_processes": (
        "myrm_agent_harness.toolkits.browser.doctor.orphans",
        "find_orphan_automation_processes",
    ),
    "calculate_trajectory_determinism": ("myrm_agent_harness.eval.assertions", "calculate_trajectory_determinism"),
    "classify_connector_error": (
        "myrm_agent_harness.toolkits.cron.engine.connector_health",
        "classify_connector_error",
    ),
    "compute_workflow_fingerprint": (
        "myrm_agent_harness.toolkits.cron.engine.fingerprint",
        "compute_workflow_fingerprint",
    ),
    "create_skill_agent": ("myrm_agent_harness.api.factory", "create_skill_agent"),
    "create_working_memory_manage_tool": (
        "myrm_agent_harness.agent.meta_tools.working_memory",
        "create_working_memory_manage_tool",
    ),
    "delete_subagent_checkpoint": ("myrm_agent_harness.api.subagents", "delete_subagent_checkpoint"),
    "drop_subagent_checkpoint_if_terminal": (
        "myrm_agent_harness.api.subagents",
        "drop_subagent_checkpoint_if_terminal",
    ),
    "evaluate_five_contract_progress": ("myrm_agent_harness.eval.contracts", "evaluate_five_contract_progress"),
    "evaluate_manifest_attribution": ("myrm_agent_harness.eval.manifest_prediction", "evaluate_manifest_attribution"),
    "evaluate_metric_proxy_alignment": ("myrm_agent_harness.eval.metric_contract", "evaluate_metric_proxy_alignment"),
    "get_session_overlay_manager": ("myrm_agent_harness.agent.session_overlay.manager", "get_session_overlay_manager"),
    "evaluate_missing_capability": (
        "myrm_agent_harness.core.security.missing_semantics",
        "evaluate_missing_capability",
    ),
    "evict_skill_safety_metadata": (
        "myrm_agent_harness.core.security.tool_registry.registry",
        "evict_skill_safety_metadata",
    ),
    "generate_fix_suggestion": ("myrm_agent_harness.toolkits.cron.engine.connector_health", "generate_fix_suggestion"),
    "close_subagent_checkpointer": ("myrm_agent_harness.api.subagents", "close_subagent_checkpointer"),
    "get_distribution_mode": ("myrm_agent_harness.runtime.install_guard.probe", "get_distribution_mode"),
    "get_ptc_safety_metadata": ("myrm_agent_harness.core.security.tool_registry.registry", "get_ptc_safety_metadata"),
    "get_subagent_checkpointer": ("myrm_agent_harness.api.subagents", "get_subagent_checkpointer"),
    "get_workspace_root": ("myrm_agent_harness.api.hooks", "get_workspace_root"),
    "is_compiled_distribution": ("myrm_agent_harness.runtime.install_guard.probe", "is_compiled_distribution"),
    "is_registered_action_tool": ("myrm_agent_harness.agent.tool_management.tool_layers", "is_registered_action_tool"),
    "redact_connector_url": ("myrm_agent_harness.toolkits.cron.engine.connector_health", "redact_connector_url"),
    "redact_sensitive_text": ("myrm_agent_harness.core.security.redact.engine", "redact_sensitive_text"),
    "register_ptc_safety_metadata": (
        "myrm_agent_harness.core.security.tool_registry.registry",
        "register_ptc_safety_metadata",
    ),
    "route_task": ("myrm_agent_harness.toolkits.llms.routing.complexity_router", "route_task"),
    "route_task_specialty": ("myrm_agent_harness.toolkits.llms.routing.specialty_router", "route_task_specialty"),
    "set_workspace_root": ("myrm_agent_harness.api.hooks", "set_workspace_root"),
    "synthesize_desktop_skill_draft": (
        "myrm_agent_harness.toolkits.computer_use.recording",
        "synthesize_desktop_skill_draft",
    ),
    "track_background_task": ("myrm_agent_harness.agent.skill_agent.context", "track_background_task"),
    "unregister_ptc_safety_metadata": (
        "myrm_agent_harness.core.security.tool_registry.registry",
        "unregister_ptc_safety_metadata",
    ),
    "DistillationCandidate": (
        "myrm_agent_harness.toolkits.memory.strategies.distillation_guards",
        "DistillationCandidate",
    ),
    "DistillationOrigin": ("myrm_agent_harness.toolkits.memory.strategies.distillation_guards", "DistillationOrigin"),
    "DistillationRejectionCode": (
        "myrm_agent_harness.toolkits.memory.strategies.distillation_guards",
        "DistillationRejectionCode",
    ),
    "EvidenceReference": ("myrm_agent_harness.toolkits.memory.strategies.distillation_guards", "EvidenceReference"),
    "SelfIdentityState": ("myrm_agent_harness.toolkits.memory.strategies.distillation_guards", "SelfIdentityState"),
    "check_distillable": ("myrm_agent_harness.toolkits.memory.strategies.distillation_guards", "check_distillable"),
    "filter_distillable_messages": (
        "myrm_agent_harness.toolkits.memory.strategies.distillation_guards",
        "filter_distillable_messages",
    ),
    "filter_memories_with_evidence": (
        "myrm_agent_harness.toolkits.memory.strategies.distillation_guards",
        "filter_memories_with_evidence",
    ),
    "is_alert_or_bot_sender": (
        "myrm_agent_harness.toolkits.memory.strategies.distillation_guards",
        "is_alert_or_bot_sender",
    ),
    "HitSource": ("myrm_agent_harness.toolkits.memory.types", "HitSource"),
    "RecallDebugTrace": ("myrm_agent_harness.toolkits.memory.types", "RecallDebugTrace"),
    "tokenize_cjk_bigram": ("myrm_agent_harness.toolkits.retriever.cjk_tokenizer", "tokenize_cjk_bigram"),
    "build_cjk_index_segment": ("myrm_agent_harness.toolkits.retriever.cjk_tokenizer", "build_cjk_index_segment"),
    "build_cjk_query_tokens": ("myrm_agent_harness.toolkits.retriever.cjk_tokenizer", "build_cjk_query_tokens"),
    "build_cjk_query_token_tiers": (
        "myrm_agent_harness.toolkits.retriever.cjk_tokenizer",
        "build_cjk_query_token_tiers",
    ),
    "fuse_rrf_deterministic": ("myrm_agent_harness.toolkits.retriever.fusion_strategies", "fuse_rrf_deterministic"),
    "RankedList": ("myrm_agent_harness.toolkits.retriever.fusion_strategies", "RankedList"),
    "FusedHit": ("myrm_agent_harness.toolkits.retriever.fusion_strategies", "FusedHit"),
    "RecallDebug": ("myrm_agent_harness.toolkits.retriever.fusion_strategies", "RecallDebug"),
    "tokenize_for_fts": ("myrm_agent_harness.toolkits.wiki.retrieval.tokenizer", "tokenize_for_fts"),
    "BehavioralMessage": ("myrm_agent_harness.toolkits.memory.strategies.behavioral_measurement", "BehavioralMessage"),
    "BehavioralStatsOptions": (
        "myrm_agent_harness.toolkits.memory.strategies.behavioral_measurement",
        "BehavioralStatsOptions",
    ),
    "RoutineMeasurement": (
        "myrm_agent_harness.toolkits.memory.strategies.behavioral_measurement",
        "RoutineMeasurement",
    ),
    "compute_routine_measurement": (
        "myrm_agent_harness.toolkits.memory.strategies.behavioral_measurement",
        "compute_routine_measurement",
    ),
    "generate_behavioral_profile_candidates": (
        "myrm_agent_harness.toolkits.memory.strategies.behavioral_measurement",
        "generate_behavioral_profile_candidates",
    ),
    "resolve_utc_offset_minutes": (
        "myrm_agent_harness.toolkits.memory.strategies.behavioral_measurement",
        "resolve_utc_offset_minutes",
    ),
    "RepoCommitItem": ("myrm_agent_harness.toolkits.code_execution.git_digest", "RepoCommitItem"),
    "RepoHistoryEvidenceDigest": ("myrm_agent_harness.toolkits.code_execution.git_digest", "RepoHistoryEvidenceDigest"),
    "extract_repo_history_digest": (
        "myrm_agent_harness.toolkits.code_execution.git_digest",
        "extract_repo_history_digest",
    ),
    "QuantizedVector": ("myrm_agent_harness.toolkits.vector.quantization", "QuantizedVector"),
    "quantize_int8": ("myrm_agent_harness.toolkits.vector.quantization", "quantize_int8"),
    "dequantize_int8": ("myrm_agent_harness.toolkits.vector.quantization", "dequantize_int8"),
    "SkillCompoundingMetrics": ("myrm_agent_harness.observability.digest.types", "SkillCompoundingMetrics"),
    "SkillHealthScore": ("myrm_agent_harness.observability.digest.types", "SkillHealthScore"),
    "SkillHealthStatus": ("myrm_agent_harness.observability.digest.types", "SkillHealthStatus"),
    "SkillHealthEvaluator": ("myrm_agent_harness.observability.digest.health_evaluator", "SkillHealthEvaluator"),
    "cosine_similarity_int8": ("myrm_agent_harness.toolkits.vector.quantization", "cosine_similarity_int8"),
    "is_within_boundary": ("myrm_agent_harness.core.security.path_security", "is_within_boundary"),
    "safe_join_path": ("myrm_agent_harness.core.security.path_security", "safe_join_path"),
    "safe_purge_fts5_virtual_table": ("myrm_agent_harness.utils.db.fts5", "safe_purge_fts5_virtual_table"),
    "build_isolated_child_env": (
        "myrm_agent_harness.toolkits.code_execution.security.env_isolation",
        "build_isolated_child_env",
    ),
    "EnvInheritPolicy": ("myrm_agent_harness.toolkits.code_execution.security.env_isolation", "EnvInheritPolicy"),
    "ProviderBalanceProbeProtocol": ("myrm_agent_harness.toolkits.llms.probe", "ProviderBalanceProbeProtocol"),
    "ProviderBalanceResult": ("myrm_agent_harness.toolkits.llms.probe", "ProviderBalanceResult"),
    "ProviderBalanceStatus": ("myrm_agent_harness.toolkits.llms.probe", "ProviderBalanceStatus"),
    "WorkingMemorySnapshot": ("myrm_agent_harness.toolkits.memory", "WorkingMemorySnapshot"),
    "create_consolidation_cleanup_task": ("myrm_agent_harness.toolkits.memory", "create_consolidation_cleanup_task"),
    "TaintedEgressGateway": ("myrm_agent_harness.core.security.egress", "TaintedEgressGateway"),
    "TaintedEgressDecision": ("myrm_agent_harness.core.security.egress", "TaintedEgressDecision"),
    "TaintedEgressBlockedError": ("myrm_agent_harness.core.security.egress", "TaintedEgressBlockedError"),
    "TaintedEgressBlockedException": ("myrm_agent_harness.core.security.egress", "TaintedEgressBlockedException"),
    "RestrictedAccessibilityBrowserSession": (
        "myrm_agent_harness.toolkits.browser.session",
        "RestrictedAccessibilityBrowserSession",
    ),
    "create_restricted_ax_browser_tools": (
        "myrm_agent_harness.toolkits.browser.session",
        "create_restricted_ax_browser_tools",
    ),
    "ReadOnlySSHValidator": ("myrm_agent_harness.toolkits.ssh_remote", "ReadOnlySSHValidator"),
    "SSHRemoteExecutor": ("myrm_agent_harness.toolkits.ssh_remote", "SSHRemoteExecutor"),
    "SSHHostSpec": ("myrm_agent_harness.toolkits.ssh_remote", "SSHHostSpec"),
    "SSHCommandResult": ("myrm_agent_harness.toolkits.ssh_remote", "SSHCommandResult"),
}

# ``__all__`` is derived from ``_EXPORTS`` so the two cannot drift: every name is declared once,
# in ``_EXPORTS``, which is also what ``__getattr__`` resolves against.
__all__: list[str] = list(_EXPORTS)


if __debug__:
    # Guard against a name that is exported but cannot be resolved at import time.
    _unresolvable = [name for name, (module_name, attr_name) in _EXPORTS.items() if not module_name or not attr_name]
    if _unresolvable:
        raise RuntimeError(f"api: _EXPORTS has incomplete targets: {_unresolvable}")


def __getattr__(name: str) -> object:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
