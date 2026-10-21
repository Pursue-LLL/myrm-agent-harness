"""MCP authentication checker — audits MCP server transport and auth config.

[INPUT]
- ProfileAuditInput.mcp_configs

[OUTPUT]
- Findings for MCP servers without authentication or with insecure transport

[POS]
MCP servers without authentication or using stdio transport with no auth
represent significant supply-chain risk. Flags missing auth, high finding
counts from pre-existing scans, and insecure transports.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.profile_audit.checkers.base import BaseChecker
from myrm_agent_harness.agent.security.profile_audit.types import (
    AuditFinding,
    AuditSeverity,
    ProfileAuditInput,
)

_INSECURE_TRANSPORTS = frozenset({"stdio", "sse"})


class MCPAuthChecker(BaseChecker):
    """Audits MCP server configurations for authentication and transport security."""

    def check(self, audit_input: ProfileAuditInput) -> list[AuditFinding]:
        findings: list[AuditFinding] = []

        for mcp in audit_input.mcp_configs:
            if not mcp.has_auth and mcp.transport_type in _INSECURE_TRANSPORTS:
                findings.append(
                    AuditFinding(
                        checker="mcp_auth",
                        severity=AuditSeverity.HIGH,
                        title=f"MCP server '{mcp.server_name}' has no authentication",
                        description=f"Server uses {mcp.transport_type} transport without auth credentials.",
                        recommendation="Configure authentication or restrict to trusted local-only MCP servers.",
                        source_location=f"mcp_configs[{mcp.server_name}].has_auth",
                    )
                )
            elif not mcp.has_auth:
                findings.append(
                    AuditFinding(
                        checker="mcp_auth",
                        severity=AuditSeverity.MEDIUM,
                        title=f"MCP server '{mcp.server_name}' has no authentication",
                        description=f"Server uses {mcp.transport_type} transport without explicit auth.",
                        recommendation="Add authentication to prevent unauthorized access to MCP capabilities.",
                        source_location=f"mcp_configs[{mcp.server_name}].has_auth",
                    )
                )

            if mcp.max_severity in ("high", "critical"):
                findings.append(
                    AuditFinding(
                        checker="mcp_auth",
                        severity=AuditSeverity.HIGH if mcp.max_severity == "critical" else AuditSeverity.MEDIUM,
                        title=f"MCP server '{mcp.server_name}' has {mcp.max_severity}-severity scan findings",
                        description=f"Pre-existing scan found {mcp.finding_count} issue(s) with max severity: {mcp.max_severity}.",
                        recommendation="Review and resolve MCP configuration findings before deployment.",
                        source_location=f"mcp_configs[{mcp.server_name}].findings",
                    )
                )

        return findings
