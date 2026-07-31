"""Integration tests for EXTERNAL layer cache-friendly ordering."""

from langchain_core.tools import StructuredTool

from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.agent.tool_management.tool_layers import (
    ToolLayer,
    tool_layer_snapshot_label,
)
from myrm_agent_harness.agent.tool_management.types import ToolSource


def _tool(name: str) -> StructuredTool:
    return StructuredTool.from_function(lambda: None, name=name, description="d")


def test_mcp_tools_sort_after_harness_extended_tools() -> None:
    reg = ToolRegistry()
    harness_extended = ("kanban_show", "render_ui_tool", "wiki_query_tool")
    for name in harness_extended:
        reg.register(_tool(name), source=ToolSource.META)
    reg.register(_tool("mcp__github__search_repositories"), source=ToolSource.USER)

    names = [t.name for t in reg.resolve()]
    mcp_index = names.index("mcp__github__search_repositories")
    for harness_name in harness_extended:
        assert names.index(harness_name) < mcp_index


def test_snapshot_layer_uses_semantic_slug() -> None:
    reg = ToolRegistry()
    reg.register(_tool("mcp__github__search"), source=ToolSource.USER)
    snapshot = reg.snapshot()[0]
    assert snapshot.layer == tool_layer_snapshot_label(ToolLayer.EXTERNAL)
