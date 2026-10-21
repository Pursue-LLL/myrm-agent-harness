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


class TestRuntimeProxyNameRoundTrip:
    """The identifier L2 prints is the one the generated runtime proxy hands to the resolver."""

    def test_generated_skill_function_passes_the_python_name_through(self, monkeypatch) -> None:
        import asyncio
        import sys
        import types

        from myrm_agent_harness.agent.skills.mcp import client_templates

        calls: list[tuple[str, str]] = []

        async def _fake_call(skill: str, tool: str, kwargs: dict[str, object]) -> str:
            calls.append((skill, tool))
            return "ok"

        namespace: dict[str, object] = {
            "_call": _fake_call,
            "asyncio": asyncio,
            "sys": sys,
            "types": types,
        }
        exec(client_templates._generate_module_system(), namespace)  # noqa: S102 - the generated runtime source
        skill_function = namespace["_SkillFunction"]
        assert asyncio.run(skill_function("mcp_x_skill", "get_ticket_2")(a="1")) == "ok"
        assert calls == [("mcp_x_skill", "get_ticket_2")]

        tools = ["mcp__srv__get-ticket", "mcp__srv__get_ticket"]
        assert resolve_mcp_tool_name("get_ticket_2", tools) == "mcp__srv__get_ticket"


class TestRenderedL2Names:
    """Every identifier printed in L2 must resolve back to a canonical tool."""

    def test_each_rendered_function_name_resolves(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.core_generator import mcp_skill_generator
        from myrm_agent_harness.backends.skills.types import SkillMetadata
        from myrm_agent_harness.backends.skills.types.types_requires import MCPSkillData

        tools = ["mcp__srv__foo.bar", "mcp__srv__foo-bar", "mcp__srv__1foo", "mcp__srv__foo__bar"]
        schemas = {
            tool: {"description": "Query.", "inputSchema": {"properties": {"a": {"type": "string"}}}} for tool in tools
        }
        meta = SkillMetadata(
            name="mcp_srv_skill",
            description="d",
            mcp=MCPSkillData(server="srv", tools=tools, config=[], skill_content=None, tool_schemas=schemas),
        )
        content = mcp_skill_generator.generate_skill_content(meta)
        rendered = [line[2 : line.index("(")] for line in content.splitlines() if line.startswith("- ") and "(" in line]
        assert len(rendered) == len(tools)
        for func_name in rendered:
            assert resolve_mcp_tool_name(func_name, tools) is not None, func_name
