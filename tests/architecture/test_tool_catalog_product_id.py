"""Architecture gate: tool_catalog product_id derives from existing group SSOTs."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.discover_capability.capability_gap import (
    BUILTIN_TOOL_ID_TO_GROUP,
)
from myrm_agent_harness.agent.tool_management.tool_catalog import get_tool_product_id
from myrm_agent_harness.core.security.tool_registry import TOOL_GROUP_MAP


@pytest.mark.architecture
def test_togglable_tool_groups_resolve_product_id() -> None:
    """Every tool in a capability-gap group maps to the GUI togglable product ID."""
    for product_id, group in BUILTIN_TOOL_ID_TO_GROUP.items():
        tools = TOOL_GROUP_MAP.get(group)
        assert tools, f"missing TOOL_GROUP_MAP entry for group {group!r}"
        for tool_name in tools:
            if group == "web" and tool_name != "web_search_tool":
                assert get_tool_product_id(tool_name) is None
                continue
            assert get_tool_product_id(tool_name) == product_id


@pytest.mark.architecture
def test_baseline_web_fetch_has_no_product_id() -> None:
    assert get_tool_product_id("web_fetch_tool") is None


@pytest.mark.architecture
def test_conversation_search_override_maps_to_memory() -> None:
    assert get_tool_product_id("conversation_search_tool") == "memory"
