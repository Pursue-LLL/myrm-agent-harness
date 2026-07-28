"""MCP tool name normalization for PTC skill invocation.

[INPUT]
- backends.skills.types::SkillMetadata.mcp.tools (POS: MCP skill tool name list)

[OUTPUT]
- resolve_mcp_tool_name: map caller tool name to canonical MCP tool name

[POS]
Single source of truth for MCP tool name matching (server prefix strip, _/- aliases).
Shared by core_generator documentation lookup and proxy_service invoke validation.
"""

from __future__ import annotations


def resolve_mcp_tool_name(tool_name: str, available_tools: list[str]) -> str | None:
    """Resolve a caller tool name to a canonical MCP tool name."""
    normalized = tool_name
    if ":" in normalized:
        normalized = normalized.split(":")[-1]

    if normalized in available_tools:
        return normalized

    alt_underscore = normalized.replace("-", "_")
    if alt_underscore in available_tools:
        return alt_underscore

    alt_hyphen = normalized.replace("_", "-")
    if alt_hyphen in available_tools:
        return alt_hyphen

    return None
