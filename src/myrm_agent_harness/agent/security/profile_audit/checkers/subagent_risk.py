"""Sub-agent risk checker — evaluates recursive delegation risks.

[INPUT]
- ProfileAuditInput.subagents

[OUTPUT]
- Findings for sub-agent chains that amplify privilege or create uncontrolled delegation

[POS]
Sub-agents inherit or expand the parent's capabilities. Deep chains or
sub-agents with their own MCPs/sub-agents create privilege amplification
risks that are hard to audit manually.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.profile_audit.checkers.base import BaseChecker
from myrm_agent_harness.agent.security.profile_audit.types import (
    AuditFinding,
    AuditSeverity,
    ProfileAuditInput,
)


class SubagentRiskChecker(BaseChecker):
    """Evaluates privilege amplification risks from sub-agent bindings."""

    def check(self, audit_input: ProfileAuditInput) -> list[AuditFinding]:
        findings: list[AuditFinding] = []

        if not audit_input.subagents:
            return findings

        for sub in audit_input.subagents:
            if sub.has_own_subagents:
                findings.append(
                    AuditFinding(
                        checker="subagent_risk",
                        severity=AuditSeverity.HIGH,
                        title=f"Sub-agent '{sub.agent_name}' has nested sub-agents",
                        description="Multi-level delegation chain creates unauditable privilege paths.",
                        recommendation="Flatten delegation hierarchy or add explicit security policies to each level.",
                        source_location=f"subagents[{sub.agent_id}].has_own_subagents",
                    )
                )

            if sub.has_own_mcps and sub.has_own_tools:
                findings.append(
                    AuditFinding(
                        checker="subagent_risk",
                        severity=AuditSeverity.MEDIUM,
                        title=f"Sub-agent '{sub.agent_name}' has independent tools and MCPs",
                        description="Sub-agent with its own tools and MCP integrations can act beyond parent's intended scope.",
                        recommendation="Review sub-agent's tool and MCP configurations for necessity.",
                        source_location=f"subagents[{sub.agent_id}]",
                    )
                )

        if len(audit_input.subagents) > 3:
            findings.append(
                AuditFinding(
                    checker="subagent_risk",
                    severity=AuditSeverity.LOW,
                    title=f"Agent delegates to {len(audit_input.subagents)} sub-agents",
                    description="Large number of sub-agents increases the overall attack surface.",
                    recommendation="Consolidate sub-agents where possible to reduce management overhead.",
                    source_location=f"subagents (count: {len(audit_input.subagents)})",
                )
            )

        return findings
