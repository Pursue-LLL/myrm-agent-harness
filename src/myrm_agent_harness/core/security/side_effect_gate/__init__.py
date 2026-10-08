"""Pre-Action Side-Effect Gate and Post-Run Acceptance module.

[INPUT]
None.

[OUTPUT]
Exported public classes, functions, and models.

[POS]
Harness core security subsystem for dual separation of irreversible action authorization
and deliverable quality acceptance.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.side_effect_gate.acceptance import (
    DeterministicAcceptanceEvaluator,
)
from myrm_agent_harness.core.security.side_effect_gate.gate import (
    PreActionEvaluationResult,
    PreActionSideEffectGate,
)
from myrm_agent_harness.core.security.side_effect_gate.idempotency import (
    IdempotencyReceiptCache,
    compute_idempotency_key,
)
from myrm_agent_harness.core.security.side_effect_gate.types import (
    AcceptanceReport,
    AcceptanceRule,
    AcceptanceRuleType,
    AcceptanceViolation,
    ActionArguments,
    ActionArgumentValue,
    ActionReceipt,
    PreActionApprovalRequiredError,
    PreActionChallenge,
    PreActionDeniedError,
    PreActionRiskLevel,
    PreActionStatus,
    SideEffectType,
)

__all__ = [
    "AcceptanceReport",
    "AcceptanceRule",
    "AcceptanceRuleType",
    "AcceptanceViolation",
    "ActionArguments",
    "ActionArgumentValue",
    "ActionReceipt",
    "DeterministicAcceptanceEvaluator",
    "IdempotencyReceiptCache",
    "PreActionApprovalRequiredError",
    "PreActionChallenge",
    "PreActionDeniedError",
    "PreActionEvaluationResult",
    "PreActionRiskLevel",
    "PreActionSideEffectGate",
    "PreActionStatus",
    "SideEffectType",
    "compute_idempotency_key",
]
