"""Deferred tool economics, stable index, and activation helpers.

[POS]
Package entry for deferred-tool Turn1 economics and stable prompt index helpers.
"""

from myrm_agent_harness.agent.tool_management.defer.economics import (
    LARGE_DEFER_TOOL_SCHEMA_TOKENS,
    should_bind_discover_gateway,
)
from myrm_agent_harness.agent.tool_management.defer.stable_index import (
    DEFERRED_TOOLS_MARKER,
    build_deferred_tools_prompt_section,
)

__all__ = [
    "DEFERRED_TOOLS_MARKER",
    "LARGE_DEFER_TOOL_SCHEMA_TOKENS",
    "build_deferred_tools_prompt_section",
    "should_bind_discover_gateway",
]
