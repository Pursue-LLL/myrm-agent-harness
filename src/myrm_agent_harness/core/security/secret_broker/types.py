"""Type definitions for Mechanical Credential Isolation and Zero-Context Secret Replacement.

[INPUT]
None.

[OUTPUT]
- BoundSecretHandle, AtomicOperationGrant, SecretInjectionResult
- SecretBrokerError, EgressHostMismatchError, AtomicGrantInvalidatedError

[POS]
Harness core security subsystem inspired by OpenClaw 2.0 (Secret Broker & Credentials Vault).
Prevents secret keys from ever entering model prompt context and enforces egress-bound proxy injection.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class GrantStatus(StrEnum):
    """Lifecycle status of an atomic one-shot operation grant."""

    PENDING = "pending"
    GRANTED = "granted"
    USED = "used"
    REVOKED = "revoked"
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True)
class BoundSecretHandle:
    """Opaque reference handle representing a credential securely bound to a target host."""

    handle_id: str
    secret_name: str
    placeholder: str
    allowed_host: str
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class AtomicOperationGrant:
    """One-shot operation grant bound to exact payload hash."""

    grant_id: str
    operation_name: str
    payload_hash: str
    status: GrantStatus = GrantStatus.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 180.0)


@dataclass(frozen=True, slots=True)
class SecretInjectionResult:
    """Telemetry report after outbound secret resolution."""

    resolved_content: str
    replacements_count: int
    target_host: str
    authorized: bool


class SecretBrokerError(Exception):
    """Base exception for secret broker and credential isolation operations."""


class EgressHostMismatchError(SecretBrokerError):
    """Raised when an outbound request attempts to use a credential on an unauthorized host."""

    def __init__(self, handle_id: str, allowed_host: str, attempted_host: str) -> None:
        super().__init__(
            f"Egress host mismatch for handle '{handle_id}': Credential is bound to '{allowed_host}', "
            f"but outbound request was targeted at '{attempted_host}'."
        )
        self.handle_id = handle_id
        self.allowed_host = allowed_host
        self.attempted_host = attempted_host


class AtomicGrantInvalidatedError(SecretBrokerError):
    """Raised when an operation grant is rejected, altered, or already consumed."""

    def __init__(self, grant_id: str, reason: str) -> None:
        super().__init__(f"Atomic grant '{grant_id}' invalid: {reason}")
        self.grant_id = grant_id
        self.reason = reason
