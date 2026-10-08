"""Domain types and models for Third-Party Asset License Compliance & Copyleft Gating.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing SPDX license metadata, risk tiering,
  deployment-aware compliance verdicts, and inventory ledger items.

[POS]
- Harness core domain models ensuring third-party skills, MCP tools, and packages
  comply with intellectual property and copyleft restrictions across local and cloud tiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class LicenseRiskTier(StrEnum):
    """Intellectual property and copyleft risk classification."""

    PERMISSIVE = "PERMISSIVE"
    WEAK_COPYLEFT = "WEAK_COPYLEFT"
    STRONG_COPYLEFT = "STRONG_COPYLEFT"
    PROPRIETARY = "PROPRIETARY"
    UNKNOWN = "UNKNOWN"


class DeploymentEnvironment(StrEnum):
    """Runtime deployment context dictating gating strictness."""

    LOCAL_DESKTOP = "LOCAL_DESKTOP"
    CLOUD_COMMERCIAL = "CLOUD_COMMERCIAL"


class LicenseGateDecision(StrEnum):
    """Outcome of license compliance gate evaluation."""

    ALLOWED = "ALLOWED"
    WARNING_PROCEED = "WARNING_PROCEED"
    BLOCKED_COPYLEFT_RESTRICTION = "BLOCKED_COPYLEFT_RESTRICTION"
    BLOCKED_UNKNOWN_LICENSE = "BLOCKED_UNKNOWN_LICENSE"


@dataclass(frozen=True)
class LicenseMetadata:
    """SPDX-normalized license metadata and legal risk attributes."""

    spdx_id: str
    raw_name: str
    risk_tier: LicenseRiskTier
    is_copyleft: bool
    commercial_friendly: bool
    description: str = ""


@dataclass(frozen=True)
class AssetLicenseDescriptor:
    """Declared or detected license specification for a third-party asset."""

    asset_id: str
    asset_type: str  # e.g., "skill", "mcp_server", "python_package", "npm_package"
    detected_license: LicenseMetadata
    license_file_path: str | None = None
    package_url: str | None = None


@dataclass(frozen=True)
class LicenseComplianceVerdict:
    """Compliance evaluation verdict for an asset under specific deployment constraints."""

    decision: LicenseGateDecision
    asset_id: str
    detected_license: LicenseMetadata
    environment: DeploymentEnvironment
    reason: str
    can_override: bool = False
    audit_notes: str = ""


@dataclass(frozen=True)
class LicenseInventorySummary:
    """Aggregated compliance inventory across all installed third-party assets."""

    total_assets: int
    permissive_count: int
    weak_copyleft_count: int
    strong_copyleft_count: int
    unknown_count: int
    has_blocking_violations: bool
    assets: tuple[AssetLicenseDescriptor, ...] = field(default_factory=tuple)


class LicenseComplianceError(Exception):
    """Base exception for license compliance and gating failures."""


class CopyleftBlockedError(LicenseComplianceError):
    """Raised when a strong copyleft asset is blocked in commercial cloud deployment."""


class UnknownLicenseBlockedError(LicenseComplianceError):
    """Raised when an unidentifiable license is blocked under strict compliance policies."""
