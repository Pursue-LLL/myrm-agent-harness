import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool

from myrm_agent_harness.toolkits.mcp.agent import MCPAgent
from myrm_agent_harness.toolkits.mcp.client import MCPServerConfigProtocol


class DummyConfig(MCPServerConfigProtocol):
    name: str = "test_server"
    connect_timeout: float = 1.0
    execute_timeout: float = 2.0
    tool_include: list[str] | None = None
    tool_exclude: list[str] | None = None

    @property
    def transport(self) -> str:
        return "stdio"

    @property
    def transport_kwargs(self) -> dict[str, Any]:
        return {}


def _make_tool(
    name: str = "test_tool",
    description: str = "a test tool",
    schema: dict[str, Any] | None = None,
    coroutine: Any = None,
    metadata: dict[str, Any] | None = None,
) -> StructuredTool:
    tool = StructuredTool(
        name=name,
        description=description,
        args_schema=schema or {"type": "object", "properties": {"a": {"type": "string"}}},
        coroutine=coroutine or AsyncMock(return_value="ok"),
    )
    if metadata:
        tool.metadata = metadata
    return tool


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.connections = {"test_server": {}}
    client.get_tools = AsyncMock(return_value=[_make_tool()])
    return client


# ---------------------------------------------------------------------------
# Core workflow: single-server get_tools_with_client
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_with_client_single_server(mock_client):
    agent = MCPAgent()
    config = DummyConfig()

    with patch(
        "myrm_agent_harness.toolkits.mcp.agent.MCPClientManager.initialize_client",
        new_callable=AsyncMock,
    ) as mock_init:
        mock_init.return_value = mock_client
        _client, tools = await agent.get_tools_with_client([config])

    assert len(tools) == 1
    assert tools[0].name == "mcp__test_server__test_tool"
    assert hasattr(tools[0], "args_schema")


# ---------------------------------------------------------------------------
# get_tools() shortcut delegates to get_tools_with_client (covers line 234-235)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_shortcut(mock_client):
    agent = MCPAgent()
    config = DummyConfig()

    with patch(
        "myrm_agent_harness.toolkits.mcp.agent.MCPClientManager.initialize_client",
        new_callable=AsyncMock,
    ) as mock_init:
        mock_init.return_value = mock_client
        tools = await agent.get_tools([config])

    assert len(tools) == 1
    assert tools[0].name == "mcp__test_server__test_tool"


# ---------------------------------------------------------------------------
# Empty connections → returns empty list (covers line 249)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_with_client_no_connections():
    agent = MCPAgent()
    empty_client = MagicMock()
    empty_client.connections = {}

    with patch(
        "myrm_agent_harness.toolkits.mcp.agent.MCPClientManager.initialize_client",
        new_callable=AsyncMock,
    ) as mock_init:
        mock_init.return_value = empty_client
        _client, tools = await agent.get_tools_with_client(None)

    assert tools == []


# ---------------------------------------------------------------------------
# Connection timeout handling (covers line 222-228)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_from_server_connection_timeout(mock_client):
    agent = MCPAgent()

    async def slow_get_tools(*_args, **_kwargs):
        await asyncio.sleep(0.5)
        return []

    mock_client.get_tools = slow_get_tools

    with patch("myrm_agent_harness.toolkits.mcp.agent._TOOL_FETCH_RETRY_BACKOFF", 0):
        _server_name, tools, err = await agent.get_tools_from_server(
            mock_client, "test_server", connect_timeout=0.1
        )
    assert err is not None
    assert "connection timed out" in err
    assert tools == []


# ---------------------------------------------------------------------------
# Empty tool list from server (covers line 214)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_from_server_empty_tools():
    agent = MCPAgent()
    client = MagicMock()
    client.get_tools = AsyncMock(return_value=[])

    with patch("myrm_agent_harness.toolkits.mcp.agent._TOOL_FETCH_RETRY_BACKOFF", 0):
        server_name, tools, err = await agent.get_tools_from_server(client, "empty_server")
    assert server_name == "empty_server"
    assert tools == []
    assert err == "not found tools"
    # Bounded retry exhausts all attempts before surfacing the error.
    assert client.get_tools.await_count == 3


