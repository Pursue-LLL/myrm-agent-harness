"""Tool exposure checker — detects high-privilege built-in tool combinations.

[INPUT]
- ProfileAuditInput.enabled_builtin_tools

[OUTPUT]
- Findings for dangerous tool combinations (e.g., shell + file_write + code_interpreter)

[POS]
Certain tool combinations create amplified risk. A single shell_exec is
medium risk, but shell_exec + file_write + mcp_invoke together is high risk.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.profile_audit.checkers.base import BaseChecker
from myrm_agent_harness.agent.security.profile_audit.types import (
    AuditFinding,
    AuditSeverity,
    ProfileAuditInput,
)

_HIGH_PRIVILEGE_TOOLS = frozenset({"shell_exec", "code_interpreter_tool"})

_DANGEROUS_COMBINATIONS: tuple[tuple[frozenset[str], str, AuditSeverity], ...] = (
    (
        frozenset({"shell_exec", "file_write", "mcp_invoke"}),
        "Shell + file write + MCP invocation enables chained exploitation",
        AuditSeverity.HIGH,
    ),
    (
        frozenset({"shell_exec", "code_interpreter_tool"}),
        "Shell + code interpreter provides redundant execution surfaces",
        AuditSeverity.MEDIUM,
    ),
    (
        frozenset({"file_write", "net_fetch"}),
        "File write + network fetch enables download-and-execute patterns",
        AuditSeverity.MEDIUM,
    ),
)


class ToolExposureChecker(BaseChecker):
    """Detects high-privilege tool combinations in the enabled tool set."""

    def check(self, audit_input: ProfileAuditInput) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        tools = frozenset(audit_input.enabled_builtin_tools)

        if not tools:
            return findings

        for combo, description, severity in _DANGEROUS_COMBINATIONS:
            if combo.issubset(tools):
                findings.append(
                    AuditFinding(
                        checker="tool_exposure",
                        severity=severity,
                        title="Dangerous tool combination detected",
                        description=description,
                        recommendation="Reduce enabled tools to the minimum required set, or add compensating security controls.",
                        source_location=f"enabled_builtin_tools: {sorted(combo)}",
                    )
                )

        high_priv_enabled = tools & _HIGH_PRIVILEGE_TOOLS
        if high_priv_enabled and len(tools) > 4:
            findings.append(
                AuditFinding(
                    checker="tool_exposure",
                    severity=AuditSeverity.MEDIUM,
                    title="Large tool surface with high-privilege tools",
                    description=f"Agent has {len(tools)} tools enabled including {sorted(high_priv_enabled)}",
                    recommendation="Consider narrowing the tool set or using per-agent capability restrictions.",
                    source_location=f"enabled_builtin_tools ({len(tools)} total)",
                )
            )

        return findings
