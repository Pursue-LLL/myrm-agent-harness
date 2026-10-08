"""Secret broker package providing credential isolation and zero-context replacement.

[INPUT]
- None.

[OUTPUT]
- Exports:
    - BoundSecretHandle, AtomicOperationGrant, SecretInjectionResult, GrantStatus
    - SecretBrokerError, EgressHostMismatchError, AtomicGrantInvalidatedError
    - EgressBoundSecretVault
    - EgressSecretInterceptor
    - AtomicOperationGrantManager

[POS]
- Harness core security subsystem inspired by OpenClaw 2.0 (credentials-vault & secret-broker).
"""

from __future__ import annotations

from myrm_agent_harness.core.security.secret_broker.atomic_grant import (
    AtomicOperationGrantManager,
)
from myrm_agent_harness.core.security.secret_broker.interceptor import (
    EgressSecretInterceptor,
)
from myrm_agent_harness.core.security.secret_broker.types import (
    AtomicGrantInvalidatedError,
    AtomicOperationGrant,
    BoundSecretHandle,
    EgressHostMismatchError,
    GrantStatus,
    SecretBrokerError,
    SecretInjectionResult,
)
from myrm_agent_harness.core.security.secret_broker.vault import EgressBoundSecretVault

__all__ = [
    "AtomicGrantInvalidatedError",
    "AtomicOperationGrant",
    "AtomicOperationGrantManager",
    "BoundSecretHandle",
    "EgressBoundSecretVault",
    "EgressHostMismatchError",
    "EgressSecretInterceptor",
    "GrantStatus",
    "SecretBrokerError",
    "SecretInjectionResult",
]
