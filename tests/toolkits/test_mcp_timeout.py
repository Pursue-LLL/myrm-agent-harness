"""Tests for MCP timeout protection.

Covers:
- MCPConfig timeout field defaults and custom values
- MCPAgent._wrap_tools_with_timeout execution timeout
- MCPAgent.get_tools_from_server connection timeout
- MCPClientManager.initialize_client with MCPServerConfigProtocol
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.toolkits.mcp.agent import MCPAgent
from myrm_agent_harness.toolkits.mcp.client import MCPClientManager
from myrm_agent_harness.toolkits.mcp.config import MCPConfig


class TestMCPConfigTimeoutFields:
    """Test MCPConfig connect_timeout and execute_timeout fields."""

    def test_default_connect_timeout(self) -> None:
        cfg = MCPConfig(name="test", type="stdio", command="echo", description="test")
        assert cfg.connect_timeout == 15.0

    def test_default_execute_timeout(self) -> None:
        cfg = MCPConfig(name="test", type="stdio", command="echo", description="test")
        assert cfg.execute_timeout == 120.0

    def test_custom_connect_timeout(self) -> None:
        cfg = MCPConfig(name="test", type="stdio", command="echo", description="test", connect_timeout=30.0)
        assert cfg.connect_timeout == 30.0

    def test_custom_execute_timeout(self) -> None:
        cfg = MCPConfig(name="test", type="stdio", command="echo", description="test", execute_timeout=300.0)
        assert cfg.execute_timeout == 300.0

    def test_timeout_fields_serialization(self) -> None:
        cfg = MCPConfig(
            name="db-server",
            type="sse",
            url="http://localhost:8080",
            description="DB",
            connect_timeout=10.0,
            execute_timeout=60.0,
        )
        data = cfg.model_dump()
        assert data["connect_timeout"] == 10.0
        assert data["execute_timeout"] == 60.0


class TestWrapToolsWithTimeout:
    """Test MCPAgent._wrap_tools_with_timeout."""

    @staticmethod
    def _make_tool(name: str, coroutine: object) -> BaseTool:
        tool = MagicMock(spec=BaseTool)
        tool.name = name
        tool.coroutine = coroutine
        return tool

    @pytest.mark.asyncio
    async def test_fast_tool_succeeds(self) -> None:
        async def fast_fn(*args: object, **kwargs: object) -> str:
            return "result"

        tool = self._make_tool("fast", fast_fn)
        MCPAgent._wrap_tools_with_timeout([tool], timeout=5.0)
        result = await tool.coroutine()
        assert "result" in result
        assert "UNTRUSTED_DATA" in result

    @pytest.mark.asyncio
    async def test_slow_tool_times_out(self) -> None:
        async def slow_fn(*args: object, **kwargs: object) -> str:
            await asyncio.sleep(10)
            return "never"

        tool = self._make_tool("slow", slow_fn)
        MCPAgent._wrap_tools_with_timeout([tool], timeout=0.1)
        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "timed out" in result
        assert "slow" in result

    def test_sync_tool_skipped(self) -> None:
        tool = self._make_tool("sync", None)
        MCPAgent._wrap_tools_with_timeout([tool], timeout=5.0)
        assert tool.coroutine is None

    @pytest.mark.asyncio
    async def test_timeout_returns_error_message_not_exception(self) -> None:
        async def hang(*args: object, **kwargs: object) -> str:
            await asyncio.sleep(100)
            return "unreachable"

        tool = self._make_tool("hang_tool", hang)
        MCPAgent._wrap_tools_with_timeout([tool], timeout=0.05)
        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "hang_tool" in result
        assert "0.05s" in result

    @pytest.mark.asyncio
    async def test_multiple_tools_wrapped_independently(self) -> None:
        async def fn_a(*args: object, **kwargs: object) -> str:
            return "a"

        async def fn_b(*args: object, **kwargs: object) -> str:
            await asyncio.sleep(10)
            return "b"

        tool_a = self._make_tool("tool_a", fn_a)
        tool_b = self._make_tool("tool_b", fn_b)
        MCPAgent._wrap_tools_with_timeout([tool_a, tool_b], timeout=0.1)

        result_a = await tool_a.coroutine()
        assert "a" in result_a
        assert "UNTRUSTED_DATA" in result_a

        result_b = await tool_b.coroutine()
        assert "timed out" in result_b


class TestGetToolsFromServerTimeout:
    """Test MCPAgent.get_tools_from_server connection timeout."""

    @pytest.mark.asyncio
    async def test_connection_timeout(self) -> None:
        agent = MCPAgent()
        mock_client = MagicMock()

        async def slow_get_tools(server_name: str) -> list[BaseTool]:
            await asyncio.sleep(10)
            return []

        mock_client.get_tools = slow_get_tools

        with patch("myrm_agent_harness.toolkits.mcp.agent._TOOL_FETCH_RETRY_BACKOFF", 0):
            server_name, tools, error = await agent.get_tools_from_server(
                mock_client,
                "slow_server",
                connect_timeout=0.1,
            )
        assert server_name == "slow_server"
        assert tools == []
        assert error is not None
        assert "timed out" in error

    @pytest.mark.asyncio
    async def test_fast_connection_succeeds(self) -> None:
        agent = MCPAgent()
        mock_client = MagicMock()

        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"

        async def fast_get_tools(server_name: str) -> list[BaseTool]:
            return [mock_tool]

        mock_client.get_tools = fast_get_tools

        server_name, tools, error = await agent.get_tools_from_server(
            mock_client,
            "fast_server",
            connect_timeout=5.0,
        )
        assert server_name == "fast_server"
        assert len(tools) == 1
        assert error is None

    @pytest.mark.asyncio
    async def test_empty_tools_returns_error(self) -> None:
        agent = MCPAgent()
        mock_client = MagicMock()
        mock_client.get_tools = AsyncMock(return_value=[])

        with patch("myrm_agent_harness.toolkits.mcp.agent._TOOL_FETCH_RETRY_BACKOFF", 0):
            _server_name, _tools, error = await agent.get_tools_from_server(
                mock_client,
                "empty_server",
            )
        assert error == "not found tools"

    @pytest.mark.asyncio
    async def test_exception_returns_error_string(self) -> None:
        agent = MCPAgent()
        mock_client = MagicMock()
        mock_client.get_tools = AsyncMock(side_effect=RuntimeError("connection refused"))

        with patch("myrm_agent_harness.toolkits.mcp.agent._TOOL_FETCH_RETRY_BACKOFF", 0):
            _server_name, _tools, error = await agent.get_tools_from_server(
                mock_client,
                "broken_server",
            )
        assert error is not None
        assert "connection refused" in error


class TestClientManagerProtocol:
    """Test MCPClientManager with timeout fields in protocol."""

    @pytest.mark.asyncio
    async def test_initialize_with_config_timeout(self) -> None:
        cfg = MCPConfig(
            name="test",
            type="stdio",
            command="echo",
            description="test",
            connect_timeout=5.0,
            execute_timeout=60.0,
        )

        with patch("myrm_agent_harness.toolkits.mcp.client.MultiServerMCPClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.connections = {}
            mock_cls.return_value = mock_client

            result = await MCPClientManager.initialize_client([cfg])
            assert result is mock_client

    @pytest.mark.asyncio
    async def test_initialize_empty_config(self) -> None:
        result = await MCPClientManager.initialize_client(None)
        assert result is not None


class TestGetToolsWithClientTimeout:
    """Test MCPAgent.get_tools_with_client passes timeouts correctly."""

    @pytest.mark.asyncio
    async def test_per_server_timeout_applied(self) -> None:
        cfg1 = MCPConfig(
            name="server1",
            type="stdio",
            command="echo",
            description="s1",
            execute_timeout=30.0,
            connect_timeout=5.0,
        )
        cfg2 = MCPConfig(
            name="server2",
            type="stdio",
            command="echo",
            description="s2",
            execute_timeout=300.0,
            connect_timeout=20.0,
        )

        agent = MCPAgent()

        mock_tool1 = MagicMock(spec=BaseTool)
        mock_tool1.name = "tool1"
        mock_tool1.description = "desc1"
        mock_tool1.coroutine = AsyncMock(return_value="r1")

        mock_tool2 = MagicMock(spec=BaseTool)
        mock_tool2.name = "tool2"
        mock_tool2.description = "desc2"
        mock_tool2.coroutine = AsyncMock(return_value="r2")

        mock_client = MagicMock()
        mock_client.connections = {"server1": MagicMock(), "server2": MagicMock()}

        async def mock_get_tools(server_name: str) -> list[BaseTool]:
            if server_name == "server1":
                return [mock_tool1]
            return [mock_tool2]

        mock_client.get_tools = mock_get_tools

        with patch.object(MCPClientManager, "initialize_client", return_value=mock_client):
            _client, tools = await agent.get_tools_with_client([cfg1, cfg2])

        assert len(tools) == 2


class TestMCPConfigValidation:
    """Test MCPConfig validation with timeout fields."""

    def test_sse_requires_url(self) -> None:
        with pytest.raises(ValueError, match="requires 'url'"):
            MCPConfig(name="bad", type="sse", description="test")

    def test_stdio_requires_command(self) -> None:
        with pytest.raises(ValueError, match="requires 'command'"):
            MCPConfig(name="bad", type="stdio", description="test")

    def test_streamable_http_with_timeout(self) -> None:
        cfg = MCPConfig(
            name="http",
            type="streamable_http",
            url="http://x",
            description="test",
            connect_timeout=5.0,
        )
        assert cfg.connect_timeout == 5.0


class TestClientConfigConversion:
    """Test MCPClientManager.convert_server_config_to_client_format."""

    def test_sse_config(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="http://x", description="d")
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["transport"] == "sse"
        assert result["url"] == "http://x"

    def test_streamable_http_config(self) -> None:
        cfg = MCPConfig(name="s", type="streamable_http", url="http://y", description="d")
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["transport"] == "streamable_http"

    def test_stdio_config(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="node", args=["server.js"], description="d")
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["transport"] == "stdio"
        assert result["command"] == "node"
        assert result["args"] == ["server.js"]

    def test_stdio_no_args(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="echo", description="d")
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["args"] == []

    def test_unsupported_type(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.type = "websocket"
        mock_cfg.url = "ws://x"
        mock_cfg.command = None
        mock_cfg.args = None
        mock_cfg.extra_params = None
        mock_cfg.connect_timeout = 15.0
        mock_cfg.execute_timeout = 120.0
        with pytest.raises(ValueError, match="Unsupported transport"):
            MCPClientManager.convert_server_config_to_client_format(mock_cfg)

    def test_extra_params_merged(self) -> None:
        cfg = MCPConfig(
            name="s",
            type="sse",
            url="http://x",
            description="d",
            extra_params={"custom_key": "val"},
        )
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["custom_key"] == "val"


class TestClientAuthInjection:
    """Test MCPClientManager._inject_auth_headers."""

    @pytest.mark.asyncio
    async def test_auth_headers_injected_for_sse(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="http://x", description="d")
        mock_provider = AsyncMock()
        mock_provider.get_auth_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
        cfg.auth_provider = mock_provider

        client_config: dict[str, str | list[str]] = {"url": "http://x", "transport": "sse"}
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        assert client_config["headers"] == {"Authorization": "Bearer tok"}

    @pytest.mark.asyncio
    async def test_auth_skipped_for_stdio(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="echo", description="d")
        mock_provider = AsyncMock()
        cfg.auth_provider = mock_provider

        client_config: dict[str, str | list[str]] = {"command": "echo", "transport": "stdio"}
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        assert "headers" not in client_config

    @pytest.mark.asyncio
    async def test_no_auth_provider(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="http://x", description="d")
        client_config: dict[str, str | list[str]] = {"url": "http://x", "transport": "sse"}
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        assert "headers" not in client_config

    @pytest.mark.asyncio
    async def test_auth_failure_non_fatal(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="http://x", description="d")
        mock_provider = AsyncMock()
        mock_provider.get_auth_headers = AsyncMock(side_effect=RuntimeError("auth fail"))
        cfg.auth_provider = mock_provider

        client_config: dict[str, str | list[str]] = {"url": "http://x", "transport": "sse"}
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        assert "headers" not in client_config

    @pytest.mark.asyncio
    async def test_empty_auth_headers_no_inject(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="http://x", description="d")
        mock_provider = AsyncMock()
        mock_provider.get_auth_headers = AsyncMock(return_value={})
        cfg.auth_provider = mock_provider

        client_config: dict[str, str | list[str]] = {"url": "http://x", "transport": "sse"}
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        assert "headers" not in client_config


class TestClientInitializeEdgeCases:
    """Test MCPClientManager.initialize_client edge cases."""

    @pytest.mark.asyncio
    async def test_config_error_skips_server(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.name = "bad"
        mock_cfg.type = "websocket"
        mock_cfg.url = None
        mock_cfg.command = None
        mock_cfg.args = None
        mock_cfg.extra_params = None
        mock_cfg.required_secrets = None
        mock_cfg.auth_provider = None
        mock_cfg.connect_timeout = 15.0
        mock_cfg.execute_timeout = 120.0

        with patch("myrm_agent_harness.toolkits.mcp.client.MultiServerMCPClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            result = await MCPClientManager.initialize_client([mock_cfg])
            assert result is not None

    @pytest.mark.asyncio
    async def test_client_init_exception(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="echo", description="d")
        call_count = 0

        original_cls = __import__(
            "langchain_mcp_adapters.client", fromlist=["MultiServerMCPClient"]
        ).MultiServerMCPClient

        def _side_effect(*args: object, **kwargs: object) -> object:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("init failed")
            return original_cls(*args, **kwargs)

        with patch(
            "myrm_agent_harness.toolkits.mcp.client.MultiServerMCPClient",
            side_effect=_side_effect,
        ):
            result = await MCPClientManager.initialize_client([cfg])
            assert result is not None


class TestAgentToolMapping:
    """Test MCPAgent tool-server mapping methods."""

    def test_get_tool_server_name(self) -> None:
        agent = MCPAgent()
        tool = MagicMock(spec=BaseTool)
        tool.name = "my_tool"
        tool.description = "does stuff"
        agent._store_tool_server_mapping([tool], "server_a")
        assert agent.get_tool_server_name(tool) == "server_a"

    def test_get_server_name_by_tool_name(self) -> None:
        agent = MCPAgent()
        tool = MagicMock(spec=BaseTool)
        tool.name = "search"
        tool.description = "search things"
        agent._store_tool_server_mapping([tool], "search_server")
        assert agent.get_server_name_by_tool_name("search") == "search_server"

    def test_unknown_tool_returns_unknown(self) -> None:
        agent = MCPAgent()
        assert agent.get_server_name_by_tool_name("nonexistent") == "unknown_server"

    def test_description_enforcement(self) -> None:
        tool = MagicMock(spec=BaseTool)
        tool.name = "verbose"
        tool.description = "x" * 5000
        MCPAgent._enforce_description_limits([tool])
        assert len(tool.description) <= 2048 + 3


class TestGetToolsFromServerCancelledError:
    """Test CancelledError handling in get_tools_from_server."""

    @pytest.mark.asyncio
    async def test_sdk_cancel_scope_leak_returns_error(self) -> None:
        """MCP SDK anyio cancel scope leak should not crash the agent."""
        agent = MCPAgent()
        mock_client = MagicMock()

        async def leaky_get_tools(server_name: str) -> list[BaseTool]:
            raise asyncio.CancelledError()

        mock_client.get_tools = leaky_get_tools

        with patch(
            "myrm_agent_harness.toolkits.mcp.errors.reraise_if_genuine_cancel",
            side_effect=lambda e: None,
        ):
            server_name, tools, error = await agent.get_tools_from_server(
                mock_client,
                "leaky_server",
            )
        assert server_name == "leaky_server"
        assert tools == []
        assert error == "cancelled by SDK"

    @pytest.mark.asyncio
    async def test_genuine_cancel_reraised(self) -> None:
        """Genuine user cancellation should propagate."""
        agent = MCPAgent()
        mock_client = MagicMock()

        cancel_error = asyncio.CancelledError()

        async def user_cancel(server_name: str) -> list[BaseTool]:
            raise cancel_error

        mock_client.get_tools = user_cancel

        def _reraise(e: asyncio.CancelledError) -> None:
            raise e

        with patch(
            "myrm_agent_harness.toolkits.mcp.errors.reraise_if_genuine_cancel",
            side_effect=_reraise,
        ), pytest.raises(asyncio.CancelledError):
            await agent.get_tools_from_server(mock_client, "cancel_server")
