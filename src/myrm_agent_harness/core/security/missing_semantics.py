"""Missing Semantics Contract — standardized policies for missing components.

[INPUT]
- types::MissingSemanticsPolicy (or defined here for zero dependencies)

[OUTPUT]
- MissingSemanticsPolicy: Enum (FAIL_CLOSED, FAIL_FAST, FALLBACK)
- MissingSemanticsError: Base security exception for missing dependency contracts
- MissingDependencyFailClosedError: Raised when a security-critical component is missing
- MissingDependencyFailFastError: Raised when a mandatory boot component is missing
- enforce_missing_semantics: Decorator/guard enforcing declared missing policy
- register_missing_semantics_contract: Registry hook for component semantics

[POS]
Foundational security contract module in core/security.
Establishes the three iron laws of missing semantics:
1. FAIL_CLOSED: Security boundaries (Sandbox, Secret Vault, Audit) MUST refuse execution. No silent bare fallback.
2. FAIL_FAST: Mandatory infrastructure (DB, Bus) MUST abort immediately at boot/admission.
3. FALLBACK: Non-critical enhancements (Vision fallback, Specialty LLM) MAY degrade with explicit telemetry.
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


class MissingSemanticsPolicy(StrEnum):
    """The 3 standardized missing semantics policies."""

    FAIL_CLOSED = "fail_closed"
    FAIL_FAST = "fail_fast"
    FALLBACK = "fallback"


class MissingSemanticsError(Exception):
    """Base exception for all missing semantics violations."""

    def __init__(
        self,
        message: str,
        *,
        component_name: str,
        policy: MissingSemanticsPolicy,
        action: str | None = None,
        repair_hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.component_name = component_name
        self.policy = policy
        self.action = action
        self.repair_hint = repair_hint


class MissingDependencyFailClosedError(MissingSemanticsError):
    """Raised when a security-boundary component is missing (FAIL_CLOSED).

    Strictly prohibits silent fallback to insecure or host-bare execution.
    """

    def __init__(
        self,
        component_name: str,
        *,
        action: str | None = None,
        repair_hint: str | None = None,
        details: str | None = None,
    ) -> None:
        msg = (
            f"[FAIL_CLOSED] Security-critical component '{component_name}' is unavailable "
            f"or uninitialized for action '{action or 'execution'}'. "
            "Execution is strictly blocked to prevent unisolated host fallback or security escape."
        )
        if details:
            msg += f" Details: {details}"
        if repair_hint:
            msg += f" (Repair: {repair_hint})"
        super().__init__(
            msg,
            component_name=component_name,
            policy=MissingSemanticsPolicy.FAIL_CLOSED,
            action=action,
            repair_hint=repair_hint,
        )


class MissingDependencyFailFastError(MissingSemanticsError):
    """Raised when a mandatory boot/starter component is missing (FAIL_FAST)."""

    def __init__(
        self,
        component_name: str,
        *,
        action: str | None = None,
        repair_hint: str | None = None,
    ) -> None:
        msg = (
            f"[FAIL_FAST] Mandatory system dependency '{component_name}' is missing. "
            "System boot/admission halted immediately."
        )
        if repair_hint:
            msg += f" (Repair: {repair_hint})"
        super().__init__(
            msg,
            component_name=component_name,
            policy=MissingSemanticsPolicy.FAIL_FAST,
            action=action,
            repair_hint=repair_hint,
        )


@dataclass(frozen=True, slots=True)
class MissingSemanticsContract:
    """Declared missing semantics contract for a system component."""

    component_name: str
    policy: MissingSemanticsPolicy
    description: str
    repair_hint: str | None = None


# Global immutable contract registry
_CONTRACT_REGISTRY: dict[str, MissingSemanticsContract] = {
    "sandbox": MissingSemanticsContract(
        component_name="sandbox",
        policy=MissingSemanticsPolicy.FAIL_CLOSED,
        description="Containerized execution sandbox for shell and python runners",
        repair_hint="Ensure container daemon (Docker/Podman) is running or bind a valid sandbox executor.",
    ),
    "credential_vault": MissingSemanticsContract(
        component_name="credential_vault",
        policy=MissingSemanticsPolicy.FAIL_CLOSED,
        description="Encrypted credential vault for secret token resolution",
        repair_hint="Initialize database secret backend with valid AES-256-GCM master key.",
    ),
    "audit_gate": MissingSemanticsContract(
        component_name="audit_gate",
        policy=MissingSemanticsPolicy.FAIL_CLOSED,
        description="Append-only security audit log pipeline",
        repair_hint="Verify disk write permissions on security audit event log directory.",
    ),
    "primary_database": MissingSemanticsContract(
        component_name="primary_database",
        policy=MissingSemanticsPolicy.FAIL_FAST,
        description="Primary SQLite/PostgreSQL persistence engine",
        repair_hint="Check database connection string and migration schema status.",
    ),
    "vision_multimodal": MissingSemanticsContract(
        component_name="vision_multimodal",
        policy=MissingSemanticsPolicy.FALLBACK,
        description="Direct multimodal image processing capability",
        repair_hint="Configure a vision-capable fallback model in settings.",
    ),
    "specialty_router": MissingSemanticsContract(
        component_name="specialty_router",
        policy=MissingSemanticsPolicy.FALLBACK,
        description="Heuristic task specialty LLM domain router",
        repair_hint="Fallback to default base model automatically.",
    ),
}


def get_registered_contract(component_name: str) -> MissingSemanticsContract | None:
    """Retrieve the declared contract for a component name."""
    return _CONTRACT_REGISTRY.get(component_name)


def list_registered_contracts() -> list[MissingSemanticsContract]:
    """List all declared missing semantics contracts in the system."""
    return list(_CONTRACT_REGISTRY.values())


def enforce_missing_semantics(
    policy: MissingSemanticsPolicy,
    component_name: str,
    *,
    guard_fn: Callable[..., bool],
    action: str | None = None,
    repair_hint: str | None = None,
    fallback_fn: Callable[..., Any] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to enforce declared missing semantics policy on a function.

    Args:
        policy: The policy to enforce (FAIL_CLOSED, FAIL_FAST, FALLBACK).
        component_name: Name of the critical component being checked.
        guard_fn: Callable returning True if component is present/ready, False otherwise.
        action: Optional human-readable action name.
        repair_hint: Optional repair instruction.
        fallback_fn: Optional fallback function when policy == FALLBACK.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                is_available = guard_fn(*args, **kwargs) if not inspect.iscoroutinefunction(guard_fn) else await guard_fn(*args, **kwargs)
                if not is_available:
                    if policy == MissingSemanticsPolicy.FAIL_CLOSED:
                        raise MissingDependencyFailClosedError(
                            component_name,
                            action=action or fn.__name__,
                            repair_hint=repair_hint,
                        )
                    if policy == MissingSemanticsPolicy.FAIL_FAST:
                        raise MissingDependencyFailFastError(
                            component_name,
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
            is_available = guard_fn(*args, **kwargs)
            if not is_available:
                if policy == MissingSemanticsPolicy.FAIL_CLOSED:
                    raise MissingDependencyFailClosedError(
                        component_name,
                        action=action or fn.__name__,
                        repair_hint=repair_hint,
                    )
                if policy == MissingSemanticsPolicy.FAIL_FAST:
                    raise MissingDependencyFailFastError(
                        component_name,
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
