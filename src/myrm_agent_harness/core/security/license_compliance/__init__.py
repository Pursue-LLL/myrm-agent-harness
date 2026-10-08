"""Public API for Third-Party Asset License Compliance & Copyleft Gating.

[INPUT]
- Package import declarations.

[OUTPUT]
- Exported classes, enums, exceptions, and registry helpers.

[POS]
- Harness core security module package entrypoint.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.license_compliance.gating import LicenseComplianceGate
from myrm_agent_harness.core.security.license_compliance.inventory import LicenseInventoryLedger
from myrm_agent_harness.core.security.license_compliance.spdx_registry import SpdxLicenseRegistry
from myrm_agent_harness.core.security.license_compliance.types import (
    AssetLicenseDescriptor,
    CopyleftBlockedError,
    DeploymentEnvironment,
    LicenseComplianceError,
    LicenseComplianceVerdict,
    LicenseGateDecision,
    LicenseInventorySummary,
    LicenseMetadata,
    LicenseRiskTier,
    UnknownLicenseBlockedError,
)

__all__ = [
    "AssetLicenseDescriptor",
    "CopyleftBlockedError",
    "DeploymentEnvironment",
    "LicenseComplianceError",
    "LicenseComplianceGate",
    "LicenseComplianceVerdict",
    "LicenseGateDecision",
    "LicenseInventoryLedger",
    "LicenseInventorySummary",
    "LicenseMetadata",
    "LicenseRiskTier",
    "SpdxLicenseRegistry",
    "UnknownLicenseBlockedError",
]
