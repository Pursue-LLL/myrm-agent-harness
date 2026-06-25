"""Architecture guard: harness tool registry must not contain vendor-specific tools."""

from __future__ import annotations

from myrm_agent_harness.agent.tool_management.tool_layers import _TOOL_LAYERS

_VENDOR_TOOL_NAMES = frozenset(
    {
        "x_search_tool",
        "notion_tool",
        "linear_tool",
        "slack_tool",
    }
)


def test_harness_tool_layers_exclude_vendor_tools() -> None:
    overlap = _VENDOR_TOOL_NAMES & set(_TOOL_LAYERS)
    assert not overlap, f"Vendor tools must be registered in server layer only: {sorted(overlap)}"
