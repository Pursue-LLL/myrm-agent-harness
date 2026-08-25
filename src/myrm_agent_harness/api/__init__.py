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
    "AdvisoryAck",
    "AdvisoryAckRegistry",
    "AgentConfig",
    "AgentEventType",
    "AgentProfileBackend",
    "AgentRuntimeConfig",
    "AgentRuntimeSpec",
    "AgentStreamEvent",
    "CompletionStatus",
    "ComplianceAuditEngine",
    "ComplianceReport",
    "ComplianceStatus",
    "ComplianceViolation",
    "ConfigIncompleteError",
    "ConnectorErrorCategory",
    "ConnectorHealthStatus",
    "Doctor",
    "HookEvent",
    "HookRegistryProtocol",
    "InstalledSkillRescanEngine",
    "IntegrationProvider",
    "KanbanStore",
    "LLMConfig",
    "MCPAnnotations",
    "MissingDependencyFailClosedError",
    "MissingDependencyFailFastError",
    "MissingSemanticsBlockedError",
    "MissingSemanticsContract",
    "MissingSemanticsDecision",
    "MissingSemanticsError",
    "MissingSemanticsPolicy",
    "PrivacyFailClosedLadder",
    "PrivacyFailClosedViolationError",
    "PrivacyLadderLevel",
    "PrivacyLadderVerdict",
    "PrivacyLadderViolationType",
    "PrivacyScope",
    "SEAL_FILENAME",
    "SEAL_MAGIC_HEADER",
    "FileChecksum",
    "IntegritySealer",
    "IntegrityStatus",
    "IntegrityVerificationResult",
    "SealManifest",
    "SafetyMetadata",
    "SemanticsCategory",
    "SkillAgent",
    "SkillBackend",
    "SkillRescanResult",
    "TaskSpecialty",
    "build_parent_delegatable_toolkit",
    "compute_workflow_fingerprint",
    "create_skill_agent",
    "delete_subagent_checkpoint",
    "evaluate_missing_capability",
    "evict_skill_safety_metadata",
    "get_distribution_mode",
    "get_ptc_safety_metadata",
    "get_subagent_checkpointer",
    "get_workspace_root",
    "is_compiled_distribution",
    "is_registered_action_tool",
    "register_ptc_safety_metadata",
    "route_task",
    "route_task_specialty",
    "set_workspace_root",
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
        "myrm_agent_harness.runtime.compliance",
        "ComplianceAuditEngine",
    ),
    "ComplianceReport": (
        "myrm_agent_harness.runtime.compliance",
        "ComplianceReport",
    ),
    "ComplianceStatus": (
        "myrm_agent_harness.runtime.compliance",
        "ComplianceStatus",
    ),
    "ComplianceViolation": (
        "myrm_agent_harness.runtime.compliance",
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
    "Doctor": ("myrm_agent_harness.runtime.doctor", "Doctor"),
    "HookEvent": ("myrm_agent_harness.api.protocols", "HookEvent"),
    "HookRegistryProtocol": (
        "myrm_agent_harness.api.protocols",
        "HookRegistryProtocol",
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
    "PrivacyFailClosedLadder": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyFailClosedLadder",
    ),
    "PrivacyFailClosedViolationError": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyFailClosedViolationError",
    ),
    "PrivacyLadderLevel": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyLadderLevel",
    ),
    "PrivacyLadderVerdict": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyLadderVerdict",
    ),
    "PrivacyLadderViolationType": (
        "myrm_agent_harness.core.security.guards.privacy_ladder",
        "PrivacyLadderViolationType",
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
    "TaskSpecialty": (
        "myrm_agent_harness.toolkits.llms.routing.specialty_router",
        "TaskSpecialty",
    ),
    "build_parent_delegatable_toolkit": (
        "myrm_agent_harness.api.subagents",
        "build_parent_delegatable_toolkit",
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
        "myrm_agent_harness.distribution.probe",
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
        "myrm_agent_harness.distribution.probe",
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
