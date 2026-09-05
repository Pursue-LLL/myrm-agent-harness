"""Agent security subsystem — 6-layer onion defense architecture.

[INPUT]
- .types::SecurityConfig, PermissionAction, Capability, PathPolicy (POS: core security types)
- .engine::evaluate_tool_call, check_capability (POS: security evaluation engine)
- .config::parse_security_config (POS: configuration parser)
- .audit::record_decision (POS: security audit logging)

[OUTPUT]
- SecurityConfig, PermissionAction, Capability, PathPolicy, evaluate_tool_call, parse_security_config

[POS]
Agent 安全子系统入口。提供 6 层洋葱防御架构的类型、引擎、配置与审计日志统一门面导出。
"""

from importlib import import_module as _import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    # types.py
    "Capability": (".types", "Capability"),
    "CapabilitySet": (".types", "CapabilitySet"),
    "DEFAULT_CAPABILITIES": (".types", "DEFAULT_CAPABILITIES"),
    "PermissionAction": (".types", "PermissionAction"),
    "PermissionRule": (".types", "PermissionRule"),
    "PermissionRuleset": (".types", "PermissionRuleset"),
    "DEFAULT_RULESET": (".types", "DEFAULT_RULESET"),
    "PathPolicy": (".types", "PathPolicy"),
    "SecurityConfig": (".types", "SecurityConfig"),
    "SensitivityLevel": (".types", "SensitivityLevel"),
    "PIIAction": (".types", "PIIAction"),
    "PrivacyPolicy": (".types", "PrivacyPolicy"),
    "ReviewDecision": (".types", "ReviewDecision"),
    "ReviewResult": (".types", "ReviewResult"),
    "RecentToolCall": (".types", "RecentToolCall"),
    "SecurityReviewerProtocol": (".types", "SecurityReviewerProtocol"),
    "EphemeralUserCredential": (".types", "EphemeralUserCredential"),
    "user_credentials_ctx": (".types", "user_credentials_ctx"),
    # transcript_classifier.py
    "TranscriptClassifier": (".transcript_classifier", "TranscriptClassifier"),
    # guards/privacy_tracker.py
    "get_privacy_tracker": (".guards.privacy_tracker", "get_privacy_tracker"),
    "reset_privacy_tracker": (".guards.privacy_tracker", "reset_privacy_tracker"),
    "get_pending_privacy_event": (".guards.privacy_tracker", "get_pending_privacy_event"),
    # engine.py
    "evaluate": (".engine", "evaluate"),
    "evaluate_tool_call": (".engine", "evaluate_tool_call"),
    "check_capability": (".engine", "check_capability"),
    "merge": (".engine", "merge"),
    "disabled_permissions": (".engine", "disabled_permissions"),
    "extract_url_domains": (".engine", "extract_url_domains"),
    # config.py
    "parse_security_config": (".config", "parse_security_config"),
    "from_config": (".config", "from_config"),
    # audit.py
    "record_decision": (".audit", "record_decision"),
    "get_audit_entries": (".audit", "get_audit_entries"),
    "reset_audit_log": (".audit", "reset_audit_log"),
    "SecurityDecision": (".audit", "SecurityDecision"),
    # redact.py
    "redact_sensitive_text": (".redact", "redact_sensitive_text"),
    "RedactingFormatter": (".redact", "RedactingFormatter"),
    # detection/pseudonym_store.py
    "PseudonymStore": (".detection.pseudonym_store", "PseudonymStore"),
    "get_pseudonym_store": (".detection.pseudonym_store", "get_pseudonym_store"),
    # detection/pseudonymizer.py
    "pseudonymize_text": (".detection.pseudonymizer", "pseudonymize_text"),
    "PseudonymRestorer": (".detection.pseudonymizer", "PseudonymRestorer"),
    "PIIItem": (".detection.pseudonymizer", "PIIItem"),
    # message_filtering
    "CredentialLeakFilter": (".message_filtering", "CredentialLeakFilter"),
    "FilterConfig": (".message_filtering", "FilterConfig"),
    "FilterContext": (".message_filtering", "FilterContext"),
    "MessageFilter": (".message_filtering", "MessageFilter"),
    "MessageFilterPipeline": (".message_filtering", "MessageFilterPipeline"),
    "PIIRedactionFilter": (".message_filtering", "PIIRedactionFilter"),
    "SystemRoleFilter": (".message_filtering", "SystemRoleFilter"),
    # batch_risk.py
    "BatchApprovalItem": (".batch_risk", "BatchApprovalItem"),
    "BatchItemRiskLevel": (".batch_risk", "BatchItemRiskLevel"),
    "BatchRiskItemDetail": (".batch_risk", "BatchRiskItemDetail"),
    "BatchRiskReport": (".batch_risk", "BatchRiskReport"),
    "classify_batch_approval_risk": (".batch_risk", "classify_batch_approval_risk"),
    # script_operand_verifier.py
    "extract_script_file_operand": (".script_operand_verifier", "extract_script_file_operand"),
    "compute_file_content_digest": (".script_operand_verifier", "compute_file_content_digest"),
    "verify_script_operand_integrity": (".script_operand_verifier", "verify_script_operand_integrity"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> object:
    spec = _EXPORTS.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr_name = spec
    module = _import_module(module_path, __name__)
    return getattr(module, attr_name)


def __dir__() -> list[str]:
    public = set(__all__)
    public.update(k for k in globals() if not k.startswith("_"))
    public.discard("_import_module")
    return sorted(public)