# ---------------------------------------------------------------------------
# Bounded retry recovers a transient empty/failed enumeration
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_from_server_retry_then_succeeds():
    agent = MCPAgent()
    client = MagicMock()
    attempts = {"n": 0}

    async def flaky_get_tools(*_args, **_kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return []  # transient empty listing on the first SSE handshake
        return [_make_tool()]

    client.get_tools = flaky_get_tools

    with patch("myrm_agent_harness.toolkits.mcp.agent._TOOL_FETCH_RETRY_BACKOFF", 0):
        _server_name, tools, err = await agent.get_tools_from_server(client, "flaky_server")

    assert err is None
    assert len(tools) == 1
    assert attempts["n"] == 2  # recovered on the second attempt


# ---------------------------------------------------------------------------
# Generic exception in get_tools_from_server (covers line 229-230)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_from_server_generic_exception():
    agent = MCPAgent()
    client = MagicMock()
    client.get_tools = AsyncMock(side_effect=RuntimeError("network error"))

    with patch("myrm_agent_harness.toolkits.mcp.agent._TOOL_FETCH_RETRY_BACKOFF", 0):
        server_name, tools, err = await agent.get_tools_from_server(client, "bad_server")
    assert server_name == "bad_server"
    assert tools == []
    assert "network error" in err


# ---------------------------------------------------------------------------
# CancelledError handling in get_tools_from_server (covers line 217-221)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_from_server_cancelled_error():
    agent = MCPAgent()
    client = MagicMock()
    client.get_tools = AsyncMock(side_effect=asyncio.CancelledError())

    with patch(
        "myrm_agent_harness.toolkits.mcp.errors.reraise_if_genuine_cancel"
    ) as mock_reraise:
        mock_reraise.return_value = None
        server_name, tools, err = await agent.get_tools_from_server(client, "cancel_server")

    assert server_name == "cancel_server"
    assert tools == []
    assert err == "cancelled by SDK"


# ---------------------------------------------------------------------------
# Single server error raises (covers line 270)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_with_client_single_server_error():
    agent = MCPAgent()
    client = MagicMock()
    client.connections = {"fail_server": {}}
    client.get_tools = AsyncMock(return_value=[])

    with patch(
        "myrm_agent_harness.toolkits.mcp.agent.MCPClientManager.initialize_client",
        new_callable=AsyncMock,
    ) as mock_init:
        mock_init.return_value = client

        with pytest.raises(Exception, match="Failed to get tools from fail_server"):
            await agent.get_tools_with_client(None)


# ---------------------------------------------------------------------------
# Multi-server parallel fetch (covers line 278-300)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_parallel_multi_server():
    agent = MCPAgent()
    client = MagicMock()
    client.connections = {"server1": {}, "server2": {}}
    client.get_tools = AsyncMock(
        return_value=[
            _make_tool(
                name="tool_multi",
                description="A" * 3000,
                schema={"type": "object"},
            )
        ]
    )

    with patch(
        "myrm_agent_harness.toolkits.mcp.agent.MCPClientManager.initialize_client",
        new_callable=AsyncMock,
    ) as mock_init:
        mock_init.return_value = client
        _, tools = await agent.get_tools_with_client([])

    assert len(tools) == 2
    assert len(tools[0].description) == 2051


# ---------------------------------------------------------------------------
# Multi-server: task exception propagation (covers line 287-288)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_parallel_task_exception():
    agent = MCPAgent()
    client = MagicMock()
    client.connections = {"s1": {}, "s2": {}}
    client.get_tools = AsyncMock(side_effect=RuntimeError("boom"))

    with patch(
        "myrm_agent_harness.toolkits.mcp.agent.MCPClientManager.initialize_client",
        new_callable=AsyncMock,
    ) as mock_init:
        mock_init.return_value = client

        with pytest.raises(Exception, match="boom"):
            await agent.get_tools_with_client(None)


# ---------------------------------------------------------------------------
# Multi-server: error in one server propagates (covers line 293)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_parallel_server_error():
    agent = MCPAgent()
    client = MagicMock()
    client.connections = {"ok_server": {}, "err_server": {}}

    call_count = 0

    async def side_effect_get_tools(*_args, server_name: str = "", **_kwargs):
        nonlocal call_count
        call_count += 1
        if server_name == "err_server":
            return []
        return [_make_tool()]

    client.get_tools = side_effect_get_tools

    with patch(
        "myrm_agent_harness.toolkits.mcp.agent.MCPClientManager.initialize_client",
        new_callable=AsyncMock,
    ) as mock_init:
        mock_init.return_value = client

        with pytest.raises(Exception, match="Failed to get tools"):
            await agent.get_tools_with_client(None)


# ---------------------------------------------------------------------------
# Tool server mapping lookup
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tool_server_mapping(mock_client):
    agent = MCPAgent()
    config = DummyConfig()

    with patch(
        "myrm_agent_harness.toolkits.mcp.agent.MCPClientManager.initialize_client",
        new_callable=AsyncMock,
    ) as mock_init:
        mock_init.return_value = mock_client
        _, tools = await agent.get_tools_with_client([config])

    assert agent.get_tool_server_name(tools[0]) == "test_server"
    assert agent.get_server_name_by_tool_name("mcp__test_server__test_tool") == "test_server"
    assert agent.get_server_name_by_tool_name("nonexistent") == "unknown_server"


# ---------------------------------------------------------------------------
# _wrap_tools_with_timeout: skips tools without coroutine (covers line 91)
# ---------------------------------------------------------------------------
def test_wrap_tools_with_timeout_no_coroutine():
    agent = MCPAgent()
    tool = MagicMock()
    tool.coroutine = None
    agent._wrap_tools_with_timeout([tool], 10.0)
    assert tool.coroutine is None


# ---------------------------------------------------------------------------
# _wrap_tools_with_timeout: timeout fires (covers line 102-108)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wrap_tools_timeout_fires():
    agent = MCPAgent()

    async def slow_fn(*_a, **_kw):
        await asyncio.sleep(5)

    tool = _make_tool(coroutine=slow_fn)
    agent._wrap_tools_with_timeout([tool], timeout=0.05)

    result = await tool.coroutine()
    assert "timed out" in result


# ---------------------------------------------------------------------------
# _wrap_tools_with_timeout: normal execution (covers line 102-104)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wrap_tools_normal_execution():
    agent = MCPAgent()

    async def fast_fn(*_a, **_kw):
        return "success"

    tool = _make_tool(coroutine=fast_fn)
    agent._wrap_tools_with_timeout([tool], timeout=5.0)

    result = await tool.coroutine()
    assert result == "success"


# ---------------------------------------------------------------------------
# _sanitize_tools: coercion wrapper (covers line 150-154)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sanitize_tools_coercion():
    agent = MCPAgent()
    inner_mock = AsyncMock(return_value="coerced_result")
    tool = _make_tool(
        schema={"type": "object", "properties": {"count": {"type": "integer"}}},
        coroutine=inner_mock,
    )
    agent._sanitize_tools([tool])
    result = await tool.coroutine(count="42")
    assert result == "coerced_result"
    inner_mock.assert_called_once()


# ---------------------------------------------------------------------------
# _sanitize_tools: canonicalize sorts schema keys in full pipeline
# ---------------------------------------------------------------------------
def test_sanitize_tools_canonicalizes_schema_keys():
    """Verify that _sanitize_tools produces deterministic key ordering
    regardless of the original key order from MCP server."""
    agent = MCPAgent()
    schema_shuffled: dict[str, Any] = {
        "required": ["z_param", "a_param"],
        "type": "object",
        "properties": {
            "z_param": {"type": "string", "description": "last"},
            "a_param": {"type": "integer", "description": "first"},
        },
    }
    tool = _make_tool(schema=schema_shuffled)
    agent._sanitize_tools([tool])

    result_schema = tool.args_schema
    assert list(result_schema.keys()) == ["properties", "required", "type"]
    assert list(result_schema["properties"].keys()) == ["a_param", "z_param"]
    assert result_schema["required"] == ["a_param", "z_param"]
    inner_a = result_schema["properties"]["a_param"]
    assert list(inner_a.keys()) == ["description", "type"]


# ---------------------------------------------------------------------------
# _sanitize_tools: two schemas with different key orders produce same result
# ---------------------------------------------------------------------------
def test_sanitize_tools_deterministic_across_restarts():
    """Simulate MCP server restart returning same schema with different key order.
    After _sanitize_tools, both must serialize identically (cache-stable)."""
    import json as _json

    agent = MCPAgent()
    schema_v1: dict[str, Any] = {
        "type": "object",
        "properties": {"repo": {"type": "string"}, "branch": {"type": "string"}},
        "required": ["repo", "branch"],
    }
    schema_v2: dict[str, Any] = {
        "required": ["branch", "repo"],
        "properties": {"branch": {"type": "string"}, "repo": {"type": "string"}},
        "type": "object",
    }
    tool1 = _make_tool(name="git_clone", schema=schema_v1)
    tool2 = _make_tool(name="git_clone", schema=schema_v2)
    agent._sanitize_tools([tool1])
    agent._sanitize_tools([tool2])

    assert _json.dumps(tool1.args_schema) == _json.dumps(tool2.args_schema)


# ---------------------------------------------------------------------------
# _register_tool_annotations: extracts MCP annotations (covers line 178)
# ---------------------------------------------------------------------------
def test_register_tool_annotations():
    agent = MCPAgent()
    tool = _make_tool(
        metadata={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    )

    with patch("myrm_agent_harness.toolkits.mcp.agent.register_ptc_safety_metadata") as mock_reg:
        agent._register_tool_annotations([tool], "my-server")

    mock_reg.assert_called_once()
    call_args = mock_reg.call_args
    assert call_args[0][0] == "mcp_my_server_skill"
    assert call_args[0][1] == "test_tool"
    safety = call_args[0][2]
    assert safety.is_read_only is True
    assert safety.is_concurrent_safe is True
    assert safety.is_destructive is False
    assert safety.is_idempotent is True


# ---------------------------------------------------------------------------
# _register_tool_annotations: server name normalization
# ---------------------------------------------------------------------------
def test_register_tool_annotations_name_normalization():
    agent = MCPAgent()
    tool = _make_tool(metadata={})

    with patch("myrm_agent_harness.toolkits.mcp.agent.register_ptc_safety_metadata") as mock_reg:
        agent._register_tool_annotations([tool], "mcp_already_skill")

    assert mock_reg.call_args[0][0] == "mcp_already_skill"


def test_register_tool_annotations_plain_name():
    agent = MCPAgent()
    tool = _make_tool(metadata={})

    with patch("myrm_agent_harness.toolkits.mcp.agent.register_ptc_safety_metadata") as mock_reg:
        agent._register_tool_annotations([tool], "github")

    assert mock_reg.call_args[0][0] == "mcp_github_skill"


# ---------------------------------------------------------------------------
# Description truncation boundary
# ---------------------------------------------------------------------------
def test_enforce_description_limits_no_truncation():
    agent = MCPAgent()
    tool = _make_tool(description="short")
    agent._enforce_description_limits([tool])
    assert tool.description == "short"


def test_enforce_description_limits_exact_boundary():
    agent = MCPAgent()
    tool = _make_tool(description="x" * 2048)
    agent._enforce_description_limits([tool])
    assert len(tool.description) == 2048


def test_enforce_description_limits_truncates():
    agent = MCPAgent()
    tool = _make_tool(description="x" * 3000)
    agent._enforce_description_limits([tool])
    assert len(tool.description) == 2051
    assert tool.description.endswith("...")


# ---------------------------------------------------------------------------
# _sanitize_tools: nested arg restoration via dot-keys (covers line 153)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sanitize_tools_flattened_dot_keys():
    """When schema exceeds depth threshold, flatten_deep_schema activates.
    The coercion wrapper must then restore nested structure from dot-path keys."""
    agent = MCPAgent()
    inner_mock = AsyncMock(return_value="nested_ok")
    deep_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "level1": {
                "type": "object",
                "properties": {
                    "level2": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "string"},
                        },
                    },
                },
            },
        },
    }
    tool = _make_tool(schema=deep_schema, coroutine=inner_mock)
    agent._sanitize_tools([tool])

    result = await tool.coroutine(**{"level1.level2.value": "deep"})
    assert result == "nested_ok"
    call_kwargs = inner_mock.call_args[1]
    assert "level1" in call_kwargs
    assert call_kwargs["level1"]["level2"]["value"] == "deep"


