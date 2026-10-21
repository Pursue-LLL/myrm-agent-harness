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

import re

_IDENTIFIER_INVALID = re.compile(r"[^A-Za-z0-9_]")


def to_python_identifier(name: str) -> str:
    """Fold an arbitrary MCP tool name into a valid Python identifier.

    Names reach the model as ``from skills.<skill> import <func>``, so ``foo.bar``,
    ``foo bar`` and ``1foo`` must all become importable before they are rendered.
    Runs of ``_`` are preserved: collapsing them would merge distinct upstream tools
    (``foo__bar`` / ``foo_bar``) that the server exposes separately.
    """
    folded = _IDENTIFIER_INVALID.sub("_", name)
    if not any(char.isalnum() for char in folded):
        return "unnamed"
    if folded[0].isdigit():
        return f"_{folded}"
    return folded


def build_tool_name_map(tools: list[str]) -> dict[str, str]:
    """Map every canonical MCP tool name to a unique, valid Python identifier.

    Deterministic: tools are sorted before allocation, and a folded collision keeps
    the first name verbatim while later ones take ``_2``, ``_3``. Rendering, file
    lookup and invocation all share this map, so the identifier the model sees is
    the same one the proxy resolves back to the canonical tool.
    """
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for canonical in sorted(tools):
        base = to_python_identifier(mcp_tool_short_name(canonical))
        candidate = base
        index = 2
        while candidate in used:
            candidate = f"{base}_{index}"
            index += 1
        used.add(candidate)
        mapping[canonical] = candidate
    return mapping


def mcp_tool_short_name(canonical_name: str) -> str:
    """Return the LLM-facing function segment from a prefixed MCP tool name.

    Only the ``mcp__<server>__`` prefix is removed: the raw tool name may itself
    contain ``__`` (``mcp__srv__foo__bar`` -> ``foo__bar``), so the tail is taken
    after the *first* separator, not the last.
    """
    normalized = canonical_name.replace("-", "_")
    if normalized.startswith("mcp__"):
        rest = normalized[len("mcp__") :]
        _, separator, tail = rest.partition("__")
        if separator:
            return tail
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
    for canonical, python_name in build_tool_name_map(available_tools).items():
        if python_name == normalized:
            return canonical

    suffix_matches = [tool for tool in available_tools if _normalize_alias(mcp_tool_short_name(tool)) == target]
    if len(suffix_matches) == 1:
        return suffix_matches[0]

    return None
