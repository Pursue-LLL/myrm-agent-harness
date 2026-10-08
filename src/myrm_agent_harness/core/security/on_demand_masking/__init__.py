"""On-demand credential masking module exports."""

from myrm_agent_harness.core.security.on_demand_masking.masker import (
    MultiEncodingSecretMasker,
)
from myrm_agent_harness.core.security.on_demand_masking.resolver import (
    CredentialConflictError,
    OnDemandCredentialResolver,
)
from myrm_agent_harness.core.security.on_demand_masking.types import (
    CredentialField,
    MaskedExecutionError,
    MaskedExecutionResult,
    MaterializedCredential,
)

__all__ = [
    "CredentialConflictError",
    "CredentialField",
    "MaskedExecutionError",
    "MaskedExecutionResult",
    "MaterializedCredential",
    "MultiEncodingSecretMasker",
    "OnDemandCredentialResolver",
]
