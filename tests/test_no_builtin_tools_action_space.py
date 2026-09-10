"""Architecture guard: test pure domain no_builtin_tools action space overriding.

Verifies that when no_builtin_tools is enabled:
1. ToolRegistry excludes ToolSource.META tools from resolve().
2. AgentProfile supports no_builtin_tools: bool flag.
3. Pure domain custom tools completely control the action space.
"""

from __future__ import annotations

import pytest
from langchain_core.tools import tool

from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.agent.tool_management.types import ToolSource
from myrm_agent_harness.backends.profiles.types import AgentProfile


@tool
def custom_file_write(path: str, content: str) -> str:
    """Domain-specific custom file writer."""
    return f"written to {path}"


@tool
def built_in_meta_tool(query: str) -> str:
    """Built-in framework meta tool."""
    return "meta result"


def test_agent_profile_no_builtin_tools_flag() -> None:
    profile = AgentProfile(id="domain_specialist", no_builtin_tools=True)
    assert profile.no_builtin_tools is True

    default_profile = AgentProfile(id="standard_agent")
    assert default_profile.no_builtin_tools is False


def test_tool_registry_no_builtin_tools_filtering() -> None:
    registry = ToolRegistry()
    registry.register(built_in_meta_tool, source=ToolSource.META)
    registry.register(custom_file_write, source=ToolSource.USER)

    # Standard resolve includes both
    all_tools = registry.resolve(no_builtin_tools=False)
    tool_names = {t.name for t in all_tools}
    assert "built_in_meta_tool" in tool_names
    assert "custom_file_write" in tool_names

    # Pure domain resolve strips META tools
    pure_tools = registry.resolve(no_builtin_tools=True)
    pure_names = {t.name for t in pure_tools}
    assert "built_in_meta_tool" not in pure_names
    assert "custom_file_write" in pure_names
    assert len(pure_tools) == 1
