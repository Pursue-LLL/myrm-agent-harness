"""Desktop MCP Server Adapter.

Wraps DesktopSession as an MCP server exposing Semantic Desktop Control (SDC)
tools (desktop_snapshot_tool, desktop_interact_tool, desktop_vision_tool)
to external agents (Claude Code, Cursor, Codex, Windsurf, etc.) via the Model Context Protocol.

[INPUT]
- myrm_agent_harness.toolkits.computer_use.desktop_session::DesktopSession (POS: semantic desktop orchestrator with @dref registry)
- myrm_agent_harness.toolkits.computer_use.types (POS: shared computer_use types)
- myrm_agent_harness.toolkits.computer_use.dref.types (POS: snapshot scope types)

[OUTPUT]
- DesktopMCPServer: MCP server adapter exposing desktop tools
- register_desktop_mcp_tools: Helper to attach desktop tools to any MCPServer
- set_request_desktop_session / reset_request_desktop_session / get_request_desktop_session: Request-level scoping

[POS]
MCP server adapter that allows external AI agents (Claude Code, Cursor, Codex)
to control the desktop via standard MCP protocol.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent, TextContent
from starlette.applications import Starlette

from myrm_agent_harness.toolkits.computer_use.dref.types import SnapshotScope
from myrm_agent_harness.toolkits.computer_use.types import (
    DesktopInteractAction,
    DesktopVisionAction,
    ModifierKey,
    ScrollDirection,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession

logger = logging.getLogger(__name__)

_request_desktop_session: ContextVar[DesktopSession | None] = ContextVar(
    "myrm_mcp_request_desktop_session",
    default=None,
)


def set_request_desktop_session(
    session: DesktopSession | None,
) -> Token[DesktopSession | None]:
    """Bind the DesktopSession used by MCP desktop tool handlers for the current request."""
    return _request_desktop_session.set(session)


def reset_request_desktop_session(token: Token[DesktopSession | None]) -> None:
    """Restore the previous DesktopSession binding after a request completes."""
    _request_desktop_session.reset(token)


def get_request_desktop_session() -> DesktopSession | None:
    """Return the active DesktopSession for the current MCP request context."""
    return _request_desktop_session.get()


def _convert_to_mcp_content(result: str | list[object]) -> list[TextContent | ImageContent]:
    """Convert desktop tool return values (strings or multimodal content blocks) to MCP content items."""
    if isinstance(result, str):
        return [TextContent(type="text", text=result)]

    contents: list[TextContent | ImageContent] = []
    for item in result:
        if isinstance(item, dict):
            item_type = str(item.get("type", ""))
            if item_type == "text" or "text" in item:
                contents.append(TextContent(type="text", text=str(item.get("text", ""))))
            elif item_type == "image" or "image" in item or "data" in item:
                img_data = str(item.get("image") or item.get("data") or "")
                mime_type = str(item.get("mime_type") or item.get("mimeType") or "image/jpeg")
                contents.append(ImageContent(type="image", data=img_data, mimeType=mime_type))
            else:
                contents.append(TextContent(type="text", text=str(item)))
        elif hasattr(item, "text"):
            contents.append(TextContent(type="text", text=str(getattr(item, "text", ""))))
        elif hasattr(item, "image") or hasattr(item, "screenshot_base64"):
            img_data = str(getattr(item, "image", getattr(item, "screenshot_base64", "")))
            mime_type = str(getattr(item, "mime_type", "image/jpeg"))
            contents.append(ImageContent(type="image", data=img_data, mimeType=mime_type))
        else:
            contents.append(TextContent(type="text", text=str(item)))
    return contents


def register_desktop_mcp_tools(
    mcp: MCPServer,
    session_resolver: Callable[[], DesktopSession | None],
) -> None:
    """Register desktop control tools on an existing MCPServer instance.

    Args:
        mcp: The MCPServer on which to register desktop tools.
        session_resolver: Callable returning the DesktopSession for the current request context.
    """

    @mcp.tool(
        name="desktop_snapshot_tool",
        description=(
            "Capture the active desktop accessibility (AX) tree with @dref element IDs.\n\n"
            "Required workflow: Always call desktop_snapshot_tool first to obtain current @dref "
            "element references, then call desktop_interact_tool(ref=@dref, action=...) to act on elements.\n"
            "Use scope='foreground' (default) for active window, or scope='target' with app_name to inspect "
            "background apps. Use desktop_vision_tool only when the AX tree is empty or semantic interact fails."
        ),
    )
    async def desktop_snapshot(
        scope: SnapshotScope = "foreground",
        app_name: str = "",
        include_screenshot: bool = False,
    ) -> list[TextContent | ImageContent]:
        session = session_resolver()
        if session is None:
            return [
                TextContent(
                    type="text",
                    text="Error: Desktop control session is unavailable in the current context.",
                )
            ]
        raw_result = await session.desktop_snapshot(
            scope=scope,
            app_name=app_name or None,
            include_screenshot=include_screenshot,
        )
        return _convert_to_mcp_content(raw_result)

    @mcp.tool(
        name="desktop_interact_tool",
        description=(
            "Perform a semantic action on a desktop element identified by @dref from desktop_snapshot_tool.\n\n"
            "Always call desktop_snapshot_tool first to obtain current @drefs, then call this tool with the valid ref.\n"
            "Actions: 'click', 'dblclick', 'set_value' (atomic text replace), 'fill', 'type', 'press' (e.g. Return/Escape), "
            "'hover', 'focus', 'scroll'."
        ),
    )
    async def desktop_interact(
        ref: str,
        action: DesktopInteractAction,
        text: str = "",
        modifiers: list[ModifierKey] | None = None,
    ) -> list[TextContent | ImageContent]:
        session = session_resolver()
        if session is None:
            return [
                TextContent(
                    type="text",
                    text="Error: Desktop control session is unavailable in the current context.",
                )
            ]
        raw_result = await session.desktop_interact(
            ref=ref,
            action=action,
            text=text,
            modifiers=modifiers,
        )
        return _convert_to_mcp_content(raw_result)

    @mcp.tool(
        name="desktop_vision_tool",
        description=(
            "Coordinate-based visual desktop automation and screen capture fallback.\n\n"
            "Actions: 'capture' (take screenshot), 'left_click', 'right_click', 'double_click', 'triple_click', "
            "'middle_click', 'mouse_move', 'type', 'key', 'drag', 'scroll', 'wait'. Use only when the accessibility tree "
            "is empty or when canvas/custom-rendered elements cannot be controlled semantically via desktop_interact_tool."
        ),
    )
    async def desktop_vision(
        action: DesktopVisionAction = "capture",
        coordinate: list[int] | None = None,
        text: str = "",
        scroll_direction: ScrollDirection | None = None,
        scroll_amount: int = 3,
        start_coordinate: list[int] | None = None,
        duration: float = 2.0,
        modifiers: list[ModifierKey] | None = None,
    ) -> list[TextContent | ImageContent]:
        session = session_resolver()
        if session is None:
            return [
                TextContent(
                    type="text",
                    text="Error: Desktop control session is unavailable in the current context.",
                )
            ]
        if action == "capture":
            raw_result = await session.desktop_vision_capture()
        else:
            raw_result = await session.desktop_vision_action(
                action=action,
                coordinate=coordinate,
                text=text or None,
                scroll_direction=scroll_direction,
                scroll_amount=scroll_amount,
                start_coordinate=start_coordinate,
                duration=duration,
                modifiers=modifiers,
            )
        return _convert_to_mcp_content(raw_result)


class DesktopMCPServer:
    """Standalone MCP server adapter exposing desktop control tools."""

    def __init__(
        self,
        session: DesktopSession | None = None,
        *,
        server_name: str = "myrm-desktop",
        session_resolver: Callable[[], DesktopSession | None] | None = None,
        stateless_http: bool = False,
    ) -> None:
        self._default_session = session
        self._session_resolver = session_resolver
        self._stateless_http = stateless_http
        self._mcp = MCPServer(
            server_name,
            instructions=(
                "Desktop automation service for inspecting and controlling the native desktop UI. "
                "Use desktop_snapshot_tool to obtain the accessibility tree with @dref element references. "
                "Use desktop_interact_tool to click or type into elements using @dref references. "
                "Use desktop_vision_tool for screenshot capture and coordinate-based visual actions."
            ),
        )
        register_desktop_mcp_tools(self._mcp, self._resolve_session)

    def _resolve_session(self) -> DesktopSession | None:
        bound = _request_desktop_session.get()
        if bound is not None:
            return bound
        if self._session_resolver is not None:
            return self._session_resolver()
        return self._default_session

    @property
    def mcp(self) -> MCPServer:
        """Access the underlying MCPServer instance."""
        return self._mcp

    def get_streamable_http_app(self) -> Starlette:
        """Get a Starlette ASGI app for Streamable HTTP transport."""
        return self._mcp.streamable_http_app(stateless_http=self._stateless_http)


__all__ = [
    "DesktopMCPServer",
    "get_request_desktop_session",
    "register_desktop_mcp_tools",
    "reset_request_desktop_session",
    "set_request_desktop_session",
]
