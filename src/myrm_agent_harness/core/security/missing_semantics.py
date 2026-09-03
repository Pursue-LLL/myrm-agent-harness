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
- MissingSemanticsError: Base security exception for missing dependency contracts
- MissingDependencyFailClosedError: Strong exception thrown on fail-closed breach
- MissingDependencyFailFastError: Strong exception thrown on fail-fast breach
- MissingSemanticsBlockedError: Backward-compatible alias for MissingDependencyFailClosedError
- MissingSemanticsDecision: Evaluation outcome
- evaluate_missing_capability: Global evaluator function
- get_missing_semantics_matrix: Accessor for the SSOT contract matrix
- register_missing_semantics_contract: Dynamic registration hook for new capability contracts
- enforce_missing_semantics: Zero-overhead guard decorator for sync/async functions

[POS]
Foundational security contract matrix. Enforced before execution or capability invocation
to prevent silent bare-metal execution or degraded security bypass.
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


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

    category: SemanticsCategory | str
    policy: MissingSemanticsPolicy
    error_code: str
    user_message: str
    remediation_hint: str
    description: str | None = None


class MissingSemanticsError(Exception):
    """Base exception for all missing semantics contract violations."""

    def __init__(
        self,
        message: str,
        *,
        component_name: str,
        policy: MissingSemanticsPolicy,
        error_code: str | None = None,
        action: str | None = None,
        repair_hint: str | None = None,
        details: str | None = None,
    ) -> None:
        super().__init__(message)
        self.component_name = component_name
        self.policy = policy
        self.error_code = error_code or f"ERR_MISSING_{component_name.upper()}"
        self.action = action
        self.repair_hint = repair_hint
        self.details = details

    def to_diagnostic_dict(self) -> dict[str, Any]:
        """Serialize exception metadata into structured diagnostic payload."""
        return {
            "error_code": self.error_code,
            "policy": self.policy.value,
            "component_name": self.component_name,
            "action": self.action or "execution",
            "repair_hint": self.repair_hint or "",
            "details": self.details or str(self),
        }


class MissingDependencyFailClosedError(MissingSemanticsError):
    """Exception raised when an operation is blocked by a FAIL_CLOSED missing semantics policy."""

    def __init__(
        self,
        component_name: str | None = None,
        *,
        action: str | None = None,
        repair_hint: str | None = None,
        details: str | None = None,
        error_code: str | None = None,
        contract: MissingSemanticsContract | None = None,
        detail: str | None = None,
    ) -> None:
        actual_comp = component_name or (str(contract.category) if contract else "unknown_component")
        actual_code = error_code or (contract.error_code if contract else f"ERR_MISSING_{actual_comp.upper()}")
        actual_hint = repair_hint or (contract.remediation_hint if contract else "")
        actual_details = details or detail or (contract.user_message if contract else None)

        msg = (
            f"[{actual_code}] [FAIL_CLOSED] Security-critical component '{actual_comp}' is unavailable "
            f"or uninitialized for action '{action or 'execution'}'. "
            "Execution is strictly blocked to prevent unisolated host fallback or security escape."
        )
        if actual_details:
            msg += f" Details: {actual_details}"
        if actual_hint:
            msg += f" (Hint: {actual_hint})"

        super().__init__(
            msg,
            component_name=actual_comp,
            policy=MissingSemanticsPolicy.FAIL_CLOSED,
            error_code=actual_code,
            action=action,
            repair_hint=actual_hint,
            details=actual_details,
        )
        self.contract = contract
        self.detail = actual_details


# Backward-compatible alias
MissingSemanticsBlockedError = MissingDependencyFailClosedError


class MissingDependencyFailFastError(MissingSemanticsError):
    """Exception raised when a mandatory boot/starter component is missing (FAIL_FAST)."""

    def __init__(
        self,
        component_name: str,
        *,
        action: str | None = None,
        repair_hint: str | None = None,
        details: str | None = None,
        error_code: str | None = None,
    ) -> None:
        actual_code = error_code or f"ERR_MISSING_{component_name.upper()}_BOOT"
        msg = (
            f"[{actual_code}] [FAIL_FAST] Mandatory system dependency '{component_name}' is missing. "
            "System boot/admission halted immediately."
        )
        if details:
            msg += f" Details: {details}"
        if repair_hint:
            msg += f" (Hint: {repair_hint})"

        super().__init__(
            msg,
            component_name=component_name,
            policy=MissingSemanticsPolicy.FAIL_FAST,
            error_code=actual_code,
            action=action,
            repair_hint=repair_hint,
            details=details,
        )


@dataclass(frozen=True, slots=True)
class MissingSemanticsDecision:
    """Outcome of evaluating capability availability against the contract matrix."""

    category: SemanticsCategory | str
    is_available: bool
    policy: MissingSemanticsPolicy
    action: str  # "PROCEED" | "BLOCKED" | "FALLBACK" | "ABORT"
    error_code: str | None = None
    reason: str | None = None


