"""DeferEconomics — when to bind discover_capability_tool on Turn1.

[POS]
Turn1 discover_gateway binding economics for deferred native tools and skills.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent._factory.mcp_routing import estimate_schema_tokens

LARGE_DEFER_TOOL_SCHEMA_TOKENS = 400
"""Single deferred tool above this size warrants semantic search (e.g. cron ~827 tok)."""


def should_bind_discover_gateway(
    searchable_skill_count: int,
    discoverable_tools: Sequence[BaseTool],
) -> bool:
    """Return True when Turn1 discover_capability_tool binding is net-positive."""
    if searchable_skill_count > 0:
        return True
    if len(discoverable_tools) > 2:
        return True
    for tool in discoverable_tools:
        if estimate_schema_tokens([tool]) > LARGE_DEFER_TOOL_SCHEMA_TOKENS:
            return True
    return False
