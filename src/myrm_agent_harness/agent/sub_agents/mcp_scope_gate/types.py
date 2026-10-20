"""Type definitions and contracts for Employee/Agent-Scoped MCP Tool Discovery Gate.

[INPUT]
- None (pure domain types)

[OUTPUT]
- EmployeeToolScopePolicy, McpDiscoveryCheckResult, ScopedMcpFilterVerdict
- EmployeeToolScopeViolationError

[POS]
myrm_agent_harness/agent/sub_agents/mcp_scope_gate/types.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


class EmployeeToolScopeViolationError(PermissionError):
    """Raised when an agent attempts to discover or invoke an MCP tool outside its scope policy."""

    def __init__(self, agent_id: str, server_name: str, tool_name: str, reason: str) -> None:
        super().__init__(
            f"Agent '{agent_id}' is not authorized to access tool '{tool_name}' on MCP server '{server_name}': {reason}"
        )
        self.agent_id = agent_id
        self.server_name = server_name
        self.tool_name = tool_name
        self.reason = reason


@dataclass(slots=True)
class EmployeeToolScopePolicy:
    """Explicit MCP tool access scope policy bound to a specific agent/employee profile."""

    agent_id: str
    allowed_mcp_servers: list[str] = field(default_factory=list)
    # Mapping of server_name -> list of explicitly permitted tool names. If empty list, all tools of that server are allowed.
    tool_allowlist_map: dict[str, list[str]] = field(default_factory=dict)
    strict_mode: bool = True
    updated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(slots=True)
class McpDiscoveryCheckResult:
    """Outcome of scoping check for an individual MCP tool candidate."""

    server_name: str
    tool_name: str
    is_allowed: bool
    reason: str
    description: str = ""


@dataclass(slots=True)
class ScopedMcpFilterVerdict:
    """Batch filtering verdict returned by the Employee-Scoped MCP Discovery Gate."""

    agent_id: str
    total_discovered: int
    allowed_count: int
    blocked_count: int
    allowed_tools: list[McpDiscoveryCheckResult] = field(default_factory=list)
    blocked_tools: list[McpDiscoveryCheckResult] = field(default_factory=list)