_DEFAULT_MISSING_SEMANTICS_MATRIX: dict[str, MissingSemanticsContract] = {
    SemanticsCategory.SANDBOX_ISOLATION.value: MissingSemanticsContract(
        category=SemanticsCategory.SANDBOX_ISOLATION,
        policy=MissingSemanticsPolicy.FAIL_CLOSED,
        error_code="ERR_MISSING_SANDBOX_ISOLATION",
        user_message="Sandbox container isolation provider is unavailable",
        remediation_hint="Ensure the Docker/Sandbox daemon is running or verify sandbox daemon connectivity. Bare-metal fallback is prohibited.",
        description="Containerized execution sandbox for shell and python runners",
    ),
    "sandbox": MissingSemanticsContract(
        category="sandbox",
        policy=MissingSemanticsPolicy.FAIL_CLOSED,
        error_code="ERR_MISSING_SANDBOX_ISOLATION",
        user_message="Sandbox container isolation provider is unavailable",
        remediation_hint="Ensure the Docker/Sandbox daemon is running or verify sandbox daemon connectivity. Bare-metal fallback is prohibited.",
        description="Containerized execution sandbox for shell and python runners",
    ),
    SemanticsCategory.CREDENTIAL_VAULT.value: MissingSemanticsContract(
        category=SemanticsCategory.CREDENTIAL_VAULT,
        policy=MissingSemanticsPolicy.FAIL_CLOSED,
        error_code="ERR_MISSING_REQUIRED_SECRET",
        user_message="Required credential or secret is missing from vault",
        remediation_hint="Configure the required secret in Agent Settings / Vault before invoking this tool.",
        description="Encrypted credential vault for secret token resolution",
    ),
    "credential_vault": MissingSemanticsContract(
        category="credential_vault",
        policy=MissingSemanticsPolicy.FAIL_CLOSED,
        error_code="ERR_MISSING_REQUIRED_SECRET",
        user_message="Required credential or secret is missing from vault",
        remediation_hint="Configure the required secret in Agent Settings / Vault before invoking this tool.",
        description="Encrypted credential vault for secret token resolution",
    ),
    SemanticsCategory.CORE_DATABASE.value: MissingSemanticsContract(
        category=SemanticsCategory.CORE_DATABASE,
        policy=MissingSemanticsPolicy.FAIL_FAST,
        error_code="ERR_MISSING_CORE_DATABASE",
        user_message="Core persistence storage is unreachable",
        remediation_hint="Check database connectivity and filesystem permissions.",
        description="Primary SQLite/PostgreSQL persistence engine",
    ),
    "primary_database": MissingSemanticsContract(
        category="primary_database",
        policy=MissingSemanticsPolicy.FAIL_FAST,
        error_code="ERR_MISSING_CORE_DATABASE",
        user_message="Core persistence storage is unreachable",
        remediation_hint="Check database connectivity and filesystem permissions.",
        description="Primary SQLite/PostgreSQL persistence engine",
    ),
    SemanticsCategory.SECURITY_REVIEWER.value: MissingSemanticsContract(
        category=SemanticsCategory.SECURITY_REVIEWER,
        policy=MissingSemanticsPolicy.FALLBACK,
        error_code="WARN_FALLBACK_DEFAULT_MODEL",
        user_message="Dedicated reviewer model is unavailable, falling back to primary model",
        remediation_hint="Configure a dedicated reviewer model in Security Settings for enhanced auditing.",
        description="Dedicated security reviewer model",
    ),
    "specialty_router": MissingSemanticsContract(
        category="specialty_router",
        policy=MissingSemanticsPolicy.FALLBACK,
        error_code="WARN_FALLBACK_BASE_MODEL",
        user_message="Specialty domain router is unavailable, falling back to base model",
        remediation_hint="Configure specialty domain routing models in settings.",
        description="Heuristic task specialty LLM domain router",
    ),
    "vision_multimodal": MissingSemanticsContract(
        category="vision_multimodal",
        policy=MissingSemanticsPolicy.FALLBACK,
        error_code="WARN_FALLBACK_VISION",
        user_message="Direct multimodal vision model is unavailable",
        remediation_hint="Configure a vision-capable fallback model in settings.",
        description="Direct multimodal image processing capability",
    ),
    SemanticsCategory.READONLY_CACHE.value: MissingSemanticsContract(
        category=SemanticsCategory.READONLY_CACHE,
        policy=MissingSemanticsPolicy.FALLBACK,
        error_code="WARN_FALLBACK_DIRECT_FETCH",
        user_message="Read-only cache service is missing, falling back to direct query",
        remediation_hint="Start local cache instance to accelerate performance.",
        description="In-memory read-only cache layer",
    ),
}


def register_missing_semantics_contract(contract: MissingSemanticsContract) -> None:
    """Register or override a capability missing semantics contract at runtime.

    Enables third-party plugins, custom MCP tools, and server extensions
    to declare their absence policies dynamically without modifying core source.
    """
    key = contract.category.value if isinstance(contract.category, SemanticsCategory) else str(contract.category)
    _DEFAULT_MISSING_SEMANTICS_MATRIX[key] = contract
    logger.info("Registered missing semantics contract for category '%s' with policy '%s'", key, contract.policy.value)


