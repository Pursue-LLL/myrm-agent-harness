"""Tests for EXTENDED layer alphabetical stable sorting."""

from __future__ import annotations

from myrm_agent_harness.agent.tool_management.tool_layers import (
    ToolLayer,
    get_tool_registry_sort_key,
)


def test_extended_tools_sort_alphabetically() -> None:
    """EXTENDED layer sorts purely alphabetically by tool name."""
    browser_nav = get_tool_registry_sort_key("browser_navigate_tool", ToolLayer.EXTENDED)
    cron_manage = get_tool_registry_sort_key("cron_manage_tool", ToolLayer.EXTENDED)
    skill_manage = get_tool_registry_sort_key("skill_manage_tool", ToolLayer.EXTENDED)
    skill_search = get_tool_registry_sort_key("skill_search_tool", ToolLayer.EXTENDED)
    wiki_query = get_tool_registry_sort_key("wiki_query_tool", ToolLayer.EXTENDED)

    assert browser_nav < cron_manage < skill_manage < skill_search < wiki_query


def test_extended_skill_order_is_alphabetical() -> None:
    ordered = [
        get_tool_registry_sort_key(name, ToolLayer.EXTENDED)
        for name in (
            "skill_manage_tool",
            "skill_market_tool",
            "skill_search_tool",
        )
    ]
    assert ordered == sorted(ordered)

