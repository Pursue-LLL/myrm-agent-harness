"""Policy gap checker — detects missing security policy coverage.

[INPUT]
- ProfileAuditInput.security_policy
- ProfileAuditInput.enabled_builtin_tools (for context)

[OUTPUT]
- Findings for missing security controls given the tool surface

[POS]
A powerful Agent with many tools but no security policy is a gap.
This checker identifies situations where the configured capabilities
exceed the configured security controls.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.profile_audit.checkers.base import BaseChecker
from myrm_agent_harness.agent.security.profile_audit.types import (
    AuditFinding,
    AuditSeverity,
    ProfileAuditInput,
)

_NETWORK_TOOLS = frozenset({"net_fetch", "web_search_tool", "mcp_invoke"})
_FS_TOOLS = frozenset({"file_read", "file_write", "shell_exec"})


class PolicyGapChecker(BaseChecker):
    """Detects gaps between enabled capabilities and security policy coverage."""

    def check(self, audit_input: ProfileAuditInput) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        tools = frozenset(audit_input.enabled_builtin_tools)
        policy = audit_input.security_policy

        has_network_tools = bool(tools & _NETWORK_TOOLS)
        has_fs_tools = bool(tools & _FS_TOOLS)

        if has_network_tools and not policy.has_network_policy:
            findings.append(
                AuditFinding(
                    checker="policy_gap",
                    severity=AuditSeverity.MEDIUM,
                    title="Network tools enabled without network policy",
                    description="Agent can access network but has no domain allowlist or blocklist configured.",
                    recommendation="Add network domain allowlist/blocklist to restrict accessible domains.",
                    source_location="security_policy.has_network_policy",
                )
            )

        if has_fs_tools and not policy.has_path_policy:
            findings.append(
                AuditFinding(
                    checker="policy_gap",
                    severity=AuditSeverity.MEDIUM,
                    title="Filesystem tools enabled without path policy",
                    description="Agent can access filesystem but has no path restrictions configured.",
                    recommendation="Configure allowed paths to restrict filesystem access scope.",
                    source_location="security_policy.has_path_policy",
                )
            )

        if (has_network_tools or has_fs_tools) and not policy.has_capability_restrictions:
            findings.append(
                AuditFinding(
                    checker="policy_gap",
                    severity=AuditSeverity.LOW,
                    title="No capability restrictions configured",
                    description="Agent has powerful tools but no explicit capability restrictions.",
                    recommendation="Consider restricting capabilities to only those required for the agent's purpose.",
                    source_location="security_policy.has_capability_restrictions",
                )
            )

        if has_network_tools and not policy.domain_hitl_enabled:
            findings.append(
                AuditFinding(
                    checker="policy_gap",
                    severity=AuditSeverity.INFO,
                    title="Domain HITL approval not enabled",
                    description="Agent can access new domains without user confirmation.",
                    recommendation="Enable domain HITL for additional safety on network requests.",
                    source_location="security_policy.domain_hitl_enabled",
                )
            )

        return findings
