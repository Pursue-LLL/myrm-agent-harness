"""Profile audit engine — orchestrates checkers and produces final result.

[INPUT]
- ProfileAuditInput DTO

[OUTPUT]
- ProfileAuditResult (score, risk_level, findings)

[POS]
Entry point for the profile audit. Instantiates all registered checkers,
runs them against the input, aggregates findings, and delegates scoring.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.profile_audit.checkers.base import BaseChecker
from myrm_agent_harness.agent.security.profile_audit.checkers.cron_risk import CronRiskChecker
from myrm_agent_harness.agent.security.profile_audit.checkers.mcp_auth import MCPAuthChecker
from myrm_agent_harness.agent.security.profile_audit.checkers.policy_gap import PolicyGapChecker
from myrm_agent_harness.agent.security.profile_audit.checkers.skill_aggregate import SkillAggregateChecker
from myrm_agent_harness.agent.security.profile_audit.checkers.subagent_risk import SubagentRiskChecker
from myrm_agent_harness.agent.security.profile_audit.checkers.tool_exposure import ToolExposureChecker
from myrm_agent_harness.agent.security.profile_audit.scoring import compute_score
from myrm_agent_harness.agent.security.profile_audit.types import (
    AuditFinding,
    ProfileAuditInput,
    ProfileAuditResult,
)

_CHECKERS: tuple[type[BaseChecker], ...] = (
    ToolExposureChecker,
    MCPAuthChecker,
    SkillAggregateChecker,
    SubagentRiskChecker,
    CronRiskChecker,
    PolicyGapChecker,
)


def run_profile_audit(audit_input: ProfileAuditInput) -> ProfileAuditResult:
    """Run all checkers against the profile and produce an aggregate result."""
    all_findings: list[AuditFinding] = []

    for checker_cls in _CHECKERS:
        checker = checker_cls()
        findings = checker.check(audit_input)
        all_findings.extend(findings)

    findings_tuple = tuple(sorted(all_findings, key=lambda f: f.severity, reverse=True))
    score, risk_level, finding_counts = compute_score(findings_tuple)

    return ProfileAuditResult(
        score=score,
        risk_level=risk_level,
        findings=findings_tuple,
        total_findings=len(findings_tuple),
        finding_counts=finding_counts,
    )
