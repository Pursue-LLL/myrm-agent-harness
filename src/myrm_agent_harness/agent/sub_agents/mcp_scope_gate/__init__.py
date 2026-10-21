"""Employee/Agent-Scoped MCP Tool Discovery Gate package.

[INPUT]
- scope_gate.EmployeeScopedMcpDiscoveryGate
- types.*

[OUTPUT]
- EmployeeScopedMcpDiscoveryGate
- EmployeeToolScopePolicy, McpDiscoveryCheckResult, ScopedMcpFilterVerdict
- EmployeeToolScopeViolationError

[POS]
myrm_agent_harness/agent/sub_agents/mcp_scope_gate/__init__.py
"""

from myrm_agent_harness.agent.sub_agents.mcp_scope_gate.scope_gate import (
    EmployeeScopedMcpDiscoveryGate,
)
from myrm_agent_harness.agent.sub_agents.mcp_scope_gate.types import (
    EmployeeToolScopePolicy,
    EmployeeToolScopeViolationError,
    McpDiscoveryCheckResult,
    ScopedMcpFilterVerdict,
)

__all__ = [
    "EmployeeScopedMcpDiscoveryGate",
    "EmployeeToolScopePolicy",
    "EmployeeToolScopeViolationError",
    "McpDiscoveryCheckResult",
    "ScopedMcpFilterVerdict",
]
