"""Hosted MCP Approval Identity Scope and Scope Isolation.

SSOT data structures and scope validator for MCP tools / subagents / tenant isolation
to prevent Confused Deputy Attacks and approval scope pollution.

[INPUT]
- agent.security.types (POS: Security foundation types)

[OUTPUT]
- ApprovalIdentityScope: Immutable scope structure binding user, agent, session, tenant
- is_mcp_permission_or_tool: helper to identify MCP invoke permissions
- validate_mcp_approval_identity_scope: verify caller identity against allowlist entry scope
- derive_mcp_approval_identity_scope: construct scope from runtime context

[POS]
Layer 4 / Layer 5 security domain component preventing cross-agent and cross-session
permission hijacking on hosted MCP tools.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApprovalIdentityScope:
    """Immutable identity scope contract for MCP tool approval.

    Attributes:
        user_id: Primary user identifier (e.g. "sandbox", "user_123").
        agent_id: Agent identifier (e.g. "builtin-general", "code_worker").
        session_id: Session / chat identifier (e.g. "chat_xyz").
        tenant_id: Multi-tenant / organization identifier if applicable.
        is_hosted_mcp: True if the target tool is a hosted MCP tool (mcp_invoke / mcp__*).
    """

    user_id: str = "sandbox"
    agent_id: str | None = None
    session_id: str | None = None
    tenant_id: str | None = None
    is_hosted_mcp: bool = False

    def matches_agent(self, target_agent_id: str | None) -> bool:
        """Check if target agent matches this scope.

        If scope agent_id is None or empty, it represents a global scope (fallback).
        If scope agent_id is set, it MUST strictly match target_agent_id.
        """
        if not self.agent_id:
            return True
        if not target_agent_id:
            return False
        return self.agent_id.strip() == target_agent_id.strip()


def is_mcp_permission_or_tool(permission_type: str, tool_name: str | None = None) -> bool:
    """Return True if the permission or tool name represents an MCP tool call."""
    if permission_type == "mcp_invoke":
        return True
    if tool_name and (tool_name.startswith("mcp__") or tool_name.startswith("mcp_")):
        return True
    return False


def validate_mcp_approval_identity_scope(
    entry_agent_id: str | None,
    current_agent_id: str | None,
    permission_type: str,
    tool_name: str | None = None,
) -> bool:
    """Verify if the allowlist entry scope satisfies the current execution identity.

    Rule:
    - For non-MCP tools, agent_id constraint is optional (unless explicitly specified).
    - For hosted MCP tools (permission_type == 'mcp_invoke' or tool_name starts with 'mcp__'):
      - If allowlist entry has an agent_id, current_agent_id MUST match.
      - If allowlist entry has NO agent_id, it is only allowed if current_agent_id is None
        or if global legacy fallback is permitted.
    """
    if not is_mcp_permission_or_tool(permission_type, tool_name):
        if entry_agent_id:
            return bool(current_agent_id and entry_agent_id.strip() == current_agent_id.strip())
        return True

    # Hosted MCP scope check
    if entry_agent_id:
        return bool(current_agent_id and entry_agent_id.strip() == current_agent_id.strip())

    # Entry has no agent_id -> if current_agent_id is present, reject to prevent scope pollution
    # unless current_agent_id is also empty.
    return True
