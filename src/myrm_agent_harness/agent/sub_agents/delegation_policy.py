"""Extensible leaf-blocked tool registry for server-registered outbound tools.

[INPUT]
- (none — server calls register_leaf_blocked_tools at bootstrap)

[OUTPUT]
- register_leaf_blocked_tools(): Merge server tool names into subagent L1 blocklist
- get_effective_leaf_blocked_tools(): Effective L1 blocklist for filter_tools

[POS]
Server-extensible delegation policy. Keeps harness free of hard-coded business tool names.
"""

from __future__ import annotations

_SERVER_LEAF_BLOCKED_TOOLS: frozenset[str] = frozenset()


def register_leaf_blocked_tools(names: frozenset[str]) -> None:
    """Register additional tool names blocked for all leaf subagents."""
    global _SERVER_LEAF_BLOCKED_TOOLS
    if not names:
        return
    _SERVER_LEAF_BLOCKED_TOOLS = _SERVER_LEAF_BLOCKED_TOOLS | frozenset(names)


def get_effective_leaf_blocked_tools(base: frozenset[str]) -> frozenset[str]:
    """Merge harness defaults with server-registered leaf blocks."""
    return base | _SERVER_LEAF_BLOCKED_TOOLS
