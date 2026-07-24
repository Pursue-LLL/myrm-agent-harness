"""Tests for extensible leaf-blocked tool registration."""

from __future__ import annotations

from unittest.mock import MagicMock

from myrm_agent_harness.agent.sub_agents.builder import filter_tools
from myrm_agent_harness.agent.sub_agents.delegation_policy import (
    register_leaf_blocked_tools,
)
from myrm_agent_harness.agent.sub_agents.types import (
    DELEGATION_CAPABILITY_MANIFEST,
    SubagentConfig,
)


def test_delegation_manifest_blocks_ask_question_tool() -> None:
    assert "ask_question_tool" in DELEGATION_CAPABILITY_MANIFEST.leaf_blocked_tools


def test_register_leaf_blocked_tools_filters_subagent_tools() -> None:
    register_leaf_blocked_tools(frozenset({"channel_notify_tool"}))

    tools = []
    for name in ("web_search_tool", "channel_notify_tool"):
        tool = MagicMock()
        tool.name = name
        tools.append(tool)

    filtered = filter_tools(SubagentConfig(system_prompt="test"), tools)
    filtered_names = {tool.name for tool in filtered}

    assert "web_search_tool" in filtered_names
    assert "channel_notify_tool" not in filtered_names


def test_register_leaf_blocked_tools_noop_on_empty() -> None:
    from myrm_agent_harness.agent.sub_agents.delegation_policy import (
        get_effective_leaf_blocked_tools,
    )
    from myrm_agent_harness.agent.sub_agents.types import DELEGATION_CAPABILITY_MANIFEST

    before = get_effective_leaf_blocked_tools(
        DELEGATION_CAPABILITY_MANIFEST.leaf_blocked_tools
    )
    register_leaf_blocked_tools(frozenset())
    after = get_effective_leaf_blocked_tools(
        DELEGATION_CAPABILITY_MANIFEST.leaf_blocked_tools
    )
    assert after == before
