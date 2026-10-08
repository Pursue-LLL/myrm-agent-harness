"""Domain types and models for Security Audit Explicit Coverage & Replayable Repair Bundles.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing application models, coverage scopes,
  audit findings, independent challenge reviews, and replayable repair bundles.

[POS]
- Harness core domain models based on gstack CSO audit paradigms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CoverageCategory(StrEnum):
    """Categories evaluated during application security audit."""

    AUTH_ACCESS_CONTROL = "AUTH_ACCESS_CONTROL"
    INPUT_VALIDATION_INJECTION = "INPUT_VALIDATION_INJECTION"
    DATA_EXFILTRATION_PRIVACY = "DATA_EXFILTRATION_PRIVACY"
    DEPENDENCY_SUPPLY_CHAIN = "DEPENDENCY_SUPPLY_CHAIN"
    SECRET_LEAKAGE = "SECRET_LEAKAGE"
    CONCURRENCY_STATE_INTEGRITY = "CONCURRENCY_STATE_INTEGRITY"


class CoverageStatus(StrEnum):
    """Explicit disclosure state of audit inspection for a specific category."""

    COVERED = "COVERED"
    PARTIALLY_COVERED = "PARTIALLY_COVERED"
    UNCOVERED_EXCLUDED = "UNCOVERED_EXCLUDED"
    UNCOVERED_UNSUPPORTED = "UNCOVERED_UNSUPPORTED"


class VerificationTier(StrEnum):
    """Honest evidence tier distinguishing self-assertion from independent witness."""

    SELF_REPORTED = "SELF_REPORTED"
    TESTED = "TESTED"


class FindingSeverity(StrEnum):
    """Severity rating for security audit findings."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class ChallengeVerdict(StrEnum):
    """Outcome of adversarial independent challenge review."""

    UNCHALLENGED = "UNCHALLENGED"
    CHALLENGED_CONFIRMED = "CHALLENGED_CONFIRMED"
    CHALLENGED_REFUTED = "CHALLENGED_REFUTED"


@dataclass(frozen=True)
class CoverageScopeItem:
    """Explicit disclosure of coverage depth for a specific security dimension."""

    category: CoverageCategory
    status: CoverageStatus
    audit_surface: str
    coverage_percentage: float
    uncovered_reason: str | None = None


@dataclass(frozen=True)
class ApplicationModel:
    """Declared boundary model of the target software application."""

    name: str
    tech_stack: tuple[str, ...]
    entrypoints: tuple[str, ...]
    trust_boundaries: tuple[str, ...]
    data_flows: tuple[str, ...]
    supported_finding_categories: tuple[str, ...]


@dataclass(frozen=True)
class AuditFinding:
    """Confirmed security finding supported by the application model."""

    finding_id: str
    category: str
    severity: FindingSeverity
    title: str
    description: str
    application_model_ref: str
    evidence: str
    challenge_status: ChallengeVerdict = ChallengeVerdict.UNCHALLENGED
    challenge_notes: str = ""
    verification_tier: VerificationTier = VerificationTier.SELF_REPORTED


@dataclass(frozen=True)
class RepairPatch:
    """Atomic file diff patch within a replayable repair bundle."""

    file_path: str
    target_checksum: str
    diff_content: str
    replay_command: str


@dataclass(frozen=True)
class ReplayableRepairBundle:
    """Self-contained verifiable bundle of patches and replay validation steps."""

    bundle_id: str
    finding_id: str
    patches: tuple[RepairPatch, ...]
    replay_script: str
    checksum: str
    is_verified: bool = False


@dataclass(frozen=True)
class ExplicitAuditCoverageReport:
    """Comprehensive audit report disclosing explicit coverage, challenged findings, and repair bundles."""

    audit_id: str
    application_model: ApplicationModel
    scopes: tuple[CoverageScopeItem, ...]
    findings: tuple[AuditFinding, ...] = field(default_factory=tuple)
    repair_bundles: tuple[ReplayableRepairBundle, ...] = field(default_factory=tuple)
    overall_coverage_percentage: float = 0.0


class AuditCoverageError(Exception):
    """Base exception for audit coverage and repair bundle operations."""


class UnsupportedFindingError(AuditCoverageError):
    """Raised when a finding asserts flaws outside the application model boundaries."""


class RepairBundleVerificationError(AuditCoverageError):
    """Raised when repair bundle fails deterministic replay verification."""
