"""Missing Semantics Contract Matrix and Fail-Closed Gate.

Standardized contract matrix for missing components across the system:
1. Fail-Closed: Strict block for security-critical dependencies (sandbox, required secrets).
2. Fail-Fast: Immediate abort on core infrastructure startup dependencies (database, primary bus).
3. Fallback: Graceful degradation for auxiliary/read-only components (review models, search caches).

[INPUT]
- (none — pure security contract, zero dependency)

[OUTPUT]
- MissingSemanticsPolicy: Enum (FAIL_CLOSED, FAIL_FAST, FALLBACK)
- SemanticsCategory: Enum for capability domains
- MissingSemanticsContract: Dataclass declaring policy, error code, and diagnostics
- MissingSemanticsBlockedError: Strong exception thrown on fail-closed breach
- MissingSemanticsDecision: Evaluation outcome
- evaluate_missing_capability: Global evaluator function
- get_missing_semantics_matrix: Accessor for the SSOT contract matrix

[POS]
Foundational security contract matrix. Enforced before execution or capability invocation
to prevent silent bare-metal execution or degraded security bypass.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class MissingSemanticsPolicy(StrEnum):
    """Degradation policies when a required capability or component is missing."""

    FAIL_CLOSED = "fail_closed"
    FAIL_FAST = "fail_fast"
    FALLBACK = "fallback"


class SemanticsCategory(StrEnum):
    """Capability domains classified by their absence risk profile."""

    SANDBOX_ISOLATION = "sandbox_isolation"
    CREDENTIAL_VAULT = "credential_vault"
    CORE_DATABASE = "core_database"
    SECURITY_REVIEWER = "security_reviewer"
    READONLY_CACHE = "readonly_cache"


@dataclass(frozen=True, slots=True)
class MissingSemanticsContract:
    """Immutable contract specification for a missing capability domain."""

    category: SemanticsCategory
    policy: MissingSemanticsPolicy
    error_code: str
    user_message: str
    remediation_hint: str


class MissingSemanticsBlockedError(RuntimeError):
    """Exception raised when an operation is blocked by a FAIL_CLOSED missing semantics policy."""

    def __init__(
        self,
        contract: MissingSemanticsContract,
        detail: str | None = None,
    ) -> None:
        self.contract = contract
        self.detail = detail
        message = (
            f"[{contract.error_code}] Execution blocked by MissingSemantics policy ({contract.policy.value}): "
            f"{contract.user_message}. Hint: {contract.remediation_hint}"
        )
        if detail:
            message = f"{message} (Detail: {detail})"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class MissingSemanticsDecision:
    """Outcome of evaluating capability availability against the contract matrix."""

    category: SemanticsCategory
    is_available: bool
    policy: MissingSemanticsPolicy
    action: str  # "PROCEED" | "BLOCKED" | "FALLBACK" | "ABORT"
    error_code: str | None = None
    reason: str | None = None


_DEFAULT_MISSING_SEMANTICS_MATRIX: dict[SemanticsCategory, MissingSemanticsContract] = {
    SemanticsCategory.SANDBOX_ISOLATION: MissingSemanticsContract(
        category=SemanticsCategory.SANDBOX_ISOLATION,
        policy=MissingSemanticsPolicy.FAIL_CLOSED,
        error_code="ERR_MISSING_SANDBOX_ISOLATION",
        user_message="Sandbox container isolation provider is unavailable",
        remediation_hint="Ensure the Docker/Sandbox daemon is running or verify sandbox daemon connectivity. Bare-metal fallback is prohibited.",
    ),
    SemanticsCategory.CREDENTIAL_VAULT: MissingSemanticsContract(
        category=SemanticsCategory.CREDENTIAL_VAULT,
        policy=MissingSemanticsPolicy.FAIL_CLOSED,
        error_code="ERR_MISSING_REQUIRED_SECRET",
        user_message="Required credential or secret is missing from vault",
        remediation_hint="Configure the required secret in Agent Settings / Vault before invoking this tool.",
    ),
    SemanticsCategory.CORE_DATABASE: MissingSemanticsContract(
        category=SemanticsCategory.CORE_DATABASE,
        policy=MissingSemanticsPolicy.FAIL_FAST,
        error_code="ERR_MISSING_CORE_DATABASE",
        user_message="Core persistence storage is unreachable",
        remediation_hint="Check database connectivity and filesystem permissions.",
    ),
    SemanticsCategory.SECURITY_REVIEWER: MissingSemanticsContract(
        category=SemanticsCategory.SECURITY_REVIEWER,
        policy=MissingSemanticsPolicy.FALLBACK,
        error_code="WARN_FALLBACK_DEFAULT_MODEL",
        user_message="Dedicated reviewer model is unavailable, falling back to primary model",
        remediation_hint="Configure a dedicated reviewer model in Security Settings for enhanced auditing.",
    ),
    SemanticsCategory.READONLY_CACHE: MissingSemanticsContract(
        category=SemanticsCategory.READONLY_CACHE,
        policy=MissingSemanticsPolicy.FALLBACK,
        error_code="WARN_FALLBACK_DIRECT_FETCH",
        user_message="Read-only cache service is missing, falling back to direct query",
        remediation_hint="Start local cache instance to accelerate performance.",
    ),
}


def get_missing_semantics_matrix() -> (
    Mapping[SemanticsCategory, MissingSemanticsContract]
):
    """Retrieve the global SSOT missing semantics contract matrix."""
    return _DEFAULT_MISSING_SEMANTICS_MATRIX


def evaluate_missing_capability(
    category: SemanticsCategory,
    is_available: bool,
    *,
    detail: str | None = None,
) -> MissingSemanticsDecision:
    """Evaluate capability availability against the contract matrix.

    Args:
        category: The capability domain being evaluated.
        is_available: Whether the underlying capability provider is present and healthy.
        detail: Optional contextual detail for audit and exception logging.

    Returns:
        MissingSemanticsDecision with the computed action.

    Raises:
        MissingSemanticsBlockedError: If the capability is missing and policy is FAIL_CLOSED.
    """
    contract = _DEFAULT_MISSING_SEMANTICS_MATRIX.get(
        category,
        MissingSemanticsContract(
            category=category,
            policy=MissingSemanticsPolicy.FAIL_CLOSED,
            error_code="ERR_UNKNOWN_MISSING_SEMANTICS",
            user_message=f"Unknown capability {category.value} is unavailable",
            remediation_hint="Register an explicit MissingSemanticsContract for this capability.",
        ),
    )

    if is_available:
        return MissingSemanticsDecision(
            category=category,
            is_available=True,
            policy=contract.policy,
            action="PROCEED",
        )

    if contract.policy == MissingSemanticsPolicy.FAIL_CLOSED:
        raise MissingSemanticsBlockedError(contract=contract, detail=detail)

    if contract.policy == MissingSemanticsPolicy.FAIL_FAST:
        return MissingSemanticsDecision(
            category=category,
            is_available=False,
            policy=contract.policy,
            action="ABORT",
            error_code=contract.error_code,
            reason=contract.user_message,
        )

    # FALLBACK
    return MissingSemanticsDecision(
        category=category,
        is_available=False,
        policy=contract.policy,
        action="FALLBACK",
        error_code=contract.error_code,
        reason=contract.user_message,
    )
