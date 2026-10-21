"""Cron risk checker — evaluates unattended scheduled task risks.

[INPUT]
- ProfileAuditInput.cron_jobs

[OUTPUT]
- Findings for cron jobs with dangerous tools running without human oversight

[POS]
Cron jobs run without human-in-the-loop. If they have access to dangerous
tools (shell, file_write), they represent a higher risk than interactive
sessions where a human can review actions.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.profile_audit.checkers.base import BaseChecker
from myrm_agent_harness.agent.security.profile_audit.types import (
    AuditFinding,
    AuditSeverity,
    ProfileAuditInput,
)


class CronRiskChecker(BaseChecker):
    """Evaluates risks from unattended cron job executions."""

    def check(self, audit_input: ProfileAuditInput) -> list[AuditFinding]:
        findings: list[AuditFinding] = []

        for job in audit_input.cron_jobs:
            if job.has_dangerous_tools:
                findings.append(
                    AuditFinding(
                        checker="cron_risk",
                        severity=AuditSeverity.HIGH,
                        title=f"Cron job '{job.job_id}' runs with dangerous tools",
                        description=f"Schedule: {job.schedule}. Unattended execution with high-privilege tools.",
                        recommendation="Dangerous tools require explicit capability declaration or YOLO mode in cron jobs (fail-closed policy). Configure capability fence in task settings.",
                        source_location=f"cron_jobs[{job.job_id}].has_dangerous_tools",
                    )
                )

        if len(audit_input.cron_jobs) > 5:
            findings.append(
                AuditFinding(
                    checker="cron_risk",
                    severity=AuditSeverity.LOW,
                    title=f"Agent has {len(audit_input.cron_jobs)} scheduled tasks",
                    description="Large number of cron jobs increases unattended execution surface.",
                    recommendation="Review and consolidate scheduled tasks; remove unused ones.",
                    source_location=f"cron_jobs (count: {len(audit_input.cron_jobs)})",
                )
            )

        return findings
