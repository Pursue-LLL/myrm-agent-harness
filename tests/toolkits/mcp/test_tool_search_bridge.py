"""Unit tests: Tool Search Bridge — progressive tool disclosure."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent._factory.tool_search_bridge import (
    BRIDGE_TOOL_NAMES,
    TOOL_CALL_NAME,
    TOOL_DESCRIBE_NAME,
    TOOL_SEARCH_NAME,
    BridgeCatalog,
    CatalogEntry,
    DeferredServerBundle,
    build_bridge_tools,
    build_catalog,
    build_catalog_listing,
    clear_deferred_tools,
    register_deferred_tools,
)
from myrm_agent_harness.toolkits.mcp.config import MCPConfig


def _make_mock_tool(name: str, desc: str = "", n_params: int = 2) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = desc or f"Tool {name} for testing"
    props = {f"param_{i}": {"type": "string", "description": f"p{i}"} for i in range(n_params)}
    mock_schema = MagicMock()
    mock_schema.model_json_schema.return_value = {
        "type": "object",
        "properties": props,
        "required": list(props.keys())[:1],
    }
    tool.get_input_schema = MagicMock(return_value=mock_schema)
    return tool


def _make_bundle(server_name: str, tool_names: list[str]) -> DeferredServerBundle:
    cfg = MCPConfig(name=server_name, type="stdio", command="python", args=["-m", server_name])
    tools = tuple(_make_mock_tool(f"mcp__{server_name}__{t}", f"Do {t} on {server_name}") for t in tool_names)
    return DeferredServerBundle(config=cfg, tools=tools, schema_tokens=100 * len(tools))


class TestBridgeCatalog:
    def test_build_catalog_from_bundles(self) -> None:
        bundle = _make_bundle("github", ["create_issue", "list_repos", "merge_pr"])
        catalog = build_catalog([bundle])
        assert catalog.size == 3

    def test_search_returns_relevant_results(self) -> None:
        bundle = _make_bundle("github", ["create_issue", "list_repos", "merge_pr"])
        catalog = build_catalog([bundle])
        hits = catalog.search("issue")
        assert len(hits) >= 1
        assert any("issue" in h.name for h in hits)

    def test_search_empty_query_returns_empty(self) -> None:
        bundle = _make_bundle("github", ["create_issue"])
        catalog = build_catalog([bundle])
        hits = catalog.search("")
        assert hits == []

    def test_search_no_match_uses_substring_fallback(self) -> None:
        bundle = _make_bundle("github", ["create_issue", "list_repos"])
        catalog = build_catalog([bundle])
        hits = catalog.search("repos")
        assert len(hits) >= 1

    def test_get_by_name(self) -> None:
        bundle = _make_bundle("slack", ["send_message", "list_channels"])
        catalog = build_catalog([bundle])
        entry = catalog.get("mcp__slack__send_message")
        assert entry is not None
        assert entry.server_name == "slack"

    def test_get_nonexistent_returns_none(self) -> None:
        bundle = _make_bundle("slack", ["send_message"])
        catalog = build_catalog([bundle])
        assert catalog.get("nonexistent") is None


class TestShortDesc:
    def test_empty_description(self) -> None:
        from myrm_agent_harness.agent._factory.tool_search_bridge import _short_desc
        assert _short_desc("") == ""
        assert _short_desc("   ") == ""

    def test_sentence_extraction(self) -> None:
        from myrm_agent_harness.agent._factory.tool_search_bridge import _short_desc
        assert _short_desc("First sentence. Second sentence.") == "First sentence."

    def test_long_description_clipped(self) -> None:
        from myrm_agent_harness.agent._factory.tool_search_bridge import _short_desc
        long_text = "A " * 100
        result = _short_desc(long_text, max_chars=20)
        assert len(result) <= 22
        assert result.endswith("\u2026")


class TestCatalogListing:
    def test_small_catalog_produces_full_listing(self) -> None:
        bundle = _make_bundle("github", ["create_issue", "merge_pr"])
        catalog = build_catalog([bundle])
        listing = build_catalog_listing(catalog)
        assert listing is not None
        assert "github" in listing
        assert TOOL_DESCRIBE_NAME in listing

    def test_empty_catalog_returns_none(self) -> None:
        catalog = BridgeCatalog([])
        listing = build_catalog_listing(catalog)
        assert listing is None

    def test_budget_zero_returns_none(self) -> None:
        bundle = _make_bundle("github", ["create_issue"])
        catalog = build_catalog([bundle])
        listing = build_catalog_listing(catalog, max_tokens=0)
        assert listing is None

    def test_tight_budget_degrades_to_names_only(self) -> None:
        tools = [f"tool_{i}" for i in range(30)]
        bundle = _make_bundle("big_server", tools)
        catalog = build_catalog([bundle])
        listing = build_catalog_listing(catalog, max_tokens=80)
        if listing is not None:
            assert "big_server" in listing


class TestBridgeTools:
    def setup_method(self) -> None:
        clear_deferred_tools()

    def teardown_method(self) -> None:
        clear_deferred_tools()

    def test_builds_three_tools(self) -> None:
        bundle = _make_bundle("github", ["create_issue", "list_repos"])
        register_deferred_tools([bundle])
        catalog = build_catalog([bundle])
        tools = build_bridge_tools(catalog)
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == BRIDGE_TOOL_NAMES

    def test_tool_search_returns_json(self) -> None:
        bundle = _make_bundle("github", ["create_issue", "list_repos"])
        register_deferred_tools([bundle])
        catalog = build_catalog([bundle])
        tools = build_bridge_tools(catalog)
        search_tool = next(t for t in tools if t.name == TOOL_SEARCH_NAME)
        result = search_tool.invoke({"query": "issue", "limit": 5})
        parsed = json.loads(result)
        assert "matches" in parsed
        assert parsed["total_available"] == 2

    def test_tool_describe_returns_schema(self) -> None:
        bundle = _make_bundle("github", ["create_issue"])
        register_deferred_tools([bundle])
        catalog = build_catalog([bundle])
        tools = build_bridge_tools(catalog)
        describe_tool = next(t for t in tools if t.name == TOOL_DESCRIBE_NAME)
        result = describe_tool.invoke({"name": "mcp__github__create_issue"})
        parsed = json.loads(result)
        assert "parameters" in parsed
        assert parsed["name"] == "mcp__github__create_issue"

    def test_tool_describe_nonexistent_returns_error(self) -> None:
        bundle = _make_bundle("github", ["create_issue"])
        register_deferred_tools([bundle])
        catalog = build_catalog([bundle])
        tools = build_bridge_tools(catalog)
        describe_tool = next(t for t in tools if t.name == TOOL_DESCRIBE_NAME)
        result = describe_tool.invoke({"name": "nonexistent_tool"})
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_tool_call_invokes_deferred_tool(self) -> None:
        from unittest.mock import AsyncMock

        bundle = _make_bundle("github", ["create_issue"])
        tool_mock = bundle.tools[0]
        tool_mock.ainvoke = AsyncMock(return_value="Issue created!")
        register_deferred_tools([bundle])
        catalog = build_catalog([bundle])
        tools = build_bridge_tools(catalog)
        call_tool = next(t for t in tools if t.name == TOOL_CALL_NAME)
        result = await call_tool.ainvoke({"name": "mcp__github__create_issue", "arguments": {"param_0": "test"}})
        assert "Issue created!" in result

    @pytest.mark.asyncio
    async def test_tool_call_nonexistent_returns_error(self) -> None:
        bundle = _make_bundle("github", ["create_issue"])
        register_deferred_tools([bundle])
        catalog = build_catalog([bundle])
        tools = build_bridge_tools(catalog)
        call_tool = next(t for t in tools if t.name == TOOL_CALL_NAME)
        result = await call_tool.ainvoke({"name": "nonexistent", "arguments": {}})
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_tool_call_exception_returns_error_json(self) -> None:
        """Tool execution exception yields user-friendly JSON error."""
        from unittest.mock import AsyncMock

        bundle = _make_bundle("github", ["create_issue"])
        tool_mock = bundle.tools[0]
        tool_mock.ainvoke = AsyncMock(side_effect=RuntimeError("Connection lost"))
        register_deferred_tools([bundle])
        catalog = build_catalog([bundle])
        tools = build_bridge_tools(catalog)
        call_tool = next(t for t in tools if t.name == TOOL_CALL_NAME)
        result = await call_tool.ainvoke({"name": "mcp__github__create_issue", "arguments": {"param_0": "x"}})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Connection lost" in parsed["error"]

    @pytest.mark.asyncio
    async def test_tool_call_missing_required_args_returns_schema(self) -> None:
        """LLM blind-call with missing required args gets schema hint instead of opaque error."""
        bundle = _make_bundle("github", ["create_issue"])
        register_deferred_tools([bundle])
        catalog = build_catalog([bundle])
        tools = build_bridge_tools(catalog)
        call_tool = next(t for t in tools if t.name == TOOL_CALL_NAME)
        # Call without required param_0
        result = await call_tool.ainvoke({"name": "mcp__github__create_issue", "arguments": {}})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "missing required" in parsed["error"]
        assert "parameters" in parsed
        assert "hint" in parsed


class TestMultiBundleCatalog:
    """Integration: multiple server bundles building one catalog."""

    def test_multi_server_catalog(self) -> None:
        b1 = _make_bundle("github", ["create_issue", "list_repos"])
        b2 = _make_bundle("slack", ["send_message", "list_channels", "react"])
        catalog = build_catalog([b1, b2])
        assert catalog.size == 5
        assert catalog.get("mcp__github__create_issue") is not None
        assert catalog.get("mcp__slack__send_message") is not None

    def test_multi_server_search_cross_server(self) -> None:
        b1 = _make_bundle("github", ["create_issue"])
        b2 = _make_bundle("slack", ["send_message"])
        catalog = build_catalog([b1, b2])
        hits = catalog.search("message")
        assert any("slack" in h.name for h in hits)

    def test_listing_groups_by_server(self) -> None:
        b1 = _make_bundle("github", ["create_issue"])
        b2 = _make_bundle("slack", ["send_message"])
        catalog = build_catalog([b1, b2])
        listing = build_catalog_listing(catalog)
        assert listing is not None
        assert "github" in listing
        assert "slack" in listing


class TestBridgeSecurityPassthrough:
    """Bridge tool_call must resolve to the underlying MCP tool for security evaluation."""

    def test_resolve_permission_type_extracts_inner_name(self) -> None:
        from myrm_agent_harness.core.security.tool_registry import resolve_permission_type

        perm = resolve_permission_type(
            "mcp_tool_call", {"name": "mcp__gmail__send_email", "arguments": {}}
        )
        assert perm == "mcp_invoke"

    def test_resolve_permission_type_without_input_falls_through(self) -> None:
        from myrm_agent_harness.core.security.tool_registry import resolve_permission_type

        perm = resolve_permission_type("mcp_tool_call", None)
        assert perm == "mcp_invoke"

    def test_security_deny_applies_through_bridge(self) -> None:
        """Per-tool DENY must fire identically for direct and bridge calls."""
        from myrm_agent_harness.agent.security.engine import evaluate_tool_call
        from myrm_agent_harness.agent.security.types import (
            PermissionAction,
            PermissionRule,
            SecurityConfig,
        )

        config = SecurityConfig(
            ruleset=(
                PermissionRule(permission="mcp_invoke", pattern="*", action=PermissionAction.ALLOW),
                PermissionRule(permission="mcp_invoke", pattern="mcp__gmail__send_email", action=PermissionAction.DENY),
            ),
        )
        # Direct call
        action_direct, _ = evaluate_tool_call(
            "mcp_invoke", {}, config, tool_name="mcp__gmail__send_email"
        )
        # Bridge call
        action_bridge, _ = evaluate_tool_call(
            "mcp_invoke",
            {"name": "mcp__gmail__send_email", "arguments": {}},
            config,
            tool_name="mcp_tool_call",
        )
        assert action_direct == PermissionAction.DENY
        assert action_bridge == PermissionAction.DENY

    def test_security_allow_applies_through_bridge(self) -> None:
        """Non-DENY tools pass through bridge with correct resolution."""
        from myrm_agent_harness.agent.security.engine import evaluate_tool_call
        from myrm_agent_harness.agent.security.types import (
            PermissionAction,
            PermissionRule,
            SecurityConfig,
        )

        config = SecurityConfig(
            ruleset=(
                PermissionRule(permission="mcp_invoke", pattern="*", action=PermissionAction.ALLOW),
                PermissionRule(permission="mcp_invoke", pattern="mcp__gmail__send_email", action=PermissionAction.DENY),
            ),
        )
        action, _ = evaluate_tool_call(
            "mcp_invoke",
            {"name": "mcp__github__list_repos", "arguments": {}},
            config,
            tool_name="mcp_tool_call",
        )
        assert action == PermissionAction.ALLOW


class TestDeferredToolRegistry:
    def setup_method(self) -> None:
        clear_deferred_tools()

    def teardown_method(self) -> None:
        clear_deferred_tools()

    def test_register_and_clear(self) -> None:
        bundle = _make_bundle("sentry", ["get_issue", "list_events"])
        register_deferred_tools([bundle])
        from myrm_agent_harness.agent._factory.tool_search_bridge import _find_deferred_tool
        assert _find_deferred_tool("mcp__sentry__get_issue") is not None
        clear_deferred_tools()
        assert _find_deferred_tool("mcp__sentry__get_issue") is None
