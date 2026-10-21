"""Skill aggregate checker — aggregates skill scan results into profile findings.

[INPUT]
- ProfileAuditInput.skill_scans

[OUTPUT]
- Findings for skills with poor security scores or dangerous trust recommendations

[POS]
Skills are scanned individually at import time. This checker aggregates those
results at the profile level, flagging any skill that was recommended as
UNTRUSTED or REJECT, or that has critical/high findings.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.profile_audit.checkers.base import BaseChecker
from myrm_agent_harness.agent.security.profile_audit.types import (
    AuditFinding,
    AuditSeverity,
    ProfileAuditInput,
)

_DANGEROUS_RECOMMENDATIONS = frozenset({"reject", "untrusted"})


class SkillAggregateChecker(BaseChecker):
    """Aggregates individual skill scan summaries into profile-level findings."""

    def check(self, audit_input: ProfileAuditInput) -> list[AuditFinding]:
        findings: list[AuditFinding] = []

        for skill in audit_input.skill_scans:
            if skill.trust_recommendation in _DANGEROUS_RECOMMENDATIONS:
                severity = AuditSeverity.CRITICAL if skill.trust_recommendation == "reject" else AuditSeverity.HIGH
                findings.append(
                    AuditFinding(
                        checker="skill_aggregate",
                        severity=severity,
                        title=f"Skill '{skill.skill_name}' flagged as {skill.trust_recommendation}",
                        description=f"Security scan scored {skill.score}/100 with recommendation: {skill.trust_recommendation}.",
                        recommendation="Remove or replace this skill, or review its content for security threats.",
                        source_location=f"skill_scans[{skill.skill_id}].trust_recommendation",
                    )
                )
            elif skill.score < 60:
                findings.append(
                    AuditFinding(
                        checker="skill_aggregate",
                        severity=AuditSeverity.MEDIUM,
                        title=f"Skill '{skill.skill_name}' has low security score ({skill.score}/100)",
                        description=f"Finding counts: {skill.finding_counts}",
                        recommendation="Review skill content and consider alternative skills with better security posture.",
                        source_location=f"skill_scans[{skill.skill_id}].score",
                    )
                )

        return findings
