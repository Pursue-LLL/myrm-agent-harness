"""Tests for create_desktop_tools LangChain tool surface."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.computer_use.desktop_agent_tools import create_desktop_tools
from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession


@pytest.fixture
def session() -> DesktopSession:
    backend = MagicMock()
    backend.is_browser_active = AsyncMock(return_value=False)
    config = MagicMock()
    config.screenshot_delay = 0.0
    return DesktopSession(backend=backend, config=config)


def test_create_desktop_tools_returns_four_tools(session: DesktopSession) -> None:
    tools = create_desktop_tools(session)
    names = {tool.name for tool in tools}
    assert names == {
        "desktop_inspect_tool",
        "desktop_snapshot_tool",
        "desktop_interact_tool",
        "desktop_vision_tool",
    }


@pytest.mark.asyncio
async def test_desktop_inspect_tool_delegates(session: DesktopSession) -> None:
    session.desktop_inspect = AsyncMock(return_value="App: Safari")
    tools = create_desktop_tools(session)
    inspect_tool = next(t for t in tools if t.name == "desktop_inspect_tool")
    result = await inspect_tool.ainvoke({})
    assert result == "App: Safari"


@pytest.mark.asyncio
async def test_snapshot_tool_injects_browser_hint_for_string_result(session: DesktopSession) -> None:
    session._backend.is_browser_active = AsyncMock(return_value=True)
    session.desktop_snapshot = AsyncMock(return_value="tree text")
    tools = create_desktop_tools(session)
    snapshot_tool = next(t for t in tools if t.name == "desktop_snapshot_tool")
    result = await snapshot_tool.ainvoke({})
    assert isinstance(result, str)
    assert "Web Browser" in result
    assert result.endswith("tree text")


@pytest.mark.asyncio
async def test_snapshot_tool_injects_browser_hint_for_multimodal_blocks(session: DesktopSession) -> None:
    session._backend.is_browser_active = AsyncMock(return_value=True)
    blocks: list[dict[str, object]] = [
        {"type": "text", "text": "header"},
        {"type": "image", "base64": "abc"},
    ]
    session.desktop_snapshot = AsyncMock(return_value=blocks)
    tools = create_desktop_tools(session)
    snapshot_tool = next(t for t in tools if t.name == "desktop_snapshot_tool")
    result = await snapshot_tool.ainvoke({"include_screenshot": True})
    assert isinstance(result, list)
    assert "Web Browser" in str(result[0]["text"])


@pytest.mark.asyncio
async def test_snapshot_tool_ignores_browser_check_errors(session: DesktopSession) -> None:
    session._backend.is_browser_active = AsyncMock(side_effect=RuntimeError("probe failed"))
    session.desktop_snapshot = AsyncMock(return_value="plain tree")
    tools = create_desktop_tools(session)
    snapshot_tool = next(t for t in tools if t.name == "desktop_snapshot_tool")
    result = await snapshot_tool.ainvoke({})
    assert result == "plain tree"
