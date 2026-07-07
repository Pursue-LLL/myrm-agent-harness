"""invoke_deferred_tool — cache-safe proxy for DISCOVERABLE native tools."""

from __future__ import annotations

import json
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
            "Deferred native tool name from <available-deferred-tools> "
            "or discover_capability_tool DeferredToolHit."
        )
    )
    arguments: dict[str, object] = Field(
        default_factory=dict,
        description="Arguments for the deferred tool (JSON object matching its schema).",
    )


def _resolve_discoverable_tool(registry: ToolRegistry, name: str) -> BaseTool | None:
    candidates = {name}
    if not name.endswith("_tool"):
        candidates.add(f"{name}_tool")
    else:
        candidates.add(name.removesuffix("_tool"))
    for tool in registry.get_discoverable_tools():
        if tool.name in candidates:
            return tool
    return None


def create_invoke_deferred_tool(registry: ToolRegistry) -> BaseTool:
    """Create Turn1 proxy that executes DISCOVERABLE tools without mutating bind_tools."""

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
        target = _resolve_discoverable_tool(registry, name)
        if target is None:
            return (
                f"Error: '{name}' is not a deferred native tool. "
                "Check <available-deferred-tools> or use discover_capability_tool."
            )
        payload = arguments if arguments is not None else {}
        try:
            result = await target.ainvoke(payload)
        except Exception as exc:
            return f"Error invoking deferred tool '{target.name}': {exc}"
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    return invoke_deferred_func
