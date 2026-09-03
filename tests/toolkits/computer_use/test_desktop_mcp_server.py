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
    assert (
        getattr(result[1], "mimeType", getattr(result[1], "mime_type", None))
        == "image/png"
    )


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
    mock_session.desktop_vision_action = AsyncMock(return_value="Left clicked")

    server = DesktopMCPServer(session=mock_session)

    tool_map = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    assert "desktop_snapshot_tool" in tool_map
    assert "desktop_interact_tool" in tool_map
    assert "desktop_vision_tool" in tool_map

    # Test invoking snapshot tool
    snapshot_res = await server.mcp.call_tool(
        "desktop_snapshot_tool", {"scope": "foreground"}
    )
    assert len(snapshot_res.content) == 1
    assert snapshot_res.content[0].type == "text"
    assert getattr(snapshot_res.content[0], "text", None) == "Window tree AX"
    mock_session.desktop_snapshot.assert_awaited_once_with(
        scope="foreground", app_name=None, include_screenshot=False
    )

    # Test invoking interact tool
    interact_res = await server.mcp.call_tool(
        "desktop_interact_tool", {"ref": "@d1", "action": "click"}
    )
    assert len(interact_res.content) == 1
    assert getattr(interact_res.content[0], "text", None) == "Clicked button"
    mock_session.desktop_interact.assert_awaited_once_with(
        ref="@d1", action="click", text="", modifiers=None
    )

    # Test invoking vision tool (capture)
    vision_cap_res = await server.mcp.call_tool(
        "desktop_vision_tool", {"action": "capture"}
    )
    assert len(vision_cap_res.content) == 1
    assert getattr(vision_cap_res.content[0], "text", None) == "Screenshot captured"
    mock_session.desktop_vision_capture.assert_awaited_once()

    # Test invoking vision tool (action)
    vision_act_res = await server.mcp.call_tool(
        "desktop_vision_tool", {"action": "left_click", "coordinate": [100, 200]}
    )
    assert len(vision_act_res.content) == 1
    assert getattr(vision_act_res.content[0], "text", None) == "Left clicked"
    mock_session.desktop_vision_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_desktop_tools_execution_without_session() -> None:
    """Test calling desktop tools when no session is bound returns descriptive error."""
    server = DesktopMCPServer(session=None)

    snapshot_res = await server.mcp.call_tool("desktop_snapshot_tool", {})
    assert len(snapshot_res.content) == 1
    assert "Error: Desktop control session is unavailable" in getattr(
        snapshot_res.content[0], "text", ""
    )

    interact_res = await server.mcp.call_tool(
        "desktop_interact_tool", {"ref": "@d1", "action": "click"}
    )
    assert len(interact_res.content) == 1
    assert "Error: Desktop control session is unavailable" in getattr(
        interact_res.content[0], "text", ""
    )

    vision_res = await server.mcp.call_tool(
        "desktop_vision_tool", {"action": "capture"}
    )
    assert len(vision_res.content) == 1
    assert "Error: Desktop control session is unavailable" in getattr(
        vision_res.content[0], "text", ""
    )


def test_convert_to_mcp_content_object_fallbacks() -> None:
    """Test _convert_to_mcp_content fallback branches."""

    class TextObj:
        text = "obj text"

    class ImgObj:
        screenshot_base64 = "img_b64"
        mime_type = "image/webp"

    class UnknownObj:
        def __str__(self) -> str:
            return "unknown str"

    items = [TextObj(), ImgObj(), UnknownObj(), {"type": "other", "raw": 123}]
    res = _convert_to_mcp_content(items)
    assert len(res) == 4
    assert res[0].type == "text"
    assert getattr(res[0], "text", None) == "obj text"
    assert res[1].type == "image"
    assert getattr(res[1], "data", None) == "img_b64"
    assert res[2].type == "text"
    assert getattr(res[2], "text", None) == "unknown str"
    assert res[3].type == "text"


def test_session_resolver_callable() -> None:
    """Test session_resolver callback parameter of DesktopMCPServer."""
    mock_session = MagicMock()
    server = DesktopMCPServer(session_resolver=lambda: mock_session)
    assert server._resolve_session() is mock_session

    # Test bound context var precedence
    token = set_request_desktop_session(mock_session)
    try:
        server_default = DesktopMCPServer(session=None)
        assert server_default._resolve_session() is mock_session
    finally:
        reset_request_desktop_session(token)


@pytest.mark.asyncio
async def test_desktop_tools_execution_with_session() -> None:
    """Test calling all desktop tools when session is present passes arguments accurately."""
    mock_session = MagicMock()
    mock_session.desktop_snapshot = AsyncMock(return_value="Snapshot result")
    mock_session.desktop_interact = AsyncMock(return_value="Interact result")
    mock_session.desktop_vision_capture = AsyncMock(return_value="Capture result")
    mock_session.desktop_vision_action = AsyncMock(return_value="Action result")

    server = DesktopMCPServer(session=mock_session)

    # 1. Snapshot tool
    res_snap = await server.mcp.call_tool("desktop_snapshot_tool", {"scope": "target", "app_name": "Finder"})
    assert getattr(res_snap.content[0], "text", None) == "Snapshot result"
    mock_session.desktop_snapshot.assert_awaited_once_with(scope="target", app_name="Finder", include_screenshot=False)

    # 2. Interact tool (ModifierKey literal allows 'ctrl', 'shift', 'alt', 'meta')
    res_int = await server.mcp.call_tool(
        "desktop_interact_tool",
        {"ref": "@dref_button", "action": "click", "text": "Submit", "modifiers": ["meta"]},
    )
    assert getattr(res_int.content[0], "text", None) == "Interact result"
    mock_session.desktop_interact.assert_awaited_once_with(
        ref="@dref_button", action="click", text="Submit", modifiers=["meta"]
    )

    # 3. Vision capture tool
    res_vis_cap = await server.mcp.call_tool("desktop_vision_tool", {"action": "capture"})
    assert getattr(res_vis_cap.content[0], "text", None) == "Capture result"
    mock_session.desktop_vision_capture.assert_awaited_once()

    # 4. Vision action tool (e.g., left_click)
    res_vis_act = await server.mcp.call_tool(
        "desktop_vision_tool",
        {"action": "left_click", "coordinate": [200, 300], "duration": 1.5},
    )
    assert getattr(res_vis_act.content[0], "text", None) == "Action result"
    mock_session.desktop_vision_action.assert_awaited_once_with(
        action="left_click",
        coordinate=[200, 300],
        text=None,
        scroll_direction=None,
        scroll_amount=3,
        start_coordinate=None,
        duration=1.5,
        modifiers=None,
    )
