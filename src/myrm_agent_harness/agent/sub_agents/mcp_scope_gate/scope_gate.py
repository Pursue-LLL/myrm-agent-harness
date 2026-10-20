"""Discovery gate scoping dynamically discovered MCP tools to specific employees/agents.

[INPUT]
- types.EmployeeToolScopePolicy, types.McpDiscoveryCheckResult, types.ScopedMcpFilterVerdict
- types.EmployeeToolScopeViolationError

[OUTPUT]
- EmployeeScopedMcpDiscoveryGate

[POS]
myrm_agent_harness/agent/sub_agents/mcp_scope_gate/scope_gate.py
"""

from __future__ import annotations

import logging
import threading
from typing import ClassVar

from myrm_agent_harness.agent.sub_agents.mcp_scope_gate.types import (
    EmployeeToolScopePolicy,
    EmployeeToolScopeViolationError,
    McpDiscoveryCheckResult,
    ScopedMcpFilterVerdict,
)

logger = logging.getLogger(__name__)


class EmployeeScopedMcpDiscoveryGate:
    """Gate enforcing employee-scoped MCP tool discovery and invocation boundaries."""

    _instance: ClassVar[EmployeeScopedMcpDiscoveryGate | None] = None
    _singleton_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        self._policies: dict[str, EmployeeToolScopePolicy] = {}
        self._lock: threading.Lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> EmployeeScopedMcpDiscoveryGate:
        """Get or initialize singleton instance of discovery gate."""
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register_policy(self, policy: EmployeeToolScopePolicy) -> None:
        """Register or update an employee/agent scope policy."""
        with self._lock:
            self._policies[policy.agent_id] = policy

    def get_policy(self, agent_id: str) -> EmployeeToolScopePolicy | None:
        """Retrieve the scope policy for a specific agent/employee."""
        with self._lock:
            return self._policies.get(agent_id)

    def filter_discovered_tools(
        self,
        agent_id: str,
        discovered_tools: list[tuple[str, str, str]],  # (server_name, tool_name, description)
    ) -> ScopedMcpFilterVerdict:
        """Filter dynamically discovered MCP tools against the agent's scope policy."""
        with self._lock:
            policy = self._policies.get(agent_id)

        allowed_results: list[McpDiscoveryCheckResult] = []
        blocked_results: list[McpDiscoveryCheckResult] = []

        # Fail-closed default if no policy is registered
        if not policy:
            for s_name, t_name, desc in discovered_tools:
                res = McpDiscoveryCheckResult(
                    server_name=s_name,
                    tool_name=t_name,
                    is_allowed=False,
                    reason=f"No MCP scope policy registered for agent '{agent_id}' (Fail-Closed)",
                    description=desc,
                )
                blocked_results.append(res)

            return ScopedMcpFilterVerdict(
                agent_id=agent_id,
                total_discovered=len(discovered_tools),
                allowed_count=0,
                blocked_count=len(discovered_tools),
                allowed_tools=[],
                blocked_tools=blocked_results,
            )

        for s_name, t_name, desc in discovered_tools:
            # Check 1: Is MCP server permitted?
            if s_name not in policy.allowed_mcp_servers:
                res = McpDiscoveryCheckResult(
                    server_name=s_name,
                    tool_name=t_name,
                    is_allowed=False,
                    reason=f"MCP server '{s_name}' is not in agent's allowed servers list",
                    description=desc,
                )
                blocked_results.append(res)
                continue

            # Check 2: If server has fine-grained tool allowlist, verify tool presence
            tool_allowlist = policy.tool_allowlist_map.get(s_name)
            if tool_allowlist is not None and len(tool_allowlist) > 0 and t_name not in tool_allowlist:
                res = McpDiscoveryCheckResult(
                    server_name=s_name,
                    tool_name=t_name,
                    is_allowed=False,
                    reason=f"Tool '{t_name}' is not in allowlist for server '{s_name}'",
                    description=desc,
                )
                blocked_results.append(res)
                continue

            # Passed all checks
            res = McpDiscoveryCheckResult(
                server_name=s_name,
                tool_name=t_name,
                is_allowed=True,
                reason="Explicitly allowed by employee scope policy",
                description=desc,
            )
            allowed_results.append(res)

        return ScopedMcpFilterVerdict(
            agent_id=agent_id,
            total_discovered=len(discovered_tools),
            allowed_count=len(allowed_results),
            blocked_count=len(blocked_results),
            allowed_tools=allowed_results,
            blocked_tools=blocked_results,
        )

    def verify_tool_invocation(
        self, agent_id: str, server_name: str, tool_name: str
    ) -> McpDiscoveryCheckResult:
        """Verify whether an agent is authorized to invoke a target MCP tool."""
        verdict = self.filter_discovered_tools(agent_id, [(server_name, tool_name, "")])
        if verdict.allowed_count == 0 and len(verdict.blocked_tools) > 0:
            blocked_reason = verdict.blocked_tools[0].reason
            raise EmployeeToolScopeViolationError(
                agent_id=agent_id,
                server_name=server_name,
                tool_name=tool_name,
                reason=blocked_reason,
            )

        return verdict.allowed_tools[0]
