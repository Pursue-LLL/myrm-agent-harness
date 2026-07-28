"""Tests for MCP tool name resolution SSOT."""

from __future__ import annotations

from myrm_agent_harness.agent.skills.mcp.tool_name_utils import resolve_mcp_tool_name


class TestResolveMcpToolName:
    def test_exact_match(self) -> None:
        assert resolve_mcp_tool_name("create_issue", ["create_issue", "list_prs"]) == "create_issue"

    def test_hyphen_to_underscore(self) -> None:
        assert resolve_mcp_tool_name("create-issue", ["create_issue"]) == "create_issue"

    def test_underscore_to_hyphen(self) -> None:
        assert resolve_mcp_tool_name("create_issue", ["create-issue"]) == "create-issue"

    def test_server_prefix_strip(self) -> None:
        assert resolve_mcp_tool_name("github:create_issue", ["create_issue"]) == "create_issue"

    def test_no_match(self) -> None:
        assert resolve_mcp_tool_name("missing", ["create_issue"]) is None
