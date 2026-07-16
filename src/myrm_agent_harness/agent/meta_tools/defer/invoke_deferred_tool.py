"""invoke_deferred_tool — cache-stable schema gateway for deferred tools.

[POS]
Turn1-bound schema gateway for DISCOVERABLE native tools. The runtime middleware
normalizes gateway calls to their effective tool identity before approval and
execution; this fallback never executes a target directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.tool_management.registry import ToolRegistry

INVOKE_DEFERRED_TOOL_NAME = "invoke_deferred_tool"


class InvokeDeferredInput(BaseModel):
    name: str = Field(
        description=(
            "Deferred native tool name from <available-deferred-tools> or discover_capability_tool DeferredToolHit."
        )
    )
    arguments: dict[str, object] = Field(
        default_factory=dict,
        description="Arguments for the deferred tool (JSON object matching its schema).",
    )


def create_invoke_deferred_tool(registry: ToolRegistry) -> BaseTool:
    """Create the Turn1 schema gateway consumed by DeferredToolMiddleware."""

    @tool(
        INVOKE_DEFERRED_TOOL_NAME,
        description=(
            "Execute a deferred native tool by name. Deferred tools are listed in "
            "<available-deferred-tools> and are not bound on Turn1. Use "
            "discover_capability_tool first when you need schema hints or semantic search."
        ),
        args_schema=InvokeDeferredInput,
    )
    async def invoke_deferred_func(
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> str:
        available_names = {tool.name for tool in registry.get_discoverable_tools()}
        if name not in available_names:
            return (
                f"Error: '{name}' is not a deferred native tool. "
                "Check <available-deferred-tools> or use discover_capability_tool."
            )
        argument_count = len(arguments) if arguments is not None else 0
        return (
            "Error: deferred tool execution was refused because the call did not pass "
            f"through runtime safety normalization (target='{name}', arguments={argument_count})."
        )

    return invoke_deferred_func
