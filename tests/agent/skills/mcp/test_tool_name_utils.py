"""Tests for MCP tool name resolution SSOT."""

from __future__ import annotations

from myrm_agent_harness.agent.skills.mcp.tool_name_utils import (
    build_tool_name_map,
    mcp_tool_short_name,
    resolve_mcp_tool_name,
    to_python_identifier,
)


class TestMcpToolShortName:
    def test_strips_server_prefix(self) -> None:
        assert mcp_tool_short_name("mcp__12306__get_current_date") == "get_current_date"

    def test_passthrough_non_prefixed(self) -> None:
        assert mcp_tool_short_name("create_issue") == "create_issue"

    def test_keeps_double_underscore_inside_raw_name(self) -> None:
        # Only the mcp__<server>__ prefix is stripped; the raw name may contain "__".
        assert mcp_tool_short_name("mcp__srv__foo__bar") == "foo__bar"


class TestPythonIdentifiers:
    def test_folds_invalid_characters(self) -> None:
        assert to_python_identifier("foo.bar") == "foo_bar"
        assert to_python_identifier("foo bar") == "foo_bar"
        assert to_python_identifier("foo-bar") == "foo_bar"

    def test_prefixes_leading_digit(self) -> None:
        assert to_python_identifier("1foo") == "_1foo"

    def test_empty_name(self) -> None:
        assert to_python_identifier("...") == "unnamed"
        assert to_python_identifier("") == "unnamed"

    def test_every_mapped_name_compiles(self) -> None:
        tools = ["mcp__srv__foo.bar", "mcp__srv__foo bar", "mcp__srv__1foo", "mcp__srv__foo__bar", "mcp__srv__bar"]
        mapping = build_tool_name_map(tools)
        assert len(set(mapping.values())) == len(tools)
        for python_name in mapping.values():
            compile(f"from skills.x import {python_name}", "<t>", "exec")

    def test_collision_gets_deterministic_suffix(self) -> None:
        # A hyphen/underscore pair folds to the same identifier, so the loser takes _2.
        tools = ["mcp__srv__foo-bar", "mcp__srv__foo_bar"]
        mapping = build_tool_name_map(tools)
        assert sorted(mapping.values()) == ["foo_bar", "foo_bar_2"]
        assert mapping == build_tool_name_map(tools)

    def test_double_underscore_stays_distinct(self) -> None:
        # foo__bar must not collapse into bar; it is a different upstream tool.
        mapping = build_tool_name_map(["mcp__srv__foo__bar", "mcp__srv__bar"])
        assert sorted(mapping.values()) == ["bar", "foo__bar"]


class TestResolveMcpToolName:
    def test_exact_match(self) -> None:
        assert resolve_mcp_tool_name("create_issue", ["create_issue", "list_prs"]) == "create_issue"

    def test_hyphen_to_underscore(self) -> None:
        assert resolve_mcp_tool_name("create-issue", ["create_issue"]) == "create_issue"

    def test_underscore_to_hyphen(self) -> None:
        assert resolve_mcp_tool_name("create_issue", ["create-issue"]) == "create-issue"

    def test_server_prefix_strip(self) -> None:
        assert resolve_mcp_tool_name("github:create_issue", ["create_issue"]) == "create_issue"

    def test_mcp_double_underscore_suffix_match(self) -> None:
        tools = ["mcp__12306__get_current_date", "mcp__12306__get_tickets"]
        assert resolve_mcp_tool_name("get_current_date", tools) == "mcp__12306__get_current_date"
        assert resolve_mcp_tool_name("get-current-date", tools) == "mcp__12306__get_current_date"

    def test_cross_server_collision_stays_callable(self) -> None:
        # Two servers exposing "search" get distinct python names; both resolve back.
        tools = ["mcp__a__search", "mcp__b__search"]
        assert resolve_mcp_tool_name("search", tools) == "mcp__a__search"
        assert resolve_mcp_tool_name("search_2", tools) == "mcp__b__search"

    def test_no_match(self) -> None:
        assert resolve_mcp_tool_name("missing", ["create_issue"]) is None
