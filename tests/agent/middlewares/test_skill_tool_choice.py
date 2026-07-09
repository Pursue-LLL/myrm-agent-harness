"""Tests for skill attenuation tool_choice helpers."""

from __future__ import annotations

from myrm_agent_harness.agent.middlewares._skill_tool_choice import (
    build_allowed_tools_tool_choice,
    extract_bound_tool_names,
)


def test_extract_bound_tool_names_from_base_tool() -> None:
    class StubTool:
        name = "echo_tool"

    assert extract_bound_tool_names([StubTool()]) == ["echo_tool"]


def test_extract_bound_tool_names_from_openai_dict() -> None:
    tools = [{"type": "function", "function": {"name": "web_search_tool", "parameters": {}}}]
    assert extract_bound_tool_names(tools) == ["web_search_tool"]


def test_extract_bound_tool_names_from_dict_direct_name() -> None:
    assert extract_bound_tool_names([{"name": "memory_search"}]) == ["memory_search"]


def test_extract_bound_tool_names_skips_unrecognized() -> None:
    assert extract_bound_tool_names([{"type": "function"}, object()]) == []


def test_build_allowed_tools_tool_choice_sorted() -> None:
    choice = build_allowed_tools_tool_choice(frozenset({"z_tool", "a_tool"}))
    assert choice == {
        "type": "allowed_tools",
        "mode": "auto",
        "tools": [
            {"type": "function", "name": "a_tool"},
            {"type": "function", "name": "z_tool"},
        ],
    }
