"""Tests for MCP tool name resolution SSOT."""

from __future__ import annotations

from myrm_agent_harness.agent.skills.mcp.tool_name_utils import (
    mcp_tool_short_name,
    resolve_mcp_tool_name,
)


class TestMcpToolShortName:
    def test_strips_server_prefix(self) -> None:
        assert mcp_tool_short_name("mcp__12306__get_current_date") == "get_current_date"

    def test_passthrough_non_prefixed(self) -> None:
        assert mcp_tool_short_name("create_issue") == "create_issue"


class TestResolveMcpToolName:
    def test_exact_match(self) -> None:
        assert (
            resolve_mcp_tool_name("create_issue", ["create_issue", "list_prs"])
            == "create_issue"
        )

    def test_hyphen_to_underscore(self) -> None:
        assert resolve_mcp_tool_name("create-issue", ["create_issue"]) == "create_issue"

    def test_underscore_to_hyphen(self) -> None:
        assert resolve_mcp_tool_name("create_issue", ["create-issue"]) == "create-issue"

    def test_server_prefix_strip(self) -> None:
        assert (
            resolve_mcp_tool_name("github:create_issue", ["create_issue"])
            == "create_issue"
        )

    def test_mcp_double_underscore_suffix_match(self) -> None:
        tools = ["mcp__12306__get_current_date", "mcp__12306__get_tickets"]
        assert (
            resolve_mcp_tool_name("get_current_date", tools)
            == "mcp__12306__get_current_date"
        )
        assert (
            resolve_mcp_tool_name("get-current-date", tools)
            == "mcp__12306__get_current_date"
        )

    def test_ambiguous_suffix_returns_none(self) -> None:
        tools = ["mcp__a__search", "mcp__b__search"]
        assert resolve_mcp_tool_name("search", tools) is None

    def test_no_match(self) -> None:
        assert resolve_mcp_tool_name("missing", ["create_issue"]) is None