# ---------------------------------------------------------------------------
# Multi-server: gather returns Exception object (covers line 287-288)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_parallel_gather_exception_object():
    """When asyncio.gather(return_exceptions=True) returns an Exception
    object (not a tuple), it must be raised."""
    agent = MCPAgent()
    client = MagicMock()
    client.connections = {"s1": {}, "s2": {}}

    with patch(
        "myrm_agent_harness.toolkits.mcp.agent.MCPClientManager.initialize_client",
        new_callable=AsyncMock,
    ) as mock_init:
        mock_init.return_value = client

        with patch.object(
            agent,
            "get_tools_from_server",
            side_effect=[
                (_make_tool(),),
                RuntimeError("gather_boom"),
            ],
        ), pytest.raises(RuntimeError, match="gather_boom"):
            await agent.get_tools_with_client(None)


# ---------------------------------------------------------------------------
# _apply_tool_filter: unit tests
# ---------------------------------------------------------------------------
class TestApplyToolFilter:
    def test_no_filter_returns_all(self) -> None:
        tools = [_make_tool(name="a"), _make_tool(name="b")]
        result = MCPAgent._apply_tool_filter(tools, "srv", None, None)
        assert len(result) == 2

    def test_empty_lists_return_all(self) -> None:
        tools = [_make_tool(name="a"), _make_tool(name="b")]
        result = MCPAgent._apply_tool_filter(tools, "srv", [], [])
        assert len(result) == 2

    def test_include_filters(self) -> None:
        tools = [_make_tool(name="read"), _make_tool(name="write"), _make_tool(name="delete")]
        result = MCPAgent._apply_tool_filter(tools, "srv", ["read", "write"], None)
        assert [t.name for t in result] == ["read", "write"]

    def test_exclude_filters(self) -> None:
        tools = [_make_tool(name="read"), _make_tool(name="write"), _make_tool(name="delete")]
        result = MCPAgent._apply_tool_filter(tools, "srv", None, ["delete"])
        assert [t.name for t in result] == ["read", "write"]

    def test_include_takes_precedence(self) -> None:
        tools = [_make_tool(name="read"), _make_tool(name="write"), _make_tool(name="delete")]
        result = MCPAgent._apply_tool_filter(tools, "srv", ["read"], ["write"])
        assert [t.name for t in result] == ["read"]

    def test_include_all_removed(self) -> None:
        tools = [_make_tool(name="a"), _make_tool(name="b")]
        result = MCPAgent._apply_tool_filter(tools, "srv", ["nonexistent"], None)
        assert result == []

    def test_exclude_all_removed(self) -> None:
        tools = [_make_tool(name="a"), _make_tool(name="b")]
        result = MCPAgent._apply_tool_filter(tools, "srv", None, ["a", "b"])
        assert result == []


