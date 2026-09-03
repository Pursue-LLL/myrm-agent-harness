"""Unit tests for computer_use/mcp_server — Desktop MCP server adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent, TextContent

from myrm_agent_harness.toolkits.computer_use.mcp_server import (
    DesktopMCPServer,
    _convert_to_mcp_content,
    get_request_desktop_session,
    register_desktop_mcp_tools,
    reset_request_desktop_session,
    set_request_desktop_session,
)


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    session.desktop_snapshot = AsyncMock(return_value="[AXTree foreground] 5 refs")
    session.desktop_interact = AsyncMock(return_value="Clicked element @d1")
    session.desktop_vision_capture = AsyncMock(return_value="Capture success")
    session.desktop_vision_action = AsyncMock(return_value="Left clicked at [100, 200]")
    return session


class TestConvertToMcpContent:
    def test_string_conversion(self) -> None:
        contents = _convert_to_mcp_content("simple text")
        assert len(contents) == 1
        assert isinstance(contents[0], TextContent)
        assert contents[0].text == "simple text"

    def test_dict_blocks_conversion(self) -> None:
        blocks = [
            {"type": "text", "text": "tree output"},
            {"type": "image", "image": "base64data", "mime_type": "image/jpeg"},
            {"other": "raw object"},
        ]
        contents = _convert_to_mcp_content(blocks)
        assert len(contents) == 3
        assert isinstance(contents[0], TextContent)
        assert contents[0].text == "tree output"
        assert isinstance(contents[1], ImageContent)
        assert contents[1].data == "base64data"
        assert contents[1].mime_type == "image/jpeg"
        assert isinstance(contents[2], TextContent)

    def test_object_blocks_conversion(self) -> None:
        text_obj = MagicMock(spec=["text"])
        text_obj.text = "object text"
        image_obj = MagicMock(spec=["image", "mime_type"])
        image_obj.image = "imgbase64"
        image_obj.mime_type = "image/png"
        generic_obj = 12345

        contents = _convert_to_mcp_content([text_obj, image_obj, generic_obj])
        assert len(contents) == 3
        assert isinstance(contents[0], TextContent)
        assert contents[0].text == "object text"
        assert isinstance(contents[1], ImageContent)
        assert contents[1].data == "imgbase64"
        assert contents[1].mime_type == "image/png"
        assert isinstance(contents[2], TextContent)
        assert contents[2].text == "12345"


class TestRegisterDesktopMcpTools:
    @pytest.mark.asyncio
    async def test_tools_registered_on_server(self, mock_session: MagicMock) -> None:
        server = MCPServer("test-server")
        register_desktop_mcp_tools(server, lambda: mock_session)
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert "desktop_snapshot_tool" in names
        assert "desktop_interact_tool" in names
        assert "desktop_vision_tool" in names

    @pytest.mark.asyncio
    async def test_call_desktop_snapshot(self, mock_session: MagicMock) -> None:
        server = MCPServer("test-server")
        register_desktop_mcp_tools(server, lambda: mock_session)
        tool = server._tool_manager.get_tool("desktop_snapshot_tool")
        assert tool is not None

        result = await tool.run({"scope": "foreground", "include_screenshot": False}, None, convert_result=True)
        assert result.content[0].text == "[AXTree foreground] 5 refs"
        mock_session.desktop_snapshot.assert_awaited_once_with(
            scope="foreground",
            app_name=None,
            include_screenshot=False,
        )

    @pytest.mark.asyncio
    async def test_call_desktop_snapshot_none_session(self) -> None:
        server = MCPServer("test-server")
        register_desktop_mcp_tools(server, lambda: None)
        tool = server._tool_manager.get_tool("desktop_snapshot_tool")
        assert tool is not None

        result = await tool.run({}, None, convert_result=True)
        assert "unavailable" in result.content[0].text

    @pytest.mark.asyncio
    async def test_call_desktop_interact(self, mock_session: MagicMock) -> None:
        server = MCPServer("test-server")
        register_desktop_mcp_tools(server, lambda: mock_session)
        tool = server._tool_manager.get_tool("desktop_interact_tool")
        assert tool is not None

        result = await tool.run({"ref": "d1", "action": "click", "text": ""}, None, convert_result=True)
        assert result.content[0].text == "Clicked element @d1"
        mock_session.desktop_interact.assert_awaited_once_with(
            ref="d1",
            action="click",
            text="",
            modifiers=None,
        )

    @pytest.mark.asyncio
    async def test_call_desktop_interact_none_session(self) -> None:
        server = MCPServer("test-server")
        register_desktop_mcp_tools(server, lambda: None)
        tool = server._tool_manager.get_tool("desktop_interact_tool")
        assert tool is not None

        result = await tool.run({"ref": "d1", "action": "click"}, None, convert_result=True)
        assert "unavailable" in result.content[0].text

    @pytest.mark.asyncio
    async def test_call_desktop_vision_capture(self, mock_session: MagicMock) -> None:
        server = MCPServer("test-server")
        register_desktop_mcp_tools(server, lambda: mock_session)
        tool = server._tool_manager.get_tool("desktop_vision_tool")
        assert tool is not None

        result = await tool.run({"action": "capture"}, None, convert_result=True)
        assert result.content[0].text == "Capture success"
        mock_session.desktop_vision_capture.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_call_desktop_vision_action(self, mock_session: MagicMock) -> None:
        server = MCPServer("test-server")
        register_desktop_mcp_tools(server, lambda: mock_session)
        tool = server._tool_manager.get_tool("desktop_vision_tool")
        assert tool is not None

        result = await tool.run(
            {"action": "left_click", "coordinate": [100, 200]},
            None,
            convert_result=True,
        )
        assert result.content[0].text == "Left clicked at [100, 200]"
        mock_session.desktop_vision_action.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_call_desktop_vision_none_session(self) -> None:
        server = MCPServer("test-server")
        register_desktop_mcp_tools(server, lambda: None)
        tool = server._tool_manager.get_tool("desktop_vision_tool")
        assert tool is not None

        result = await tool.run({"action": "capture"}, None, convert_result=True)
        assert "unavailable" in result.content[0].text


class TestDesktopMCPServer:
    @pytest.mark.asyncio
    async def test_standalone_server_with_session(self, mock_session: MagicMock) -> None:
        server = DesktopMCPServer(mock_session)
        assert server.mcp.name == "myrm-desktop"
        tools = await server.mcp.list_tools()
        assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_standalone_server_with_resolver(self, mock_session: MagicMock) -> None:
        server = DesktopMCPServer(session_resolver=lambda: mock_session)
        assert server._resolve_session() is mock_session

    def test_request_desktop_session_contextvar(self, mock_session: MagicMock) -> None:
        assert get_request_desktop_session() is None
        token = set_request_desktop_session(mock_session)
        try:
            assert get_request_desktop_session() is mock_session
        finally:
            reset_request_desktop_session(token)
        assert get_request_desktop_session() is None

    def test_get_streamable_http_app(self, mock_session: MagicMock) -> None:
        server = DesktopMCPServer(mock_session, stateless_http=True)
        app = server.get_streamable_http_app()
        assert app is not None
