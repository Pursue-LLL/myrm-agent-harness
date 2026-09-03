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

__all__ = [
    "SEAL_FILENAME",
    "SEAL_MAGIC_HEADER",
    "AdvisoryAck",
    "AdvisoryAckRegistry",
    "AgentConfig",
    "AgentEventType",
    "AgentProfileBackend",
    "AgentRuntimeConfig",
    "AgentRuntimeSpec",
    "AgentStreamEvent",
    "AttributionVerdict",
    "ChangePredictionManifest",
    "CompletionStatus",
    "ComplianceAuditEngine",
    "ComplianceOutcome",
    "ComplianceReport",
    "ComplianceStatus",
    "ComplianceTrailExporter",
    "ComplianceViolation",
    "ConfigIncompleteError",
    "ConnectorErrorCategory",
    "ConnectorHealthStatus",
    "DesktopRecordedEvent",
    "Doctor",
    "DualTrackAuditCollector",
    "FileChecksum",
    "HookEvent",
    "HookRegistryProtocol",
    "InsecureRedirectSecurityError",
    "InstalledSkillRescanEngine",
    "IntegrationProvider",
    "IntegritySealer",
    "IntegrityStatus",
    "IntegrityVerificationResult",
    "KanbanStore",
    "LLMConfig",
    "MCPAnnotations",
    "ManifestAttributionResult",
    "MetricAttributionDetail",
    "MetricPrediction",
    "MissingDependencyFailClosedError",
    "MissingDependencyFailFastError",
    "MissingSemanticsBlockedError",
    "MissingSemanticsContract",
    "MissingSemanticsDecision",
    "MissingSemanticsError",
    "MissingSemanticsPolicy",
    "Origin",
    "PredictionDirection",
    "PrivacyFailClosedLadder",
    "PrivacyFailClosedViolationError",
    "PrivacyLadderLevel",
    "PrivacyLadderScanResult",
    "PrivacyLadderValidator",
    "PrivacyLadderVerdict",
    "PrivacyLadderViolation",
    "PrivacyLadderViolationType",
    "PrivacyScanVerdict",
    "PrivacyScope",
    "SafetyMetadata",
    "SealManifest",
    "SemanticsCategory",
    "SkillAgent",
    "SkillBackend",
    "SkillRescanResult",
    "SynthesizedSkillDraft",
    "TaskSpecialty",
    "WorkflowIntentPlan",
    "WorkflowSkillCompiler",
    "build_parent_delegatable_toolkit",
    "calculate_trajectory_determinism",
    "classify_connector_error",
    "cleanup_orphan_processes",
    "compute_workflow_fingerprint",
    "create_skill_agent",
    "delete_subagent_checkpoint",
    "evaluate_five_contract_progress",
    "evaluate_manifest_attribution",
    "evaluate_missing_capability",
    "evict_skill_safety_metadata",
    "find_orphan_automation_processes",
    "generate_fix_suggestion",
    "get_distribution_mode",
    "get_ptc_safety_metadata",
    "get_subagent_checkpointer",
    "get_workspace_root",
    "is_compiled_distribution",
    "is_registered_action_tool",
    "redact_connector_url",
    "redact_sensitive_text",
    "register_ptc_safety_metadata",
    "route_task",
    "route_task_specialty",
    "set_workspace_root",
    "synthesize_desktop_skill_draft",
    "track_background_task",
    "unregister_ptc_safety_metadata",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "AdvisoryAck": (
        "myrm_agent_harness.backends.skills.scanning.rescan_engine",
        "AdvisoryAck",
    ),
    "AdvisoryAckRegistry": (
        "myrm_agent_harness.backends.skills.scanning.rescan_engine",
        "AdvisoryAckRegistry",
    ),
    "AgentConfig": ("myrm_agent_harness.api.config", "AgentConfig"),
    "AgentEventType": ("myrm_agent_harness.api.types", "AgentEventType"),
    "AgentProfileBackend": ("myrm_agent_harness.api.protocols", "AgentProfileBackend"),
    "AgentRuntimeConfig": ("myrm_agent_harness.api.types", "AgentRuntimeConfig"),
    "AgentRuntimeSpec": ("myrm_agent_harness.api.types", "AgentRuntimeSpec"),
    "AgentStreamEvent": ("myrm_agent_harness.api.types", "AgentStreamEvent"),
    "CompletionStatus": ("myrm_agent_harness.api.types", "CompletionStatus"),
    "ComplianceAuditEngine": (
        "myrm_agent_harness.runtime.diagnostics.compliance",
        "ComplianceAuditEngine",
    ),
    "ComplianceOutcome": (
        "myrm_agent_harness.observability.audit_trail",
        "ComplianceOutcome",
    ),
    "ComplianceReport": (
        "myrm_agent_harness.runtime.diagnostics.compliance",
        "ComplianceReport",
    ),
    "ComplianceStatus": (
        "myrm_agent_harness.runtime.diagnostics.compliance",
        "ComplianceStatus",
    ),
    "ComplianceTrailExporter": (
        "myrm_agent_harness.observability.audit_trail",
        "ComplianceTrailExporter",
    ),
    "ComplianceViolation": (
        "myrm_agent_harness.runtime.diagnostics.compliance",
        "ComplianceViolation",
    ),
    "ConfigIncompleteError": ("myrm_agent_harness.api.config", "ConfigIncompleteError"),
    "ConnectorErrorCategory": (
        "myrm_agent_harness.toolkits.cron.engine.connector_health",
        "ConnectorErrorCategory",
    ),
    "ConnectorHealthStatus": (
        "myrm_agent_harness.toolkits.cron.engine.connector_health",
        "ConnectorHealthStatus",
    ),
    "DesktopRecordedEvent": (
        "myrm_agent_harness.toolkits.computer_use.recording",
        "DesktopRecordedEvent",
    ),
    "Doctor": ("myrm_agent_harness.runtime.diagnostics.doctor", "Doctor"),
    "DualTrackAuditCollector": (
        "myrm_agent_harness.observability.audit_trail",
        "DualTrackAuditCollector",
    ),
    "HookEvent": ("myrm_agent_harness.api.protocols", "HookEvent"),
    "HookRegistryProtocol": (
        "myrm_agent_harness.api.protocols",
        "HookRegistryProtocol",
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
    "MCPAnnotations": (
        "myrm_agent_harness.core.security.tool_registry.registry",
        "MCPAnnotations",
    ),
    "MissingDependencyFailClosedError": (
        "myrm_agent_harness.core.security.missing_semantics",
        "MissingDependencyFailClosedError",
    ),
    "MissingDependencyFailFastError": (
        "myrm_agent_harness.core.security.missing_semantics",
        "MissingDependencyFailFastError",
    ),
    "AttributionVerdict": (
        "myrm_agent_harness.eval.manifest_prediction",
        "AttributionVerdict",
    ),
    "ChangePredictionManifest": (
        "myrm_agent_harness.eval.manifest_prediction",
        "ChangePredictionManifest",
    ),
    "ManifestAttributionResult": (
        "myrm_agent_harness.eval.manifest_prediction",
        "ManifestAttributionResult",
    ),
    "MetricAttributionDetail": (
        "myrm_agent_harness.eval.manifest_prediction",
        "MetricAttributionDetail",
    ),
    "MetricPrediction": (
        "myrm_agent_harness.eval.manifest_prediction",
        "MetricPrediction",
    ),
    "MissingSemanticsBlockedError": (
        "myrm_agent_harness.core.security.missing_semantics",
        "MissingSemanticsBlockedError",
    ),
    "MissingSemanticsContract": (
        "myrm_agent_harness.core.security.missing_semantics",
        "MissingSemanticsContract",
    ),
    "MissingSemanticsDecision": (
        "myrm_agent_harness.core.security.missing_semantics",
        "MissingSemanticsDecision",
    ),
    "MissingSemanticsError": (
        "myrm_agent_harness.core.security.missing_semantics",
        "MissingSemanticsError",
    ),
    "MissingSemanticsPolicy": (
        "myrm_agent_harness.core.security.missing_semantics",
        "MissingSemanticsPolicy",
    ),
    "Origin": (
        "myrm_agent_harness.core.security.http.redirect_guard",
        "Origin",
    ),
    "PredictionDirection": (
        "myrm_agent_harness.eval.manifest_prediction",
        "PredictionDirection",
    ),
    "PrivacyFailClosedLadder": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyFailClosedLadder",
    ),
    "PrivacyFailClosedViolationError": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyFailClosedViolationError",
    ),
    "PrivacyLadderLevel": (
        "myrm_agent_harness.core.security.privacy.ladder",
        "PrivacyLadderLevel",
    ),
    "PrivacyLadderScanResult": (
        "myrm_agent_harness.core.security.privacy.ladder",
        "PrivacyLadderScanResult",
    ),
    "PrivacyLadderValidator": (
        "myrm_agent_harness.core.security.privacy.ladder",
        "PrivacyLadderValidator",
    ),
    "PrivacyLadderViolation": (
        "myrm_agent_harness.core.security.privacy.ladder",
        "PrivacyLadderViolation",
    ),
    "PrivacyLadderVerdict": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyLadderVerdict",
    ),
    "PrivacyLadderViolationType": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyLadderViolationType",
    ),
    "PrivacyScanVerdict": (
        "myrm_agent_harness.core.security.privacy.ladder",
        "PrivacyScanVerdict",
    ),
    "PrivacyScope": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyScope",
    ),
    "FileChecksum": (
        "myrm_agent_harness.core.security.integrity.seal",
        "FileChecksum",
    ),
    "IntegritySealer": (
        "myrm_agent_harness.core.security.integrity.seal",
        "IntegritySealer",
    ),
    "IntegrityStatus": (
        "myrm_agent_harness.core.security.integrity.seal",
        "IntegrityStatus",
    ),
    "IntegrityVerificationResult": (
        "myrm_agent_harness.core.security.integrity.seal",
        "IntegrityVerificationResult",
    ),
    "SEAL_FILENAME": (
        "myrm_agent_harness.core.security.integrity.seal",
        "SEAL_FILENAME",
    ),
    "SEAL_MAGIC_HEADER": (
        "myrm_agent_harness.core.security.integrity.seal",
        "SEAL_MAGIC_HEADER",
    ),
    "SealManifest": (
        "myrm_agent_harness.core.security.integrity.seal",
        "SealManifest",
    ),
    "SafetyMetadata": (
        "myrm_agent_harness.core.security.tool_registry.registry",
        "SafetyMetadata",
    ),
    "SemanticsCategory": (
        "myrm_agent_harness.core.security.missing_semantics",
        "SemanticsCategory",
    ),
    "SkillAgent": ("myrm_agent_harness.api.factory", "SkillAgent"),
    "SkillBackend": ("myrm_agent_harness.api.protocols", "SkillBackend"),
    "SkillRescanResult": (
        "myrm_agent_harness.backends.skills.scanning.rescan_engine",
        "SkillRescanResult",
    ),
    "SynthesizedSkillDraft": (
        "myrm_agent_harness.toolkits.computer_use.recording",
        "SynthesizedSkillDraft",
    ),
    "TaskSpecialty": (
        "myrm_agent_harness.toolkits.llms.routing.specialty_router",
        "TaskSpecialty",
    ),
    "WorkflowIntentPlan": (
        "myrm_agent_harness.backends.skills.workflow_compiler",
        "WorkflowIntentPlan",
    ),
    "WorkflowSkillCompiler": (
        "myrm_agent_harness.backends.skills.workflow_compiler",
        "WorkflowSkillCompiler",
    ),
    "build_parent_delegatable_toolkit": (
        "myrm_agent_harness.api.subagents",
        "build_parent_delegatable_toolkit",
    ),
    "cleanup_orphan_processes": (
        "myrm_agent_harness.toolkits.browser.doctor.orphans",
        "cleanup_orphan_processes",
    ),
    "find_orphan_automation_processes": (
        "myrm_agent_harness.toolkits.browser.doctor.orphans",
        "find_orphan_automation_processes",
    ),
    "calculate_trajectory_determinism": (
        "myrm_agent_harness.eval.assertions",
        "calculate_trajectory_determinism",
    ),
    "classify_connector_error": (
        "myrm_agent_harness.toolkits.cron.engine.connector_health",
        "classify_connector_error",
    ),
    "compute_workflow_fingerprint": (
        "myrm_agent_harness.toolkits.cron.engine.fingerprint",
        "compute_workflow_fingerprint",
    ),
    "create_skill_agent": ("myrm_agent_harness.api.factory", "create_skill_agent"),
    "delete_subagent_checkpoint": (
        "myrm_agent_harness.api.subagents",
        "delete_subagent_checkpoint",
    ),
    "evaluate_five_contract_progress": (
        "myrm_agent_harness.eval.contracts",
        "evaluate_five_contract_progress",
    ),
    "evaluate_manifest_attribution": (
        "myrm_agent_harness.eval.manifest_prediction",
        "evaluate_manifest_attribution",
    ),
    "evaluate_missing_capability": (
        "myrm_agent_harness.core.security.missing_semantics",
        "evaluate_missing_capability",
    ),
    "evict_skill_safety_metadata": (
        "myrm_agent_harness.core.security.tool_registry.registry",
        "evict_skill_safety_metadata",
    ),
    "generate_fix_suggestion": (
        "myrm_agent_harness.toolkits.cron.engine.connector_health",
        "generate_fix_suggestion",
    ),
    "get_distribution_mode": (
        "myrm_agent_harness.runtime.install_guard.probe",
        "get_distribution_mode",
    ),
    "get_ptc_safety_metadata": (
        "myrm_agent_harness.core.security.tool_registry.registry",
        "get_ptc_safety_metadata",
    ),
    "get_subagent_checkpointer": (
        "myrm_agent_harness.api.subagents",
        "get_subagent_checkpointer",
    ),
    "get_workspace_root": ("myrm_agent_harness.api.hooks", "get_workspace_root"),
    "is_compiled_distribution": (
        "myrm_agent_harness.runtime.install_guard.probe",
        "is_compiled_distribution",
    ),
    "is_registered_action_tool": (
        "myrm_agent_harness.agent.tool_management.tool_layers",
        "is_registered_action_tool",
    ),
    "redact_connector_url": (
        "myrm_agent_harness.toolkits.cron.engine.connector_health",
        "redact_connector_url",
    ),
    "redact_sensitive_text": (
        "myrm_agent_harness.core.security.redact.engine",
        "redact_sensitive_text",
    ),
    "register_ptc_safety_metadata": (
        "myrm_agent_harness.core.security.tool_registry.registry",
        "register_ptc_safety_metadata",
    ),
    "route_task": (
        "myrm_agent_harness.toolkits.llms.routing.complexity_router",
        "route_task",
    ),
    "route_task_specialty": (
        "myrm_agent_harness.toolkits.llms.routing.specialty_router",
        "route_task_specialty",
    ),
    "set_workspace_root": ("myrm_agent_harness.api.hooks", "set_workspace_root"),
    "synthesize_desktop_skill_draft": (
        "myrm_agent_harness.toolkits.computer_use.recording",
        "synthesize_desktop_skill_draft",
    ),
    "track_background_task": (
        "myrm_agent_harness.agent.skill_agent.context",
        "track_background_task",
    ),
    "unregister_ptc_safety_metadata": (
        "myrm_agent_harness.core.security.tool_registry.registry",
        "unregister_ptc_safety_metadata",
    ),
}


if __debug__:
    _lazy_set = set(_EXPORTS.keys())
    _all_set = set(__all__)
    _missing = _all_set - _lazy_set
    _extra = _lazy_set - _all_set
    if _missing or _extra:
        raise RuntimeError(
            f"api: __all__ and _EXPORTS mismatch: missing={_missing}, extra={_extra}"
        )


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