# ---------------------------------------------------------------------------
# End-to-end: tool_include config filters tools in get_tools_with_client
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_with_client_applies_tool_filter():
    agent = MCPAgent()
    config = DummyConfig()
    config.tool_include = ["wanted_tool"]

    client = MagicMock()
    client.connections = {"test_server": {}}
    client.get_tools = AsyncMock(
        return_value=[_make_tool(name="wanted_tool"), _make_tool(name="unwanted_tool")]
    )

    with patch(
        "myrm_agent_harness.toolkits.mcp.agent.MCPClientManager.initialize_client",
        new_callable=AsyncMock,
    ) as mock_init:
        mock_init.return_value = client
        _, tools = await agent.get_tools_with_client([config])

    assert len(tools) == 1
    assert tools[0].name == "mcp__test_server__wanted_tool"


# ---------------------------------------------------------------------------
# _prefix_tool_names: unit tests
# ---------------------------------------------------------------------------
class TestPrefixToolNames:
    def test_basic_prefix(self) -> None:
        tools = [_make_tool(name="search"), _make_tool(name="create")]
        MCPAgent._prefix_tool_names(tools, "github")
        assert [t.name for t in tools] == ["mcp__github__search", "mcp__github__create"]

    def test_special_chars_sanitized(self) -> None:
        tools = [_make_tool(name="my-tool")]
        MCPAgent._prefix_tool_names(tools, "my-server")
        assert tools[0].name == "mcp__my_server__my_tool"

    def test_multiple_servers_no_collision(self) -> None:
        github_tools = [_make_tool(name="search_repos")]
        gitlab_tools = [_make_tool(name="search_repos")]
        MCPAgent._prefix_tool_names(github_tools, "github")
        MCPAgent._prefix_tool_names(gitlab_tools, "gitlab")
        assert github_tools[0].name == "mcp__github__search_repos"
        assert gitlab_tools[0].name == "mcp__gitlab__search_repos"
        assert github_tools[0].name != gitlab_tools[0].name

    def test_process_session_tools_applies_prefix(self) -> None:
        tools = [_make_tool(name="read"), _make_tool(name="write")]
        result = MCPAgent.process_session_tools(
            tools, "my_server", None, None, 10.0,
        )
        assert [t.name for t in result] == ["mcp__my_server__read", "mcp__my_server__write"]

    def test_filter_uses_original_names(self) -> None:
        """tool_include uses original names (before prefixing)."""
        tools = [_make_tool(name="read"), _make_tool(name="write")]
        result = MCPAgent.process_session_tools(
            tools, "srv", ["read"], None, 10.0,
        )
        assert len(result) == 1
        assert result[0].name == "mcp__srv__read"

    def test_builtin_name_collision_avoided(self) -> None:
        """An MCP tool named 'file_read_tool' gets prefixed, no collision."""
        tools = [_make_tool(name="file_read_tool")]
        result = MCPAgent.process_session_tools(
            tools, "remote", None, None, 10.0,
        )
        assert result[0].name == "mcp__remote__file_read_tool"

    def test_double_underscore_eliminates_ambiguity(self) -> None:
        """server 'github_actions' + tool 'run' differs from server 'github' + tool 'actions_run'."""
        tools_a = [_make_tool(name="run")]
        tools_b = [_make_tool(name="actions_run")]
        MCPAgent._prefix_tool_names(tools_a, "github_actions")
        MCPAgent._prefix_tool_names(tools_b, "github")
        assert tools_a[0].name == "mcp__github_actions__run"
        assert tools_b[0].name == "mcp__github__actions_run"
        assert tools_a[0].name != tools_b[0].name

    def test_server_name_with_consecutive_hyphens(self) -> None:
        """Consecutive hyphens collapse to single underscore after sanitize."""
        tools = [_make_tool(name="echo")]
        MCPAgent._prefix_tool_names(tools, "my--server")
        assert tools[0].name == "mcp__my_server__echo"

    def test_unicode_server_name(self) -> None:
        """Non-ASCII characters sanitized to underscores."""
        tools = [_make_tool(name="list")]
        MCPAgent._prefix_tool_names(tools, "飞书mcp")
        assert tools[0].name == "mcp__mcp__list"

    def test_roundtrip_prefix_parse(self) -> None:
        """Prefixed name can be parsed back to (server, tool)."""
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        tools = [_make_tool(name="search_repos")]
        MCPAgent._prefix_tool_names(tools, "github")
        result = parse_mcp_tool_name(tools[0].name)
        assert result == ("github", "search_repos")


