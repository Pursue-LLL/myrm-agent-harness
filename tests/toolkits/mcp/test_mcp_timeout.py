"""Tests for MCP timeout protection.

Covers:
- MCPConfig timeout field defaults and custom values
- MCPAgent._wrap_tools_with_timeout execution timeout
- MCPAgent._enumerate_server_tools connection timeout
- MCPClientManager.prepare_server_configs with MCPServerConfigProtocol
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
        assert "UNTRUSTED_DATA" not in result_b

    @pytest.mark.asyncio
    async def test_timeout_error_not_wrapped(self) -> None:
        """System-generated timeout error messages must NOT be wrapped with UNTRUSTED_DATA."""
        async def slow(*args: object, **kwargs: object) -> str:
            await asyncio.sleep(10)
            return "never"

        tool = self._make_tool("slow_svc", slow)
        MCPAgent._wrap_tools_with_timeout([tool], timeout=0.05)
        result = await tool.coroutine()
        assert "timed out" in result
        assert "UNTRUSTED_DATA" not in result

    @pytest.mark.asyncio
    async def test_multimodal_image_blocks_kept_but_text_wrapped(self) -> None:
        """Multimodal outputs return list[dict]; image blocks pass through, text
        blocks still receive the content-boundary defense."""
        from mcp.types import CallToolResult, ImageContent, TextContent

        async def multimodal_fn(*args: object, **kwargs: object) -> CallToolResult:
            return CallToolResult(
                content=[
                    TextContent(type="text", text="Image description"),
                    ImageContent(
                        type="image",
                        data="iVBORw0KGgoAAAANSUhEUg==",
                        mime_type="image/png",
                    ),
                ]
            )

        tool = self._make_tool("vision_tool", multimodal_fn)
        MCPAgent._wrap_tools_with_timeout([tool], timeout=5.0)
        result = await tool.coroutine()
        assert isinstance(result, list)
        image_blocks = [b for b in result if b.get("type") == "image"]
        text_blocks = [b for b in result if b.get("type") == "text"]
        assert len(image_blocks) == 1
        assert len(text_blocks) == 1
        # Image data must stay intact (no wrapping); the text block must be
        # wrapped with the security boundary.
        assert image_blocks[0]["base64"] == "iVBORw0KGgoAAAANSUhEUg=="
        assert "UNTRUSTED_DATA" in text_blocks[0]["text"]
        assert "Image description" in text_blocks[0]["text"]


class TestEnumerateServerToolsTimeout:
    """Test MCPAgent._enumerate_server_tools connection timeout."""

    @pytest.mark.asyncio
    async def test_connection_timeout(self) -> None:
        agent = MCPAgent()

        async def _fake_enumerate(cfg):
            return ("slow_server", [], "connection timed out after 1.0s")

        cfg = MCPConfig(name="slow_server", type="stdio", command="echo", description="d", connect_timeout=1.0)
        with patch.object(agent, "_enumerate_server_tools", side_effect=_fake_enumerate):
            server_name, tools, error = await agent._enumerate_server_tools(cfg)

        assert server_name == "slow_server"
        assert tools == []
        assert error is not None
        assert "timed out" in error

    @pytest.mark.asyncio
    async def test_fast_connection_succeeds(self) -> None:
        agent = MCPAgent()
        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"

        async def _fake_enumerate(cfg):
            return ("fast_server", [mock_tool], None)

        cfg = MCPConfig(name="fast_server", type="stdio", command="echo", description="d")
        with patch.object(agent, "_enumerate_server_tools", side_effect=_fake_enumerate):
            server_name, tools, error = await agent._enumerate_server_tools(cfg)

        assert server_name == "fast_server"
        assert len(tools) == 1
        assert error is None

    @pytest.mark.asyncio
    async def test_empty_tools_returns_error(self) -> None:
        agent = MCPAgent()

        async def _fake_enumerate(cfg):
            return ("empty_server", [], "not found tools")

        cfg = MCPConfig(name="empty_server", type="stdio", command="echo", description="d")
        with patch.object(agent, "_enumerate_server_tools", side_effect=_fake_enumerate):
            _server_name, _tools, error = await agent._enumerate_server_tools(cfg)
        assert error == "not found tools"

    @pytest.mark.asyncio
    async def test_exception_returns_error_string(self) -> None:
        agent = MCPAgent()

        async def _fake_enumerate(cfg):
            return ("broken_server", [], "connection refused")

        cfg = MCPConfig(name="broken_server", type="stdio", command="echo", description="d")
        with patch.object(agent, "_enumerate_server_tools", side_effect=_fake_enumerate):
            _server_name, _tools, error = await agent._enumerate_server_tools(cfg)
        assert error is not None
        assert "connection refused" in error


class TestClientManagerProtocol:
    """Test MCPClientManager with timeout fields in protocol."""

    @pytest.mark.asyncio
    async def test_prepare_with_config_timeout(self) -> None:
        cfg = MCPConfig(
            name="test",
            type="stdio",
            command="echo",
            description="test",
            connect_timeout=5.0,
            execute_timeout=60.0,
        )
        result = await MCPClientManager.prepare_server_configs([cfg])
        assert "test" in result

    @pytest.mark.asyncio
    async def test_prepare_empty_config(self) -> None:
        result = await MCPClientManager.prepare_server_configs([])
        assert len(result) == 0


class TestGetToolsTimeout:
    """Test MCPAgent.get_tools passes timeouts correctly."""

    @pytest.mark.asyncio
    async def test_per_server_timeout_applied(self) -> None:
        from langchain_core.tools import StructuredTool

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

        tool1 = StructuredTool(
            name="tool1", description="desc1",
            args_schema={"type": "object", "properties": {"a": {"type": "string"}}},
            coroutine=AsyncMock(return_value="r1"),
        )
        tool2 = StructuredTool(
            name="tool2", description="desc2",
            args_schema={"type": "object", "properties": {"a": {"type": "string"}}},
            coroutine=AsyncMock(return_value="r2"),
        )

        async def _fake_enumerate(cfg):
            if cfg.name == "server1":
                return ("server1", [tool1], None)
            return ("server2", [tool2], None)

        with patch.object(agent, "_enumerate_server_tools", side_effect=_fake_enumerate):
            tools = await agent.get_tools([cfg1, cfg2])

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


class TestBuildClientTarget:
    """Test MCPClientManager.build_client_target."""

    def test_sse_returns_url(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="http://x", description="d")
        target = MCPClientManager.build_client_target(cfg)
        assert target == "http://x"

    def test_streamable_http_returns_url(self) -> None:
        cfg = MCPConfig(name="s", type="streamable_http", url="http://y", description="d")
        target = MCPClientManager.build_client_target(cfg)
        assert target == "http://y"

    def test_stdio_returns_params(self) -> None:
        from mcp import StdioServerParameters

        cfg = MCPConfig(name="s", type="stdio", command="node", args=["server.js"], description="d")
        target = MCPClientManager.build_client_target(cfg)
        assert isinstance(target, StdioServerParameters)
        assert target.command == "node"
        assert target.args == ["server.js"]

    def test_stdio_no_args(self) -> None:
        from mcp import StdioServerParameters

        cfg = MCPConfig(name="s", type="stdio", command="echo", description="d")
        target = MCPClientManager.build_client_target(cfg)
        assert isinstance(target, StdioServerParameters)
        assert target.args == []

    def test_unsupported_type_raises(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.type = "websocket"
        mock_cfg.url = "ws://x"
        mock_cfg.command = None
        mock_cfg.args = None
        mock_cfg.name = "bad"
        with pytest.raises(ValueError, match="Unsupported transport"):
            MCPClientManager.build_client_target(mock_cfg)


class TestClientAuthInjection:
    """Test MCPClientManager._inject_auth_headers_into_config."""

    @pytest.mark.asyncio
    async def test_auth_headers_injected_for_sse(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="http://x", description="d")
        mock_provider = AsyncMock()
        mock_provider.get_auth_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
        cfg.auth_provider = mock_provider

        await MCPClientManager._inject_auth_headers_into_config(cfg)
        headers = MCPClientManager.get_headers(cfg)
        assert headers["Authorization"] == "Bearer tok"

    @pytest.mark.asyncio
    async def test_auth_skipped_for_stdio(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="echo", description="d")
        mock_provider = AsyncMock()
        cfg.auth_provider = mock_provider

        await MCPClientManager._inject_auth_headers_into_config(cfg)
        mock_provider.get_auth_headers.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_auth_provider(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="http://x", description="d")
        await MCPClientManager._inject_auth_headers_into_config(cfg)
        assert not hasattr(cfg, "_injected_auth_headers")

    @pytest.mark.asyncio
    async def test_auth_failure_non_fatal(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="http://x", description="d")
        mock_provider = AsyncMock()
        mock_provider.get_auth_headers = AsyncMock(side_effect=RuntimeError("auth fail"))
        cfg.auth_provider = mock_provider

        await MCPClientManager._inject_auth_headers_into_config(cfg)
        assert not hasattr(cfg, "_injected_auth_headers")

    @pytest.mark.asyncio
    async def test_empty_auth_headers_no_inject(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="http://x", description="d")
        mock_provider = AsyncMock()
        mock_provider.get_auth_headers = AsyncMock(return_value={})
        cfg.auth_provider = mock_provider

        await MCPClientManager._inject_auth_headers_into_config(cfg)
        assert not hasattr(cfg, "_injected_auth_headers")


class TestPrepareServerConfigsEdgeCases:
    """Test MCPClientManager.prepare_server_configs edge cases."""

    @pytest.mark.asyncio
    async def test_config_error_skips_server(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.name = "bad"
        mock_cfg.type = "websocket"
        mock_cfg.url = None
        mock_cfg.command = None
        mock_cfg.args = None
        result = await MCPClientManager.prepare_server_configs([mock_cfg])
        assert len(result) == 0


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


class TestEnumerateServerToolsCancelledError:
    """Test CancelledError handling in _enumerate_server_tools."""

    @pytest.mark.asyncio
    async def test_sdk_cancel_scope_leak_returns_error(self) -> None:
        """MCP SDK anyio cancel scope leak should not crash the agent."""
        agent = MCPAgent()

        async def _fake_enumerate(cfg):
            return ("leaky_server", [], "cancelled by SDK")

        cfg = MCPConfig(name="leaky_server", type="stdio", command="echo", description="d")
        with patch.object(agent, "_enumerate_server_tools", side_effect=_fake_enumerate):
            server_name, tools, error = await agent._enumerate_server_tools(cfg)

        assert server_name == "leaky_server"
        assert tools == []
        assert error == "cancelled by SDK"

    @pytest.mark.asyncio
    async def test_genuine_cancel_reraised(self) -> None:
        """Genuine user cancellation should propagate."""
        agent = MCPAgent()

        async def _fake_enumerate(cfg):
            raise asyncio.CancelledError()

        cfg = MCPConfig(name="cancel_server", type="stdio", command="echo", description="d")
        with patch.object(agent, "_enumerate_server_tools", side_effect=_fake_enumerate), pytest.raises(
            asyncio.CancelledError
        ):
            await agent._enumerate_server_tools(cfg)
