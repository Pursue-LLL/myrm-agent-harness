"""Profile audit scoring algorithm.

[INPUT]
- Sequence of AuditFinding from all checkers

[OUTPUT]
- score: int (0-100, higher = safer)
- risk_level: RiskLevel
- finding_counts: dict[str, int]

[POS]
Deterministic scoring: starts at 100, deducts points per finding based on severity.
Maps final score to qualitative RiskLevel. Transparent and predictable.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.profile_audit.types import (
    AuditFinding,
    AuditSeverity,
    RiskLevel,
)

_SEVERITY_DEDUCTION: dict[AuditSeverity, int] = {
    AuditSeverity.INFO: 0,
    AuditSeverity.LOW: 3,
    AuditSeverity.MEDIUM: 8,
    AuditSeverity.HIGH: 15,
    AuditSeverity.CRITICAL: 30,
}

_SCORE_THRESHOLDS: tuple[tuple[int, RiskLevel], ...] = (
    (90, RiskLevel.SAFE),
    (70, RiskLevel.LOW),
    (50, RiskLevel.MEDIUM),
    (30, RiskLevel.HIGH),
)


def compute_score(findings: tuple[AuditFinding, ...]) -> tuple[int, RiskLevel, dict[str, int]]:
    """Compute aggregate score, risk level, and finding counts from findings."""
    total_deduction = 0
    counts: dict[str, int] = {}

    for finding in findings:
        severity_name = finding.severity.name.lower()
        counts[severity_name] = counts.get(severity_name, 0) + 1
        total_deduction += _SEVERITY_DEDUCTION.get(finding.severity, 0)

    score = max(0, 100 - total_deduction)

    risk_level = RiskLevel.CRITICAL
    for threshold, level in _SCORE_THRESHOLDS:
        if score >= threshold:
            risk_level = level
            break

    return score, risk_level, counts
