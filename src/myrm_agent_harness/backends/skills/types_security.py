"""Security scan summary types for API and frontend exposure.

[INPUT]
- (none)

[OUTPUT]
- SecurityFindingDetail: single finding (threat_type/severity/description)
- SecurityScanSummary: aggregate scan result with score and findings

[POS]
Security scan result types populated at skill load/save time for API visualization.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SecurityFindingDetail:
    """A single security finding for API/frontend consumption.

    Simplified version of ScanFinding (no line_number, severity as str).
    """

    threat_type: str
    severity: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {
            "threat_type": self.threat_type,
            "severity": self.severity,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class SecurityScanSummary:
    """Security scan summary for API exposure and frontend visualization.

    Score is consistent with trust_recommendation: the recommendation
    determines the score band, and deductions refine within that band.
    """

    score: int
    """0-100 security score. Higher is safer."""

    trust_recommendation: str
    """One of: trusted, installed, untrusted, reject."""

    finding_counts: dict[str, int] = field(default_factory=dict)
    """Finding counts by severity: {critical: N, high: N, medium: N, low: N}."""

    total_findings: int = 0
    """Total number of security findings."""

    findings: tuple[SecurityFindingDetail, ...] = ()
    """Individual findings with threat_type, severity, and description."""

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "trust_recommendation": self.trust_recommendation,
            "finding_counts": self.finding_counts,
            "total_findings": self.total_findings,
            "findings": [f.to_dict() for f in self.findings],
        }
