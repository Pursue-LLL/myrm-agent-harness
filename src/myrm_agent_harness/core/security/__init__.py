"""Core security — foundational security primitives used across all layers.

[INPUT]
- myrm_agent_harness.core.security.missing_semantics (POS: Missing semantics contract and evaluation)

[OUTPUT]
- MissingSemanticsPolicy, MissingSemanticsDecision, enforce_missing_semantics, evaluate_missing_capability: security API

[POS]
Core security exports. Foundational security primitives used across all layers.
"""

from myrm_agent_harness.core.security.device_policy import (
    BatchRiskAssessment,
    DeviceSecurityPolicy,
    evaluate_batch_risk,
)
from myrm_agent_harness.core.security.missing_semantics import (
    MissingDependencyFailClosedError,
    MissingDependencyFailFastError,
    MissingSemanticsBlockedError,
    MissingSemanticsContract,
    MissingSemanticsDecision,
    MissingSemanticsError,
    MissingSemanticsPolicy,
    SemanticsCategory,
    enforce_missing_semantics,
    evaluate_missing_capability,
    get_missing_semantics_matrix,
    get_registered_contract,
    list_registered_contracts,
    register_missing_semantics_contract,
)
from myrm_agent_harness.core.security.remote_ops_ledger import (
    ActionRecoveryHint,
    RemoteOpsActionRecord,
    compute_action_fingerprint,
    derive_recovery_hint,
)
from myrm_agent_harness.core.security.spend_governance import (
    SpendPolicy,
    SpendReceipt,
    compute_action_digest,
    is_financial_or_spend_tool,
    is_irreversible_social_action,
    is_shell_execution_tool,
    parse_spend_amount,
    verify_action_digest,
)

__all__ = [
    "ActionRecoveryHint",
    "BatchRiskAssessment",
    "DeviceSecurityPolicy",
    "MissingDependencyFailClosedError",
    "MissingDependencyFailFastError",
    "MissingSemanticsBlockedError",
    "MissingSemanticsContract",
    "MissingSemanticsDecision",
    "MissingSemanticsError",
    "MissingSemanticsPolicy",
    "RemoteOpsActionRecord",
    "SemanticsCategory",
    "SpendPolicy",
    "SpendReceipt",
    "compute_action_digest",
    "compute_action_fingerprint",
    "derive_recovery_hint",
    "enforce_missing_semantics",
    "evaluate_batch_risk",
    "evaluate_missing_capability",
    "get_missing_semantics_matrix",
    "get_registered_contract",
    "is_financial_or_spend_tool",
    "is_irreversible_social_action",
    "is_shell_execution_tool",
    "list_registered_contracts",
    "parse_spend_amount",
    "register_missing_semantics_contract",
    "verify_action_digest",
]
