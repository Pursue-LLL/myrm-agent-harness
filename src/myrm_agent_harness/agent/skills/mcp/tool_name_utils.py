"""MCP tool name normalization for PTC skill invocation.

[INPUT]
- backends.skills.types::SkillMetadata.mcp.tools (POS: MCP skill tool name list)

[OUTPUT]
- mcp_tool_short_name: strip ``mcp__{server}__`` prefix for LLM-facing names
- resolve_mcp_tool_name: map caller tool name to canonical MCP tool name

[POS]
Single source of truth for MCP tool name matching (server prefix strip, _/- aliases,
``mcp__{server}__{tool}`` suffix resolution). Shared by core_generator documentation
lookup, MCPFileSystemStrategy, and proxy_service invoke validation.
"""

from __future__ import annotations


def mcp_tool_short_name(canonical_name: str) -> str:
    """Return the LLM-facing function segment from a prefixed MCP tool name."""
    normalized = canonical_name.replace("-", "_")
    if normalized.startswith("mcp__") and normalized.count("__") >= 2:
        return normalized.rsplit("__", 1)[-1]
    return normalized


def _normalize_alias(name: str) -> str:
    return name.replace("-", "_")


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

    target = _normalize_alias(normalized)
    suffix_matches = [
        tool
        for tool in available_tools
        if _normalize_alias(mcp_tool_short_name(tool)) == target
    ]
    if len(suffix_matches) == 1:
        return suffix_matches[0]

    return None