def get_missing_semantics_matrix() -> Mapping[str, MissingSemanticsContract]:
    """Retrieve the global SSOT missing semantics contract matrix."""
    return _DEFAULT_MISSING_SEMANTICS_MATRIX


def get_registered_contract(category_or_name: SemanticsCategory | str) -> MissingSemanticsContract | None:
    """Retrieve the declared contract for a capability category or component name."""
    key = category_or_name.value if isinstance(category_or_name, SemanticsCategory) else str(category_or_name)
    return _DEFAULT_MISSING_SEMANTICS_MATRIX.get(key)


def list_registered_contracts() -> list[MissingSemanticsContract]:
    """List all declared missing semantics contracts in the system."""
    return list(_DEFAULT_MISSING_SEMANTICS_MATRIX.values())


def evaluate_missing_capability(
    category: SemanticsCategory | str,
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
        MissingDependencyFailClosedError: If the capability is missing and policy is FAIL_CLOSED.
    """
    cat_key = category.value if isinstance(category, SemanticsCategory) else str(category)
    contract = _DEFAULT_MISSING_SEMANTICS_MATRIX.get(
        cat_key,
        MissingSemanticsContract(
            category=category,
            policy=MissingSemanticsPolicy.FAIL_CLOSED,
            error_code="ERR_UNKNOWN_MISSING_SEMANTICS",
            user_message=f"Unknown capability '{cat_key}' is unavailable",
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
        raise MissingDependencyFailClosedError(
            component_name=cat_key,
            action="evaluate_missing_capability",
            repair_hint=contract.remediation_hint,
            details=detail or contract.user_message,
            error_code=contract.error_code,
            contract=contract,
            detail=detail,
        )

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


def enforce_missing_semantics(
    policy: MissingSemanticsPolicy,
    component_name: str,
    *,
    guard_fn: Callable[..., bool | Awaitable[bool]] | None = None,
    action: str | None = None,
    repair_hint: str | None = None,
    fallback_fn: Callable[..., Any] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to enforce declared missing semantics policy on a function.

    Args:
        policy: The policy to enforce (FAIL_CLOSED, FAIL_FAST, FALLBACK).
        component_name: Name of the critical component being checked.
        guard_fn: Optional callable returning True if component is present/ready, False otherwise.
        action: Optional human-readable action name.
        repair_hint: Optional repair instruction.
        fallback_fn: Optional fallback function when policy == FALLBACK.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                if guard_fn is not None:
                    is_avail = guard_fn(*args, **kwargs)
                    if inspect.isawaitable(is_avail):
                        is_avail = await is_avail
                else:
                    is_avail = True

                if not is_avail:
                    if policy == MissingSemanticsPolicy.FAIL_CLOSED:
                        raise MissingDependencyFailClosedError(
                            component_name=component_name,
                            action=action or fn.__name__,
                            repair_hint=repair_hint,
                        )
                    if policy == MissingSemanticsPolicy.FAIL_FAST:
                        raise MissingDependencyFailFastError(
                            component_name=component_name,
                            action=action or fn.__name__,
                            repair_hint=repair_hint,
                        )
                    if policy == MissingSemanticsPolicy.FALLBACK:
                        if fallback_fn is not None:
                            logger.warning(
                                "[FALLBACK] Component '%s' unavailable for '%s', executing fallback",
                                component_name,
                                action or fn.__name__,
                            )
                            if inspect.iscoroutinefunction(fallback_fn):
                                return await fallback_fn(*args, **kwargs)
                            return fallback_fn(*args, **kwargs)
                        logger.warning(
                            "[FALLBACK] Component '%s' unavailable for '%s', returning None",
                            component_name,
                            action or fn.__name__,
                        )
                        return None  # type: ignore[return-value]
                return await fn(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if guard_fn is not None:
                is_avail = guard_fn(*args, **kwargs)
            else:
                is_avail = True

            if not is_avail:
                if policy == MissingSemanticsPolicy.FAIL_CLOSED:
                    raise MissingDependencyFailClosedError(
                        component_name=component_name,
                        action=action or fn.__name__,
                        repair_hint=repair_hint,
                    )
                if policy == MissingSemanticsPolicy.FAIL_FAST:
                    raise MissingDependencyFailFastError(
                        component_name=component_name,
                        action=action or fn.__name__,
                        repair_hint=repair_hint,
                    )
                if policy == MissingSemanticsPolicy.FALLBACK:
                    if fallback_fn is not None:
                        logger.warning(
                            "[FALLBACK] Component '%s' unavailable for '%s', executing fallback",
                            component_name,
                            action or fn.__name__,
                        )
                        return fallback_fn(*args, **kwargs)
                    logger.warning(
                        "[FALLBACK] Component '%s' unavailable for '%s', returning None",
                        component_name,
                        action or fn.__name__,
                    )
                    return None  # type: ignore[return-value]
            return fn(*args, **kwargs)

        return sync_wrapper

    return decorator
