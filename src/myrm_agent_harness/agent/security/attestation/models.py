"""Data models for runtime environment and connection integrity attestation suite.

[POS]
Immutable contracts defining vector categories, check results,
and comprehensive environment attestation reports.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class VectorCategory(StrEnum):
    """Classification of attestation inspection vectors."""

    HOST_ISOLATION = "host_isolation"
    MOUNT_BOUNDARY = "mount_boundary"
    BINARY_INTEGRITY = "binary_integrity"
    OUTBOUND_TLS = "outbound_tls"


class AttestationSeverity(StrEnum):
    """Severity classification when a vector probe encounters an anomaly."""

    CRITICAL = "critical"  # Triggers hard-break shutdown
    WARNING = "warning"    # Logged in report but allows restricted execution
    INFO = "info"


class AttestationFailedHardBreakError(Exception):
    """Raised when one or more critical security vectors fail attestation."""

    def __init__(self, message: str, failed_vectors: list[str]) -> None:
        super().__init__(f"Runtime Attestation Hard-Break: {message} (Failed vectors: {', '.join(failed_vectors)})")
        self.failed_vectors = failed_vectors


@dataclass(frozen=True, slots=True)
class VectorCheckResult:
    """Individual result of an attestation vector inspection probe."""

    vector: VectorCategory
    target: str
    is_valid: bool
    severity: AttestationSeverity = AttestationSeverity.CRITICAL
    expected_digest: str | None = None
    actual_digest: str | None = None
    details: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Convert vector check result to dictionary."""
        return {
            "vector": self.vector.value,
            "target": self.target,
            "is_valid": self.is_valid,
            "severity": self.severity.value,
            "expected_digest": self.expected_digest,
            "actual_digest": self.actual_digest,
            "details": self.details,
            "error_message": self.error_message,
        }


@dataclass(frozen=True, slots=True)
class EnvironmentAttestationReport:
    """Complete all-vector attestation report certifying runtime trustworthiness."""

    attestation_id: str
    overall_passed: bool
    checked_at: float = field(default_factory=time.time)
    vector_results: tuple[VectorCheckResult, ...] = field(default_factory=tuple)
    host_fingerprint: str = ""
    summary: str = ""

    @property
    def failed_critical_vectors(self) -> list[VectorCheckResult]:
        """Filter results for failed critical checks."""
        return [
            r for r in self.vector_results
            if not r.is_valid and r.severity == AttestationSeverity.CRITICAL
        ]

    def to_dict(self) -> dict[str, object]:
        """Serialize report to dictionary for API and UI consumption."""
        return {
            "attestation_id": self.attestation_id,
            "overall_passed": self.overall_passed,
            "checked_at": self.checked_at,
            "host_fingerprint": self.host_fingerprint,
            "summary": self.summary,
            "vector_results": [r.to_dict() for r in self.vector_results],
        }
