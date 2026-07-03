"""Architecture guard: harness tool registry must not contain server-layer tools."""

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

_SERVER_BUSINESS_TOOL_NAMES = frozenset(
    {
        "canvas_get_state",
        "canvas_get_selection",
        "canvas_insert_element",
        "channel_notify_tool",
        "image_tool",
        "video_tool",
        "tts_generate",
    }
)


def test_harness_tool_layers_exclude_vendor_tools() -> None:
    overlap = _VENDOR_TOOL_NAMES & set(_TOOL_LAYERS)
    assert not overlap, f"Vendor tools must be registered in server layer only: {sorted(overlap)}"


def test_harness_tool_layers_exclude_server_business_tools() -> None:
    overlap = _SERVER_BUSINESS_TOOL_NAMES & set(_TOOL_LAYERS)
    assert not overlap, (
        "Server business tools must be registered via _tool_layer_bootstrap only: "
        f"{sorted(overlap)}"
    )
