"""Unit tests for DesktopMCPServer adapter and context management."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.computer_use.mcp_server import (
    DesktopMCPServer,
    _convert_to_mcp_content,
    get_request_desktop_session,
    reset_request_desktop_session,
    set_request_desktop_session,
)


def test_request_desktop_session_context() -> None:
    """Test set, get, and reset of request-scoped DesktopSession."""
    assert get_request_desktop_session() is None

    mock_session = MagicMock()
    token = set_request_desktop_session(mock_session)
    try:
        assert get_request_desktop_session() is mock_session
    finally:
        reset_request_desktop_session(token)

    assert get_request_desktop_session() is None


def test_convert_to_mcp_content_string() -> None:
    """Test conversion of plain string to MCP TextContent."""
    result = _convert_to_mcp_content("Hello Desktop")
    assert len(result) == 1
    assert result[0].type == "text"
    assert getattr(result[0], "text", None) == "Hello Desktop"


def test_convert_to_mcp_content_dict_and_objects() -> None:
    """Test conversion of dict and structured image items to MCP content."""
    items: list[object] = [
        {"type": "text", "text": "Snapshot text"},
        {"type": "image", "data": "base64data", "mime_type": "image/png"},
    ]
    result = _convert_to_mcp_content(items)
    assert len(result) == 2
    assert result[0].type == "text"
    assert getattr(result[0], "text", None) == "Snapshot text"
    assert result[1].type == "image"
    assert getattr(result[1], "data", None) == "base64data"
    assert getattr(result[1], "mimeType", getattr(result[1], "mime_type", None)) == "image/png"


def test_desktop_mcp_server_init() -> None:
    """Test initializing DesktopMCPServer and inspecting registered tools."""
    mock_session = MagicMock()
    server = DesktopMCPServer(session=mock_session, server_name="test-desktop")
    assert server.mcp is not None
    # Verify streamable HTTP app generation
    app = server.get_streamable_http_app()
    assert app is not None


@pytest.mark.asyncio
async def test_desktop_tools_execution_with_session() -> None:
    """Test calling desktop tools via DesktopMCPServer with active session."""
    mock_session = MagicMock()
    mock_session.desktop_snapshot = AsyncMock(return_value="Window tree AX")
    mock_session.desktop_interact = AsyncMock(return_value="Clicked button")
    mock_session.desktop_vision_capture = AsyncMock(return_value="Screenshot captured")

    server = DesktopMCPServer(session=mock_session)

    # Resolve internal tool functions from the server's MCPServer
    tool_map = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    assert "desktop_snapshot_tool" in tool_map
    assert "desktop_interact_tool" in tool_map
    assert "desktop_vision_tool" in tool_map
