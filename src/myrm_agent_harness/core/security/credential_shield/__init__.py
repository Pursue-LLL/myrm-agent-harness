"""Public API for Credential Stdin Pipelining & Process Leakage Shield Suite.

[INPUT]
- Package import declarations.

[OUTPUT]
- Exported classes, enums, exceptions, and pipelining engines.

[POS]
- Harness core security module package entrypoint.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.credential_shield.inspector import (
    CommandLineCredentialInspector,
)
from myrm_agent_harness.core.security.credential_shield.pipeliner import (
    CredentialStdinPipeliningEngine,
)
from myrm_agent_harness.core.security.credential_shield.types import (
    CredentialPipeliningError,
    CredentialTransportMode,
    LeakageRiskLevel,
    PipelinedCommandSpec,
    ProcessLeakageAnalysis,
    ProcessLeakageViolationError,
)
from myrm_agent_harness.core.security.credential_shield.zeroizer import (
    EphemeralCredentialZeroizer,
)

__all__ = [
    "CommandLineCredentialInspector",
    "CredentialPipeliningError",
    "CredentialStdinPipeliningEngine",
    "CredentialTransportMode",
    "EphemeralCredentialZeroizer",
    "LeakageRiskLevel",
    "PipelinedCommandSpec",
    "ProcessLeakageAnalysis",
    "ProcessLeakageViolationError",
]
