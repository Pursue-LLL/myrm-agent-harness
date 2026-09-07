"""Tests for create_desktop_tools LangChain tool surface."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.computer_use.desktop_agent_tools import (
    create_desktop_tools,
)
from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession


@pytest.fixture
def session() -> DesktopSession:
    backend = MagicMock()
    backend.is_browser_active = AsyncMock(return_value=False)
    config = MagicMock()
    config.screenshot_delay = 0.0
    return DesktopSession(backend=backend, config=config)


def test_create_desktop_tools_returns_three_tools(session: DesktopSession) -> None:
    tools = create_desktop_tools(session)
    names = {tool.name for tool in tools}
    assert names == {
        "desktop_snapshot_tool",
        "desktop_interact_tool",
        "desktop_vision_tool",
    }


@pytest.mark.asyncio
async def test_snapshot_tool_injects_browser_hint_for_string_result(
    session: DesktopSession,
) -> None:
    session._backend.is_browser_active = AsyncMock(return_value=True)
    session.desktop_snapshot = AsyncMock(return_value="tree text")
    tools = create_desktop_tools(session)
    snapshot_tool = next(t for t in tools if t.name == "desktop_snapshot_tool")
    result = await snapshot_tool.ainvoke({})
    assert isinstance(result, str)
    assert "Web Browser" in result
    assert result.endswith("tree text")


@pytest.mark.asyncio
async def test_snapshot_tool_injects_browser_hint_for_multimodal_blocks(
    session: DesktopSession,
) -> None:
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
async def test_snapshot_tool_ignores_browser_check_errors(
    session: DesktopSession,
) -> None:
    session._backend.is_browser_active = AsyncMock(
        side_effect=RuntimeError("probe failed")
    )
    session.desktop_snapshot = AsyncMock(return_value="plain tree")
    tools = create_desktop_tools(session)
    snapshot_tool = next(t for t in tools if t.name == "desktop_snapshot_tool")
    result = await snapshot_tool.ainvoke({})
    assert result == "plain tree"


@pytest.mark.asyncio
async def test_snapshot_tool_forwards_target_scope_and_app_name(
    session: DesktopSession,
) -> None:
    session._backend.is_browser_active = AsyncMock(return_value=False)
    session.desktop_snapshot = AsyncMock(return_value="tree text")
    tools = create_desktop_tools(session)
    snapshot_tool = next(t for t in tools if t.name == "desktop_snapshot_tool")
    result = await snapshot_tool.ainvoke({"scope": "target", "app_name": "Mail"})
    assert result == "tree text"
    session.desktop_snapshot.assert_awaited_once_with(
        scope="target",
        app_name="Mail",
        include_screenshot=False,
        query=None,
        role=None,
        wait_seconds=0.0,
    )


@pytest.mark.asyncio
async def test_snapshot_tool_forwards_query_role_and_wait_seconds(
    session: DesktopSession,
) -> None:
    session._backend.is_browser_active = AsyncMock(return_value=False)
    session.desktop_snapshot = AsyncMock(return_value="filtered tree")
    tools = create_desktop_tools(session)
    snapshot_tool = next(t for t in tools if t.name == "desktop_snapshot_tool")
    result = await snapshot_tool.ainvoke({
        "scope": "foreground",
        "query": "Settings",
        "role": "button",
        "wait_seconds": 2.5,
    })
    assert result == "filtered tree"
    session.desktop_snapshot.assert_awaited_once_with(
        scope="foreground",
        app_name=None,
        include_screenshot=False,
        query="Settings",
        role="button",
        wait_seconds=2.5,
    )


@pytest.mark.asyncio
async def test_interact_tool_forwards_wait_seconds(
    session: DesktopSession,
) -> None:
    session.desktop_interact = AsyncMock(return_value="Action 'click' succeeded")
    tools = create_desktop_tools(session)
    interact_tool = next(t for t in tools if t.name == "desktop_interact_tool")
    result = await interact_tool.ainvoke({
        "ref": "d3",
        "action": "click",
        "wait_seconds": 3.0,
    })
    assert result == "Action 'click' succeeded"
    session.desktop_interact.assert_awaited_once_with(
        ref="d3",
        action="click",
        text="",
        modifiers=None,
        wait_seconds=3.0,
    )


@pytest.mark.asyncio
async def test_interact_tool_supports_new_pattern_actions(
    session: DesktopSession,
) -> None:
    session.desktop_interact = AsyncMock(return_value="Action 'expand' succeeded")
    tools = create_desktop_tools(session)
    interact_tool = next(t for t in tools if t.name == "desktop_interact_tool")
    for action_name in ["toggle", "expand", "collapse", "invoke", "check", "uncheck"]:
        session.desktop_interact.reset_mock()
        result = await interact_tool.ainvoke({
            "ref": "d5",
            "action": action_name,
        })
        assert result == "Action 'expand' succeeded"
        session.desktop_interact.assert_awaited_once_with(
            ref="d5",
            action=action_name,
            text="",
            modifiers=None,
            wait_seconds=0.0,
        )
