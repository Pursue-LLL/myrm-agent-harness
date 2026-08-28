"""Tests for EXTENDED layer cache-friendly sort ranks."""

from __future__ import annotations

from myrm_agent_harness.agent.tool_management.tool_layers import (
    ToolLayer,
    get_tool_registry_sort_key,
)


def test_extended_skill_cluster_sorts_before_browser_tools() -> None:
    skill_search = get_tool_registry_sort_key("skill_search_tool", ToolLayer.EXTENDED)
    skill_manage = get_tool_registry_sort_key("skill_manage_tool", ToolLayer.EXTENDED)
    browser_nav = get_tool_registry_sort_key("browser_navigate_tool", ToolLayer.EXTENDED)

    assert skill_search < skill_manage < browser_nav


def test_extended_skill_order_is_stable() -> None:
    ordered = [
        get_tool_registry_sort_key(name, ToolLayer.EXTENDED)
        for name in (
            "skill_search_tool",
            "skill_manage_tool",
            "skill_market_tool",
        )
    ]
    assert ordered == sorted(ordered)
