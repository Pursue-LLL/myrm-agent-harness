"""Air-Gapped Sovereign Intelligence and Zero-Egress Compliance module.

[INPUT]
None.

[OUTPUT]
- EgressControlTier, EgressAttemptRecord, ZeroEgressAssertionResult, OfflineModelMetadata
- AirGappedViolationError, ExternalEgressBlockedError
- ZeroEgressGuard
- OfflineModelRegistry

[POS]
Harness core security subsystem for strict zero-egress enforcement and air-gapped sovereign execution.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.air_gapped.offline_registry import (
    OfflineModelRegistry,
)
from myrm_agent_harness.core.security.air_gapped.types import (
    AirGappedViolationError,
    EgressAttemptRecord,
    EgressControlTier,
    ExternalEgressBlockedError,
    OfflineModelMetadata,
    ZeroEgressAssertionResult,
)
from myrm_agent_harness.core.security.air_gapped.zero_egress_guard import (
    ZeroEgressGuard,
)

__all__ = [
    "EgressControlTier",
    "EgressAttemptRecord",
    "ZeroEgressAssertionResult",
    "OfflineModelMetadata",
    "AirGappedViolationError",
    "ExternalEgressBlockedError",
    "ZeroEgressGuard",
    "OfflineModelRegistry",
]
