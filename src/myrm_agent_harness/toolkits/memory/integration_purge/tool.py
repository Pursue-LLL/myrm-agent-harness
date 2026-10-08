"""Agent runtime tool factory for integration retained context governance and purge.

[INPUT]
- typing::{Literal}
- pydantic::{BaseModel, Field}
- langchain_core.tools::{BaseTool, tool}
- .types::{PurgeExecutionMode}
- .manager::{IntegrationRetainedContextManager}

[OUTPUT]
- create_integration_context_purge_tool: Factory creating LangChain tool for connector context governance

[POS]
Agent runtime surface enabling autonomous inspection and privacy-compliant purging
of connector-scoped context when integrations are disconnected or revoked.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.integration_purge.manager import (
    IntegrationRetainedContextManager,
)
from myrm_agent_harness.toolkits.memory.integration_purge.types import (
    PurgeExecutionMode,
)


class IntegrationContextPurgeInput(BaseModel):
    """Input parameters for managing integration retained context."""

    action: Literal["inspect", "purge", "status"] = Field(
        description="Action to perform: 'inspect' retained context, 'purge' connector data, or check revocation 'status'"
    )
    integration_id: str = Field(
        description="Identifier of the connector or integration (e.g. 'google_workspace', 'github', 'mcp_server')"
    )
    purge_mode: Literal["retain_context", "selective_purge", "purge_and_revoke"] = Field(
        default="retain_context",
        description="Purge mode when action is 'purge'. 'retain_context' preserves data, 'purge_and_revoke' deletes all.",
    )
    reason: str = Field(
        default="",
        description="Optional reason or confirmation message for audit logging",
    )


def create_integration_context_purge_tool(
    manager: IntegrationRetainedContextManager,
) -> BaseTool:
    """Create a LangChain tool for inspecting, purging, and revoking integration context."""

    @tool("manage_integration_retained_context", args_schema=IntegrationContextPurgeInput)
    async def manage_integration_retained_context(
        action: Literal["inspect", "purge", "status"],
        integration_id: str,
        purge_mode: Literal["retain_context", "selective_purge", "purge_and_revoke"] = "retain_context",
        reason: str = "",
    ) -> str:
        """Inspect retained context, disconnect integrations, and selectively purge context with provenance revocation."""
        if action == "inspect":
            summary = await manager.inspect_retained_context(integration_id)
            status_text = "REVOKED" if summary.is_provenance_revoked else "ACTIVE"
            return (
                f"Connector '{integration_id}' Retained Context Summary:\n"
                f"- Total Retained Items: {summary.total_retained_items}\n"
                f"- Retained Memories: {summary.retained_memory_count}\n"
                f"- Retained Trees: {summary.retained_tree_count}\n"
                f"- Provenance Status: {status_text}\n"
                f"- Sample Snippets: {len(summary.sample_snippets)} items found"
            )

        if action == "status":
            is_revoked = manager.is_provenance_revoked(integration_id)
            return (
                f"Connector '{integration_id}' Provenance Status: "
                f"{'REVOKED (Access blocked)' if is_revoked else 'ACTIVE (Trusted)'}"
            )

        if action == "purge":
            mode_enum = PurgeExecutionMode(purge_mode)
            result = await manager.execute_purge(
                integration_id,
                mode_enum,
                actor="agent_tool",
                reason=reason or "Agent tool initiated integration purge",
            )
            return (
                f"Purge Result for '{integration_id}':\n"
                f"- Mode: {result.mode.value}\n"
                f"- Deleted Memories: {result.deleted_memories_count}\n"
                f"- Deleted Trees: {result.deleted_trees_count}\n"
                f"- Revocation ID: {result.revocation_id or 'N/A'}\n"
                f"- Status: {'SUCCESS' if result.success else 'FAILED'}"
            )

        return f"Unknown action: {action}"

    return manage_integration_retained_context