class TestParseMcpToolName:
    def test_valid_name(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        result = parse_mcp_tool_name("mcp__github__search_repos")
        assert result == ("github", "search_repos")

    def test_server_with_underscore(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        result = parse_mcp_tool_name("mcp__github_actions__run")
        assert result == ("github_actions", "run")

    def test_non_mcp_name(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        assert parse_mcp_tool_name("file_read_tool") is None

    def test_is_mcp_tool_name(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import is_mcp_tool_name

        assert is_mcp_tool_name("mcp__github__search") is True
        assert is_mcp_tool_name("file_read_tool") is False
        assert is_mcp_tool_name("mcp__") is False

    def test_no_tool_delimiter(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        assert parse_mcp_tool_name("mcp__serveronly") is None

    def test_empty_server(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        assert parse_mcp_tool_name("mcp____tool") is None

    def test_empty_tool_part(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        result = parse_mcp_tool_name("mcp__server__")
        assert result == ("server", "")

    def test_tool_with_nested_double_underscore(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        result = parse_mcp_tool_name("mcp__server__tool__extra")
        assert result == ("server", "tool__extra")

    def test_is_mcp_tool_name_edge_cases(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import is_mcp_tool_name

        assert is_mcp_tool_name("mcp__s__t") is True
        assert is_mcp_tool_name("mcp__a__") is True
        assert is_mcp_tool_name("MCP__server__tool") is False
        assert is_mcp_tool_name("") is False

    def test_parse_empty_string(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        assert parse_mcp_tool_name("") is None


class TestPrefixEdgeCases:
    def test_empty_tool_list(self) -> None:
        tools: list[StructuredTool] = []
        MCPAgent._prefix_tool_names(tools, "srv")
        assert tools == []

    def test_annotations_use_prefixed_names(self) -> None:
        """_register_tool_annotations runs after prefix — tool.name is prefixed."""
        tools = [_make_tool(name="search", metadata={"readOnlyHint": True})]
        result = MCPAgent.process_session_tools(tools, "gh", None, None, 10.0)
        assert result[0].name == "mcp__gh__search"

    def test_sanitize_none_input(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import sanitize_mcp_name_component

        assert sanitize_mcp_name_component(None) == "unnamed"  # type: ignore[arg-type]

